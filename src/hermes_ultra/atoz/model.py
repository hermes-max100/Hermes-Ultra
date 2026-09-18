from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class RecoveryEventKind(str, Enum):
    CASE_OPENED = "case_opened"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    APPOINTMENT_BOOKED = "appointment_booked"
    JOB_SCHEDULED = "job_scheduled"
    JOB_COMPLETED = "job_completed"
    PAYMENT_COLLECTED = "payment_collected"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    MARKED_DUPLICATE = "marked_duplicate"
    DISPUTE_OPENED = "dispute_opened"
    DISPUTE_RESOLVED = "dispute_resolved"
    PROVIDER_COST_RECORDED = "provider_cost_recorded"
    HUMAN_REVIEW_RECORDED = "human_review_recorded"


class RecoveryCaseStatus(str, Enum):
    OPEN = "open"
    RECOVERY_ACTIVE = "recovery_active"
    APPOINTMENT_BOOKED = "appointment_booked"
    JOB_SCHEDULED = "job_scheduled"
    JOB_COMPLETED = "job_completed"
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    DUPLICATE = "duplicate"
    DISPUTED = "disputed"


class DisputeStatus(str, Enum):
    NONE = "none"
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class RecoveryEvent:
    event_id: str
    case_id: str
    tenant_id: str
    kind: RecoveryEventKind
    occurred_at: datetime
    payload: Mapping[str, object] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("event_id", self.event_id), ("case_id", self.case_id), ("tenant_id", self.tenant_id)):
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "kind", RecoveryEventKind(self.kind))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(ref.strip() for ref in self.evidence_refs if ref.strip())))


@dataclass(frozen=True)
class RecoveryCase:
    case_id: str
    tenant_id: str
    lead_conversation_id: str
    original_lead_source: str
    intake_at: datetime
    currency: str
    attribution_window_hours: int
    attribution_rule_version: str
    status: RecoveryCaseStatus
    revision: int
    appointment_id: str | None = None
    job_id: str | None = None
    payment_id: str | None = None
    collected_amount_minor: int = 0
    refunded_amount_minor: int = 0
    provider_cost_minor: int = 0
    human_review_minutes: int = 0
    completion_at: datetime | None = None
    collection_at: datetime | None = None
    cancellation_at: datetime | None = None
    duplicate_of_case_id: str | None = None
    dispute_status: DisputeStatus = DisputeStatus.NONE
    evidence_refs: tuple[str, ...] = ()

    @property
    def net_collected_minor(self) -> int:
        return max(0, self.collected_amount_minor - self.refunded_amount_minor)


@dataclass(frozen=True)
class BillableOutcomeDecision:
    case_id: str
    eligible: bool
    rule_version: str
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    decided_at: datetime
    success_fee_enabled: bool = False

    def __post_init__(self) -> None:
        require_aware(self.decided_at, "decided_at")
        if self.success_fee_enabled:
            raise ValueError("success-fee charging is disabled for the pilot")
