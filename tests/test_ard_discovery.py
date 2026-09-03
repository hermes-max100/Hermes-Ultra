from __future__ import annotations

import pytest

from hermes_ultra.ard_discovery import ArdCatalogError, ArdCatalogLoader
from hermes_ultra.skill_lifecycle import LifecycleState, Provenance


def test_ard_catalog_normalizes_to_discovered_candidate_only() -> None:
    catalog = ArdCatalogLoader().load(
        {
            "entries": [
                {
                    "identifier": "urn:air:example.com:skills:debugger",
                    "displayName": "Portable Debugger",
                    "type": "application/agent-skills+zip",
                    "url": "https://example.com/debugger.zip",
                    "capabilities": ["debugging", "test-analysis"],
                }
            ]
        }
    )

    candidate = ArdCatalogLoader().to_candidate(
        catalog.entries[0],
        provenance=Provenance(
            repository="https://github.com/example/registry",
            commit_sha="a" * 40,
            license="Apache-2.0",
            discovered_from="ard:github-agent-finder",
        ),
    )

    assert candidate.candidate_id == "ard:urn:air:example.com:skills:debugger"
    assert candidate.name == "Portable Debugger"
    assert candidate.state is LifecycleState.DISCOVERED
    assert candidate.authority.network is True
    assert candidate.authority.consequential is False
    assert candidate.capability.capability_id == "urn:air:example.com:skills:debugger"
    assert candidate.capability.capabilities == frozenset({"debugging", "test-analysis"})


def test_ard_catalog_rejects_non_air_resource_identifier() -> None:
    with pytest.raises(ArdCatalogError, match="identifier"):
        ArdCatalogLoader().load(
            {
                "entries": [
                    {
                        "identifier": "urn:ai:example.com:skills:debugger",
                        "displayName": "Portable Debugger",
                        "type": "application/agent-skills+zip",
                        "url": "https://example.com/debugger.zip",
                    }
                ]
            }
        )
