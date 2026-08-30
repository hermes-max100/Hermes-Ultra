from hermes_ultra import (
    MCP_PROTOCOL_VERSION,
    AgentPluginLoader,
    CredentialReference,
    DelegatedIdentity,
    McpGateway,
    McpProvider,
)


def test_mcp_capability_substrate_is_public_api() -> None:
    assert MCP_PROTOCOL_VERSION == "2026-07-28"
    assert AgentPluginLoader is not None
    assert CredentialReference is not None
    assert DelegatedIdentity is not None
    assert McpGateway is not None
    assert McpProvider is not None
