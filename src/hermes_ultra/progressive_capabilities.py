from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from .autonomy import ActionContext
from .capability_expansion import CapabilityExpansionController, CapabilityExpansionDecision
from .capability_projection import (
    CapabilityCatalog,
    CapabilityProjection,
    CapabilityProjector,
    RuntimeCapabilityDescriptor,
)
from .contracts import CapabilityResult, FailureClass


class CapabilityExecutor(Protocol):
    def execute(
        self,
        *,
        capability_id: str,
        arguments: dict[str, object],
    ) -> CapabilityResult[object]: ...


class DiscoveryTask(Protocol):
    task_id: str
    objective: str
    capability_hints: Iterable[object]


@dataclass(frozen=True)
class _QueryTask:
    task_id: str
    objective: str
    capability_hints: tuple[object, ...]


@dataclass(frozen=True)
class CapabilityDiscoveryHit:
    descriptor: RuntimeCapabilityDescriptor
    relevance_score: float
    match_reason: str
    summary_only: bool

    @property
    def capability_id(self) -> str:
        return self.descriptor.capability_id

    @property
    def dispatchable(self) -> bool:
        return self.descriptor.available

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "family": self.descriptor.family,
            "purpose": self.descriptor.purpose,
            "relevance_score": round(float(self.relevance_score), 6),
            "match_reason": self.match_reason,
            "dispatchable": self.dispatchable,
            "summary_only": self.summary_only,
        }


@dataclass(frozen=True)
class CapabilityDiscoveryResult:
    task_id: str
    query: str
    hits: tuple[CapabilityDiscoveryHit, ...]
    discoverable_ids: frozenset[str]
    catalog_size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
            "discoverable_ids": sorted(self.discoverable_ids),
            "catalog_size": self.catalog_size,
        }


@dataclass(frozen=True)
class CapabilityDescription:
    descriptor: RuntimeCapabilityDescriptor
    dispatchable: bool

    def to_dict(self) -> dict[str, object]:
        descriptor = self.descriptor
        return {
            "capability_id": descriptor.capability_id,
            "family": descriptor.family,
            "purpose": descriptor.purpose,
            "match_terms": list(descriptor.match_terms),
            "base_utility": descriptor.base_utility,
            "consequence_class": descriptor.consequence_class.value,
            "reversible": descriptor.reversible,
            "interface": descriptor.interface,
            "provider": descriptor.provider,
            "evidence_state": descriptor.evidence_state.value,
            "provenance": dict(descriptor.provenance),
            "detail_token_estimate": descriptor.detail_token_estimate,
            "summary_token_estimate": descriptor.summary_token_estimate,
            "available": descriptor.available,
            "dispatchable": self.dispatchable,
        }


@dataclass(frozen=True)
class CapabilityDispatchResult:
    capability_id: str
    value: object
    projection: CapabilityProjection | None
    expansion: CapabilityExpansionDecision | None = None


