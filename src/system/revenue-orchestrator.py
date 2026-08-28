#!/usr/bin/env python3
"""Hermes Revenue Orchestrator v1.

Selects one eligible Revenue OS opportunity and turns it into a bounded,
ledger-tracked experiment plan. This is a local planner only: it does not send,
post, purchase, change accounts, enter credentials, or perform platform actions.
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


AUTONOMOUS_ACTIONS = {
    "public_research",
    "analysis",
    "drafting",
    "local_artifact_generation",
    "lead_scoring",
    "reporting",
    "ledger_entry",
}

APPROVAL_REQUIRED_ACTIONS = {
    "send",
    "post",
    "outreach",
    "purchase",
    "payment",
    "credential_use",
    "account_modification",
    "permission_change",
    "external_message",
    "paid_spend",
}

PROHIBITED_ACTIONS = {
    "credential_theft",
    "stealth",
    "persistence",
    "unapproved_send",
    "unapproved_post",
    "unapproved_purchase",
    "privacy_or_security_change_without_approval",
    "destructive_action_without_approval",
}


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


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def revenue_root() -> Path:
    return Path(os.environ.get("HERMES_REVENUE_OS_DIR", ".hermes/revenue-os"))


def queue_path(root: Path) -> Path:
    return root / "opportunity-queue.jsonl"


def ledger_opportunities_path(root: Path) -> Path:
    return root / "opportunities.jsonl"


def experiments_dir(root: Path) -> Path:
    return root / "experiments"


def reports_dir(root: Path) -> Path:
    return root / "reports" / "revenue-orchestrator"


def approval_receipts_dir(root: Path) -> Path:
    return root / "approval-receipts"


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


def load_policy(path: Path) -> dict[str, Any]:
    default = {
        "budgets": {
            "monthly_ai_budget_usd": 50,
            "daily_experiment_budget_usd": 3,
            "maximum_paid_spend_without_human_approval_usd": 0,
            "maximum_external_messages_without_human_approval": 0,
        },
        "approval_required": sorted(APPROVAL_REQUIRED_ACTIONS),
        "allowed_without_approval": sorted(AUTONOMOUS_ACTIONS),
    }
    loaded = read_json(path)
    if not loaded:
        return default
    merged = dict(default)
    merged.update(loaded)
    merged["budgets"] = {**default["budgets"], **loaded.get("budgets", {})}
    return merged


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_expired(item: dict[str, Any]) -> bool:
    expires = parse_ts(str(item.get("expires_at", "")))
    return bool(expires and expires < utc_now_dt())


def merge_opportunities(root: Path) -> list[dict[str, Any]]:
    queue_rows = read_jsonl(queue_path(root))
    ledger_rows = read_jsonl(ledger_opportunities_path(root))
    ledger_by_id = {str(row.get("opportunity_id")): row for row in ledger_rows if row.get("opportunity_id")}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in queue_rows:
        opp_id = str(row.get("opportunity_id", ""))
        if not opp_id:
            continue
        item = dict(row)
        ledger = ledger_by_id.get(opp_id)
        if ledger:
            item["ledger_backed"] = True
            item["ledger_opportunity_hash"] = ledger.get("opportunity_hash", "")
            item["ledger_record"] = {
                "opportunity_hash": ledger.get("opportunity_hash", ""),
                "memory_status": ledger.get("memory_status", ""),
            }
        else:
            item["ledger_backed"] = False
        merged.append(item)
        seen.add(opp_id)
    for opp_id, ledger in ledger_by_id.items():
        if opp_id in seen:
            continue
        item = dict(ledger)
        item["ledger_backed"] = True
        item["ledger_opportunity_hash"] = ledger.get("opportunity_hash", "")
        if item.get("evidence_refs") and not item.get("evidence_validation"):
            item["evidence_validation"] = {"status": "ledger_evidence"}
        merged.append(item)
    return merged


def eligibility_reasons(item: dict[str, Any], args: argparse.Namespace) -> list[str]:
    reasons: list[str] = []
    if args.require_ledger and not item.get("ledger_backed"):
        reasons.append("not_ledger_backed")
    if is_expired(item):
        reasons.append("expired")
    evidence_status = str(item.get("evidence_validation", {}).get("status", "unknown"))
    if evidence_status == "insufficient":
        reasons.append("insufficient_evidence")
    if float_value(item.get("confidence")) < args.min_confidence:
        reasons.append("low_confidence")
    if float_value(item.get("compliance_risk")) > args.max_compliance_risk:
        reasons.append("compliance_risk_too_high")
    if float_value(item.get("execution_risk")) > args.max_execution_risk:
        reasons.append("execution_risk_too_high")
    if float_value(item.get("expected_profit")) <= 0:
        reasons.append("nonpositive_expected_profit")
    if float_value(item.get("expected_cost")) > args.max_budget_request:
        reasons.append("budget_request_too_high")
    return reasons


def sorted_eligible(root: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in merge_opportunities(root):
        reasons = eligibility_reasons(item, args)
        if reasons:
            rejected.append({"opportunity_id": item.get("opportunity_id"), "reasons": reasons})
        else:
            eligible.append(item)
    eligible.sort(
        key=lambda row: (
            float_value(row.get("expected_value_score", row.get("expected_value"))),
            float_value(row.get("confidence")),
            float_value(row.get("expected_profit")),
        ),
        reverse=True,
    )
    return eligible, rejected


def workflow_steps(item: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    autonomous = [
        {"class": "AUTONOMOUS", "action": "public_research", "description": "Collect public evidence about the customer segment and channel."},
        {"class": "AUTONOMOUS", "action": "analysis", "description": "Qualify the opportunity against the stated problem and evidence."},
        {"class": "AUTONOMOUS", "action": "drafting", "description": "Draft a tailored audit, offer, and follow-up sequence locally."},
        {"class": "AUTONOMOUS", "action": "local_artifact_generation", "description": "Create local artifacts for review and attribution."},
        {"class": "AUTONOMOUS", "action": "ledger_entry", "description": "Record experiment events and outcomes in Revenue Ledger."},
    ]
    approval = [
        {"class": "APPROVAL_REQUIRED", "action": "outreach", "description": "Any outbound message to a prospect requires an approval receipt.", "approval_id": ""},
        {"class": "APPROVAL_REQUIRED", "action": "send", "description": "Sending prepared outreach requires an approval receipt.", "approval_id": ""},
    ]
    if float_value(item.get("expected_cost")) > 0:
        approval.append(
            {
                "class": "APPROVAL_REQUIRED",
                "action": "paid_spend",
                "description": "Any nonzero paid spend requires an approval receipt.",
                "approval_id": "",
            }
        )
    prohibited = [{"class": "PROHIBITED", "action": action, "description": "Outside declared Revenue OS policy."} for action in sorted(PROHIBITED_ACTIONS)]
    return autonomous, approval, prohibited


def build_plan(item: dict[str, Any], policy: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    created_at = utc_now()
    expires_dt = utc_now_dt() + timedelta(days=args.plan_ttl_days)
    experiment_id = args.experiment_id or "exp_" + sha256_json(
        {
            "opportunity_id": item.get("opportunity_id"),
            "created_at": created_at,
            "expected_value_score": item.get("expected_value_score", item.get("expected_value")),
        }
    )[:20]
    autonomous, approval, prohibited = workflow_steps(item)
    budget_requested = max(0.0, float_value(item.get("expected_cost")))
    plan = {
        "schema_version": "revenue-experiment-plan-v1",
        "experiment_id": experiment_id,
        "opportunity_id": item.get("opportunity_id"),
        "objective": args.objective
        or f"Test whether {item.get('offer')} can create qualified demand from {item.get('customer_segment', item.get('customer'))}.",
        "offer": item.get("offer"),
        "customer_segment": item.get("customer_segment", item.get("customer")),
        "channel": item.get("channel"),
        "hypothesis": args.hypothesis
        or f"If Hermes prepares a specific local audit for {item.get('customer_segment', item.get('customer'))}, the offer can generate a qualified lead without unapproved external action.",
        "expected_profit": float_value(item.get("expected_profit")),
        "expected_value_score": float_value(item.get("expected_value_score", item.get("expected_value"))),
        "confidence": float_value(item.get("confidence")),
        "budget_requested": budget_requested,
        "maximum_loss": budget_requested,
        "timebox_days": args.timebox_days,
        "success_threshold": args.success_threshold or "At least one qualified lead, booked call, paid conversion, or explicit validated learning event.",
        "stop_conditions": [
            "timebox_exceeded",
            "maximum_loss_reached",
            "approval_denied_or_expired",
            "compliance_risk_increases",
            "no_qualified_signal_after_declared_sample",
        ],
        "workflow_steps": autonomous + approval,
        "local_automation_steps": autonomous,
        "approval_required_steps": approval,
        "prohibited_actions": prohibited,
        "attribution_fields": {
            "experiment_id": experiment_id,
            "workflow_id": args.workflow_id or f"wf_{item.get('business_model', 'revenue').replace(' ', '_')[:40]}",
            "offer_id": args.offer_id or "offer_" + sha256_json(str(item.get("offer")))[:12],
            "channel": item.get("channel"),
            "campaign": args.campaign or "orchestrator-v1",
            "asset_id": "",
            "lead_id": "",
            "customer_id": "",
        },
        "required_evidence": [
            "source-linked opportunity evidence",
            "local artifacts generated",
            "approval receipt before any approval-required action",
            "ledger events for leads, conversions, costs, and revenue",
        ],
        "approval_policy": {
            "approval_receipt_required": True,
            "human_approved_boolean_is_not_authority": True,
            "approval_receipt_fields": ["approval_id", "experiment_id", "action", "scope", "approved_at", "expires_at", "approver", "policy_hash"],
        },
        "opportunity_snapshot": item,
        "policy_hash": sha256_json(policy),
        "policy_path": args.policy,
        "created_at": created_at,
        "expires_at": expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    plan["experiment_plan_body_hash"] = sha256_json(plan)
    return plan


def persist_memory(repo_root: Path, artifact_path: Path, artifact_hash: str, status: str) -> tuple[str, str]:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return "", "disabled"
    memory = repo_root / "src/system/memory-fabric.py"
    if not memory.is_file():
        return "", "memory-fabric-missing"
    envelope = {
        "producer": "revenue-orchestrator",
        "objective": "revenue-os-experiment-planning",
        "input_hash": artifact_hash,
        "selected_agent": "revenue-orchestrator",
        "actions": [{"type": "experiment-plan", "path": str(artifact_path)}],
        "predicted_outcome": "eligible opportunity should become a bounded local experiment plan",
        "observed_outcome": f"experiment plan status={status}",
        "status": status,
        "evidence_refs": [{"type": "experiment-plan", "path": str(artifact_path), "sha256": artifact_hash}],
        "security_classification": "INTERNAL",
        "metadata": {
            "artifact_type": "revenue-experiment-plan",
            "approval_receipts_required": True,
            "profit_optimization": True,
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return "", proc.stderr.strip() or proc.stdout.strip()
    return proc.stdout.strip().partition("=")[2], "persisted"


def seal_plan(root: Path, repo_root: Path, plan: dict[str, Any], rejected: list[dict[str, Any]]) -> Path:
    exp_dir = experiments_dir(root) / str(plan["experiment_id"])
    tmp_dir = experiments_dir(root) / f".tmp-{plan['experiment_id']}"
    if exp_dir.exists() or tmp_dir.exists():
        raise SystemExit(f"experiment plan already exists: {exp_dir}")
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        plan_path = tmp_dir / "experiment-plan.json"
        write_json(plan_path, plan)
        plan_hash = sha256_file(plan_path)
        receipt = {
            "schema_version": "revenue-experiment-plan-receipt-v1",
            "experiment_id": plan["experiment_id"],
            "plan_path": str(exp_dir / "experiment-plan.json"),
            "plan_sha256": plan_hash,
            "created_at": utc_now(),
            "selection_rejections": rejected,
        }
        memory_id, memory_status = persist_memory(repo_root, plan_path, plan_hash, "planned")
        receipt["memory_evidence_id"] = memory_id
        receipt["memory_status"] = memory_status
        receipt["receipt_hash"] = sha256_json(receipt)
        write_json(tmp_dir / "experiment-receipt.json", receipt)
        os.replace(tmp_dir, exp_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return exp_dir


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    experiments_dir(root).mkdir(parents=True, exist_ok=True)
    reports_dir(root).mkdir(parents=True, exist_ok=True)
    approval_receipts_dir(root).mkdir(parents=True, exist_ok=True)
    print(json.dumps({"root": str(root), "experiments": str(experiments_dir(root)), "approval_receipts": str(approval_receipts_dir(root))}, indent=2, sort_keys=True))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    policy = load_policy(Path(args.policy))
    eligible, rejected = sorted_eligible(root, args)
    if not eligible:
        raise SystemExit("no eligible opportunities found")
    selected = eligible[0]
    plan = build_plan(selected, policy, args)
    exp_dir = seal_plan(root, Path(args.repo_root), plan, rejected)
    print(json.dumps({"schema_version": "revenue-orchestrator-plan-result-v1", "experiment_dir": str(exp_dir), "experiment_id": plan["experiment_id"], "opportunity_id": plan["opportunity_id"]}, indent=2, sort_keys=True))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root)
    plans: list[dict[str, Any]] = []
    for plan_path in sorted(experiments_dir(root).glob("*/experiment-plan.json")):
        plan = read_json(plan_path)
        if plan:
            plans.append(
                {
                    "experiment_id": plan.get("experiment_id"),
                    "opportunity_id": plan.get("opportunity_id"),
                    "expected_value_score": plan.get("expected_value_score"),
                    "confidence": plan.get("confidence"),
                    "expires_at": plan.get("expires_at"),
                    "path": str(plan_path),
                }
            )
    print(json.dumps({"schema_version": "revenue-orchestrator-plan-list-v1", "plans": plans}, indent=2, sort_keys=True))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = Path(args.root)
    plan_path = experiments_dir(root) / args.experiment_id / "experiment-plan.json"
    if not plan_path.is_file():
        raise SystemExit(f"experiment plan not found: {args.experiment_id}")
    print(plan_path.read_text(encoding="utf-8"))
    return 0


def cmd_record_approval(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if args.action not in APPROVAL_REQUIRED_ACTIONS:
        raise SystemExit(f"unsupported approval action: {args.action}")
    plan_path = experiments_dir(root) / args.experiment_id / "experiment-plan.json"
    if not plan_path.is_file():
        raise SystemExit(f"experiment plan not found: {args.experiment_id}")
    receipt_path = approval_receipts_dir(root) / f"{args.approval_id}.json"
    if receipt_path.exists():
        raise SystemExit(f"approval receipt already exists: {receipt_path}")
    approved_at = args.approved_at or utc_now()
    receipt = {
        "schema_version": "revenue-approval-receipt-v1",
        "approval_id": args.approval_id,
        "experiment_id": args.experiment_id,
        "action": args.action,
        "scope": args.scope,
        "action_id": args.action_id,
        "principal": args.principal,
        "actor": args.actor,
        "counterparty": args.counterparty,
        "destination": args.destination,
        "amount": float(args.amount),
        "approved_at": approved_at,
        "expires_at": args.expires_at,
        "approver": args.approver,
        "policy_hash": args.policy_hash,
        "source": args.source,
        "notes": args.notes,
    }
    receipt["approval_receipt_hash"] = sha256_json(receipt)
    write_json(receipt_path, receipt)
    print(json.dumps({"schema_version": "revenue-approval-record-result-v1", "approval_id": args.approval_id, "receipt": str(receipt_path)}, indent=2, sort_keys=True))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(revenue_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))


def add_plan_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-ledger", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-confidence", type=float, default=0.4)
    parser.add_argument("--max-compliance-risk", type=float, default=0.5)
    parser.add_argument("--max-execution-risk", type=float, default=0.6)
    parser.add_argument("--max-budget-request", type=float, default=250.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Revenue Orchestrator v1")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_common(init)
    init.set_defaults(func=cmd_init)

    plan = sub.add_parser("plan")
    add_common(plan)
    add_plan_filters(plan)
    plan.add_argument("--policy", default="config/revenue-os-policy.example.json")
    plan.add_argument("--experiment-id", default="")
    plan.add_argument("--objective", default="")
    plan.add_argument("--hypothesis", default="")
    plan.add_argument("--workflow-id", default="")
    plan.add_argument("--offer-id", default="")
    plan.add_argument("--campaign", default="")
    plan.add_argument("--timebox-days", type=int, default=7)
    plan.add_argument("--plan-ttl-days", type=int, default=14)
    plan.add_argument("--success-threshold", default="")
    plan.set_defaults(func=cmd_plan)

    list_cmd = sub.add_parser("list-plans")
    add_common(list_cmd)
    list_cmd.set_defaults(func=cmd_list)

    show = sub.add_parser("show")
    add_common(show)
    show.add_argument("--experiment-id", required=True)
    show.set_defaults(func=cmd_show)

    approval = sub.add_parser("record-approval")
    add_common(approval)
    approval.add_argument("--approval-id", required=True)
    approval.add_argument("--experiment-id", required=True)
    approval.add_argument("--action", required=True)
    approval.add_argument("--scope", required=True)
    approval.add_argument("--action-id", required=True)
    approval.add_argument("--principal", required=True)
    approval.add_argument("--actor", required=True)
    approval.add_argument("--counterparty", required=True)
    approval.add_argument("--destination", required=True)
    approval.add_argument("--amount", type=float, required=True)
    approval.add_argument("--approver", required=True)
    approval.add_argument("--policy-hash", required=True)
    approval.add_argument("--approved-at", default="")
    approval.add_argument("--expires-at", required=True)
    approval.add_argument("--source", default="upstream-approval")
    approval.add_argument("--notes", default="")
    approval.set_defaults(func=cmd_record_approval)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
