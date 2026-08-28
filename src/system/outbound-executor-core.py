#!/usr/bin/env python3
"""Hermes Outbound Executor v1.

Campaign-policy-gated outbound execution for Revenue OS.

This is the first real execution-channel boundary after Local Service Funnel:
it verifies campaign approval, evidence, channel/scope constraints, duplicate
prevention, and transport success before recording a `sent` stage. It does not
discover prospects, rewrite offers, buy anything, change accounts, enter
credentials, or bypass policy.
"""

from __future__ import annotations

import argparse
import email.message
import hashlib
import json
import os
import re
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ALLOWED_APPROVAL_ACTIONS = {"send", "outreach", "external_message"}
DEFAULT_ALLOWED_INDUSTRIES = [
    "plumbing",
    "plumbing_hvac",
    "hvac",
    "hvac_plumbing",
    "roofing",
    "garage_door",
    "garage_door_gate",
    "garage_door_commercial_door",
    "electrical",
    "pest_control",
]
DEFAULT_AUTONOMOUS_CHANNELS = ["email", "business_email"]
DEFAULT_HANDOFF_ONLY_CHANNELS = ["contact_form"]
PROHIBITED_CHANNELS = {"sms", "personal_email", "social_dm", "phone", "personal_phone"}


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return utc_now_dt().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1] + "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def revenue_root() -> Path:
    return Path(os.environ.get("HERMES_REVENUE_OS_DIR", ".hermes/revenue-os"))


def policies_dir(root: Path) -> Path:
    return root / "campaign-policies"


def approvals_dir(root: Path) -> Path:
    return root / "approval-receipts"


def outbound_dir(root: Path) -> Path:
    return root / "outbound"


def send_receipts_path(root: Path) -> Path:
    return outbound_dir(root) / "send-receipts.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                rows.append(data)
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def load_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                if isinstance(data.get("prospects"), list):
                    return [item for item in data["prospects"] if isinstance(item, dict)]
                return [data]
        except json.JSONDecodeError:
            pass
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            rows.append(data)
    return rows


def prospect_id(prospect: dict[str, Any]) -> str:
    if prospect.get("prospect_id"):
        return str(prospect["prospect_id"])
    return "pros_" + sha256_json(
        {
            "business_name": prospect.get("business_name") or prospect.get("name"),
            "website": prospect.get("website"),
            "city": prospect.get("city"),
            "category": prospect.get("category"),
        }
    )[:16]


def load_prospect(path: str, pid: str) -> dict[str, Any]:
    if not path:
        return {}
    prospects_file = Path(path)
    if not prospects_file.is_file():
        raise SystemExit(f"prospects file not found: {path}")
    for item in load_json_or_jsonl(prospects_file):
        if prospect_id(item) == pid:
            return item
    raise SystemExit(f"prospect not found in prospects file: {pid}")


def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def parse_outreach(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"outreach draft not found: {path}")
    text = path.read_text(encoding="utf-8")
    subject = markdown_section(text, "Subject").strip()
    body = markdown_section(text, "Draft").strip()
    if not subject or not body:
        raise SystemExit(f"outreach draft missing Subject or Draft section: {path}")
    return {"subject": subject, "body": body, "message_hash": sha256_text(subject + "\n\n" + body)}


def audit_has_source(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"(?im)^-\s+source:\s+\S+", text))


def validate_no_unsupported_claims(message: dict[str, str]) -> list[str]:
    combined = f"{message['subject']}\n{message['body']}".lower()
    risky_patterns = {
        "losing calls": "unsupported lost-call claim",
        "losing leads": "unsupported lost-lead claim",
        "lost revenue": "unsupported lost-revenue claim",
        "poor follow-up": "unsupported poor-follow-up claim",
        "missed calls": "unsupported missed-call claim",
        "missed leads": "unsupported missed-lead claim",
    }
    return [reason for pattern, reason in risky_patterns.items() if pattern in combined]


def policy_hash(policy: dict[str, Any]) -> str:
    body = {k: v for k, v in policy.items() if k != "campaign_policy_hash"}
    return sha256_json(body)


