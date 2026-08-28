#!/usr/bin/env python3
"""Hermes Candidate Generator v1.

Builds immutable candidate packages from Failure Intelligence clusters. This is
proposal-package generation only: it does not edit files, anchors, skills,
routing, runtime config, or promotion state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_precise() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
    fsync_file(path)


def fsync_file(path: Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def finalize_package_dir(tmp_dir: Path, package_dir: Path) -> None:
    if package_dir.exists():
        raise SystemExit(f"candidate package already exists; refusing to overwrite immutable package: {package_dir}")
    fsync_dir(tmp_dir)
    fsync_dir(package_dir.parent)
    try:
        os.replace(tmp_dir, package_dir)
    except FileExistsError:
        raise SystemExit(f"candidate package already exists; refusing to overwrite immutable package: {package_dir}") from None
    fsync_dir(package_dir.parent)


def new_candidate_identity(cluster: dict[str, Any]) -> tuple[str, str, str]:
    generation_nonce = utc_now_precise()
    random_nonce = uuid.uuid4().hex
    root_hash = str(cluster.get("root_signature_hash") or cluster.get("signature_hash") or "")
    candidate_id = "cand_" + sha256_json(
        {
            "cluster_id": cluster["cluster_id"],
            "root_signature_hash": root_hash,
            "generation_nonce": generation_nonce,
            "random_nonce": random_nonce,
        }
    )[:20]
    return candidate_id, generation_nonce, random_nonce


def default_failure_dir() -> Path:
    return Path(os.environ.get("HERMES_FAILURE_INTEL_DIR", ".hermes/failure-intelligence"))


def default_candidate_dir() -> Path:
    return Path(os.environ.get("HERMES_CANDIDATE_DIR", ".hermes/candidates"))


def load_clusters(failure_dir: Path) -> list[dict[str, Any]]:
    path = failure_dir / "clusters.json"
    if not path.is_file():
        raise SystemExit(f"cluster artifact not found; run failure-intelligence scan first: {path}")
    data = read_json(path)
    clusters = data.get("clusters", [])
    if not isinstance(clusters, list):
        raise SystemExit(f"invalid cluster artifact: {path}")
    return [cluster for cluster in clusters if isinstance(cluster, dict)]


def find_cluster(failure_dir: Path, cluster_id: str) -> dict[str, Any]:
    for cluster in load_clusters(failure_dir):
        if cluster.get("cluster_id") == cluster_id:
            return cluster
    raise SystemExit(f"cluster not found: {cluster_id}")


def evidence_hashes(cluster: dict[str, Any], failure_dir: Path) -> list[str]:
    hashes = {sha256_text((failure_dir / "clusters.json").read_text(encoding="utf-8"))}
    for ref in cluster.get("evidence_refs", []):
        if isinstance(ref, dict) and ref.get("sha256"):
            hashes.add(str(ref["sha256"]))
    return sorted(hashes)


def base_version_hashes(cluster: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ref in cluster.get("evidence_refs", []):
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("path") or "")
        digest = str(ref.get("sha256") or "")
        if path and digest:
            out[path] = digest
    return out


def target_component(cluster: dict[str, Any]) -> str:
    root = cluster.get("root_signature", {}) if isinstance(cluster.get("root_signature"), dict) else {}
    if root.get("subsystem"):
        return str(root["subsystem"])
    if cluster.get("affected_skills"):
        return str(cluster["affected_skills"][0])
    if cluster.get("affected_models"):
        return str(cluster["affected_models"][0])
    return "unknown"


def risk_class(cluster: dict[str, Any]) -> str:
    severity = str(cluster.get("severity") or "medium")
    return "high" if severity in {"critical", "high"} else "medium"


def regression_test_spec(cluster: dict[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "artifact_type": "candidate-regression-test-spec",
        "source_cluster_id": cluster["cluster_id"],
        "root_signature_hash": cluster.get("root_signature_hash") or cluster.get("signature_hash"),
        "source_trajectory_ids": cluster.get("representative_trajectory_ids", []),
        "test_objective": f"Reproduce and prevent recurrence of failure cluster {cluster['cluster_id']}",
        "fixtures": [
            {
                "trajectory_id": trajectory_id,
                "expected_failure_signature": cluster.get("root_signature", {}),
            }
            for trajectory_id in cluster.get("representative_trajectory_ids", [])
        ],
        "assertions": [
            "candidate output does not reproduce the root failure signature",
            "candidate preserves approval, classification, evidence, and anchor gates",
            "candidate does not require anchor-suite changes",
            "candidate does not reduce Trust Gate, verifier, canary, or rollback requirements",
        ],
        "created_before_candidate_spec": True,
        "created_at": created_at,
    }


def candidate_manifest_body(
    cluster: dict[str, Any],
    failure_dir: Path,
    regression_path: Path,
    generator_model: str,
    candidate_id: str,
    generation_nonce: str,
    generated_at: str,
) -> dict[str, Any]:
    root_hash = str(cluster.get("root_signature_hash") or cluster.get("signature_hash") or "")
    source_ids = [str(item) for item in cluster.get("representative_trajectory_ids", [])]
    security_classification = ",".join(cluster.get("security_classifications", [])) or "INTERNAL"
    component = target_component(cluster)
    return {
        "artifact_type": "hermes-candidate-package",
        "candidate_id": candidate_id,
        "generation_nonce": generation_nonce,
        "source_cluster_id": cluster["cluster_id"],
        "root_signature_hash": root_hash,
        "root_signature": cluster.get("root_signature", {}),
        "source_trajectory_ids": source_ids,
        "source_evidence_hashes": evidence_hashes(cluster, failure_dir),
        "causal_hypothesis": "; ".join(cluster.get("suspected_causes", [])),
        "hypothesis_confidence": cluster.get("confidence", 0.5),
        "target_component": component,
        "change_type": "bounded_candidate_specification",
        "affected_paths": [],
        "affected_files_or_skills": sorted(
            set(cluster.get("affected_skills", []) + cluster.get("affected_models", []) + cluster.get("affected_profiles", []))
        ),
        "base_version_hashes": base_version_hashes(cluster),
        "proposed_diff": {
            "format": "unified_diff",
            "content": "",
            "status": "not_generated_by_v1",
            "reason": "Candidate Generator v1 creates a governed package and regression spec; implementation remains a later sandboxed step.",
        },
        "candidate_implementation": {
            "mode": "specification_only",
            "instructions": [
                "Generate one bounded implementation that addresses the root signature.",
                "Do not modify frozen anchors, promotion criteria, approval gates, classification gates, evidence gates, or rollback rules.",
                "Attach the regression test spec before implementation review.",
            ],
        },
        "new_regression_tests": [str(regression_path)],
        "expected_improvement": "Reduce recurrence of this failure cluster without weakening governance gates.",
        "possible_regressions": [
            "Overfit to representative failures and miss other context dimensions.",
            "Weaken approval, classification, evidence, anchor, verifier, canary, or rollback behavior.",
        ],
        "security_classification": security_classification,
        "risk_class": risk_class(cluster),
        "existing_anchor_ids": [],
        "required_anchor_changes": [],
        "benchmark_gap_proposal": None,
        "generator_model": generator_model,
        "generator_version": "candidate-generator-v1",
        "generated_at": generated_at,
        "candidate_manifest_hash_scope": "sha256_json over canonical manifest JSON with candidate_manifest_hash omitted",
        "governance_boundaries": [
            "proposal-package-only",
            "no automatic mutation",
            "required_anchor_changes must remain empty",
            "benchmark gaps require a separate benchmark-gap-proposal",
            "must pass Trust Gate, sandbox tests, Anchor Evaluator, independent verifier, canary, rollback safety, and Memory Fabric evidence",
        ],
    }


def create_candidate_package(cluster: dict[str, Any], failure_dir: Path, candidate_dir: Path, generator_model: str) -> dict[str, Any]:
    candidate_id, generation_nonce, _random_nonce = new_candidate_identity(cluster)
    package_dir = candidate_dir / candidate_id
    tmp_dir = candidate_dir / f".tmp-{candidate_id}"
    if package_dir.exists():
        raise SystemExit(f"candidate package already exists; refusing to overwrite immutable package: {package_dir}")
    if tmp_dir.exists():
        raise SystemExit(f"stale candidate staging directory exists; remove it before retrying: {tmp_dir}")
    tmp_dir.mkdir(parents=True, exist_ok=False)

    regression_path = tmp_dir / "regression-test-spec.json"
    regression_created_at = utc_now_precise()
    regression = regression_test_spec(cluster, regression_created_at)
    write_json(regression_path, regression)

    generated_at = utc_now_precise()
    manifest = candidate_manifest_body(
        cluster,
        failure_dir,
        package_dir / "regression-test-spec.json",
        generator_model,
        candidate_id,
        generation_nonce,
        generated_at,
    )
    manifest["regression_test_spec_hash"] = sha256_text(regression_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_json(manifest)
    manifest["candidate_manifest_hash"] = manifest_hash
    manifest_path = tmp_dir / "candidate-manifest.json"
    write_json(manifest_path, manifest)

    receipt = {
        "artifact_type": "candidate-package-receipt",
        "candidate_id": manifest["candidate_id"],
        "source_cluster_id": cluster["cluster_id"],
        "candidate_manifest_path": str(package_dir / "candidate-manifest.json"),
        "candidate_manifest_hash": manifest_hash,
        "candidate_manifest_hash_scope": manifest["candidate_manifest_hash_scope"],
        "regression_test_spec_path": str(regression_path),
        "regression_test_spec_hash": manifest["regression_test_spec_hash"],
        "created_at": utc_now_precise(),
        "package_immutable": True,
    }
    receipt["regression_test_spec_path"] = str(package_dir / "regression-test-spec.json")
    receipt_path = tmp_dir / "candidate-receipt.json"
    write_json(receipt_path, receipt)
    try:
        finalize_package_dir(tmp_dir, package_dir)
    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise
    return {
        "package_dir": str(package_dir),
        "manifest": str(package_dir / "candidate-manifest.json"),
        "receipt": str(package_dir / "candidate-receipt.json"),
        **receipt,
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_generate(args: argparse.Namespace) -> int:
    failure_dir = Path(args.failure_dir)
    candidate_dir = Path(args.candidate_dir)
    cluster = find_cluster(failure_dir, args.cluster_id)
    result = create_candidate_package(cluster, failure_dir, candidate_dir, args.generator_model)
    print_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Candidate Generator v1")
    parser.add_argument("--failure-dir", default=str(default_failure_dir()))
    parser.add_argument("--candidate-dir", default=str(default_candidate_dir()))
    parser.add_argument("--generator-model", default=os.environ.get("HERMES_GENERATOR_MODEL", "deterministic-v1"))
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Create a candidate package from one failure cluster")
    generate.add_argument("cluster_id")
    generate.set_defaults(func=cmd_generate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
