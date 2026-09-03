from __future__ import annotations

import pytest

from hermes_ultra.legal import (
    EvidenceBundle,
    LegalContext,
    LegalPolicy,
    PolicyViolation,
    ProvenanceViolation,
    RouteKind,
    RouteRequest,
)


def test_provider_allowlists_require_exact_frozensets() -> None:
    with pytest.raises(PolicyViolation, match="official_legal_providers_must_be_frozenset"):
        LegalPolicy(official_legal_providers="official-court")  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="approved_model_providers_must_be_frozenset"):
        LegalPolicy(approved_model_providers=["model"])  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="invalid_official_legal_providers"):
        LegalPolicy(official_legal_providers=frozenset({" official-court"}))


def test_policy_rejects_non_contract_context_and_route_objects() -> None:
    policy = LegalPolicy()
    with pytest.raises(PolicyViolation, match="legal_context_required"):
        policy.authorize(object(), RouteRequest(kind=RouteKind.LOCAL))  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation, match="route_request_required"):
        policy.authorize(LegalContext(matter_id="M"), object())  # type: ignore[arg-type]


def test_evidence_bundle_rejects_runtime_type_spoofing() -> None:
    with pytest.raises(ProvenanceViolation, match="external_disclosure_must_be_bool"):
        EvidenceBundle(
            matter_id="M",
            operation="document_reader",
            source_ids=("s1",),
            authority_ids=(),
            external_disclosure=1,  # type: ignore[arg-type]
            model_route=None,
            verified=True,
        )
    with pytest.raises(ProvenanceViolation, match="verified_must_be_bool"):
        EvidenceBundle(
            matter_id="M",
            operation="document_reader",
            source_ids=("s1",),
            authority_ids=(),
            external_disclosure=False,
            model_route=None,
            verified=1,  # type: ignore[arg-type]
        )
    with pytest.raises(ProvenanceViolation, match="source_ids_must_be_tuple"):
        EvidenceBundle(
            matter_id="M",
            operation="document_reader",
            source_ids=["s1"],  # type: ignore[arg-type]
            authority_ids=(),
            external_disclosure=False,
            model_route=None,
            verified=True,
        )
