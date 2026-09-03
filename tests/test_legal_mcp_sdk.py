from __future__ import annotations

import asyncio

import pytest

mcp = pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from hermes_ultra.legal import LegalService  # noqa: E402
from hermes_ultra.legal.mcp_server import create_mcp_server  # noqa: E402


def test_mcp_v2_lists_all_private_legal_tools_and_dispatches_through_service() -> None:
    async def scenario() -> None:
        service = LegalService()
        service.register_handler(
            "document_reader",
            lambda ctx, args: {"matter_id": ctx.matter_id, "resource_id": args["resource_id"]},
        )
        server = create_mcp_server(service)
        async with Client(server) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == set(service.tool_names)

            result = await client.call_tool(
                "document_reader",
                {
                    "matter_id": "MCP-MATTER",
                    "arguments": {"resource_id": "record-1"},
                },
            )
            assert result.is_error is False
            assert result.structured_content == {
                "matter_id": "MCP-MATTER",
                "resource_id": "record-1",
            }

    asyncio.run(scenario())


def test_mcp_v2_denies_external_route_by_default() -> None:
    async def scenario() -> None:
        service = LegalService()
        service.register_handler("legal_retrieval", lambda _ctx, args: args)
        server = create_mcp_server(service)
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

    asyncio.run(scenario())
