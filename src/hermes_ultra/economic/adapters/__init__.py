from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class AdapterResult:
    ok: bool
    external_id: str | None
    amount: Decimal
    currency: str
    status: str
    metadata: Mapping[str, object] = field(default_factory=dict)

from .omkar_google_maps import OmkarGoogleMapsAdapter, OmkarLead, OmkarLeadBatch, OmkarProviderError

__all__ = ["AdapterResult", "OmkarGoogleMapsAdapter", "OmkarLead", "OmkarLeadBatch", "OmkarProviderError"]
