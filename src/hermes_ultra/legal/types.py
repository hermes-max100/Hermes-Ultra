from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LegalBoundaryError(RuntimeError):
    """Base error for the fail-closed Hermes Legal boundary."""


class PolicyViolation(LegalBoundaryError):
    """A requested route or operation is not authorized."""


class MatterIsolationViolation(LegalBoundaryError):
    """A resource or source belongs to another legal matter."""


class ProvenanceViolation(LegalBoundaryError):
    """An evidence/provenance invariant was not satisfied."""


class Sensitivity(str, Enum):
    LEGAL_PRIVATE = "LEGAL_PRIVATE"
    LEGAL_PRIVILEGED = "LEGAL_PRIVILEGED"


class ExternalAccess(str, Enum):
    DENY = "DENY"
    ALLOWLIST = "ALLOWLIST"


class RouteKind(str, Enum):
    LOCAL = "LOCAL"
    OFFICIAL_LEGAL_API = "OFFICIAL_LEGAL_API"
    APPROVED_MODEL = "APPROVED_MODEL"
    MONID = "MONID"
    PUBLIC_MCP = "PUBLIC_MCP"
    UNKNOWN = "UNKNOWN"


class SourceKind(str, Enum):
    RECORD = "RECORD"
    AUTHORITY = "AUTHORITY"
    USER_SUPPLIED = "USER_SUPPLIED"
    GENERATED = "GENERATED"


@dataclass(frozen=True)
class LegalContext:
    matter_id: str
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED
    external_access: ExternalAccess = ExternalAccess.DENY

    def __post_init__(self) -> None:
        matter_id = self.matter_id.strip() if isinstance(self.matter_id, str) else ""
        if not matter_id or len(matter_id) > 200:
            raise PolicyViolation("invalid_matter_id")
        object.__setattr__(self, "matter_id", matter_id)


@dataclass(frozen=True)
class RouteRequest:
    kind: RouteKind
    provider: str | None = None
    redaction_attestation: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    route: RouteRequest


@dataclass(frozen=True)
class RedactedPayload:
    payload: Any
    redacted: bool
    redacted_keys: tuple[str, ...]
    attestation: str


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    matter_id: str
    kind: SourceKind
    locator: str
    sha256: str


@dataclass(frozen=True)
class EvidenceBundle:
    matter_id: str
    operation: str
    source_ids: tuple[str, ...]
    authority_ids: tuple[str, ...]
    external_disclosure: bool
    model_route: str | None
    verified: bool


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    matter_id: str
    tool_name: str
    route_kind: RouteKind
    outcome: str
    reason: str
