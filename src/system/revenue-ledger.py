#!/usr/bin/env python3
"""Hermes Revenue Ledger v1.

Local-only attribution and opportunity ledger for Revenue OS. This tool records
economic events and opportunity hypotheses; it does not send messages, post,
purchase, change accounts, or execute platform actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVENT_TYPES = {
    "impression",
    "click",
    "lead",
    "qualified_lead",
    "appointment_booked",
    "completed_outcome",
    "proposal_sent",
    "sale_closed",
    "conversion",
    "revenue",
    "attributed_revenue",
    "refund",
    "platform_fee",
    "ad_spend",
    "ai_api_cost",
    "other_cost",
    "outreach_draft",
    "approval",
    "fulfillment",
    "manual_note",
}

HUMAN_APPROVAL_ACTIONS = {
    "send",
    "post",
    "delete",
    "purchase",
    "account_change",
    "credential_entry",
    "permission_change",
    "payment",
    "invite",
    "security_setting",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ledger_root() -> Path:
    return Path(os.environ.get("HERMES_REVENUE_OS_DIR", ".hermes/revenue-os"))


def events_path(root: Path) -> Path:
    return root / "revenue-events.jsonl"


def opportunities_path(root: Path) -> Path:
    return root / "opportunities.jsonl"


def reports_dir(root: Path) -> Path:
    return root / "reports"


def parse_evidence_refs(values: list[str]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for value in values:
        if not value:
            continue
        if "=" in value:
            kind, _, ref = value.partition("=")
            refs.append({"type": kind.strip() or "reference", "ref": ref.strip()})
        else:
            refs.append({"type": "reference", "ref": value})
    return refs


def parse_metadata(values: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for value in values:
        if not value:
            continue
        if "=" not in value:
            metadata[value] = True
            continue
        key, _, raw = value.partition("=")
        key = key.strip()
        if not key:
            continue
        raw = raw.strip()
        if raw.lower() in {"true", "false"}:
            metadata[key] = raw.lower() == "true"
            continue
        try:
            metadata[key] = json.loads(raw)
        except json.JSONDecodeError:
            metadata[key] = raw
    return metadata


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def opportunity_score(
    *,
    expected_profit: float,
    probability_of_conversion: float,
    automation_fit: float,
    confidence: float,
    strategic_fit: float,
    time_to_revenue_days: float,
    execution_cost: float,
    compliance_risk: float,
    execution_risk: float,
) -> float:
    """Risk-adjusted expected value score for opportunity ranking.

    Formula:
      profit * p(conversion) * automation_fit * confidence * strategic_fit
      / (time_to_revenue * execution_cost_factor * risk_penalty)

    `execution_cost_factor` is normalized to avoid letting dollars dominate the
    score scale while still penalizing expensive experiments.
    """
    time_factor = max(1.0, float(time_to_revenue_days))
    execution_cost_factor = max(1.0, float(execution_cost) / 100.0)
    risk_penalty = 1.0 + max(0.0, float(compliance_risk)) + max(0.0, float(execution_risk))
    numerator = (
        float(expected_profit)
        * clamp01(probability_of_conversion)
        * clamp01(automation_fit)
        * clamp01(confidence)
        * clamp01(strategic_fit)
    )
    denominator = time_factor * execution_cost_factor * risk_penalty
    return round(numerator / denominator, 6)


def metric_args(args: argparse.Namespace) -> dict[str, float | int]:
    return {
        "impressions": int(args.impressions),
        "clicks": int(args.clicks),
        "leads": int(args.leads),
        "qualified_leads": int(args.qualified_leads),
        "appointments_booked": int(args.appointments_booked),
        "completed_outcomes": int(args.completed_outcomes),
        "proposals_sent": int(args.proposals_sent),
        "sales_closed": int(args.sales_closed),
        "conversions": int(args.conversions),
        "gross_revenue": float(args.gross_revenue),
        "attributed_revenue": float(args.attributed_revenue),
        "refunds": float(args.refunds),
        "platform_fees": float(args.platform_fees),
        "ad_spend": float(args.ad_spend),
        "inference_cost": float(args.inference_cost),
        "ai_api_cost": float(args.ai_api_cost),
        "tool_cost": float(args.tool_cost),
        "other_cost": float(args.other_cost),
    }


def derived_metrics(metrics: dict[str, float | int]) -> dict[str, float]:
    gross_revenue = float(metrics.get("gross_revenue", 0))
    attributed_revenue = float(metrics.get("attributed_revenue", 0))
    refunds = float(metrics.get("refunds", 0))
    platform_fees = float(metrics.get("platform_fees", 0))
    ad_spend = float(metrics.get("ad_spend", 0))
    configured_inference_cost = float(metrics.get("inference_cost", 0))
    legacy_ai_cost = float(metrics.get("ai_api_cost", 0))
    inference_cost = configured_inference_cost if configured_inference_cost != 0 else legacy_ai_cost
    tool_cost = float(metrics.get("tool_cost", 0))
    other_cost = float(metrics.get("other_cost", 0))
    direct_costs = platform_fees + inference_cost + tool_cost + other_cost
    costs = direct_costs + ad_spend
    net_revenue = gross_revenue - refunds
    gross_profit = net_revenue - direct_costs
    profit = gross_profit - ad_spend
    clicks = int(metrics.get("clicks", 0))
    leads = int(metrics.get("leads", 0))
    qualified_leads = int(metrics.get("qualified_leads", 0))
    appointments = int(metrics.get("appointments_booked", 0))
    completed_outcomes = int(metrics.get("completed_outcomes", 0))
    proposals = int(metrics.get("proposals_sent", 0))
    sales = int(metrics.get("sales_closed", 0))
    conversions = int(metrics.get("conversions", 0))
    return {
        "direct_cost": round(direct_costs, 4),
        "inference_cost_effective": round(inference_cost, 4),
        "total_cost": round(costs, 4),
        "net_revenue": round(net_revenue, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_margin": round(gross_profit / net_revenue, 6) if net_revenue else 0.0,
        "profit": round(profit, 4),
        "profit_margin": round(profit / net_revenue, 6) if net_revenue else 0.0,
        "conversion_rate": round(conversions / leads, 6) if leads else 0.0,
        "click_to_lead_rate": round(leads / clicks, 6) if clicks else 0.0,
        "qualified_lead_rate": round(qualified_leads / leads, 6) if leads else 0.0,
        "appointment_rate": round(appointments / qualified_leads, 6) if qualified_leads else 0.0,
        "proposal_to_sale_rate": round(sales / proposals, 6) if proposals else 0.0,
        "cac": round(costs / conversions, 4) if conversions else 0.0,
        "cost_per_qualified_lead": round(costs / qualified_leads, 4) if qualified_leads else 0.0,
        "cost_per_appointment": round(costs / appointments, 4) if appointments else 0.0,
        "cost_per_completed_outcome": round(costs / completed_outcomes, 4) if completed_outcomes else 0.0,
        "cost_per_proposal": round(costs / proposals, 4) if proposals else 0.0,
        "cost_per_sale": round(costs / sales, 4) if sales else 0.0,
        "attributed_revenue_per_sale": round(attributed_revenue / sales, 4) if sales else 0.0,
        "roas": round(gross_revenue / ad_spend, 6) if ad_spend else 0.0,
        "profit_per_lead": round(profit / leads, 4) if leads else 0.0,
    }


def event_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.event_type not in EVENT_TYPES:
        raise SystemExit(f"unsupported event type: {args.event_type}")
    if args.action in HUMAN_APPROVAL_ACTIONS and not args.human_approved:
        raise SystemExit(f"action requires human approval: {args.action}")
    metrics = metric_args(args)
    payload = {
        "schema_version": "revenue-event-v1",
        "ts": args.ts or utc_now(),
        "event_id": args.event_id or "rev_evt_" + sha256_json(
            {
                "ts": args.ts or utc_now(),
                "experiment_id": args.experiment_id,
                "workflow_id": args.workflow_id,
                "offer_id": args.offer_id,
                "event_type": args.event_type,
                "notes": args.notes,
            }
        )[:20],
        "experiment_id": args.experiment_id,
        "workflow_id": args.workflow_id,
        "offer_id": args.offer_id,
        "channel": args.channel,
        "campaign": args.campaign,
        "asset_id": args.asset_id,
        "lead_id": args.lead_id,
        "customer_id": args.customer_id,
        "event_type": args.event_type,
        "action": args.action,
        "human_approved": bool(args.human_approved),
        "approval_required_actions": sorted(HUMAN_APPROVAL_ACTIONS),
        "metrics": metrics,
        "derived": derived_metrics(metrics),
        "evidence_refs": parse_evidence_refs(args.evidence_ref),
        "metadata": parse_metadata(args.metadata),
        "notes": args.notes,
        "source": args.source,
    }
    payload["event_hash"] = sha256_json(payload)
    return payload


def opportunity_payload(args: argparse.Namespace) -> dict[str, Any]:
    probability = clamp01(args.probability_of_conversion)
    expected_revenue = float(args.expected_revenue)
    expected_cost = float(args.expected_cost)
    if args.expected_profit is None:
        expected_profit = expected_revenue - expected_cost
    else:
        expected_profit = float(args.expected_profit)
    automation_fit = clamp01(args.automation_fit)
    confidence = clamp01(args.confidence)
    strategic_fit = clamp01(args.strategic_fit)
    time_days = max(float(args.time_to_revenue_days), 0.0)
    startup_cost = max(float(args.startup_cost), 0.0)
    execution_cost = max(float(args.execution_cost), startup_cost, expected_cost, 0.0)
    compliance_risk = float(args.compliance_risk)
    execution_risk = float(args.execution_risk)
    expected_value = opportunity_score(
        expected_profit=expected_profit,
        probability_of_conversion=probability,
        automation_fit=automation_fit,
        confidence=confidence,
        strategic_fit=strategic_fit,
        time_to_revenue_days=time_days,
        execution_cost=execution_cost,
        compliance_risk=compliance_risk,
        execution_risk=execution_risk,
    )
    customer_segment = args.customer_segment or args.customer
    payload = {
        "schema_version": "revenue-opportunity-v1",
        "ts": args.ts or utc_now(),
        "opportunity_id": args.opportunity_id or "opp_" + sha256_json(
            {
                "business_model": args.business_model,
                "customer_segment": customer_segment,
                "problem": args.problem,
                "offer": args.offer,
                "channel": args.channel,
            }
        )[:20],
        "business_model": args.business_model,
        "customer": customer_segment,
        "customer_segment": customer_segment,
        "problem": args.problem,
        "offer": args.offer,
        "channel": args.channel,
        "estimated_demand": float(args.estimated_demand),
        "competition": float(args.competition),
        "time_to_revenue_days": time_days,
        "startup_cost": startup_cost,
        "execution_cost": execution_cost,
        "margin_estimate": float(args.margin_estimate),
        "automation_fit": automation_fit,
        "compliance_risk": compliance_risk,
        "execution_risk": execution_risk,
        "confidence": confidence,
        "strategic_fit": strategic_fit,
        "probability_of_conversion": probability,
        "expected_revenue": round(expected_revenue, 4),
        "expected_cost": round(expected_cost, 4),
        "expected_profit": expected_profit,
        "expected_value": expected_value,
        "expected_value_score": expected_value,
        "created_at": args.created_at or args.ts or utc_now(),
        "expires_at": args.expires_at,
        "evidence_refs": parse_evidence_refs(args.evidence_ref),
        "approval_boundary": {
            "external_communications": "human_required",
            "paid_spend": "human_required_unless_budget_policy_allows",
            "purchases": "human_required",
            "account_changes": "human_required",
        },
        "status": args.status,
        "notes": args.notes,
    }
    payload["opportunity_hash"] = sha256_json(payload)
    return payload


def aggregate_events(rows: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(group_by) or "unassigned")
        bucket = buckets.setdefault(
            key,
            {
                group_by: key,
                "events": 0,
                "impressions": 0,
                "clicks": 0,
                "leads": 0,
                "qualified_leads": 0,
                "appointments_booked": 0,
                "completed_outcomes": 0,
                "proposals_sent": 0,
                "sales_closed": 0,
                "conversions": 0,
                "gross_revenue": 0.0,
                "attributed_revenue": 0.0,
                "refunds": 0.0,
                "platform_fees": 0.0,
                "ad_spend": 0.0,
                "inference_cost": 0.0,
                "ai_api_cost": 0.0,
                "tool_cost": 0.0,
                "other_cost": 0.0,
            },
        )
        bucket["events"] += 1
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        for field in (
            "impressions",
            "clicks",
            "leads",
            "qualified_leads",
            "appointments_booked",
            "completed_outcomes",
            "proposals_sent",
            "sales_closed",
            "conversions",
            "gross_revenue",
            "attributed_revenue",
            "refunds",
            "platform_fees",
            "ad_spend",
            "inference_cost",
            "ai_api_cost",
            "tool_cost",
            "other_cost",
        ):
            bucket[field] += metrics.get(field, 0)
    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        metrics = {
            "impressions": bucket["impressions"],
            "clicks": bucket["clicks"],
            "leads": bucket["leads"],
            "qualified_leads": bucket["qualified_leads"],
            "appointments_booked": bucket["appointments_booked"],
            "completed_outcomes": bucket["completed_outcomes"],
            "proposals_sent": bucket["proposals_sent"],
            "sales_closed": bucket["sales_closed"],
            "conversions": bucket["conversions"],
            "gross_revenue": bucket["gross_revenue"],
            "attributed_revenue": bucket["attributed_revenue"],
            "refunds": bucket["refunds"],
            "platform_fees": bucket["platform_fees"],
            "ad_spend": bucket["ad_spend"],
            "inference_cost": bucket["inference_cost"],
            "ai_api_cost": bucket["ai_api_cost"],
            "tool_cost": bucket["tool_cost"],
            "other_cost": bucket["other_cost"],
        }
        bucket["derived"] = derived_metrics(metrics)
        out.append(bucket)
    out.sort(key=lambda item: item["derived"]["profit"], reverse=True)
    return out


def persist_memory(root: Path, artifact_type: str, artifact_path: Path, artifact_hash: str, status: str) -> tuple[str, str]:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return "", "disabled"
    memory = root / "src/system/memory-fabric.py"
    if not memory.is_file():
        return "", "memory-fabric-missing"
    envelope = {
        "producer": "revenue-ledger",
        "objective": "revenue-os-attribution",
        "input_hash": artifact_hash,
        "selected_agent": "revenue-ledger",
        "actions": [{"type": artifact_type, "path": str(artifact_path)}],
        "predicted_outcome": "economic event should be locally attributed",
        "observed_outcome": f"artifact={artifact_type} status={status}",
        "status": status,
        "evidence_refs": [{"type": artifact_type, "path": str(artifact_path), "sha256": artifact_hash}],
        "security_classification": "INTERNAL",
        "metadata": {
            "artifact_type": artifact_type,
            "evidence_persisted": True,
            "profit_optimization": True,
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return "", proc.stderr.strip() or proc.stdout.strip()
    return proc.stdout.strip().partition("=")[2], "persisted"


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    events_path(root).touch(exist_ok=True)
    opportunities_path(root).touch(exist_ok=True)
    reports_dir(root).mkdir(parents=True, exist_ok=True)
    print(json.dumps({"root": str(root), "events": str(events_path(root)), "opportunities": str(opportunities_path(root))}, indent=2, sort_keys=True))
    return 0


def cmd_record_event(args: argparse.Namespace) -> int:
    root = Path(args.root)
    payload = event_payload(args)
    append_jsonl(events_path(root), payload)
    memory_id, memory_status = persist_memory(Path(args.repo_root), "revenue-event", events_path(root), payload["event_hash"], "observed")
    payload["memory_evidence_id"] = memory_id
    payload["memory_status"] = memory_status
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_record_opportunity(args: argparse.Namespace) -> int:
    root = Path(args.root)
    payload = opportunity_payload(args)
    append_jsonl(opportunities_path(root), payload)
    memory_id, memory_status = persist_memory(Path(args.repo_root), "revenue-opportunity", opportunities_path(root), payload["opportunity_hash"], "observed")
    payload["memory_evidence_id"] = memory_id
    payload["memory_status"] = memory_status
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    rows = read_jsonl(events_path(Path(args.root)))
    summary = {
        "schema_version": "revenue-summary-v1",
        "generated_at": utc_now(),
        "group_by": args.group_by,
        "total_events": len(rows),
        "groups": aggregate_events(rows, args.group_by),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_rank_opportunities(args: argparse.Namespace) -> int:
    rows = read_jsonl(opportunities_path(Path(args.root)))
    rows.sort(key=lambda row: (float(row.get("expected_value_score", row.get("expected_value", 0))), float(row.get("confidence", 0))), reverse=True)
    print(json.dumps({"schema_version": "revenue-opportunity-rank-v1", "opportunities": rows[: args.limit]}, indent=2, sort_keys=True))
    return 0


def render_report(root: Path, group_by: str) -> str:
    rows = read_jsonl(events_path(root))
    opportunities = read_jsonl(opportunities_path(root))
    groups = aggregate_events(rows, group_by)
    opportunities.sort(key=lambda row: (float(row.get("expected_value_score", row.get("expected_value", 0))), float(row.get("confidence", 0))), reverse=True)
    lines = [
        f"# Hermes Revenue OS Report - {utc_now()}",
        "",
        "## Guardrails",
        "",
        "- Local ledger and reports only.",
        "- Profit is the primary optimization target.",
        "- Sending, posting, purchases, account changes, credential entry, and security changes require human approval.",
        "",
        "## Attribution Summary",
        "",
        f"Grouped by: `{group_by}`",
        "",
        "| Group | Events | Leads | Conversions | Gross Revenue | Cost | Profit | CAC | Conversion Rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if groups:
        for group in groups:
            derived = group["derived"]
            lines.append(
                f"| {group[group_by]} | {group['events']} | {group['leads']} | {group['conversions']} | "
                f"{group['gross_revenue']:.2f} | {derived['total_cost']:.2f} | {derived['profit']:.2f} | "
                f"{derived['cac']:.2f} | {derived['conversion_rate']:.4f} |"
            )
    else:
        lines.append("| none | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0000 |")
    lines.extend(["", "## Ranked Opportunities", "", "| Opportunity | Customer | Offer | Channel | EV | Confidence | Risk |", "|---|---|---|---|---:|---:|---:|"])
    if opportunities:
        for item in opportunities[:10]:
            lines.append(
                f"| {item.get('opportunity_id')} | {item.get('customer_segment', item.get('customer'))} | {item.get('offer')} | {item.get('channel')} | "
                f"{float(item.get('expected_value_score', item.get('expected_value', 0))):.4f} | {float(item.get('confidence', 0)):.2f} | {float(item.get('compliance_risk', 0)):.2f} |"
            )
    else:
        lines.append("| none | none | none | none | 0.0000 | 0.00 | 0.00 |")
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    report = render_report(root, args.group_by)
    out = reports_dir(root) / f"revenue-os-report-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text(report, encoding="utf-8")
    print(f"report={out}")
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(ledger_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))


def add_metrics(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--impressions", type=int, default=0)
    parser.add_argument("--clicks", type=int, default=0)
    parser.add_argument("--leads", type=int, default=0)
    parser.add_argument("--qualified-leads", type=int, default=0)
    parser.add_argument("--appointments-booked", type=int, default=0)
    parser.add_argument("--completed-outcomes", type=int, default=0)
    parser.add_argument("--proposals-sent", type=int, default=0)
    parser.add_argument("--sales-closed", type=int, default=0)
    parser.add_argument("--conversions", type=int, default=0)
    parser.add_argument("--gross-revenue", type=float, default=0.0)
    parser.add_argument("--attributed-revenue", type=float, default=0.0)
    parser.add_argument("--refunds", type=float, default=0.0)
    parser.add_argument("--platform-fees", type=float, default=0.0)
    parser.add_argument("--ad-spend", type=float, default=0.0)
    parser.add_argument("--inference-cost", type=float, default=0.0)
    parser.add_argument("--ai-api-cost", type=float, default=0.0, help="Legacy alias used when --inference-cost is zero")
    parser.add_argument("--tool-cost", type=float, default=0.0)
    parser.add_argument("--other-cost", type=float, default=0.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Revenue Ledger v1")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_common(init)
    init.set_defaults(func=cmd_init)

    event = sub.add_parser("record-event")
    add_common(event)
    event.add_argument("--ts", default="")
    event.add_argument("--event-id", default="")
    event.add_argument("--experiment-id", required=True)
    event.add_argument("--workflow-id", default="")
    event.add_argument("--offer-id", default="")
    event.add_argument("--channel", default="")
    event.add_argument("--campaign", default="")
    event.add_argument("--asset-id", default="")
    event.add_argument("--lead-id", default="")
    event.add_argument("--customer-id", default="")
    event.add_argument("--event-type", required=True)
    event.add_argument("--action", default="manual_note")
    event.add_argument("--human-approved", action="store_true")
    event.add_argument("--source", default="manual")
    event.add_argument("--evidence-ref", action="append", default=[])
    event.add_argument("--metadata", action="append", default=[])
    event.add_argument("--notes", default="")
    add_metrics(event)
    event.set_defaults(func=cmd_record_event)

    opportunity = sub.add_parser("record-opportunity")
    add_common(opportunity)
    opportunity.add_argument("--ts", default="")
    opportunity.add_argument("--created-at", default="")
    opportunity.add_argument("--expires-at", default="")
    opportunity.add_argument("--opportunity-id", default="")
    opportunity.add_argument("--business-model", required=True)
    opportunity.add_argument("--customer", required=True)
    opportunity.add_argument("--customer-segment", default="")
    opportunity.add_argument("--problem", required=True)
    opportunity.add_argument("--offer", required=True)
    opportunity.add_argument("--channel", required=True)
    opportunity.add_argument("--estimated-demand", type=float, default=0.5)
    opportunity.add_argument("--competition", type=float, default=0.5)
    opportunity.add_argument("--time-to-revenue-days", type=float, default=7)
    opportunity.add_argument("--startup-cost", type=float, default=0)
    opportunity.add_argument("--execution-cost", type=float, default=0)
    opportunity.add_argument("--margin-estimate", type=float, default=0.7)
    opportunity.add_argument("--automation-fit", type=float, default=0.5)
    opportunity.add_argument("--compliance-risk", type=float, default=0.1)
    opportunity.add_argument("--execution-risk", type=float, default=0.1)
    opportunity.add_argument("--confidence", type=float, default=0.5)
    opportunity.add_argument("--strategic-fit", type=float, default=0.5)
    opportunity.add_argument("--probability-of-conversion", type=float, default=0.05)
    opportunity.add_argument("--expected-revenue", type=float, default=100)
    opportunity.add_argument("--expected-cost", type=float, default=0)
    opportunity.add_argument("--expected-profit", type=float, default=None)
    opportunity.add_argument("--evidence-ref", action="append", default=[])
    opportunity.add_argument("--status", default="candidate")
    opportunity.add_argument("--notes", default="")
    opportunity.set_defaults(func=cmd_record_opportunity)

    summary = sub.add_parser("summary")
    add_common(summary)
    summary.add_argument("--group-by", default="experiment_id", choices=["experiment_id", "workflow_id", "offer_id", "channel", "campaign"])
    summary.set_defaults(func=cmd_summary)

    rank = sub.add_parser("rank-opportunities")
    add_common(rank)
    rank.add_argument("--limit", type=int, default=10)
    rank.set_defaults(func=cmd_rank_opportunities)

    report = sub.add_parser("report")
    add_common(report)
    report.add_argument("--group-by", default="experiment_id", choices=["experiment_id", "workflow_id", "offer_id", "channel", "campaign"])
    report.set_defaults(func=cmd_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
