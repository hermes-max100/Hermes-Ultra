from __future__ import annotations

from dataclasses import dataclass, field

from .types import ExternalAccess, LegalContext, PolicyDecision, PolicyViolation, RouteKind, RouteRequest


@dataclass(frozen=True)
class LegalPolicy:
    """Application-level legal egress policy.

    This is deliberately default-deny. Network-layer allowlisting is still required
    at deployment; this object is the in-process authorization gate every transport
    and handler must traverse.
    """

    official_legal_providers: frozenset[str] = field(default_factory=frozenset)
    approved_model_providers: frozenset[str] = field(default_factory=frozenset)

    def authorize(self, context: LegalContext, route: RouteRequest) -> PolicyDecision:
        if route.kind is RouteKind.LOCAL:
            return PolicyDecision(True, "local_private_route", route)

        if context.external_access is ExternalAccess.DENY:
            raise PolicyViolation("external_access_denied")

        if route.kind in {RouteKind.MONID, RouteKind.PUBLIC_MCP, RouteKind.UNKNOWN}:
            raise PolicyViolation("route_kind_forbidden")

        provider = (route.provider or "").strip()
        if not provider:
            raise PolicyViolation("provider_required")

        if route.kind is RouteKind.OFFICIAL_LEGAL_API:
            if provider not in self.official_legal_providers:
                raise PolicyViolation("provider_not_allowlisted")
            return PolicyDecision(True, "official_legal_provider_allowlisted", route)

        if route.kind is RouteKind.APPROVED_MODEL:
            if provider not in self.approved_model_providers:
                raise PolicyViolation("provider_not_allowlisted")
            if not route.payload_redacted:
                raise PolicyViolation("external_model_payload_not_redacted")
            return PolicyDecision(True, "approved_model_redacted_payload", route)

        raise PolicyViolation("route_kind_forbidden")
