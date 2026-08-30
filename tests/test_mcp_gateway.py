from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_ultra.delegated_identity import DelegatedIdentity
from hermes_ultra.mcp_gateway import MCP_PROTOCOL_VERSION, McpGateway, McpGatewayError, McpProvider
from hermes_ultra.skill_lifecycle import LifecycleState


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, *, method, params, headers):
        self.calls.append({"method": method, "params": dict(params), "headers": dict(headers)})
        response = self.responses[method]
        if isinstance(response, list):
            return response.pop(0)
        return response


def active_provider(**overrides) -> McpProvider:
    values = {
        "provider_id": "playwright",
        "transport_type": "streamable-http",
        "profiles": frozenset({"coding"}),
        "state": LifecycleState.ACTIVE,
    }
    values.update(overrides)
    return McpProvider(**values)


def tool_payload(*, ttl_ms=0, scope="private"):
    return {
        "result": {
            "tools": [
                {
                    "name": "browser.navigate",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": False},
                    "_meta": {"com.hermes.ultra/capabilities": ["browser.write"]},
                },
                {
                    "name": "browser.snapshot",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": True},
                    "_meta": {"com.hermes.ultra/capabilities": ["browser.read"]},
                },
            ],
            "ttlMs": ttl_ms,
            "cacheScope": scope,
        }
    }


def identity(*, capabilities=frozenset({"browser.read", "browser.write"})):
    return DelegatedIdentity.root(
        owner="owner",
        subject="worker",
        capabilities=capabilities,
        profiles={"coding"},
        providers={"playwright"},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_server_discover_uses_stateless_2026_envelope_and_caches() -> None:
    transport = FakeTransport({
        "server/discover": {
            "result": {
                "supportedVersions": [MCP_PROTOCOL_VERSION],
                "capabilities": {"tools": {}},
                "ttlMs": 5000,
                "cacheScope": "private",
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "pw", "version": "1"}},
            }
        }
    })
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    first = gateway.discover("playwright")
    second = gateway.discover("playwright")
    assert first == second
    assert len(transport.calls) == 1
    assert transport.calls[0]["headers"]["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION
    assert transport.calls[0]["headers"]["Mcp-Method"] == "server/discover"
    assert "Mcp-Session-Id" not in transport.calls[0]["headers"]
    assert first.server_info == {"name": "pw", "version": "1"}


def test_private_cache_is_partitioned_by_authorization_context() -> None:
    transport = FakeTransport({"tools/list": [tool_payload(ttl_ms=5000), tool_payload(ttl_ms=5000)]})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    gateway.refresh_tools("playwright", authorization_context="tenant-a")
    gateway.refresh_tools("playwright", authorization_context="tenant-b")
    gateway.refresh_tools("playwright", authorization_context="tenant-a")
    assert len(transport.calls) == 2


def test_profile_override_exposes_active_provider_without_permanent_rebind() -> None:
    transport = FakeTransport({"tools/list": tool_payload()})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    assert gateway.visible_tools(profile="research", capabilities={"browser"}) == ()
    visible = gateway.visible_tools(
        profile="research",
        capabilities={"browser"},
        provider_overrides={"playwright"},
    )
    assert {tool.name for tool in visible} == {"browser.navigate", "browser.snapshot"}
    assert "research" not in gateway.provider("playwright").profiles


def test_override_cannot_activate_candidate_provider() -> None:
    transport = FakeTransport({"tools/list": tool_payload()})
    gateway = McpGateway()
    gateway.register(active_provider(state=LifecycleState.CANDIDATE), transport)
    assert gateway.visible_tools(
        profile="research",
        provider_overrides={"playwright"},
        capabilities={"browser"},
    ) == ()


def test_visible_tools_are_narrowed_by_delegated_capabilities() -> None:
    transport = FakeTransport({"tools/list": tool_payload()})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    visible = gateway.visible_tools(
        profile="coding",
        capabilities={"browser"},
        identity=identity(capabilities=frozenset({"browser.read"})),
    )
    assert [tool.name for tool in visible] == ["browser.snapshot"]


def test_call_tool_requires_delegated_capability_and_mirrors_name() -> None:
    transport = FakeTransport({"tools/list": tool_payload(), "tools/call": {"result": {"content": []}}})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    with pytest.raises(PermissionError, match="capability"):
        gateway.call_tool("playwright", "browser.navigate", {}, identity=identity(capabilities=frozenset({"browser.read"})))
    result = gateway.call_tool("playwright", "browser.snapshot", {}, identity=identity(capabilities=frozenset({"browser.read"})))
    assert result == {"content": []}
    assert transport.calls[-1]["headers"]["Mcp-Name"] == "browser.snapshot"


def test_paginated_tool_catalog_is_combined_before_caching() -> None:
    first = tool_payload(ttl_ms=5000)
    first["result"]["tools"] = [first["result"]["tools"][0]]
    first["result"]["nextCursor"] = "page-2"
    second = tool_payload(ttl_ms=3000)
    second["result"]["tools"] = [second["result"]["tools"][1]]
    transport = FakeTransport({"tools/list": [first, second]})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    catalog = gateway.refresh_tools("playwright")
    cached = gateway.refresh_tools("playwright")
    assert {tool.name for tool in catalog} == {"browser.navigate", "browser.snapshot"}
    assert cached == catalog
    assert len(transport.calls) == 2
    assert transport.calls[1]["params"]["cursor"] == "page-2"


def test_streamable_http_mirrors_nested_x_mcp_header_values_safely() -> None:
    payload = tool_payload()
    payload["result"]["tools"] = [
        {
            "name": "tenant.query",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "routing": {
                        "type": "object",
                        "properties": {
                            "tenant": {"type": "string", "x-mcp-header": "Tenant"},
                            "attempt": {"type": "integer", "x-mcp-header": "Attempt"},
                        },
                    }
                },
            },
            "_meta": {"com.hermes.ultra/capabilities": ["query"]},
        }
    ]
    transport = FakeTransport({"tools/list": payload, "tools/call": {"result": {"content": []}}})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    query_identity = identity(capabilities=frozenset({"query"}))
    gateway.call_tool(
        "playwright",
        "tenant.query",
        {"routing": {"tenant": " west coast ", "attempt": 7}},
        identity=query_identity,
    )
    headers = transport.calls[-1]["headers"]
    assert headers["Mcp-Param-Attempt"] == "7"
    assert headers["Mcp-Param-Tenant"].startswith("=?base64?")
    assert headers["Mcp-Param-Tenant"].endswith("?=")


