from __future__ import annotations

from typing import Any, Callable

from .service import LegalService
from .transport import invoke_transport


def _tool_wrapper(service: LegalService, tool_name: str) -> Callable[..., Any]:
    async def legal_tool(
        matter_id: str,
        arguments: dict[str, Any],
        sensitivity: str = "LEGAL_PRIVILEGED",
        external_access: str = "DENY",
        route_kind: str = "LOCAL",
        provider: str | None = None,
        endpoint: str | None = None,
        payload_redacted: bool = False,
    ) -> Any:
        """Execute a Hermes Legal capability through the private governance boundary."""
        return await invoke_transport(
            service,
            tool_name,
            matter_id=matter_id,
            arguments=arguments,
            sensitivity=sensitivity,
            external_access=external_access,
            route_kind=route_kind,
            provider=provider,
            endpoint=endpoint,
            payload_redacted=payload_redacted,
        )

    legal_tool.__name__ = tool_name
    legal_tool.__qualname__ = tool_name
    legal_tool.__doc__ = f"Hermes Legal private tool: {tool_name}. All calls are matter-scoped and fail closed."
    return legal_tool


def create_mcp_server(service: LegalService | None = None) -> Any:
    """Create a Hermes Legal MCP server using the official MCP Python SDK v2.

    The SDK is an optional transport dependency. The legal policy/core remains
    importable and testable without MCP installed.
    """
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError("Hermes Legal MCP requires the optional 'mcp>=2,<3' dependency") from exc

    legal_service = service or LegalService()
    server = MCPServer(
        "Hermes Legal Private",
        instructions=(
            "Private first-party legal tools. Treat all inputs and outputs as matter-scoped. "
            "External access defaults to DENY; public MCP, Monid, and unknown routes are forbidden."
        ),
    )
    for tool_name in legal_service.tool_names:
        server.add_tool(_tool_wrapper(legal_service, tool_name))
    return server