def create_policy(args: argparse.Namespace) -> dict[str, Any]:
    created_at = utc_now()
    expires_at = args.expires_at or (utc_now_dt() + timedelta(days=args.ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    allowed_industries = args.allowed_industry or DEFAULT_ALLOWED_INDUSTRIES
    autonomous_channels = args.allowed_autonomous_channel or args.allowed_channel or DEFAULT_AUTONOMOUS_CHANNELS
    handoff_only_channels = args.handoff_only_channel or DEFAULT_HANDOFF_ONLY_CHANNELS
    autonomous_set = set(autonomous_channels)
    handoff_only_set = set(handoff_only_channels)
    overlap = autonomous_set & handoff_only_set
    if overlap:
        raise SystemExit(f"channels cannot be both autonomous and handoff-only: {', '.join(sorted(overlap))}")
    policy = {
        "schema_version": "hermes-campaign-policy-v1",
        "campaign_id": args.campaign_id or f"camp_{args.experiment_id}",
        "experiment_id": args.experiment_id,
        "offer": args.offer,
        "geography": args.geography,
        "max_sends": int(args.max_sends),
        "max_messages_per_business": int(args.max_messages_per_business),
        "allowed_industries": sorted(set(allowed_industries)),
        "allowed_autonomous_channels": sorted(autonomous_set),
        "handoff_only_channels": sorted(handoff_only_set),
        "allowed_channels": sorted(autonomous_set),
        "prohibited_channels": sorted(PROHIBITED_CHANNELS),
        "paid_spend_usd": float(args.paid_spend_usd),
        "evidence_requirement": {
            "minimum_public_sources": int(args.minimum_public_sources),
            "require_audit_source": bool(args.require_audit_source),
            "forbid_unsupported_claims": True,
        },
        "follow_up_policy": {
            "allowed": bool(args.allow_follow_up),
            "maximum_follow_ups": int(args.maximum_follow_ups),
            "minimum_wait_business_days": int(args.minimum_wait_business_days),
        },
        "stop_conditions": [
            "campaign_send_limit_reached",
            "duplicate_prospect_send_attempt",
            "complaint_threshold_reached",
            "bounce_threshold_reached",
            "factual_validation_failure",
            "approval_expired_or_missing",
            "policy_expired",
        ],
        "created_at": created_at,
        "expires_at": expires_at,
    }
    policy["campaign_policy_hash"] = policy_hash(policy)
    return policy


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    policies_dir(root).mkdir(parents=True, exist_ok=True)
    outbound_dir(root).mkdir(parents=True, exist_ok=True)
    send_receipts_path(root).touch(exist_ok=True)
    print(
        json.dumps(
            {
                "schema_version": "outbound-executor-init-v1",
                "root": str(root),
                "campaign_policies": str(policies_dir(root)),
                "send_receipts": str(send_receipts_path(root)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_create_policy(args: argparse.Namespace) -> int:
    root = Path(args.root)
    policy = create_policy(args)
    path = policies_dir(root) / f"{policy['campaign_id']}.json"
    if path.exists() and not args.overwrite:
        raise SystemExit(f"campaign policy already exists: {path}")
    write_json(path, policy)
    print(
        json.dumps(
            {
                "schema_version": "campaign-policy-create-result-v1",
                "campaign_id": policy["campaign_id"],
                "campaign_policy": str(path),
                "campaign_policy_hash": policy["campaign_policy_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def load_policy(path: str) -> dict[str, Any]:
    policy = read_json(Path(path))
    if not policy:
        raise SystemExit(f"campaign policy not found: {path}")
    actual = policy_hash(policy)
    if policy.get("campaign_policy_hash") != actual:
        raise SystemExit("campaign policy hash mismatch")
    return policy


def load_approval(root: Path, approval_id: str) -> dict[str, Any]:
    path = approvals_dir(root) / f"{approval_id}.json"
    receipt = read_json(path)
    if not receipt:
        raise SystemExit(f"approval receipt not found: {approval_id}")
    actual = sha256_json({k: v for k, v in receipt.items() if k != "approval_receipt_hash"})
    if receipt.get("approval_receipt_hash") != actual:
        raise SystemExit("approval receipt hash mismatch")
    return receipt


def current_sends(root: Path, campaign_id: str) -> list[dict[str, Any]]:
    return [row for row in read_jsonl(send_receipts_path(root)) if row.get("campaign_id") == campaign_id and row.get("send_status") == "sent"]


def validate_policy_receipt(policy: dict[str, Any], receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("experiment_id") != policy.get("experiment_id"):
        errors.append("approval experiment mismatch")
    if receipt.get("action") not in ALLOWED_APPROVAL_ACTIONS:
        errors.append("approval action does not authorize outbound send")
    if receipt.get("policy_hash") != policy.get("campaign_policy_hash"):
        errors.append("approval policy hash does not match campaign policy hash")
    expires_at = parse_ts(str(receipt.get("expires_at") or ""))
    if not expires_at or expires_at <= utc_now_dt():
        errors.append("approval receipt expired")
    return errors


def validate_send(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    policy = load_policy(args.campaign_policy)
    receipt = load_approval(root, args.approval_id)
    handoff = read_json(Path(args.handoff))
    if not handoff:
        raise SystemExit(f"handoff not found: {args.handoff}")
    message = parse_outreach(Path(handoff.get("outreach_draft", "")))
    prospect = load_prospect(args.prospects_file, str(handoff.get("prospect_id", ""))) if args.prospects_file else {}
    errors = validate_policy_receipt(policy, receipt)
    now = utc_now_dt()
    policy_expires = parse_ts(str(policy.get("expires_at") or ""))
    if not policy_expires or policy_expires <= now:
        errors.append("campaign policy expired")
    if handoff.get("experiment_id") != policy.get("experiment_id"):
        errors.append("handoff experiment mismatch")
    if handoff.get("approval_required") is not True:
        errors.append("handoff does not declare approval requirement")
    if handoff.get("allowed_to_send") is True:
        errors.append("handoff should not self-authorize sending")
    if policy.get("offer") and policy.get("offer") != read_plan_offer(root, str(policy["experiment_id"])):
        # This catches accidental policy/plan drift while still allowing tests
        # using explicit offers in isolated temp roots.
        errors.append("campaign offer does not match experiment plan offer")
    contact_channel = str(handoff.get("contact_channel") or "")
    autonomous_channels = set(policy.get("allowed_autonomous_channels") or policy.get("allowed_channels", []))
    handoff_only_channels = set(policy.get("handoff_only_channels", []))
    if contact_channel in handoff_only_channels:
        errors.append(f"contact channel is handoff-only, not autonomous: {contact_channel}")
    elif contact_channel not in autonomous_channels:
        errors.append(f"contact channel not allowed: {contact_channel}")
    if contact_channel in set(policy.get("prohibited_channels", [])):
        errors.append(f"contact channel prohibited: {contact_channel}")
    if not handoff.get("contact_ref"):
        errors.append("handoff missing contact_ref")
    if not audit_has_source(Path(handoff.get("audit", ""))) and policy.get("evidence_requirement", {}).get("require_audit_source", True):
        errors.append("audit does not contain a source reference")
    unsupported = validate_no_unsupported_claims(message)
    if unsupported and policy.get("evidence_requirement", {}).get("forbid_unsupported_claims", True):
        errors.extend(unsupported)
    category = str(prospect.get("category") or "")
    allowed_industries = set(policy.get("allowed_industries", []))
    if allowed_industries:
        if not args.prospects_file:
            errors.append("prospects_file required to verify allowed industry")
        elif category not in allowed_industries:
            errors.append(f"industry not allowed: {category}")
    if prospect:
        source_url = prospect.get("source_url") or prospect.get("url") or ""
        evidence_refs = prospect.get("evidence_refs") if isinstance(prospect.get("evidence_refs"), list) else []
        source_count = int(bool(source_url)) + sum(1 for item in evidence_refs if isinstance(item, dict) and (item.get("ref") or item.get("url")))
        if source_count < int(policy.get("evidence_requirement", {}).get("minimum_public_sources", 1)):
            errors.append("insufficient public source evidence")
    send_rows = current_sends(root, str(policy["campaign_id"]))
    if len(send_rows) >= int(policy.get("max_sends", 0)):
        errors.append("campaign send limit reached")
    prospect_sends = [row for row in send_rows if row.get("prospect_id") == handoff.get("prospect_id")]
    if prospect_sends and not args.allow_duplicate:
        errors.append("duplicate prospect send attempt")
    return {
        "schema_version": "outbound-send-validation-v1",
        "valid": not errors,
        "errors": errors,
        "campaign_id": policy.get("campaign_id"),
        "experiment_id": policy.get("experiment_id"),
        "prospect_id": handoff.get("prospect_id"),
        "business_name": handoff.get("business_name"),
        "contact_channel": handoff.get("contact_channel"),
        "contact_ref": handoff.get("contact_ref"),
        "message_hash": message["message_hash"],
        "message_subject": message["subject"],
        "policy": policy,
        "approval_receipt": receipt,
        "handoff": handoff,
        "message": message,
    }


def read_plan_offer(root: Path, experiment_id: str) -> str:
    plan = read_json(root / "experiments" / experiment_id / "experiment-plan.json")
    return str(plan.get("offer") or "")


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_send(args)
    print(json.dumps({k: v for k, v in result.items() if k not in {"policy", "approval_receipt", "handoff", "message"}}, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


def send_smtp(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    host = os.environ.get("HERMES_SMTP_HOST", "")
    user = os.environ.get("HERMES_SMTP_USER", "")
    password = os.environ.get("HERMES_SMTP_PASSWORD", "")
    sender = os.environ.get("HERMES_SMTP_FROM", user)
    port = int(os.environ.get("HERMES_SMTP_PORT", "587"))
    if not host or not sender:
        raise SystemExit("SMTP transport requires HERMES_SMTP_HOST and HERMES_SMTP_FROM/HERMES_SMTP_USER")
    recipient = str(validation["contact_ref"])
    if "@" not in recipient:
        raise SystemExit("SMTP transport requires an email contact_ref")
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = validation["message"]["subject"]
    msg.set_content(validation["message"]["body"])
    with smtplib.SMTP(host, port, timeout=args.timeout_seconds) as smtp:
        smtp.starttls()
        if user or password:
            smtp.login(user, password)
        smtp.send_message(msg)
    return {"transport": "smtp", "recipient": recipient, "sender": sender}


def send_sendmail(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    recipient = str(validation["contact_ref"])
    if "@" not in recipient:
        raise SystemExit("sendmail transport requires an email contact_ref")
    sendmail_cmd = os.environ.get("HERMES_SENDMAIL_CMD", "sendmail")
    msg = email.message.EmailMessage()
    sender = os.environ.get("HERMES_SENDMAIL_FROM", "hermes@localhost")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = validation["message"]["subject"]
    msg.set_content(validation["message"]["body"])
    proc = subprocess.run([sendmail_cmd, recipient], input=msg.as_string(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout_seconds, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or "sendmail transport failed")
    return {"transport": "sendmail", "recipient": recipient, "sender": sender}


def record_sent_stage(validation: dict[str, Any], args: argparse.Namespace, send_receipt: dict[str, Any]) -> None:
    funnel = Path(args.repo_root) / "src/system/local-service-funnel.py"
    if not funnel.is_file():
        raise SystemExit("local-service-funnel.py not found for sent-stage recording")
    cmd = [
        sys.executable,
        str(funnel),
        "--root",
        str(args.root),
        "--repo-root",
        str(args.repo_root),
        "record-stage",
        "--experiment-id",
        str(validation["experiment_id"]),
        "--prospect-id",
        str(validation["prospect_id"]),
        "--business-name",
        str(validation["business_name"]),
        "--stage",
        "sent",
        "--approval-id",
        str(args.approval_id),
        "--evidence-ref",
        f"send_receipt={send_receipt['send_receipt_path']}",
        "--evidence-ref",
        f"message_hash={send_receipt['message_hash']}",
        "--notes",
        f"Outbound executor recorded successful {send_receipt['transport']} send",
    ]
    proc = subprocess.run(cmd, cwd=args.repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or "failed to record sent stage")


def cmd_send(args: argparse.Namespace) -> int:
    validation = validate_send(args)
    if not validation["valid"]:
        raise SystemExit("send validation failed: " + "; ".join(validation["errors"]))
    if args.transport == "smtp":
        transport_receipt = send_smtp(validation, args)
    elif args.transport == "sendmail":
        transport_receipt = send_sendmail(validation, args)
    else:
        raise SystemExit(f"unsupported send transport: {args.transport}")
    root = Path(args.root)
    send_id = "send_" + sha256_json(
        {
            "campaign_id": validation["campaign_id"],
            "prospect_id": validation["prospect_id"],
            "message_hash": validation["message_hash"],
            "sent_at": utc_now(),
        }
    )[:20]
    receipt_path = outbound_dir(root) / "send-receipts" / f"{send_id}.json"
    receipt = {
        "schema_version": "outbound-send-receipt-v1",
        "send_id": send_id,
        "send_status": "sent",
        "sent_at": utc_now(),
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
        "send_receipt_path": str(receipt_path),
    }
    receipt["send_receipt_hash"] = sha256_json(receipt)
    write_json(receipt_path, receipt)
    append_jsonl(send_receipts_path(root), receipt)
    record_sent_stage(validation, args, receipt)
    print(json.dumps({"schema_version": "outbound-send-result-v1", "sent": True, "send_id": send_id, "send_receipt": str(receipt_path)}, indent=2, sort_keys=True))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(revenue_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))


def add_send_args(parser: argparse.ArgumentParser) -> None:
    add_common(parser)
    parser.add_argument("--campaign-policy", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--prospects-file", default="")
    parser.add_argument("--allow-duplicate", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Outbound Executor v1")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_common(init)
    init.set_defaults(func=cmd_init)

    policy = sub.add_parser("create-campaign-policy")
    add_common(policy)
    policy.add_argument("--campaign-id", default="")
    policy.add_argument("--experiment-id", required=True)
    policy.add_argument("--offer", required=True)
    policy.add_argument("--geography", default="Inland Empire, CA")
    policy.add_argument("--max-sends", type=int, default=10)
    policy.add_argument("--max-messages-per-business", type=int, default=1)
    policy.add_argument("--allowed-industry", action="append", default=[])
    policy.add_argument("--allowed-channel", action="append", default=[], help="Backward-compatible alias for --allowed-autonomous-channel")
    policy.add_argument("--allowed-autonomous-channel", action="append", default=[])
    policy.add_argument("--handoff-only-channel", action="append", default=[])
    policy.add_argument("--paid-spend-usd", type=float, default=0.0)
    policy.add_argument("--minimum-public-sources", type=int, default=1)
    policy.add_argument("--require-audit-source", action=argparse.BooleanOptionalAction, default=True)
    policy.add_argument("--allow-follow-up", action=argparse.BooleanOptionalAction, default=True)
    policy.add_argument("--maximum-follow-ups", type=int, default=1)
    policy.add_argument("--minimum-wait-business-days", type=int, default=3)
    policy.add_argument("--ttl-days", type=int, default=14)
    policy.add_argument("--expires-at", default="")
    policy.add_argument("--overwrite", action="store_true")
    policy.set_defaults(func=cmd_create_policy)

    validate = sub.add_parser("validate-handoff")
    add_send_args(validate)
    validate.set_defaults(func=cmd_validate)

    send = sub.add_parser("send")
    add_send_args(send)
    send.add_argument("--transport", choices=["smtp", "sendmail"], required=True)
    send.set_defaults(func=cmd_send)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
