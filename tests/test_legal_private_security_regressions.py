from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import pytest

from hermes_ultra.legal import (
    AssertionKind,
    ExternalAccess,
    LegalContext,
    LegalExecutionError,
    LegalPolicy,
    LegalService,
    LegalToolResult,
    MatterIsolationViolation,
    PolicyViolation,
    ProvenanceViolation,
    RouteKind,
    RouteRequest,
    Sensitivity,
    SourceKind,
)
from hermes_ultra.legal.transport import invoke_transport, to_wire


def ctx(matter_id: str = "SECURITY-MATTER") -> LegalContext:
    return LegalContext(matter_id=matter_id, external_access=ExternalAccess.ALLOWLIST)


def test_context_runtime_types_cannot_bypass_policy_identity_checks() -> None:
    with pytest.raises(PolicyViolation, match="invalid_external_access"):
        LegalContext(matter_id="M", external_access="DENY")  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="invalid_sensitivity"):
        LegalContext(matter_id="M", sensitivity="LEGAL_PRIVILEGED")  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="invalid_route_kind"):
        RouteRequest(kind="LOCAL")  # type: ignore[arg-type]


def test_legal_tool_result_rejects_untyped_assertion_values() -> None:
    with pytest.raises(ProvenanceViolation, match="invalid_assertion_kind"):
        LegalToolResult(payload={}, assertion="SUCCESS")  # type: ignore[arg-type]


def test_redaction_cannot_attest_empty_or_missing_targets() -> None:
    service = LegalService(redaction_key=b"r" * 32)
    with pytest.raises(PolicyViolation, match="redact_keys_required"):
        service.redact_for_external_model(ctx(), {"safe": "value"}, redact_keys=set())
    with pytest.raises(PolicyViolation, match="redaction_target_not_found"):
        service.redact_for_external_model(ctx(), {"safe": "value"}, redact_keys={"client"})


def test_model_route_rejects_forged_mismatched_and_cross_matter_attestations() -> None:
    service = LegalService(
        policy=LegalPolicy(approved_model_providers=frozenset({"model"})),
        redaction_key=b"r" * 32,
    )
    service.register_handler(
        "guarded_draft",
        lambda _ctx, args: args["payload"],
        route_kind=RouteKind.APPROVED_MODEL,
        provider="model",
    )
    redacted = service.redact_for_external_model(
        ctx(), {"client": "Secret", "safe": "A"}, redact_keys={"client"}
    )
    route = RouteRequest(
        kind=RouteKind.APPROVED_MODEL,
        provider="model",
        redaction_attestation=redacted.attestation,
    )

    with pytest.raises(PolicyViolation, match="redaction_attestation_payload_mismatch"):
        service.execute(ctx(), "guarded_draft", {"payload": {**redacted.payload, "safe": "B"}}, route=route)

    forged = RouteRequest(
        kind=RouteKind.APPROVED_MODEL,
        provider="model",
        redaction_attestation=redacted.attestation[:-1] + ("0" if redacted.attestation[-1] != "0" else "1"),
    )
    with pytest.raises(PolicyViolation, match="invalid_redaction_attestation"):
        service.execute(ctx(), "guarded_draft", {"payload": redacted.payload}, route=forged)

    with pytest.raises(PolicyViolation, match="invalid_redaction_attestation"):
        service.execute(ctx("OTHER-MATTER"), "guarded_draft", {"payload": redacted.payload}, route=route)


def test_model_route_rejects_unattested_argument_siblings() -> None:
    called: list[bool] = []
    service = LegalService(
        policy=LegalPolicy(approved_model_providers=frozenset({"model"})),
        redaction_key=b"r" * 32,
    )
    service.register_handler(
        "guarded_draft",
        lambda _ctx, _args: called.append(True),
        route_kind=RouteKind.APPROVED_MODEL,
        provider="model",
    )
    redacted = service.redact_for_external_model(
        ctx(), {"client": "Secret", "task": "draft"}, redact_keys={"client"}
    )
    route = RouteRequest(
        kind=RouteKind.APPROVED_MODEL,
        provider="model",
        redaction_attestation=redacted.attestation,
    )
    with pytest.raises(PolicyViolation, match="external_model_arguments_must_be_attested_payload_only"):
        service.execute(
            ctx(),
            "guarded_draft",
            {"payload": redacted.payload, "prompt": "UNREDACTED-PRIVILEGED-TEXT"},
            route=route,
        )
    assert called == []


