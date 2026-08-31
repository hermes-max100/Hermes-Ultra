from __future__ import annotations

from hermes_ultra.autonomy import ActionContext, ActionConsequenceClassifier, ApprovalRegistry
from hermes_ultra.capability_expansion import CapabilityExpansionController
from hermes_ultra.capability_projection import ConsequenceClass, EvidenceState, default_runtime_capability_catalog
from hermes_ultra.evidence import EvidenceRecorder


def test_powerful_tool_label_does_not_make_reversible_local_action_consequential():
    action = ActionContext(
        action_category="filesystem_mutation",
        reversible=True,
        remote=False,
    )

    assert ActionConsequenceClassifier().classify(action) is ConsequenceClass.REVERSIBLE_LOCAL


def test_reversible_remote_inside_existing_scope_remains_autonomous():
    registry = ApprovalRegistry({"production_deploy"})
    action = ActionContext(
        action_category="research_search",
        reversible=True,
        remote=True,
        within_authorized_scope=True,
    )

    decision = registry.evaluate_action(action)

    assert decision.human_approval_required is False
    assert decision.consequence_class is ConsequenceClass.REVERSIBLE_REMOTE


def test_reversible_local_omitted_capability_expands_without_approval_and_records_evidence():
    recorder = EvidenceRecorder()
    controller = CapabilityExpansionController(
        default_runtime_capability_catalog(),
        ApprovalRegistry({"production_deploy"}),
        recorder,
    )

    result = controller.request(
        task_id="t1",
        capability_id="compute.execute",
        reason="need a local calculation",
        expected_utility=0.9,
        action=ActionContext("code_execution", reversible=True),
    )

    assert result.ok
    assert result.value.expanded is True
    assert result.value.human_approval_required is False
    assert result.value.event.sequence == 1
    assert result.value.event.consequence_class is ConsequenceClass.REVERSIBLE_LOCAL
    assert recorder.records[-1]["capability"] == "capability-expansion"


def test_registered_consequential_action_records_boundary_without_expanding():
    recorder = EvidenceRecorder()
    controller = CapabilityExpansionController(
        default_runtime_capability_catalog(),
        ApprovalRegistry({"production_deploy"}),
        recorder,
    )

    result = controller.request(
        task_id="t2",
        capability_id="connector.invoke",
        reason="deployment requires a connector",
        expected_utility=1.0,
        action=ActionContext("production_deploy", reversible=False, remote=True),
    )

    assert result.ok
    assert result.value.expanded is False
    assert result.value.human_approval_required is True
    assert result.value.approval_category == "production_deploy"
    assert recorder.records[-1]["human_approval_required"] is True


def test_expansion_observation_is_separate_evidence_and_does_not_rewrite_prior_event():
    recorder = EvidenceRecorder()
    controller = CapabilityExpansionController(
        default_runtime_capability_catalog(),
        ApprovalRegistry(),
        recorder,
    )
    decision = controller.request(
        task_id="t3",
        capability_id="files.retrieve",
        reason="need source evidence",
        expected_utility=0.8,
        action=ActionContext("file_read", reversible=True),
    ).value

    observation = controller.observe(decision.event, result="retrieved", state=EvidenceState.OBSERVED)

    assert observation.evidence_state is EvidenceState.OBSERVED
    assert len(recorder.records) == 2
    assert recorder.records[0]["health"]["event"]["observed_result"] is None
    assert recorder.records[1]["capability"] == "capability-observation"
