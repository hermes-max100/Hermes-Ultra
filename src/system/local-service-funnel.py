#!/usr/bin/env python3
"""Hermes Local Service Funnel v1.

First concrete Revenue OS funnel for AI automation/service offers to local
service businesses. This tool creates local audits, offer drafts, outreach
drafts, approval-gated send handoff packets, premortem gate artifacts, and
Revenue Ledger draft events. It does not send messages, post, buy, change
accounts, enter credentials, or perform platform actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PILOT_STAGES = [
    "discovered",
    "qualified",
    "audit_generated",
    "outreach_drafted",
    "approved",
    "sent",
    "replied",
    "lead_qualified",
    "call_booked",
    "proposal_sent",
    "won",
    "lost",
    "revenue_received",
]

TERMINAL_STAGES = {"won", "lost", "revenue_received"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "prospect"


def revenue_root() -> Path:
    return Path(os.environ.get("HERMES_REVENUE_OS_DIR", ".hermes/revenue-os"))


def experiments_dir(root: Path) -> Path:
    return root / "experiments"


def approval_receipts_dir(root: Path) -> Path:
    return root / "approval-receipts"


def funnel_dir(root: Path, experiment_id: str) -> Path:
    return root / "funnels" / "local-service" / experiment_id


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def events_path(root: Path) -> Path:
    return root / "revenue-events.jsonl"


def stage_rank(stage: str) -> int:
    try:
        return PILOT_STAGES.index(stage)
    except ValueError:
        return -1


def event_type_for_stage(stage: str) -> str:
    return {
        "discovered": "lead",
        "qualified": "qualified_lead",
        "approved": "approval",
        "won": "conversion",
        "revenue_received": "revenue",
    }.get(stage, "manual_note")


def metrics_for_stage(stage: str, args: argparse.Namespace) -> dict[str, float | int]:
    metrics = {
        "leads": 1 if stage == "discovered" else 0,
        "qualified_leads": 1 if stage == "qualified" else 0,
        "conversions": 1 if stage == "won" else 0,
        "gross_revenue": float(getattr(args, "gross_revenue", 0.0) or 0.0),
        "other_cost": float(getattr(args, "direct_cost", 0.0) or 0.0),
    }
    return metrics


def event_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def event_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


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


def normalize_prospect(prospect: dict[str, Any]) -> dict[str, Any]:
    name = str(prospect.get("business_name") or prospect.get("name") or "Unknown business").strip()
    signals = prospect.get("signals") if isinstance(prospect.get("signals"), list) else []
    evidence_refs = prospect.get("evidence_refs") if isinstance(prospect.get("evidence_refs"), list) else []
    source_url = prospect.get("source_url") or prospect.get("url") or ""
    if source_url:
        evidence_refs.append({"type": "source", "ref": str(source_url)})
    normalized = {
        "prospect_id": prospect_id(prospect),
        "business_name": name,
        "category": str(prospect.get("category") or "local service business"),
        "city": str(prospect.get("city") or ""),
        "state": str(prospect.get("state") or ""),
        "website": str(prospect.get("website") or ""),
        "contact_channel": str(prospect.get("contact_channel") or "manual_review"),
        "contact_ref": str(prospect.get("contact_ref") or ""),
        "signals": [str(signal) for signal in signals],
        "evidence_refs": evidence_refs,
        "notes": str(prospect.get("notes") or ""),
    }
    normalized["qualification_score"] = qualification_score(normalized)
    normalized["qualified"] = normalized["qualification_score"] >= 0.45
    return normalized


def qualification_score(prospect: dict[str, Any]) -> float:
    score = 0.2
    signals = {str(signal).lower() for signal in prospect.get("signals", [])}
    if prospect.get("website"):
        score += 0.15
    if prospect.get("contact_ref"):
        score += 0.1
    if prospect.get("evidence_refs"):
        score += 0.15
    if {"missed-calls", "slow-response", "no-online-booking", "manual-follow-up", "bad-contact-flow"} & signals:
        score += 0.3
    if {"active-ads", "high-ticket-service", "emergency-service"} & signals:
        score += 0.1
    return round(min(score, 1.0), 4)


def plan_path(root: Path, experiment_id: str) -> Path:
    return experiments_dir(root) / experiment_id / "experiment-plan.json"


def load_plan(root: Path, experiment_id: str) -> dict[str, Any]:
    path = plan_path(root, experiment_id)
    if not path.is_file():
        raise SystemExit(f"experiment plan not found: {experiment_id}")
    return read_json(path)


def audit_markdown(plan: dict[str, Any], prospect: dict[str, Any]) -> str:
    signals = "\n".join(f"- {signal}" for signal in prospect["signals"]) or "- No explicit signals provided; manual review required."
    evidence = "\n".join(f"- {item.get('type', 'source')}: {item.get('ref', '')}" for item in prospect["evidence_refs"]) or "- No source evidence provided."
    return f"""# Local Service Automation Audit - {prospect['business_name']}

