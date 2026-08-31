from __future__ import annotations

from hermes_ultra.autonomy import ActionContext, ApprovalRegistry
from hermes_ultra.capability_diagnostics import (
    CapabilityDoctor,
    RuntimeCapabilityObservation,
    VerificationHookRegistry,
)
from hermes_ultra.capability_projection import EvidenceState, default_runtime_capability_catalog
from hermes_ultra.contracts import FailureClass
from hermes_ultra.evidence import EvidenceRecorder


def test_doctor_reports_discoverable_unloaded_and_verified_runtime_states():
    doctor = CapabilityDoctor(
        default_runtime_capability_catalog(),
        ApprovalRegistry(),
        EvidenceRecorder(),
    )

    report = doctor.inspect(
        (
            RuntimeCapabilityObservation(
                "research.search",
                loaded=True,
                healthy=True,
                evidence_state=EvidenceState.VERIFIED,
                providers=("omniroute",),
            ),
        )
    )

    assert report.by_id("research.search").loaded is True
    assert report.by_id("research.search").healthy is True
    assert report.by_id("research.search").evidence_state is EvidenceState.VERIFIED
    assert report.by_id("files.retrieve").discoverable is True
    assert report.by_id("files.retrieve").loaded is False


def test_reversible_diagnostic_repair_runs_without_new_approval_boundary():
    calls: list[str] = []
    recorder = EvidenceRecorder()
    doctor = CapabilityDoctor(
        default_runtime_capability_catalog(),
        ApprovalRegistry({"production_deploy"}),
        recorder,
    )

    result = doctor.repair(
        "files.retrieve",
        action=ActionContext("repair_local_config", reversible=True),
        repairer=lambda capability_id: calls.append(capability_id) or True,
    )

    assert result.ok
    assert calls == ["files.retrieve"]
    assert result.value.evidence_state is EvidenceState.OBSERVED
    assert recorder.records[-1]["capability"] == "capability-diagnostic-repair"
    assert recorder.records[-1]["human_approval_required"] is False


def test_consequential_diagnostic_repair_requires_authority_and_does_not_run():
    calls: list[str] = []
    doctor = CapabilityDoctor(
        default_runtime_capability_catalog(),
        ApprovalRegistry({"production_deploy"}),
        EvidenceRecorder(),
    )

    result = doctor.repair(
        "connector.invoke",
        action=ActionContext("production_deploy", reversible=False, remote=True),
        repairer=lambda capability_id: calls.append(capability_id) or True,
    )

    assert result.ok is False
    assert result.failure_class is FailureClass.AUTHORITY_REQUIRED
    assert result.recoverable is True
    assert calls == []


def test_surface_verification_records_verified_or_observed_without_changing_availability():
    hooks = VerificationHookRegistry()
    hooks.register("plugin", lambda payload: payload == "loads")

    passed = hooks.verify("plugin", "loads")
    failed = hooks.verify("plugin", "broken")

    assert passed.ok and passed.value.passed is True
    assert passed.value.evidence_state is EvidenceState.VERIFIED
    assert failed.ok and failed.value.passed is False
    assert failed.value.evidence_state is EvidenceState.OBSERVED


def test_missing_verification_hook_is_recoverable_not_capability_denial():
    hooks = VerificationHookRegistry()

    result = hooks.verify("unknown-surface", {})

    assert result.ok is False
    assert result.recoverable is True
    assert result.failure_class is FailureClass.DEPENDENCY_MISSING
