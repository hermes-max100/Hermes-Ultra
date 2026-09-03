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


class LegalExecutionError(LegalBoundaryError):
    """A legal capability failed without exposing handler exception details."""


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


class AssertionKind(str, Enum):
    NONE = "NONE"
    SUCCESS = "SUCCESS"
    VERIFIED_FACT = "VERIFIED_FACT"
    VERIFIED_CITATION = "VERIFIED_CITATION"


def _nonempty(value: Any, label: str, *, maximum: int = 500) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > maximum:
        raise ProvenanceViolation(f"invalid_{label}")
    return text


def _id_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ProvenanceViolation(f"{label}_must_be_tuple")
    if len(value) != len(set(value)):
        raise ProvenanceViolation(f"duplicate_{label}")
    for item in value:
        _nonempty(item, label, maximum=256)
    return value


@dataclass(frozen=True)
class LegalContext:
    matter_id: str
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED
    external_access: ExternalAccess = ExternalAccess.DENY

    def __post_init__(self) -> None:
        matter_id = self.matter_id.strip() if isinstance(self.matter_id, str) else ""
        if not matter_id or len(matter_id) > 200:
            raise PolicyViolation("invalid_matter_id")
        if not isinstance(self.sensitivity, Sensitivity):
            raise PolicyViolation("invalid_sensitivity")
        if not isinstance(self.external_access, ExternalAccess):
            raise PolicyViolation("invalid_external_access")
        object.__setattr__(self, "matter_id", matter_id)


@dataclass(frozen=True)
class RouteRequest:
    kind: RouteKind
    provider: str | None = None
    redaction_attestation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RouteKind):
            raise PolicyViolation("invalid_route_kind")
        if self.provider is not None and not isinstance(self.provider, str):
            raise PolicyViolation("invalid_provider")
        if self.redaction_attestation is not None and not isinstance(self.redaction_attestation, str):
            raise PolicyViolation("invalid_redaction_attestation")


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

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceKind):
            raise ProvenanceViolation("invalid_source_kind")


@dataclass(frozen=True)
class EvidenceBundle:
    matter_id: str
    operation: str
    source_ids: tuple[str, ...]
    authority_ids: tuple[str, ...]
    external_disclosure: bool
    model_route: str | None
    verified: bool

    def __post_init__(self) -> None:
        _nonempty(self.matter_id, "evidence_matter_id", maximum=200)
        _nonempty(self.operation, "evidence_operation", maximum=256)
        _id_tuple(self.source_ids, "source_ids")
        _id_tuple(self.authority_ids, "authority_ids")
        if type(self.external_disclosure) is not bool:
            raise ProvenanceViolation("external_disclosure_must_be_bool")
        if self.model_route is not None:
            _nonempty(self.model_route, "model_route", maximum=256)
        if type(self.verified) is not bool:
            raise ProvenanceViolation("verified_must_be_bool")


@dataclass(frozen=True)
class LegalToolResult:
    """Typed legal result for formal Hermes SUCCESS/VERIFIED assertions.

    Raw handler values are wrapped with ``assertion=NONE`` by LegalService, so
    claim-like words inside source/provider data remain data rather than authority.
    """

    payload: Any
    assertion: AssertionKind = AssertionKind.NONE
    evidence: EvidenceBundle | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assertion, AssertionKind):
            raise ProvenanceViolation("invalid_assertion_kind")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceBundle):
            raise ProvenanceViolation("invalid_evidence_bundle")


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    matter_id: str
    tool_name: str
    route_kind: RouteKind
    outcome: str
    reason: str
