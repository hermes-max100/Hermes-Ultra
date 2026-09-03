"""Private, matter-isolated Hermes Legal capability boundary."""

from .policy import LegalPolicy
from .provenance import ProvenanceGuard
from .service import LEGAL_TOOL_ROUTES, LegalService
from .types import (
    AssertionKind,
    AuditRecord,
    EvidenceBundle,
    EvidenceSource,
    ExternalAccess,
    LegalBoundaryError,
    LegalContext,
    LegalExecutionError,
    LegalToolResult,
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
    "AssertionKind",
    "AuditRecord",
    "EvidenceBundle",
    "EvidenceSource",
    "ExternalAccess",
    "LEGAL_TOOL_ROUTES",
    "LegalBoundaryError",
    "LegalContext",
    "LegalExecutionError",
    "LegalPolicy",
    "LegalService",
    "LegalToolResult",
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
