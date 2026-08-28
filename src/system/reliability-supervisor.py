#!/usr/bin/env python3
"""Durable reliability primitives for long-running Hermes jobs.

This module is intentionally scheduler-agnostic. It adds four fail-closed
primitives that can sit underneath cron, Revenue OS, and other Hermes workers:

* content-bound persistent job state,
* heartbeat/runtime stall detection with bounded re-arming,
* verified completion receipts, and
* immutable update receipts.

It does not spawn arbitrary processes or grant new authority. Callers remain
responsible for executing only through their existing governed tool boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
JOB_SCHEMA = "hermes-reliability-job-v1"
RUN_RECEIPT_SCHEMA = "hermes-reliability-run-receipt-v1"
UPDATE_RECEIPT_SCHEMA = "hermes-update-receipt-v1"


class ReliabilityError(ValueError):
    pass


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


def _parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReliabilityError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _id(value: str, label: str) -> str:
    text = str(value).strip()
    if not ID_RE.fullmatch(text):
        raise ReliabilityError(f"invalid {label}")
    return text


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body.pop("content_hash", None)
    body["content_hash"] = digest(body)
    return body


def _verify(payload: Mapping[str, Any], schema: str) -> dict[str, Any]:
    value = dict(payload)
    expected = value.pop("content_hash", "")
    if value.get("schema_version") != schema:
        raise ReliabilityError("receipt/state schema mismatch")
    if expected != digest(value):
        raise ReliabilityError("receipt/state content hash mismatch")
    value["content_hash"] = expected
    return value


def _atomic_replace(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sealed = _seal(payload)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sealed, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            parent_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except OSError:
            pass
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return path


def _create_only(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sealed = _seal(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sealed, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


class ReliabilitySupervisor:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.run_receipts_dir = self.root / "run-receipts"
        self.update_receipts_dir = self.root / "update-receipts"

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{_id(job_id, 'job id')}.json"

    def _run_receipt_path(self, job_id: str, run_id: str) -> Path:
        return self.run_receipts_dir / _id(job_id, "job id") / f"{_id(run_id, 'run id')}.json"

    def _update_receipt_path(self, update_id: str) -> Path:
        return self.update_receipts_dir / f"{_id(update_id, 'update id')}.json"

    def register_job(
        self,
        job_id: str,
        *,
        schedule: str,
        max_runtime_seconds: int = 900,
        heartbeat_timeout_seconds: int = 180,
        max_recoveries: int = 3,
        memory_refs: Iterable[str] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        job_id = _id(job_id, "job id")
        if not str(schedule).strip():
            raise ReliabilityError("schedule is required")
        if int(max_runtime_seconds) <= 0 or int(heartbeat_timeout_seconds) <= 0 or int(max_recoveries) < 0:
            raise ReliabilityError("invalid reliability limits")
        path = self._job_path(job_id)
        contract = {
            "schedule": str(schedule).strip(),
            "max_runtime_seconds": int(max_runtime_seconds),
            "heartbeat_timeout_seconds": int(heartbeat_timeout_seconds),
            "max_recoveries": int(max_recoveries),
        }
        if path.exists():
            state = self.load_job(job_id)
            existing = {key: state[key] for key in contract}
            if existing != contract:
                raise ReliabilityError("existing job reliability contract mismatch")
            merged_memory = _dedupe([*state.get("memory_refs", []), *memory_refs])
            if merged_memory != state.get("memory_refs", []):
                state["memory_refs"] = merged_memory
                state["updated_at"] = _ts(now)
                _atomic_replace(path, state)
            return self.load_job(job_id)
        stamp = _ts(now)
        state = {
            "schema_version": JOB_SCHEMA,
            "job_id": job_id,
            **contract,
            "status": "idle",
            "run_id": "",
            "started_at": "",
            "heartbeat_at": "",
            "stall_reason": "",
            "recovery_count": 0,
            "last_recovery_at": "",
            "memory_refs": _dedupe(memory_refs),
            "last_receipt_ref": "",
            "created_at": stamp,
            "updated_at": stamp,
        }
        _atomic_replace(path, state)
        return self.load_job(job_id)

    def load_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if path.is_symlink() or not path.is_file():
            raise ReliabilityError("job state missing or unsafe")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReliabilityError(f"cannot load job state: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise ReliabilityError("job state must be an object")
        return _verify(raw, JOB_SCHEMA)

    def _save_job(self, state: Mapping[str, Any]) -> dict[str, Any]:
        path = self._job_path(str(state.get("job_id", "")))
        _atomic_replace(path, state)
        return self.load_job(str(state["job_id"]))

    def start_run(self, job_id: str, run_id: str, *, memory_refs: Iterable[str] = (), now: datetime | None = None) -> dict[str, Any]:
        run_id = _id(run_id, "run id")
        state = self.load_job(job_id)
        if state["status"] in {"running", "stalled"}:
            raise ReliabilityError("job already has an active or stalled run")
        stamp = _ts(now)
        state.update({
            "status": "running",
            "run_id": run_id,
            "started_at": stamp,
            "heartbeat_at": stamp,
            "stall_reason": "",
            "memory_refs": _dedupe([*state.get("memory_refs", []), *memory_refs]),
            "updated_at": stamp,
        })
        return self._save_job(state)

    def heartbeat(self, job_id: str, run_id: str, *, memory_refs: Iterable[str] = (), now: datetime | None = None) -> dict[str, Any]:
        state = self.load_job(job_id)
        if state["status"] != "running" or state["run_id"] != _id(run_id, "run id"):
            raise ReliabilityError("heartbeat does not match active run")
        stamp = _ts(now)
        state["heartbeat_at"] = stamp
        state["memory_refs"] = _dedupe([*state.get("memory_refs", []), *memory_refs])
        state["updated_at"] = stamp
        return self._save_job(state)

    def assess(self, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        state = self.load_job(job_id)
        if state["status"] != "running":
            return state
        current = _now(now)
        started = _parse_ts(state["started_at"])
        heartbeat = _parse_ts(state["heartbeat_at"])
        runtime = (current - started).total_seconds()
        heartbeat_age = (current - heartbeat).total_seconds()
        reason = ""
        if heartbeat_age > float(state["heartbeat_timeout_seconds"]):
            reason = "heartbeat_timeout"
        elif runtime > float(state["max_runtime_seconds"]):
            reason = "runtime_timeout"
        if reason:
            state["status"] = "stalled"
            state["stall_reason"] = reason
            state["updated_at"] = _ts(current)
            return self._save_job(state)
        return state

    def rearm(self, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        state = self.load_job(job_id)
        if state["status"] != "stalled":
            raise ReliabilityError("only stalled jobs can be rearmed")
        if int(state["recovery_count"]) >= int(state["max_recoveries"]):
            raise ReliabilityError("recovery budget exhausted")
        stamp = _ts(now)
        state.update({
            "status": "idle",
            "run_id": "",
            "started_at": "",
            "heartbeat_at": "",
            "stall_reason": "",
            "recovery_count": int(state["recovery_count"]) + 1,
            "last_recovery_at": stamp,
            "updated_at": stamp,
        })
        return self._save_job(state)

    def complete_run(
        self,
        job_id: str,
        run_id: str,
        *,
        status: str,
        result_hash: str,
        evidence: Iterable[str],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = _id(run_id, "run id")
        receipt_path = self._run_receipt_path(job_id, run_id)
        if receipt_path.exists():
            raise FileExistsError(str(receipt_path))
        if status not in {"success", "failed"}:
            raise ReliabilityError("run status must be success or failed")
        if not SHA256_RE.fullmatch(str(result_hash)):
            raise ReliabilityError("completion requires canonical sha256 result hash")
        evidence_rows = _dedupe(evidence)
        if status == "success" and not evidence_rows:
            raise ReliabilityError("successful completion requires evidence")
        state = self.load_job(job_id)
        if state["status"] != "running" or state["run_id"] != run_id:
            raise ReliabilityError("completion does not match active run")
        stamp = _ts(now)
        receipt = {
            "schema_version": RUN_RECEIPT_SCHEMA,
            "job_id": state["job_id"],
            "run_id": run_id,
            "status": status,
            "result_hash": result_hash,
            "evidence": evidence_rows,
            "memory_refs": list(state.get("memory_refs", [])),
            "started_at": state["started_at"],
            "completed_at": stamp,
            "recovery_count": int(state["recovery_count"]),
        }
        _create_only(receipt_path, receipt)
        state.update({
            "status": status,
            "last_receipt_ref": str(receipt_path),
            "run_id": "",
            "started_at": "",
            "heartbeat_at": "",
            "stall_reason": "",
            "updated_at": stamp,
        })
        self._save_job(state)
        return {"job": self.load_job(job_id), "receipt_path": str(receipt_path), "receipt": self.verify_receipt(receipt_path)}

    def record_update_receipt(
        self,
        *,
        update_id: str,
        component: str,
        before_ref: str,
        after_ref: str,
        status: str,
        evidence: Iterable[str],
        tests: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> Path:
        if status not in {"verified", "failed", "rejected"}:
            raise ReliabilityError("invalid update receipt status")
        if not str(component).strip():
            raise ReliabilityError("component is required")
        if not SHA256_RE.fullmatch(str(before_ref)) or not SHA256_RE.fullmatch(str(after_ref)):
            raise ReliabilityError("update refs must be canonical sha256 values")
        evidence_rows = _dedupe(evidence)
        if not evidence_rows:
            raise ReliabilityError("update receipt requires evidence")
        receipt = {
            "schema_version": UPDATE_RECEIPT_SCHEMA,
            "update_id": _id(update_id, "update id"),
            "component": str(component).strip(),
            "before_ref": before_ref,
            "after_ref": after_ref,
            "status": status,
            "evidence": evidence_rows,
            "tests": dict(tests or {}),
            "recorded_at": _ts(now),
        }
        path = self._update_receipt_path(update_id)
        return _create_only(path, receipt)

    def verify_receipt(self, path: Path | str) -> dict[str, Any]:
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise ReliabilityError("receipt missing or unsafe")
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReliabilityError(f"cannot load receipt: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise ReliabilityError("receipt must be an object")
        schema = raw.get("schema_version")
        if schema not in {RUN_RECEIPT_SCHEMA, UPDATE_RECEIPT_SCHEMA}:
            raise ReliabilityError("unsupported receipt schema")
        return _verify(raw, str(schema))