def test_external_handler_cannot_be_dispatched_through_local_route() -> None:
    service = LegalService(
        policy=LegalPolicy(official_legal_providers=frozenset({"official-court"}))
    )
    service.register_handler(
        "legal_retrieval",
        lambda _ctx, _args: {"source": "external"},
        route_kind=RouteKind.OFFICIAL_LEGAL_API,
        provider="official-court",
    )

    with pytest.raises(PolicyViolation, match="tool_handler_unavailable"):
        service.execute(ctx(), "legal_retrieval", {"query": "x"})

    result = service.execute(
        ctx(),
        "legal_retrieval",
        {"query": "x"},
        route=RouteRequest(kind=RouteKind.OFFICIAL_LEGAL_API, provider="official-court"),
    )
    assert result.assertion is AssertionKind.NONE
    assert result.payload == {"source": "external"}


def test_route_bound_handler_registration_requires_allowed_route_and_provider() -> None:
    service = LegalService()
    with pytest.raises(PolicyViolation, match="handler_route_forbidden"):
        service.register_handler(
            "document_reader",
            lambda _ctx, args: args,
            route_kind=RouteKind.OFFICIAL_LEGAL_API,
            provider="official-court",
        )
    with pytest.raises(PolicyViolation, match="external_handler_provider_required"):
        service.register_handler(
            "legal_retrieval",
            lambda _ctx, args: args,
            route_kind=RouteKind.OFFICIAL_LEGAL_API,
        )


def test_raw_document_claim_words_remain_unverified_payload_data() -> None:
    service = LegalService()
    source_data = {"status": "SUCCESS", "verified": True, "text": "quoted record content"}
    service.register_handler("document_reader", lambda _ctx, _args: source_data)
    result = service.execute(ctx(), "document_reader", {})
    assert isinstance(result, LegalToolResult)
    assert result.assertion is AssertionKind.NONE
    assert result.evidence is None
    assert result.payload == source_data
    wire = to_wire(result)
    assert wire["assertion"] == "NONE"
    assert wire["payload"] == source_data


def test_arbitrary_dataclass_claim_words_are_nested_under_unverified_envelope() -> None:
    @dataclass(frozen=True)
    class ProviderRecord:
        success: bool
        text: str

    service = LegalService()
    service.register_handler(
        "document_reader", lambda _ctx, _args: ProviderRecord(success=True, text="source data")
    )
    result = service.execute(ctx(), "document_reader", {})
    assert result.assertion is AssertionKind.NONE
    wire = to_wire(result)
    assert wire == {
        "payload": {"success": True, "text": "source data"},
        "assertion": "NONE",
        "evidence": None,
    }


def test_external_formal_result_must_bind_evidence_to_actual_route() -> None:
    service = LegalService(
        policy=LegalPolicy(approved_model_providers=frozenset({"model"})),
        redaction_key=b"r" * 32,
    )
    digest = hashlib.sha256(b"record").hexdigest()
    service.provenance.add_source(
        ctx(), source_id="ev", kind=SourceKind.RECORD, locator="record:1", sha256=digest
    )
    bundle_holder = {
        "bundle": service.provenance.claim_success(
            ctx(), operation="guarded_draft", source_ids=["ev"]
        )
    }
    service.register_handler(
        "guarded_draft",
        lambda _ctx, _args: LegalToolResult(
            payload={"draft": "x"}, assertion=AssertionKind.SUCCESS, evidence=bundle_holder["bundle"]
        ),
        route_kind=RouteKind.APPROVED_MODEL,
        provider="model",
    )
    redacted = service.redact_for_external_model(
        ctx(), {"client": "Secret", "task": "draft"}, redact_keys={"client"}
    )
    route = RouteRequest(
        kind=RouteKind.APPROVED_MODEL,
        provider="model",
        redaction_attestation=redacted.attestation,
    )

    with pytest.raises(ProvenanceViolation, match="external_disclosure_mismatch"):
        service.execute(ctx(), "guarded_draft", {"payload": redacted.payload}, route=route)

    bundle_holder["bundle"] = service.provenance.claim_success(
        ctx(),
        operation="guarded_draft",
        source_ids=["ev"],
        external_disclosure=True,
        model_route="model",
    )
    result = service.execute(ctx(), "guarded_draft", {"payload": redacted.payload}, route=route)
    assert result.assertion is AssertionKind.SUCCESS
    assert result.evidence is bundle_holder["bundle"]


