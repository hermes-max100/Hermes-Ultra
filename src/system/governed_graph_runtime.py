#!/usr/bin/env python3
"""Governed DAG runtime for Hermes.

Deterministic authority chain:
plan -> fake-edge/contract validation -> resource governor -> trust gate ->
bounded scheduler -> schema/provenance/trust/evidence/policy verification ->
deterministic fan-in -> checkpoint + telemetry.

Workers only produce candidate outputs. They cannot self-certify trust or
lineage. Standard-library-only by design.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from execution_state import DurableTaskStateStore, ExecutionStateLedger, StateError

Handler = Callable[["NodeContext"], Any]
PolicyVerifier = Callable[["PolicyContext"], Any]
ALLOWED_EDGE_KINDS = {"data", "authority", "order"}
NODE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

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
    "PUBLIC": {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "INTERNAL": {"INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "CONFIDENTIAL": {"CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"},
    "LEGAL_PRIVILEGED": {"LEGAL_PRIVILEGED"},
    "FINANCIAL": {"FINANCIAL"},
    "SECURITY_SENSITIVE": {"SECURITY_SENSITIVE", "CREDENTIAL"},
    "CREDENTIAL": {"CREDENTIAL"},
}


class GraphValidationError(ValueError):
    """The graph or resource policy is invalid and must not execute."""


class VerificationFailure(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class NodeSpec:
    id: str
    handler: str
    provider: str = "local"
    input_schema: Mapping[str, Any] = field(default_factory=lambda: {"type": "object"})
    output_schema: Mapping[str, Any] = field(default_factory=lambda: {"type": "object"})
    security_classification: str = "INTERNAL"
    estimated_latency_ms: float = 100.0
    estimated_cost: float = 0.0
    estimated_tokens: int = 0
    require_evidence: bool = False
    max_retries: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NodeSpec":
        if not isinstance(raw, Mapping):
            raise GraphValidationError("node must be a JSON object")
        node_id = str(raw.get("id", "")).strip()
        if not node_id or not NODE_ID_RE.match(node_id):
            raise GraphValidationError(f"invalid node id: {node_id!r}")
        handler = str(raw.get("handler", node_id)).strip()
        if not handler:
            raise GraphValidationError(f"node {node_id}: handler must not be empty")
        provider = str(raw.get("provider", "local")).strip() or "local"
        input_schema = raw.get("input_schema", {"type": "object"})
        output_schema = raw.get("output_schema", {"type": "object"})
        if not isinstance(input_schema, Mapping) or not isinstance(output_schema, Mapping):
            raise GraphValidationError(f"node {node_id}: input_schema/output_schema must be objects")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise GraphValidationError(f"node {node_id}: metadata must be an object")
        if "execution_state_reusable" in metadata and not isinstance(metadata["execution_state_reusable"], bool):
            raise GraphValidationError(f"node {node_id}: execution_state_reusable must be boolean")
        return cls(
            id=node_id,
            handler=handler,
            provider=provider,
            input_schema=dict(input_schema),
            output_schema=dict(output_schema),
            security_classification=normalize_class(raw.get("security_classification", "INTERNAL")),
            estimated_latency_ms=_nonnegative_float(raw.get("estimated_latency_ms", 100), f"node {node_id}.estimated_latency_ms"),
            estimated_cost=_nonnegative_float(raw.get("estimated_cost", 0), f"node {node_id}.estimated_cost"),
            estimated_tokens=_nonnegative_int(raw.get("estimated_tokens", 0), f"node {node_id}.estimated_tokens"),
            require_evidence=bool(raw.get("require_evidence", False)),
            max_retries=_nonnegative_int(raw.get("max_retries", 0), f"node {node_id}.max_retries"),
            metadata=dict(metadata),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "handler": self.handler,
            "provider": self.provider,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "security_classification": self.security_classification,
            "estimated_latency_ms": self.estimated_latency_ms,
            "estimated_cost": self.estimated_cost,
            "estimated_tokens": self.estimated_tokens,
            "require_evidence": self.require_evidence,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class EdgeContract:
    id: str
    source: str
    target: str
    kind: str = "data"
    bindings: Mapping[str, str] = field(default_factory=dict)
    required: bool = True

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EdgeContract":
        if not isinstance(raw, Mapping):
            raise GraphValidationError("edge must be a JSON object")
        edge_id = str(raw.get("id", "")).strip()
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        kind = str(raw.get("kind", "data")).strip().lower()
        if not edge_id or not NODE_ID_RE.match(edge_id):
            raise GraphValidationError(f"invalid edge id: {edge_id!r}")
        if not source or not target:
            raise GraphValidationError(f"edge {edge_id}: source and target are required")
        if kind not in ALLOWED_EDGE_KINDS:
            raise GraphValidationError(f"edge {edge_id}: unsupported kind {kind!r}")
        bindings = raw.get("bindings", {})
        if not isinstance(bindings, Mapping):
            raise GraphValidationError(f"edge {edge_id}: bindings must be an object")
        normalized: dict[str, str] = {}
        for target_path, source_path in bindings.items():
            target_key = str(target_path).strip()
            source_key = str(source_path).strip()
            if not target_key or not source_key.startswith("$"):
                raise GraphValidationError(f"edge {edge_id}: bindings must map a target field to a '$' JSON path")
            normalized[target_key] = source_key
        required = bool(raw.get("required", True))
        if kind == "authority" and not required:
            raise GraphValidationError(f"edge {edge_id}: authority edges must be required")
        return cls(edge_id, source, target, kind, normalized, required)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "bindings": dict(sorted(self.bindings.items())),
            "required": self.required,
        }


@dataclass(frozen=True)
class GraphPlan:
    version: str
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeContract, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GraphPlan":
        if not isinstance(raw, Mapping):
            raise GraphValidationError("graph plan must be a JSON object")
        version = str(raw.get("version", "")).strip()
        if not version:
            raise GraphValidationError("graph plan version is required")
        raw_nodes = raw.get("nodes", [])
        raw_edges = raw.get("edges", [])
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise GraphValidationError("graph plan nodes must be a non-empty array")
        if not isinstance(raw_edges, list):
            raise GraphValidationError("graph plan edges must be an array")
        nodes = tuple(sorted((NodeSpec.from_dict(item) for item in raw_nodes), key=lambda item: item.id))
        edges = tuple(sorted((EdgeContract.from_dict(item) for item in raw_edges), key=lambda item: item.id))
        if len({n.id for n in nodes}) != len(nodes):
            raise GraphValidationError("graph plan contains duplicate node ids")
        if len({e.id for e in edges}) != len(edges):
            raise GraphValidationError("graph plan contains duplicate edge ids")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise GraphValidationError("graph plan metadata must be an object")
        return cls(version, nodes, edges, dict(metadata))

    @classmethod
    def from_json_file(cls, path: Path | str) -> "GraphPlan":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": [n.canonical_dict() for n in sorted(self.nodes, key=lambda item: item.id)],
            "edges": [e.canonical_dict() for e in sorted(self.edges, key=lambda item: item.id)],
            "metadata": self.metadata,
        }

    @property
    def graph_hash(self) -> str:
        return "sha256:" + sha256_json(self.canonical_dict())

    def node_map(self) -> dict[str, NodeSpec]:
        return {node.id: node for node in self.nodes}


@dataclass(frozen=True)
class OptimizedPlan:
    plan: GraphPlan
    original_graph_hash: str
    effective_graph_hash: str
    pruned_edge_ids: tuple[str, ...]
    layers: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class NodeOutput:
    data: Any
    evidence: tuple[str, ...] = ()
    classification: str | None = None
    cost: float = 0.0
    tokens: int = 0
    external_provenance: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class VerifiedNodeOutput:
    data: Any
    evidence: tuple[str, ...]
    classification: str
    cost: float
    tokens: int
    external_provenance: tuple[Mapping[str, Any], ...]
    dependency_provenance: tuple[Mapping[str, Any], ...]
    output_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "evidence": list(self.evidence),
            "classification": self.classification,
            "cost": self.cost,
            "tokens": self.tokens,
            "external_provenance": [dict(x) for x in self.external_provenance],
            "dependency_provenance": [dict(x) for x in self.dependency_provenance],
            "output_hash": self.output_hash,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "VerifiedNodeOutput":
        return cls(
            data=raw.get("data"),
            evidence=tuple(str(x) for x in raw.get("evidence", [])),
            classification=normalize_class(raw.get("classification", "INTERNAL")),
            cost=_nonnegative_float(raw.get("cost", 0), "checkpoint.output.cost"),
            tokens=_nonnegative_int(raw.get("tokens", 0), "checkpoint.output.tokens"),
            external_provenance=tuple(dict(x) for x in raw.get("external_provenance", [])),
            dependency_provenance=tuple(dict(x) for x in raw.get("dependency_provenance", [])),
            output_hash=str(raw.get("output_hash", "")),
        )


@dataclass(frozen=True)
class NodeContext:
    node: NodeSpec
    inputs: Mapping[str, Any]
    dependencies: Mapping[str, VerifiedNodeOutput]
    dependency_status: Mapping[str, str]
    graph_hash: str
    attempt: int
    continuation_state: Mapping[str, Any] = field(default_factory=dict)
    execution_state: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyContext:
    node: NodeSpec
    inputs: Mapping[str, Any]
    dependencies: Mapping[str, VerifiedNodeOutput]
    dependency_status: Mapping[str, str]
    output: VerifiedNodeOutput
    graph_hash: str


@dataclass
class NodeExecutionRecord:
    node_id: str
    provider: str
    status: str = "pending"
    output: VerifiedNodeOutput | None = None
    error: str | None = None
    attempts: int = 0
    retries: int = 0
    duration_ms: float = 0.0
    blocked_wait_ms: float = 0.0
    checkpoint_hit: bool = False
    execution_state_hit: bool = False
    blocked_by: tuple[str, ...] = ()
    input_hash: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    _finished_monotonic: float | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "provider": self.provider,
            "status": self.status,
            "output": self.output.to_dict() if self.output else None,
            "error": self.error,
            "attempts": self.attempts,
            "retries": self.retries,
            "duration_ms": round(self.duration_ms, 3),
            "blocked_wait_ms": round(self.blocked_wait_ms, 3),
            "checkpoint_hit": self.checkpoint_hit,
            "execution_state_hit": self.execution_state_hit,
            "blocked_by": list(self.blocked_by),
            "input_hash": self.input_hash,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class RuntimeTelemetry:
    original_graph_hash: str
    graph_hash: str
    pruned_edge_ids: tuple[str, ...]
    started_at: str
    finished_at: str | None = None
    duration_ms: float = 0.0
    max_parallelism: int = 0
    retries: int = 0
    rejected_count: int = 0
    checkpoint_hits: int = 0
    execution_state_hits: int = 0
    verifier_failures: dict[str, int] = field(default_factory=dict)
    critical_path_ms: float = 0.0
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    estimated_tokens: int = 0
    actual_tokens: int = 0
    node_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_graph_hash": self.original_graph_hash,
            "graph_hash": self.graph_hash,
            "pruned_edge_ids": list(self.pruned_edge_ids),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "max_parallelism": self.max_parallelism,
            "retries": self.retries,
            "rejected_count": self.rejected_count,
            "checkpoint_hits": self.checkpoint_hits,
            "execution_state_hits": self.execution_state_hits,
            "verifier_failures": dict(sorted(self.verifier_failures.items())),
            "critical_path_ms": round(self.critical_path_ms, 3),
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "estimated_tokens": self.estimated_tokens,
            "actual_tokens": self.actual_tokens,
            "node_metrics": self.node_metrics,
        }


@dataclass
class RunReport:
    status: str
    nodes: dict[str, NodeExecutionRecord]
    telemetry: RuntimeTelemetry

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "nodes": {k: self.nodes[k].to_dict() for k in sorted(self.nodes)},
            "telemetry": self.telemetry.to_dict(),
        }


@dataclass(frozen=True)
class ResourceGovernor:
    max_concurrency: int = 4
    provider_limits: Mapping[str, int] = field(default_factory=dict)
    parallel_value_threshold_ms: float = 0.0
    coordination_overhead_ms: float = 0.0
    verification_overhead_ms: float = 0.0
    max_total_estimated_cost: float | None = None
    max_total_estimated_tokens: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.max_concurrency, bool) or not isinstance(self.max_concurrency, int) or self.max_concurrency <= 0:
            raise GraphValidationError("resource governor max_concurrency must be an integer > 0")
        for provider, limit in self.provider_limits.items():
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise GraphValidationError(f"provider limit for {provider!r} must be an integer > 0")
        if self.parallel_value_threshold_ms < 0:
            raise GraphValidationError("parallel_value_threshold_ms must be >= 0")
        if self.coordination_overhead_ms < 0 or self.verification_overhead_ms < 0:
            raise GraphValidationError("parallelism overhead values must be >= 0")
        if self.max_total_estimated_cost is not None and self.max_total_estimated_cost < 0:
            raise GraphValidationError("max_total_estimated_cost must be >= 0")
        if self.max_total_estimated_tokens is not None and self.max_total_estimated_tokens < 0:
            raise GraphValidationError("max_total_estimated_tokens must be >= 0")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResourceGovernor":
        limits = raw.get("provider_limits", {})
        if not isinstance(limits, Mapping):
            raise GraphValidationError("resource policy provider_limits must be an object")
        return cls(
            max_concurrency=_positive_int(raw.get("max_concurrency", 4), "resource policy max_concurrency"),
            provider_limits={str(k): _positive_int(v, f"provider limit {k}") for k, v in limits.items()},
            parallel_value_threshold_ms=float(raw.get("parallel_value_threshold_ms", 0.0)),
            coordination_overhead_ms=float(raw.get("coordination_overhead_ms", 0.0)),
            verification_overhead_ms=float(raw.get("verification_overhead_ms", 0.0)),
            max_total_estimated_cost=None if raw.get("max_total_estimated_cost") is None else float(raw["max_total_estimated_cost"]),
            max_total_estimated_tokens=None if raw.get("max_total_estimated_tokens") is None else _nonnegative_int(raw["max_total_estimated_tokens"], "max_total_estimated_tokens"),
        )

    @classmethod
    def from_json_file(cls, path: Path | str) -> "ResourceGovernor":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise GraphValidationError("resource policy must be a JSON object")
        return cls.from_dict(raw)

    def validate_budget(self, plan: GraphPlan) -> None:
        cost = sum(n.estimated_cost for n in plan.nodes)
        tokens = sum(n.estimated_tokens for n in plan.nodes)
        if self.max_total_estimated_cost is not None and cost > self.max_total_estimated_cost:
            raise GraphValidationError(f"graph estimated cost {cost:.6f} exceeds ceiling {self.max_total_estimated_cost:.6f}")
        if self.max_total_estimated_tokens is not None and tokens > self.max_total_estimated_tokens:
            raise GraphValidationError(f"graph estimated tokens {tokens} exceeds ceiling {self.max_total_estimated_tokens}")

    def should_parallelize(self, nodes: Sequence[NodeSpec]) -> bool:
        if len(nodes) <= 1 or self.max_concurrency <= 1:
            return False
        latencies = [max(0.0, n.estimated_latency_ms) for n in nodes]
        savings = sum(latencies) - max(latencies, default=0.0)
        overhead = (len(nodes) - 1) * (self.coordination_overhead_ms + self.verification_overhead_ms)
        return savings - overhead >= self.parallel_value_threshold_ms


class FileCheckpointStore:
    """Atomic, graph-hash and input-hash scoped successful-node checkpoints."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, graph_hash: str, node_id: str) -> Path:
        return self.root / graph_hash.replace(":", "-") / f"{node_id}.json"

    def load(self, graph_hash: str, node_id: str, input_hash: str) -> VerifiedNodeOutput | None:
        path = self._path(graph_hash, node_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                return None
            if raw.get("graph_hash") != graph_hash or raw.get("node_id") != node_id or raw.get("input_hash") != input_hash:
                return None
            output = raw.get("output")
            if not isinstance(output, Mapping):
                return None
            verified = VerifiedNodeOutput.from_dict(output)
            if not verified.output_hash or verified.output_hash != _verified_output_hash(verified):
                return None
            return verified
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save(self, graph_hash: str, node_id: str, input_hash: str, output: VerifiedNodeOutput) -> None:
        path = self._path(graph_hash, node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"graph_hash": graph_hash, "node_id": node_id, "input_hash": input_hash, "output": output.to_dict()}
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)


