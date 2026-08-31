from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .autonomy import ActionConsequenceClassifier, ActionContext, ApprovalRegistry
from .capability_projection import (
    CapabilityCatalog,
    ConsequenceClass,
    EvidenceState,
)
from .contracts import CapabilityResult, FailureClass
from .evidence import EvidenceEnvelope, EvidenceRecorder


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CapabilityExpansionEvent:
    sequence: int
    task_id: str
    capability_id: str
    reason: str
    expected_utility: float
    consequence_class: ConsequenceClass
    reversible: bool
    provenance: tuple[tuple[str, str], ...]
    recorded_at: str
    decision: str
    observed_result: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "reason": self.reason,
            "expected_utility": self.expected_utility,
            "consequence_class": self.consequence_class.value,
            "reversible": self.reversible,
            "provenance": dict(self.provenance),
            "recorded_at": self.recorded_at,
            "decision": self.decision,
            "observed_result": self.observed_result,
        }


@dataclass(frozen=True)
class CapabilityObservation:
    sequence: int
    task_id: str
    capability_id: str
    evidence_state: EvidenceState
    result: str
    recorded_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "evidence_state": self.evidence_state.value,
            "result": self.result,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class CapabilityExpansionDecision:
    event: CapabilityExpansionEvent
    expanded: bool
    human_approval_required: bool
    approval_category: str | None
    reason: str


class CapabilityExpansionController:
    """Expand task working capability without creating a second authority store."""

    def __init__(
        self,
        catalog: CapabilityCatalog,
        approval_registry: ApprovalRegistry,
        evidence_recorder: EvidenceRecorder,
        *,
        consequence_classifier: ActionConsequenceClassifier | None = None,
    ) -> None:
        self.catalog = catalog
        self.approval_registry = approval_registry
        self.evidence_recorder = evidence_recorder
        self.consequence_classifier = consequence_classifier or ActionConsequenceClassifier()
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def request(
        self,
        *,
        task_id: str,
        capability_id: str,
        reason: str,
        expected_utility: float,
        action: ActionContext,
    ) -> CapabilityResult[CapabilityExpansionDecision]:
        descriptor = self.catalog.get(capability_id)
        if descriptor is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"unknown capability: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )

        autonomy = self.approval_registry.evaluate_action(
            action,
            classifier=self.consequence_classifier,
        )
        consequence = autonomy.consequence_class or self.consequence_classifier.classify(action)
        expanded = not autonomy.human_approval_required
        decision_name = "expanded" if expanded else "authorization_required"
        event = CapabilityExpansionEvent(
            sequence=self._next_sequence(),
            task_id=task_id,
            capability_id=capability_id,
            reason=reason,
            expected_utility=max(0.0, min(1.0, float(expected_utility))),
            consequence_class=consequence,
            reversible=action.reversible,
            provenance=descriptor.provenance,
            recorded_at=_now(),
            decision=decision_name,
        )
        envelope = EvidenceEnvelope.new(
            task_id,
            "capability-expansion",
            run_id=f"capability-expansion:{task_id}:{event.sequence}",
        )
        envelope.human_approval_required = autonomy.human_approval_required
        envelope.approval_category = autonomy.category
        envelope.health = {
            "event": event.to_dict(),
            "expanded": expanded,
            "decision_reason": autonomy.reason,
        }
        envelope.provenance = dict(descriptor.provenance)
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)

        return CapabilityResult.success(
            CapabilityExpansionDecision(
                event=event,
                expanded=expanded,
                human_approval_required=autonomy.human_approval_required,
                approval_category=autonomy.category,
                reason=autonomy.reason or decision_name,
            )
        )

    def observe(
        self,
        event: CapabilityExpansionEvent,
        *,
        result: object,
        state: EvidenceState = EvidenceState.OBSERVED,
    ) -> CapabilityObservation:
        observation = CapabilityObservation(
            sequence=self._next_sequence(),
            task_id=event.task_id,
            capability_id=event.capability_id,
            evidence_state=state,
            result=str(result),
            recorded_at=_now(),
        )
        envelope = EvidenceEnvelope.new(
            event.task_id,
            "capability-observation",
            run_id=f"capability-observation:{event.task_id}:{observation.sequence}",
        )
        envelope.health = {
            "observation": observation.to_dict(),
            "expansion_sequence": event.sequence,
        }
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)
        return observation
