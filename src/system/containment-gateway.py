#!/usr/bin/env python3
"""Hermes independent containment capability gateway.

This module issues and verifies short-lived, exactly-scoped HMAC capabilities for
network/credential use. It is intentionally policy-mechanical: governance decides
whether a grant should exist; this component only enforces the grant at the
containment boundary.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

VERSION = 1
DEFAULT_MAX_TTL_SECONDS = 300
ABSOLUTE_MAX_TTL_SECONDS = 3600
DEFAULT_CLOCK_SKEW_SECONDS = 15
MAX_TOKEN_BYTES = 64 * 1024
DATA_CLASSES = {
    "PUBLIC", "INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL",
    "CREDENTIAL", "SECURITY_SENSITIVE",
}
TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/@+=,-]{1,512}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")
BODY_FIELDS = {
    "version", "grant_id", "principal", "tool", "destination", "resource",
    "data_class", "purpose", "evidence_id", "issued_at", "expires_at",
    "single_use",
}
BODY_STRING_FIELDS = BODY_FIELDS - {"version", "single_use"}
SIGNATURE_FIELDS = {"algorithm", "value"}
FORBIDDEN_DESTINATION_IPS = {
    ipaddress.ip_address("fd00:ec2::254"),
}


class CapabilityError(ValueError):
    """A deterministic capability validation failure."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityError("invalid_timestamp") from exc
    if dt.tzinfo is None:
        raise CapabilityError("timestamp_must_be_timezone_aware")
    return dt.astimezone(timezone.utc)


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def require_secret(secret: str | None) -> str:
    if not secret or len(secret.encode("utf-8")) < 32:
        raise CapabilityError("containment_secret_missing_or_too_short")
    return secret


