#!/usr/bin/env python3
"""Atomic, fail-closed externalization claims for Hermes Revenue OS.

A validation read followed by a network action is not a concurrency boundary.
This module atomically claims {channel,campaign,prospect} before externalization.
The claim is retained after an attempted external action; ambiguous failures
require governance review rather than risking a duplicate message.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_ENV = "HERMES_EXTERNALIZATION_STATE_DIR"
DEFAULT_STATE_DIR = ".hermes/externalization"


class ExternalizationClaimError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def state_dir() -> Path:
    return Path(os.getenv(STATE_ENV, DEFAULT_STATE_DIR))


def ensure_private_dir(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    if len(absolute.parts) <= 1:
        raise ExternalizationClaimError("unsafe_externalization_state_dir")
    for index, part in enumerate(absolute.parts[1:]):
        current = current / part
        final = index == len(absolute.parts[1:]) - 1
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                os.mkdir(current, 0o700)
            except FileExistsError:
                info = os.lstat(current)
            else:
                info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode):
            raise ExternalizationClaimError("unsafe_externalization_state_symlink")
        if not stat.S_ISDIR(info.st_mode):
            raise ExternalizationClaimError("unsafe_externalization_state_not_directory")
        if final:
            if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
                raise ExternalizationClaimError("unsafe_externalization_state_owner")
            if stat.S_IMODE(info.st_mode) != 0o700:
                os.chmod(current, 0o700, follow_symlinks=False)


def claim_scope(channel: str, campaign_id: str, prospect_id: str) -> dict[str, str]:
    values = {
        "channel": str(channel).strip(),
        "campaign_id": str(campaign_id).strip(),
        "prospect_id": str(prospect_id).strip(),
    }
    if not all(values.values()):
        raise ExternalizationClaimError("externalization_claim_scope_incomplete")
    return values


def claim_id(scope: dict[str, str]) -> str:
    return "ext_" + hashlib.sha256(canonical_json(scope)).hexdigest()[:40]


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    ensure_private_dir(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ExternalizationClaimError("externalization_already_claimed") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def acquire(channel: str, campaign_id: str, prospect_id: str) -> dict[str, Any]:
    scope = claim_scope(channel, campaign_id, prospect_id)
    cid = claim_id(scope)
    root = state_dir()
    ensure_private_dir(root)
    payload = {
        "claim_id": cid,
        "scope": scope,
        "claimed_at": utc_now(),
        "status": "claimed",
    }
    _write_once(root / "claims" / f"{cid}.json", payload)
    return payload


def complete(claim: dict[str, Any], receipt_ref: str, receipt_hash: str) -> dict[str, Any]:
    cid = str(claim.get("claim_id") or "")
    if not cid.startswith("ext_") or len(cid) != 44:
        raise ExternalizationClaimError("invalid_externalization_claim")
    payload = {
        "claim_id": cid,
        "completed_at": utc_now(),
        "receipt_ref": str(receipt_ref),
        "receipt_hash": str(receipt_hash),
        "status": "completed",
    }
    _write_once(state_dir() / "completed" / f"{cid}.json", payload)
    return payload
