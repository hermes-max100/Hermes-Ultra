from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .autonomy import ActionContext
from .capability_projection import CapabilityProjection
from .contracts import CapabilityResult, FailureClass


class Capability(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    RESEARCH = "research"
    LONG_CONTEXT = "long_context"
    VISION = "vision"
    AUDIO = "audio"
    TOOL_USE = "tool_use"
    SPEED = "speed"
    FILES = "files"
    COMPUTE = "compute"
    CONNECTORS = "connectors"
    SPECIALIST = "specialist"


class EscalationStep(str, Enum):
    FILE_RETRIEVAL = "file_retrieval"
    SEARCH = "search"
    DEEP_RESEARCH = "deep_research"
    CODE_EXECUTION = "code_execution"
    CONNECTOR = "connector"
    SPECIALIST = "specialist"


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    objective: str
    capability_hints: frozenset[str | Capability] = frozenset()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskRequirements:
    required: frozenset[Capability]
    preferred: frozenset[Capability] = frozenset()
    quality_first: bool = True
    advisory_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextItem:
    key: str
    content: str
    source: str
    priority: int = 50
    token_estimate: int | None = None

    @property
    def estimated_tokens(self) -> int:
        if self.token_estimate is not None:
            return max(1, self.token_estimate)
        return max(1, (len(self.content) + 3) // 4)


@dataclass(frozen=True)
class ContextBundle:
    items: tuple[ContextItem, ...]
    dropped_keys: tuple[str, ...]
    estimated_tokens: int
    token_budget: int

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.items)


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    evidence_sufficient: bool
    reason: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OrchestrationResult:
    task_id: str
    response: object
    selection: object
    requirements: TaskRequirements
    context: ContextBundle
    verification: VerificationResult
    attempted_steps: tuple[EscalationStep, ...] = ()
    memory_written: bool = False
    capability_projection: CapabilityProjection | None = None


class RuleBasedCapabilityClassifier:
    """Deterministic baseline classifier; external classifiers may be injected."""

    _HINTS = {
        capability.value: capability
        for capability in Capability
    }

    _KEYWORDS = {
        Capability.CODING: (
            "code",
            "coding",
            "repository",
            "repo",
            "bug",
            "test",
            "implement",
            "refactor",
        ),
        Capability.RESEARCH: (
            "research",
            "latest",
            "current",
            "search",
            "web",
            "source",
        ),
        Capability.FILES: (
            "attached",
            "attachment",
            "file",
            "document",
            "pdf",
            "spreadsheet",
        ),
        Capability.VISION: ("image", "photo", "screenshot", "vision"),
        Capability.AUDIO: ("audio", "voice", "speech", "transcript"),
        Capability.COMPUTE: ("calculate", "compute", "python", "numerical"),
        Capability.CONNECTORS: (
            "gmail",
            "calendar",
            "drive",
            "slack",
            "github",
            "notion",
        ),
        Capability.SPECIALIST: ("legal", "medical", "tax", "security"),
    }

    _TOOL_CAPABILITIES = frozenset(
        {
            Capability.CODING,
            Capability.RESEARCH,
            Capability.FILES,
            Capability.VISION,
            Capability.AUDIO,
            Capability.COMPUTE,
            Capability.CONNECTORS,
            Capability.SPECIALIST,
        }
    )

    def classify(self, task: TaskSpec) -> CapabilityResult[TaskRequirements]:
        required: set[Capability] = {Capability.REASONING}

        for hint in task.capability_hints:
            if isinstance(hint, Capability):
                required.add(hint)
                continue
            normalized = str(hint).strip().lower().replace("-", "_")
            capability = self._HINTS.get(normalized)
            if capability is not None:
                required.add(capability)

        text = task.objective.lower()
        for capability, needles in self._KEYWORDS.items():
            if any(needle in text for needle in needles):
                required.add(capability)

        if bool(task.metadata.get("long_context")) or len(task.objective) >= 12_000:
            required.add(Capability.LONG_CONTEXT)

        if required.intersection(self._TOOL_CAPABILITIES):
            required.add(Capability.TOOL_USE)

        preferred: set[Capability] = set()
        if bool(task.metadata.get("latency_sensitive")):
            preferred.add(Capability.SPEED)

        return CapabilityResult.success(
            TaskRequirements(
                required=frozenset(required),
                preferred=frozenset(preferred),
                quality_first=True,
            )
        )


class ContextBuilder:
    """Builds the smallest high-value context that fits the configured budget."""

    def __init__(self, *, token_budget: int = 16_000) -> None:
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        self.token_budget = token_budget

    def build(
        self,
        *,
        task: TaskSpec,
        requirements: TaskRequirements,
        items: Sequence[ContextItem] = (),
    ) -> CapabilityResult[ContextBundle]:
        del requirements

        task_item = ContextItem(
            key="__task__",
            content=task.objective,
            source="task",
            priority=1_000_000,
        )
        effective_budget = max(self.token_budget, task_item.estimated_tokens)
        selected = [task_item]
        used = task_item.estimated_tokens

        deduplicated: dict[str, ContextItem] = {}
        for item in items:
            if item.key == "__task__":
                continue
            existing = deduplicated.get(item.key)
            if existing is None or item.priority > existing.priority:
                deduplicated[item.key] = item

        dropped: list[str] = []
        for item in sorted(
            deduplicated.values(),
            key=lambda candidate: (-candidate.priority, candidate.key),
        ):
            estimate = item.estimated_tokens
            if used + estimate <= effective_budget:
                selected.append(item)
                used += estimate
            else:
                dropped.append(item.key)

        return CapabilityResult.success(
            ContextBundle(
                items=tuple(selected),
                dropped_keys=tuple(dropped),
                estimated_tokens=used,
                token_budget=effective_budget,
            )
        )


class ToolEscalationPolicy:
    """Deterministic tool escalation; model/provider choice stays outside this policy."""

    def ordered_steps(self, requirements: TaskRequirements) -> tuple[EscalationStep, ...]:
        required = requirements.required
        steps: list[EscalationStep] = []

        if Capability.FILES in required:
            steps.append(EscalationStep.FILE_RETRIEVAL)
        if Capability.RESEARCH in required:
            steps.extend((EscalationStep.SEARCH, EscalationStep.DEEP_RESEARCH))
        if Capability.CODING in required or Capability.COMPUTE in required:
            steps.append(EscalationStep.CODE_EXECUTION)
        if Capability.CONNECTORS in required:
            steps.append(EscalationStep.CONNECTOR)
        if Capability.SPECIALIST in required:
            steps.append(EscalationStep.SPECIALIST)

        return tuple(dict.fromkeys(steps))

    def next_step(
        self,
        requirements: TaskRequirements,
        attempted: Iterable[EscalationStep],
    ) -> EscalationStep | None:
        attempted_set = set(attempted)
        for step in self.ordered_steps(requirements):
            if step not in attempted_set:
                return step
        return None


class CapabilityContextOrchestrator:
    """Capability/context layer above the existing Hermes model router.

    This class deliberately owns no provider ranking, pricing policy, or approval
    registry. It asks the injected router to select the model and only escalates
    tools when verification says the current answer lacks evidence. Capability
    projection is advisory context metadata, never a replacement authority.
    """

    _STEP_CAPABILITIES = {
        EscalationStep.FILE_RETRIEVAL: "files.retrieve",
        EscalationStep.SEARCH: "research.search",
        EscalationStep.DEEP_RESEARCH: "research.deep",
        EscalationStep.CODE_EXECUTION: "compute.execute",
        EscalationStep.CONNECTOR: "connector.invoke",
        EscalationStep.SPECIALIST: "specialist.delegate",
    }

    _STEP_ACTIONS = {
        EscalationStep.FILE_RETRIEVAL: ActionContext("file_retrieval", reversible=True),
        EscalationStep.SEARCH: ActionContext("research_search", reversible=True, remote=True),
        EscalationStep.DEEP_RESEARCH: ActionContext("deep_research", reversible=True, remote=True),
        EscalationStep.CODE_EXECUTION: ActionContext("code_execution", reversible=True),
        EscalationStep.CONNECTOR: ActionContext("connector_invoke", reversible=True, remote=True),
        EscalationStep.SPECIALIST: ActionContext("specialist_delegate", reversible=True, remote=True),
    }

    def __init__(
        self,
        *,
        router,
        model_executor,
        verifier,
        classifier=None,
        context_builder: ContextBuilder | None = None,
        context_sources: Sequence[object] = (),
        tool_executor=None,
        escalation_policy: ToolEscalationPolicy | None = None,
        memory_writer=None,
        capability_projector=None,
        capability_expander=None,
        max_escalations: int = 6,
    ) -> None:
        if max_escalations < 0:
            raise ValueError("max_escalations must be >= 0")
        self.router = router
        self.model_executor = model_executor
        self.verifier = verifier
        self.classifier = classifier or RuleBasedCapabilityClassifier()
        self.context_builder = context_builder or ContextBuilder()
        self.context_sources = tuple(context_sources)
        self.tool_executor = tool_executor
        self.escalation_policy = escalation_policy or ToolEscalationPolicy()
        self.memory_writer = memory_writer
        self.capability_projector = capability_projector
        self.capability_expander = capability_expander
        self.max_escalations = max_escalations

    @staticmethod
    def _with_projection_metadata(
        requirements: TaskRequirements,
        projection: CapabilityProjection | None,
    ) -> TaskRequirements:
        if projection is None:
            return requirements
        metadata = dict(requirements.advisory_metadata)
        metadata["capability_projection"] = projection.to_router_metadata()
        return replace(requirements, advisory_metadata=metadata)

    @staticmethod
    def _normalize_items(value: object) -> tuple[ContextItem, ...]:
        if isinstance(value, ContextItem):
            return (value,)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items = tuple(value)
            if all(isinstance(item, ContextItem) for item in items):
                return items
        return ()

    def _source_items(
        self,
        *,
        task: TaskSpec,
        requirements: TaskRequirements,
    ) -> CapabilityResult[tuple[ContextItem, ...]]:
        collected: list[ContextItem] = []
        source_failures: list[Mapping[str, object]] = []

        for source in self.context_sources:
            result = source.retrieve(task=task, requirements=requirements)
            if not isinstance(result, CapabilityResult):
                source_failures.append(
                    {
                        "source": type(source).__name__,
                        "failure_class": FailureClass.UNKNOWN.value,
                        "message": "context source returned a non-CapabilityResult",
                    }
                )
                continue
            if result.ok:
                collected.extend(self._normalize_items(result.value))
                continue
            if result.recoverable:
                source_failures.append(
                    {
                        "source": type(source).__name__,
                        "failure_class": (
                            result.failure_class.value
                            if result.failure_class is not None
                            else FailureClass.UNKNOWN.value
                        ),
                        "message": result.message,
                    }
                )
                continue
            return CapabilityResult.failure(
                result.failure_class or FailureClass.UNKNOWN,
                result.message,
                recoverable=False,
                metadata={"source": type(source).__name__},
            )

        return CapabilityResult.success(
            tuple(collected),
            metadata={"recoverable_source_failures": tuple(source_failures)},
        )

    def _failure(
        self,
        message: str,
        *,
        attempted: Sequence[EscalationStep],
        metadata: Mapping[str, object] | None = None,
    ) -> CapabilityResult[OrchestrationResult]:
        details = dict(metadata or {})
        details["attempted_steps"] = tuple(step.value for step in attempted)
        return CapabilityResult.failure(
            FailureClass.EVIDENCE_INCOMPLETE,
            message,
            recoverable=True,
            metadata=details,
        )

    def run(self, task: TaskSpec) -> CapabilityResult[OrchestrationResult]:
        classified = self.classifier.classify(task)
        if not classified.ok or classified.value is None:
            return CapabilityResult.failure(
                classified.failure_class or FailureClass.UNKNOWN,
                classified.message or "capability classification failed",
                recoverable=classified.recoverable,
                metadata=classified.metadata,
            )
        requirements = classified.value
        projection: CapabilityProjection | None = None
        if self.capability_projector is not None:
            projection = self.capability_projector.project(task)
            requirements = self._with_projection_metadata(requirements, projection)

        source_result = self._source_items(task=task, requirements=requirements)
        if not source_result.ok or source_result.value is None:
            return CapabilityResult.failure(
                source_result.failure_class or FailureClass.UNKNOWN,
                source_result.message,
                recoverable=source_result.recoverable,
                metadata=source_result.metadata,
            )

        context_items = list(source_result.value)
        attempted: list[EscalationStep] = []
        authorization_boundaries: list[Mapping[str, object]] = []

        while True:
            context_result = self.context_builder.build(
                task=task,
                requirements=requirements,
                items=tuple(context_items),
            )
            if not context_result.ok or context_result.value is None:
                return CapabilityResult.failure(
                    context_result.failure_class or FailureClass.UNKNOWN,
                    context_result.message or "context assembly failed",
                    recoverable=context_result.recoverable,
                    metadata=context_result.metadata,
                )
            context = context_result.value

            selection_result = self.router.select(
                task=task,
                requirements=requirements,
                context=context,
                quality_first=requirements.quality_first,
            )
            if not selection_result.ok or selection_result.value is None:
                return CapabilityResult.failure(
                    selection_result.failure_class or FailureClass.UPSTREAM_UNAVAILABLE,
                    selection_result.message or "existing Hermes router failed to select a model",
                    recoverable=selection_result.recoverable,
                    metadata=selection_result.metadata,
                )
            selection = selection_result.value

            response_result = self.model_executor.execute(
                selection=selection,
                task=task,
                context=context,
            )
            if not response_result.ok or response_result.value is None:
                return CapabilityResult.failure(
                    response_result.failure_class or FailureClass.UPSTREAM_UNAVAILABLE,
                    response_result.message or "model execution failed",
                    recoverable=response_result.recoverable,
                    metadata=response_result.metadata,
                )
            response = response_result.value

            verification_result = self.verifier.verify(
                task=task,
                response=response,
                context=context,
                requirements=requirements,
            )
            if not verification_result.ok or verification_result.value is None:
                return CapabilityResult.failure(
                    verification_result.failure_class or FailureClass.EVIDENCE_INCOMPLETE,
                    verification_result.message or "verification failed",
                    recoverable=verification_result.recoverable,
                    metadata=verification_result.metadata,
                )
            verification = verification_result.value

            if verification.accepted:
                memory_written = False
                memory_metadata: dict[str, object] = {}
                if self.memory_writer is not None:
                    memory_result = self.memory_writer.write(
                        task=task,
                        requirements=requirements,
                        context=context,
                        selection=selection,
                        response=response,
                        verification=verification,
                    )
                    if isinstance(memory_result, CapabilityResult):
                        memory_written = bool(memory_result.ok)
                        if not memory_result.ok:
                            memory_metadata = {
                                "memory_write_failure": memory_result.failure_class.value
                                if memory_result.failure_class is not None
                                else FailureClass.UNKNOWN.value,
                                "memory_write_message": memory_result.message,
                            }
                    else:
                        memory_written = bool(memory_result)

                return CapabilityResult.success(
                    OrchestrationResult(
                        task_id=task.task_id,
                        response=response,
                        selection=selection,
                        requirements=requirements,
                        context=context,
                        verification=verification,
                        attempted_steps=tuple(attempted),
                        memory_written=memory_written,
                        capability_projection=projection,
                    ),
                    metadata={
                        "context_dropped_keys": context.dropped_keys,
                        "recoverable_source_failures": source_result.metadata.get(
                            "recoverable_source_failures", ()
                        ),
                        **memory_metadata,
                    },
                )

            if verification.evidence_sufficient:
                return self._failure(
                    verification.reason or "verification rejected the answer",
                    attempted=attempted,
                    metadata={"verification_metadata": dict(verification.metadata)},
                )

            tool_succeeded = False
            while len(attempted) < self.max_escalations:
                step = self.escalation_policy.next_step(requirements, attempted)
                if step is None:
                    break
                attempted.append(step)

                if self.tool_executor is None:
                    break

                capability_id = self._STEP_CAPABILITIES[step]
                if (
                    projection is not None
                    and self.capability_expander is not None
                    and not projection.contains(capability_id)
                ):
                    expansion_result = self.capability_expander.request(
                        task_id=task.task_id,
                        capability_id=capability_id,
                        reason=f"evidence escalation requires {step.value}",
                        expected_utility=0.9,
                        action=self._STEP_ACTIONS[step],
                    )
                    if not isinstance(expansion_result, CapabilityResult):
                        continue
                    if not expansion_result.ok or expansion_result.value is None:
                        if expansion_result.recoverable:
                            continue
                        return CapabilityResult.failure(
                            expansion_result.failure_class or FailureClass.UNKNOWN,
                            expansion_result.message or "capability expansion failed",
                            recoverable=False,
                            metadata={
                                **dict(expansion_result.metadata),
                                "attempted_steps": tuple(item.value for item in attempted),
                            },
                        )
                    expansion = expansion_result.value
                    if not expansion.expanded:
                        authorization_boundaries.append(
                            {
                                "step": step.value,
                                "capability_id": capability_id,
                                "approval_category": expansion.approval_category,
                                "reason": expansion.reason,
                            }
                        )
                        continue
                    descriptor = self.capability_expander.catalog.require(capability_id)
                    projection = projection.include_on_demand(
                        descriptor,
                        expected_utility=0.9,
                        reason=f"escalation:{step.value}",
                    )
                    requirements = self._with_projection_metadata(requirements, projection)

                tool_result = self.tool_executor.execute(
                    step=step,
                    task=task,
                    context=context,
                    requirements=requirements,
                )
                if not isinstance(tool_result, CapabilityResult):
                    continue
                if tool_result.ok:
                    new_items = self._normalize_items(tool_result.value)
                    if new_items:
                        context_items.extend(new_items)
                        tool_succeeded = True
                        break
                    continue
                if tool_result.recoverable:
                    continue
                return CapabilityResult.failure(
                    tool_result.failure_class or FailureClass.UNKNOWN,
                    tool_result.message,
                    recoverable=False,
                    metadata={
                        **dict(tool_result.metadata),
                        "attempted_steps": tuple(step.value for step in attempted),
                    },
                )

            if tool_succeeded:
                continue

            return self._failure(
                verification.reason or "evidence remained insufficient after tool escalation",
                attempted=attempted,
                metadata={
                    "authorization_boundaries": tuple(authorization_boundaries),
                } if authorization_boundaries else None,
            )
