#!/usr/bin/env python3
"""Hermes Memory Fabric v1.

SQLite-backed evidence graph for Hermes/JARVIS. This tool is intentionally
local, deterministic, and append-first: corrections create new records and
supersession edges instead of rewriting prior evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NODE_TYPES = {
    "FACT",
    "DECISION",
    "EXPERIENCE",
    "FAILURE",
    "SKILL",
    "CODE",
    "PROVENANCE",
}

EDGE_TYPES = {
    "DERIVED_FROM",
    "SUPERSEDES",
    "CAUSED",
    "RESOLVED_BY",
    "USED_SKILL",
    "AFFECTS",
    "VALIDATED_BY",
}

VALIDATION_STATES = {
    "observed",
    "inferred",
    "validated",
    "disputed",
    "deprecated",
    "untrusted",
}

SECURITY_CLASSES = {
    "PUBLIC",
    "INTERNAL",
    "CONFIDENTIAL",
    "LEGAL_PRIVILEGED",
    "FINANCIAL",
    "CREDENTIAL",
    "SECURITY_SENSITIVE",
}

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
    "SECRET": "CREDENTIAL",
    "SECRETS": "CREDENTIAL",
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

TRAJECTORY_PRODUCERS = {
    "anchor-evaluator",
    "canary-controller",
    "external-source-sweep",
    "hermes-dispatch",
    "memory-fabric-test",
    "revenue-orchestrator",
    "revenue-ledger",
    "sandbox-candidate-executor",
    "skill-evolver",
    "trust-gate",
    "video-watch",
}

EVIDENCE_REQUIRED_STATUSES = {
    "allow",
    "promoted",
    "trusted_candidate",
    "validated",
    "sandbox_passed",
}

FAILURE_STATUSES = {
    "blocked",
    "error",
    "failed",
    "failure",
    "rejected",
    "rollback_unverified",
}

SUCCESS_AND_RECOVERY_STATUSES = {
    "completed",
    "success",
    "passed",
    "validated",
    "canary_passed",
    "recovered",
    "resolved",
    "rolled_back",
    "sandbox_passed",
}

SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|cookie|credential|otp|pass(word)?|secret|session|token)",
    re.I,
)

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bam_[A-Za-z0-9_]{24,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,}]{6,}"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    digest = sha256_text("\x1f".join(parts))[:20]
    return f"{prefix}_{digest}"


def normalize_security_classification(value: str | None) -> str:
    raw = (value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    normalized = SECURITY_CLASS_ALIASES.get(raw)
    if not normalized:
        raise SystemExit(f"unsupported security classification: {value}")
    return normalized


def can_flow_security_classification(source: str, destination: str) -> bool:
    return destination in SECURITY_CLASS_FLOWS[source]


def parse_json(value: str | None, field: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{field} must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{field} must be a JSON object")
    return data


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            source_uri TEXT NOT NULL DEFAULT '',
            source_hash TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            agent TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            security_classification TEXT NOT NULL DEFAULT 'internal',
            validation_state TEXT NOT NULL DEFAULT 'observed',
            created_at TEXT NOT NULL,
            ttl_seconds INTEGER,
            deprecated_at TEXT,
            supersedes_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            CHECK (confidence >= 0.0 AND confidence <= 1.0)
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
        CREATE INDEX IF NOT EXISTS idx_nodes_validation ON nodes(validation_state);
        CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created_at);
        CREATE INDEX IF NOT EXISTS idx_nodes_source_hash ON nodes(source_hash);

        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY,
            src_id TEXT NOT NULL,
            dst_id TEXT NOT NULL,
            type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (src_id) REFERENCES nodes(id),
            FOREIGN KEY (dst_id) REFERENCES nodes(id),
            CHECK (confidence >= 0.0 AND confidence <= 1.0)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
        CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);

        CREATE TABLE IF NOT EXISTS trajectories (
            id TEXT PRIMARY KEY,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            skill TEXT NOT NULL DEFAULT '',
            proposal_id TEXT NOT NULL DEFAULT '',
            input_hash TEXT NOT NULL DEFAULT '',
            prediction TEXT NOT NULL DEFAULT '',
            observed TEXT NOT NULL DEFAULT '',
            delta TEXT NOT NULL DEFAULT '',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            verifier_json TEXT NOT NULL DEFAULT '{}',
            run_id TEXT NOT NULL DEFAULT '',
            agent TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trajectories_status ON trajectories(status);
        CREATE INDEX IF NOT EXISTS idx_trajectories_skill ON trajectories(skill);
        CREATE INDEX IF NOT EXISTS idx_trajectories_created ON trajectories(created_at);

        CREATE TABLE IF NOT EXISTS trajectory_envelopes (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            parent_run_id TEXT NOT NULL DEFAULT '',
            timestamp TEXT NOT NULL,
            producer TEXT NOT NULL,
            objective TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            selected_agent TEXT NOT NULL DEFAULT '',
            selected_skills_json TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '',
            actions_json TEXT NOT NULL DEFAULT '[]',
            predicted_outcome TEXT NOT NULL DEFAULT '',
            observed_outcome TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            failure_class TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            memory_refs_json TEXT NOT NULL DEFAULT '[]',
            security_classification TEXT NOT NULL DEFAULT 'internal',
            duration_ms INTEGER,
            cost REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            redaction_count INTEGER NOT NULL DEFAULT 0,
            policy_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trajectory_envelopes_run ON trajectory_envelopes(run_id);
        CREATE INDEX IF NOT EXISTS idx_trajectory_envelopes_producer ON trajectory_envelopes(producer);
        CREATE INDEX IF NOT EXISTS idx_trajectory_envelopes_status ON trajectory_envelopes(status);
        CREATE INDEX IF NOT EXISTS idx_trajectory_envelopes_created ON trajectory_envelopes(created_at);
        """
    )
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for key in (
        "actions_json",
        "evidence_refs_json",
        "memory_refs_json",
        "metadata_json",
        "metrics_json",
        "policy_json",
        "selected_skills_json",
        "verifier_json",
    ):
        if key in out:
            try:
                out[key[:-5] if key.endswith("_json") else key] = json.loads(out.pop(key))
            except json.JSONDecodeError:
                out[key[:-5] if key.endswith("_json") else key] = {}
    return out