def trusted_max_ttl_seconds() -> int:
    raw = os.getenv("HERMES_CONTAINMENT_MAX_TTL", str(DEFAULT_MAX_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise CapabilityError("invalid_max_ttl_config") from exc
    if value < 1 or value > ABSOLUTE_MAX_TTL_SECONDS:
        raise CapabilityError("invalid_max_ttl_config")
    return value


def validate_max_ttl_seconds(value: int) -> int:
    if value < 1 or value > ABSOLUTE_MAX_TTL_SECONDS:
        raise CapabilityError("invalid_max_ttl_config")
    return value


def safe_token(name: str, value: str) -> str:
    value = value.strip()
    if not value or not TOKEN_RE.fullmatch(value):
        raise CapabilityError(f"invalid_{name}")
    return value


def safe_identifier(name: str, value: str) -> str:
    value = value.strip()
    if not value or not IDENTIFIER_RE.fullmatch(value):
        raise CapabilityError(f"invalid_{name}")
    return value


def canonical_destination(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https", "tcp", "tls"}:
        raise CapabilityError("invalid_destination_scheme")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CapabilityError("invalid_destination")

    raw_host = parsed.hostname.lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(raw_host)
    except ValueError:
        try:
            host = raw_host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise CapabilityError("invalid_destination_host") from exc
        authority_host = host
    else:
        if ip.is_link_local or ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip in FORBIDDEN_DESTINATION_IPS:
            raise CapabilityError("forbidden_destination_ip")
        host = ip.compressed
        authority_host = f"[{host}]" if ip.version == 6 else host

    try:
        port = parsed.port
    except ValueError as exc:
        raise CapabilityError("invalid_destination_port") from exc
    default_port = {"http": 80, "https": 443, "tls": 443}.get(parsed.scheme)
    authority = authority_host if port is None or port == default_port else f"{authority_host}:{port}"
    path = parsed.path.rstrip("/")
    if path:
        raise CapabilityError("destination_must_be_origin_only")
    return f"{parsed.scheme}://{authority}"


def sign(body: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_json(body), hashlib.sha256).hexdigest()


def token_digest(token: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(token)).hexdigest()


@dataclass(frozen=True)
class RequestScope:
    principal: str
    tool: str
    destination: str
    resource: str
    data_class: str

    @classmethod
    def make(cls, principal: str, tool: str, destination: str, resource: str, data_class: str) -> "RequestScope":
        dc = data_class.strip().upper()
        if dc not in DATA_CLASSES:
            raise CapabilityError("invalid_data_class")
        return cls(
            principal=safe_token("principal", principal),
            tool=safe_token("tool", tool),
            destination=canonical_destination(destination),
            resource=safe_token("resource", resource),
            data_class=dc,
        )


def issue_capability(
    *, secret: str, scope: RequestScope, purpose: str, evidence_id: str,
    ttl_seconds: int, max_ttl_seconds: int = DEFAULT_MAX_TTL_SECONDS,
    single_use: bool = True, now: datetime | None = None, grant_id: str | None = None,
) -> dict[str, Any]:
    secret = require_secret(secret)
    max_ttl_seconds = validate_max_ttl_seconds(max_ttl_seconds)
    if ttl_seconds < 1 or ttl_seconds > max_ttl_seconds:
        raise CapabilityError("ttl_out_of_policy")
    if type(single_use) is not bool:
        raise CapabilityError("invalid_single_use_type")
    now = (now or utc_now()).astimezone(timezone.utc)
    body: dict[str, Any] = {
        "version": VERSION,
        "grant_id": safe_identifier("grant_id", grant_id or f"cap_{uuid.uuid4().hex}"),
        "principal": scope.principal,
        "tool": scope.tool,
        "destination": scope.destination,
        "resource": scope.resource,
        "data_class": scope.data_class,
        "purpose": safe_token("purpose", purpose),
        "evidence_id": safe_token("evidence_id", evidence_id),
        "issued_at": isoformat(now),
        "expires_at": isoformat(now + timedelta(seconds=ttl_seconds)),
        "single_use": single_use,
    }
    return {"body": body, "signature": {"algorithm": "hmac-sha256", "value": sign(body, secret)}}


def ensure_private_dir(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    if not parts:
        raise CapabilityError("unsafe_state_dir")

    for index, part in enumerate(parts):
        current = current / part
        final = index == len(parts) - 1
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
            raise CapabilityError("unsafe_state_dir_symlink")
        if not stat.S_ISDIR(info.st_mode):
            raise CapabilityError("unsafe_state_dir_not_directory")
        if final:
            if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
                raise CapabilityError("unsafe_state_dir_owner")
            if stat.S_IMODE(info.st_mode) != 0o700:
                os.chmod(current, 0o700, follow_symlinks=False)
                info = os.lstat(current)
                if stat.S_IMODE(info.st_mode) != 0o700:
                    raise CapabilityError("unsafe_state_dir_permissions")


def marker_path(state_dir: Path, kind: str, grant_id: str) -> Path:
    return state_dir / kind / f"{safe_identifier('grant_id', grant_id)}.json"


def marker_exists(state_dir: Path, kind: str, grant_id: str) -> bool:
    return marker_path(state_dir, kind, grant_id).is_file()


def write_marker_once(state_dir: Path, kind: str, grant_id: str, payload: dict[str, Any]) -> None:
    directory = state_dir / kind
    ensure_private_dir(directory)
    path = marker_path(state_dir, kind, grant_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


def validate_authenticated_body(body: dict[str, Any]) -> None:
    missing = BODY_FIELDS - set(body)
    if missing:
        raise CapabilityError("capability_missing_fields")
    if set(body) - BODY_FIELDS:
        raise CapabilityError("capability_unknown_fields")
    if type(body["version"]) is not int:
        raise CapabilityError("invalid_version_type")
    if type(body["single_use"]) is not bool:
        raise CapabilityError("invalid_single_use_type")
    for field in BODY_STRING_FIELDS:
        if not isinstance(body[field], str):
            raise CapabilityError(f"invalid_{field}_type")


def verify_capability(
    *, token: dict[str, Any], secret: str, requested: RequestScope, state_dir: Path,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS, now: datetime | None = None,
    consume: bool = True, max_ttl_seconds: int = DEFAULT_MAX_TTL_SECONDS,
) -> dict[str, Any]:
    secret = require_secret(secret)
    max_ttl_seconds = validate_max_ttl_seconds(max_ttl_seconds)
    ensure_private_dir(state_dir)
    now = (now or utc_now()).astimezone(timezone.utc)
    if (state_dir / "KILL_SWITCH").exists():
        raise CapabilityError("containment_kill_switch_active")
    if set(token) != {"body", "signature"} or not isinstance(token.get("body"), dict):
        raise CapabilityError("malformed_capability")
    body = token["body"]
    sig = token.get("signature")
    if not isinstance(sig, dict) or set(sig) != SIGNATURE_FIELDS:
        raise CapabilityError("malformed_signature")
    if sig.get("algorithm") != "hmac-sha256" or not isinstance(sig.get("value"), str):
        raise CapabilityError("malformed_signature")
    if not SIGNATURE_RE.fullmatch(sig["value"]):
        raise CapabilityError("malformed_signature")
    expected = sign(body, secret)
    if not hmac.compare_digest(expected, sig["value"]):
        raise CapabilityError("invalid_signature")

    validate_authenticated_body(body)
    if body["version"] != VERSION:
        raise CapabilityError("unsupported_capability_version")
    grant_id = safe_identifier("grant_id", body["grant_id"])
    safe_token("purpose", body["purpose"])
    safe_token("evidence_id", body["evidence_id"])
    if marker_exists(state_dir, "revoked", grant_id):
        raise CapabilityError("capability_revoked")
    if marker_exists(state_dir, "used", grant_id):
        raise CapabilityError("capability_replay")

    issued_at = parse_time(body["issued_at"])
    expires_at = parse_time(body["expires_at"])
    skew = timedelta(seconds=max(0, clock_skew_seconds))
    if issued_at - skew > now:
        raise CapabilityError("capability_not_yet_valid")
    if expires_at <= now:
        raise CapabilityError("capability_expired")
    if expires_at <= issued_at:
        raise CapabilityError("invalid_capability_window")
    if expires_at - issued_at > timedelta(seconds=max_ttl_seconds):
        raise CapabilityError("capability_ttl_exceeds_verifier_policy")

    token_scope = RequestScope.make(
        body["principal"], body["tool"], body["destination"],
        body["resource"], body["data_class"],
    )
    mismatches = [
        field for field in ("principal", "tool", "destination", "resource", "data_class")
        if getattr(token_scope, field) != getattr(requested, field)
    ]
    if mismatches:
        raise CapabilityError("scope_mismatch:" + ",".join(mismatches))

    receipt = {
        "decision": "ALLOW",
        "grant_id": grant_id,
        "token_sha256": token_digest(token),
        "principal": requested.principal,
        "tool": requested.tool,
        "destination": requested.destination,
        "resource": requested.resource,
        "data_class": requested.data_class,
        "evidence_id": body["evidence_id"],
        "verified_at": isoformat(now),
        "expires_at": body["expires_at"],
    }
    if body["single_use"] and consume:
        try:
            write_marker_once(state_dir, "used", grant_id, receipt)
        except FileExistsError as exc:
            raise CapabilityError("capability_replay") from exc
    if (state_dir / "KILL_SWITCH").exists():
        raise CapabilityError("containment_kill_switch_active")
    return receipt


def revoke(state_dir: Path, grant_id: str, reason: str) -> dict[str, Any]:
    ensure_private_dir(state_dir)
    payload = {"grant_id": safe_identifier("grant_id", grant_id), "reason": safe_token("reason", reason), "revoked_at": isoformat(utc_now())}
    try:
        write_marker_once(state_dir, "revoked", grant_id, payload)
    except FileExistsError:
        pass
    return payload


def set_kill_switch(state_dir: Path, active: bool, reason: str = "operator") -> None:
    ensure_private_dir(state_dir)
    path = state_dir / "KILL_SWITCH"
    if active:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="kill-", dir=state_dir)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                json.dump({"active": True, "reason": safe_token("reason", reason), "at": isoformat(utc_now())}, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    else:
        path.unlink(missing_ok=True)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CapabilityError("duplicate_json_key")
        result[key] = value
    return result


def parse_json_bytes(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_TOKEN_BYTES:
        raise CapabilityError("token_file_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityError("token_file_not_utf8") from exc
    data = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(data, dict):
        raise CapabilityError("json_object_required")
    return data


def load_json(path: str) -> dict[str, Any]:
    token_path = Path(path)
    if token_path.is_symlink():
        raise CapabilityError("token_file_symlink_forbidden")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(token_path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise CapabilityError("token_file_symlink_forbidden") from exc
        raise
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise CapabilityError("token_file_not_regular")
        if info.st_size > MAX_TOKEN_BYTES:
            raise CapabilityError("token_file_too_large")
        raw = handle.read(MAX_TOKEN_BYTES + 1)
    return parse_json_bytes(raw)


def load_json_stdin() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_TOKEN_BYTES + 1)
    return parse_json_bytes(raw)


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    verify = sub.add_parser("verify")
    for cmd in (issue, verify):
        cmd.add_argument("--principal", required=True)
        cmd.add_argument("--tool", required=True)
        cmd.add_argument("--destination", required=True)
        cmd.add_argument("--resource", required=True)
        cmd.add_argument("--data-class", required=True)
    issue.add_argument("--purpose", required=True)
    issue.add_argument("--evidence-id", required=True)
    issue.add_argument("--ttl", type=int, default=60)
    verify.add_argument("--token-stdin", action="store_true", required=True)
    rev = sub.add_parser("revoke")
    rev.add_argument("grant_id")
    rev.add_argument("--reason", default="operator")
    kill = sub.add_parser("kill")
    kill.add_argument("action", choices=("on", "off"))
    kill.add_argument("--reason", default="operator")
    sub.add_parser("status")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        state_dir = Path(os.getenv("HERMES_CONTAINMENT_STATE_DIR", ".hermes/containment"))
        if args.command == "issue":
            max_ttl_seconds = trusted_max_ttl_seconds()
            secret = require_secret(os.getenv("HERMES_CONTAINMENT_SECRET"))
            scope = RequestScope.make(args.principal, args.tool, args.destination, args.resource, args.data_class)
            emit(issue_capability(
                secret=secret, scope=scope, purpose=args.purpose, evidence_id=args.evidence_id,
                ttl_seconds=args.ttl, max_ttl_seconds=max_ttl_seconds, single_use=True,
            ))
        elif args.command == "verify":
            max_ttl_seconds = trusted_max_ttl_seconds()
            secret = require_secret(os.getenv("HERMES_CONTAINMENT_SECRET"))
            requested = RequestScope.make(args.principal, args.tool, args.destination, args.resource, args.data_class)
            emit(verify_capability(
                token=load_json_stdin(), secret=secret, requested=requested,
                state_dir=state_dir, consume=True, max_ttl_seconds=max_ttl_seconds,
            ))
        elif args.command == "revoke":
            emit(revoke(state_dir, args.grant_id, args.reason))
        elif args.command == "kill":
            set_kill_switch(state_dir, args.action == "on", args.reason)
            emit({"kill_switch": args.action})
        elif args.command == "status":
            ensure_private_dir(state_dir)
            emit({
                "state_dir": str(state_dir),
                "kill_switch": (state_dir / "KILL_SWITCH").exists(),
                "used": len(list((state_dir / "used").glob("*.json"))) if (state_dir / "used").exists() else 0,
                "revoked": len(list((state_dir / "revoked").glob("*.json"))) if (state_dir / "revoked").exists() else 0,
            })
        return 0
    except (CapabilityError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"decision": "DENY", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
