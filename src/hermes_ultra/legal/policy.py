from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import ExternalAccess, LegalContext, PolicyDecision, PolicyViolation, RouteKind, RouteRequest


def _validate_provider_set(value: Any, label: str) -> frozenset[str]:
    if type(value) is not frozenset:
        raise PolicyViolation(f"{label}_must_be_frozenset")
    for provider in value:
        if not isinstance(provider, str) or not provider or provider != provider.strip() or len(provider) > 256:
            raise PolicyViolation(f"invalid_{label}")
    return value


@dataclass(frozen=True)
class LegalPolicy:
    """Default-deny in-process egress policy for the private legal boundary."""

    official_legal_providers: frozenset[str] = field(default_factory=frozenset)
    approved_model_providers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _validate_provider_set(self.official_legal_providers, "official_legal_providers")
        _validate_provider_set(self.approved_model_providers, "approved_model_providers")

    def authorize(self, context: LegalContext, route: RouteRequest) -> PolicyDecision:
        if not isinstance(context, LegalContext):
            raise PolicyViolation("legal_context_required")
        if not isinstance(route, RouteRequest):
            raise PolicyViolation("route_request_required")

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
            if not isinstance(route.redaction_attestation, str) or not route.redaction_attestation:
                raise PolicyViolation("external_model_redaction_attestation_required")
            return PolicyDecision(True, "approved_model_requires_verified_attestation", route)

        raise PolicyViolation("route_kind_forbidden")
