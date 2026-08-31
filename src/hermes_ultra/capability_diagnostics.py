from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping

from .autonomy import ActionContext, ApprovalRegistry
from .capability_expansion import CapabilityObservation
from .capability_projection import CapabilityCatalog, EvidenceState
from .contracts import CapabilityResult, FailureClass
from .evidence import EvidenceEnvelope, EvidenceRecorder


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RuntimeCapabilityObservation:
    capability_id: str
    loaded: bool = False
    healthy: bool | None = None
    evidence_state: EvidenceState = EvidenceState.OBSERVED
    providers: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    missing_dependencies: tuple[str, ...] = ()
    repair_action: str | None = None


@dataclass(frozen=True)
class CapabilityDiagnostic:
    capability_id: str
    purpose: str
    discoverable: bool
    loaded: bool
    healthy: bool | None
    evidence_state: EvidenceState
    providers: tuple[str, ...]
    interfaces: tuple[str, ...]
    missing_dependencies: tuple[str, ...]
    repair_action: str | None


@dataclass(frozen=True)
class CapabilityDiagnosticReport:
    diagnostics: tuple[CapabilityDiagnostic, ...]

    def by_id(self, capability_id: str) -> CapabilityDiagnostic:
        for diagnostic in self.diagnostics:
            if diagnostic.capability_id == capability_id:
                return diagnostic
        raise KeyError(capability_id)


@dataclass(frozen=True)
class VerificationHookResult:
    surface: str
    passed: bool
    evidence_state: EvidenceState
    detail: str = ""


class VerificationHookRegistry:
    """Surface-specific completion verification without capability gating."""

    def __init__(self, hooks: Mapping[str, Callable[[object], object]] | None = None) -> None:
        self._hooks: dict[str, Callable[[object], object]] = dict(hooks or {})

    def register(self, surface: str, verifier: Callable[[object], object]) -> None:
        normalized = surface.strip()
        if not normalized:
            raise ValueError("surface is required")
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        self._hooks[normalized] = verifier

    def verify(self, surface: str, payload: object) -> CapabilityResult[VerificationHookResult]:
        verifier = self._hooks.get(surface)
        if verifier is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"no verification hook registered for surface: {surface}",
                recoverable=True,
                metadata={"surface": surface},
            )
        try:
            passed = bool(verifier(payload))
        except Exception as exc:
            return CapabilityResult.success(
                VerificationHookResult(
                    surface=surface,
                    passed=False,
                    evidence_state=EvidenceState.OBSERVED,
                    detail=f"verification hook raised {type(exc).__name__}",
                )
            )
        return CapabilityResult.success(
            VerificationHookResult(
                surface=surface,
                passed=passed,
                evidence_state=EvidenceState.VERIFIED if passed else EvidenceState.OBSERVED,
                detail="verified" if passed else "verification did not pass",
            )
        )


class CapabilityDoctor:
    """Inspect capability state and autonomously repair reversible failures."""

    def __init__(
        self,
        catalog: CapabilityCatalog,
        approval_registry: ApprovalRegistry,
        evidence_recorder: EvidenceRecorder,
    ) -> None:
        self.catalog = catalog
        self.approval_registry = approval_registry
        self.evidence_recorder = evidence_recorder
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def inspect(
        self,
        observations: Iterable[RuntimeCapabilityObservation] = (),
    ) -> CapabilityDiagnosticReport:
        observed = {item.capability_id: item for item in observations}
        diagnostics: list[CapabilityDiagnostic] = []
        for descriptor in self.catalog.descriptors:
            current = observed.get(descriptor.capability_id)
            providers = current.providers if current is not None and current.providers else (
                (descriptor.provider,) if descriptor.provider else ()
            )
            interfaces = current.interfaces if current is not None and current.interfaces else (
                (descriptor.interface,) if descriptor.interface else ()
            )
            diagnostics.append(
                CapabilityDiagnostic(
                    capability_id=descriptor.capability_id,
                    purpose=descriptor.purpose,
                    discoverable=True,
                    loaded=current.loaded if current is not None else False,
                    healthy=current.healthy if current is not None else None,
                    evidence_state=(
                        current.evidence_state if current is not None else descriptor.evidence_state
                    ),
                    providers=tuple(providers),
                    interfaces=tuple(interfaces),
                    missing_dependencies=(
                        current.missing_dependencies if current is not None else ()
                    ),
                    repair_action=current.repair_action if current is not None else None,
                )
            )
        return CapabilityDiagnosticReport(tuple(diagnostics))

    def repair(
        self,
        capability_id: str,
        *,
        action: ActionContext,
        repairer: Callable[[str], object],
    ) -> CapabilityResult[CapabilityObservation]:
        descriptor = self.catalog.get(capability_id)
        if descriptor is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"unknown capability: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )

        decision = self.approval_registry.evaluate_action(action)
        envelope = EvidenceEnvelope.new(
            f"diagnostic:{capability_id}",
            "capability-diagnostic-repair",
            run_id=f"capability-diagnostic-repair:{capability_id}:{self._next_sequence()}",
        )
        envelope.human_approval_required = decision.human_approval_required
        envelope.approval_category = decision.category
        envelope.provenance = dict(descriptor.provenance)

        if decision.human_approval_required:
            envelope.health = {
                "capability_id": capability_id,
                "repair_executed": False,
                "reason": decision.reason,
            }
            envelope.finish(status="blocked", failure_class=FailureClass.AUTHORITY_REQUIRED.value)
            self.evidence_recorder.record(envelope)
            return CapabilityResult.failure(
                FailureClass.AUTHORITY_REQUIRED,
                decision.reason or "repair requires existing authority boundary",
                recoverable=True,
                metadata={
                    "capability_id": capability_id,
                    "approval_category": decision.category,
                },
            )

        try:
            repair_result = repairer(capability_id)
        except Exception as exc:
            envelope.health = {
                "capability_id": capability_id,
                "repair_executed": True,
                "passed": False,
                "error_type": type(exc).__name__,
            }
            envelope.finish(status="failure", failure_class=FailureClass.HEALTHCHECK_FAILED.value)
            self.evidence_recorder.record(envelope)
            return CapabilityResult.failure(
                FailureClass.HEALTHCHECK_FAILED,
                "diagnostic repair failed",
                recoverable=True,
                metadata={"capability_id": capability_id, "error_type": type(exc).__name__},
            )

        if not bool(repair_result):
            envelope.health = {
                "capability_id": capability_id,
                "repair_executed": True,
                "passed": False,
            }
            envelope.finish(status="failure", failure_class=FailureClass.HEALTHCHECK_FAILED.value)
            self.evidence_recorder.record(envelope)
            return CapabilityResult.failure(
                FailureClass.HEALTHCHECK_FAILED,
                "diagnostic repair did not restore capability health",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )

        observation = CapabilityObservation(
            sequence=self._next_sequence(),
            task_id=f"diagnostic:{capability_id}",
            capability_id=capability_id,
            evidence_state=EvidenceState.OBSERVED,
            result=str(repair_result),
            recorded_at=_now(),
        )
        envelope.health = {
            "capability_id": capability_id,
            "repair_executed": True,
            "passed": True,
            "observation": observation.to_dict(),
        }
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)
        return CapabilityResult.success(observation)
