from __future__ import annotations

from typing import Any

from .service import LegalService
from .transport import MatterAuthorizer, invoke_transport
from .types import ExternalAccess, LegalBoundaryError, LegalExecutionError, Sensitivity


def create_fastapi_router(
    service: LegalService | None = None,
    *,
    matter_authorizer: MatterAuthorizer,
    sensitivity: Sensitivity = Sensitivity.LEGAL_PRIVILEGED,
    external_access: ExternalAccess = ExternalAccess.DENY,
) -> Any:
    """Create an optional REST facade over the same governed legal core.

    Matter authorization and maximum egress are deployment-owned; request bodies
    cannot escalate either setting. Request JSON is parsed inside the boundary so
    framework validation cannot echo privileged input in a default 422 response.
    """
    try:
        from fastapi import APIRouter, HTTPException, Request
    except ImportError as exc:  # pragma: no cover - optional runtime package
        raise RuntimeError("Hermes Legal API requires the optional 'fastapi' dependency") from exc

    legal_service = service or LegalService()
    router = APIRouter(prefix="/legal", tags=["hermes-legal-private"])

    @router.get("/health")
    async def legal_health() -> dict[str, str]:
        return {"status": "ok", "boundary": "hermes-legal-private"}

    async def execute_legal_tool(tool_name: str, request: Any) -> Any:
        try:
            try:
                body = await request.json()
            except Exception:
                raise ValueError("invalid_json_body") from None
            if not isinstance(body, dict):
                raise ValueError("body_must_be_object")

            matter_id = body.get("matter_id")
            arguments = body.get("arguments", {})
            if not isinstance(matter_id, str):
                raise ValueError("matter_id_required")
            if not isinstance(arguments, dict):
                raise ValueError("arguments_must_be_object")

            route_value = body.get("route_kind", "LOCAL")
            if not isinstance(route_value, str):
                raise ValueError("route_kind_must_be_string")

            return await invoke_transport(
                legal_service,
                tool_name,
                matter_id=matter_id,
                arguments=arguments,
                matter_authorizer=matter_authorizer,
                sensitivity=sensitivity,
                external_access=external_access,
                route_kind=route_value,
                provider=body.get("provider") if isinstance(body.get("provider"), str) else None,
                redaction_attestation=(
                    body.get("redaction_attestation")
                    if isinstance(body.get("redaction_attestation"), str)
                    else None
                ),
            )
        except LegalExecutionError:
            raise HTTPException(status_code=500, detail="legal_tool_execution_failed") from None
        except (LegalBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    # FastAPI is an optional dependency imported inside this factory. With
    # postponed annotations enabled, bind the concrete Request class before
    # registration so FastAPI treats it as transport state, never as a body model.
    execute_legal_tool.__annotations__["request"] = Request
    router.add_api_route("/tools/{tool_name}", execute_legal_tool, methods=["POST"])

    return router
