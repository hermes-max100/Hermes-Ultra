from __future__ import annotations

from dataclasses import dataclass

from hermes_ultra.autonomy import ActionContext, ApprovalRegistry
from hermes_ultra.capability_expansion import CapabilityExpansionController
from hermes_ultra.capability_projection import (
    CapabilityCatalog,
    CapabilityProjector,
    RuntimeCapabilityDescriptor,
)
from hermes_ultra.contracts import CapabilityResult, FailureClass
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.progressive_capabilities import ProgressiveCapabilityRuntime


@dataclass(frozen=True)
class Task:
    task_id: str
    objective: str
    capability_hints: frozenset[str] = frozenset()


class RecordingExecutor:
    def __init__(self, result: CapabilityResult[object] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.result = result or CapabilityResult.success({"status": "ok"})

    def execute(self, *, capability_id: str, arguments: dict[str, object]) -> CapabilityResult[object]:
        self.calls.append((capability_id, dict(arguments)))
        return self.result


def _catalog(*, connector_available: bool = True) -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            RuntimeCapabilityDescriptor(
                "research.search",
                "research",
                "Search current sources",
                match_terms=("research", "search", "current"),
                base_utility=0.4,
                detail_token_estimate=20,
                summary_token_estimate=5,
            ),
            RuntimeCapabilityDescriptor(
                "connector.invoke",
                "connectors",
                "Invoke an already-governed connector capability",
                match_terms=("connector", "calendar", "gmail"),
                base_utility=0.3,
                available=connector_available,
                detail_token_estimate=20,
                summary_token_estimate=5,
                provenance=(("registry", "governed"),),
            ),
        )
    )


def _runtime(
    catalog: CapabilityCatalog,
    executor: RecordingExecutor,
) -> ProgressiveCapabilityRuntime:
    expansion = CapabilityExpansionController(
        catalog,
        ApprovalRegistry({"production_deploy", "spend_money"}),
        EvidenceRecorder(),
    )
    return ProgressiveCapabilityRuntime(
        catalog,
        executor=executor,
        expansion_controller=expansion,
    )


def test_discover_is_bounded_but_preserves_full_catalog_discoverability():
    runtime = _runtime(_catalog(), RecordingExecutor())

    result = runtime.discover(
        task=Task("t1", "research current sources and calendar"),
        query="calendar connector",
        limit=1,
    )

    assert result.ok is True
    assert result.value is not None
    assert len(result.value.hits) == 1
    assert result.value.hits[0].capability_id == "connector.invoke"
    assert result.value.catalog_size == 2
    assert result.value.discoverable_ids == frozenset({"research.search", "connector.invoke"})


def test_describe_returns_full_descriptor_without_granting_authority():
    runtime = _runtime(_catalog(connector_available=False), RecordingExecutor())

    result = runtime.describe("connector.invoke")

    assert result.ok is True
    assert result.value is not None
    assert result.value.descriptor.capability_id == "connector.invoke"
    assert result.value.descriptor.match_terms == ("connector", "calendar", "gmail")
    assert result.value.dispatchable is False
    assert result.value.descriptor.provenance == (("registry", "governed"),)


def test_unknown_capability_does_not_call_executor():
    executor = RecordingExecutor()
    runtime = _runtime(_catalog(), executor)

    result = runtime.dispatch(
        task_id="t3",
        capability_id="missing.capability",
        arguments={},
        action=ActionContext("ordinary_work", reversible=True),
        reason="needed",
        expected_utility=0.8,
    )

    assert result.ok is False
    assert result.failure_class is FailureClass.DEPENDENCY_MISSING
    assert executor.calls == []


def test_unavailable_capability_is_discoverable_but_not_dispatchable():
    executor = RecordingExecutor()
    runtime = _runtime(_catalog(connector_available=False), executor)

    result = runtime.dispatch(
        task_id="t4",
        capability_id="connector.invoke",
        arguments={"operation": "calendar.read"},
        action=ActionContext("calendar_read", reversible=True, remote=True),
        reason="need calendar evidence",
        expected_utility=0.9,
    )

    assert result.ok is False
    assert result.failure_class is FailureClass.AUTHORITY_REQUIRED
    assert result.recoverable is True
    assert executor.calls == []


def test_omitted_reversible_capability_expands_autonomously_and_executes():
    catalog = _catalog()
    executor = RecordingExecutor(CapabilityResult.success({"events": 2}))
    runtime = _runtime(catalog, executor)
    projection = CapabilityProjector(catalog, token_budget=5, max_projected=1).project(
        Task("t5", "research current sources")
    )
    assert "connector.invoke" not in projection.included_ids

    result = runtime.dispatch(
        task_id="t5",
        capability_id="connector.invoke",
        arguments={"operation": "calendar.read"},
        action=ActionContext("calendar_read", reversible=True, remote=True),
        reason="need calendar evidence",
        expected_utility=0.95,
        projection=projection,
    )

    assert result.ok is True
    assert result.value is not None
    assert result.value.value == {"events": 2}
    assert result.value.projection is not None
    assert result.value.projection.contains("connector.invoke") is True
    assert result.value.expansion is not None
    assert result.value.expansion.expanded is True
    assert executor.calls == [("connector.invoke", {"operation": "calendar.read"})]


def test_consequential_expansion_boundary_does_not_execute():
    catalog = _catalog()
    executor = RecordingExecutor()
    runtime = _runtime(catalog, executor)
    projection = CapabilityProjector(catalog, token_budget=5, max_projected=1).project(
        Task("t6", "research current sources")
    )

    result = runtime.dispatch(
        task_id="t6",
        capability_id="connector.invoke",
        arguments={"operation": "production.delete"},
        action=ActionContext(
            "production_deploy",
            reversible=False,
            remote=True,
            destructive=True,
            external_irreversible_effect=True,
        ),
        reason="deploy production",
        expected_utility=0.99,
        projection=projection,
    )

    assert result.ok is False
    assert result.failure_class is FailureClass.AUTHORITY_REQUIRED
    assert result.recoverable is True
    assert executor.calls == []


def test_dispatch_preserves_executor_failure_semantics():
    executor_failure = CapabilityResult.failure(
        FailureClass.UPSTREAM_UNAVAILABLE,
        "provider offline",
        recoverable=True,
        metadata={"provider": "example"},
    )
    executor = RecordingExecutor(executor_failure)
    runtime = _runtime(_catalog(), executor)

    result = runtime.dispatch(
        task_id="t7",
        capability_id="research.search",
        arguments={"query": "latest"},
        action=ActionContext("research_search", reversible=True, remote=True),
        reason="research",
        expected_utility=0.9,
    )

    assert result.ok is False
    assert result.failure_class is FailureClass.UPSTREAM_UNAVAILABLE
    assert result.message == "provider offline"
    assert result.recoverable is True
    assert result.metadata == {"provider": "example"}
