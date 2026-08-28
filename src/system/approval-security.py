#!/usr/bin/env python3
"""Authenticated approval receipts for Hermes Revenue OS.

A SHA-256 field proves only accidental integrity; any process able to rewrite a
receipt can recompute it. Execution approvals therefore require an HMAC emitted
by the trusted governance boundary. The signing secret is fixed to
HERMES_APPROVAL_HMAC_SECRET and is never selectable from request arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SECRET_ENV = "HERMES_APPROVAL_HMAC_SECRET"
MIN_SECRET_BYTES = 32
AUTH_FIELDS = {"algorithm", "key_id", "value"}
SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


class ApprovalSecurityError(ValueError):
    pass


def require_secret(secret: str | None = None) -> str:
    value = secret if secret is not None else os.getenv(SECRET_ENV, "")
    if len(value.encode("utf-8")) < MIN_SECRET_BYTES:
        raise ApprovalSecurityError("approval_authenticator_missing_or_too_short")
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def legacy_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def signature_body(receipt: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in receipt.items() if k not in {"approval_receipt_hash", "approval_auth"}}


def sign_receipt(receipt: dict[str, Any], secret: str | None = None) -> dict[str, Any]:
    secret = require_secret(secret)
    body = signature_body(receipt)
    value = hmac.new(secret.encode("utf-8"), canonical_json(body), hashlib.sha256).hexdigest()
    signed = dict(body)
    signed["approval_auth"] = {"algorithm": "hmac-sha256", "key_id": "revenue-governance-v1", "value": value}
    signed["approval_receipt_hash"] = legacy_hash(signed)
    return signed


def verify_receipt(receipt: dict[str, Any], secret: str | None = None) -> None:
    secret = require_secret(secret)
    if not isinstance(receipt, dict):
        raise ApprovalSecurityError("approval_receipt_invalid")
    expected_hash = receipt.get("approval_receipt_hash")
    if not isinstance(expected_hash, str) or expected_hash != legacy_hash({k: v for k, v in receipt.items() if k != "approval_receipt_hash"}):
        raise ApprovalSecurityError("approval_receipt_hash_mismatch")
    auth = receipt.get("approval_auth")
    if not isinstance(auth, dict) or set(auth) != AUTH_FIELDS:
        raise ApprovalSecurityError("approval_authenticator_missing")
    if auth.get("algorithm") != "hmac-sha256" or auth.get("key_id") != "revenue-governance-v1":
        raise ApprovalSecurityError("approval_authenticator_invalid")
    value = auth.get("value")
    if not isinstance(value, str) or not SIGNATURE_RE.fullmatch(value):
        raise ApprovalSecurityError("approval_authenticator_invalid")
    expected = hmac.new(secret.encode("utf-8"), canonical_json(signature_body(receipt)), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, value):
        raise ApprovalSecurityError("approval_authenticator_invalid")


def read_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ApprovalSecurityError("approval_receipt_not_regular_file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ApprovalSecurityError("approval_receipt_invalid")
    return data


def write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if tmp.exists():
        raise ApprovalSecurityError("approval_signing_temp_exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def cmd_sign(args: argparse.Namespace) -> int:
    path = Path(args.root) / "approval-receipts" / f"{args.approval_id}.json"
    receipt = read_receipt(path)
    signed = sign_receipt(receipt)
    write_atomic(path, signed)
    print(json.dumps({"approval_id": args.approval_id, "authenticated": True, "path": str(path)}, sort_keys=True))
    return 0


def cmd_check_secret(_args: argparse.Namespace) -> int:
    require_secret()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-secret")
    check.set_defaults(func=cmd_check_secret)
    sign = sub.add_parser("sign")
    sign.add_argument("--root", required=True)
    sign.add_argument("--approval-id", required=True)
    sign.set_defaults(func=cmd_sign)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (ApprovalSecurityError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"decision": "DENY", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
