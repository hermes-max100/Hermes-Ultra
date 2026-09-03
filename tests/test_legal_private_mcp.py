from __future__ import annotations

import hashlib

import pytest

from hermes_ultra.legal import (
    AssertionKind,
    ExternalAccess,
    LegalContext,
    LegalPolicy,
    LegalService,
    MatterIsolationViolation,
    PolicyViolation,
    ProvenanceViolation,
    RouteKind,
    RouteRequest,
    SourceKind,
)


def context(*, matter_id: str = "MATTER-1", external: ExternalAccess = ExternalAccess.ALLOWLIST) -> LegalContext:
    return LegalContext(matter_id=matter_id, external_access=external)


def test_privileged_legal_blocks_dynamic_and_unknown_brokers() -> None:
    policy = LegalPolicy()
    ctx = context()
    for kind in (RouteKind.MONID, RouteKind.PUBLIC_MCP, RouteKind.UNKNOWN):
        with pytest.raises(PolicyViolation):
            policy.authorize(ctx, RouteRequest(kind=kind, provider="anything"))


def test_external_access_deny_blocks_even_allowlisted_provider() -> None:
    policy = LegalPolicy(official_legal_providers=frozenset({"official-court"}))
    ctx = context(external=ExternalAccess.DENY)
    with pytest.raises(PolicyViolation, match="external_access_denied"):
        policy.authorize(
            ctx,
            RouteRequest(kind=RouteKind.OFFICIAL_LEGAL_API, provider="official-court"),
        )


def test_official_provider_must_be_explicitly_allowlisted() -> None:
    policy = LegalPolicy(official_legal_providers=frozenset({"official-court"}))
    allowed = policy.authorize(
        context(),
        RouteRequest(kind=RouteKind.OFFICIAL_LEGAL_API, provider="official-court"),
    )
    assert allowed.allowed is True
    with pytest.raises(PolicyViolation, match="provider_not_allowlisted"):
        policy.authorize(
            context(),
            RouteRequest(kind=RouteKind.OFFICIAL_LEGAL_API, provider="other"),
        )


def test_external_model_requires_allowlist_and_redaction_attestation() -> None:
    policy = LegalPolicy(approved_model_providers=frozenset({"approved-model"}))
    ctx = context()
    with pytest.raises(PolicyViolation, match="external_model_redaction_attestation_required"):
        policy.authorize(
            ctx,
            RouteRequest(kind=RouteKind.APPROVED_MODEL, provider="approved-model"),
        )
    with pytest.raises(PolicyViolation, match="provider_not_allowlisted"):
        policy.authorize(
            ctx,
            RouteRequest(
                kind=RouteKind.APPROVED_MODEL,
                provider="unapproved",
                redaction_attestation="not-trusted-by-service",
            ),
        )
    assert policy.authorize(
        ctx,
        RouteRequest(
            kind=RouteKind.APPROVED_MODEL,
            provider="approved-model",
            redaction_attestation="service-will-verify-this",
        ),
    ).allowed


def test_matter_store_rejects_cross_matter_reads() -> None:
    service = LegalService()
    service.put_resource(context(), resource_id="doc-1", value={"text": "privileged"})
    assert service.get_resource(context(), "doc-1") == {"text": "privileged"}
    with pytest.raises(MatterIsolationViolation):
        service.get_resource(context(matter_id="MATTER-2"), "doc-1")


def test_verified_fact_requires_source_and_verified_citation_requires_authority() -> None:
    service = LegalService()
    ctx = context()
    with pytest.raises(ProvenanceViolation, match="verified_fact_requires_source"):
        service.provenance.verify_fact(ctx, source_ids=[])
    with pytest.raises(ProvenanceViolation, match="verified_citation_requires_authority"):
        service.provenance.verify_citation(ctx, authority_source_ids=[])

    digest = hashlib.sha256(b"record page").hexdigest()
    service.provenance.add_source(
        ctx,
        source_id="record-1",
        kind=SourceKind.RECORD,
        locator="record.pdf#page=10",
        sha256=digest,
    )
    service.provenance.add_source(
        ctx,
        source_id="authority-1",
        kind=SourceKind.AUTHORITY,
        locator="official-source",
        sha256=digest,
    )
    service.provenance.verify_fact(ctx, source_ids=["record-1"])
    service.provenance.verify_citation(ctx, authority_source_ids=["authority-1"])


