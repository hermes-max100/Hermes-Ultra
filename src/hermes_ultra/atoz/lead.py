from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from .model import require_aware


@dataclass(frozen=True)
class LeadConversation:
    lead_conversation_id: str
    tenant_id: str
    source: str
    source_external_id: str | None
    campaign: str | None
    consent_evidence_refs: tuple[str, ...]
    customer_need: str
    qualified: bool
    handoff_required: bool
    acquisition_cost_minor: int | None
    currency: str
    received_at: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("lead_conversation_id", "tenant_id", "source", "customer_need"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        if self.acquisition_cost_minor is not None and self.acquisition_cost_minor < 0:
            raise ValueError("acquisition_cost_minor cannot be negative")
        require_aware(self.received_at, "received_at")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def dedupe_key(self) -> str:
        material = {"tenant_id": self.tenant_id, "source": self.source.strip().lower(), "source_external_id": self.source_external_id, "customer_need": self.customer_need.strip().lower(), "received_bucket": self.received_at.replace(second=0, microsecond=0).isoformat()}
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LeadIngestor:
    """Channel-neutral in-memory acceptance contract for tests/adapters."""

    def __init__(self) -> None:
        self._by_dedupe: dict[str, LeadConversation] = {}

    def ingest(self, lead: LeadConversation) -> tuple[LeadConversation, bool]:
        prior = self._by_dedupe.get(lead.dedupe_key)
        if prior is not None:
            return prior, False
        self._by_dedupe[lead.dedupe_key] = lead
        return lead, True
