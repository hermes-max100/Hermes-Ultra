from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Protocol


class ConsequenceClass(str, Enum):
    REVERSIBLE_LOCAL = "REVERSIBLE_LOCAL"
    REVERSIBLE_REMOTE = "REVERSIBLE_REMOTE"
    CONSEQUENTIAL = "CONSEQUENTIAL"


class EvidenceState(str, Enum):
    PREPARED = "prepared"
    OBSERVED = "observed"
    VERIFIED = "verified"


class ProjectionExclusionReason(str, Enum):
    NOT_RELEVANT_TO_REQUEST = "not_relevant_to_request"
    OUTRANKED_BY_SHORTLIST = "outranked_by_shortlist"
    BEYOND_CONTEXT_BUDGET = "beyond_context_budget"
    UNAVAILABLE_IN_CURRENT_RUNTIME = "unavailable_in_current_runtime"
    CONSEQUENTIAL_BOUNDARY_REQUIRES_AUTHORIZATION = "consequential_boundary_requires_authorization"


class ProjectionTask(Protocol):
    task_id: str
    objective: str
    capability_hints: Iterable[object]


@dataclass(frozen=True)
class RuntimeCapabilityDescriptor:
    capability_id: str
    family: str
    purpose: str
    match_terms: tuple[str, ...] = ()
    base_utility: float = 0.2
    consequence_class: ConsequenceClass = ConsequenceClass.REVERSIBLE_LOCAL
    reversible: bool = True
    interface: str | None = None
    provider: str | None = None
    evidence_state: EvidenceState = EvidenceState.PREPARED
    provenance: tuple[tuple[str, str], ...] = ()
    detail_token_estimate: int = 32
    summary_token_estimate: int = 8
    available: bool = True

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id is required")
        if not self.family.strip():
            raise ValueError("family is required")
        if not self.purpose.strip():
            raise ValueError("purpose is required")
        if not 0.0 <= float(self.base_utility) <= 1.0:
            raise ValueError("base_utility must be between 0 and 1")
        if self.summary_token_estimate <= 0:
            raise ValueError("summary_token_estimate must be positive")
        if self.detail_token_estimate < self.summary_token_estimate:
            raise ValueError("detail_token_estimate must be >= summary_token_estimate")

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "family": self.family,
            "purpose": self.purpose,
            "consequence_class": self.consequence_class.value,
            "reversible": self.reversible,
            "interface": self.interface,
            "provider": self.provider,
            "evidence_state": self.evidence_state.value,
            "provenance": dict(self.provenance),
            "available": self.available,
        }


@dataclass(frozen=True)
class ProjectedCapability:
    descriptor: RuntimeCapabilityDescriptor
    match_reason: str
    relevance_score: float
    summary_only: bool = True

    @property
    def capability_id(self) -> str:
        return self.descriptor.capability_id

    @property
    def context_tokens(self) -> int:
        if self.summary_only:
            return self.descriptor.summary_token_estimate
        return self.descriptor.detail_token_estimate

    def to_dict(self) -> dict[str, object]:
        payload = self.descriptor.to_dict()
        payload.update(
            {
                "match_reason": self.match_reason,
                "relevance_score": round(float(self.relevance_score), 6),
                "summary_only": self.summary_only,
            }
        )
        return payload


@dataclass(frozen=True)
class CapabilityExclusion:
    capability_id: str
    reason: ProjectionExclusionReason
    relevance_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "reason": self.reason.value,
            "relevance_score": round(float(self.relevance_score), 6),
            "discoverable": True,
        }