Generated: {utc_now()}
Experiment: `{plan['experiment_id']}`
Offer: {plan.get('offer')}

## Prospect

- Business: {prospect['business_name']}
- Category: {prospect['category']}
- Location: {prospect['city']} {prospect['state']}
- Website: {prospect['website'] or 'not provided'}
- Contact channel: {prospect['contact_channel']}
- Qualification score: {prospect['qualification_score']:.2f}

## Evidence

{evidence}

## Observed Signals

{signals}

## Pain Hypothesis

This business may be losing or delaying inbound revenue because lead capture,
follow-up, booking, or response routing appears manual, slow, or hard to verify.

## Proposed Automation

Set up a lightweight lead capture and follow-up flow:

1. Capture inbound inquiries from forms, calls, email, or chat.
2. Classify lead urgency and service type.
3. Draft or trigger fast follow-up messages for human approval.
4. Track unanswered leads and callbacks.
5. Produce a simple weekly missed-lead report.

## Review Notes

- This is a draft audit, not a claim of verified lost revenue.
- Human review is required before outreach.
- Do not contact the prospect without an approval receipt.
"""


def outreach_markdown(plan: dict[str, Any], prospect: dict[str, Any]) -> str:
    return f"""# Outreach Draft - {prospect['business_name']}

Experiment: `{plan['experiment_id']}`
Prospect: `{prospect['prospect_id']}`
Approval required before sending: yes

## Subject

Quick idea to reduce missed leads for {prospect['business_name']}

## Draft

Hi,

I was looking at {prospect['business_name']} and noticed a few places where
inbound leads may be hard to capture or follow up quickly.

I put together a short, no-obligation audit with a practical automation idea:
capture inquiries, classify urgency, draft fast follow-ups for approval, and
track missed leads in one simple report.

If useful, I can send the audit over and show what the setup would look like for
your business.

Thanks.

## Approval Gate

Do not send this draft unless a Revenue Orchestrator approval receipt exists for
action `send` or `outreach` covering this prospect and experiment.
"""


def premortem_gate(plan: dict[str, Any], prospects: list[dict[str, Any]]) -> str:
    return f"""# Premortem Gate - Local Service Funnel

Generated: {utc_now()}
Experiment: `{plan['experiment_id']}`

## Frame

It is six months from now. This first local-service revenue funnel failed.
We are looking back to understand what went wrong.

## Most Likely Failure Modes

1. Prospect evidence was too weak, so the audits sounded generic and did not
   earn replies.
2. The offer was framed as "AI automation" instead of a concrete business
   outcome such as faster lead response or fewer missed calls.
3. Outreach volume stayed too low because every send correctly required human
   approval, but the review queue was not worked daily.
4. The funnel generated interest but fulfillment scope was unclear, making calls
   hard to convert into paid work.
5. Ledger attribution was skipped after manual steps, so Hermes could not learn
   which channels, niches, or offers produced profit.

## Hidden Assumption

The system assumes a tailored audit plus a lead-follow-up offer is specific
enough to create trust with local service businesses before any relationship
exists.

## Revised Launch Guardrails

- Require source-linked evidence for every prospect.
- Keep the first offer narrow: "missed lead capture and follow-up setup."
- Review and approve at most a small batch of outreach drafts manually.
- Define fulfillment scope before sending: intake, follow-up workflow, weekly
  missed-lead report, and handoff notes.
