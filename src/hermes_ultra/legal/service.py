from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from .policy import LegalPolicy
from .provenance import ProvenanceGuard
from .types import (
    AuditRecord,
    LegalContext,
    MatterIsolationViolation,
    PolicyViolation,
    RedactedPayload,
    RouteKind,
    RouteRequest,
)

Handler = Callable[[LegalContext, Mapping[str, Any]], Any]

LEGAL_TOOL_ROUTES: dict[str, frozenset[RouteKind]] = {
    "document_reader": frozenset({RouteKind.LOCAL}),
    "legal_retrieval": frozenset({RouteKind.LOCAL, RouteKind.OFFICIAL_LEGAL_API}),
    "citation_validator": frozenset({RouteKind.LOCAL, RouteKind.OFFICIAL_LEGAL_API}),
    "guarded_draft": frozenset({RouteKind.LOCAL, RouteKind.APPROVED_MODEL}),
    "case_record_search": frozenset({RouteKind.LOCAL}),
    "timeline_builder": frozenset({RouteKind.LOCAL}),
    "exhibit_indexer": frozenset({RouteKind.LOCAL}),
    "record_fact_extractor": frozenset({RouteKind.LOCAL}),
    "authority_checker": frozenset({RouteKind.LOCAL, RouteKind.OFFICIAL_LEGAL_API}),
    "redact_for_external_model": frozenset({RouteKind.LOCAL}),
    "compare_filings": frozenset({RouteKind.LOCAL}),
    "record_citation_resolver": frozenset({RouteKind.LOCAL, RouteKind.OFFICIAL_LEGAL_API}),
    "perseus_remember": frozenset({RouteKind.LOCAL}),
    "perseus_recall": frozenset({RouteKind.LOCAL}),
}


class LegalService:
    """Shared legal core used by MCP, HTTP, CLI, or in-process callers."""

    def __init__(self, *, policy: LegalPolicy | None = None) -> None:
        self.policy = policy or LegalPolicy()
        self.provenance = ProvenanceGuard()
        self._resources: dict[str, tuple[str, Any]] = {}
        self._handlers: dict[str, Handler] = {"redact_for_external_model": self._redaction_handler}
        self._audit: list[AuditRecord] = []

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(LEGAL_TOOL_ROUTES)

    @property
    def audit_records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._audit)

    def _record(self, context: LegalContext, tool_name: str, route: RouteRequest, outcome: str, reason: str) -> None:
        self._audit.append(
            AuditRecord(len(self._audit) + 1, context.matter_id, tool_name, route.kind, outcome, reason)
        )

    def register_handler(self, tool_name: str, handler: Handler) -> None:
        if tool_name not in LEGAL_TOOL_ROUTES:
            raise PolicyViolation("unknown_legal_tool")
        if not callable(handler):
            raise PolicyViolation("tool_handler_must_be_callable")
        self._handlers[tool_name] = handler

    def put_resource(self, context: LegalContext, *, resource_id: str, value: Any) -> None:
        resource_id = resource_id.strip() if isinstance(resource_id, str) else ""
        if not resource_id:
            raise PolicyViolation("invalid_resource_id")
        existing = self._resources.get(resource_id)
        if existing is not None and existing[0] != context.matter_id:
            raise MatterIsolationViolation("resource_id_owned_by_other_matter")
        self._resources[resource_id] = (context.matter_id, copy.deepcopy(value))

    def get_resource(self, context: LegalContext, resource_id: str) -> Any:
        stored = self._resources.get(resource_id)
        if stored is None:
            raise KeyError(resource_id)
        matter_id, value = stored
        if matter_id != context.matter_id:
            raise MatterIsolationViolation("cross_matter_resource_access")
        return copy.deepcopy(value)

    def redact_for_external_model(
        self,
        context: LegalContext,
        payload: Any,
        *,
        redact_keys: set[str] | frozenset[str],
    ) -> RedactedPayload:
        del context
        normalized = {str(key).casefold() for key in redact_keys if str(key).strip()}
        if not normalized:
            raise PolicyViolation("redact_keys_required")
        touched: set[str] = set()

        def walk(value: Any) -> Any:
            if isinstance(value, dict):
                result: dict[Any, Any] = {}
                for key, item in value.items():
                    if str(key).casefold() in normalized:
                        result[key] = "[REDACTED]"
                        touched.add(str(key))
                    else:
                        result[key] = walk(item)
                return result
            if isinstance(value, list):
                return [walk(item) for item in value]
            if isinstance(value, tuple):
                return tuple(walk(item) for item in value)
            return copy.deepcopy(value)

        sanitized = walk(payload)
        if not touched:
            raise PolicyViolation("redaction_target_not_found")
        return RedactedPayload(sanitized, True, tuple(sorted(touched)))

    def _redaction_handler(self, context: LegalContext, arguments: Mapping[str, Any]) -> RedactedPayload:
        if "payload" not in arguments:
            raise PolicyViolation("redaction_payload_required")
        raw_keys = arguments.get("redact_keys", ())
        if not isinstance(raw_keys, (list, tuple, set, frozenset)):
            raise PolicyViolation("redact_keys_must_be_collection")
        return self.redact_for_external_model(
            context, arguments["payload"], redact_keys={str(key) for key in raw_keys}
        )

    def execute(
        self,
        context: LegalContext,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        route: RouteRequest | None = None,
    ) -> Any:
        requested_route = route or RouteRequest(kind=RouteKind.LOCAL)
        if tool_name not in LEGAL_TOOL_ROUTES:
            self._record(context, tool_name, requested_route, "DENY", "unknown_legal_tool")
            raise PolicyViolation("unknown_legal_tool")
        if not isinstance(arguments, Mapping):
            self._record(context, tool_name, requested_route, "DENY", "tool_arguments_must_be_mapping")
            raise PolicyViolation("tool_arguments_must_be_mapping")
        try:
            self.policy.authorize(context, requested_route)
            if requested_route.kind not in LEGAL_TOOL_ROUTES[tool_name]:
                raise PolicyViolation("tool_route_forbidden")
            handler = self._handlers.get(tool_name)
            if handler is None:
                raise PolicyViolation("tool_handler_unavailable")
        except PolicyViolation as exc:
            self._record(context, tool_name, requested_route, "DENY", str(exc))
            raise
        try:
            result = handler(context, copy.deepcopy(dict(arguments)))
        except Exception:
            self._record(context, tool_name, requested_route, "ERROR", "handler_error")
            raise
        self._record(context, tool_name, requested_route, "EXECUTED", "authorized")
        return result
