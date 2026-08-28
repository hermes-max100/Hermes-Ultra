#!/usr/bin/env python3
"""Hermes Canary Controller v1.

Promotion is reversible; evidence is not. This controller starts bounded
canaries, records telemetry, and performs idempotent rollback to the previous
known-good files when hard rollback conditions are observed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SECURITY_CLASS_ALIASES = {
    "PUBLIC": "PUBLIC",
    "INTERNAL": "INTERNAL",
    "CONFIDENTIAL": "CONFIDENTIAL",
    "LEGAL": "LEGAL_PRIVILEGED",
    "LEGAL_PRIVILEGED": "LEGAL_PRIVILEGED",
    "PRIVILEGED": "LEGAL_PRIVILEGED",
    "FINANCIAL": "FINANCIAL",
    "CREDENTIAL": "CREDENTIAL",
    "CREDENTIALS": "CREDENTIAL",
    "SECURITY": "SECURITY_SENSITIVE",
    "SECURITY_SENSITIVE": "SECURITY_SENSITIVE",
    "RESTRICTED": "SECURITY_SENSITIVE",
}

SECURITY_CLASS_FLOWS = {
    "PUBLIC": {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "INTERNAL": {"INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "CONFIDENTIAL": {"CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "LEGAL_PRIVILEGED": {"LEGAL_PRIVILEGED"},
    "FINANCIAL": {"FINANCIAL"},
    "SECURITY_SENSITIVE": {"SECURITY_SENSITIVE", "CREDENTIAL"},
    "CREDENTIAL": {"CREDENTIAL"},
}

ROLLBACK_STATUSES = {"blocked", "error", "failed", "failure", "rejected"}
ROLLBACK_TERMINAL_STATUSES = {"rolled_back", "rollback_unverified"}
POLICY_SNAPSHOT_FIELDS = (
    "promotion_id",
    "candidate_version",
    "previous_version",
    "promotion_evidence_id",
    "anchor_report_hash",
    "rollback_target",
    "rollback_conditions",
    "canary_policy",
    "rollback_targets",
    "release_unit",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json_synced(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_tree(path: Path) -> None:
    if path.is_file():
        with path.open("rb") as fh:
            os.fsync(fh.fileno())
        fsync_dir(path.parent)
        return
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                with child.open("rb") as fh:
                    os.fsync(fh.fileno())
        fsync_dir(path)
        fsync_dir(path.parent)


def normalize_class(value: str | None) -> str:
    raw = (value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    out = SECURITY_CLASS_ALIASES.get(raw)
    if not out:
        raise SystemExit(f"unsupported security classification: {value}")
    return out


def can_flow(source: str, destination: str) -> bool:
    return destination in SECURITY_CLASS_FLOWS[source]


def state_path(state_dir: Path, promotion_id: str) -> Path:
    return state_dir / f"{promotion_id}.json"


def validate_policy(policy: dict[str, Any]) -> None:
    for field in ("promotion_id", "candidate_version", "previous_version", "promotion_evidence_id", "anchor_report_hash"):
        if not policy.get(field):
            raise SystemExit(f"policy missing required field: {field}")
    canary = policy.get("canary_policy", {})
    if not isinstance(canary, dict):
        raise SystemExit("canary_policy must be a JSON object")
    max_executions = int(canary.get("max_executions", 0))
    window_seconds = int(canary.get("window_seconds", 0))
    if max_executions <= 0:
        raise SystemExit("canary_policy.max_executions must be > 0")
    if window_seconds <= 0:
        raise SystemExit("canary_policy.window_seconds must be > 0")
    has_targets = bool(policy.get("rollback_targets"))
    has_release_unit = bool(policy.get("release_unit"))
    if has_targets == has_release_unit:
        raise SystemExit("provide exactly one rollback mode: rollback_targets or release_unit")
    if has_release_unit:
        release_unit = policy.get("release_unit", {})
        if not isinstance(release_unit, dict):
            raise SystemExit("release_unit must be a JSON object")
        for field in ("active_path", "previous_release_path", "candidate_release_path"):
            if not release_unit.get(field):
                raise SystemExit(f"release_unit missing required field: {field}")
        previous = Path(str(release_unit["previous_release_path"]))
        candidate = Path(str(release_unit["candidate_release_path"]))
        if not previous.exists():
            raise SystemExit(f"release_unit previous release missing: {previous}")
        if not candidate.exists():
            raise SystemExit(f"release_unit candidate release missing: {candidate}")
    normalize_class(canary.get("security_classification_ceiling", "INTERNAL"))


def policy_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for field in POLICY_SNAPSHOT_FIELDS:
        if field in source:
            snapshot[field] = source[field]
    return snapshot


def assert_policy_immutable(state: dict[str, Any]) -> None:
    expected_hash = state.get("policy_hash")
    stored_snapshot = state.get("policy_snapshot")
    if not expected_hash or not isinstance(stored_snapshot, dict):
        raise SystemExit("canary state missing immutable policy snapshot")
    if sha256_json(stored_snapshot) != expected_hash:
        raise SystemExit("stored canary policy snapshot hash mismatch")
    if sha256_json(policy_snapshot(state)) != expected_hash:
        raise SystemExit("canary policy changed after start; start a new canary")


def start_canary(policy_path: Path, state_dir: Path) -> dict[str, Any]:
    policy = read_json(policy_path)
    validate_policy(policy)
    promotion_id = str(policy["promotion_id"])
    started = datetime.now(timezone.utc).replace(microsecond=0)
    expires = started + timedelta(seconds=int(policy["canary_policy"]["window_seconds"]))
    state = {
        "promotion_id": promotion_id,
        "status": "active",
        "candidate_version": policy["candidate_version"],
        "previous_version": policy["previous_version"],
        "promotion_evidence_id": policy["promotion_evidence_id"],
        "anchor_report_hash": policy["anchor_report_hash"],
        "canary_policy": policy["canary_policy"],
        "canary_started_at": started.isoformat().replace("+00:00", "Z"),
        "canary_expires_at": expires.isoformat().replace("+00:00", "Z"),
        "rollback_target": policy.get("rollback_target", policy["previous_version"]),
        "rollback_targets": policy.get("rollback_targets", []),
        "release_unit": policy.get("release_unit", {}),
        "rollback_conditions": policy.get("rollback_conditions", [
            "critical security failure",
            "mandatory-anchor regression",
            "classification violation",
            "evidence persistence failure",
            "error-rate threshold exceeded",
            "latency/cost ceiling exceeded",
            "explicit governance rejection",
        ]),
        "metrics": {
            "execution_count": 0,
            "error_count": 0,
            "total_cost": 0.0,
            "max_latency_ms": 0,
            "violations": [],
        },
        "telemetry": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    immutable_policy = policy_snapshot(state)
    state["policy_snapshot"] = immutable_policy
    state["policy_hash"] = sha256_json(immutable_policy)
    write_json(state_path(state_dir, promotion_id), state)
    record_memory(state_dir, state, "canary-started", "canary started", [])
    return state


def load_state(state_dir: Path, promotion_id: str) -> dict[str, Any]:
    path = state_path(state_dir, promotion_id)
    if not path.is_file():
        raise SystemExit(f"canary state not found: {promotion_id}")
    return read_json(path)


def telemetry_violation(state: dict[str, Any], trajectory: dict[str, Any]) -> list[str]:
    canary = state["canary_policy"]
    violations: list[str] = []
    status = str(trajectory.get("status", "")).lower()
    metadata = trajectory.get("metadata", {}) if isinstance(trajectory.get("metadata"), dict) else {}
    failure_class = str(trajectory.get("failure_class", "")).lower()
    if status in ROLLBACK_STATUSES:
        violations.append(f"bad-status:{status}")
    if metadata.get("critical_security_failure") or "critical security" in failure_class:
        violations.append("critical-security-failure")
    if metadata.get("mandatory_anchor_failure") or "mandatory-anchor" in failure_class:
        violations.append("mandatory-anchor-regression")
    if metadata.get("governance_rejection") or status == "rejected":
        violations.append("explicit-governance-rejection")
    if metadata.get("evidence_persisted") is False:
        violations.append("evidence-persistence-failure")

    ceiling = normalize_class(canary.get("security_classification_ceiling", "INTERNAL"))
    observed_class = normalize_class(str(trajectory.get("security_classification") or ceiling))
    allowed = {normalize_class(item) for item in canary.get("permitted_security_classifications", [])}
    if allowed:
        if observed_class not in allowed:
            violations.append(f"classification-not-permitted:{observed_class}")
    elif not can_flow(observed_class, ceiling):
        violations.append(f"classification-ceiling-exceeded:{observed_class}->{ceiling}")

    latency = trajectory.get("duration_ms")
    latency_ceiling = canary.get("latency_ceiling_ms")
    if latency_ceiling is not None and isinstance(latency, int) and latency > int(latency_ceiling):
        violations.append(f"latency-ceiling-exceeded:{latency}")

    task = str(trajectory.get("objective", ""))
    task_set = [str(item) for item in canary.get("explicit_task_set", [])]
    if task_set and task not in task_set:
        violations.append("task-outside-canary-scope")

    profile = str(metadata.get("profile", ""))
    profiles = [str(item) for item in canary.get("permitted_profiles", [])]
    if profiles and profile and profile not in profiles:
        violations.append(f"profile-not-permitted:{profile}")

    project = str(metadata.get("project", ""))
    projects = [str(item) for item in canary.get("permitted_projects", [])]
    if projects and project and project not in projects:
        violations.append(f"project-not-permitted:{project}")

    return violations


def record_telemetry(state_dir: Path, promotion_id: str, trajectory_path: Path) -> dict[str, Any]:
    state = load_state(state_dir, promotion_id)
    if state["status"] in ROLLBACK_TERMINAL_STATUSES:
        print(f"already_rolled_back={promotion_id}")
        return state
    if state["status"] != "active":
        raise SystemExit(f"canary is not active: {state['status']}")
    assert_policy_immutable(state)
    trajectory = read_json(trajectory_path)
    metrics = state["metrics"]
    metrics["execution_count"] += 1
    if str(trajectory.get("status", "")).lower() in ROLLBACK_STATUSES:
        metrics["error_count"] += 1
    cost = trajectory.get("cost")
    if isinstance(cost, (int, float)):
        metrics["total_cost"] += float(cost)
    duration = trajectory.get("duration_ms")
    if isinstance(duration, int):
        metrics["max_latency_ms"] = max(int(metrics["max_latency_ms"]), duration)
    violations = telemetry_violation(state, trajectory)
    error_rate = metrics["error_count"] / max(metrics["execution_count"], 1)
    if error_rate > float(state["canary_policy"].get("error_rate_threshold", 1.0)):
        violations.append(f"error-rate-threshold-exceeded:{error_rate:.4f}")
    if metrics["total_cost"] > float(state["canary_policy"].get("cost_ceiling", 10**9)):
        violations.append(f"cost-ceiling-exceeded:{metrics['total_cost']:.4f}")
    if parse_time(state["canary_expires_at"]) < datetime.now(timezone.utc):
        violations.append("canary-window-expired")

    state["telemetry"].append(
        {
            "path": str(trajectory_path),
            "sha256": sha256_file(trajectory_path),
            "violations": violations,
            "recorded_at": utc_now(),
        }
    )
    metrics["violations"].extend(violations)
    state["updated_at"] = utc_now()
    write_json(state_path(state_dir, promotion_id), state)
    record_memory(state_dir, state, "canary-telemetry", f"telemetry recorded violations={len(violations)}", [{"path": str(trajectory_path), "sha256": sha256_file(trajectory_path)}])

    if violations:
        return rollback(state_dir, promotion_id, ";".join(violations))
    if metrics["execution_count"] >= int(state["canary_policy"]["max_executions"]):
        state["status"] = "canary_passed"
        state["updated_at"] = utc_now()
        write_json(state_path(state_dir, promotion_id), state)
    return state


def safe_target_name(index: int, path: Path) -> str:
    return f"{index:03d}-{sha256_text(str(path))[:16]}-{path.name}"


def copy_to_freeze(path: Path, freeze_path: Path) -> None:
    dest = freeze_path
    if path.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(path, dest)
    elif path.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    fsync_tree(dest)


def rollback_journal_path(state_dir: Path, promotion_id: str) -> Path:
    return state_dir / "journals" / f"{promotion_id}-rollback.json"


def verify_restored_hash(path: Path, expected: str | None) -> None:
    if expected and path.is_file() and sha256_file(path) != expected:
        raise SystemExit(f"restored file hash mismatch: {path}")


def replace_from_staged(path: Path, staged: Path) -> None:
    if staged.is_dir():
        tmp = path.with_name(path.name + ".rollback.tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(staged, tmp)
        fsync_tree(tmp)
        if path.exists():
            shutil.rmtree(path)
        os.replace(tmp, path)
    else:
        tmp = path.with_name(path.name + ".rollback.tmp")
        shutil.copy2(staged, tmp)
        fsync_tree(tmp)
        os.replace(tmp, path)
    fsync_dir(path.parent)


def build_rollback_journal(state_dir: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    if state.get("release_unit"):
        return build_release_unit_rollback_journal(state_dir, state, reason)
    promotion_id = state["promotion_id"]
    transaction_id = f"rollback-{promotion_id}-{sha256_text(utc_now())[:12]}"
    staging_dir = state_dir / "staging" / promotion_id
    freeze_dir = state_dir / "frozen" / promotion_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    freeze_dir.mkdir(parents=True, exist_ok=True)

    targets = []
    for index, target in enumerate(state["rollback_targets"]):
        path = Path(target["path"])
        backup = Path(target["backup_path"])
        expected = target.get("sha256")
        if not backup.exists():
            raise SystemExit(f"rollback backup missing: {backup}")
        if expected and backup.is_file() and sha256_file(backup) != expected:
            raise SystemExit(f"rollback backup hash mismatch: {backup}")

        name = safe_target_name(index, path)
        staged = staging_dir / name
        freeze_path = freeze_dir / name
        if backup.is_dir():
            shutil.copytree(backup, staged)
        else:
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, staged)
        fsync_tree(staged)
        if path.exists():
            copy_to_freeze(path, freeze_path)

        targets.append(
            {
                "path": str(path),
                "backup_path": str(backup),
                "staged_path": str(staged),
                "pre_rollback_path": str(freeze_path) if path.exists() else "",
                "sha256": expected or "",
                "replaced": False,
                "verified": False,
            }
        )

    return {
        "transaction_id": transaction_id,
        "mode": "rollback_targets",
        "promotion_id": promotion_id,
        "reason": reason,
        "status": "intent",
        "started_at": utc_now(),
        "committed_at": "",
        "targets": targets,
    }


def active_points_to(active: Path, target: Path) -> bool:
    if not active.is_symlink():
        return False
    return Path(os.path.realpath(active)) == target.resolve()


def build_release_unit_rollback_journal(state_dir: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    promotion_id = state["promotion_id"]
    release_unit = state["release_unit"]
    active = Path(release_unit["active_path"])
    previous = Path(release_unit["previous_release_path"])
    candidate = Path(release_unit["candidate_release_path"])
    if active.exists() and not active.is_symlink():
        raise SystemExit(f"release_unit active_path must be a symlink: {active}")
    if not previous.exists():
        raise SystemExit(f"release_unit previous release missing: {previous}")
    if not candidate.exists():
        raise SystemExit(f"release_unit candidate release missing: {candidate}")
    active.parent.mkdir(parents=True, exist_ok=True)
    staged = active.with_name(active.name + ".rollback-link.tmp")
    if staged.exists() or staged.is_symlink():
        staged.unlink()
    os.symlink(str(previous.resolve()), staged)
    fsync_dir(active.parent)
    pre_active_target = os.readlink(active) if active.is_symlink() else ""
    return {
        "transaction_id": f"rollback-{promotion_id}-{sha256_text(utc_now())[:12]}",
        "mode": "release_unit",
        "promotion_id": promotion_id,
        "reason": reason,
        "status": "intent",
        "started_at": utc_now(),
        "committed_at": "",
        "targets": [],
        "release_unit": {
            "active_path": str(active),
            "previous_release_path": str(previous),
            "candidate_release_path": str(candidate),
            "pre_rollback_active_target": pre_active_target,
            "staged_active_path": str(staged),
            "swapped": False,
            "verified": False,
        },
    }


def finish_release_unit_rollback_transaction(journal_file: Path, journal: dict[str, Any]) -> dict[str, Any]:
    release_unit = journal["release_unit"]
    active = Path(release_unit["active_path"])
    previous = Path(release_unit["previous_release_path"])
    staged = Path(release_unit["staged_active_path"])
    if not release_unit.get("verified"):
        if not active_points_to(active, previous):
            if not staged.exists() and not staged.is_symlink():
                os.symlink(str(previous.resolve()), staged)
                fsync_dir(active.parent)
            os.replace(staged, active)
            release_unit["swapped"] = True
            write_json_synced(journal_file, journal)
            fsync_dir(active.parent)
        if not active_points_to(active, previous):
            raise SystemExit(f"release_unit active pointer did not switch to previous release: {active}")
        release_unit["verified"] = True
        write_json_synced(journal_file, journal)
    journal["status"] = "committed"
    journal["committed_at"] = utc_now()
    write_json_synced(journal_file, journal)
    return journal


def finish_rollback_transaction(journal_file: Path) -> dict[str, Any]:
    journal = read_json(journal_file)
    if journal.get("status") == "committed":
        return journal
    if journal.get("mode") == "release_unit":
        return finish_release_unit_rollback_transaction(journal_file, journal)
    for target in journal["targets"]:
        path = Path(target["path"])
        staged = Path(target["staged_path"])
        if not staged.exists():
            raise SystemExit(f"rollback staged restore missing: {staged}")
        if not target.get("verified"):
            replace_from_staged(path, staged)
            target["replaced"] = True
            write_json_synced(journal_file, journal)
            verify_restored_hash(path, target.get("sha256") or None)
            target["verified"] = True
            write_json_synced(journal_file, journal)
    journal["status"] = "committed"
    journal["committed_at"] = utc_now()
    write_json_synced(journal_file, journal)
    return journal


def execute_rollback_transaction(state_dir: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    journal_file = rollback_journal_path(state_dir, state["promotion_id"])
    if journal_file.is_file():
        return finish_rollback_transaction(journal_file)
    journal = build_rollback_journal(state_dir, state, reason)
    write_json_synced(journal_file, journal)
    return finish_rollback_transaction(journal_file)


def rollback_result_path(state_dir: Path, promotion_id: str) -> Path:
    return state_dir / "reports" / f"rollback-result-{promotion_id}.json"


def rollback_receipt_path(state_dir: Path, promotion_id: str) -> Path:
    return state_dir / "reports" / f"rollback-receipt-{promotion_id}.json"


def rollback_legacy_report_path(state_dir: Path, promotion_id: str) -> Path:
    return state_dir / "reports" / f"rollback-{promotion_id}.json"


def write_rollback_result(result_path: Path, state: dict[str, Any], reason: str, journal_file: Path) -> str:
    journal = read_json(journal_file)
    result = {
        "artifact_type": "rollback-result",
        "promotion_id": state["promotion_id"],
        "candidate_version": state["candidate_version"],
        "previous_version": state["previous_version"],
        "rollback_reason": reason,
        "rollback_transaction_id": journal["transaction_id"],
        "rollback_journal": str(journal_file),
        "rollback_journal_hash": sha256_file(journal_file),
        "journal_status": journal.get("status", ""),
        "journal_committed_at": journal.get("committed_at", ""),
        "disk_rollback_status": "committed",
        "restored_targets": [
            {
                "path": target.get("path", ""),
                "backup_path": target.get("backup_path", ""),
                "sha256": target.get("sha256", ""),
                "replaced": bool(target.get("replaced")),
                "verified": bool(target.get("verified")),
            }
            for target in journal.get("targets", [])
        ],
        "release_unit": journal.get("release_unit", {}),
        "created_at": utc_now(),
    }
    write_json_synced(result_path, result)
    return sha256_file(result_path)


def write_rollback_receipt(receipt_path: Path, state: dict[str, Any], result_path: Path, result_hash: str, receipt: str) -> str:
    receipt_artifact = {
        "artifact_type": "rollback-receipt",
        "promotion_id": state["promotion_id"],
        "rollback_result_path": str(result_path),
        "rollback_result_hash": result_hash,
        "memory_evidence_id": receipt,
        "final_governance_state": "rolled_back" if receipt else "rollback_unverified",
        "created_at": utc_now(),
    }
    write_json_synced(receipt_path, receipt_artifact)
    return sha256_file(receipt_path)


def finalize_rollback_evidence(state_dir: Path, state: dict[str, Any], reason: str, journal_file: Path) -> dict[str, Any]:
    promotion_id = state["promotion_id"]
    result_path = rollback_result_path(state_dir, promotion_id)
    receipt_path = rollback_receipt_path(state_dir, promotion_id)
    legacy_report = rollback_legacy_report_path(state_dir, promotion_id)
    result_hash = state.get("rollback_result_hash") or ""
    if not result_hash:
        result_hash = write_rollback_result(result_path, state, reason, journal_file)
        state["rollback_result_path"] = str(result_path)
        state["rollback_result_hash"] = result_hash
    evidence_refs = [{"path": str(result_path), "sha256": result_hash}]
    if journal_file.is_file():
        evidence_refs.append({"path": str(journal_file), "sha256": sha256_file(journal_file)})
    receipt = record_memory(
        state_dir,
        state,
        "rolled_back",
        f"rollback completed: {reason}",
        evidence_refs,
        include_state_ref=False,
    )
    if receipt:
        state["status"] = "rolled_back"
        state["rollback_evidence_id"] = receipt
        state["rollback_receipt_path"] = str(receipt_path)
        state["rollback_receipt_hash"] = write_rollback_receipt(receipt_path, state, result_path, result_hash, receipt)
    else:
        state["status"] = "rollback_unverified"
        state["rollback_evidence_id"] = ""
        state["rollback_receipt_path"] = ""
        state["rollback_receipt_hash"] = ""
    state["updated_at"] = utc_now()
    write_json(state_path(state_dir, state["promotion_id"]), state)
    write_json(legacy_report, state)
    return state


def rollback(state_dir: Path, promotion_id: str, reason: str) -> dict[str, Any]:
    state = load_state(state_dir, promotion_id)
    if state["status"] == "rolled_back":
        return state
    assert_policy_immutable(state)
    journal_file = rollback_journal_path(state_dir, promotion_id)
    if state["status"] == "rollback_unverified":
        return finalize_rollback_evidence(state_dir, state, state.get("rollback_reason", reason), journal_file)
    journal = execute_rollback_transaction(state_dir, state, reason)
    state["status"] = "rollback_evidence_pending"
    state["rollback_reason"] = reason
    state["rollback_transaction_id"] = journal["transaction_id"]
    state["rollback_journal"] = str(journal_file)
    state["rolled_back_at"] = utc_now()
    state["updated_at"] = utc_now()
    return finalize_rollback_evidence(state_dir, state, reason, journal_file)


def record_memory(
    state_dir: Path,
    state: dict[str, Any],
    status: str,
    observed: str,
    evidence_refs: list[dict[str, str]],
    include_state_ref: bool = True,
) -> str:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return ""
    root_dir = Path(__file__).resolve().parents[2]
    memory = root_dir / "src/system/memory-fabric.py"
    if not memory.is_file():
        return ""
    state_file = state_path(state_dir, state["promotion_id"])
    refs = [{"path": str(state_file), "sha256": sha256_file(state_file)}] if include_state_ref and state_file.is_file() else []
    refs.extend(evidence_refs)
    envelope = {
        "producer": "canary-controller",
        "objective": "promotion-canary",
        "input_hash": sha256_json({"promotion_id": state["promotion_id"], "status": status}),
        "selected_agent": "canary-controller",
        "actions": [{"type": status, "promotion_id": state["promotion_id"]}],
        "predicted_outcome": "candidate remains bounded until canary passes",
        "observed_outcome": observed,
        "status": status,
        "failure_class": state.get("rollback_reason", ""),
        "evidence_refs": refs,
        "security_classification": "SECURITY_SENSITIVE",
        "metadata": {
            "promotion_id": state["promotion_id"],
            "candidate_version": state["candidate_version"],
            "previous_version": state["previous_version"],
            "promotion_evidence_id": state["promotion_evidence_id"],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.splitlines():
        if line.startswith("trajectory="):
            return line.partition("=")[2].strip()
    return ""


def print_state(state: dict[str, Any]) -> None:
    print(json.dumps(state, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Canary Controller v1")
    parser.add_argument("--state-dir", default=".hermes/canary")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--policy", required=True)

    record = sub.add_parser("record")
    record.add_argument("--promotion-id", required=True)
    record.add_argument("--trajectory", required=True)

    rb = sub.add_parser("rollback")
    rb.add_argument("--promotion-id", required=True)
    rb.add_argument("--reason", required=True)

    status = sub.add_parser("status")
    status.add_argument("--promotion-id", default="")

    args = parser.parse_args()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "start":
        print_state(start_canary(Path(args.policy), state_dir))
    elif args.command == "record":
        print_state(record_telemetry(state_dir, args.promotion_id, Path(args.trajectory)))
    elif args.command == "rollback":
        print_state(rollback(state_dir, args.promotion_id, args.reason))
    elif args.command == "status":
        if args.promotion_id:
            print_state(load_state(state_dir, args.promotion_id))
        else:
            rows = []
            for path in sorted(state_dir.glob("*.json")):
                rows.append(read_json(path))
            print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
