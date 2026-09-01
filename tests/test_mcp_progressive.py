from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hermes_ultra.autonomy import ActionContext, ApprovalRegistry
from hermes_ultra.delegated_identity import DelegatedIdentity
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.mcp_gateway import McpGateway, McpProvider
from hermes_ultra.mcp_progressive import McpProgressiveCapabilityFacade
from hermes_ultra.skill_lifecycle import LifecycleState


@dataclass(frozen=True)
class Task:
    task_id: str
    objective: str
    capability_hints: frozenset[str] = frozenset()


class FakeTransport:
    def __init__(self, tools: list[dict[str, object]]) -> None:
        self.tools = tools
        self.calls: list[dict[str, object]] = []

    def request(self, *, method, params, headers):
        self.calls.append({"method": method, "params": dict(params), "headers": dict(headers)})
        if method == "tools/list":
            return {"result": {"tools": self.tools}}
        if method == "tools/call":
            return {
                "result": {
                    "content": [],
                    "called": params["name"],
                    "arguments": dict(params["arguments"]),
                }
            }
        raise AssertionError(method)


def _tool(name: str, *, capability: str, read_only: bool, destructive: bool = False):
    return {
        "name": name,
        "description": f"Tool for {name}",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
        },
        "_meta": {"com.hermes.ultra/capabilities": [capability]},
    }


def _provider(provider_id: str, *, state: LifecycleState = LifecycleState.ACTIVE) -> McpProvider:
    return McpProvider(
        provider_id=provider_id,
        transport_type="streamable-http",
        profiles=frozenset({"coding"}),
        state=state,
    )


def _identity(*, capabilities: frozenset[str]) -> DelegatedIdentity:
    return DelegatedIdentity.root(
        owner="owner",
        subject="worker",
        capabilities=capabilities,
        profiles={"coding"},
        providers={"playwright"},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _facade(gateway: McpGateway) -> McpProgressiveCapabilityFacade:
    return McpProgressiveCapabilityFacade(
        gateway,
        approval_registry=ApprovalRegistry({"production_deploy", "spend_money"}),
        evidence_recorder=EvidenceRecorder(),
    )


def test_discovery_exposes_compact_active_governed_mcp_capabilities_only():
    gateway = McpGateway()
    active = FakeTransport(
        [
            _tool("browser.snapshot", capability="browser.read", read_only=True),
            _tool("browser.navigate", capability="browser.write", read_only=False),
        ]
    )
    candidate = FakeTransport([_tool("candidate.tool", capability="candidate", read_only=True)])
    gateway.register(_provider("playwright"), active)
    gateway.register(_provider("candidate", state=LifecycleState.CANDIDATE), candidate)
    facade = _facade(gateway)

    result = facade.discover(
        task=Task("mcp-1", "inspect browser state"),
        query="browser snapshot",
        profile="coding",
        capabilities={"browser"},
        limit=1,
    )

    assert result.ok is True
    assert result.value is not None
    assert len(result.value.hits) == 1
    assert result.value.hits[0].capability_id == "mcp:playwright:browser.snapshot"
    assert result.value.catalog_size == 2
    assert all("candidate" not in capability_id for capability_id in result.value.discoverable_ids)
    assert candidate.calls == []


def test_delegated_identity_scope_is_applied_before_progressive_discovery():
    gateway = McpGateway()
    transport = FakeTransport(
        [
            _tool("browser.snapshot", capability="browser.read", read_only=True),
            _tool("browser.navigate", capability="browser.write", read_only=False),
        ]
    )
    gateway.register(_provider("playwright"), transport)
    facade = _facade(gateway)

    result = facade.discover(
        task=Task("mcp-2", "browser"),
        profile="coding",
        capabilities={"browser"},
        identity=_identity(capabilities=frozenset({"browser.read"})),
        limit=8,
    )

    assert result.ok is True
    assert result.value is not None
    assert result.value.discoverable_ids == frozenset({"mcp:playwright:browser.snapshot"})


def test_read_only_mcp_capability_dispatches_autonomously_through_gateway():
    gateway = McpGateway()
    transport = FakeTransport([_tool("browser.snapshot", capability="browser.read", read_only=True)])
    gateway.register(_provider("playwright"), transport)
    facade = _facade(gateway)

    result = facade.dispatch(
        task_id="mcp-3",
        capability_id="mcp:playwright:browser.snapshot",
        arguments={"url": "https://example.invalid"},
        profile="coding",
        capabilities={"browser"},
        reason="inspect current page",
        expected_utility=0.9,
    )

    assert result.ok is True
    assert result.value is not None
    assert result.value.value["called"] == "browser.snapshot"
    methods = [call["method"] for call in transport.calls]
    assert methods[-1] == "tools/call"
    assert methods.count("tools/call") == 1
    assert all(method in {"tools/list", "tools/call"} for method in methods)


def test_destructive_mcp_annotation_hits_existing_consequential_boundary_before_call():
    gateway = McpGateway()
    transport = FakeTransport(
        [_tool("files.delete", capability="files.delete", read_only=False, destructive=True)]
    )
    gateway.register(_provider("playwright"), transport)
    facade = _facade(gateway)

    result = facade.dispatch(
        task_id="mcp-4",
        capability_id="mcp:playwright:files.delete",
        arguments={"path": "/tmp/example"},
        profile="coding",
        reason="delete file",
        expected_utility=0.9,
    )

    assert result.ok is False
    assert result.recoverable is True
    assert [call["method"] for call in transport.calls] == ["tools/list"]


def test_explicit_action_context_can_preserve_existing_spend_boundary():
    gateway = McpGateway()
    transport = FakeTransport([_tool("checkout.create", capability="checkout", read_only=False)])
    gateway.register(_provider("playwright"), transport)
    facade = _facade(gateway)

    result = facade.dispatch(
        task_id="mcp-5",
        capability_id="mcp:playwright:checkout.create",
        arguments={"amount": 25},
        profile="coding",
        reason="purchase service",
        expected_utility=0.95,
        action=ActionContext(
            "spend_money",
            reversible=False,
            remote=True,
            material_spend=True,
            external_irreversible_effect=True,
        ),
    )

    assert result.ok is False
    assert result.recoverable is True
    assert [call["method"] for call in transport.calls] == ["tools/list"]
