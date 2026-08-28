#!/usr/bin/env python3
"""Hermes Outbound Executor hardened execution boundary.

The legacy campaign-policy implementation is retained in an internal core, while
this public entrypoint enforces authenticated human approval, a consumed exact
Containment Gateway capability, and an atomic campaign/prospect claim before any
SMTP externalization. Request-time policy-off switches are removed.
"""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import os
import socket
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load_module("hermes_outbound_executor_core", HERE / "outbound-executor-core.py")
approval_security = load_module("hermes_approval_security", HERE / "approval-security.py")
containment = load_module("hermes_outbound_containment", HERE / "containment-gateway.py")
externalization = load_module("hermes_externalization_claim", HERE / "externalization-claim.py")

_original_load_approval = core.load_approval
_original_build_parser = core.build_parser
_original_send_smtp = core.send_smtp


def secure_load_approval(root: Path, approval_id: str) -> dict[str, Any]:
    receipt = _original_load_approval(root, approval_id)
    try:
        approval_security.verify_receipt(receipt)
    except approval_security.ApprovalSecurityError as exc:
        raise SystemExit(f"approval receipt authentication failed: {exc}") from exc
    return receipt


def remove_option(parser: argparse.ArgumentParser, option: str) -> None:
    action = next((a for a in parser._actions if option in a.option_strings), None)
    if action is None:
        return
    parser._remove_action(action)
    for item in action.option_strings:
        parser._option_string_actions.pop(item, None)


def child_parser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices[name]


def hardened_build_parser() -> argparse.ArgumentParser:
    parser = _original_build_parser()
    validate = child_parser(parser, "validate-handoff")
    send = child_parser(parser, "send")
    for child in (validate, send):
        remove_option(child, "--allow-duplicate")
        child.set_defaults(allow_duplicate=False)
    transport = next(a for a in send._actions if "--transport" in a.option_strings)
    transport.choices = ["smtp"]
    send.add_argument(
        "--containment-token-stdin",
        action="store_true",
        required=True,
        help="Read the single-use signed containment capability from stdin.",
    )
    return parser


def smtp_destination(host: str, port: int) -> str:
    host = host.strip()
    if not host:
        raise SystemExit("SMTP host is required")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SystemExit(f"SMTP destination DNS resolution failed: {exc}") from exc
    if not infos:
        raise SystemExit("SMTP destination resolved to no addresses")
    for info in infos:
        raw = info[4][0].split("%", 1)[0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SystemExit("SMTP destination returned an invalid IP address") from exc
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
            or addr.is_reserved
        ):
            raise SystemExit(f"SMTP destination resolved to non-public address: {addr}")
    return containment.canonical_destination(f"tcp://{host}:{port}")