class ProgressiveCapabilityRuntime:
    """Compact discovery/description/dispatch facade over governed capabilities.

    The runtime does not own provider lifecycle, provider selection, routing, or
    promotion. It can only expose descriptors present in the injected catalog,
    expand task working context through the existing expansion controller, and
    delegate execution to the injected already-governed executor.
    """

    def __init__(
        self,
        catalog: CapabilityCatalog,
        *,
        executor: CapabilityExecutor,
        expansion_controller: CapabilityExpansionController | None = None,
        discovery_token_budget: int = 512,
    ) -> None:
        if discovery_token_budget <= 0:
            raise ValueError("discovery_token_budget must be positive")
        self.catalog = catalog
        self.executor = executor
        self.expansion_controller = expansion_controller
        self.discovery_token_budget = discovery_token_budget

    def discover(
        self,
        *,
        task: DiscoveryTask,
        query: str = "",
        limit: int = 5,
    ) -> CapabilityResult[CapabilityDiscoveryResult]:
        if limit <= 0:
            return CapabilityResult.failure(
                FailureClass.ADAPTER_REJECTED,
                "discovery limit must be positive",
                recoverable=True,
            )

        normalized_query = query.strip()
        objective = normalized_query or str(task.objective)
        query_task = _QueryTask(
            task_id=str(task.task_id),
            objective=objective,
            capability_hints=tuple(getattr(task, "capability_hints", ())),
        )
        projector = CapabilityProjector(
            self.catalog,
            token_budget=max(self.discovery_token_budget, limit * 8),
            max_projected=limit,
        )
        projection = projector.project(query_task)
        hits = tuple(
            CapabilityDiscoveryHit(
                descriptor=item.descriptor,
                relevance_score=item.relevance_score,
                match_reason=item.match_reason,
                summary_only=True,
            )
            for item in projection.included[:limit]
        )
        return CapabilityResult.success(
            CapabilityDiscoveryResult(
                task_id=str(task.task_id),
                query=normalized_query,
                hits=hits,
                discoverable_ids=projection.discoverable_ids,
                catalog_size=projection.catalog_size,
            )
        )

    def describe(self, capability_id: str) -> CapabilityResult[CapabilityDescription]:
        descriptor = self.catalog.get(capability_id)
        if descriptor is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"unknown capability: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )
        return CapabilityResult.success(
            CapabilityDescription(
                descriptor=descriptor,
                dispatchable=descriptor.available,
            )
        )

    def _authority_failure(
        self,
        capability_id: str,
        message: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> CapabilityResult[CapabilityDispatchResult]:
        details = {"capability_id": capability_id}
        details.update(dict(metadata or {}))
        return CapabilityResult.failure(
            FailureClass.AUTHORITY_REQUIRED,
            message,
            recoverable=True,
            metadata=details,
        )

    def dispatch(
        self,
        *,
        task_id: str,
        capability_id: str,
        arguments: Mapping[str, object],
        action: ActionContext,
        reason: str,
        expected_utility: float,
        projection: CapabilityProjection | None = None,
    ) -> CapabilityResult[CapabilityDispatchResult]:
        descriptor = self.catalog.get(capability_id)
        if descriptor is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"unknown capability: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )
        if not descriptor.available:
            return self._authority_failure(
                capability_id,
                f"capability is known but not runtime-available: {capability_id}",
                metadata={"reason": "governance_state_not_runtime_available"},
            )

        current_projection = projection
        expansion: CapabilityExpansionDecision | None = None
        controller = self.expansion_controller

        if current_projection is not None and not current_projection.contains(capability_id):
            if controller is None:
                return self._authority_failure(
                    capability_id,
                    f"capability is outside the current task projection: {capability_id}",
                    metadata={"reason": "capability_expansion_controller_unavailable"},
                )
            expansion_result = controller.request(
                task_id=task_id,
                capability_id=capability_id,
                reason=reason,
                expected_utility=expected_utility,
                action=action,
            )
            if not expansion_result.ok or expansion_result.value is None:
                return CapabilityResult.failure(
                    expansion_result.failure_class or FailureClass.UNKNOWN,
                    expansion_result.message or "capability expansion failed",
                    recoverable=expansion_result.recoverable,
                    metadata=expansion_result.metadata,
                )
            expansion = expansion_result.value
            if not expansion.expanded:
                return self._authority_failure(
                    capability_id,
                    expansion.reason or "capability expansion requires authorization",
                    metadata={
                        "approval_category": expansion.approval_category,
                        "reason": expansion.reason,
                    },
                )
            current_projection = current_projection.include_on_demand(
                descriptor,
                expected_utility=expected_utility,
                reason=reason,
            )
        elif controller is not None:
            autonomy = controller.approval_registry.evaluate_action(
                action,
                classifier=controller.consequence_classifier,
            )
            if autonomy.human_approval_required:
                return self._authority_failure(
                    capability_id,
                    autonomy.reason or "action requires authorization",
                    metadata={
                        "approval_category": autonomy.category,
                        "reason": autonomy.reason,
                    },
                )

        executor_result = self.executor.execute(
            capability_id=capability_id,
            arguments=dict(arguments),
        )
        if not isinstance(executor_result, CapabilityResult):
            return CapabilityResult.failure(
                FailureClass.ADAPTER_REJECTED,
                "capability executor returned a non-CapabilityResult",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )
        if not executor_result.ok:
            return CapabilityResult.failure(
                executor_result.failure_class or FailureClass.UNKNOWN,
                executor_result.message,
                recoverable=executor_result.recoverable,
                metadata=executor_result.metadata,
            )

        return CapabilityResult.success(
            CapabilityDispatchResult(
                capability_id=capability_id,
                value=executor_result.value,
                projection=current_projection,
                expansion=expansion,
            ),
            metadata=executor_result.metadata,
        )
