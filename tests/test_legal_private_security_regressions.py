from __future__ import annotations

import pytest

from hermes_ultra.legal import ExternalAccess, LegalContext, LegalPolicy, LegalService, PolicyViolation, RouteKind, RouteRequest


def ctx() -> LegalContext:
    return LegalContext(matter_id="SECURITY-MATTER", external_access=ExternalAccess.ALLOWLIST)


def test_redaction_cannot_attest_empty_or_missing_targets() -> None:
    service = LegalService()
    with pytest.raises(PolicyViolation, match="redact_keys_required"):
        service.redact_for_external_model(ctx(), {"safe": "value"}, redact_keys=set())
    with pytest.raises(PolicyViolation, match="redaction_target_not_found"):
        service.redact_for_external_model(ctx(), {"safe": "value"}, redact_keys={"client"})


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
    policy = LegalPolicy()
    service = LegalService(policy=policy)
    service.register_handler("document_reader", lambda _ctx, _args: {"ok": True})
    secret = "PRIVATE-CONTENT"
    assert service.execute(ctx(), "document_reader", {"text": secret}) == {"ok": True}
    record = service.audit_records[-1]
    assert record.outcome == "EXECUTED"
    assert record.route_kind is RouteKind.LOCAL
    assert secret not in repr(record)