@dataclass
class _RunState:
    graph_started_monotonic: float
    active: int = 0
    max_active: int = 0
    active_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    telemetry_failures: Counter[str] = field(default_factory=Counter)
    retries: int = 0
    checkpoint_hits: int = 0
    execution_state_hits: int = 0


class GovernedGraphRuntime:
    def __init__(
        self,
        resource_governor: ResourceGovernor | None = None,
        *,
        checkpoint_store: FileCheckpointStore | None = None,
        policy_verifier: PolicyVerifier | None = None,
        execution_state_ledger: ExecutionStateLedger | None = None,
        task_state_store: DurableTaskStateStore | None = None,
    ):
        self.resource_governor = resource_governor or ResourceGovernor()
        self.checkpoint_store = checkpoint_store
        self.policy_verifier = policy_verifier
        self.execution_state_ledger = execution_state_ledger or ExecutionStateLedger()
        self.task_state_store = task_state_store or DurableTaskStateStore(os.environ.get("HERMES_TASK_STATE_DIR", ".hermes/state/tasks"))

    async def run(self, plan: GraphPlan, handlers: Mapping[str, Handler]) -> RunReport:
        optimized = optimize_plan(plan)
        self.resource_governor.validate_budget(optimized.plan)
        effective = optimized.plan
        task_contract = self._prepare_task_contract(effective)
        node_map = effective.node_map()
        incoming = _incoming_edges(effective)
        records = {n.id: NodeExecutionRecord(n.id, n.provider) for n in effective.nodes}
        start_mono = time.monotonic()
        started_at = utc_now()
        state = _RunState(start_mono)
        global_sem = asyncio.Semaphore(self.resource_governor.max_concurrency)
        provider_sems = {p: asyncio.Semaphore(limit) for p, limit in self.resource_governor.provider_limits.items()}

        pending = set(node_map)
        while pending:
            progressed = False
            for node_id in sorted(tuple(pending)):
                required = [e.source for e in incoming[node_id] if e.required]
                bad = sorted(pred for pred in required if records[pred].status in {"failed", "rejected", "blocked"})
                if bad:
                    rec = records[node_id]
                    rec.status = "blocked"
                    rec.blocked_by = tuple(bad)
                    rec.error = "required dependency not accepted: " + ", ".join(bad)
                    rec.finished_at = utc_now()
                    rec._finished_monotonic = time.monotonic()
                    pending.remove(node_id)
                    progressed = True

            ready: list[str] = []
            for node_id in sorted(pending):
                predecessors = [e.source for e in incoming[node_id]]
                if all(records[p].status in {"success", "failed", "rejected", "blocked"} for p in predecessors):
                    ready.append(node_id)
            if ready:
                specs = [node_map[x] for x in ready]
                batch = ready if self.resource_governor.should_parallelize(specs) else ready[:1]
                await asyncio.gather(*[
                    asyncio.create_task(self._execute_node(node_map[x], incoming[x], records, handlers, optimized.effective_graph_hash, state, global_sem, provider_sems, task_contract))
                    for x in batch
                ])
                for node_id in batch:
                    pending.discard(node_id)
                progressed = True
            if not progressed:
                raise RuntimeError("graph scheduler made no progress; unresolved nodes: " + ", ".join(sorted(pending)))

        duration_ms = (time.monotonic() - start_mono) * 1000.0
        rejected = sum(1 for r in records.values() if r.status == "rejected")
        telemetry = RuntimeTelemetry(
            original_graph_hash=optimized.original_graph_hash,
            graph_hash=optimized.effective_graph_hash,
            pruned_edge_ids=optimized.pruned_edge_ids,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=duration_ms,
            max_parallelism=state.max_active,
            retries=state.retries,
            rejected_count=rejected,
            checkpoint_hits=state.checkpoint_hits,
            execution_state_hits=state.execution_state_hits,
            verifier_failures=dict(state.telemetry_failures),
            critical_path_ms=_critical_path_ms(effective, records),
            estimated_cost=sum(n.estimated_cost for n in effective.nodes),
            actual_cost=sum(r.output.cost for r in records.values() if r.output),
            estimated_tokens=sum(n.estimated_tokens for n in effective.nodes),
            actual_tokens=sum(r.output.tokens for r in records.values() if r.output),
            node_metrics={k: records[k].to_dict() for k in sorted(records)},
        )
        non_success = [r for r in records.values() if r.status != "success"]
        outgoing_sources = {e.source for e in effective.edges}
        sinks = sorted(n.id for n in effective.nodes if n.id not in outgoing_sources)
        sinks_accepted = all(records[x].status == "success" for x in sinks)
        if not non_success:
            status = "success"
        elif sinks_accepted:
            status = "degraded"
        else:
            status = "failed"
        return RunReport(status, records, telemetry)

    def _prepare_task_contract(self, plan: GraphPlan) -> Mapping[str, Any] | None:
        raw = plan.metadata.get("long_horizon")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise GraphValidationError("graph metadata.long_horizon must be an object")
        task_id = str(raw.get("task_id", "")).strip()
        objective = str(raw.get("objective", "")).strip()
        requirements = raw.get("requirements", [])
        if not task_id or not objective or not isinstance(requirements, list) or not requirements:
            raise GraphValidationError("long_horizon requires task_id, objective, and requirements")
        normalized: list[dict[str, str]] = []
        requirement_ids: set[str] = set()
        for item in requirements:
            if not isinstance(item, Mapping):
                raise GraphValidationError("long_horizon requirements must be objects")
            rid = str(item.get("id", "")).strip()
            text = str(item.get("text", "")).strip()
            if not rid or not text or rid in requirement_ids:
                raise GraphValidationError("long_horizon requirements need unique ids and text")
            requirement_ids.add(rid)
            normalized.append({"id": rid, "text": text})
        for node in plan.nodes:
            rid = str(node.metadata.get("completes_requirement", "")).strip()
            if rid:
                if rid not in requirement_ids:
                    raise GraphValidationError(f"node {node.id}: unknown completes_requirement {rid}")
                if not node.require_evidence:
                    raise GraphValidationError(f"node {node.id}: durable progress requires require_evidence=true")
                fields = node.metadata.get("environment_fields", [])
                if not isinstance(fields, list) or any(not isinstance(x, str) or not x for x in fields):
                    raise GraphValidationError(f"node {node.id}: environment_fields must be a string list")
        contract = {"task_id": task_id, "objective": objective, "requirements": normalized}
        if self.task_state_store is not None:
            try:
                self.task_state_store.ensure_initialized(task_id, objective, normalized)
            except StateError as exc:
                raise GraphValidationError(f"durable task state rejected: {exc}") from exc
        return contract

    def _continuation_state(self, task_contract: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if self.task_state_store is None or task_contract is None:
            return {}
        try:
            return self.task_state_store.fresh_context(str(task_contract["task_id"]))
        except StateError as exc:
            raise VerificationFailure("progress", f"cannot build fresh continuation state: {exc}") from exc

    def _record_execution_success(
        self, node: NodeSpec, graph_hash: str, input_hash: str, dependencies: Mapping[str, VerifiedNodeOutput], verified: VerifiedNodeOutput
    ) -> None:
        if self.execution_state_ledger is None:
            return
        resource = f"graph-node-output:{node.id}"
        self.execution_state_ledger.record_mutation(resource, verified.output_hash, source="governed-graph")
        requires = tuple(f"graph-node-output:{d}" for d in sorted(dependencies))
        self.execution_state_ledger.record_attempt(
            f"graph-node:{node.id}", {"graph_hash": graph_hash, "input_hash": input_hash}, status="success",
            result=verified.to_dict(), requires=requires, evidence=verified.evidence,
        )

    def _record_execution_failure(
        self, node: NodeSpec, graph_hash: str, input_hash: str, dependencies: Mapping[str, VerifiedNodeOutput], status: str, error: str
    ) -> None:
        if self.execution_state_ledger is None:
            return
        requires = tuple(f"graph-node-output:{d}" for d in sorted(dependencies))
        self.execution_state_ledger.record_attempt(
            f"graph-node:{node.id}", {"graph_hash": graph_hash, "input_hash": input_hash}, status=status,
            result={"error": error}, requires=requires,
        )

    def _admit_verified_progress(self, node: NodeSpec, verified: VerifiedNodeOutput, task_contract: Mapping[str, Any] | None) -> None:
        rid = str(node.metadata.get("completes_requirement", "")).strip()
        if not rid or self.task_state_store is None or task_contract is None:
            return
        if not verified.evidence:
            raise VerificationFailure("progress", f"node {node.id}: durable progress lacks evidence")
        env: dict[str, Any] = {}
        fields = node.metadata.get("environment_fields", [])
        if fields:
            if not isinstance(verified.data, Mapping):
                raise VerificationFailure("progress", f"node {node.id}: environment_fields require object output")
            for key in fields:
                if key not in verified.data:
                    raise VerificationFailure("progress", f"node {node.id}: environment field {key!r} missing from verified output")
                env[key] = verified.data[key]
        try:
            self.task_state_store.admit_verified(
                str(task_contract["task_id"]), requirement_id=rid, output_hash=verified.output_hash, evidence=verified.evidence,
                environment_state=env, next_subtask=node.metadata.get("next_subtask"),
            )
        except StateError as exc:
            raise VerificationFailure("progress", f"durable progress admission failed: {exc}") from exc

    def _record_failed_progress(self, node: NodeSpec, task_contract: Mapping[str, Any] | None, reason: str) -> None:
        rid = str(node.metadata.get("completes_requirement", "")).strip()
        if not rid or self.task_state_store is None or task_contract is None:
            return
        try:
            self.task_state_store.record_rejected_attempt(str(task_contract["task_id"]), rid, reason)
        except StateError:
            pass

    async def _execute_node(
        self,
        node: NodeSpec,
        incoming_edges: Sequence[EdgeContract],
        records: Mapping[str, NodeExecutionRecord],
        handlers: Mapping[str, Handler],
        graph_hash: str,
        state: _RunState,
        global_sem: asyncio.Semaphore,
        provider_sems: Mapping[str, asyncio.Semaphore],
        task_contract: Mapping[str, Any] | None,
    ) -> None:
        rec = records[node.id]
        rec.started_at = utc_now()
        node_start = time.monotonic()
        dependency_ids = sorted({e.source for e in incoming_edges if records[e.source].status == "success"})
        dependencies = {d: records[d].output for d in dependency_ids if records[d].output is not None}
        dependency_status = {d: records[d].status for d in sorted({e.source for e in incoming_edges})}
        latest_finish = max([records[e.source]._finished_monotonic or state.graph_started_monotonic for e in incoming_edges] or [state.graph_started_monotonic])
        rec.blocked_wait_ms = max(0.0, (node_start - latest_finish) * 1000.0)

        try:
            self._verify_dependency_trust(node, dependencies)
            inputs = _build_inputs(node, incoming_edges, records)
            validate_json_schema(inputs, node.input_schema, path=f"node {node.id} input")
            input_hash = "sha256:" + sha256_json({
                "inputs": inputs,
                "dependency_hashes": {d: dependencies[d].output_hash for d in sorted(dependencies)},
            })
            rec.input_hash = input_hash
        except VerificationFailure as exc:
            self._reject(rec, exc, state, node_start)
            return
        except (GraphValidationError, ValueError, TypeError) as exc:
            self._reject(rec, VerificationFailure("schema", str(exc)), state, node_start)
            return

        if self.checkpoint_store is not None:
            cached = self.checkpoint_store.load(graph_hash, node.id, input_hash)
            if cached is not None:
                try:
                    cached = await self._verify_output(node, inputs, dependencies, dependency_status, cached, graph_hash, already_verified=True)
                    self._admit_verified_progress(node, cached, task_contract)
                except VerificationFailure:
                    cached = None
                if cached is not None:
                    rec.status = "success"
                    rec.output = cached
                    rec.checkpoint_hit = True
                    state.checkpoint_hits += 1
                    self._record_execution_success(node, graph_hash, input_hash, dependencies, cached)
                    self._finish_record(rec, node_start)
                    return

        if self.execution_state_ledger is not None and bool(node.metadata.get("execution_state_reusable", False)):
            requires = tuple(f"graph-node-output:{d}" for d in sorted(dependencies))
            decision = self.execution_state_ledger.preflight(
                f"graph-node:{node.id}", {"graph_hash": graph_hash, "input_hash": input_hash}, requires=requires
            )
            if decision.action == "reuse_success" and isinstance(decision.result, Mapping):
                try:
                    reused = VerifiedNodeOutput.from_dict(decision.result)
                    reused = await self._verify_output(node, inputs, dependencies, dependency_status, reused, graph_hash, already_verified=True)
                    self._admit_verified_progress(node, reused, task_contract)
                    rec.status = "success"
                    rec.output = reused
                    rec.execution_state_hit = True
                    state.execution_state_hits += 1
                    self._record_execution_success(node, graph_hash, input_hash, dependencies, reused)
                    self._finish_record(rec, node_start)
                    return
                except (VerificationFailure, ValueError, TypeError):
                    pass

        handler = handlers.get(node.handler)
        if handler is None:
            rec.status = "failed"
            rec.error = f"handler not registered: {node.handler}"
            self._record_execution_failure(node, graph_hash, input_hash, dependencies, "failed", rec.error)
            self._record_failed_progress(node, task_contract, rec.error)
            self._finish_record(rec, node_start)
            return

        last_exception: Exception | None = None
        for attempt in range(1, node.max_retries + 2):
            rec.attempts = attempt
            try:
                continuation = self._continuation_state(task_contract)
                execution = self.execution_state_ledger.compact_snapshot() if self.execution_state_ledger is not None else {}
                ctx = NodeContext(
                    node, inputs, {k: dependencies[k] for k in sorted(dependencies)}, dependency_status, graph_hash, attempt, continuation, execution
                )
                raw = await self._call_handler(handler, ctx, node.provider, state, global_sem, provider_sems)
                candidate = _coerce_node_output(raw, node.security_classification)
                verified = await self._verify_output(node, inputs, dependencies, dependency_status, candidate, graph_hash)
                self._admit_verified_progress(node, verified, task_contract)
                rec.status = "success"
                rec.output = verified
                self._record_execution_success(node, graph_hash, input_hash, dependencies, verified)
                if self.checkpoint_store is not None:
                    self.checkpoint_store.save(graph_hash, node.id, input_hash, verified)
                self._finish_record(rec, node_start)
                return
            except VerificationFailure as exc:
                self._record_execution_failure(node, graph_hash, input_hash, dependencies, "rejected", f"{exc.stage}: {exc.message}")
                self._record_failed_progress(node, task_contract, f"{exc.stage}: {exc.message}")
                self._reject(rec, exc, state, node_start)
                return
            except Exception as exc:
                last_exception = exc
                if attempt <= node.max_retries:
                    rec.retries += 1
                    state.retries += 1
                    continue
                break
        rec.status = "failed"
        rec.error = f"handler failed after {rec.attempts} attempt(s): {type(last_exception).__name__}: {last_exception}"
        self._record_execution_failure(node, graph_hash, input_hash, dependencies, "failed", rec.error)
        self._record_failed_progress(node, task_contract, rec.error)
        self._finish_record(rec, node_start)

    async def _call_handler(self, handler: Handler, context: NodeContext, provider: str, state: _RunState, global_sem: asyncio.Semaphore, provider_sems: Mapping[str, asyncio.Semaphore]) -> Any:
        provider_sem = provider_sems.get(provider)
        if provider_sem is None:
            return await self._call_under_global_limit(handler, context, state, global_sem)
        async with provider_sem:
            return await self._call_under_global_limit(handler, context, state, global_sem)

    async def _call_under_global_limit(self, handler: Handler, context: NodeContext, state: _RunState, global_sem: asyncio.Semaphore) -> Any:
        async with global_sem:
            async with state.active_lock:
                state.active += 1
                state.max_active = max(state.max_active, state.active)
            try:
                if inspect.iscoroutinefunction(handler):
                    return await handler(context)
                result = await asyncio.to_thread(handler, context)
                return await result if inspect.isawaitable(result) else result
            finally:
                async with state.active_lock:
                    state.active -= 1

    def _verify_dependency_trust(self, node: NodeSpec, dependencies: Mapping[str, VerifiedNodeOutput]) -> None:
        for dep_id, output in dependencies.items():
            if not can_flow(output.classification, node.security_classification):
                raise VerificationFailure("trust", f"dependency {dep_id} classification {output.classification} cannot flow to node {node.id} classification {node.security_classification}")

    async def _verify_output(
        self,
        node: NodeSpec,
        inputs: Mapping[str, Any],
        dependencies: Mapping[str, VerifiedNodeOutput],
        dependency_status: Mapping[str, str],
        output: NodeOutput | VerifiedNodeOutput,
        graph_hash: str,
        *,
        already_verified: bool = False,
    ) -> VerifiedNodeOutput:
        if isinstance(output, VerifiedNodeOutput):
            candidate = NodeOutput(output.data, output.evidence, output.classification, output.cost, output.tokens, output.external_provenance)
        else:
            candidate = output
        try:
            validate_json_schema(candidate.data, node.output_schema, path=f"node {node.id} output")
        except (GraphValidationError, ValueError, TypeError) as exc:
            raise VerificationFailure("schema", str(exc)) from exc
        classification = normalize_class(candidate.classification or node.security_classification)
        if not can_flow(classification, node.security_classification):
            raise VerificationFailure("trust", f"output classification {classification} cannot flow to node classification {node.security_classification}")
        evidence = tuple(str(x).strip() for x in candidate.evidence if str(x).strip())
        if node.require_evidence and not evidence:
            raise VerificationFailure("evidence", f"node {node.id} requires evidence before fan-in")
        try:
            cost = _nonnegative_float(candidate.cost, f"node {node.id} output cost")
            tokens = _nonnegative_int(candidate.tokens, f"node {node.id} output tokens")
            external = tuple(_normalize_provenance(x, node.id) for x in candidate.external_provenance)
            canonical_json(candidate.data)
        except (GraphValidationError, TypeError, ValueError) as exc:
            raise VerificationFailure("provenance", str(exc)) from exc
        lineage = tuple({"node_id": d, "output_hash": dependencies[d].output_hash, "classification": dependencies[d].classification} for d in sorted(dependencies))
        base = VerifiedNodeOutput(candidate.data, evidence, classification, cost, tokens, external, lineage, "")
        verified = VerifiedNodeOutput(**{**asdict(base), "output_hash": _verified_output_hash(base)})
        if already_verified and isinstance(output, VerifiedNodeOutput) and output.dependency_provenance != lineage:
            raise VerificationFailure("provenance", f"checkpoint lineage mismatch for node {node.id}")
        if self.policy_verifier is not None:
            ctx = PolicyContext(node, inputs, {k: dependencies[k] for k in sorted(dependencies)}, dict(sorted(dependency_status.items())), verified, graph_hash)
            decision = self.policy_verifier(ctx)
            if inspect.isawaitable(decision):
                decision = await decision
            allowed, reason = _normalize_policy_decision(decision)
            if not allowed:
                raise VerificationFailure("policy", reason or f"policy rejected node {node.id}")
        return verified

    @staticmethod
    def _finish_record(rec: NodeExecutionRecord, node_start: float) -> None:
        rec.duration_ms = (time.monotonic() - node_start) * 1000.0
        rec.finished_at = utc_now()
        rec._finished_monotonic = time.monotonic()

    @staticmethod
    def _reject(rec: NodeExecutionRecord, exc: VerificationFailure, state: _RunState, node_start: float) -> None:
        rec.status = "rejected"
        rec.error = f"{exc.stage}: {exc.message}"
        state.telemetry_failures[exc.stage] += 1
        GovernedGraphRuntime._finish_record(rec, node_start)


def optimize_plan(plan: GraphPlan) -> OptimizedPlan:
    node_map = plan.node_map()
    for edge in plan.edges:
        if edge.source not in node_map:
            raise GraphValidationError(f"edge {edge.id}: unknown source node {edge.source}")
        if edge.target not in node_map:
            raise GraphValidationError(f"edge {edge.id}: unknown target node {edge.target}")
        if edge.source == edge.target:
            raise GraphValidationError(f"edge {edge.id}: self dependency is not allowed")
        if edge.kind == "data" and edge.bindings:
            _validate_edge_bindings(edge, node_map[edge.target])
    pruned = tuple(sorted(e.id for e in plan.edges if e.kind == "data" and not e.bindings))
    pruned_set = set(pruned)
    effective = GraphPlan(plan.version, plan.nodes, tuple(e for e in plan.edges if e.id not in pruned_set), plan.metadata)
    _validate_binding_conflicts(effective)
    layers = _topological_layers(effective)
    return OptimizedPlan(effective, plan.graph_hash, effective.graph_hash, pruned, layers)


def _validate_edge_bindings(edge: EdgeContract, target: NodeSpec) -> None:
    schema = target.input_schema
    if schema.get("type") not in (None, "object"):
        raise GraphValidationError(f"edge {edge.id}: target node {target.id} input schema is not an object")
    properties = schema.get("properties")
    if isinstance(properties, Mapping) and schema.get("additionalProperties", True) is False:
        allowed = set(str(k) for k in properties)
        for path in edge.bindings:
            if path.split(".", 1)[0] not in allowed:
                raise GraphValidationError(f"edge {edge.id}: binding target {path!r} is not declared by node {target.id} input schema")


def _validate_binding_conflicts(plan: GraphPlan) -> None:
    by_target: dict[str, dict[str, str]] = {}
    for edge in sorted(plan.edges, key=lambda x: x.id):
        if edge.kind != "data":
            continue
        seen = by_target.setdefault(edge.target, {})
        for path in edge.bindings:
            if path in seen:
                raise GraphValidationError(f"node {edge.target}: input binding {path!r} is written by both {seen[path]} and {edge.id}")
            seen[path] = edge.id


def _topological_layers(plan: GraphPlan) -> tuple[tuple[str, ...], ...]:
    indegree = {n.id: 0 for n in plan.nodes}
    outgoing = {n.id: [] for n in plan.nodes}
    for edge in plan.edges:
        indegree[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    frontier = sorted(n for n, degree in indegree.items() if degree == 0)
    layers: list[tuple[str, ...]] = []
    seen = 0
    while frontier:
        layer = tuple(frontier)
        layers.append(layer)
        seen += len(layer)
        nxt: list[str] = []
        for source in layer:
            for target in sorted(outgoing[source]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    nxt.append(target)
        frontier = sorted(set(nxt))
    if seen != len(plan.nodes):
        cyclic = sorted(n for n, degree in indegree.items() if degree > 0)
        raise GraphValidationError("effective graph contains a cycle involving: " + ", ".join(cyclic))
    return tuple(layers)


def _incoming_edges(plan: GraphPlan) -> dict[str, tuple[EdgeContract, ...]]:
    result: dict[str, list[EdgeContract]] = {n.id: [] for n in plan.nodes}
    for edge in plan.edges:
        result[edge.target].append(edge)
    return {k: tuple(sorted(v, key=lambda e: (e.source, e.id))) for k, v in result.items()}


def _build_inputs(node: NodeSpec, incoming_edges: Sequence[EdgeContract], records: Mapping[str, NodeExecutionRecord]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for edge in sorted(incoming_edges, key=lambda e: (e.source, e.id)):
        source = records[edge.source]
        if source.status != "success" or source.output is None:
            if edge.required:
                raise VerificationFailure("provenance", f"required source {edge.source} is not accepted")
            continue
        if edge.kind != "data":
            continue
        for target_path, source_path in sorted(edge.bindings.items()):
            try:
                value = extract_json_path(source.output.data, source_path)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise VerificationFailure("provenance", f"edge {edge.id}: cannot resolve {source_path} from source {edge.source}: {exc}") from exc
            _set_dotted_path(inputs, target_path, value)
    return inputs


def extract_json_path(value: Any, path: str) -> Any:
    if path == "$":
        return value
    if not path.startswith("$."):
        raise ValueError("only '$' and '$.field[.field]' JSON paths are supported")
    current = value
    for part in path[2:].split("."):
        if not part:
            raise ValueError("empty JSON-path segment")
        if isinstance(current, Mapping):
            if part not in current:
                raise KeyError(part)
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            current = current[int(part)]
        else:
            raise TypeError(f"cannot traverse segment {part!r}")
    return current


def _set_dotted_path(target: MutableMapping[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: MutableMapping[str, Any] = target
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            nested: dict[str, Any] = {}
            current[part] = nested
            current = nested
        elif isinstance(existing, MutableMapping):
            current = existing
        else:
            raise VerificationFailure("schema", f"input binding conflict at {path!r}")
    current[parts[-1]] = value


def normalize_class(value: Any) -> str:
    raw = str(value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    normalized = SECURITY_CLASS_ALIASES.get(raw)
    if not normalized:
        raise GraphValidationError(f"unsupported security classification: {value}")
    return normalized


def can_flow(source: str, destination: str) -> bool:
    return normalize_class(destination) in SECURITY_CLASS_FLOWS[normalize_class(source)]


def validate_json_schema(value: Any, schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Conservative JSON-Schema subset used at graph boundaries."""
    if not isinstance(schema, Mapping):
        raise GraphValidationError(f"{path}: schema must be an object")
    if "allOf" in schema:
        clauses = schema["allOf"]
        if not isinstance(clauses, list):
            raise GraphValidationError(f"{path}: allOf must be an array")
        for clause in clauses:
            validate_json_schema(value, clause, path=path)
    if "anyOf" in schema:
        clauses = schema["anyOf"]
        if not isinstance(clauses, list) or not clauses:
            raise GraphValidationError(f"{path}: anyOf must be a non-empty array")
        errors = []
        for clause in clauses:
            try:
                validate_json_schema(value, clause, path=path)
                break
            except GraphValidationError as exc:
                errors.append(str(exc))
        else:
            raise GraphValidationError(f"{path}: value did not match anyOf: {'; '.join(errors)}")
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_json_type_matches(value, x) for x in allowed):
            raise GraphValidationError(f"{path}: expected type {expected!r}, got {_json_type_name(value)}")
    if "enum" in schema and value not in schema["enum"]:
        raise GraphValidationError(f"{path}: value is not in enum")
    if "const" in schema and value != schema["const"]:
        raise GraphValidationError(f"{path}: value does not match const")
    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise GraphValidationError(f"{path}: required must be an array")
        missing = [str(k) for k in required if k not in value]
        if missing:
            raise GraphValidationError(f"{path}: missing required properties: {', '.join(missing)}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise GraphValidationError(f"{path}: properties must be an object")
        for key, subschema in properties.items():
            if key in value:
                validate_json_schema(value[key], subschema, path=f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extras = sorted(str(k) for k in value if k not in properties)
            if extras:
                raise GraphValidationError(f"{path}: additional properties not allowed: {', '.join(extras)}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise GraphValidationError(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise GraphValidationError(f"{path}: more than maxItems")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                validate_json_schema(item, items, path=f"{path}.{index}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise GraphValidationError(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise GraphValidationError(f"{path}: longer than maxLength")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            raise GraphValidationError(f"{path}: does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise GraphValidationError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise GraphValidationError(f"{path}: above maximum")


def _json_type_matches(value: Any, expected: Any) -> bool:
    expected = str(expected)
    if expected == "null": return value is None
    if expected == "object": return isinstance(value, Mapping)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise GraphValidationError(f"unsupported schema type: {expected}")


def _json_type_name(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, Mapping): return "object"
    if isinstance(value, list): return "array"
    if isinstance(value, str): return "string"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "number"
    return type(value).__name__


def _coerce_node_output(value: Any, default_classification: str) -> NodeOutput:
    if isinstance(value, NodeOutput):
        return value
    if isinstance(value, VerifiedNodeOutput):
        return NodeOutput(value.data, value.evidence, value.classification, value.cost, value.tokens, value.external_provenance)
    return NodeOutput(value, classification=default_classification)


def _normalize_provenance(value: Any, node_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GraphValidationError(f"node {node_id}: external provenance entries must be objects")
    normalized = {str(k): v for k, v in value.items()}
    canonical_json(normalized)
    return normalized


def _normalize_policy_decision(value: Any) -> tuple[bool, str]:
    if isinstance(value, bool):
        return value, ""
    if isinstance(value, tuple) and len(value) == 2:
        return bool(value[0]), str(value[1] or "")
    if isinstance(value, Mapping) and "allowed" in value:
        return bool(value["allowed"]), str(value.get("reason", ""))
    raise VerificationFailure("policy", "policy verifier must return bool, (bool, reason), or {'allowed': ...}")


def _verified_output_hash(output: VerifiedNodeOutput) -> str:
    return "sha256:" + sha256_json({
        "data": output.data,
        "evidence": list(output.evidence),
        "classification": output.classification,
        "cost": output.cost,
        "tokens": output.tokens,
        "external_provenance": [dict(x) for x in output.external_provenance],
        "dependency_provenance": [dict(x) for x in output.dependency_provenance],
    })


def _critical_path_ms(plan: GraphPlan, records: Mapping[str, NodeExecutionRecord]) -> float:
    incoming = _incoming_edges(plan)
    longest: dict[str, float] = {}
    for layer in _topological_layers(plan):
        for node_id in layer:
            prev = max((longest.get(e.source, 0.0) for e in incoming[node_id]), default=0.0)
            duration = records[node_id].duration_ms if records[node_id].status == "success" else 0.0
            longest[node_id] = prev + duration
    return max(longest.values(), default=0.0)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GraphValidationError(f"value is not canonical JSON: {exc}") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _nonnegative_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GraphValidationError(f"{field_name} must be numeric") from exc
    if result < 0 or result != result or result == float("inf"):
        raise GraphValidationError(f"{field_name} must be finite and >= 0")
    return result


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise GraphValidationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        result = int(value.strip())
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    else:
        raise GraphValidationError(f"{field_name} must be an integer")
    if result < 0:
        raise GraphValidationError(f"{field_name} must be an integer >= 0")
    return result


def _positive_int(value: Any, field_name: str) -> int:
    result = _nonnegative_int(value, field_name)
    if result <= 0:
        raise GraphValidationError(f"{field_name} must be > 0")
    return result


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def analyze_plan(plan: GraphPlan, governor: ResourceGovernor | None = None) -> dict[str, Any]:
    optimized = optimize_plan(plan)
    governor = governor or ResourceGovernor()
    governor.validate_budget(optimized.plan)
    return {
        "status": "valid",
        "version": plan.version,
        "original_graph_hash": optimized.original_graph_hash,
        "graph_hash": optimized.effective_graph_hash,
        "pruned_edge_ids": list(optimized.pruned_edge_ids),
        "layers": [list(layer) for layer in optimized.layers],
        "estimated_cost": sum(n.estimated_cost for n in optimized.plan.nodes),
        "estimated_tokens": sum(n.estimated_tokens for n in optimized.plan.nodes),
        "max_concurrency": governor.max_concurrency,
        "provider_limits": dict(governor.provider_limits),
    }


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes governed graph runtime validator/analyzer")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "analyze"):
        child = sub.add_parser(command, help=f"{command} a graph plan without executing workers")
        child.add_argument("--plan", required=True, type=Path)
        child.add_argument("--resource-policy", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    try:
        plan = GraphPlan.from_json_file(args.plan)
        governor = ResourceGovernor.from_json_file(args.resource_policy) if args.resource_policy else ResourceGovernor()
        result = analyze_plan(plan, governor)
    except (OSError, json.JSONDecodeError, GraphValidationError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
