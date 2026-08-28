#!/usr/bin/env python3
"""Hermes Failure Intelligence v1.

Reads governed Memory Fabric trajectory envelopes, extracts recurring failure
signatures, clusters them, and writes bounded proposal artifacts. This tool is
analysis-only: it does not edit skills, anchors, routing, or runtime config.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FAILURE_STATUSES = {"blocked", "error", "failed", "failure", "rejected", "rollback_unverified"}
RECOVERY_STATUSES = {"recovered", "resolved"}
SUCCESS_STATUSES = {"completed", "success", "passed", "validated", "canary_passed", "rolled_back"}
SECURITY_SEVERITY_CLASSES = {"CREDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE"}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*", re.I)
URL_RE = re.compile(r"https?://[^\s)>\"]+", re.I)
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
TIMESTAMP_RE = re.compile(
    r"\b(?:20\d{2}[-_/]?\d{2}[-_/]?\d{2})(?:[T _-]?\d{2}:?\d{2}:?\d{2}(?:Z|[+-]\d{2}:?\d{2})?)?\b"
)
HASH_RE = re.compile(r"\b(?:sha256:)?[0-9a-f]{16,}\b", re.I)
DURATION_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|sec|secs|seconds?|m|min|mins|minutes?)\b", re.I)
ABS_PATH_RE = re.compile(r"(?:/[A-Za-z0-9._%+@-]+){2,}")
NUMERIC_ID_RE = re.compile(r"\b\d{4,}\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    base = raw.split("?", 1)[0].split("#", 1)[0]
    return base or "<URL>"


def canonicalize_volatile(value: str) -> str:
    text = value or ""
    text = URL_RE.sub(normalize_url, text)
    text = UUID_RE.sub("<UUID>", text)
    text = TIMESTAMP_RE.sub("<TIMESTAMP>", text)
    text = HASH_RE.sub("<HASH>", text)
    text = ABS_PATH_RE.sub("<PATH>", text)
    text = DURATION_RE.sub("<DURATION>", text)
    text = NUMERIC_ID_RE.sub("<ID>", text)
    return text


def load_trajectories(db_path: Path, limit: int = 1000) -> list[dict[str, Any]]:
    if not db_path.is_file():
        raise SystemExit(f"Memory Fabric DB not found: {db_path}")
    root_dir = Path(__file__).resolve().parents[2]
    memory = root_dir / "src/system/memory-fabric.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(memory),
            "--db",
            str(db_path),
            "export-trajectories",
            "--limit",
            str(int(limit)),
            "--jsonl",
        ],
        cwd=root_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "Memory Fabric trajectory export failed")
    trajectories = []
    for line in proc.stdout.splitlines():
        if line.strip():
            trajectories.append(json.loads(line))
    return trajectories


def is_failure(traj: dict[str, Any]) -> bool:
    status = str(traj.get("status", "")).lower()
    metadata = traj.get("metadata") if isinstance(traj.get("metadata"), dict) else {}
    if status in SUCCESS_STATUSES or is_recovery(traj):
        return False
    return (
        status in FAILURE_STATUSES
        or bool(metadata.get("critical_security_failure"))
        or bool(metadata.get("mandatory_anchor_failure"))
        or bool(metadata.get("governance_rejection"))
        or metadata.get("evidence_persisted") is False
        or bool(str(traj.get("failure_class", "")).strip())
    )


def is_recovery(traj: dict[str, Any]) -> bool:
    status = str(traj.get("status", "")).lower()
    metadata = traj.get("metadata") if isinstance(traj.get("metadata"), dict) else {}
    return status in RECOVERY_STATUSES or bool(metadata.get("recovery")) or bool(metadata.get("recovery_for_signature"))


def norm_text(value: str, max_tokens: int = 8) -> str:
    tokens = [token.lower() for token in TOKEN_RE.findall(canonicalize_volatile(value or "")) if len(token) > 2]
    return " ".join(tokens[:max_tokens])


def action_types(traj: dict[str, Any]) -> list[str]:
    actions = traj.get("actions") if isinstance(traj.get("actions"), list) else []
    out = []
    for action in actions:
        if isinstance(action, dict) and action.get("type"):
            out.append(str(action["type"]))
    return sorted(set(out))


def root_signature(traj: dict[str, Any]) -> dict[str, Any]:
    metadata = traj.get("metadata") if isinstance(traj.get("metadata"), dict) else {}
    failure_class = norm_text(str(traj.get("failure_class") or "")) or f"status:{str(traj.get('status', '')).lower()}"
    raw_observed = str(traj.get("observed_outcome") or "")
    observed = norm_text(raw_observed)
    actions = action_types(traj)
    return {
        "failure_class": failure_class,
        "subsystem": norm_text(str(metadata.get("subsystem") or metadata.get("component") or traj.get("producer") or ""), max_tokens=4),
        "operation": norm_text(str(metadata.get("operation") or " ".join(actions) or traj.get("objective") or ""), max_tokens=4),
        "normalized_observed_fingerprint": observed,
        "observed_failure": observed,
        "security_compartment": str(traj.get("security_classification") or "INTERNAL").upper(),
        "action_type": actions[0] if actions else "",
    }


def context_signature(traj: dict[str, Any]) -> dict[str, Any]:
    metadata = traj.get("metadata") if isinstance(traj.get("metadata"), dict) else {}
    model = str(traj.get("model") or "")
    provider = str(metadata.get("provider") or (model.split("/", 1)[0] if "/" in model else ""))
    return {
        "model": str(traj.get("model") or ""),
        "selected_agent": str(traj.get("selected_agent") or ""),
        "profile": str(metadata.get("profile") or ""),
        "project": str(metadata.get("project") or ""),
        "provider": provider,
        "selected_skills": sorted(str(item) for item in traj.get("selected_skills", []) if str(item)),
    }


def dimension_counts(contexts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    dimensions: dict[str, Counter[str]] = {
        "models": Counter(),
        "agents": Counter(),
        "profiles": Counter(),
        "providers": Counter(),
        "projects": Counter(),
        "skills": Counter(),
    }
    for context in contexts:
        if context.get("model"):
            dimensions["models"][str(context["model"])] += 1
        if context.get("selected_agent"):
            dimensions["agents"][str(context["selected_agent"])] += 1
        if context.get("profile"):
            dimensions["profiles"][str(context["profile"])] += 1
        if context.get("provider"):
            dimensions["providers"][str(context["provider"])] += 1
        if context.get("project"):
            dimensions["projects"][str(context["project"])] += 1
        for skill in context.get("selected_skills", []):
            dimensions["skills"][str(skill)] += 1
    return {key: dict(counter.most_common()) for key, counter in dimensions.items()}


def aggregate_evidence_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    refs = []
    for item in items:
        for ref in item.get("evidence_refs", []):
            if not isinstance(ref, dict):
                continue
            key = sha256_json(ref)
            if key not in seen:
                seen.add(key)
                refs.append(ref)
    return refs


def failure_signature(traj: dict[str, Any]) -> dict[str, Any]:
    root = root_signature(traj)
    return {
        **root,
        "root_signature": root,
        "context_signature": context_signature(traj),
        "action_types": action_types(traj),
    }


def cluster_id(signature_hash: str) -> str:
    return f"failcl_{signature_hash[:20]}"


def severity_for(cluster_items: list[dict[str, Any]]) -> str:
    classes = {str(item.get("security_classification") or "").upper() for item in cluster_items}
    failure_text = " ".join(str(item.get("failure_class") or "").lower() for item in cluster_items)
    statuses = {str(item.get("status") or "").lower() for item in cluster_items}
    if classes & SECURITY_SEVERITY_CLASSES:
        return "critical"
    if any(term in failure_text for term in ("security", "credential", "classification", "privilege", "rollback_unverified")):
        return "critical"
    if "blocked" in statuses or "rejected" in statuses or len(cluster_items) >= 3:
        return "high"
    if len(cluster_items) >= 2:
        return "medium"
    return "low"


def suspected_causes(items: list[dict[str, Any]]) -> list[str]:
    text = " ".join(
        " ".join(
            [
                str(item.get("failure_class") or ""),
                str(item.get("observed_outcome") or ""),
                json.dumps(item.get("metadata") or {}, sort_keys=True),
            ]
        ).lower()
        for item in items
    )
    causes = []
    patterns = [
        ("evidence persistence", ("evidence", "persist", "receipt")),
        ("classification or compartment policy", ("classification", "credential", "privilege", "security_classification")),
        ("tool or bridge execution", ("tool", "bridge", "shizuku", "termux", "command")),
        ("latency or cost ceiling", ("latency", "cost", "ceiling", "timeout")),
        ("anchor or validation regression", ("anchor", "validator", "verifier", "regression")),
        ("governance rejection", ("governance", "rejected", "approval")),
    ]
    for label, terms in patterns:
        if any(term in text for term in terms):
            causes.append(label)
    if not causes:
        causes.append("insufficient trajectory detail; inspect representative runs")
    return causes


def confidence_for(items: list[dict[str, Any]]) -> float:
    evidence_count = sum(1 for item in items if item.get("evidence_refs"))
    base = 0.45 + min(len(items), 5) * 0.08 + min(evidence_count, 5) * 0.04
    return round(min(base, 0.95), 2)


def cluster_failures(trajectories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = [item for item in trajectories if is_failure(item)]
    recoveries = [item for item in trajectories if is_recovery(item)]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    signatures: dict[str, dict[str, Any]] = {}
    for item in failures:
        signature = root_signature(item)
        sig_hash = sha256_json(signature)
        grouped[sig_hash].append(item)
        signatures[sig_hash] = signature

    clusters = []
    for sig_hash, items in grouped.items():
        items_sorted = sorted(items, key=lambda item: str(item.get("timestamp") or item.get("created_at") or ""))
        affected_skills = sorted({skill for item in items for skill in item.get("selected_skills", []) if str(skill)})
        affected_models = sorted({str(item.get("model")) for item in items if str(item.get("model") or "")})
        affected_profiles = sorted(
            {
                str((item.get("metadata") or {}).get("profile"))
                for item in items
                if isinstance(item.get("metadata"), dict) and str((item.get("metadata") or {}).get("profile") or "")
            }
        )
        security_classes = sorted({str(item.get("security_classification") or "INTERNAL") for item in items})
        contexts = [context_signature(item) for item in items]
        related_recoveries = [
            item for item in recoveries
            if (item.get("metadata") or {}).get("recovery_for_signature") in {sig_hash, cluster_id(sig_hash)}
        ]
        cluster = {
            "cluster_id": cluster_id(sig_hash),
            "signature_hash": sig_hash,
            "root_signature_hash": sig_hash,
            "root_signature": signatures[sig_hash],
            "raw_observed_hashes": sorted({sha256_text(str(item.get("observed_outcome") or "")) for item in items}),
            "context_signatures": contexts,
            "context_signature_hashes": sorted({sha256_json(context) for context in contexts}),
            "context_dimensions": dimension_counts(contexts),
            "signature": signatures[sig_hash],
            "failure_class": signatures[sig_hash]["failure_class"],
            "affected_skills": affected_skills,
            "affected_models": affected_models,
            "affected_profiles": affected_profiles,
            "security_classifications": security_classes,
            "occurrence_count": len(items),
            "first_seen": str(items_sorted[0].get("timestamp") or items_sorted[0].get("created_at") or ""),
            "last_seen": str(items_sorted[-1].get("timestamp") or items_sorted[-1].get("created_at") or ""),
            "severity": severity_for(items),
            "representative_trajectory_ids": [str(item.get("id")) for item in items_sorted[:5]],
            "evidence_refs": aggregate_evidence_refs(items_sorted),
            "successful_recoveries": [str(item.get("id")) for item in related_recoveries if str(item.get("status", "")).lower() in RECOVERY_STATUSES],
            "failed_recoveries": [
                str(item.get("id")) for item in items
                if isinstance(item.get("metadata"), dict) and item["metadata"].get("recovery_attempt")
            ],
            "suspected_causes": suspected_causes(items),
            "confidence": confidence_for(items),
        }
        clusters.append(cluster)
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    clusters.sort(key=lambda c: (severity_rank.get(c["severity"], 9), -int(c["occurrence_count"]), c["cluster_id"]))
    return clusters


def default_db_path() -> Path:
    return Path(os.environ.get("HERMES_MEMORY_DB", ".hermes/memory/memory-fabric.sqlite3"))


def default_output_dir() -> Path:
    return Path(os.environ.get("HERMES_FAILURE_INTEL_DIR", ".hermes/failure-intelligence"))


def write_clusters(output_dir: Path, clusters: list[dict[str, Any]], source_db: Path) -> Path:
    payload = {
        "artifact_type": "failure-intelligence-clusters",
        "generated_at": utc_now(),
        "source_db": str(source_db),
        "cluster_count": len(clusters),
        "clusters": clusters,
    }
    path = output_dir / "clusters.json"
    write_json(path, payload)
    jsonl = output_dir / "clusters.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text("".join(json.dumps(cluster, sort_keys=True) + "\n" for cluster in clusters), encoding="utf-8")
    return path


def load_clusters(output_dir: Path) -> list[dict[str, Any]]:
    path = output_dir / "clusters.json"
    if not path.is_file():
        raise SystemExit(f"cluster artifact not found; run scan first: {path}")
    payload = read_json(path)
    clusters = payload.get("clusters", [])
    if not isinstance(clusters, list):
        raise SystemExit(f"invalid cluster artifact: {path}")
    return [cluster for cluster in clusters if isinstance(cluster, dict)]


def find_cluster(output_dir: Path, cid: str) -> dict[str, Any]:
    for cluster in load_clusters(output_dir):
        if cluster.get("cluster_id") == cid:
            return cluster
    raise SystemExit(f"cluster not found: {cid}")


def proposal_for(cluster: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    evidence_refs = [
        {
            "path": str(output_dir / "clusters.json"),
            "sha256": sha256_text((output_dir / "clusters.json").read_text(encoding="utf-8")),
        }
    ]
    affected = sorted(set(cluster.get("affected_skills", []) + cluster.get("affected_models", []) + cluster.get("affected_profiles", [])))
    risk_class = "high" if cluster.get("severity") in {"critical", "high"} else "medium"
    root = cluster.get("root_signature", {}) if isinstance(cluster.get("root_signature"), dict) else {}
    context_dimensions = cluster.get("context_dimensions", {}) if isinstance(cluster.get("context_dimensions"), dict) else {}
    existing_anchor_ids = sorted(
        {
            str(ref.get("anchor_id"))
            for ref in cluster.get("evidence_refs", [])
            if isinstance(ref, dict) and ref.get("anchor_id")
        }
    )
    return {
        "artifact_type": "failure-intelligence-proposal",
        "proposal_id": f"fiprop_{sha256_json({'cluster_id': cluster['cluster_id'], 'generated_at': utc_now()})[:20]}",
        "generated_at": utc_now(),
        "source_cluster_id": cluster["cluster_id"],
        "root_signature": root,
        "evidence_trajectory_ids": cluster.get("representative_trajectory_ids", []),
        "causal_hypothesis": "; ".join(cluster.get("suspected_causes", [])),
        "hypothesis_confidence": cluster.get("confidence", 0.5),
        "target_component": root.get("subsystem", ""),
        "proposed_change": (
            "Create one bounded candidate change that addresses this failure signature. "
            "Do not modify frozen anchors or promotion criteria in this proposal."
        ),
        "affected_files_or_skills": affected,
        "affected_paths": [],
        "expected_improvement": "Reduce recurrence of this signature without weakening safety gates or anchor requirements.",
        "possible_regressions": [
            "Overfitting to one failure cluster while missing broader context dimensions.",
            "Weakening an approval, classification, evidence, or anchor gate.",
        ],
        "security_classification": ",".join(cluster.get("security_classifications", [])) or "INTERNAL",
        "risk_class": risk_class,
        "existing_anchor_ids": existing_anchor_ids,
        "required_anchor_changes": [],
        "new_regression_tests": [
            f"Add a regression fixture reproducing failure cluster {cluster['cluster_id']}.",
            "Assert the candidate preserves existing approval, classification, and evidence-persistence gates.",
            f"Run the regression across context dimensions: {json.dumps(context_dimensions, sort_keys=True)}",
        ],
        "evidence_refs": evidence_refs,
        "governance_boundaries": [
            "proposal-only",
            "no automatic mutation",
            "no anchor-suite changes",
            "must pass Trust Gate, Anchor Evaluator, independent verifier, canary, and rollback evidence checks",
        ],
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_scan(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    trajectories = load_trajectories(db_path, limit=args.limit)
    clusters = cluster_failures(trajectories)
    artifact = write_clusters(output_dir, clusters, db_path)
    print_json({"clusters": len(clusters), "artifact": str(artifact)})
    return 0


def cmd_clusters(args: argparse.Namespace) -> int:
    clusters = load_clusters(Path(args.output_dir))
    rows = [
        {
            "cluster_id": cluster["cluster_id"],
            "severity": cluster["severity"],
            "occurrence_count": cluster["occurrence_count"],
            "failure_class": cluster["failure_class"],
            "affected_skills": cluster["affected_skills"],
            "affected_models": cluster["affected_models"],
        }
        for cluster in clusters[: args.limit]
    ]
    print_json(rows)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print_json(find_cluster(Path(args.output_dir), args.cluster_id))
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    cluster = find_cluster(output_dir, args.cluster_id)
    proposal = proposal_for(cluster, output_dir)
    path = output_dir / "proposals" / f"{proposal['proposal_id']}.json"
    write_json(path, proposal)
    print_json({"proposal": str(path), **proposal})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Failure Intelligence v1")
    parser.add_argument("--db", default=str(default_db_path()))
    parser.add_argument("--output-dir", default=str(default_output_dir()))
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan Memory Fabric trajectories and write clusters")
    scan.add_argument("--limit", type=int, default=1000)
    scan.set_defaults(func=cmd_scan)

    clusters = sub.add_parser("clusters", help="List failure clusters")
    clusters.add_argument("--limit", type=int, default=50)
    clusters.set_defaults(func=cmd_clusters)

    show = sub.add_parser("show", help="Show one failure cluster")
    show.add_argument("cluster_id")
    show.set_defaults(func=cmd_show)

    propose = sub.add_parser("propose", help="Write a bounded proposal for one cluster")
    propose.add_argument("cluster_id")
    propose.set_defaults(func=cmd_propose)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
