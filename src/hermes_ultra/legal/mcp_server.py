from __future__ import annotations

from typing import Any, Callable

from .service import LegalService
from .transport import MatterAuthorizer, invoke_transport
from .types import ExternalAccess, Sensitivity

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _tool_wrapper(
    service: LegalService,
    tool_name: str,
    *,
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity,
    external_access: ExternalAccess,
) -> Callable[..., Any]:
    async def legal_tool(
        matter_id: str,
        arguments: dict[str, Any],
        route_kind: str = "LOCAL",
        provider: str | None = None,
        redaction_attestation: str | None = None,
    ) -> Any:
        """Execute a Hermes Legal capability through the private governance boundary."""
        return await invoke_transport(
            service,
            tool_name,
            matter_id=matter_id,
            arguments=arguments,
            matter_authorizer=matter_authorizer,
            sensitivity=sensitivity,
            external_access=external_access,
            route_kind=route_kind,
            provider=provider,
            redaction_attestation=redaction_attestation,
        )

    legal_tool.__name__ = tool_name
    legal_tool.__qualname__ = tool_name
    legal_tool.__doc__ = f"Hermes Legal private tool: {tool_name}. All calls are matter-scoped and fail closed."
    return legal_tool


def create_mcp_server(
    service: LegalService | None = None,
    *,
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED,
    external_access: ExternalAccess = ExternalAccess.DENY,
) -> Any:
    """Create a private Hermes Legal MCP server using official MCP Python SDK v2.

    Matter authorization and the maximum egress mode are deployment-owned inputs,
    not tool-call parameters that an agent can escalate.
    """
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - optional runtime package
        raise RuntimeError("Hermes Legal MCP requires the optional 'mcp>=2,<3' dependency") from exc

    legal_service = service or LegalService()
    server = MCPServer(
        "Hermes Legal Private",
        instructions=(
            "Private first-party legal tools. Matter scope and maximum egress are fixed by the server. "
            "Public MCP, Monid, and unknown routes are forbidden."
        ),
    )
    for tool_name in legal_service.tool_names:
        server.add_tool(
            _tool_wrapper(
                legal_service,
                tool_name,
                matter_authorizer=matter_authorizer,
                sensitivity=sensitivity,
                external_access=external_access,
            )
        )
    return server


def create_mcp_http_app(
    service: LegalService | None = None,
    *,
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED,
    external_access: ExternalAccess = ExternalAccess.DENY,
    host: str = "127.0.0.1",
    transport_security: Any | None = None,
) -> Any:
    """Build the private Legal MCP Streamable HTTP app with no protocol sessions.

    MCP 2026-07-28 requests are sessionless by protocol. ``stateless_http=True``
    additionally prevents the SDK's legacy compatibility leg from issuing or
    retaining ``Mcp-Session-Id`` state. JSON responses avoid a request-scoped SSE
    back-channel, matching Hermes's response-carried approval model.

    The MCP SDK automatically enables DNS-rebinding protection for loopback binds.
    Any non-loopback bind must supply explicit deployment-owned transport-security
    settings rather than relying on permissive defaults.
    """
    bind_host = host.strip()
    if not bind_host:
        raise ValueError("host is required")
    if bind_host not in _LOOPBACK_HOSTS and transport_security is None:
        raise ValueError("transport_security is required for non-loopback legal MCP binds")

    server = create_mcp_server(
        service,
        matter_authorizer=matter_authorizer,
        sensitivity=sensitivity,
        external_access=external_access,
    )
    return server.streamable_http_app(
        host=bind_host,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