def test_cross_matter_evidence_rejection_is_audited() -> None:
    service = LegalService()
    other = ctx("OTHER-MATTER")
    digest = hashlib.sha256(b"other-record").hexdigest()
    service.provenance.add_source(
        other, source_id="other-ev", kind=SourceKind.RECORD, locator="record:2", sha256=digest
    )
    other_bundle = service.provenance.claim_success(
        other, operation="document_reader", source_ids=["other-ev"]
    )
    service.register_handler(
        "document_reader",
        lambda _ctx, _args: LegalToolResult(
            payload={"text": "x"}, assertion=AssertionKind.SUCCESS, evidence=other_bundle
        ),
    )
    with pytest.raises(MatterIsolationViolation, match="cross_matter_evidence_bundle"):
        service.execute(ctx(), "document_reader", {})
    assert service.audit_records[-1].outcome == "DENY"
    assert service.audit_records[-1].reason == "cross_matter_handler_evidence"


def test_wire_mapping_rejects_non_string_keys_instead_of_colliding() -> None:
    with pytest.raises(PolicyViolation, match="wire_mapping_requires_string_keys"):
        to_wire({1: "page one", "1": "citation"})


def test_wire_rejects_unordered_sets_unsupported_objects_and_nonfinite_floats() -> None:
    with pytest.raises(PolicyViolation, match="wire_collection_must_be_ordered"):
        to_wire({"citations": {"A", "B"}})
    with pytest.raises(PolicyViolation, match="wire_value_not_serializable"):
        to_wire({"value": object()})
    with pytest.raises(PolicyViolation, match="wire_float_must_be_finite"):
        to_wire({"value": float("nan")})


def test_transport_sanitizes_handler_exception_details() -> None:
    service = LegalService()
    secret = "PRIVILEGED-HANDLER-DETAIL"

    def handler(_ctx, _args):
        raise RuntimeError(secret)

    service.register_handler("document_reader", handler)
    with pytest.raises(LegalExecutionError, match="legal_tool_execution_failed") as caught:
        asyncio.run(
            invoke_transport(
                service,
                "document_reader",
                matter_id="M",
                arguments={},
                matter_authorizer=lambda matter_id: matter_id == "M",
                sensitivity=Sensitivity.LEGAL_PRIVILEGED,
                external_access=ExternalAccess.DENY,
            )
        )
    assert secret not in str(caught.value)
    assert service.audit_records[-1].outcome == "ERROR"
    assert secret not in repr(service.audit_records[-1])


def test_audit_records_policy_denial_without_payload() -> None:
    service = LegalService()
    service.register_handler("legal_retrieval", lambda _ctx, args: args)
    secret = "DO-NOT-LOG-THIS-PRIVILEGED-TEXT"
    with pytest.raises(PolicyViolation, match="route_kind_forbidden"):
        service.execute(
            ctx(),
            "legal_retrieval",
            {"query": secret},
            route=RouteRequest(kind=RouteKind.MONID, provider="monid"),
        )
    records = service.audit_records
    assert len(records) == 1
    assert records[0].outcome == "DENY"
    assert records[0].reason == "route_kind_forbidden"
    assert secret not in repr(records[0])


def test_audit_records_success_without_arguments() -> None:
    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, _args: {"ok": True})
    secret = "PRIVATE-CONTENT"
    result = service.execute(ctx(), "document_reader", {"text": secret})
    assert result.assertion is AssertionKind.NONE
    assert result.payload == {"ok": True}
    record = service.audit_records[-1]
    assert record.outcome == "EXECUTED"
    assert record.route_kind is RouteKind.LOCAL
    assert secret not in repr(record)


def test_async_handler_is_not_audited_success_until_await_completes() -> None:
    service = LegalService()

    async def handler(_ctx, _args):
        await asyncio.sleep(0)
        return {"ok": True}

    service.register_handler("document_reader", handler)
    pending = service.execute(ctx(), "document_reader", {})
    assert service.audit_records == ()
    result = asyncio.run(pending)
    assert result.assertion is AssertionKind.NONE
    assert result.payload == {"ok": True}
    assert service.audit_records[-1].outcome == "EXECUTED"


def test_async_handler_failure_is_audited_as_error_not_success() -> None:
    service = LegalService()

    async def handler(_ctx, _args):
        await asyncio.sleep(0)
        raise RuntimeError("private detail")

    service.register_handler("document_reader", handler)
    pending = service.execute(ctx(), "document_reader", {})
    with pytest.raises(RuntimeError, match="private detail"):
        asyncio.run(pending)
    assert service.audit_records[-1].outcome == "ERROR"
    assert service.audit_records[-1].reason == "handler_error"
    assert "private detail" not in repr(service.audit_records[-1])
