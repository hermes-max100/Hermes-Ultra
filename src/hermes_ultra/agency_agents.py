from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class AgentState(str, Enum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    SCORED = "SCORED"
    QUALIFIED = "QUALIFIED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    prompt: str
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    source_revision: str = ""
    privilege_category: str | None = None


@dataclass(frozen=True)
class QualificationScore:
    uniqueness: float
    capability_completeness: float
    provenance: float
    tool_quality: float
    integrity: float

    @property
    def total(self) -> float:
        return round(
            0.25 * self.uniqueness
            + 0.25 * self.capability_completeness
            + 0.20 * self.provenance
            + 0.15 * self.tool_quality
            + 0.15 * self.integrity,
            6,
        )


@dataclass(frozen=True)
class IngestionResult:
    definition: AgentDefinition
    state: AgentState
    score: QualificationScore
    digest: str
    reason: str = ""
    human_approval_required: bool = False


class AgencyAgentIngestor:
    def __init__(
        self,
        *,
        existing_names: Iterable[str] = (),
        activation_threshold: float = 0.70,
    ) -> None:
        self._existing_names = {name.strip().lower() for name in existing_names}
        self.activation_threshold = activation_threshold

    def normalize(self, definition: AgentDefinition) -> AgentDefinition:
        return AgentDefinition(
            name=definition.name.strip().lower(),
            prompt=" ".join(definition.prompt.split()),
            capabilities=tuple(sorted(set(item.strip().lower() for item in definition.capabilities if item.strip()))),
            tools=tuple(sorted(set(item.strip().lower() for item in definition.tools if item.strip()))),
            source_revision=definition.source_revision.strip(),
            privilege_category=(
                definition.privilege_category.strip()
                if definition.privilege_category and definition.privilege_category.strip()
                else None
            ),
        )

    def digest(self, definition: AgentDefinition) -> str:
        normalized = self.normalize(definition)
        payload = json.dumps(
            {
                "name": normalized.name,
                "prompt": normalized.prompt,
                "capabilities": normalized.capabilities,
                "tools": normalized.tools,
                "source_revision": normalized.source_revision,
                "privilege_category": normalized.privilege_category,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def _integrity_score(self, prompt: str) -> float:
        lowered = prompt.lower()
        conflicting = (
            "ignore previous instructions",
            "rewrite hermes runtime policy",
            "disable hermes policy",
            "override hermes policy",
        )
        return 0.0 if any(phrase in lowered for phrase in conflicting) else 1.0

    def score(self, definition: AgentDefinition) -> QualificationScore:
        normalized = self.normalize(definition)
        return QualificationScore(
            uniqueness=0.0 if normalized.name in self._existing_names else 1.0,
            capability_completeness=1.0 if normalized.capabilities else 0.0,
            provenance=1.0 if normalized.source_revision else 0.0,
            tool_quality=1.0 if normalized.tools else 0.75,
            integrity=self._integrity_score(normalized.prompt),
        )

    def ingest(self, definition: AgentDefinition) -> IngestionResult:
        normalized = self.normalize(definition)
        score = self.score(normalized)
        digest = self.digest(normalized)

        if normalized.name in self._existing_names:
            return IngestionResult(
                definition=normalized,
                state=AgentState.REJECTED,
                score=score,
                digest=digest,
                reason="duplicate agent name",
            )
        if score.integrity == 0.0:
            return IngestionResult(
                definition=normalized,
                state=AgentState.REJECTED,
                score=score,
                digest=digest,
                reason="definition conflicts with Hermes policy boundary",
            )
        if score.total < self.activation_threshold:
            return IngestionResult(
                definition=normalized,
                state=AgentState.REJECTED,
                score=score,
                digest=digest,
                reason=f"qualification score {score.total:.3f} below {self.activation_threshold:.3f}",
            )

        self._existing_names.add(normalized.name)
        return IngestionResult(
            definition=normalized,
            state=AgentState.ACTIVE,
            score=score,
            digest=digest,
            reason="qualified automatically",
            human_approval_required=False,
        )