def test_source_ids_are_matter_isolated() -> None:
    service = LegalService()
    digest = hashlib.sha256(b"x").hexdigest()
    service.provenance.add_source(
        context(), source_id="source-1", kind=SourceKind.RECORD, locator="p1", sha256=digest
    )
    with pytest.raises(MatterIsolationViolation):
        service.provenance.verify_fact(context(matter_id="MATTER-2"), source_ids=["source-1"])


def test_success_claim_requires_nonempty_evidence_bundle() -> None:
    service = LegalService()
    ctx = context()
    with pytest.raises(ProvenanceViolation, match="success_requires_evidence_bundle"):
        service.provenance.claim_success(ctx, operation="guarded_draft", source_ids=[])

    digest = hashlib.sha256(b"evidence").hexdigest()
    service.provenance.add_source(
        ctx, source_id="ev-1", kind=SourceKind.RECORD, locator="record:1", sha256=digest
    )
    bundle = service.provenance.claim_success(
        ctx, operation="guarded_draft", source_ids=["ev-1"]
    )
    assert bundle.verified is True
    assert bundle.matter_id == "MATTER-1"
    assert bundle.source_ids == ("ev-1",)


def test_redaction_is_recursive_and_attestation_binds_exact_payload() -> None:
    policy = LegalPolicy(approved_model_providers=frozenset({"approved-model"}))
    service = LegalService(policy=policy, redaction_key=b"k" * 32)
    ctx = context()
    redacted = service.redact_for_external_model(
        ctx,
        {"client": "Jane Doe", "nested": {"token": "secret", "safe": "keep"}},
        redact_keys={"client", "token"},
    )
    assert redacted.payload == {
        "client": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "safe": "keep"},
    }
    assert redacted.redacted is True
    assert redacted.attestation.startswith("hrp1.")

    service.register_handler(
        "guarded_draft",
        lambda _ctx, args: args["payload"],
        route_kind=RouteKind.APPROVED_MODEL,
        provider="approved-model",
    )
    result = service.execute(
        ctx,
        "guarded_draft",
        {"payload": redacted.payload},
        route=RouteRequest(
            kind=RouteKind.APPROVED_MODEL,
            provider="approved-model",
            redaction_attestation=redacted.attestation,
        ),
    )
    assert result.assertion is AssertionKind.NONE
    assert result.payload == redacted.payload


def test_all_legal_tools_are_registered_and_missing_handlers_fail_closed() -> None:
    service = LegalService()
    expected = {
        "document_reader",
        "legal_retrieval",
        "citation_validator",
        "guarded_draft",
        "case_record_search",
        "timeline_builder",
        "exhibit_indexer",
        "record_fact_extractor",
        "authority_checker",
        "redact_for_external_model",
        "compare_filings",
        "record_citation_resolver",
        "perseus_remember",
        "perseus_recall",
    }
    assert set(service.tool_names) == expected
    with pytest.raises(PolicyViolation, match="tool_handler_unavailable"):
        service.execute(context(), "document_reader", {})


def test_registered_handler_cannot_bypass_route_policy() -> None:
    service = LegalService()
    service.register_handler("legal_retrieval", lambda _ctx, args: args)
    with pytest.raises(PolicyViolation, match="route_kind_forbidden"):
        service.execute(
            context(),
            "legal_retrieval",
            {"q": "case"},
            route=RouteRequest(kind=RouteKind.MONID, provider="monid"),
        )


def test_local_registered_handler_executes_inside_matter_context() -> None:
    service = LegalService()
    service.register_handler("document_reader", lambda ctx, args: {"matter": ctx.matter_id, **args})
    result = service.execute(context(), "document_reader", {"doc": "A"})
    assert result.assertion is AssertionKind.NONE
    assert result.payload == {"matter": "MATTER-1", "doc": "A"}