def test_invalid_x_mcp_header_tool_is_excluded_for_http_provider() -> None:
    payload = tool_payload()
    payload["result"]["tools"] = [
        {
            "name": "bad.route",
            "inputSchema": {
                "type": "object",
                "properties": {"ratio": {"type": "object", "x-mcp-header": "Route"}},
            },
        },
        payload["result"]["tools"][1],
    ]
    transport = FakeTransport({"tools/list": payload})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    assert [tool.name for tool in gateway.refresh_tools("playwright")] == ["browser.snapshot"]


def test_duplicate_x_mcp_header_names_exclude_tool() -> None:
    payload = tool_payload()
    payload["result"]["tools"] = [
        {
            "name": "bad.duplicate",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "x-mcp-header": "Tenant"},
                    "b": {"type": "string", "x-mcp-header": "tenant"},
                },
            },
        }
    ]
    transport = FakeTransport({"tools/list": payload})
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    assert gateway.refresh_tools("playwright") == ()


def test_discover_rejects_server_without_supported_protocol() -> None:
    transport = FakeTransport({
        "server/discover": {"result": {"supportedVersions": ["2025-11-25"], "capabilities": {}}}
    })
    gateway = McpGateway()
    gateway.register(active_provider(), transport)
    with pytest.raises(McpGatewayError, match="does not support"):
        gateway.discover("playwright")
