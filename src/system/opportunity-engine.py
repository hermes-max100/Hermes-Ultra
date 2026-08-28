#!/usr/bin/env python3
"""Hermes Opportunity Engine v1.

Local-only opportunity normalization and ranking for Revenue OS. This tool
turns source findings into evidence-backed opportunity records, applies
expiry/staleness handling, and can hand records to Revenue Ledger. It does not
send messages, post, buy, change accounts, or perform platform actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


LOCAL_ONLY_BOUNDARY = {
    "sends_messages": False,
    "posts_content": False,
    "makes_purchases": False,
    "changes_accounts": False,
    "enters_credentials": False,
    "performs_platform_actions": False,
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


def clamp01(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def revenue_root() -> Path:
    return Path(os.environ.get("HERMES_REVENUE_OS_DIR", ".hermes/revenue-os"))


def queue_path(root: Path) -> Path:
    return root / "opportunity-queue.jsonl"


def reports_dir(root: Path) -> Path:
    return root / "reports" / "opportunity-engine"


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


def load_source_findings(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return []
    findings: list[dict[str, Any]] = []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                findings = [item for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                if isinstance(data.get("findings"), list):
                    findings = [item for item in data["findings"] if isinstance(item, dict)]
                else:
                    findings = [data]
            return findings
        except json.JSONDecodeError:
            pass
    if not findings:
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                findings.append(data)
    return findings


def evidence_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                refs.append({"type": "reference", "ref": item})
            elif isinstance(item, dict):
                ref = item.get("ref") or item.get("url") or item.get("path") or item.get("source")
                if ref:
                    refs.append(
                        {
                            "type": str(item.get("type") or "reference"),
                            "ref": str(ref),
                            "confidence": str(item.get("confidence", "")),
                        }
                    )
    return refs


def normalize_ref(ref: str) -> str:
    if ref.startswith("http://") or ref.startswith("https://"):
        parts = urlsplit(ref)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", "", ""))
    return ref


def validate_evidence(refs: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    source_urls = 0
    local_refs = 0
    for item in refs:
        ref = str(item.get("ref", "")).strip()
        if not ref:
            continue
        norm = dict(item)
        norm["ref"] = normalize_ref(ref)
        if ref.startswith("http://") or ref.startswith("https://"):
            source_urls += 1
        else:
            local_refs += 1
        normalized.append(norm)
    if not normalized:
        status = "insufficient"
    elif source_urls:
        status = "source_linked"
    else:
        status = "local_evidence_only"
    return {
        "status": status,
        "source_url_count": source_urls,
        "local_ref_count": local_refs,
        "normalized_refs": normalized,
    }


def score_opportunity(record: dict[str, Any]) -> float:
    expected_profit = float_value(record.get("expected_profit"))
    probability = clamp01(record.get("probability_of_conversion"), 0.05)
    automation_fit = clamp01(record.get("automation_fit"), 0.5)
    confidence = clamp01(record.get("confidence"), 0.5)
    strategic_fit = clamp01(record.get("strategic_fit"), 0.5)
    time_days = max(1.0, float_value(record.get("time_to_revenue_days"), 7.0))
    execution_cost = max(0.0, float_value(record.get("execution_cost"), float_value(record.get("expected_cost"), 0.0)))
    execution_cost_factor = max(1.0, execution_cost / 100.0)
    risk_penalty = 1.0 + max(0.0, float_value(record.get("compliance_risk"), 0.1)) + max(0.0, float_value(record.get("execution_risk"), 0.1))
    return round(
        expected_profit
        * probability
        * automation_fit
        * confidence
        * strategic_fit
        / (time_days * execution_cost_factor * risk_penalty),
        6,
    )


def status_for_expiry(expires_at: str) -> str:
    expires = parse_ts(expires_at)
    if expires and expires < utc_now_dt():
        return "expired"
    return "fresh"


def normalized_opportunity(finding: dict[str, Any], *, default_ttl_days: int, source_file: Path) -> dict[str, Any]:
    created_at = str(finding.get("created_at") or finding.get("ts") or utc_now())
    created_dt = parse_ts(created_at) or utc_now_dt()
    expires_at = str(finding.get("expires_at") or (created_dt + timedelta(days=default_ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    expected_revenue = float_value(finding.get("expected_revenue"), float_value(finding.get("gross_revenue"), 0.0))
    expected_cost = float_value(finding.get("expected_cost"), float_value(finding.get("startup_cost"), 0.0))
    expected_profit = float_value(finding.get("expected_profit"), expected_revenue - expected_cost)
    refs = evidence_refs(finding.get("evidence_refs") or finding.get("evidence_ref") or finding.get("sources") or [])
    evidence = validate_evidence(refs)
    confidence = clamp01(finding.get("confidence"), 0.5)
    if evidence["status"] == "insufficient":
        confidence = min(confidence, 0.35)

    customer_segment = str(finding.get("customer_segment") or finding.get("customer") or "unclear").strip()
    record = {
        "schema_version": "revenue-opportunity-engine-v1",
        "created_at": created_at,
        "expires_at": expires_at,
        "status": status_for_expiry(expires_at),
        "business_model": str(finding.get("business_model") or "unclear").strip(),
        "customer_segment": customer_segment,
        "customer": customer_segment,
        "problem": str(finding.get("problem") or "unclear").strip(),
        "offer": str(finding.get("offer") or "unclear").strip(),
        "channel": str(finding.get("channel") or "unclear").strip(),
        "evidence_refs": evidence["normalized_refs"],
        "evidence_validation": {k: v for k, v in evidence.items() if k != "normalized_refs"},
        "estimated_demand": clamp01(finding.get("estimated_demand"), 0.5),
        "competition": clamp01(finding.get("competition"), 0.5),
        "probability_of_conversion": clamp01(finding.get("probability_of_conversion"), 0.05),
        "expected_revenue": round(expected_revenue, 4),
        "expected_cost": round(expected_cost, 4),
        "expected_profit": round(expected_profit, 4),
        "automation_fit": clamp01(finding.get("automation_fit"), 0.5),
        "time_to_revenue_days": max(1.0, float_value(finding.get("time_to_revenue_days", finding.get("time_to_revenue")), 7.0)),
        "confidence": confidence,
        "strategic_fit": clamp01(finding.get("strategic_fit"), 0.5),
        "compliance_risk": clamp01(finding.get("compliance_risk"), 0.1),
        "execution_risk": clamp01(finding.get("execution_risk"), 0.1),
        "source_file": str(source_file),
        "notes": str(finding.get("notes") or ""),
        "approval_boundary": {
            "external_communications": "human_required",
            "paid_spend": "human_required_unless_budget_policy_allows",
            "purchases": "human_required",
            "account_changes": "human_required",
        },
        "local_only_boundary": LOCAL_ONLY_BOUNDARY,
    }
    record["expected_value_score"] = score_opportunity(record)
    record["expected_value"] = record["expected_value_score"]
    record["opportunity_id"] = str(
        finding.get("opportunity_id")
        or "opp_"
        + sha256_json(
            {
                "business_model": record["business_model"],
                "customer_segment": record["customer_segment"],
                "problem": record["problem"],
                "offer": record["offer"],
                "channel": record["channel"],
                "source_refs": [item.get("ref") for item in record["evidence_refs"]],
            }
        )[:20]
    )
    record["opportunity_hash"] = sha256_json(record)
    return record


def run_ledger_record(root_dir: Path, repo_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    ledger = repo_root / "src/system/revenue-ledger.py"
    cmd = [
        sys.executable,
        str(ledger),
        "record-opportunity",
        "--root",
        str(root_dir),
        "--repo-root",
        str(repo_root),
        "--created-at",
        str(record["created_at"]),
        "--expires-at",
        str(record["expires_at"]),
        "--opportunity-id",
        str(record["opportunity_id"]),
        "--business-model",
        str(record["business_model"]),
        "--customer",
        str(record["customer_segment"]),
        "--customer-segment",
        str(record["customer_segment"]),
        "--problem",
        str(record["problem"]),
        "--offer",
        str(record["offer"]),
        "--channel",
        str(record["channel"]),
        "--estimated-demand",
        str(record["estimated_demand"]),
        "--competition",
        str(record["competition"]),
        "--time-to-revenue-days",
        str(record["time_to_revenue_days"]),
        "--startup-cost",
        str(record["expected_cost"]),
        "--execution-cost",
        str(record["expected_cost"]),
        "--automation-fit",
        str(record["automation_fit"]),
        "--compliance-risk",
        str(record["compliance_risk"]),
        "--execution-risk",
        str(record["execution_risk"]),
        "--confidence",
        str(record["confidence"]),
        "--strategic-fit",
        str(record["strategic_fit"]),
        "--probability-of-conversion",
        str(record["probability_of_conversion"]),
        "--expected-revenue",
        str(record["expected_revenue"]),
        "--expected-cost",
        str(record["expected_cost"]),
        "--expected-profit",
        str(record["expected_profit"]),
        "--status",
        str(record["status"]),
        "--notes",
        str(record.get("notes", "")),
    ]
    for ref in record.get("evidence_refs", []):
        cmd.extend(["--evidence-ref", f"{ref.get('type', 'reference')}={ref.get('ref', '')}"])
    proc = subprocess.run(cmd, cwd=repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout)


def ranked_records(root: Path, *, include_expired: bool) -> list[dict[str, Any]]:
    rows = read_jsonl(queue_path(root))
    for row in rows:
        row["status"] = status_for_expiry(str(row.get("expires_at", "")))
    if not include_expired:
        rows = [row for row in rows if row.get("status") != "expired"]
    rows.sort(key=lambda row: (float_value(row.get("expected_value_score")), float_value(row.get("confidence"))), reverse=True)
    return rows


def render_report(root: Path, records: list[dict[str, Any]]) -> str:
    lines = [
        f"# Hermes Opportunity Engine Report - {utc_now()}",
        "",
        "## Boundary",
        "",
        "- Local opportunity queue and reports only.",
        "- No sending, posting, purchases, account changes, credential entry, or platform actions.",
        "- Expired opportunities are excluded from ranked output by default.",
        "",
        "## Ranked Queue",
        "",
        "| Rank | Opportunity | Customer | Offer | Channel | EV Score | Confidence | Evidence | Expires |",
        "|---:|---|---|---|---|---:|---:|---|---|",
    ]
    if records:
        for idx, item in enumerate(records, start=1):
            evidence_status = item.get("evidence_validation", {}).get("status", "unknown")
            lines.append(
                f"| {idx} | {item.get('opportunity_id')} | {item.get('customer_segment')} | {item.get('offer')} | "
                f"{item.get('channel')} | {float_value(item.get('expected_value_score')):.4f} | "
                f"{float_value(item.get('confidence')):.2f} | {evidence_status} | {item.get('expires_at')} |"
            )
    else:
        lines.append("| 0 | none | none | none | none | 0.0000 | 0.00 | none | none |")
    return "\n".join(lines) + "\n"


def cmd_normalize(args: argparse.Namespace) -> int:
    root = Path(args.root)
    source_file = Path(args.source_file)
    findings = load_source_findings(source_file)
    records = [normalized_opportunity(item, default_ttl_days=args.default_ttl_days, source_file=source_file) for item in findings]
    for record in records:
        append_jsonl(queue_path(root), record)
        if args.write_ledger:
            ledger_payload = run_ledger_record(root, Path(args.repo_root), record)
            record["ledger_opportunity_hash"] = ledger_payload.get("opportunity_hash", "")
            record["ledger_memory_status"] = ledger_payload.get("memory_status", "")
    output = {
        "schema_version": "opportunity-normalize-result-v1",
        "root": str(root),
        "queue": str(queue_path(root)),
        "source_file": str(source_file),
        "records_written": len(records),
        "opportunities": records,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    rows = ranked_records(Path(args.root), include_expired=args.include_expired)
    print(json.dumps({"schema_version": "opportunity-rank-v1", "opportunities": rows[: args.limit]}, indent=2, sort_keys=True))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rows = ranked_records(root, include_expired=args.include_expired)
    report = render_report(root, rows[: args.limit])
    out = reports_dir(root) / f"opportunity-engine-report-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"report={out}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    queue_path(root).touch(exist_ok=True)
    reports_dir(root).mkdir(parents=True, exist_ok=True)
    print(json.dumps({"root": str(root), "queue": str(queue_path(root)), "reports": str(reports_dir(root))}, indent=2, sort_keys=True))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(revenue_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Opportunity Engine v1")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_common(init)
    init.set_defaults(func=cmd_init)

    normalize = sub.add_parser("normalize")
    add_common(normalize)
    normalize.add_argument("--source-file", required=True)
    normalize.add_argument("--default-ttl-days", type=int, default=14)
    normalize.add_argument("--write-ledger", action="store_true")
    normalize.set_defaults(func=cmd_normalize)

    rank = sub.add_parser("rank")
    add_common(rank)
    rank.add_argument("--limit", type=int, default=10)
    rank.add_argument("--include-expired", action="store_true")
    rank.set_defaults(func=cmd_rank)

    report = sub.add_parser("report")
    add_common(report)
    report.add_argument("--limit", type=int, default=10)
    report.add_argument("--include-expired", action="store_true")
    report.set_defaults(func=cmd_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
