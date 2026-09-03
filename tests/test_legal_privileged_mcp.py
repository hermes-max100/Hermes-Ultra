from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_ultra.delegated_identity import DelegatedIdentity
from hermes_ultra.mcp_gateway import (
    MCP_PROTOCOL_VERSION,
    McpGateway,
    McpPrivilegedRequestContext,
    McpProvider,
)
from hermes_ultra.skill_lifecycle import LifecycleState


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, *, method, params, headers):
        self.calls.append({"method": method, "params": dict(params), "headers": dict(headers)})
        if method == "tools/list":
            return {
                "result": {
                    "tools": [
                        {
                            "name": "legal_retrieval",
                            "inputSchema": {"type": "object", "properties": {}},
                            "annotations": {"readOnlyHint": True},
                            "_meta": {"com.hermes.ultra/capabilities": ["legal.read"]},
                        }
                    ]
                }
            }
        if method == "tools/call":
            return {"result": {"content": []}}
        raise AssertionError(f"unexpected method: {method}")


def legal_provider() -> McpProvider:
    return McpProvider(
        provider_id="private-legal",
        transport_type="streamable-http",
        profiles=frozenset({"LEGAL_PRIVILEGED"}),
        state=LifecycleState.ACTIVE,
        authorization_context="legal-default",
    )


def legal_identity() -> DelegatedIdentity:
    return DelegatedIdentity.root(
        owner="owner",
        subject="legal-worker",
        capabilities={"legal.read"},
        profiles={"LEGAL_PRIVILEGED"},
        providers={"private-legal"},
        task_id="legal-task-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def legal_context() -> McpPrivilegedRequestContext:
    return McpPrivilegedRequestContext(
        authorization_context="case:E088165",
        provenance_ref="sha256:0123456789abcdef",
        audit_ref="evidence:legal-task-1",
    )


def test_legal_privileged_tool_call_requires_delegated_identity() -> None:
    gateway = McpGateway()
    gateway.register(legal_provider(), FakeTransport())

    with pytest.raises(PermissionError, match="delegated identity"):
        gateway.call_tool(
            "private-legal",
            "legal_retrieval",
            {},
            request_context=legal_context(),
        )


def test_legal_privileged_tool_call_requires_governance_context() -> None:
    gateway = McpGateway()
    gateway.register(legal_provider(), FakeTransport())

    with pytest.raises(PermissionError, match="request context"):
        gateway.call_tool(
            "private-legal",
            "legal_retrieval",
            {},
            identity=legal_identity(),
        )


def test_legal_privileged_request_is_stateless_and_self_describing() -> None:
    transport = FakeTransport()
    gateway = McpGateway()
    gateway.register(legal_provider(), transport)

    result = gateway.call_tool(
        "private-legal",
        "legal_retrieval",
        {},
        identity=legal_identity(),
        request_context=legal_context(),
    )

    assert result == {"content": []}
    assert [call["method"] for call in transport.calls] == ["tools/list", "tools/call"]
    for call in transport.calls:
        headers = call["headers"]
        params = call["params"]
        assert headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION
        assert "Mcp-Session-Id" not in headers
        meta = params["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == MCP_PROTOCOL_VERSION
        governed = meta["com.hermes.ultra/privilegedRequest"]
        assert governed == {
            "profile": "LEGAL_PRIVILEGED",
            "authorizationContext": "case:E088165",
            "provenanceRef": "sha256:0123456789abcdef",
            "auditRef": "evidence:legal-task-1",
            "stateless": True,
        }
        assert "com.hermes.ultra/delegatedIdentity" in meta


def test_legal_privileged_provider_requires_stateless_http_transport() -> None:
    gateway = McpGateway()
    gateway.register(
        McpProvider(
            provider_id="private-legal",
            transport_type="stdio",
            profiles=frozenset({"LEGAL_PRIVILEGED"}),
            state=LifecycleState.ACTIVE,
        ),
        FakeTransport(),
    )

    with pytest.raises(PermissionError, match="streamable-http"):
        gateway.refresh_tools(
            "private-legal",
            identity=legal_identity(),
            request_context=legal_context(),
        )


def test_non_privileged_provider_remains_backward_compatible() -> None:
    transport = FakeTransport()
    gateway = McpGateway()
    gateway.register(
        McpProvider(
            provider_id="ordinary",
            transport_type="streamable-http",
            profiles=frozenset({"research"}),
            state=LifecycleState.ACTIVE,
        ),
        transport,
    )

    tools = gateway.refresh_tools("ordinary")

    assert [tool.name for tool in tools] == ["legal_retrieval"]
    assert "com.hermes.ultra/privilegedRequest" not in transport.calls[0]["params"]["_meta"]
