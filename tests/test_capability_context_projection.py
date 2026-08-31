from __future__ import annotations

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.capability_context import (
    CapabilityContextOrchestrator,
    ContextItem,
    TaskSpec,
    VerificationResult,
)
from hermes_ultra.capability_expansion import CapabilityExpansionController
from hermes_ultra.capability_projection import CapabilityProjector, default_runtime_capability_catalog
from hermes_ultra.contracts import CapabilityResult
from hermes_ultra.evidence import EvidenceRecorder


class Router:
    def __init__(self):
        self.calls = []

    def select(self, *, task, requirements, context, quality_first):
        self.calls.append(
            {
                "task": task,
                "requirements": requirements,
                "context": context,
                "quality_first": quality_first,
            }
        )
        return CapabilityResult.success("omniroute-selection")


class ModelExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, *, selection, task, context):
        self.calls.append((selection, task, context))
        return CapabilityResult.success(f"answer-{len(self.calls)}")


class Verifier:
    def __init__(self, values):
        self.values = list(values)

    def verify(self, *, task, response, context, requirements):
        if len(self.values) == 1:
            return self.values[0]
        return self.values.pop(0)


class ToolExecutor:
    def __init__(self):
        self.steps = []

    def execute(self, *, step, task, context, requirements):
        self.steps.append(step.value)
        return CapabilityResult.success(
            ContextItem(
                key=f"tool-{step.value}",
                content="fresh evidence",
                source=step.value,
                token_estimate=4,
                priority=100,
            )
        )


def accepted():
    return CapabilityResult.success(
        VerificationResult(accepted=True, evidence_sufficient=True, reason="verified")
    )


def insufficient():
    return CapabilityResult.success(
        VerificationResult(
            accepted=False,
            evidence_sufficient=False,
            reason="need evidence",
        )
    )


def test_projection_is_advisory_metadata_and_router_remains_selection_authority():
    catalog = default_runtime_capability_catalog()
    router = Router()
    orchestrator = CapabilityContextOrchestrator(
        router=router,
        model_executor=ModelExecutor(),
        verifier=Verifier([accepted()]),
        capability_projector=CapabilityProjector(catalog, token_budget=16, max_projected=2),
    )

    result = orchestrator.run(
        TaskSpec(task_id="projection", objective="research current behavior")
    )

    assert result.ok
    metadata = result.value.requirements.advisory_metadata["capability_projection"]
    assert metadata["task_id"] == "projection"
    assert result.value.selection == "omniroute-selection"
    assert router.calls[0]["quality_first"] is True
    assert result.value.capability_projection is not None


def test_escalation_expands_capability_omitted_by_projection_without_approval_roundtrip():
    catalog = default_runtime_capability_catalog()
    recorder = EvidenceRecorder()
    expander = CapabilityExpansionController(
        catalog,
        ApprovalRegistry({"production_deploy"}),
        recorder,
    )
    tools = ToolExecutor()
    orchestrator = CapabilityContextOrchestrator(
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=Verifier([insufficient(), accepted()]),
        tool_executor=tools,
        capability_projector=CapabilityProjector(catalog, token_budget=8, max_projected=1),
        capability_expander=expander,
    )
    task = TaskSpec(
        task_id="expand",
        objective="research latest behavior",
        capability_hints=frozenset({"research.deep"}),
    )

    result = orchestrator.run(task)

    assert result.ok
    assert tools.steps == ["search"]
    assert any(row["capability"] == "capability-expansion" for row in recorder.records)
    assert "research.search" in result.value.capability_projection.included_ids
    assert all(row["human_approval_required"] is False for row in recorder.records)
