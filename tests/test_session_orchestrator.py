from __future__ import annotations

from pathlib import Path

from hermes_ultra.capability_context import (
    CapabilityContextOrchestrator,
    ContextItem,
    TaskSpec,
    VerificationResult,
)
from hermes_ultra.contracts import CapabilityResult
from hermes_ultra.session_environment import SessionEnvironment
from hermes_ultra.session_orchestrator import SessionAwareCapabilityContextOrchestrator


class Router:
    def select(self, **kwargs):
        return CapabilityResult.success("model")


class ModelExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return CapabilityResult.success({"answer": self.calls})


class AcceptingVerifier:
    def verify(self, **kwargs):
        return CapabilityResult.success(
            VerificationResult(accepted=True, evidence_sufficient=True, reason="verified")
        )


class EscalatingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return CapabilityResult.success(
                VerificationResult(
                    accepted=False,
                    evidence_sufficient=False,
                    reason="need evidence",
                )
            )
        return CapabilityResult.success(
            VerificationResult(accepted=True, evidence_sufficient=True, reason="verified")
        )


class Source:
    def retrieve(self, **kwargs):
        return CapabilityResult.success(
            (ContextItem("source-1", "source evidence", "fixture-source", priority=80),)
        )


class ToolExecutor:
    def execute(self, *, step, **kwargs):
        return CapabilityResult.success(
            ContextItem(
                "tool-1",
                f"tool evidence from {step.value}",
                "fixture-tool",
                priority=90,
            )
        )


def test_existing_orchestrator_behavior_remains_unchanged_without_session_adapter():
    orchestrator = CapabilityContextOrchestrator(
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=AcceptingVerifier(),
    )

    result = orchestrator.run(TaskSpec("plain", "answer this question"))

    assert result.ok is True
    assert result.value is not None
    assert result.value.response == {"answer": 1}


def test_session_aware_orchestrator_records_task_source_tool_and_outcome(tmp_path: Path):
    environment = SessionEnvironment(tmp_path, task_id="session-task")
    orchestrator = SessionAwareCapabilityContextOrchestrator(
        session_environment=environment,
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=EscalatingVerifier(),
        context_sources=(Source(),),
        tool_executor=ToolExecutor(),
    )

    result = orchestrator.run(TaskSpec("session-task", "research current evidence"))

    assert result.ok is True
    events = environment.events()
    assert tuple(event.event_type for event in events) == (
        "task",
        "context_source",
        "tool_result",
        "outcome",
    )
    assert environment.load_payload(events[0].payload_ref)["objective"] == "research current evidence"
    assert environment.load_payload(events[1].payload_ref)["content"] == "source evidence"
    assert environment.load_payload(events[2].payload_ref)["source"] == "fixture-tool"
    assert environment.load_payload(events[3].payload_ref)["accepted"] is True
    assert events[2].metadata["step"] == "search"


def test_repeated_run_initializes_task_session_only_once(tmp_path: Path):
    environment = SessionEnvironment(tmp_path, task_id="repeat-task")
    orchestrator = SessionAwareCapabilityContextOrchestrator(
        session_environment=environment,
        router=Router(),
        model_executor=ModelExecutor(),
        verifier=AcceptingVerifier(),
    )
    task = TaskSpec("repeat-task", "answer this question")

    first = orchestrator.run(task)
    second = orchestrator.run(task)

    assert first.ok is True
    assert second.ok is True
    events = environment.events()
    assert tuple(event.event_type for event in events) == ("task", "outcome", "outcome")
    assert sum(event.event_type == "task" for event in events) == 1


def test_session_aware_orchestrator_rejects_task_session_mismatch_without_running(tmp_path: Path):
    environment = SessionEnvironment(tmp_path, task_id="expected-task")
    executor = ModelExecutor()
    orchestrator = SessionAwareCapabilityContextOrchestrator(
        session_environment=environment,
        router=Router(),
        model_executor=executor,
        verifier=AcceptingVerifier(),
    )

    result = orchestrator.run(TaskSpec("other-task", "answer this question"))

    assert result.ok is False
    assert executor.calls == 0
    assert environment.events() == ()
