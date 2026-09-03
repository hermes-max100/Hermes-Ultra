from __future__ import annotations

import asyncio

import pytest

from hermes_ultra.legal import ExternalAccess, LegalContext, LegalPolicy, LegalService, PolicyViolation, RouteKind, RouteRequest
from hermes_ultra.legal.transport import to_wire


def ctx(matter_id: str = "SECURITY-MATTER") -> LegalContext:
    return LegalContext(matter_id=matter_id, external_access=ExternalAccess.ALLOWLIST)


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

    assert service.execute(
        ctx(),
        "legal_retrieval",
        {"query": "x"},
        route=RouteRequest(kind=RouteKind.OFFICIAL_LEGAL_API, provider="official-court"),
    ) == {"source": "external"}


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


def test_wire_mapping_rejects_non_string_keys_instead_of_colliding() -> None:
    with pytest.raises(PolicyViolation, match="wire_mapping_requires_string_keys"):
        to_wire({1: "page one", "1": "citation"})


def test_wire_rejects_unordered_sets_for_deterministic_legal_results() -> None:
    with pytest.raises(PolicyViolation, match="wire_collection_must_be_ordered"):
        to_wire({"citations": {"A", "B"}})


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
    assert service.execute(ctx(), "document_reader", {"text": secret}) == {"ok": True}
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
    assert asyncio.run(pending) == {"ok": True}
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
