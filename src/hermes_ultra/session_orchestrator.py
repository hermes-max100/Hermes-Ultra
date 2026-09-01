from __future__ import annotations

from enum import Enum
from typing import Sequence

from .capability_context import (
    CapabilityContextOrchestrator,
    ContextItem,
    TaskSpec,
)
from .contracts import CapabilityResult, FailureClass
from .session_environment import SessionEnvironment


def _context_payload(item: ContextItem) -> dict[str, object]:
    return {
        "key": item.key,
        "content": item.content,
        "source": item.source,
        "priority": item.priority,
        "token_estimate": item.token_estimate,
    }


def _normalize_items(value: object) -> tuple[ContextItem, ...]:
    if isinstance(value, ContextItem):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = tuple(value)
        if all(isinstance(item, ContextItem) for item in items):
            return items
    return ()


def _hint_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class _RecordingContextSource:
    def __init__(self, source: object, environment: SessionEnvironment) -> None:
        self.source = source
        self.environment = environment

    def retrieve(self, *, task, requirements):
        result = self.source.retrieve(task=task, requirements=requirements)
        if isinstance(result, CapabilityResult) and result.ok:
            for item in _normalize_items(result.value):
                self.environment.append(
                    "context_source",
                    _context_payload(item),
                    metadata={"source_adapter": type(self.source).__name__},
                )
        return result


class _RecordingToolExecutor:
    def __init__(self, executor: object, environment: SessionEnvironment) -> None:
        self.executor = executor
        self.environment = environment

    def execute(self, *, step, task, context, requirements):
        result = self.executor.execute(
            step=step,
            task=task,
            context=context,
            requirements=requirements,
        )
        if isinstance(result, CapabilityResult) and result.ok:
            for item in _normalize_items(result.value):
                self.environment.append(
                    "tool_result",
                    _context_payload(item),
                    metadata={
                        "step": step.value,
                        "tool_executor": type(self.executor).__name__,
                    },
                )
        return result


class _RecordingVerifier:
    def __init__(self, verifier: object, environment: SessionEnvironment) -> None:
        self.verifier = verifier
        self.environment = environment

    def verify(self, *, task, response, context, requirements):
        result = self.verifier.verify(
            task=task,
            response=response,
            context=context,
            requirements=requirements,
        )
        if isinstance(result, CapabilityResult) and result.ok and result.value is not None:
            verification = result.value
            if bool(getattr(verification, "accepted", False)):
                self.environment.append(
                    "outcome",
                    {
                        "accepted": bool(verification.accepted),
                        "evidence_sufficient": bool(verification.evidence_sufficient),
                        "reason": str(verification.reason),
                        "metadata": dict(verification.metadata),
                        "response": response,
                    },
                    metadata={"verifier": type(self.verifier).__name__},
                )
        return result


class SessionAwareCapabilityContextOrchestrator(CapabilityContextOrchestrator):
    """Record durable session context around the existing Hermes orchestrator.

    The base orchestrator remains authoritative for classification, routing,
    escalation, capability expansion, approval boundaries, verification, and
    memory writes. This adapter only records task/context/tool/outcome events in
    a rebuildable SessionEnvironment.
    """

    def __init__(
        self,
        *,
        session_environment: SessionEnvironment,
        verifier,
        context_sources: Sequence[object] = (),
        tool_executor=None,
        **kwargs,
    ) -> None:
        self.session_environment = session_environment
        wrapped_sources = tuple(
            _RecordingContextSource(source, session_environment)
            for source in context_sources
        )
        wrapped_tool_executor = (
            None
            if tool_executor is None
            else _RecordingToolExecutor(tool_executor, session_environment)
        )
        super().__init__(
            verifier=_RecordingVerifier(verifier, session_environment),
            context_sources=wrapped_sources,
            tool_executor=wrapped_tool_executor,
            **kwargs,
        )

    def run(self, task: TaskSpec):
        if str(task.task_id) != self.session_environment.task_id:
            return CapabilityResult.failure(
                FailureClass.ADAPTER_REJECTED,
                "task_id does not match the bound session environment",
                recoverable=True,
                metadata={
                    "task_id": str(task.task_id),
                    "session_task_id": self.session_environment.task_id,
                },
            )

        self.session_environment.append(
            "task",
            {
                "task_id": str(task.task_id),
                "objective": task.objective,
                "capability_hints": sorted(_hint_value(hint) for hint in task.capability_hints),
                "metadata": dict(task.metadata),
            },
        )
        return super().run(task)
