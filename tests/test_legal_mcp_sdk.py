from __future__ import annotations

import asyncio

import pytest

mcp = pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from hermes_ultra.legal import LegalService  # noqa: E402
from hermes_ultra.legal import mcp_server as legal_mcp_server  # noqa: E402
from hermes_ultra.legal.mcp_server import create_mcp_http_app, create_mcp_server  # noqa: E402

AUTHORIZE = lambda matter_id: matter_id == "MCP-MATTER"


def test_mcp_v2_lists_tools_hides_trusted_controls_and_dispatches_through_service() -> None:
    async def scenario() -> None:
        service = LegalService()
        service.register_handler(
            "document_reader",
            lambda ctx, args: {"matter_id": ctx.matter_id, "resource_id": args["resource_id"]},
        )
        server = create_mcp_server(service, matter_authorizer=AUTHORIZE)
        async with Client(server) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == set(service.tool_names)
            reader = next(tool for tool in listed.tools if tool.name == "document_reader")
            properties = reader.input_schema.get("properties", {})
            assert "external_access" not in properties
            assert "sensitivity" not in properties

            result = await client.call_tool(
                "document_reader",
                {
                    "matter_id": "MCP-MATTER",
                    "arguments": {"resource_id": "record-1"},
                },
            )
            assert result.is_error is False
            assert service.audit_records[-1].outcome == "EXECUTED"
            assert service.audit_records[-1].matter_id == "MCP-MATTER"

    asyncio.run(scenario())


def test_mcp_v2_denies_external_route_by_server_default() -> None:
    async def scenario() -> None:
        service = LegalService()
        service.register_handler("legal_retrieval", lambda _ctx, args: args)
        server = create_mcp_server(service, matter_authorizer=AUTHORIZE)
        async with Client(server) as client:
            result = await client.call_tool(
                "legal_retrieval",
                {
                    "matter_id": "MCP-MATTER",
                    "arguments": {"q": "authority"},
                    "route_kind": "OFFICIAL_LEGAL_API",
                    "provider": "not-configured",
                },
            )
            assert result.is_error is True
            assert service.audit_records[-1].reason == "external_access_denied"

    asyncio.run(scenario())


def test_mcp_v2_denies_unauthorized_matter_before_service_dispatch() -> None:
    async def scenario() -> None:
        service = LegalService()
        service.register_handler("document_reader", lambda _ctx, args: args)
        server = create_mcp_server(service, matter_authorizer=AUTHORIZE)
        async with Client(server) as client:
            result = await client.call_tool(
                "document_reader",
                {"matter_id": "OTHER-MATTER", "arguments": {}},
            )
            assert result.is_error is True
            assert service.audit_records == ()

    asyncio.run(scenario())


def test_legal_http_app_is_stateless_for_modern_and_legacy_clients(monkeypatch) -> None:
    calls: dict[str, object] = {}
    sentinel = object()

    class FakeServer:
        def streamable_http_app(self, **kwargs):
            calls.update(kwargs)
            return sentinel

    monkeypatch.setattr(legal_mcp_server, "create_mcp_server", lambda *args, **kwargs: FakeServer())

    app = create_mcp_http_app(
        matter_authorizer=AUTHORIZE,
        host="127.0.0.1",
    )

    assert app is sentinel
    assert calls["stateless_http"] is True
    assert calls["json_response"] is True
    assert calls["host"] == "127.0.0.1"
    assert "event_store" not in calls


def test_legal_http_app_requires_explicit_transport_security_off_loopback() -> None:
    with pytest.raises(ValueError, match="transport_security"):
        create_mcp_http_app(
            matter_authorizer=AUTHORIZE,
            host="legal.internal",
        )
