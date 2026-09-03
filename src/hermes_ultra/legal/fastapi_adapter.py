from __future__ import annotations

from typing import Any

from .service import LegalService
from .transport import invoke_transport
from .types import LegalBoundaryError


def create_fastapi_router(service: LegalService | None = None) -> Any:
    """Create an optional REST facade over the same governed legal core.

    FastAPI is a transport only; it never receives direct handler access and
    therefore cannot bypass LegalService authorization.
    """
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError as exc:  # pragma: no cover - optional runtime package
        raise RuntimeError("Hermes Legal API requires the optional 'fastapi' dependency") from exc

    legal_service = service or LegalService()
    router = APIRouter(prefix="/legal", tags=["hermes-legal-private"])

    @router.get("/health")
    async def legal_health() -> dict[str, str]:
        return {"status": "ok", "boundary": "hermes-legal-private"}

    @router.post("/tools/{tool_name}")
    async def execute_legal_tool(tool_name: str, body: dict[str, Any]) -> Any:
        try:
            matter_id = body.get("matter_id")
            arguments = body.get("arguments", {})
            if not isinstance(matter_id, str):
                raise ValueError("matter_id_required")
            if not isinstance(arguments, dict):
                raise ValueError("arguments_must_be_object")
            return await invoke_transport(
                legal_service,
                tool_name,
                matter_id=matter_id,
                arguments=arguments,
                sensitivity=str(body.get("sensitivity", "LEGAL_PRIVILEGED")),
                external_access=str(body.get("external_access", "DENY")),
                route_kind=str(body.get("route_kind", "LOCAL")),
                provider=body.get("provider") if isinstance(body.get("provider"), str) else None,
                endpoint=body.get("endpoint") if isinstance(body.get("endpoint"), str) else None,
                payload_redacted=body.get("payload_redacted") is True,
            )
        except (LegalBoundaryError, ValueError) as exc:
            # Return the stable policy reason only. Never echo arguments or privileged payloads.
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return router
