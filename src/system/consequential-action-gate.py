#!/usr/bin/env python3
"""Stateful, fail-closed authorization for consequential Hermes actions.

The gate does not execute payments, messages, deployments, purchases, or legal
acts. It decides whether one exact requested action is currently authorized and
emits a create-only authorization receipt. Existing authorization receipts are
the durable budget/duplicate ledger, so a restart cannot reset cumulative spend.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
REQUEST_SCHEMA = "hermes-consequential-action-v1"
GRANT_SCHEMA = "hermes-authority-grant-v1"
RECEIPT_SCHEMA = "hermes-action-authorization-receipt-v1"


class GateError(ValueError):
    pass


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError(f"cannot load required module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


approval_security = _load_module("hermes_consequential_approval_security", HERE / "approval-security.py")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _ts(value: datetime | None = None) -> str:
    return _now(value).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GateError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not ID_RE.fullmatch(text):
        raise GateError(f"invalid {label}")
    return text


def _require_schema(value: Mapping[str, Any], schema: str, label: str) -> None:
    if value.get("schema_version") != schema:
        raise GateError(f"{label} schema mismatch")


def _as_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GateError(f"invalid {label}") from exc
    if number < 0:
        raise GateError(f"{label} cannot be negative")
    return number


def _sealed(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body.pop("content_hash", None)
    body["content_hash"] = digest(body)
    return body


def _create_only(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_sealed(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ConsequentialActionGate:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.receipts_dir = self.root / "authorization-receipts"
        self.lock_path = self.root / ".authorization.lock"

    def _receipt_path(self, action_id: str) -> Path:
        return self.receipts_dir / f"{_require_id(action_id, 'action id')}.json"

    def _existing_receipts(self) -> list[dict[str, Any]]:
        if not self.receipts_dir.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(self.receipts_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise GateError("unsafe authorization receipt encountered")
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GateError(f"authorization ledger unreadable: {exc}") from exc
            if not isinstance(raw, dict) or raw.get("schema_version") != RECEIPT_SCHEMA:
                raise GateError("authorization ledger contains invalid receipt")
            expected = raw.get("content_hash")
            body = {k: v for k, v in raw.items() if k != "content_hash"}
            if expected != digest(body):
                raise GateError("authorization receipt content hash mismatch")
            rows.append(raw)
        return rows

    @staticmethod
    def _identity_evidence(request: Mapping[str, Any], events: Iterable[Mapping[str, Any]], ttl_seconds: int, now: datetime) -> str:
        if ttl_seconds <= 0:
            raise GateError("identity ttl must be positive")
        matches: list[tuple[datetime, str]] = []
        for event in events:
            if event.get("event_type") != "identity_verified":
                continue
            if event.get("principal") != request.get("principal") or event.get("actor") != request.get("actor"):
                continue
            when = _parse_ts(event.get("verified_at"), "identity timestamp")
            age = (now - when).total_seconds()
            if 0 <= age <= ttl_seconds:
                evidence_id = str(event.get("evidence_id") or "").strip()
                if evidence_id:
                    matches.append((when, evidence_id))
        if not matches:
            raise GateError("identity prerequisite missing_or_stale")
        matches.sort(reverse=True)
        return matches[0][1]

    @staticmethod
    def _required_evidence(request: Mapping[str, Any], grant: Mapping[str, Any]) -> list[str]:
        refs = request.get("evidence_refs")
        if not isinstance(refs, list):
            raise GateError("evidence_refs must be a list")
        observed = {
            str(item.get("type"))
            for item in refs
            if isinstance(item, Mapping) and str(item.get("type") or "").strip() and str(item.get("ref") or "").strip()
        }
        required = {str(x) for x in grant.get("required_evidence_types", [])}
        missing = sorted(required - observed)
        if missing:
            raise GateError("required evidence missing: " + ",".join(missing))
        return sorted(observed)

    @staticmethod
    def _verify_approval(request: Mapping[str, Any], approval: Mapping[str, Any] | None, now: datetime) -> str:
        if not isinstance(approval, Mapping):
            raise GateError("authenticated approval required")
        try:
            approval_security.verify_receipt(dict(approval))
        except approval_security.ApprovalSecurityError as exc:
            raise GateError(f"approval_authentication_failed:{exc}") from exc
        expires = _parse_ts(approval.get("expires_at"), "approval expiry")
        approved_at = _parse_ts(approval.get("approved_at"), "approval time")
        if expires <= now or approved_at > now:
            raise GateError("approval expired_or_not_yet_valid")
        exact = {
            "action_id": request.get("action_id"),
            "action": request.get("action_type"),
            "principal": request.get("principal"),
            "actor": request.get("actor"),
            "counterparty": request.get("counterparty"),
            "destination": request.get("destination"),
        }
        for key, expected in exact.items():
            if approval.get(key) != expected:
                raise GateError(f"approval_binding_mismatch:{key}")
        if abs(_as_float(approval.get("amount"), "approval amount") - _as_float(request.get("amount"), "request amount")) > 1e-9:
            raise GateError("approval_binding_mismatch:amount")
        return str(approval.get("approval_id") or "")

    def authorize(
        self,
        request: Mapping[str, Any],
        grant: Mapping[str, Any],
        prior_events: Iterable[Mapping[str, Any]],
        approval_receipt: Mapping[str, Any] | None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request = dict(request)
        grant = dict(grant)
        _require_schema(request, REQUEST_SCHEMA, "request")
        _require_schema(grant, GRANT_SCHEMA, "grant")
        action_id = _require_id(request.get("action_id"), "action id")
        grant_id = _require_id(grant.get("grant_id"), "grant id")
        current = _now(now)
        if request.get("principal") != grant.get("principal") or request.get("actor") != grant.get("actor"):
            raise GateError("principal_or_actor_outside_grant")
        if _parse_ts(grant.get("expires_at"), "grant expiry") <= current:
            raise GateError("authority grant expired")
        action = str(request.get("action_type") or "")
        tool = str(request.get("tool") or "")
        destination = str(request.get("destination") or "")
        counterparty = str(request.get("counterparty") or "")
        if action not in set(map(str, grant.get("allowed_actions", []))):
            raise GateError("action outside authority scope")
        if tool not in set(map(str, grant.get("allowed_tools", []))):
            raise GateError("tool outside authority scope")
        if destination not in set(map(str, grant.get("allowed_destinations", []))):
            raise GateError("destination outside authority scope")
        if counterparty not in set(map(str, grant.get("allowed_counterparties", []))):
            raise GateError("counterparty outside authority scope")
        amount = _as_float(request.get("amount", 0), "request amount")
        max_single = _as_float(grant.get("max_single_amount", 0), "single action limit")
        cumulative_budget = _as_float(grant.get("cumulative_budget", 0), "cumulative budget")
        if amount > max_single:
            raise GateError("single action limit exceeded")
        identity_evidence_id = self._identity_evidence(
            request, prior_events, int(grant.get("identity_ttl_seconds", 0)), current
        )
        evidence_types = self._required_evidence(request, grant)
        approval_id = ""
        if action in set(map(str, grant.get("approval_required_actions", []))):
            approval_id = self._verify_approval(request, approval_receipt, current)

        with _locked(self.lock_path):
            receipts = self._existing_receipts()
            if any(row.get("action_id") == action_id for row in receipts):
                raise GateError("action already authorized")
            spent = sum(
                float(row.get("amount", 0))
                for row in receipts
                if row.get("grant_id") == grant_id and row.get("decision") == "ALLOW"
            )
            if spent + amount > cumulative_budget + 1e-9:
                raise GateError("cumulative budget exceeded")
            remaining = round(cumulative_budget - spent - amount, 8)
            payload = {
                "schema_version": RECEIPT_SCHEMA,
                "decision": "ALLOW",
                "authorization_id": "auth_" + hashlib.sha256(f"{grant_id}:{action_id}".encode()).hexdigest()[:24],
                "action_id": action_id,
                "grant_id": grant_id,
                "principal": request.get("principal"),
                "actor": request.get("actor"),
                "action_type": action,
                "purpose": str(request.get("purpose") or ""),
                "tool": tool,
                "destination": destination,
                "counterparty": counterparty,
                "amount": amount,
                "risk_class": str(request.get("risk_class") or ""),
                "identity_evidence_id": identity_evidence_id,
                "approval_id": approval_id,
                "evidence_types": evidence_types,
                "spent_before": round(spent, 8),
                "remaining_budget_after": remaining,
                "authorized_at": _ts(current),
                "request_hash": digest(request),
                "grant_hash": digest(grant),
            }
            path = self._receipt_path(action_id)
            _create_only(path, payload)
            result = json.loads(path.read_text(encoding="utf-8"))
            return result
