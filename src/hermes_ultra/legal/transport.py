from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .service import LegalService
from .types import ExternalAccess, LegalContext, PolicyViolation, RouteKind, RouteRequest, Sensitivity


def _enum(enum_type: type[Enum], value: str, label: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise PolicyViolation(f"invalid_{label}") from exc


def to_wire(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return to_wire(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_wire(item) for item in value]
    return value


async def invoke_transport(
    service: LegalService,
    tool_name: str,
    *,
    matter_id: str,
    arguments: dict[str, Any],
    sensitivity: str = "LEGAL_PRIVILEGED",
    external_access: str = "DENY",
    route_kind: str = "LOCAL",
    provider: str | None = None,
    endpoint: str | None = None,
    payload_redacted: bool = False,
) -> Any:
    parsed_sensitivity = _enum(Sensitivity, sensitivity, "sensitivity")
    parsed_access = _enum(ExternalAccess, external_access, "external_access")
    parsed_route = _enum(RouteKind, route_kind, "route_kind")
    context = LegalContext(
        matter_id=matter_id,
        sensitivity=parsed_sensitivity,  # type: ignore[arg-type]
        external_access=parsed_access,  # type: ignore[arg-type]
    )
    route = RouteRequest(
        kind=parsed_route,  # type: ignore[arg-type]
        provider=provider,
        endpoint=endpoint,
        payload_redacted=payload_redacted,
    )
    result = service.execute(context, tool_name, arguments, route=route)
    if inspect.isawaitable(result):
        result = await result
    return to_wire(result)
