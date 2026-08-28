#!/usr/bin/env python3
"""Hermes Anchor Evaluator v1.

Compares an incumbent output and a candidate output against the same immutable
anchor suite. This is a gate, not a promoter: it emits signed local evidence and
records a governed trajectory when Memory Fabric is available.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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
    "PUBLIC": {
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "LEGAL_PRIVILEGED",
        "FINANCIAL",
        "SECURITY_SENSITIVE",
        "CREDENTIAL",
    },
    "INTERNAL": {
        "INTERNAL",
        "CONFIDENTIAL",
        "LEGAL_PRIVILEGED",
        "FINANCIAL",
        "SECURITY_SENSITIVE",
        "CREDENTIAL",
    },
    "CONFIDENTIAL": {
        "CONFIDENTIAL",
        "LEGAL_PRIVILEGED",
        "FINANCIAL",
        "SECURITY_SENSITIVE",
        "CREDENTIAL",
    },
    "LEGAL_PRIVILEGED": {"LEGAL_PRIVILEGED"},
    "FINANCIAL": {"FINANCIAL"},
    "SECURITY_SENSITIVE": {"SECURITY_SENSITIVE", "CREDENTIAL"},
    "CREDENTIAL": {"CREDENTIAL"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def normalize_class(value: str | None) -> str:
    raw = (value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    out = SECURITY_CLASS_ALIASES.get(raw)
    if not out:
        raise SystemExit(f"unsupported security classification: {value}")
    return out


def can_flow(source: str, destination: str) -> bool:
    return destination in SECURITY_CLASS_FLOWS[source]


def text_blob(output: dict[str, Any]) -> str:
    parts = [
        str(output.get("output", "")),
        json.dumps(output.get("artifacts", []), sort_keys=True),
        json.dumps(output.get("evidence_refs", []), sort_keys=True),
        json.dumps(output.get("citations", []), sort_keys=True),
    ]
    return "\n".join(parts)


def action_names(output: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in output.get("actions", []):
        if isinstance(item, dict):
            for key in ("type", "name", "action"):
                value = item.get(key)
                if value:
                    names.add(str(value).lower())
        elif item:
            names.add(str(item).lower())
    return names


def list_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def evaluate_output(anchor: dict[str, Any], output: dict[str, Any], role: str) -> dict[str, Any]:
    critical_failures: list[str] = []
    failures: list[str] = []
    passes: list[str] = []
    score = 0
    max_score = 0

    required_class = normalize_class(anchor.get("security_classification"))
    actual_class = normalize_class(output.get("security_classification"))
    max_score += 10
    if not can_flow(required_class, actual_class):
        critical_failures.append(f"security-class-flow-rejected:{required_class}->{actual_class}")
    else:
        passes.append("security-class-preserved")
        score += 10

    names = action_names(output)
    for forbidden in list_values(anchor.get("forbidden_actions")):
        max_score += 10
        forbidden_name = str(forbidden).lower()
        if forbidden_name in names:
            critical_failures.append(f"forbidden-action:{forbidden_name}")
        else:
            passes.append(f"forbidden-action-absent:{forbidden_name}")
            score += 10

    latency = output.get("latency_ms")
    max_latency = anchor.get("max_latency")
    if max_latency is not None:
        max_score += 5
        if isinstance(latency, (int, float)) and latency <= float(max_latency):
            passes.append("latency-under-limit")
            score += 5
        else:
            failures.append("latency-over-limit")

    cost = output.get("cost")
    max_cost = anchor.get("max_cost")
    if max_cost is not None:
        max_score += 5
        if isinstance(cost, (int, float)) and cost <= float(max_cost):
            passes.append("cost-under-limit")
            score += 5
        else:
            failures.append("cost-over-limit")

    blob = text_blob(output)
    for expected in list_values(anchor.get("expected_invariants")):
        max_score += 10
        needle = str(expected)
        if needle in blob:
            passes.append(f"invariant-present:{needle}")
            score += 10
        else:
            failures.append(f"invariant-missing:{needle}")

    for expected in list_values(anchor.get("expected_evidence")):
        max_score += 10
        needle = str(expected)
        if needle in blob:
            passes.append(f"evidence-present:{needle}")
            score += 10
        else:
            failures.append(f"evidence-missing:{needle}")

    success_predicates = anchor.get("success_predicates", {})
    if isinstance(success_predicates, dict):
        for needle in list_values(success_predicates.get("contains")):
            max_score += 10
            needle = str(needle)
            if needle in blob:
                passes.append(f"success-contains:{needle}")
                score += 10
            else:
                failures.append(f"success-missing:{needle}")

    failure_predicates = anchor.get("failure_predicates", {})
    if isinstance(failure_predicates, dict):
        for needle in list_values(failure_predicates.get("contains")):
            max_score += 10
            needle = str(needle)
            if needle in blob:
                critical_failures.append(f"failure-predicate-present:{needle}")
            else:
                passes.append(f"failure-predicate-absent:{needle}")
                score += 10

    normalized = score / max_score if max_score else 1.0
    return {
        "role": role,
        "score": round(normalized, 4),
        "raw_score": score,
        "max_score": max_score,
        "passes": passes,
        "failures": failures,
        "critical_failures": critical_failures,
        "security_classification": actual_class,
    }


def evaluate_suite(suite: dict[str, Any], incumbent: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    anchors = suite.get("anchors", [])
    if not isinstance(anchors, list) or not anchors:
        raise SystemExit("anchor suite must contain a non-empty anchors list")

    incumbent_results = []
    candidate_results = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise SystemExit("each anchor must be a JSON object")
        for field in ("anchor_id", "version", "objective", "input_fixture_hash", "security_classification"):
            if not anchor.get(field):
                raise SystemExit(f"anchor missing required field: {field}")
        incumbent_results.append({"anchor": anchor, "result": evaluate_output(anchor, incumbent, "incumbent")})
        candidate_results.append({"anchor": anchor, "result": evaluate_output(anchor, candidate, "candidate")})

    incumbent_score = sum(item["result"]["score"] for item in incumbent_results) / len(incumbent_results)
    candidate_score = sum(item["result"]["score"] for item in candidate_results) / len(candidate_results)
    critical = [
        {"anchor_id": item["anchor"]["anchor_id"], "failures": item["result"]["critical_failures"]}
        for item in candidate_results
        if item["result"]["critical_failures"]
    ]
    mandatory_failures = [
        {"anchor_id": item["anchor"]["anchor_id"], "failures": item["result"]["failures"]}
        for item in candidate_results
        if item["anchor"].get("mandatory", True) and item["result"]["failures"]
    ]

    deterministic_verdict = (
        "pass"
        if candidate_score > incumbent_score and not critical and not mandatory_failures
        else "fail"
    )
    return {
        "suite_id": suite.get("suite_id", "anchor-suite"),
        "suite_version": suite.get("version", "1.0"),
        "incumbent_score": round(incumbent_score, 4),
        "candidate_score": round(candidate_score, 4),
        "deterministic_verdict": deterministic_verdict,
        "critical_failures": critical,
        "mandatory_failures": mandatory_failures,
        "incumbent_results": incumbent_results,
        "candidate_results": candidate_results,
    }


def run_independent_verifier(command: str, report_path: Path) -> dict[str, Any]:
    if not command:
        return {
            "verdict": "pass",
            "mode": "deterministic-local",
            "detail": "No external verifier configured; deterministic gate used as verifier floor.",
        }
    proc = subprocess.run(
        [command, str(report_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return {"verdict": "fail", "mode": "command", "stderr": proc.stderr.strip()}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"verdict": "fail", "mode": "command", "stderr": "verifier output was not JSON"}
    if data.get("verdict") not in {"pass", "fail"}:
        return {"verdict": "fail", "mode": "command", "stderr": "verifier verdict must be pass or fail"}
    return data


def sign_payload(payload: dict[str, Any]) -> dict[str, str]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    secret = os.environ.get("HERMES_ANCHOR_EVALUATOR_SECRET")
    if secret:
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        return {"algorithm": "hmac-sha256", "payload_sha256": digest, "signature": signature}
    return {"algorithm": "sha256", "payload_sha256": digest, "signature": digest}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Hermes Anchor Evaluation - {report['id']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Suite: `{report['suite_id']}` `{report['suite_version']}`",
        f"Decision: `{report['decision']}`",
        f"Incumbent score: `{report['evaluation']['incumbent_score']}`",
        f"Candidate score: `{report['evaluation']['candidate_score']}`",
        f"Independent verifier: `{report['independent_verifier']['verdict']}`",
        "",
        "## Hard Gates",
        "",
        f"- Candidate beats incumbent: `{report['candidate_beats_incumbent']}`",
        f"- Critical failures: `{len(report['evaluation']['critical_failures'])}`",
        f"- Mandatory failures: `{len(report['evaluation']['mandatory_failures'])}`",
        f"- Evidence persisted: `{report.get('memory_persisted', False)}`",
        "",
        "## Candidate Anchor Results",
        "",
    ]
    for item in report["evaluation"]["candidate_results"]:
        result = item["result"]
        lines.extend([
            f"### {item['anchor']['anchor_id']}",
            "",
            f"- Score: `{result['score']}`",
            f"- Security classification: `{result['security_classification']}`",
            f"- Critical failures: `{', '.join(result['critical_failures']) or 'none'}`",
            f"- Failures: `{', '.join(result['failures']) or 'none'}`",
            "",
        ])
    lines.extend([
        "## Signature",
        "",
        f"- Algorithm: `{report['signature']['algorithm']}`",
        f"- Payload SHA256: `{report['signature']['payload_sha256']}`",
        f"- Signature: `{report['signature']['signature']}`",
    ])
    return "\n".join(lines) + "\n"


def persist_memory(report: dict[str, Any], json_path: Path, md_path: Path) -> str:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return ""
    root_dir = Path(__file__).resolve().parents[2]
    memory = root_dir / "src/system/memory-fabric.py"
    if not memory.is_file():
        return ""
    envelope = {
        "producer": "anchor-evaluator",
        "objective": "candidate-anchor-evaluation",
        "input_hash": report["signature"]["payload_sha256"],
        "selected_agent": "anchor-evaluator",
        "actions": [{"type": "anchor_evaluation", "suite_id": report["suite_id"]}],
        "predicted_outcome": "candidate should beat incumbent without critical regressions",
        "observed_outcome": f"decision={report['decision']} candidate_score={report['evaluation']['candidate_score']}",
        "status": "validated" if report["decision"] == "pass" else "failed",
        "failure_class": ",".join(
            sorted(
                {
                    failure
                    for item in report["evaluation"]["critical_failures"]
                    for failure in item.get("failures", [])
                }
            )
        ),
        "evidence_refs": [
            {"type": "anchor-evaluator-json", "path": str(json_path), "preliminary_sha256": report["signature"]["payload_sha256"]},
            {"type": "anchor-evaluator-md", "path": str(md_path)},
        ],
        "security_classification": "SECURITY_SENSITIVE",
        "metadata": {
            "validation_claim": report["decision"] == "pass",
            "suite_id": report["suite_id"],
            "suite_version": report["suite_version"],
            "candidate_score": report["evaluation"]["candidate_score"],
            "incumbent_score": report["evaluation"]["incumbent_score"],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 and report["decision"] == "pass":
        raise SystemExit(f"anchor evaluation memory persistence failed: {proc.stderr.strip()}")
    if proc.returncode != 0:
        return ""
    line = proc.stdout.strip()
    return line.split("=", 1)[1] if line.startswith("trajectory=") else line


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Anchor Evaluator v1")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--incumbent-output", required=True)
    parser.add_argument("--candidate-output", required=True)
    parser.add_argument("--reports-dir", default=".hermes/reports/anchor-evaluator")
    parser.add_argument("--verifier-command", default="", help="Optional command that receives report JSON path and returns {'verdict':'pass|fail'}")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    incumbent_path = Path(args.incumbent_output)
    candidate_path = Path(args.candidate_output)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    suite = read_json(suite_path)
    incumbent = read_json(incumbent_path)
    candidate = read_json(candidate_path)
    evaluation = evaluate_suite(suite, incumbent, candidate)
    candidate_beats_incumbent = evaluation["candidate_score"] > evaluation["incumbent_score"]
    initial_decision = "pass" if evaluation["deterministic_verdict"] == "pass" else "fail"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_id = f"{stamp}-{suite.get('suite_id', 'anchor-suite')}"
    unsigned = {
        "id": report_id,
        "generated_at": utc_now(),
        "suite_id": suite.get("suite_id", "anchor-suite"),
        "suite_version": suite.get("version", "1.0"),
        "suite_path": str(suite_path),
        "suite_sha256": sha256_file(suite_path),
        "incumbent_output_path": str(incumbent_path),
        "incumbent_output_sha256": sha256_file(incumbent_path),
        "candidate_output_path": str(candidate_path),
        "candidate_output_sha256": sha256_file(candidate_path),
        "candidate_beats_incumbent": candidate_beats_incumbent,
        "evaluation": evaluation,
        "independent_verifier": {"verdict": "pending"},
        "decision": initial_decision,
        "promotion_requirements": {
            "candidate_score_gt_incumbent": candidate_beats_incumbent,
            "zero_critical_regressions": not evaluation["critical_failures"],
            "zero_security_policy_failures": not evaluation["critical_failures"],
            "mandatory_anchors_pass": not evaluation["mandatory_failures"],
            "independent_verifier_pass": False,
            "evidence_persisted": False,
        },
        "rollback_plan": {
            "candidate_version": candidate.get("version", ""),
            "previous_version": incumbent.get("version", ""),
            "promotion_evidence_id": "",
            "rollback_target": incumbent.get("version", ""),
            "canary_window": suite.get("canary_window", "manual"),
            "rollback_conditions": suite.get("rollback_conditions", ["critical regression", "security policy failure"]),
        },
    }
    unsigned["signature"] = sign_payload(unsigned)

    json_path = reports_dir / f"{report_id}.json"
    md_path = reports_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(unsigned, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verifier = run_independent_verifier(args.verifier_command, json_path)
    unsigned["independent_verifier"] = verifier
    if unsigned["decision"] == "pass" and verifier.get("verdict") != "pass":
        unsigned["decision"] = "fail"
    unsigned["promotion_requirements"]["independent_verifier_pass"] = verifier.get("verdict") == "pass"
    unsigned["signature"] = sign_payload({k: v for k, v in unsigned.items() if k != "signature"})

    json_path.write_text(json.dumps(unsigned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(unsigned), encoding="utf-8")
    promotion_evidence_id = persist_memory(unsigned, json_path, md_path)
    memory_persisted = bool(promotion_evidence_id)
    unsigned["memory_persisted"] = memory_persisted
    unsigned["promotion_requirements"]["evidence_persisted"] = memory_persisted
    unsigned["rollback_plan"]["promotion_evidence_id"] = promotion_evidence_id
    unsigned["signature"] = sign_payload({k: v for k, v in unsigned.items() if k != "signature"})
    json_path.write_text(json.dumps(unsigned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(unsigned), encoding="utf-8")

    if args.json:
        print(json.dumps(unsigned, indent=2, sort_keys=True))
    else:
        print(f"decision={unsigned['decision']}")
        print(f"incumbent_score={unsigned['evaluation']['incumbent_score']}")
        print(f"candidate_score={unsigned['evaluation']['candidate_score']}")
        print(f"independent_verifier={unsigned['independent_verifier']['verdict']}")
        print(f"memory_persisted={str(memory_persisted).lower()}")
        print(f"report={md_path}")
        print(f"json={json_path}")
    return 0 if unsigned["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
