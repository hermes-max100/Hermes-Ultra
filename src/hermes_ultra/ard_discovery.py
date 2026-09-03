from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .skill_lifecycle import (
    AuthorityProfile,
    CapabilityDescriptor,
    LifecycleState,
    Provenance,
    SkillCandidate,
)


class ArdCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ArdCatalogEntry:
    identifier: str
    display_name: str
    media_type: str
    url: str | None = None
    data: Mapping[str, object] | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArdCatalog:
    entries: tuple[ArdCatalogEntry, ...]


class ArdCatalogLoader:
    """Offline ARD catalog adapter.

    This adapter only normalizes discovery metadata. It never retrieves an entry URL,
    installs a resource, promotes trust, or activates a capability.
    """

    def load(self, payload: Mapping[str, object]) -> ArdCatalog:
        if not isinstance(payload, Mapping):
            raise ArdCatalogError("ARD catalog must be an object")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise ArdCatalogError("ARD catalog entries must be an array")

        entries: list[ArdCatalogEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, Mapping):
                raise ArdCatalogError("ARD catalog entry must be an object")
            identifier = raw.get("identifier")
            display_name = raw.get("displayName")
            media_type = raw.get("type")
            capabilities = raw.get("capabilities", [])
            if not isinstance(identifier, str) or not identifier:
                raise ArdCatalogError("ARD entry identifier is required")
            if not isinstance(display_name, str) or not display_name:
                raise ArdCatalogError("ARD entry displayName is required")
            if not isinstance(media_type, str) or not media_type:
                raise ArdCatalogError("ARD entry type is required")
            if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
                raise ArdCatalogError("ARD entry capabilities must be an array of strings")

            url = raw.get("url")
            data = raw.get("data")
            entries.append(
                ArdCatalogEntry(
                    identifier=identifier,
                    display_name=display_name,
                    media_type=media_type,
                    url=url if isinstance(url, str) else None,
                    data=dict(data) if isinstance(data, Mapping) else None,
                    capabilities=tuple(capabilities),
                )
            )
        return ArdCatalog(entries=tuple(entries))

    def to_candidate(self, entry: ArdCatalogEntry, *, provenance: Provenance) -> SkillCandidate:
        return SkillCandidate(
            candidate_id=f"ard:{entry.identifier}",
            name=entry.display_name,
            provenance=provenance,
            authority=AuthorityProfile(network=entry.url is not None),
            capability=CapabilityDescriptor(
                capability_id=entry.identifier,
                capabilities=frozenset(entry.capabilities),
                tools=frozenset(),
                outputs=frozenset({"ard-discovery-record"}),
            ),
            state=LifecycleState.DISCOVERED,
        )