@dataclass(frozen=True)
class CapabilityProjection:
    task_id: str
    included: tuple[ProjectedCapability, ...]
    excluded: tuple[CapabilityExclusion, ...]
    token_budget: int
    estimated_tokens: int
    catalog_size: int

    @property
    def included_ids(self) -> frozenset[str]:
        return frozenset(item.capability_id for item in self.included)

    @property
    def discoverable_ids(self) -> frozenset[str]:
        return self.included_ids | frozenset(item.capability_id for item in self.excluded)

    def contains(self, capability_id: str) -> bool:
        return capability_id in self.included_ids

    def to_router_metadata(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "included": [item.to_dict() for item in self.included],
            "excluded": [item.to_dict() for item in self.excluded],
            "discoverable_ids": sorted(self.discoverable_ids),
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "catalog_size": self.catalog_size,
        }

    def include_on_demand(
        self,
        descriptor: RuntimeCapabilityDescriptor,
        *,
        expected_utility: float,
        reason: str,
    ) -> "CapabilityProjection":
        if self.contains(descriptor.capability_id):
            return self
        score = max(0.0, min(1.0, float(expected_utility)))
        included = list(self.included)
        excluded = [item for item in self.excluded if item.capability_id != descriptor.capability_id]
        needed = descriptor.summary_token_estimate
        used = self.estimated_tokens

        for index in sorted(
            (i for i, item in enumerate(included) if not item.summary_only),
            key=lambda i: (included[i].relevance_score, included[i].capability_id),
        ):
            if used + needed <= self.token_budget:
                break
            current = included[index]
            used -= current.descriptor.detail_token_estimate - current.descriptor.summary_token_estimate
            included[index] = replace(current, summary_only=True)

        while included and used + needed > self.token_budget:
            victim_index = min(
                range(len(included)),
                key=lambda i: (included[i].relevance_score, included[i].capability_id),
            )
            victim = included.pop(victim_index)
            used -= victim.context_tokens
            excluded.append(
                CapabilityExclusion(
                    capability_id=victim.capability_id,
                    reason=ProjectionExclusionReason.BEYOND_CONTEXT_BUDGET,
                    relevance_score=victim.relevance_score,
                )
            )

        if needed <= self.token_budget:
            included.append(
                ProjectedCapability(
                    descriptor=descriptor,
                    match_reason=reason,
                    relevance_score=score,
                    summary_only=True,
                )
            )
            used += needed
        else:
            excluded.append(
                CapabilityExclusion(
                    capability_id=descriptor.capability_id,
                    reason=ProjectionExclusionReason.BEYOND_CONTEXT_BUDGET,
                    relevance_score=score,
                )
            )

        return CapabilityProjection(
            task_id=self.task_id,
            included=tuple(included),
            excluded=tuple(sorted(excluded, key=lambda item: item.capability_id)),
            token_budget=self.token_budget,
            estimated_tokens=used,
            catalog_size=self.catalog_size,
        )


class CapabilityCatalog:
    def __init__(self, descriptors: Iterable[RuntimeCapabilityDescriptor]) -> None:
        indexed: dict[str, RuntimeCapabilityDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.capability_id in indexed:
                raise ValueError(f"duplicate capability_id: {descriptor.capability_id}")
            indexed[descriptor.capability_id] = descriptor
        self._descriptors = tuple(indexed[key] for key in sorted(indexed))
        self._index = indexed

    @property
    def descriptors(self) -> tuple[RuntimeCapabilityDescriptor, ...]:
        return self._descriptors

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._index)

    def get(self, capability_id: str) -> RuntimeCapabilityDescriptor | None:
        return self._index.get(capability_id)

    def require(self, capability_id: str) -> RuntimeCapabilityDescriptor:
        descriptor = self.get(capability_id)
        if descriptor is None:
            raise KeyError(capability_id)
        return descriptor


