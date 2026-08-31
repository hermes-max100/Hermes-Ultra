from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

PROVIDER_ID = "omkar-google-maps"
DEFAULT_API_URL = "http://127.0.0.1:8000"
_SENSITIVE_KEYS = {"api_key", "apikey", "auth_token", "authorization", "token", "password", "secret"}


class OmkarProviderError(ValueError):
    pass


class BotasaurusApi(Protocol):
    def create_sync_task(self, data: Mapping[str, object]): ...
    def get_task_results(self, task_id: object): ...


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _pick(row: Mapping[str, object], *names: str) -> object:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception as exc:
        raise OmkarProviderError("invalid numeric value in Omkar result") from exc


def _int_or_zero(value: object) -> int:
    text = _text(value).replace(",", "")
    if not text:
        return 0
    try:
        return max(0, int(float(text)))
    except ValueError as exc:
        raise OmkarProviderError("invalid review count in Omkar result") from exc


def _digest(row: Mapping[str, object]) -> str:
    safe = {
        str(key): value
        for key, value in row.items()
        if str(key).lower() not in _SENSITIVE_KEYS
    }
    raw = json.dumps(safe, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OmkarLead:
    provider_key: str
    name: str
    category: str
    address: str
    phone: str
    website: str
    source_url: str
    rating: Decimal | None
    reviews: int
    email: str
    linkedin: str
    instagram: str
    raw_digest: str

    def prospect_id(self) -> str:
        return "omkar_" + hashlib.sha256(self.provider_key.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class OmkarLeadBatch:
    leads: tuple[OmkarLead, ...]
    allocated_cost_usd: Decimal
    task_id: str

    def prospects(self, *, city: str = "", state: str = "") -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for lead in self.leads:
            contact_channel = "phone" if lead.phone else "website" if lead.website else "manual_review"
            contact_ref = lead.phone or lead.website
            refs = [] if not lead.source_url else [{"type": "source", "ref": lead.source_url}]
            notes = f"Omkar Google Maps discovery; rating={lead.rating or ''}; reviews={lead.reviews}; evidence={lead.raw_digest}"
            output.append({
                "prospect_id": lead.prospect_id(), "business_name": lead.name,
                "category": lead.category or "local service business", "city": city, "state": state,
                "website": lead.website, "contact_channel": contact_channel, "contact_ref": contact_ref,
                "signals": [], "evidence_refs": refs, "notes": notes,
            })
        return output

    def revenue_event(self, *, experiment_id: str) -> dict[str, object]:
        if not isinstance(experiment_id, str) or not experiment_id.strip():
            raise OmkarProviderError("experiment_id is required")
        return {
            "experiment_id": experiment_id.strip(),
            "event_type": "lead",
            "action": "analysis",
            "source": PROVIDER_ID,
            "human_approved": False,
            "metrics": {
                "leads": len(self.leads),
                "tool_cost": self.allocated_cost_usd,
            },
        }


class OmkarGoogleMapsAdapter:
    def __init__(self, *, api: BotasaurusApi, api_url: str = DEFAULT_API_URL) -> None:
        self.api = api
        self.api_url = self._loopback_url(api_url)

    @staticmethod
    def _loopback_url(value: str) -> str:
        parsed = urlparse(str(value).strip())
        if parsed.scheme not in {"http", "https"}:
            raise OmkarProviderError("Omkar API URL must use HTTP(S)")
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise OmkarProviderError("Omkar API must remain loopback-only")
        return str(value).rstrip("/")

    @classmethod
    def from_api_url(cls, api_url: str = DEFAULT_API_URL) -> "OmkarGoogleMapsAdapter":
        cls._loopback_url(api_url)
        try:
            from botasaurus_api import Api  # type: ignore
        except ImportError as exc:
            raise OmkarProviderError("botasaurus-api==4.0.10 is required for live Omkar discovery") from exc
        return cls(api=Api(api_url, create_response_files=False), api_url=api_url)

    @staticmethod
    def _provider_key(row: Mapping[str, object]) -> str:
        for field in ("KGMID", "PLACE_ID", "DATA_ID", "CID"):
            value = _text(_pick(row, field))
            if value:
                return f"{field.lower()}:{value}"
        fallback = {
            "name": _text(_pick(row, "NAME")),
            "address": _text(_pick(row, "ADDRESS")),
            "phone": _text(_pick(row, "PHONE", "PHONE_INTERNATIONAL")),
            "website": _text(_pick(row, "WEBSITE")),
        }
        raw = json.dumps(fallback, sort_keys=True, separators=(",", ":"))
        return "fallback:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _lead(cls, row: Mapping[str, object]) -> OmkarLead:
        return OmkarLead(
            provider_key=cls._provider_key(row),
            name=_text(_pick(row, "NAME")) or "Unknown business",
            category=_text(_pick(row, "MAIN_CATEGORY")),
            address=_text(_pick(row, "ADDRESS")),
            phone=_text(_pick(row, "PHONE_INTERNATIONAL", "PHONE")),
            website=_text(_pick(row, "WEBSITE")),
            source_url=_text(_pick(row, "LINK")),
            rating=_decimal_or_none(_pick(row, "RATING")),
            reviews=_int_or_zero(_pick(row, "REVIEWS")),
            email=_text(_pick(row, "EMAIL")),
            linkedin=_text(_pick(row, "LINKEDIN")),
            instagram=_text(_pick(row, "INSTAGRAM")),
            raw_digest=_digest(row),
        )

    @staticmethod
    def _task_rows(api: BotasaurusApi, task: object) -> Sequence[Mapping[str, object]]:
        if isinstance(task, list):
            return [row for row in task if isinstance(row, Mapping)]
        if isinstance(task, Mapping):
            for key in ("result", "results", "data"):
                value = task.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, Mapping)]
            if task.get("id") is not None:
                value = api.get_task_results(task.get("id"))
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, Mapping)]
        raise OmkarProviderError("Omkar task did not return a result list")

    def discover(
        self,
        payload: Mapping[str, object],
        *,
        allocated_cost_usd: Decimal | int | str = Decimal("0"),
    ) -> OmkarLeadBatch:
        if not isinstance(payload, Mapping) or not payload:
            raise OmkarProviderError("Omkar task payload is required")
        cost = Decimal(str(allocated_cost_usd))
        if cost < 0:
            raise OmkarProviderError("allocated provider cost cannot be negative")
        task = self.api.create_sync_task(dict(payload))
        rows = self._task_rows(self.api, task)
        unique: dict[str, OmkarLead] = {}
        for row in rows:
            lead = self._lead(row)
            unique.setdefault(lead.provider_key, lead)
        task_id = _text(task.get("id")) if isinstance(task, Mapping) else ""
        return OmkarLeadBatch(tuple(unique.values()), cost, task_id)


__all__ = [
    "DEFAULT_API_URL", "PROVIDER_ID", "OmkarGoogleMapsAdapter",
    "OmkarLead", "OmkarLeadBatch", "OmkarProviderError",
]
