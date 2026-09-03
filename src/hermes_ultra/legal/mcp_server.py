from __future__ import annotations

from typing import Any, Callable

from .service import LegalService
from .transport import MatterAuthorizer, invoke_transport
from .types import ExternalAccess, Sensitivity


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
