from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from hermes_ultra.legal import (
    ExternalAccess,
    LegalContext,
    LegalExecutionError,
    LegalPolicy,
    LegalService,
    MatterIsolationViolation,
    PolicyDecision,
    PolicyViolation,
    RouteKind,
    RouteRequest,
)
from hermes_ultra.legal.fastapi_adapter import create_fastapi_router
from hermes_ultra.legal.transport import invoke_transport


ALLOW_M1 = lambda matter_id: matter_id == "M-1"


def allow_ctx(matter_id: str = "M-1") -> LegalContext:
    return LegalContext(matter_id=matter_id, external_access=ExternalAccess.ALLOWLIST)


class _FlipPayloadMapping(Mapping[str, Any]):
    """Return one payload for attestation and another on a second read."""

    def __init__(self, first: Any, second: Any) -> None:
        self.first = first
        self.second = second
        self.reads = 0

    def __getitem__(self, key: str) -> Any:
        if key != "payload":
            raise KeyError(key)
        self.reads += 1
        return self.first if self.reads == 1 else self.second

    def __iter__(self) -> Iterator[str]:
        return iter(("payload",))

    def __len__(self) -> int:
        return 1


def test_approved_model_verifies_and_dispatches_one_argument_snapshot() -> None:
    service = LegalService(
        policy=LegalPolicy(approved_model_providers=frozenset({"model"})),
        redaction_key=b"r" * 32,
    )
    received: list[Any] = []
    service.register_handler(
        "guarded_draft",
        lambda _ctx, args: received.append(args["payload"]) or args["payload"],
        route_kind=RouteKind.APPROVED_MODEL,
        provider="model",
    )
    redacted = service.redact_for_external_model(
        allow_ctx(), {"client": "Secret", "task": "draft"}, redact_keys={"client"}
    )
    changing = _FlipPayloadMapping(
        redacted.payload,
        {"client": "UNREDACTED-PRIVILEGED-TEXT", "task": "draft"},
    )
    result = service.execute(
        allow_ctx(),
        "guarded_draft",
        changing,
        route=RouteRequest(
            kind=RouteKind.APPROVED_MODEL,
            provider="model",
            redaction_attestation=redacted.attestation,
        ),
    )
    assert result.payload == redacted.payload
    assert received == [redacted.payload]
    assert changing.reads == 1


def test_handler_boundary_error_is_sanitized_at_transport_boundary() -> None:
    secret = "PRIVATE-PROVIDER-DETAIL"
    service = LegalService()

    def handler(_ctx: LegalContext, _args: Mapping[str, Any]) -> Any:
        raise PolicyViolation(secret)

    service.register_handler("document_reader", handler)
    with pytest.raises(LegalExecutionError, match="legal_tool_execution_failed") as excinfo:
        asyncio.run(
            invoke_transport(
                service,
                "document_reader",
                matter_id="M-1",
                arguments={},
                matter_authorizer=ALLOW_M1,
            )
        )
    assert secret not in str(excinfo.value)
    assert service.audit_records[-1].outcome == "ERROR"
    assert service.audit_records[-1].reason == "handler_error"


def test_transport_serialization_failure_is_audited_as_error_not_execution() -> None:
    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, _args: {"unordered": {"A", "B"}})
    with pytest.raises(LegalExecutionError, match="legal_tool_execution_failed"):
        asyncio.run(
            invoke_transport(
                service,
                "document_reader",
                matter_id="M-1",
                arguments={},
                matter_authorizer=ALLOW_M1,
            )
        )
    assert [record.outcome for record in service.audit_records] == ["ERROR"]
    assert service.audit_records[-1].reason == "result_serialization_error"


class _BarrierValue:
    def __init__(self, barrier: threading.Barrier, marker: str) -> None:
        self.barrier = barrier
        self.marker = marker

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, str]:
        self.barrier.wait(timeout=5)
        return {"marker": self.marker}


def test_cross_matter_resource_claim_is_atomic_under_concurrency() -> None:
    service = LegalService()
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []
    outcomes_lock = threading.Lock()

    def writer(matter_id: str) -> None:
        try:
            service.put_resource(
                LegalContext(matter_id=matter_id),
                resource_id="same-id",
                value=_BarrierValue(barrier, matter_id),
            )
        except MatterIsolationViolation:
            outcome = (matter_id, "DENY")
        else:
            outcome = (matter_id, "OK")
        with outcomes_lock:
            outcomes.append(outcome)

    first = threading.Thread(target=writer, args=("M-1",))
    second = threading.Thread(target=writer, args=("M-2",))
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(status for _, status in outcomes) == ["DENY", "OK"]

    winner = next(matter for matter, status in outcomes if status == "OK")
    loser = next(matter for matter, status in outcomes if status == "DENY")
    assert service.get_resource(LegalContext(matter_id=winner), "same-id") == {"marker": winner}
    with pytest.raises(MatterIsolationViolation):
        service.get_resource(LegalContext(matter_id=loser), "same-id")


class _DenyPolicy(LegalPolicy):
    def authorize(self, context: LegalContext, route: RouteRequest) -> PolicyDecision:
        return PolicyDecision(False, "deployment_denied", route)


class _InvalidDecisionPolicy(LegalPolicy):
    def authorize(self, context: LegalContext, route: RouteRequest) -> Any:
        return True


def test_explicit_policy_denial_and_invalid_decisions_fail_closed() -> None:
    called: list[bool] = []
    service = LegalService(policy=_DenyPolicy())
    service.register_handler("document_reader", lambda _ctx, _args: called.append(True))
    with pytest.raises(PolicyViolation, match="policy_denied"):
        service.execute(LegalContext(matter_id="M-1"), "document_reader", {})
    assert called == []
    assert service.audit_records[-1].reason == "policy_denied"

    invalid = LegalService(policy=_InvalidDecisionPolicy())
    invalid.register_handler("document_reader", lambda _ctx, _args: None)
    with pytest.raises(PolicyViolation, match="invalid_policy_decision"):
        invalid.execute(LegalContext(matter_id="M-1"), "document_reader", {})


def test_falsey_non_route_does_not_default_to_local() -> None:
    called: list[bool] = []
    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, _args: called.append(True))
    for malformed in ("", 0, {}):
        with pytest.raises(PolicyViolation, match="route_request_required"):
            service.execute(  # type: ignore[arg-type]
                LegalContext(matter_id="M-1"), "document_reader", {}, route=malformed
            )
    assert called == []


class _EvilFrozenSet(frozenset[str]):
    def __contains__(self, item: object) -> bool:
        return True


def test_provider_allowlist_rejects_frozenset_subclasses() -> None:
    with pytest.raises(PolicyViolation, match="official_legal_providers_must_be_frozenset"):
        LegalPolicy(official_legal_providers=_EvilFrozenSet())
    with pytest.raises(PolicyViolation, match="approved_model_providers_must_be_frozenset"):
        LegalPolicy(approved_model_providers=_EvilFrozenSet())


def test_fastapi_non_object_validation_never_echoes_privileged_input() -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, args: args)
    app = FastAPI()
    app.include_router(create_fastapi_router(service, matter_authorizer=ALLOW_M1))
    secret = "TOP-SECRET-LEGAL-PAYLOAD"
    response = TestClient(app).post("/legal/tools/document_reader", json=secret)
    assert response.status_code != 422
    assert secret not in response.text
    assert response.status_code == 403