class CapabilityProjector:
    def __init__(
        self,
        catalog: CapabilityCatalog,
        *,
        token_budget: int = 256,
        max_projected: int = 8,
    ) -> None:
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if max_projected <= 0:
            raise ValueError("max_projected must be positive")
        self.catalog = catalog
        self.token_budget = token_budget
        self.max_projected = max_projected

    @staticmethod
    def _normalized_hints(task: ProjectionTask) -> frozenset[str]:
        return frozenset(
            str(value).strip().lower().replace("-", "_")
            for value in getattr(task, "capability_hints", ())
            if str(value).strip()
        )

    def _rank(self, descriptor: RuntimeCapabilityDescriptor, task: ProjectionTask) -> tuple[float, str]:
        hints = self._normalized_hints(task)
        objective = str(task.objective).lower()
        capability_key = descriptor.capability_id.lower().replace("-", "_")
        family_key = descriptor.family.lower().replace("-", "_")
        score = float(descriptor.base_utility)
        reasons: list[str] = []

        if capability_key in hints:
            score += 0.8
            reasons.append("explicit_capability_hint")
        if family_key in hints:
            score += 0.55
            reasons.append("explicit_family_hint")
        if descriptor.family.lower() in objective:
            score += 0.35
            reasons.append("family_match")
        matched_terms = tuple(term for term in descriptor.match_terms if term.lower() in objective)
        if matched_terms:
            score += min(0.45, 0.15 * len(matched_terms))
            reasons.append("objective_match:" + ",".join(sorted(matched_terms)))

        return min(score, 1.0), ";".join(reasons) or "baseline_utility"

    def project(self, task: ProjectionTask) -> CapabilityProjection:
        ranked: list[tuple[RuntimeCapabilityDescriptor, float, str]] = []
        exclusions: list[CapabilityExclusion] = []

        for descriptor in self.catalog.descriptors:
            score, reason = self._rank(descriptor, task)
            if not descriptor.available:
                exclusions.append(
                    CapabilityExclusion(
                        descriptor.capability_id,
                        ProjectionExclusionReason.UNAVAILABLE_IN_CURRENT_RUNTIME,
                        score,
                    )
                )
                continue
            if reason == "baseline_utility":
                exclusions.append(
                    CapabilityExclusion(
                        descriptor.capability_id,
                        ProjectionExclusionReason.NOT_RELEVANT_TO_REQUEST,
                        score,
                    )
                )
                continue
            ranked.append((descriptor, score, reason))

        ranked.sort(key=lambda item: (-item[1], item[0].capability_id))
        shortlist = ranked[: self.max_projected]
        for descriptor, score, _ in ranked[self.max_projected :]:
            exclusions.append(
                CapabilityExclusion(
                    descriptor.capability_id,
                    ProjectionExclusionReason.OUTRANKED_BY_SHORTLIST,
                    score,
                )
            )

        included: list[ProjectedCapability] = []
        used = 0
        for descriptor, score, reason in shortlist:
            if used + descriptor.summary_token_estimate <= self.token_budget:
                included.append(
                    ProjectedCapability(
                        descriptor=descriptor,
                        match_reason=reason,
                        relevance_score=score,
                        summary_only=True,
                    )
                )
                used += descriptor.summary_token_estimate
            else:
                exclusions.append(
                    CapabilityExclusion(
                        descriptor.capability_id,
                        ProjectionExclusionReason.BEYOND_CONTEXT_BUDGET,
                        score,
                    )
                )

        for index, item in enumerate(included):
            upgrade = item.descriptor.detail_token_estimate - item.descriptor.summary_token_estimate
            if used + upgrade <= self.token_budget:
                included[index] = replace(item, summary_only=False)
                used += upgrade

        return CapabilityProjection(
            task_id=str(task.task_id),
            included=tuple(included),
            excluded=tuple(sorted(exclusions, key=lambda item: item.capability_id)),
            token_budget=self.token_budget,
            estimated_tokens=used,
            catalog_size=len(self.catalog.descriptors),
        )


def default_runtime_capability_catalog() -> CapabilityCatalog:
    source = (("source", "hermes-ultra"),)
    return CapabilityCatalog(
        (
            RuntimeCapabilityDescriptor(
                "files.retrieve",
                "files",
                "Retrieve task-scoped local or connected file evidence",
                match_terms=("file", "document", "attachment", "pdf"),
                consequence_class=ConsequenceClass.REVERSIBLE_LOCAL,
                interface="files",
                provenance=source,
            ),
            RuntimeCapabilityDescriptor(
                "research.search",
                "research",
                "Search current sources for task evidence",
                match_terms=("research", "search", "latest", "current", "source"),
                consequence_class=ConsequenceClass.REVERSIBLE_REMOTE,
                interface="search",
                provider="omniroute",
                provenance=source,
            ),
            RuntimeCapabilityDescriptor(
                "research.deep",
                "research",
                "Run deeper multi-source research when ordinary search is insufficient",
                match_terms=("research", "deep", "investigate", "analysis"),
                consequence_class=ConsequenceClass.REVERSIBLE_REMOTE,
                interface="research",
                provider="omniroute",
                provenance=source,
            ),
            RuntimeCapabilityDescriptor(
                "compute.execute",
                "compute",
                "Execute bounded local computation for task evidence",
                match_terms=("compute", "calculate", "python", "code", "test"),
                consequence_class=ConsequenceClass.REVERSIBLE_LOCAL,
                interface="compute",
                provenance=source,
            ),
            RuntimeCapabilityDescriptor(
                "connector.invoke",
                "connectors",
                "Invoke an already-authorized connected service capability",
                match_terms=("connector", "gmail", "calendar", "github", "drive", "slack"),
                consequence_class=ConsequenceClass.REVERSIBLE_REMOTE,
                interface="connector",
                provenance=source,
            ),
            RuntimeCapabilityDescriptor(
                "specialist.delegate",
                "specialist",
                "Delegate bounded specialist analysis while Hermes retains authority",
                match_terms=("specialist", "legal", "security", "medical", "tax"),
                consequence_class=ConsequenceClass.REVERSIBLE_REMOTE,
                interface="specialist",
                provider="omniroute",
                provenance=source,
            ),
        )
    )
