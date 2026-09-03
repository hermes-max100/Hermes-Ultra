from __future__ import annotations

from typing import Any

from .service import LegalService
from .transport import MatterAuthorizer, invoke_transport
from .types import ExternalAccess, LegalBoundaryError, Sensitivity


def create_fastapi_router(
    service: LegalService | None = None,
    *,
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED,
    external_access: ExternalAccess = ExternalAccess.DENY,
) -> Any:
    """Create an optional REST facade over the same governed legal core.

    Matter authorization and maximum egress are deployment-owned; request bodies
    cannot escalate either setting.
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
                matter_authorizer=matter_authorizer,
                sensitivity=sensitivity,
                external_access=external_access,
                route_kind=str(body.get("route_kind", "LOCAL")),
                provider=body.get("provider") if isinstance(body.get("provider"), str) else None,
                redaction_attestation=(
                    body.get("redaction_attestation")
                    if isinstance(body.get("redaction_attestation"), str)
                    else None
                ),
            )
        except (LegalBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return router
