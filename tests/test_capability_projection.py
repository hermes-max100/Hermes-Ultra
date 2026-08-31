from __future__ import annotations

from dataclasses import dataclass

from hermes_ultra.capability_projection import (
    CapabilityCatalog,
    CapabilityProjector,
    ProjectionExclusionReason,
    RuntimeCapabilityDescriptor,
    default_runtime_capability_catalog,
)


@dataclass(frozen=True)
class Task:
    task_id: str
    objective: str
    capability_hints: frozenset[str] = frozenset()


def test_budget_prefers_summaries_before_losing_discoverability():
    catalog = CapabilityCatalog(
        (
            RuntimeCapabilityDescriptor(
                "research.search",
                "research",
                "Search current sources",
                match_terms=("research",),
                detail_token_estimate=20,
                summary_token_estimate=5,
            ),
            RuntimeCapabilityDescriptor(
                "files.retrieve",
                "files",
                "Read task files",
                match_terms=("file",),
                detail_token_estimate=20,
                summary_token_estimate=5,
            ),
        )
    )

    projection = CapabilityProjector(catalog, token_budget=5, max_projected=2).project(
        Task("t1", "research file")
    )

    assert len(projection.included) == 1
    assert projection.included[0].summary_only is True
    assert projection.discoverable_ids == frozenset({"research.search", "files.retrieve"})
    assert projection.excluded[0].reason is ProjectionExclusionReason.BEYOND_CONTEXT_BUDGET


def test_omitted_capability_can_be_added_immutably_on_demand():
    catalog = default_runtime_capability_catalog()
    projector = CapabilityProjector(catalog, token_budget=8, max_projected=1)
    projection = projector.project(Task("t2", "research current behavior"))

    expanded = projection.include_on_demand(
        catalog.require("connector.invoke"),
        expected_utility=0.95,
        reason="needed after discovery",
    )

    assert "connector.invoke" not in projection.included_ids
    assert "connector.invoke" in expanded.included_ids
    assert "connector.invoke" in projection.discoverable_ids
    assert expanded.included[-1].match_reason == "needed after discovery"


def test_unavailable_capability_is_discoverable_with_explicit_reason():
    catalog = CapabilityCatalog(
        (
            RuntimeCapabilityDescriptor(
                "vision.inspect",
                "vision",
                "Inspect an image",
                available=False,
            ),
        )
    )

    projection = CapabilityProjector(catalog, token_budget=64).project(Task("t3", "inspect image"))

    assert projection.included == ()
    assert projection.discoverable_ids == frozenset({"vision.inspect"})
    assert projection.excluded[0].reason is ProjectionExclusionReason.UNAVAILABLE_IN_CURRENT_RUNTIME


def test_router_metadata_is_machine_readable_and_does_not_encode_authority_denial():
    projection = CapabilityProjector(
        default_runtime_capability_catalog(), token_budget=16, max_projected=2
    ).project(Task("t4", "research current sources"))

    metadata = projection.to_router_metadata()

    assert metadata["task_id"] == "t4"
    assert metadata["discoverable_ids"] == sorted(projection.discoverable_ids)
    assert "authorized" not in metadata
    assert "denied" not in metadata
