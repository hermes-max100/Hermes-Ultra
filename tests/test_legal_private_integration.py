from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hermes_ultra.legal import ExternalAccess, LegalContext, LegalService, MatterIsolationViolation, PolicyViolation, Sensitivity
from hermes_ultra.legal.mcp_server import _tool_wrapper
from hermes_ultra.legal.transport import invoke_transport

ROOT = Path(__file__).resolve().parents[1]
ALLOW_M1 = lambda matter_id: matter_id == "M-1"


def test_bot_mode_legal_entrypoints_match_private_legal_service() -> None:
    policy = json.loads((ROOT / "config/bot-mode-policy.json").read_text(encoding="utf-8"))
    legal_bot = next(bot for bot in policy["bots"] if bot["id"] == "legal")
    assert set(legal_bot["allowed_entrypoints"]) == set(LegalService().tool_names)
    assert legal_bot["externalization_authority"] is False
    assert "LEGAL_PRIVILEGED" in legal_bot["allowed_data_classes"]


def test_mcp_wrapper_preserves_exact_tool_name_without_importing_sdk() -> None:
    service = LegalService()
    wrapper = _tool_wrapper(
        service,
        "document_reader",
        matter_authorizer=ALLOW_M1,
        sensitivity=Sensitivity.LEGAL_PRIVILEGED,
        external_access=ExternalAccess.DENY,
    )
    assert wrapper.__name__ == "document_reader"
    assert "matter-scoped" in (wrapper.__doc__ or "")


def test_transport_server_owned_external_deny_cannot_be_escalated_by_call() -> None:
    service = LegalService()
    service.register_handler("legal_retrieval", lambda _ctx, args: args)
    with pytest.raises(PolicyViolation, match="external_access_denied"):
        asyncio.run(
            invoke_transport(
                service,
                "legal_retrieval",
                matter_id="M-1",
                arguments={"q": "x"},
                matter_authorizer=ALLOW_M1,
                external_access=ExternalAccess.DENY,
                route_kind="OFFICIAL_LEGAL_API",
                provider="official",
            )
        )


def test_transport_rejects_unauthorized_matter_before_dispatch() -> None:
    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, args: args)
    with pytest.raises(MatterIsolationViolation, match="matter_not_authorized"):
        asyncio.run(
            invoke_transport(
                service,
                "document_reader",
                matter_id="M-2",
                arguments={},
                matter_authorizer=ALLOW_M1,
            )
        )
    assert service.audit_records == ()


def test_transport_rejects_invalid_route_kind_before_dispatch() -> None:
    service = LegalService()
    service.register_handler("document_reader", lambda _ctx, args: args)
    with pytest.raises(PolicyViolation, match="invalid_route_kind"):
        asyncio.run(
            invoke_transport(
                service,
                "document_reader",
                matter_id="M-1",
                arguments={},
                matter_authorizer=ALLOW_M1,
                route_kind="NOT_A_ROUTE",
            )
        )


def test_transport_can_execute_local_handler_inside_authorized_matter() -> None:
    service = LegalService()
    service.put_resource(
        LegalContext(matter_id="M-1", external_access=ExternalAccess.DENY),
        resource_id="doc",
        value={"text": "private"},
    )
    service.register_handler(
        "document_reader",
        lambda ctx, args: service.get_resource(ctx, str(args["resource_id"])),
    )
    result = asyncio.run(
        invoke_transport(
            service,
            "document_reader",
            matter_id="M-1",
            arguments={"resource_id": "doc"},
            matter_authorizer=ALLOW_M1,
        )
    )
    assert result == {"text": "private"}