def verify_send_capability(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not bool(getattr(args, "containment_token_stdin", False)):
        raise SystemExit("containment token from stdin is required")
    host = os.environ.get("HERMES_SMTP_HOST", "")
    port = int(os.environ.get("HERMES_SMTP_PORT", "587"))
    destination = smtp_destination(host, port)
    recipient = str(validation.get("contact_ref") or "")
    if "@" not in recipient:
        raise SystemExit("SMTP containment scope requires an email recipient")
    requested = containment.RequestScope.make(
        "revenue-os:outbound-executor",
        "outbound:smtp",
        destination,
        f"recipient:{recipient}",
        "INTERNAL",
    )
    token = containment.load_json_stdin()
    try:
        receipt = containment.verify_capability(
            token=token,
            secret=containment.require_secret(os.getenv("HERMES_CONTAINMENT_SECRET")),
            requested=requested,
            state_dir=Path(os.getenv("HERMES_CONTAINMENT_STATE_DIR", ".hermes/containment")),
            consume=True,
            max_ttl_seconds=containment.trusted_max_ttl_seconds(),
        )
    except containment.CapabilityError as exc:
        raise SystemExit(f"containment capability denied: {exc}") from exc
    body = token.get("body", {})
    if body.get("purpose") != "outbound-send":
        raise SystemExit("containment capability denied: purpose mismatch")
    if body.get("evidence_id") != str(args.approval_id):
        raise SystemExit("containment capability denied: approval evidence mismatch")
    return receipt


def hardened_send_smtp(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    # Repeat destination validation immediately before connecting. An external
    # egress proxy remains the production defense against DNS rebinding between
    # resolution and connect.
    host = os.environ.get("HERMES_SMTP_HOST", "")
    port = int(os.environ.get("HERMES_SMTP_PORT", "587"))
    smtp_destination(host, port)
    return _original_send_smtp(validation, args)


def acquire_claim(validation: dict[str, Any]) -> dict[str, Any]:
    try:
        return externalization.acquire(
            "smtp",
            str(validation["campaign_id"]),
            str(validation["prospect_id"]),
        )
    except externalization.ExternalizationClaimError as exc:
        raise SystemExit(f"externalization claim denied: {exc}") from exc


def hardened_cmd_send(args: argparse.Namespace) -> int:
    if args.transport != "smtp":
        raise SystemExit("only SMTP transport is permitted at the outbound execution boundary")
    # One immutable-in-memory validation snapshot is used for authorization,
    # transport construction, receipts, and sent-stage attribution. Do not
    # re-read caller-writable handoff/policy files after capability consumption.
    validation = core.validate_send(args)
    if not validation["valid"]:
        raise SystemExit("send validation failed: " + "; ".join(validation["errors"]))
    containment_receipt = verify_send_capability(validation, args)
    claim = acquire_claim(validation)
    transport_receipt = core.send_smtp(validation, args)
    root = Path(args.root)
    send_id = "send_" + core.sha256_json(
        {
            "campaign_id": validation["campaign_id"],
            "prospect_id": validation["prospect_id"],
            "message_hash": validation["message_hash"],
            "sent_at": core.utc_now(),
        }
    )[:20]
    receipt_path = core.outbound_dir(root) / "send-receipts" / f"{send_id}.json"
    receipt = {
        "schema_version": "outbound-send-receipt-v1",
        "send_id": send_id,
        "send_status": "sent",
        "sent_at": core.utc_now(),
        "campaign_id": validation["campaign_id"],
        "experiment_id": validation["experiment_id"],
        "prospect_id": validation["prospect_id"],
        "business_name": validation["business_name"],
        "approval_id": args.approval_id,
        "campaign_policy_hash": validation["policy"]["campaign_policy_hash"],
        "message_hash": validation["message_hash"],
        "message_subject": validation["message_subject"],
        "transport": transport_receipt["transport"],
        "transport_receipt": transport_receipt,
        "containment_grant_id": containment_receipt["grant_id"],
        "containment_token_sha256": containment_receipt["token_sha256"],
        "externalization_claim_id": claim["claim_id"],
        "send_receipt_path": str(receipt_path),
    }
    receipt["send_receipt_hash"] = core.sha256_json(receipt)
    core.write_json(receipt_path, receipt)
    core.append_jsonl(core.send_receipts_path(root), receipt)
    core.record_sent_stage(validation, args, receipt)
    try:
        externalization.complete(claim, str(receipt_path), receipt["send_receipt_hash"])
    except externalization.ExternalizationClaimError as exc:
        # Externalization already happened. Keep the permanent claim and fail
        # visibly so governance reconciles the evidence instead of retrying.
        raise SystemExit(f"send completed but claim finalization failed: {exc}") from exc
    print(core.json.dumps({"schema_version": "outbound-send-result-v1", "sent": True, "send_id": send_id, "send_receipt": str(receipt_path)}, indent=2, sort_keys=True))
    return 0


core.load_approval = secure_load_approval
core.build_parser = hardened_build_parser
core.send_smtp = hardened_send_smtp
core.cmd_send = hardened_cmd_send

for _name in dir(core):
    if not _name.startswith("_"):
        globals()[_name] = getattr(core, _name)

load_approval = secure_load_approval
build_parser = hardened_build_parser
send_smtp = hardened_send_smtp
cmd_send = hardened_cmd_send


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
