from __future__ import annotations

import copy
import hashlib
import hmac
import inspect
import json
import math
import secrets
import threading
from collections.abc import Callable, Mapping
from typing import Any

from .policy import LegalPolicy
from .provenance import ProvenanceGuard
from .types import (
    AssertionKind,
    AuditRecord,
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
)

Handler = Callable[[LegalContext, Mapping[str, Any]], Any]
HandlerKey = tuple[str, RouteKind, str | None]

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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PolicyViolation("external_payload_not_json_serializable")
        return value
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise PolicyViolation("external_payload_requires_string_keys")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise PolicyViolation("external_payload_not_json_serializable")


def _payload_digest(payload: Any) -> str:
    canonical = json.dumps(
        _json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _handler_provider(route_kind: RouteKind, provider: str | None) -> str | None:
    if route_kind is RouteKind.LOCAL:
        if provider is not None and str(provider).strip():
            raise PolicyViolation("local_handler_provider_forbidden")
        return None
    normalized = provider.strip() if isinstance(provider, str) else ""
    if not normalized:
        raise PolicyViolation("external_handler_provider_required")
    return normalized


class LegalService:
    """Shared legal core used by MCP, HTTP, CLI, or in-process callers."""

    def __init__(self, *, policy: LegalPolicy | None = None, redaction_key: bytes | None = None) -> None:
        self.policy = policy or LegalPolicy()
        self.provenance = ProvenanceGuard()
        self._resources: dict[str, tuple[str, Any]] = {}
        self._resource_lock = threading.RLock()
        self._handlers: dict[HandlerKey, Handler] = {
            ("redact_for_external_model", RouteKind.LOCAL, None): self._redaction_handler
        }
        self._audit: list[AuditRecord] = []
        self._audit_lock = threading.Lock()
        key = redaction_key if redaction_key is not None else secrets.token_bytes(32)
        if not isinstance(key, bytes) or len(key) < 32:
            raise PolicyViolation("redaction_key_must_be_at_least_32_bytes")
        self._redaction_key = key

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(LEGAL_TOOL_ROUTES)

    @property
    def audit_records(self) -> tuple[AuditRecord, ...]:
        with self._audit_lock:
            return tuple(self._audit)

    def _record(self, context: LegalContext, tool_name: str, route: RouteRequest, outcome: str, reason: str) -> None:
        with self._audit_lock:
            self._audit.append(
                AuditRecord(len(self._audit) + 1, context.matter_id, tool_name, route.kind, outcome, reason)
            )

    def record_transport_success(self, context: LegalContext, tool_name: str, route: RouteRequest) -> None:
        self._record(context, tool_name, route, "EXECUTED", "authorized")

    def record_transport_error(
        self,
        context: LegalContext,
        tool_name: str,
        route: RouteRequest,
        *,
        reason: str,
    ) -> None:
        self._record(context, tool_name, route, "ERROR", reason)

    def register_handler(
        self,
        tool_name: str,
        handler: Handler,
        *,
        route_kind: RouteKind = RouteKind.LOCAL,
        provider: str | None = None,
    ) -> None:
        if tool_name not in LEGAL_TOOL_ROUTES:
            raise PolicyViolation("unknown_legal_tool")
        if not callable(handler):
            raise PolicyViolation("tool_handler_must_be_callable")
        if not isinstance(route_kind, RouteKind):
            raise PolicyViolation("invalid_handler_route_kind")
        if route_kind not in LEGAL_TOOL_ROUTES[tool_name]:
            raise PolicyViolation("handler_route_forbidden")
        normalized_provider = _handler_provider(route_kind, provider)
        key = (tool_name, route_kind, normalized_provider)
        if key in self._handlers:
            raise PolicyViolation("handler_route_already_registered")
        self._handlers[key] = handler

    def put_resource(self, context: LegalContext, *, resource_id: str, value: Any) -> None:
        resource_id = resource_id.strip() if isinstance(resource_id, str) else ""
        if not resource_id:
            raise PolicyViolation("invalid_resource_id")
        value_snapshot = copy.deepcopy(value)
        with self._resource_lock:
            existing = self._resources.get(resource_id)
            if existing is not None and existing[0] != context.matter_id:
                raise MatterIsolationViolation("resource_id_owned_by_other_matter")
            self._resources[resource_id] = (context.matter_id, value_snapshot)

    def get_resource(self, context: LegalContext, resource_id: str) -> Any:
        with self._resource_lock:
            stored = self._resources.get(resource_id)
            if stored is None:
                raise KeyError(resource_id)
            matter_id, value = stored
            if matter_id != context.matter_id:
                raise MatterIsolationViolation("cross_matter_resource_access")
            return copy.deepcopy(value)

    def _attestation(self, matter_id: str, payload: Any) -> str:
        digest = _payload_digest(payload)
        message = f"{matter_id}\0{digest}".encode("utf-8")
        signature = hmac.new(self._redaction_key, message, hashlib.sha256).hexdigest()
        return f"hrp1.{digest}.{signature}"

    def _verify_attestation(self, context: LegalContext, payload: Any, attestation: str | None) -> None:
        if not isinstance(attestation, str):
            raise PolicyViolation("invalid_redaction_attestation")
        parts = attestation.split(".")
        if len(parts) != 3 or parts[0] != "hrp1":
            raise PolicyViolation("invalid_redaction_attestation")
        _, claimed_digest, claimed_signature = parts
        actual_digest = _payload_digest(payload)
        if not hmac.compare_digest(claimed_digest, actual_digest):
            raise PolicyViolation("redaction_attestation_payload_mismatch")
        expected = self._attestation(context.matter_id, payload).split(".", 2)[2]
        if not hmac.compare_digest(claimed_signature, expected):
            raise PolicyViolation("invalid_redaction_attestation")

    def redact_for_external_model(
        self,
        context: LegalContext,
        payload: Any,
        *,
        redact_keys: set[str] | frozenset[str],
    ) -> RedactedPayload:
        normalized = {str(key).casefold() for key in redact_keys if str(key).strip()}
        if not normalized:
            raise PolicyViolation("redact_keys_required")
        touched: set[str] = set()

        def walk(value: Any) -> Any:
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise PolicyViolation("external_payload_requires_string_keys")
                result: dict[str, Any] = {}
                for key, item in value.items():
                    if key.casefold() in normalized:
                        result[key] = "[REDACTED]"
                        touched.add(key)
                    else:
                        result[key] = walk(item)
                return result
            if isinstance(value, list):
                return [walk(item) for item in value]
            if isinstance(value, tuple):
                return [walk(item) for item in value]
            return _json_safe(value)

        sanitized = walk(payload)
        if not touched:
            raise PolicyViolation("redaction_target_not_found")
        return RedactedPayload(
            payload=sanitized,
            redacted=True,
            redacted_keys=tuple(sorted(touched)),
            attestation=self._attestation(context.matter_id, sanitized),
        )

    def _redaction_handler(self, context: LegalContext, arguments: Mapping[str, Any]) -> RedactedPayload:
        if "payload" not in arguments:
            raise PolicyViolation("redaction_payload_required")
        raw_keys = arguments.get("redact_keys", ())
        if not isinstance(raw_keys, (list, tuple, set, frozenset)):
            raise PolicyViolation("redact_keys_must_be_collection")
        return self.redact_for_external_model(
            context, arguments["payload"], redact_keys={str(key) for key in raw_keys}
        )

    def _normalize_handler_result(self, value: Any) -> LegalToolResult:
        if isinstance(value, LegalToolResult):
            return value
        return LegalToolResult(payload=value, assertion=AssertionKind.NONE, evidence=None)

    def _validate_handler_result(
        self,
        context: LegalContext,
        tool_name: str,
        route: RouteRequest,
        value: Any,
    ) -> LegalToolResult:
        result = self._normalize_handler_result(value)
        if result.assertion is AssertionKind.NONE:
            if result.evidence is not None:
                raise ProvenanceViolation("unverified_result_cannot_attach_evidence")
            return result
        if result.evidence is None:
            raise ProvenanceViolation("formal_claim_requires_evidence_bundle")

        bundle = self.provenance.validate_bundle(context, result.evidence, operation=tool_name)
        if result.assertion is AssertionKind.VERIFIED_CITATION and not bundle.authority_ids:
            raise ProvenanceViolation("verified_citation_requires_authority")

        if route.kind is RouteKind.LOCAL:
            if bundle.external_disclosure:
                raise ProvenanceViolation("external_disclosure_mismatch")
            if bundle.model_route is not None:
                raise ProvenanceViolation("model_route_mismatch")
        elif route.kind is RouteKind.OFFICIAL_LEGAL_API:
            if not bundle.external_disclosure:
                raise ProvenanceViolation("external_disclosure_mismatch")
            if bundle.model_route is not None:
                raise ProvenanceViolation("model_route_mismatch")
        elif route.kind is RouteKind.APPROVED_MODEL:
            if not bundle.external_disclosure:
                raise ProvenanceViolation("external_disclosure_mismatch")
            if bundle.model_route != route.provider:
                raise ProvenanceViolation("model_route_mismatch")
        else:
            raise ProvenanceViolation("evidence_route_mismatch")

        return result

    def _finalize_result(
        self,
        context: LegalContext,
        tool_name: str,
        route: RouteRequest,
        value: Any,
        *,
        defer_success_audit: bool,
    ) -> LegalToolResult:
        try:
            validated = self._validate_handler_result(context, tool_name, route, value)
        except MatterIsolationViolation:
            self._record(context, tool_name, route, "DENY", "cross_matter_handler_evidence")
            raise
        except ProvenanceViolation:
            self._record(context, tool_name, route, "DENY", "unproven_handler_claim")
            raise
        if not defer_success_audit:
            self._record(context, tool_name, route, "EXECUTED", "authorized")
        return validated

    def execute(
        self,
        context: LegalContext,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        route: RouteRequest | None = None,
        defer_success_audit: bool = False,
    ) -> Any:
        if route is None:
            requested_route = RouteRequest(kind=RouteKind.LOCAL)
        elif isinstance(route, RouteRequest):
            requested_route = route
        else:
            fallback_route = RouteRequest(kind=RouteKind.UNKNOWN)
            if isinstance(context, LegalContext):
                self._record(context, tool_name, fallback_route, "DENY", "route_request_required")
            raise PolicyViolation("route_request_required")

        if tool_name not in LEGAL_TOOL_ROUTES:
            self._record(context, tool_name, requested_route, "DENY", "unknown_legal_tool")
            raise PolicyViolation("unknown_legal_tool")
        if not isinstance(arguments, Mapping):
            self._record(context, tool_name, requested_route, "DENY", "tool_arguments_must_be_mapping")
            raise PolicyViolation("tool_arguments_must_be_mapping")
        try:
            argument_snapshot = copy.deepcopy(dict(arguments))
        except Exception:
            self._record(context, tool_name, requested_route, "DENY", "tool_arguments_snapshot_failed")
            raise PolicyViolation("tool_arguments_snapshot_failed") from None

        try:
            decision = self.policy.authorize(context, requested_route)
            if not isinstance(decision, PolicyDecision):
                raise PolicyViolation("invalid_policy_decision")
            if decision.allowed is not True:
                raise PolicyViolation("policy_denied")
            if decision.route != requested_route:
                raise PolicyViolation("policy_route_mismatch")
            if requested_route.kind not in LEGAL_TOOL_ROUTES[tool_name]:
                raise PolicyViolation("tool_route_forbidden")
            if requested_route.kind is RouteKind.APPROVED_MODEL:
                if set(argument_snapshot) != {"payload"}:
                    raise PolicyViolation("external_model_arguments_must_be_attested_payload_only")
                self._verify_attestation(
                    context, argument_snapshot["payload"], requested_route.redaction_attestation
                )
            normalized_provider = _handler_provider(requested_route.kind, requested_route.provider)
            handler = self._handlers.get((tool_name, requested_route.kind, normalized_provider))
            if handler is None:
                raise PolicyViolation("tool_handler_unavailable")
        except PolicyViolation as exc:
            self._record(context, tool_name, requested_route, "DENY", str(exc))
            raise

        try:
            result = handler(context, copy.deepcopy(argument_snapshot))
        except Exception:
            self._record(context, tool_name, requested_route, "ERROR", "handler_error")
            raise LegalExecutionError("legal_tool_execution_failed") from None

        if inspect.isawaitable(result):
            async def finalize() -> LegalToolResult:
                try:
                    value = await result
                except Exception:
                    self._record(context, tool_name, requested_route, "ERROR", "handler_error")
                    raise LegalExecutionError("legal_tool_execution_failed") from None
                return self._finalize_result(
                    context,
                    tool_name,
                    requested_route,
                    value,
                    defer_success_audit=defer_success_audit,
                )

            return finalize()

        return self._finalize_result(
            context,
            tool_name,
            requested_route,
            result,
            defer_success_audit=defer_success_audit,
        )
