from __future__ import annotations

import inspect
import math
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .service import LegalService
from .types import (
    ExternalAccess,
    LegalBoundaryError,
    LegalContext,
    LegalExecutionError,
    MatterIsolationViolation,
    PolicyViolation,
    RouteKind,
    RouteRequest,
    Sensitivity,
)

MatterAuthorizer = Callable[[str], bool]


def to_wire(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PolicyViolation("wire_float_must_be_finite")
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return to_wire(asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise PolicyViolation("wire_mapping_requires_string_keys")
        return {key: to_wire(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        raise PolicyViolation("wire_collection_must_be_ordered")
    if isinstance(value, (list, tuple)):
        return [to_wire(item) for item in value]
    raise PolicyViolation("wire_value_not_serializable")


def _route_kind(value: str) -> RouteKind:
    try:
        return RouteKind(value)
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("invalid_route_kind") from exc


def _authorize_matter(matter_authorizer: MatterAuthorizer, matter_id: str) -> None:
    try:
        authorized = matter_authorizer(matter_id)
    except Exception as exc:
        raise MatterIsolationViolation("matter_authorization_failed") from exc
    if authorized is not True:
        raise MatterIsolationViolation("matter_not_authorized")


async def invoke_transport(
    service: LegalService,
    tool_name: str,
    *,
    matter_id: str,
    arguments: dict[str, Any],
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED,
    external_access: ExternalAccess = ExternalAccess.DENY,
    route_kind: str = "LOCAL",
    provider: str | None = None,
    redaction_attestation: str | None = None,
) -> Any:
    _authorize_matter(matter_authorizer, matter_id)
    context = LegalContext(
        matter_id=matter_id,
        sensitivity=sensitivity,
        external_access=external_access,
    )
    route = RouteRequest(
        kind=_route_kind(route_kind),
        provider=provider,
        redaction_attestation=redaction_attestation,
    )
    try:
        result = service.execute(
            context,
            tool_name,
            arguments,
            route=route,
            defer_success_audit=True,
        )
        if inspect.isawaitable(result):
            result = await result
        try:
            wire_result = to_wire(result)
        except Exception:
            service.record_transport_error(
                context,
                tool_name,
                route,
                reason="result_serialization_error",
            )
            raise LegalExecutionError("legal_tool_execution_failed") from None
        service.record_transport_success(context, tool_name, route)
        return wire_result
    except LegalBoundaryError:
        raise
    except Exception:
        # Never expose unexpected handler/provider/serialization details across
        # MCP or HTTP. Service-side audit entries contain only stable reasons.
        raise LegalExecutionError("legal_tool_execution_failed") from None