- Record every draft, approval, send, reply, call, conversion, cost, and revenue
  in Revenue Ledger.

## Pre-Launch Checklist

- Qualified prospects: {sum(1 for p in prospects if p['qualified'])}
- Draft audits generated for qualified prospects.
- Outreach drafts generated but not sent.
- Approval receipt exists before any send.
- Revenue Ledger event path verified.
"""


def run_ledger_event(root: Path, repo_root: Path, plan: dict[str, Any], prospect: dict[str, Any], artifact_path: Path) -> None:
    ledger = repo_root / "src/system/revenue-ledger.py"
    attr = plan.get("attribution_fields", {})
    cmd = [
        sys.executable,
        str(ledger),
        "record-event",
        "--root",
        str(root),
        "--repo-root",
        str(repo_root),
        "--experiment-id",
        str(plan["experiment_id"]),
        "--workflow-id",
        str(attr.get("workflow_id") or "wf_local_service_funnel"),
        "--offer-id",
        str(attr.get("offer_id") or "offer_local_service_automation"),
        "--channel",
        str(attr.get("channel") or plan.get("channel") or "manual"),
        "--campaign",
        str(attr.get("campaign") or "local-service-funnel-v1"),
        "--asset-id",
        artifact_path.name,
        "--lead-id",
        str(prospect["prospect_id"]),
        "--event-type",
        "outreach_draft",
        "--action",
        "manual_note",
        "--source",
        "local-service-funnel",
        "--evidence-ref",
        f"artifact={artifact_path}",
        "--metadata",
        "pilot_tracker=true",
        "--metadata",
        "stage=outreach_drafted",
        "--metadata",
        f"business_name={prospect['business_name']}",
        "--metadata",
        f"qualification_score={prospect['qualification_score']}",
        "--metadata",
        f"qualification_signals={json.dumps(prospect['signals'], sort_keys=True)}",
        "--metadata",
        f"audit_path={artifact_path.with_name('audit.md')}",
        "--metadata",
        f"outreach_draft_path={artifact_path}",
        "--notes",
        f"Generated local audit and outreach draft for {prospect['business_name']}",
    ]
    subprocess.run(cmd, cwd=repo_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_stage_event(root: Path, repo_root: Path, plan: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    stage = args.stage
    if stage not in PILOT_STAGES:
        raise SystemExit(f"unsupported pilot stage: {stage}")
    validate_stage_transition(root, args)
    metrics = metrics_for_stage(stage, args)
    attr = plan.get("attribution_fields", {})
    ledger = repo_root / "src/system/revenue-ledger.py"
    cmd = [
        sys.executable,
        str(ledger),
        "record-event",
        "--root",
        str(root),
        "--repo-root",
        str(repo_root),
        "--experiment-id",
        str(args.experiment_id),
        "--workflow-id",
        str(attr.get("workflow_id") or "wf_local_service_funnel"),
        "--offer-id",
        str(attr.get("offer_id") or "offer_local_service_automation"),
        "--channel",
        str(attr.get("channel") or plan.get("channel") or "manual"),
        "--campaign",
        str(attr.get("campaign") or "local-service-funnel-v1"),
        "--lead-id",
        str(args.prospect_id),
        "--customer-id",
        str(args.customer_id or ""),
        "--event-type",
        event_type_for_stage(stage),
        "--action",
        "manual_note",
        "--source",
        "local-service-pilot-tracker",
        "--leads",
        str(metrics["leads"]),
        "--qualified-leads",
        str(metrics["qualified_leads"]),
        "--conversions",
        str(metrics["conversions"]),
        "--gross-revenue",
        str(metrics["gross_revenue"]),
        "--other-cost",
        str(metrics["other_cost"]),
        "--metadata",
        "pilot_tracker=true",
        "--metadata",
        f"stage={stage}",
        "--metadata",
        f"business_name={args.business_name}",
        "--metadata",
        f"reply_status={args.reply_status}",
        "--metadata",
        f"proposal_value={float(args.proposal_value or 0.0)}",
        "--metadata",
        f"outcome={args.outcome}",
        "--metadata",
        f"direct_cost={float(args.direct_cost or 0.0)}",
        "--notes",
        args.notes or f"Pilot tracker stage update: {stage} for {args.business_name}",
    ]
    optional_metadata = {
        "qualification_score": args.qualification_score,
        "qualification_signals": args.qualification_signal,
        "audit_path": args.audit_path,
        "outreach_draft_path": args.outreach_draft_path,
        "approval_id": args.approval_id,
    }
    for key, value in optional_metadata.items():
        if value in (None, "", []):
            continue
        encoded = json.dumps(value, sort_keys=True) if isinstance(value, list) else str(value)
        cmd.extend(["--metadata", f"{key}={encoded}"])
    for evidence_ref in args.evidence_ref:
        cmd.extend(["--evidence-ref", evidence_ref])
    proc = subprocess.run(cmd, cwd=repo_root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(proc.stdout)


def cmd_generate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    repo_root = Path(args.repo_root)
    plan = load_plan(root, args.experiment_id)
    prospects = [normalize_prospect(item) for item in load_json_or_jsonl(Path(args.prospects_file))]
    if args.max_prospects:
        prospects = prospects[: args.max_prospects]
    out_dir = funnel_dir(root, args.experiment_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict[str, Any]] = []
    qualified = [prospect for prospect in prospects if prospect["qualified"]]
    for prospect in qualified:
        prospect_dir = out_dir / "prospects" / f"{slugify(prospect['business_name'])}-{prospect['prospect_id']}"
        audit_path = prospect_dir / "audit.md"
        outreach_path = prospect_dir / "outreach-draft.md"
        handoff_path = prospect_dir / "send-handoff.json"
        write_text(audit_path, audit_markdown(plan, prospect))
        write_text(outreach_path, outreach_markdown(plan, prospect))
        handoff = {
            "schema_version": "local-service-send-handoff-v1",
            "experiment_id": args.experiment_id,
            "prospect_id": prospect["prospect_id"],
            "business_name": prospect["business_name"],
            "contact_channel": prospect["contact_channel"],
            "contact_ref": prospect["contact_ref"],
            "outreach_draft": str(outreach_path),
            "audit": str(audit_path),
            "approval_required": True,
            "allowed_to_send": False,
            "required_approval_actions": ["send", "outreach"],
            "created_at": utc_now(),
        }
        handoff["handoff_hash"] = sha256_json(handoff)
        write_json(handoff_path, handoff)
        if args.record_ledger:
            run_ledger_event(root, repo_root, plan, prospect, outreach_path)
        artifacts.append(
            {
                "prospect_id": prospect["prospect_id"],
                "business_name": prospect["business_name"],
                "audit": str(audit_path),
                "outreach_draft": str(outreach_path),
                "send_handoff": str(handoff_path),
            }
        )

    premortem_path = out_dir / f"premortem-gate-{stamp()}.md"
    write_text(premortem_path, premortem_gate(plan, prospects))
    summary = {
        "schema_version": "local-service-funnel-generate-result-v1",
        "experiment_id": args.experiment_id,
        "prospects_seen": len(prospects),
        "qualified_prospects": len(qualified),
        "funnel_dir": str(out_dir),
        "premortem_gate": str(premortem_path),
        "artifacts": artifacts,
        "boundary": {
            "sent_anything": False,
            "requires_approval_before_send": True,
            "local_only": True,
        },
    }
    write_json(out_dir / "funnel-summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_prepare_approved_handoff(args: argparse.Namespace) -> int:
    root = Path(args.root)
    receipt_path = approval_receipts_dir(root) / f"{args.approval_id}.json"
    if not receipt_path.is_file():
        raise SystemExit(f"approval receipt not found: {args.approval_id}")
    receipt = read_json(receipt_path)
    if receipt.get("experiment_id") != args.experiment_id:
        raise SystemExit("approval receipt experiment mismatch")
    if receipt.get("action") not in {"send", "outreach", "external_message"}:
        raise SystemExit("approval receipt does not authorize send/outreach handoff")
    handoff = read_json(Path(args.handoff))
    if handoff.get("experiment_id") != args.experiment_id:
        raise SystemExit("handoff experiment mismatch")
    approved = dict(handoff)
    approved["approval_id"] = args.approval_id
    approved["approval_receipt"] = str(receipt_path)
    approved["allowed_to_send"] = False
    approved["connector_handoff_ready"] = True
    approved["connector_must_verify_receipt"] = True
    approved["prepared_at"] = utc_now()
    approved["approved_handoff_hash"] = sha256_json(approved)
    out = Path(args.handoff).with_name("approved-send-handoff.json")
    write_json(out, approved)
    print(json.dumps({"schema_version": "approved-send-handoff-result-v1", "handoff": str(out), "sent_anything": False}, indent=2, sort_keys=True))
    return 0


def empty_tracker_row(experiment_id: str, prospect_id_value: str, business_name: str) -> dict[str, Any]:
    return {
        "prospect_id": prospect_id_value,
        "business_name": business_name,
        "experiment_id": experiment_id,
        "current_stage": "discovered",
        "stage_updated_at": "",
        "qualification_score": 0.0,
        "qualification_signals": [],
        "audit_path": "",
        "outreach_draft_path": "",
        "approval_id": "",
        "sent_at": "",
        "reply_status": "",
        "reply_at": "",
        "call_booked_at": "",
        "proposal_value": 0.0,
        "outcome": "",
        "gross_revenue": 0.0,
        "direct_cost": 0.0,
        "profit": 0.0,
        "notes": "",
    }


def update_row_stage(row: dict[str, Any], stage: str, ts: str) -> None:
    if stage not in PILOT_STAGES:
        return
    current_stage = str(row.get("current_stage", ""))
    outcome = str(row.get("outcome", ""))
    if stage == "revenue_received" and (current_stage == "lost" or outcome == "lost"):
        return
    if stage == "lost" and (current_stage in {"won", "revenue_received"} or outcome == "won"):
        return
    if stage == "won" and (current_stage == "lost" or outcome == "lost"):
        return
    current_rank = stage_rank(str(row.get("current_stage", "")))
    new_rank = stage_rank(stage)
    if new_rank >= current_rank or stage in TERMINAL_STAGES:
        row["current_stage"] = stage
        row["stage_updated_at"] = ts
    if stage == "approved":
        row["approval_id"] = row.get("approval_id", "")
    elif stage == "sent":
        row["sent_at"] = ts
    elif stage == "replied":
        row["reply_at"] = ts
    elif stage == "call_booked":
        row["call_booked_at"] = ts
    elif stage in {"won", "lost"}:
        row["outcome"] = stage


def validate_stage_transition(root: Path, args: argparse.Namespace) -> None:
    existing = next((row for row in pilot_rows(root, args.experiment_id, None) if row["prospect_id"] == args.prospect_id), None)
    if not existing:
        if args.stage == "revenue_received":
            raise SystemExit("cannot record revenue_received before won")
        return
    current_stage = str(existing.get("current_stage") or "")
    outcome = str(existing.get("outcome") or "")
    if args.stage == "revenue_received":
        if current_stage == "lost" or outcome == "lost":
            raise SystemExit("cannot record revenue_received after lost")
        if current_stage not in {"won", "revenue_received"} and outcome != "won":
            raise SystemExit("cannot record revenue_received before won")
    if args.stage == "lost" and (current_stage in {"won", "revenue_received"} or outcome == "won"):
        raise SystemExit("cannot record lost after won")
    if args.stage == "won" and (current_stage == "lost" or outcome == "lost"):
        raise SystemExit("cannot record won after lost")


def seed_rows_from_prospects(rows: dict[str, dict[str, Any]], experiment_id: str, prospects_file: str | None) -> None:
    if not prospects_file:
        return
    for item in load_json_or_jsonl(Path(prospects_file)):
        prospect = normalize_prospect(item)
        row = rows.setdefault(prospect["prospect_id"], empty_tracker_row(experiment_id, prospect["prospect_id"], prospect["business_name"]))
        row["qualification_score"] = prospect["qualification_score"]
        row["qualification_signals"] = prospect["signals"]
        row["notes"] = prospect.get("notes", "")
        if prospect["qualified"]:
            update_row_stage(row, "qualified", row.get("stage_updated_at") or "")


def seed_rows_from_funnel_summary(rows: dict[str, dict[str, Any]], root: Path, experiment_id: str) -> None:
    summary = read_json(funnel_dir(root, experiment_id) / "funnel-summary.json")
    for artifact in summary.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        pid = str(artifact.get("prospect_id") or "")
        if not pid:
            continue
        row = rows.setdefault(pid, empty_tracker_row(experiment_id, pid, str(artifact.get("business_name") or "")))
        row["business_name"] = str(artifact.get("business_name") or row["business_name"])
        row["audit_path"] = str(artifact.get("audit") or row["audit_path"])
        row["outreach_draft_path"] = str(artifact.get("outreach_draft") or row["outreach_draft_path"])
        update_row_stage(row, "outreach_drafted", row.get("stage_updated_at") or "")


def update_row_from_event(row: dict[str, Any], event: dict[str, Any]) -> None:
    metadata = event_metadata(event)
    ts = str(event.get("ts") or "")
    stage = str(metadata.get("stage") or "")
    if not stage:
        event_type = str(event.get("event_type") or "")
        stage = {"lead": "discovered", "qualified_lead": "qualified", "approval": "approved", "conversion": "won", "revenue": "revenue_received", "outreach_draft": "outreach_drafted"}.get(event_type, "")
    if stage:
        update_row_stage(row, stage, ts)
    for key in ("business_name", "audit_path", "outreach_draft_path", "approval_id", "reply_status", "outcome"):
        value = metadata.get(key)
        if value not in (None, "", []):
            row[key] = value
    if metadata.get("qualification_score") not in (None, ""):
        row["qualification_score"] = float(metadata["qualification_score"])
    if metadata.get("qualification_signals") not in (None, ""):
        signals = metadata["qualification_signals"]
        row["qualification_signals"] = signals if isinstance(signals, list) else [str(signals)]
    if metadata.get("proposal_value") not in (None, ""):
        row["proposal_value"] = float(metadata["proposal_value"])
    metrics = event_metrics(event)
    row["gross_revenue"] += float(metrics.get("gross_revenue", 0) or 0)
    direct_cost = float(metadata.get("direct_cost", 0) or 0)
    row["direct_cost"] += direct_cost if direct_cost else float(metrics.get("other_cost", 0) or 0)
    row["profit"] = round(float(row["gross_revenue"]) - float(row["direct_cost"]), 4)
    notes = str(event.get("notes") or "")
    if notes:
        row["notes"] = notes


def pilot_rows(root: Path, experiment_id: str, prospects_file: str | None) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    seed_rows_from_prospects(rows, experiment_id, prospects_file)
    seed_rows_from_funnel_summary(rows, root, experiment_id)
    for event in read_jsonl(events_path(root)):
        if event.get("experiment_id") != experiment_id:
            continue
        metadata = event_metadata(event)
        if metadata.get("pilot_tracker") is not True and event.get("source") not in {"local-service-funnel", "local-service-pilot-tracker"}:
            continue
        pid = str(event.get("lead_id") or "")
        if not pid:
            continue
        row = rows.setdefault(pid, empty_tracker_row(experiment_id, pid, str(metadata.get("business_name") or "")))
        update_row_from_event(row, event)
    out = list(rows.values())
    out.sort(key=lambda row: (stage_rank(str(row["current_stage"])), float(row.get("qualification_score") or 0), str(row["business_name"])), reverse=True)
    return out


def pilot_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prospects_reviewed = len(rows)
    qualified = sum(1 for row in rows if stage_rank(str(row["current_stage"])) >= stage_rank("qualified"))
    sent = sum(1 for row in rows if row.get("sent_at") or stage_rank(str(row["current_stage"])) >= stage_rank("sent"))
    replied = sum(1 for row in rows if row.get("reply_at") or stage_rank(str(row["current_stage"])) >= stage_rank("replied"))
    positive = sum(1 for row in rows if str(row.get("reply_status", "")).lower() in {"positive", "interested", "yes"})
    calls = sum(1 for row in rows if row.get("call_booked_at") or stage_rank(str(row["current_stage"])) >= stage_rank("call_booked"))
    proposals = sum(1 for row in rows if stage_rank(str(row["current_stage"])) >= stage_rank("proposal_sent"))
    wins = sum(1 for row in rows if row.get("outcome") == "won" or row.get("current_stage") in {"won", "revenue_received"})
    losses = sum(1 for row in rows if row.get("outcome") == "lost" or row.get("current_stage") == "lost")
    gross = round(sum(float(row.get("gross_revenue") or 0) for row in rows), 4)
    direct_cost = round(sum(float(row.get("direct_cost") or 0) for row in rows), 4)
    profit = round(gross - direct_cost, 4)
    return {
        "prospects_reviewed": prospects_reviewed,
        "qualified": qualified,
        "qualified_rate": round(qualified / prospects_reviewed, 6) if prospects_reviewed else 0.0,
        "outreach_sent": sent,
        "reply_rate": round(replied / sent, 6) if sent else 0.0,
        "positive_reply_rate": round(positive / sent, 6) if sent else 0.0,
        "positive_replies": positive,
        "calls_booked": calls,
        "proposals_sent": proposals,
        "wins": wins,
        "losses": losses,
        "gross_revenue": gross,
        "total_direct_cost": direct_cost,
        "profit": profit,
        "cost_per_qualified_lead": round(direct_cost / qualified, 4) if qualified else 0.0,
        "profit_per_contacted_prospect": round(profit / sent, 4) if sent else 0.0,
    }


def bottleneck_guidance(metrics: dict[str, Any]) -> str:
    reviewed = int(metrics["prospects_reviewed"])
    qualified = int(metrics["qualified"])
    sent = int(metrics["outreach_sent"])
    positive = int(metrics["positive_replies"])
    calls = int(metrics["calls_booked"])
    wins = int(metrics["wins"])
    profit = float(metrics["profit"])
    if reviewed and qualified / reviewed < 0.33:
        return "low qualification rate -> improve prospect discovery/signals"
    if qualified and not positive:
        return "good qualification, no replies -> fix offer/outreach"
    if positive and not calls:
        return "replies, no calls -> fix qualification/CTA/follow-up"
    if calls and not wins:
        return "calls, no closes -> fix pricing/proposal/sales process"
    if wins and profit <= 0:
        return "sales, poor profit -> fix fulfillment/cost structure"
    if wins and profit > 0:
        return "profitable conversions -> automate more of the winning funnel"
    if not sent:
        return "no sends recorded -> review drafts, approve a small batch, then record sends"
    return "insufficient signal -> continue the controlled pilot without changing the offer"


def render_pilot_report(experiment_id: str, rows: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    lines = [
        f"# Local Service Pilot Tracker - {experiment_id}",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Operating Numbers",
        "",
        "- Public prospects target: 30",
        "- Audit/draft target: 10-15 strongest prospects",
        "- Manual outreach target: 10",
        "- Paid acquisition: 0",
        "- Primary metric: attributable profit",
        "",
        "## Pilot Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Prospects reviewed | {metrics['prospects_reviewed']} |",
        f"| Qualified | {metrics['qualified']} |",
        f"| Qualified rate | {metrics['qualified_rate']:.2%} |",
        f"| Outreach sent | {metrics['outreach_sent']} |",
        f"| Reply rate | {metrics['reply_rate']:.2%} |",
        f"| Positive reply rate | {metrics['positive_reply_rate']:.2%} |",
        f"| Calls booked | {metrics['calls_booked']} |",
        f"| Proposals sent | {metrics['proposals_sent']} |",
        f"| Wins | {metrics['wins']} |",
        f"| Losses | {metrics['losses']} |",
        f"| Gross revenue | {metrics['gross_revenue']:.2f} |",
        f"| Total direct cost | {metrics['total_direct_cost']:.2f} |",
        f"| Profit | {metrics['profit']:.2f} |",
        f"| Cost per qualified lead | {metrics['cost_per_qualified_lead']:.2f} |",
        f"| Profit per contacted prospect | {metrics['profit_per_contacted_prospect']:.2f} |",
        "",
        "## Bottleneck Read",
        "",
        bottleneck_guidance(metrics),
        "",
        "## Prospect Tracker",
        "",
        "| Prospect | Stage | Score | Signals | Reply | Proposal | Revenue | Cost | Profit | Notes |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        signals = ", ".join(str(s) for s in row.get("qualification_signals", []))
        notes = str(row.get("notes", "")).replace("\n", " ")[:120]
        lines.append(
            f"| {row['business_name']} | {row['current_stage']} | {float(row.get('qualification_score') or 0):.2f} | "
            f"{signals} | {row.get('reply_status', '')} | {float(row.get('proposal_value') or 0):.2f} | "
            f"{float(row.get('gross_revenue') or 0):.2f} | {float(row.get('direct_cost') or 0):.2f} | "
            f"{float(row.get('profit') or 0):.2f} | {notes} |"
        )
    return "\n".join(lines) + "\n"


def cmd_record_stage(args: argparse.Namespace) -> int:
    root = Path(args.root)
    repo_root = Path(args.repo_root)
    plan = load_plan(root, args.experiment_id)
    event = run_stage_event(root, repo_root, plan, args)
    print(json.dumps({"schema_version": "local-service-pilot-stage-result-v1", "event_id": event.get("event_id"), "stage": args.stage, "prospect_id": args.prospect_id}, indent=2, sort_keys=True))
    return 0


def cmd_pilot_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rows = pilot_rows(root, args.experiment_id, args.prospects_file)
    metrics = pilot_metrics(rows)
    out_dir = funnel_dir(root, args.experiment_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "local-service-pilot-tracker-v1",
        "experiment_id": args.experiment_id,
        "generated_at": utc_now(),
        "metrics": metrics,
        "bottleneck_guidance": bottleneck_guidance(metrics),
        "rows": rows,
    }
    json_path = out_dir / "pilot-tracker.json"
    md_path = out_dir / "pilot-tracker.md"
    write_json(json_path, payload)
    write_text(md_path, render_pilot_report(args.experiment_id, rows, metrics))
    print(json.dumps({"schema_version": "local-service-pilot-report-result-v1", "json": str(json_path), "report": str(md_path), "metrics": metrics}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Local Service Funnel v1")
    parser.add_argument("--root", default=str(revenue_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--experiment-id", required=True)
    generate.add_argument("--prospects-file", required=True)
    generate.add_argument("--max-prospects", type=int, default=0)
    generate.add_argument("--record-ledger", action="store_true")
    generate.set_defaults(func=cmd_generate)

    handoff = sub.add_parser("prepare-approved-handoff")
    handoff.add_argument("--experiment-id", required=True)
    handoff.add_argument("--handoff", required=True)
    handoff.add_argument("--approval-id", required=True)
    handoff.set_defaults(func=cmd_prepare_approved_handoff)

    stage = sub.add_parser("record-stage")
    stage.add_argument("--experiment-id", required=True)
    stage.add_argument("--prospect-id", required=True)
    stage.add_argument("--business-name", required=True)
    stage.add_argument("--stage", required=True, choices=PILOT_STAGES)
    stage.add_argument("--customer-id", default="")
    stage.add_argument("--qualification-score", type=float, default=0.0)
    stage.add_argument("--qualification-signal", action="append", default=[])
    stage.add_argument("--audit-path", default="")
    stage.add_argument("--outreach-draft-path", default="")
    stage.add_argument("--approval-id", default="")
    stage.add_argument("--reply-status", default="")
    stage.add_argument("--proposal-value", type=float, default=0.0)
    stage.add_argument("--outcome", default="")
    stage.add_argument("--gross-revenue", type=float, default=0.0)
    stage.add_argument("--direct-cost", type=float, default=0.0)
    stage.add_argument("--evidence-ref", action="append", default=[])
    stage.add_argument("--notes", default="")
    stage.set_defaults(func=cmd_record_stage)

    report = sub.add_parser("pilot-report")
    report.add_argument("--experiment-id", required=True)
    report.add_argument("--prospects-file", default="")
    report.set_defaults(func=cmd_pilot_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
