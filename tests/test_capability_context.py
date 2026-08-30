from __future__ import annotations

from dataclasses import dataclass

from hermes_ultra.capability_context import (
    Capability,
    CapabilityContextOrchestrator,
    ContextBuilder,
    ContextItem,
    EscalationStep,
    RuleBasedCapabilityClassifier,
    TaskRequirements,
    TaskSpec,
    VerificationResult,
)
from hermes_ultra.contracts import CapabilityResult, FailureClass
from hermes_ultra.orchestrator import HermesUltraOrchestrator


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
        return CapabilityResult.success("subscription-router-selection")


class ModelExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, *, selection, task, context):
        self.calls.append(
            {"selection": selection, "task": task, "context": context}
        )
        return CapabilityResult.success(f"answer-{len(self.calls)}")


class Verifier:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def verify(self, *, task, response, context, requirements):
        self.calls.append(
            {
                "task": task,
                "response": response,
                "context": context,
                "requirements": requirements,
            }
        )
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


class ToolExecutor:
    def __init__(self, results):
        self.results = list(results)
        self.steps = []

    def execute(self, *, step, task, context, requirements):
        self.steps.append(step)
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


class MemoryWriter:
    def __init__(self):
        self.calls = []

    def write(self, *, task, requirements, context, selection, response, verification):
        self.calls.append(
            {
                "task": task,
                "requirements": requirements,
                "context": context,
                "selection": selection,
                "response": response,
                "verification": verification,
            }
        )
        return CapabilityResult.success(True)


@dataclass(frozen=True)
class DelegatedResult:
    task_id: str


class Delegate:
    def __init__(self):
        self.tasks = []

    def run(self, task):
        self.tasks.append(task)
        return CapabilityResult.success(DelegatedResult(task_id=task.task_id))


def accepted():
    return CapabilityResult.success(
        VerificationResult(
            accepted=True,
            evidence_sufficient=True,
            reason="verified",
        )
    )


def insufficient():
    return CapabilityResult.success(
        VerificationResult(
            accepted=False,
            evidence_sufficient=False,
            reason="need external evidence",
        )
    )


def test_classifier_combines_explicit_hints_without_provider_or_cost_policy():
    classifier = RuleBasedCapabilityClassifier()
    task = TaskSpec(
        task_id="task-1",
        objective="Investigate the attached material.",
        capability_hints=frozenset({"research", "files", "reasoning"}),
    )

    result = classifier.classify(task)

    assert result.ok
    assert result.value.required == frozenset(
        {Capability.REASONING, Capability.RESEARCH, Capability.FILES, Capability.TOOL_USE}
    )
    assert result.value.quality_first is True


def test_context_builder_prioritizes_relevant_items_inside_budget():
    builder = ContextBuilder(token_budget=30)
    task = TaskSpec(task_id="task-2", objective="Review")
    requirements = TaskRequirements(required=frozenset({Capability.REASONING}))
    items = (
        ContextItem(
            key="critical-evidence",
            content="critical",
            source="evidence",
            priority=100,
            token_estimate=12,
        ),
        ContextItem(
            key="stale-history",
            content="stale",
            source="memory",
            priority=1,
            token_estimate=25,
        ),
    )

    result = builder.build(task=task, requirements=requirements, items=items)

    assert result.ok
    assert "critical-evidence" in result.value.keys
    assert "stale-history" not in result.value.keys
    assert "stale-history" in result.value.dropped_keys
    assert result.value.estimated_tokens <= result.value.token_budget


def test_quality_first_router_remains_authority_and_success_writes_memory():
    router = Router()
    model = ModelExecutor()
    verifier = Verifier([accepted()])
    memory = MemoryWriter()
    orchestrator = CapabilityContextOrchestrator(
        router=router,
        model_executor=model,
        verifier=verifier,
        memory_writer=memory,
    )
    task = TaskSpec(task_id="task-3", objective="Explain the architecture")

    result = orchestrator.run(task)

    assert result.ok
    assert router.calls[0]["quality_first"] is True
    assert router.calls[0]["requirements"].quality_first is True
    assert model.calls[0]["selection"] == "subscription-router-selection"
    assert len(memory.calls) == 1
    assert memory.calls[0]["response"] == "answer-1"


def test_insufficient_research_evidence_escalates_to_search_then_reruns_model():
    router = Router()
    model = ModelExecutor()
    verifier = Verifier([insufficient(), accepted()])
    tools = ToolExecutor(
        [
            CapabilityResult.success(
                ContextItem(
                    key="search-result",
                    content="fresh source",
                    source="search",
                    priority=90,
                    token_estimate=8,
                )
            )
        ]
    )
    memory = MemoryWriter()
    orchestrator = CapabilityContextOrchestrator(
        router=router,
        model_executor=model,
        verifier=verifier,
        tool_executor=tools,
        memory_writer=memory,
    )
    task = TaskSpec(
        task_id="task-4",
        objective="Research the latest upstream behavior",
        capability_hints=frozenset({"research"}),
    )

    result = orchestrator.run(task)

    assert result.ok
    assert tools.steps == [EscalationStep.SEARCH]
    assert len(model.calls) == 2
    assert "search-result" in model.calls[-1]["context"].keys
    assert len(memory.calls) == 1


def test_recoverable_search_failure_falls_through_to_deep_research_automatically():
    verifier = Verifier([insufficient(), accepted()])
    tools = ToolExecutor(
        [
            CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                "search unavailable",
                recoverable=True,
            ),
            CapabilityResult.success(
                ContextItem(
                    key="deep-research-result",
                    content="deep result",
                    source="deep-research",
                    priority=95,
                    token_estimate=8,
                )
            ),
        ]
    )
    orchestrator = CapabilityContextOrchestrator(
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=verifier,
        tool_executor=tools,
    )
    task = TaskSpec(
        task_id="task-5",
        objective="Research a hard current question",
        capability_hints=frozenset({"research"}),
    )

    result = orchestrator.run(task)

    assert result.ok
    assert tools.steps == [EscalationStep.SEARCH, EscalationStep.DEEP_RESEARCH]
    assert result.value.attempted_steps == (
        EscalationStep.SEARCH,
        EscalationStep.DEEP_RESEARCH,
    )


def test_exhausted_evidence_path_returns_explicit_failure_instead_of_false_success():
    verifier = Verifier([insufficient()])
    tools = ToolExecutor(
        [
            CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                "all research routes unavailable",
                recoverable=True,
            )
        ]
    )
    orchestrator = CapabilityContextOrchestrator(
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=verifier,
        tool_executor=tools,
        max_escalations=1,
    )
    task = TaskSpec(
        task_id="task-6",
        objective="Research current facts",
        capability_hints=frozenset({"research"}),
    )

    result = orchestrator.run(task)

    assert result.ok is False
    assert result.failure_class == FailureClass.EVIDENCE_INCOMPLETE
    assert result.recoverable is True
    assert result.metadata["attempted_steps"] == ("search",)


def test_existing_hermes_orchestrator_delegates_generic_tasks_to_capability_context_layer():
    delegate = Delegate()
    outer = HermesUltraOrchestrator(capability_context=delegate)
    task = TaskSpec(task_id="task-7", objective="Do ordinary autonomous work")

    result = outer.run_task(task)

    assert result.ok
    assert result.value.task_id == "task-7"
    assert delegate.tasks == [task]
