#!/usr/bin/env python3
"""Durable Hermes-Relay completion evidence for the shared task reconciler."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from background_task_reconciler import ProviderInspection
from hermes_relay_adapter import (
    COMPLETION_SCHEMA,
    RelayCompletionReceipt,
    canonical_digest,
    redact_sensitive,
)

STATE_SCHEMA = "hermes-relay-receipt-state-v1"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RelayReceiptError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RelayReceiptStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @classmethod
    def default(cls) -> "RelayReceiptStore":
        return cls(os.environ.get("HERMES_RELAY_RECEIPT_STATE_DIR", ".hermes/state/relay-receipts"))

    @staticmethod
    def _handle(provider_task_id: str) -> str:
        value = str(provider_task_id or "").strip()
        if not value or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise RelayReceiptError("invalid Relay provider task id")
        return value

    def path_for(self, provider_task_id: str) -> Path:
        handle = self._handle(provider_task_id)
        name = hashlib.sha256(handle.encode("utf-8")).hexdigest() + ".json"
        return self.root / name

    @staticmethod
    def _seal(row: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(row)
        body.pop("content_hash", None)
        body["content_hash"] = canonical_digest(body)
        return body

    @staticmethod
    def _verify(raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        expected = value.pop("content_hash", "")
        if value.get("schema_version") != STATE_SCHEMA:
            raise RelayReceiptError("Relay receipt state schema mismatch")
        if expected != canonical_digest(value):
            raise RelayReceiptError("Relay receipt state content hash mismatch")
        value["content_hash"] = expected
        return value

    def _write(self, provider_task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        path = self.path_for(provider_task_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        sealed = self._seal(row)
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(sealed, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        return self.load(provider_task_id)

    def register(
        self,
        provider_task_id: str,
        *,
        task_id: str,
        target_device_id: str,
        operation: str,
        request_id: str,
        authorization_id: str,
    ) -> dict[str, Any]:
        handle = self._handle(provider_task_id)
        expectation = {
            "task_id": str(task_id),
            "target_device_id": str(target_device_id),
            "operation": str(operation),
            "request_id": str(request_id),
            "authorization_id": str(authorization_id),
        }
        if any(not value for value in expectation.values()):
            raise RelayReceiptError("Relay receipt expectation fields are required")
        path = self.path_for(handle)
        if path.exists():
            existing = self.load(handle)
            if existing.get("expectation") != expectation:
                raise RelayReceiptError("Relay provider task already has a different expectation")
            return existing
        return self._write(handle, {
            "schema_version": STATE_SCHEMA,
            "provider_task_id": handle,
            "expectation": expectation,
            "receipt": None,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        })

    def record_completion(self, provider_task_id: str, receipt: RelayCompletionReceipt) -> dict[str, Any]:
        row = self.load(provider_task_id)
        value = receipt.to_dict()
        if value.get("schema_version") != COMPLETION_SCHEMA:
            raise RelayReceiptError("Relay completion receipt schema mismatch")
        previous = row.get("receipt")
        if previous is not None and previous != value:
            raise RelayReceiptError("Relay completion receipt already recorded differently")
        row["receipt"] = value
        row["updated_at"] = _utc_now()
        return self._write(provider_task_id, row)

    def load(self, provider_task_id: str) -> dict[str, Any]:
        path = self.path_for(provider_task_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RelayReceiptError(f"cannot load Relay receipt state: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise RelayReceiptError("Relay receipt state must be an object")
        row = self._verify(raw)
        if row.get("provider_task_id") != self._handle(provider_task_id):
            raise RelayReceiptError("Relay receipt handle mismatch")
        return row


class RelayTaskInspector:
    def __init__(
        self,
        store: RelayReceiptStore,
        *,
        session_validator: Callable[[str], bool] | None = None,
    ):
        self.store = store
        self.session_validator = session_validator

    async def inspect(self, provider_task_id: str) -> ProviderInspection:
        if self.session_validator is not None and not bool(self.session_validator(provider_task_id)):
            return ProviderInspection(
                status="failed",
                result={"reason": "relay_session_revoked"},
                metadata={"progressFingerprint": f"relay-revoked:{provider_task_id}"},
            )
        row = self.store.load(provider_task_id)
        receipt = row.get("receipt")
        if not isinstance(receipt, Mapping):
            return ProviderInspection(
                status="running",
                result={"state": "awaiting_correlated_relay_receipt"},
                metadata={"progressFingerprint": f"relay-awaiting:{provider_task_id}"},
            )
        result = dict(receipt)
        output_hash = canonical_digest(result)
        if result.get("terminal_status") == "success":
            return ProviderInspection(
                status="completed",
                result=result,
                evidence=(f"relay-receipt:{provider_task_id}",),
                output_hash=output_hash,
                metadata={"progressFingerprint": output_hash},
            )
        return ProviderInspection(
            status="failed",
            result=result,
            evidence=(f"relay-receipt:{provider_task_id}",),
            output_hash=output_hash,
            metadata={"progressFingerprint": output_hash},
        )


def relay_evidence_verifier(store: RelayReceiptStore):
    async def verify(provider: str, provider_task_id: str, inspection: ProviderInspection) -> bool:
        if provider != "relay":
            return False
        try:
            row = store.load(provider_task_id)
        except RelayReceiptError:
            return False
        receipt = row.get("receipt")
        expectation = row.get("expectation")
        if not isinstance(receipt, Mapping) or not isinstance(expectation, Mapping):
            return False
        exact = ("task_id", "target_device_id", "operation", "request_id", "authorization_id")
        if any(receipt.get(key) != expectation.get(key) for key in exact):
            return False
        if receipt.get("schema_version") != COMPLETION_SCHEMA:
            return False
        if receipt.get("channel") != "bridge" or receipt.get("verification_source") != "relay_response":
            return False
        if receipt.get("terminal_status") != "success":
            return False
        if not SHA256_RE.fullmatch(str(receipt.get("result_digest") or "")):
            return False
        expected_hash = canonical_digest(dict(receipt))
        if inspection.output_hash != expected_hash:
            return False
        if tuple(inspection.evidence) != (f"relay-receipt:{provider_task_id}",):
            return False
        if inspection.result != dict(receipt):
            return False
        return True
    return verify


def observe_relay_notification(reconciler: Any, task_id: str, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    safe = redact_sensitive(dict(params or {}))
    return reconciler.observe_notification(task_id, method, safe)
