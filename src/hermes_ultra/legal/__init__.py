"""Private, matter-isolated Hermes Legal capability boundary."""

from .policy import LegalPolicy
from .provenance import ProvenanceGuard
from .service import LEGAL_TOOL_ROUTES, LegalService
from .types import (
    EvidenceBundle,
    EvidenceSource,
    ExternalAccess,
    LegalBoundaryError,
    LegalContext,
    MatterIsolationViolation,
    PolicyDecision,
    PolicyViolation,
    ProvenanceViolation,
    RedactedPayload,
    RouteKind,
    RouteRequest,
    Sensitivity,
    SourceKind,
)

__all__ = [
    "EvidenceBundle",
    "EvidenceSource",
    "ExternalAccess",
    "LEGAL_TOOL_ROUTES",
    "LegalBoundaryError",
    "LegalContext",
    "LegalPolicy",
    "LegalService",
    "MatterIsolationViolation",
    "PolicyDecision",
    "PolicyViolation",
    "ProvenanceGuard",
    "ProvenanceViolation",
    "RedactedPayload",
    "RouteKind",
    "RouteRequest",
    "Sensitivity",
    "SourceKind",
]