def add_node(conn: sqlite3.Connection, args: argparse.Namespace) -> str:
    node_type = args.type.upper()
    if node_type not in NODE_TYPES:
        raise SystemExit(f"unsupported node type: {args.type}")
    validation_state = args.validation_state.lower()
    if validation_state not in VALIDATION_STATES:
        raise SystemExit(f"unsupported validation state: {args.validation_state}")
    created_at = utc_now()
    security_classification = normalize_security_classification(args.security_classification)
    if security_classification == "CREDENTIAL" and node_type != "PROVENANCE":
        raise SystemExit("CREDENTIAL records may only be persisted as redacted PROVENANCE metadata")
    redacted_node, redactions = redact_json(
        {
            "title": args.title,
            "body": args.body,
            "source_uri": args.source_uri or "",
            "metadata": parse_json(args.metadata, "--metadata"),
        }
    )
    title = str(redacted_node["title"])
    body = str(redacted_node["body"])
    source_uri = str(redacted_node["source_uri"])
    metadata = as_dict(redacted_node["metadata"], "--metadata")
    if redactions:
        metadata["redaction_count"] = int(metadata.get("redaction_count", 0)) + redactions
    if args.supersedes:
        prior = conn.execute("SELECT security_classification FROM nodes WHERE id = ?", (args.supersedes,)).fetchone()
        if prior:
            prior_class = normalize_security_classification(prior["security_classification"])
            if not can_flow_security_classification(prior_class, security_classification):
                raise SystemExit(
                    f"security classification flow rejected: {prior_class} -> {security_classification}"
                )
    source_hash = args.source_hash or sha256_text("\n".join([title, body, source_uri]))
    node_id = args.id or stable_id("node", node_type, title, body, source_hash, created_at)
    conn.execute(
        """
        INSERT INTO nodes (
            id, type, title, body, source_uri, source_hash, run_id, agent, model,
            confidence, security_classification, validation_state, created_at,
            ttl_seconds, supersedes_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            node_type,
            title,
            body,
            source_uri,
            source_hash,
            args.run_id or "",
            args.agent or "",
            args.model or "",
            args.confidence,
            security_classification,
            validation_state,
            created_at,
            args.ttl_seconds,
            args.supersedes,
            json.dumps(metadata, sort_keys=True),
        ),
    )
    if args.supersedes:
        add_edge_values(
            conn,
            src_id=node_id,
            dst_id=args.supersedes,
            edge_type="SUPERSEDES",
            run_id=args.run_id or "",
            confidence=args.confidence,
            metadata={"reason": "append-first correction"},
        )
        conn.execute("UPDATE nodes SET deprecated_at = COALESCE(deprecated_at, ?) WHERE id = ?", (created_at, args.supersedes))
    conn.commit()
    return node_id


def add_edge_values(
    conn: sqlite3.Connection,
    *,
    src_id: str,
    dst_id: str,
    edge_type: str,
    run_id: str,
    confidence: float,
    metadata: dict[str, Any],
) -> str:
    edge_type = edge_type.upper()
    if edge_type not in EDGE_TYPES:
        raise SystemExit(f"unsupported edge type: {edge_type}")
    created_at = utc_now()
    edge_id = stable_id("edge", src_id, dst_id, edge_type, created_at)
    conn.execute(
        """
        INSERT INTO edges (id, src_id, dst_id, type, created_at, run_id, confidence, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (edge_id, src_id, dst_id, edge_type, created_at, run_id, confidence, json.dumps(metadata, sort_keys=True)),
    )
    return edge_id


def add_edge(conn: sqlite3.Connection, args: argparse.Namespace) -> str:
    edge_id = add_edge_values(
        conn,
        src_id=args.src,
        dst_id=args.dst,
        edge_type=args.type,
        run_id=args.run_id or "",
        confidence=args.confidence,
        metadata=parse_json(args.metadata, "--metadata"),
    )
    conn.commit()
    return edge_id


def redact_string(value: str) -> tuple[str, int]:
    redactions = 0
    out = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        out, count = pattern.subn("[REDACTED_SECRET]", out)
        redactions += count
    return out, redactions


def redact_json(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        redactions = 0
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                out[key] = "[REDACTED_SECRET]"
                redactions += 1
                continue
            out_item, item_redactions = redact_json(item)
            out[key] = out_item
            redactions += item_redactions
        return out, redactions
    if isinstance(value, list):
        items = []
        redactions = 0
        for item in value:
            out_item, item_redactions = redact_json(item)
            items.append(out_item)
            redactions += item_redactions
        return items, redactions
    if isinstance(value, str):
        return redact_string(value)
    return value, 0


def parse_json_file(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read --json-file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--json-file must contain valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("--json-file must contain a JSON object")
    return data


def as_list(value: Any, field: str) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    raise SystemExit(f"{field} must be a list or comma-separated string")


def as_dict(value: Any, field: str) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return parse_json(value, field)
    raise SystemExit(f"{field} must be a JSON object")


def normalize_trajectory_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    redacted, redaction_count = redact_json(raw)
    if not isinstance(redacted, dict):
        raise SystemExit("trajectory envelope must be a JSON object")

    timestamp = str(redacted.get("timestamp") or utc_now())
    producer = str(redacted.get("producer") or "").strip()
    objective = str(redacted.get("objective") or "").strip()
    status_value = str(redacted.get("status") or "").strip()
    metadata = as_dict(redacted.get("metadata"), "metadata")
    actions = as_list(redacted.get("actions"), "actions")
    evidence_refs = as_list(redacted.get("evidence_refs"), "evidence_refs")
    memory_refs = as_list(redacted.get("memory_refs"), "memory_refs")
    selected_skills = as_list(redacted.get("selected_skills"), "selected_skills")
    input_hash = str(redacted.get("input_hash") or sha256_text(json.dumps({
        "objective": objective,
        "actions": actions,
        "metadata": metadata,
    }, sort_keys=True)))
    trajectory_id = str(redacted.get("trajectory_id") or redacted.get("id") or stable_id(
        "trajenv", producer, objective, input_hash, timestamp
    ))
    run_id = str(redacted.get("run_id") or trajectory_id)
    security_classification = normalize_security_classification(str(redacted.get("security_classification") or "INTERNAL"))

    return {
        "trajectory_id": trajectory_id,
        "run_id": run_id,
        "parent_run_id": str(redacted.get("parent_run_id") or ""),
        "timestamp": timestamp,
        "producer": producer,
        "objective": objective,
        "input_hash": input_hash,
        "selected_agent": str(redacted.get("selected_agent") or redacted.get("agent") or ""),
        "selected_skills": selected_skills,
        "model": str(redacted.get("model") or ""),
        "actions": actions,
        "predicted_outcome": str(redacted.get("predicted_outcome") or redacted.get("prediction") or ""),
        "observed_outcome": str(redacted.get("observed_outcome") or redacted.get("observed") or ""),
        "status": status_value,
        "failure_class": str(redacted.get("failure_class") or ""),
        "evidence_refs": evidence_refs,
        "memory_refs": memory_refs,
        "security_classification": security_classification,
        "duration_ms": redacted.get("duration_ms"),
        "cost": redacted.get("cost"),
        "metadata": metadata,
        "redaction_count": redaction_count + int(redacted.get("redaction_count") or 0),
    }


def validate_trajectory_envelope(env: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    producer = env["producer"]
    status_value = env["status"]

    if producer not in TRAJECTORY_PRODUCERS:
        errors.append(f"unsupported producer: {producer or '<empty>'}")
    if not env["objective"]:
        errors.append("objective is required")
    if not status_value:
        errors.append("status is required")
    if env["security_classification"] not in SECURITY_CLASSES:
        errors.append(f"unsupported security classification: {env['security_classification']}")
    if env["security_classification"] == "CREDENTIAL":
        errors.append("CREDENTIAL trajectories are non-persistable; store redacted PROVENANCE metadata instead")
    if env["duration_ms"] is not None and not isinstance(env["duration_ms"], int):
        errors.append("duration_ms must be an integer when provided")
    if env["cost"] is not None and not isinstance(env["cost"], (int, float)):
        errors.append("cost must be numeric when provided")

    status_key = status_value.lower()
    metadata = env["metadata"]
    for key in ("source_security_classification", "input_security_classification", "max_input_security_classification"):
        if key not in metadata:
            continue
        source_class = normalize_security_classification(str(metadata[key]))
        if not can_flow_security_classification(source_class, env["security_classification"]):
            errors.append(
                f"security classification flow rejected: {source_class} -> {env['security_classification']}"
            )
    requires_evidence = (
        status_key in EVIDENCE_REQUIRED_STATUSES
        or bool(metadata.get("validation_claim"))
        or bool(metadata.get("promotion_claim"))
        or bool(metadata.get("safety_claim"))
    )
    if requires_evidence and not env["evidence_refs"]:
        errors.append(f"status {status_value} requires evidence_refs")

    if errors:
        return {"accepted": False, "errors": errors}
    return {"accepted": True, "errors": []}


def add_node_from_envelope(conn: sqlite3.Connection, env: dict[str, Any]) -> str:
    status_key = env["status"].lower()
    node_type = "FAILURE" if status_key in {"failed", "failure", "blocked", "error"} else "EXPERIENCE"
    title = f"{env['producer']}: {env['objective']} -> {env['status']}"
    body_parts = [
        f"selected_agent={env['selected_agent']}" if env["selected_agent"] else "",
        f"selected_skills={','.join(map(str, env['selected_skills']))}" if env["selected_skills"] else "",
        f"prediction={env['predicted_outcome']}" if env["predicted_outcome"] else "",
        f"observed={env['observed_outcome']}" if env["observed_outcome"] else "",
        f"failure_class={env['failure_class']}" if env["failure_class"] else "",
    ]
    node_args = argparse.Namespace(
        id=stable_id("node", node_type, env["trajectory_id"]),
        type=node_type,
        title=title,
        body="\n".join(part for part in body_parts if part) or env["objective"],
        source_uri=f"trajectory:{env['trajectory_id']}",
        source_hash=sha256_text(env["trajectory_id"]),
        run_id=env["run_id"],
        agent=env["selected_agent"] or env["producer"],
        model=env["model"],
        confidence=float(env["metadata"].get("confidence", 0.7)),
        security_classification=env["security_classification"],
        validation_state="observed",
        ttl_seconds=None,
        supersedes=None,
        metadata=json.dumps(
            {
                "trajectory_id": env["trajectory_id"],
                "producer": env["producer"],
                "evidence_refs": env["evidence_refs"],
                "redaction_count": env["redaction_count"],
            },
            sort_keys=True,
        ),
    )
    return add_node(conn, node_args)


def ingest_trajectory_envelope(conn: sqlite3.Connection, raw: dict[str, Any]) -> str:
    env = normalize_trajectory_envelope(raw)
    policy = validate_trajectory_envelope(env)
    if not policy["accepted"]:
        raise SystemExit("trajectory rejected by ingestion policy: " + "; ".join(policy["errors"]))

    conn.execute(
        """
        INSERT INTO trajectory_envelopes (
            id, run_id, parent_run_id, timestamp, producer, objective, input_hash,
            selected_agent, selected_skills_json, model, actions_json,
            predicted_outcome, observed_outcome, status, failure_class,
            evidence_refs_json, memory_refs_json, security_classification,
            duration_ms, cost, metadata_json, redaction_count, policy_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            env["trajectory_id"],
            env["run_id"],
            env["parent_run_id"],
            env["timestamp"],
            env["producer"],
            env["objective"],
            env["input_hash"],
            env["selected_agent"],
            json.dumps(env["selected_skills"], sort_keys=True),
            env["model"],
            json.dumps(env["actions"], sort_keys=True),
            env["predicted_outcome"],
            env["observed_outcome"],
            env["status"],
            env["failure_class"],
            json.dumps(env["evidence_refs"], sort_keys=True),
            json.dumps(env["memory_refs"], sort_keys=True),
            env["security_classification"],
            env["duration_ms"],
            env["cost"],
            json.dumps(env["metadata"], sort_keys=True),
            env["redaction_count"],
            json.dumps(policy, sort_keys=True),
            utc_now(),
        ),
    )
    add_node_from_envelope(conn, env)
    conn.commit()
    return env["trajectory_id"]


def record_trajectory(conn: sqlite3.Connection, args: argparse.Namespace) -> str:
    created_at = utc_now()
    metrics = parse_json(args.metrics, "--metrics")
    verifier = parse_json(args.verifier, "--verifier")
    input_hash = args.input_hash or sha256_text(args.input or "")
    trajectory_id = args.id or stable_id(
        "traj",
        args.objective,
        args.status,
        args.skill or "",
        args.proposal_id or "",
        input_hash,
        created_at,
    )
    conn.execute(
        """
        INSERT INTO trajectories (
            id, objective, status, skill, proposal_id, input_hash, prediction,
            observed, delta, metrics_json, verifier_json, run_id, agent, model, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trajectory_id,
            args.objective,
            args.status,
            args.skill or "",
            args.proposal_id or "",
            input_hash,
            args.prediction or "",
            args.observed or "",
            args.delta or "",
            json.dumps(metrics, sort_keys=True),
            json.dumps(verifier, sort_keys=True),
            args.run_id or "",
            args.agent or "",
            args.model or "",
            created_at,
        ),
    )
    evidence_refs = as_list(args.evidence_refs, "evidence_refs")
    metadata = {
        "confidence": args.confidence,
        "legacy_trajectory_id": trajectory_id,
        "metrics": metrics,
        "proposal_id": args.proposal_id or "",
        "skill": args.skill or "",
        "verifier": verifier,
    }
    ingest_trajectory_envelope(
        conn,
        {
            "trajectory_id": trajectory_id,
            "run_id": args.run_id or trajectory_id,
            "producer": args.producer or args.agent or "skill-evolver",
            "objective": args.objective,
            "input_hash": input_hash,
            "selected_agent": args.agent or "",
            "selected_skills": [args.skill] if args.skill else [],
            "model": args.model or "",
            "actions": [
                {
                    "type": "record-trajectory",
                    "skill": args.skill or "",
                    "proposal_id": args.proposal_id or "",
                }
            ],
            "predicted_outcome": args.prediction or "",
            "observed_outcome": args.observed or "",
            "status": args.status,
            "failure_class": args.delta or "",
            "evidence_refs": evidence_refs,
            "security_classification": args.security_classification,
            "metadata": metadata,
        },
    )
    conn.commit()
    return trajectory_id


def retrieve(conn: sqlite3.Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    terms = [term.lower() for term in args.query.split() if term.strip()]
    values: list[Any] = []
    where = ["deprecated_at IS NULL"]
    if not args.include_unsafe:
        where.append("validation_state NOT IN ('deprecated', 'disputed', 'untrusted')")
    if args.type:
        where.append("type = ?")
        values.append(args.type.upper())
    if terms:
        for term in terms:
            where.append("(LOWER(title) LIKE ? OR LOWER(body) LIKE ?)")
            like = f"%{term}%"
            values.extend([like, like])
    sql = f"""
        SELECT * FROM nodes
        WHERE {' AND '.join(where)}
        ORDER BY confidence DESC, created_at DESC
        LIMIT ?
    """
    values.append(args.limit)
    return [row_to_dict(row) for row in conn.execute(sql, values)]


def list_trajectory_envelopes(conn: sqlite3.Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    values: list[Any] = []
    where: list[str] = []
    if args.producer:
        where.append("producer = ?")
        values.append(args.producer)
    if args.status:
        where.append("status = ?")
        values.append(args.status)
    sql = "SELECT * FROM trajectory_envelopes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    values.append(args.limit)
    return [row_to_dict(row) for row in conn.execute(sql, values)]


def trajectory_is_failure(item: dict[str, Any]) -> bool:
    status = str(item.get("status", "")).lower()
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if status in SUCCESS_AND_RECOVERY_STATUSES:
        return False
    return (
        status in FAILURE_STATUSES
        or bool(metadata.get("critical_security_failure"))
        or bool(metadata.get("mandatory_anchor_failure"))
        or bool(metadata.get("governance_rejection"))
        or metadata.get("evidence_persisted") is False
        or bool(str(item.get("failure_class", "")).strip())
    )


def export_trajectory_envelopes(conn: sqlite3.Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = list_trajectory_envelopes(conn, args)
    if args.failures_only:
        rows = [row for row in rows if trajectory_is_failure(row)]
    return rows


def status(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    init_db(conn)
    counts = {
        "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "trajectories": conn.execute("SELECT COUNT(*) FROM trajectories").fetchone()[0],
        "trajectory_envelopes": conn.execute("SELECT COUNT(*) FROM trajectory_envelopes").fetchone()[0],
    }
    node_types = {
        row["type"]: row["count"]
        for row in conn.execute("SELECT type, COUNT(*) AS count FROM nodes GROUP BY type ORDER BY type")
    }
    return {"db": str(db_path), **counts, "node_types": node_types}


def dump_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Memory Fabric v1")
    parser.add_argument("--db", default=os.environ.get("HERMES_MEMORY_DB", ".hermes/memory/memory-fabric.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    node = sub.add_parser("add-node")
    node.add_argument("--id")
    node.add_argument("--type", required=True)
    node.add_argument("--title", required=True)
    node.add_argument("--body", required=True)
    node.add_argument("--source-uri", default="")
    node.add_argument("--source-hash", default="")
    node.add_argument("--run-id", default="")
    node.add_argument("--agent", default="")
    node.add_argument("--model", default="")
    node.add_argument("--confidence", type=float, default=0.5)
    node.add_argument("--security-classification", default="internal")
    node.add_argument("--validation-state", default="observed")
    node.add_argument("--ttl-seconds", type=int)
    node.add_argument("--supersedes")
    node.add_argument("--metadata", default="{}")

    edge = sub.add_parser("add-edge")
    edge.add_argument("--src", required=True)
    edge.add_argument("--dst", required=True)
    edge.add_argument("--type", required=True)
    edge.add_argument("--run-id", default="")
    edge.add_argument("--confidence", type=float, default=0.5)
    edge.add_argument("--metadata", default="{}")

    traj = sub.add_parser("record-trajectory")
    traj.add_argument("--id")
    traj.add_argument("--objective", required=True)
    traj.add_argument("--status", required=True)
    traj.add_argument("--skill", default="")
    traj.add_argument("--proposal-id", default="")
    traj.add_argument("--input", default="")
    traj.add_argument("--input-hash", default="")
    traj.add_argument("--prediction", default="")
    traj.add_argument("--observed", default="")
    traj.add_argument("--delta", default="")
    traj.add_argument("--metrics", default="{}")
    traj.add_argument("--verifier", default="{}")
    traj.add_argument("--run-id", default="")
    traj.add_argument("--agent", default="")
    traj.add_argument("--model", default="")
    traj.add_argument("--producer", default="")
    traj.add_argument("--evidence-refs", default="[]")
    traj.add_argument("--confidence", type=float, default=0.5)
    traj.add_argument("--security-classification", default="internal")

    ingest = sub.add_parser("ingest-trajectory")
    ingest.add_argument("--json", default="", help="Trajectory envelope JSON object")
    ingest.add_argument("--json-file", default="", help="Path to trajectory envelope JSON object")

    list_traj = sub.add_parser("list-trajectories")
    list_traj.add_argument("--producer", default="")
    list_traj.add_argument("--status", default="")
    list_traj.add_argument("--limit", type=int, default=20)

    export_traj = sub.add_parser("export-trajectories")
    export_traj.add_argument("--producer", default="")
    export_traj.add_argument("--status", default="")
    export_traj.add_argument("--limit", type=int, default=1000)
    export_traj.add_argument("--failures-only", action="store_true")
    export_traj.add_argument("--jsonl", action="store_true")

    ret = sub.add_parser("retrieve")
    ret.add_argument("query")
    ret.add_argument("--type")
    ret.add_argument("--limit", type=int, default=10)
    ret.add_argument("--include-unsafe", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    db_path = Path(args.db)
    conn = connect(db_path)
    init_db(conn)

    if args.command == "init":
        print(f"initialized={db_path}")
    elif args.command == "status":
        dump_json(status(conn, db_path))
    elif args.command == "add-node":
        print(f"node={add_node(conn, args)}")
    elif args.command == "add-edge":
        print(f"edge={add_edge(conn, args)}")
    elif args.command == "record-trajectory":
        print(f"trajectory={record_trajectory(conn, args)}")
    elif args.command == "ingest-trajectory":
        if bool(args.json) == bool(args.json_file):
            raise SystemExit("provide exactly one of --json or --json-file")
        raw = parse_json_file(args.json_file) if args.json_file else parse_json(args.json, "--json")
        print(f"trajectory={ingest_trajectory_envelope(conn, raw)}")
    elif args.command == "list-trajectories":
        dump_json(list_trajectory_envelopes(conn, args))
    elif args.command == "export-trajectories":
        rows = export_trajectory_envelopes(conn, args)
        if args.jsonl:
            for row in rows:
                print(json.dumps(row, sort_keys=True))
        else:
            dump_json(rows)
    elif args.command == "retrieve":
        dump_json(retrieve(conn, args))
    else:
        parser.error(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
