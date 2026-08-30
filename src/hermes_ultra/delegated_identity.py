from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping


@dataclass(frozen=True, order=True)
class CredentialReference:
    """Opaque credential reference; raw credential material never enters agent context."""

    provider: str
    reference: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.reference.strip():
            raise ValueError("credential provider and reference are required")


@dataclass(frozen=True)
class DelegatedIdentity:
    owner: str
    subject: str
    capabilities: frozenset[str]
    profiles: frozenset[str]
    providers: frozenset[str]
    expires_at: datetime
    credentials: tuple[CredentialReference, ...] = ()
    task_id: str | None = None
    delegated_by: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.owner.strip() or not self.subject.strip():
            raise ValueError("owner and subject are required")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        object.__setattr__(self, "capabilities", frozenset(self._clean(self.capabilities)))
        object.__setattr__(self, "profiles", frozenset(self._clean(self.profiles)))
        object.__setattr__(self, "providers", frozenset(self._clean(self.providers)))
        object.__setattr__(self, "credentials", tuple(sorted(set(self.credentials))))

    @staticmethod
    def _clean(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(value.strip() for value in values if value and value.strip())

    @classmethod
    def root(
        cls,
        *,
        owner: str,
        subject: str,
        capabilities: Iterable[str],
        profiles: Iterable[str],
        providers: Iterable[str],
        expires_at: datetime,
        credentials: Iterable[CredentialReference] = (),
        task_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "DelegatedIdentity":
        return cls(
            owner=owner,
            subject=subject,
            capabilities=frozenset(capabilities),
            profiles=frozenset(profiles),
            providers=frozenset(providers),
            expires_at=expires_at,
            credentials=tuple(credentials),
            task_id=task_id,
            delegated_by=owner,
            metadata={} if metadata is None else dict(metadata),
        )

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at

    def delegate(
        self,
        *,
        subject: str,
        capabilities: Iterable[str] | None = None,
        profiles: Iterable[str] | None = None,
        providers: Iterable[str] | None = None,
        credentials: Iterable[CredentialReference] | None = None,
        expires_at: datetime | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> "DelegatedIdentity":
        child_capabilities = self.capabilities if capabilities is None else frozenset(self._clean(capabilities))
        child_profiles = self.profiles if profiles is None else frozenset(self._clean(profiles))
        child_providers = self.providers if providers is None else frozenset(self._clean(providers))
        child_credentials = set(self.credentials if credentials is None else tuple(credentials))
        child_expiry = expires_at or self.expires_at
        child_task = self.task_id if task_id is None else task_id

        if not child_capabilities.issubset(self.capabilities):
            raise PermissionError("delegation cannot widen capabilities")
        if not child_profiles.issubset(self.profiles):
            raise PermissionError("delegation cannot widen profiles")
        if not child_providers.issubset(self.providers):
            raise PermissionError("delegation cannot widen providers")
        if not child_credentials.issubset(set(self.credentials)):
            raise PermissionError("delegation cannot introduce credential references")
        if child_expiry > self.expires_at:
            raise PermissionError("delegation cannot extend expiry")
        if self.task_id is not None and child_task != self.task_id:
            raise PermissionError("delegation cannot widen task scope")

        return DelegatedIdentity(
            owner=self.owner,
            subject=subject,
            capabilities=child_capabilities,
            profiles=child_profiles,
            providers=child_providers,
            expires_at=child_expiry,
            credentials=tuple(child_credentials),
            task_id=child_task,
            delegated_by=self.subject,
            metadata={} if metadata is None else dict(metadata),
        )

    def to_mcp_meta(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "owner": self.owner,
            "subject": self.subject,
            "delegatedBy": self.delegated_by,
            "capabilities": sorted(self.capabilities),
            "profiles": sorted(self.profiles),
            "providers": sorted(self.providers),
            "expiresAt": self.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "credentialRefs": [
                {"provider": item.provider, "reference": item.reference}
                for item in self.credentials
            ],
        }
        if self.task_id is not None:
            payload["taskId"] = self.task_id
        return {"com.hermes.ultra/delegatedIdentity": payload}
