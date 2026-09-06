from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .model import CallContext, CallFacts, DispositionKind, VoiceDisposition, VoicePolicyConfig


class TransferUrgency(str, Enum):
    ROUTINE = "routine"
    PRIORITY = "priority"
    EMERGENCY = "emergency"


class WarmTransferStepKind(str, Enum):
    INITIATE = "initiate_warm_transfer"
    AWAIT_ACCEPTANCE = "await_human_acceptance"


class WarmTransferStatus(str, Enum):
    ACCEPTED = "accepted"
    FAILED = "failed"


@dataclass(frozen=True)
class WarmTransferPacket:
    call_id: str
    tenant_id: str
    target_reference: str
    urgency: TransferUrgency
    reasons: tuple[str, ...]
    requested_service: str | None
    postal_code: str | None
    qualified: bool
    follow_up_consent: bool
    contact_reference: str | None
    actions_attempted: tuple[str, ...]
    requested_next_step: str

    def telemetry_payload(self) -> Mapping[str, object]:
        """Return the PII-minimized transfer shape permitted in telemetry."""

        return MappingProxyType(
            {
                "call_id": self.call_id,
                "tenant_id": self.tenant_id,
                "urgency": self.urgency.value,
                "reasons": self.reasons,
                "requested_service": self.requested_service,
                "qualified": self.qualified,
                "follow_up_consent": self.follow_up_consent,
                "has_contact_reference": bool(self.contact_reference),
                "actions_attempted": self.actions_attempted,
                "requested_next_step": self.requested_next_step,
            }
        )


@dataclass(frozen=True)
class WarmTransferStep:
    kind: WarmTransferStepKind
    idempotency_key: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class WarmTransferPlan:
    call_id: str
    tenant_id: str
    packet: WarmTransferPacket
    expires_at: datetime
    steps: tuple[WarmTransferStep, ...]
    staged: bool = True


@dataclass(frozen=True)
class WarmTransferReceipt:
    call_id: str
    tenant_id: str
    status: WarmTransferStatus
    recorded_at: datetime
    human_reference: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.status is WarmTransferStatus.ACCEPTED and not (
            self.human_reference and self.human_reference.strip()
        ):
            raise ValueError("accepted transfer requires a human_reference")
        if self.status is WarmTransferStatus.FAILED and not (
            self.failure_reason and self.failure_reason.strip()
        ):
            raise ValueError("failed transfer requires a failure_reason")


class WarmTransferPlanner:
    """Stages a contextual handoff; provider adapters perform the actual transfer."""

    def __init__(self, config: VoicePolicyConfig) -> None:
        self.config = config

    def build(
        self,
        context: CallContext,
        facts: CallFacts,
        disposition: VoiceDisposition,
        *,
        now: datetime | None = None,
    ) -> WarmTransferPlan:
        if disposition.kind is not DispositionKind.WARM_TRANSFER_REQUIRED:
            raise ValueError("warm transfer plan requires a warm-transfer disposition")
        target = self.config.warm_transfer_target_reference
        if not target:
            raise PermissionError("warm transfer target is not configured")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        urgency = (
            TransferUrgency.EMERGENCY if facts.emergency_detected else TransferUrgency.PRIORITY
        )
        packet = WarmTransferPacket(
            call_id=context.call_id,
            tenant_id=context.tenant_id,
            target_reference=target,
            urgency=urgency,
            reasons=disposition.reasons,
            requested_service=facts.requested_service,
            postal_code=facts.postal_code,
            qualified=facts.qualified,
            follow_up_consent=facts.follow_up_consent,
            contact_reference=facts.contact_reference,
            actions_attempted=facts.actions_attempted,
            requested_next_step=facts.requested_next_step or "continue caller assistance",
        )
        prefix = f"voice:{context.call_id}:warm-transfer"
        steps = (
            WarmTransferStep(
                WarmTransferStepKind.INITIATE,
                f"{prefix}:initiate",
                {"packet": packet, "target_reference": target},
            ),
            WarmTransferStep(
                WarmTransferStepKind.AWAIT_ACCEPTANCE,
                f"{prefix}:acceptance",
                {
                    "call_id": context.call_id,
                    "timeout_seconds": self.config.warm_transfer_acceptance_timeout_seconds,
                },
            ),
        )
        return WarmTransferPlan(
            call_id=context.call_id,
            tenant_id=context.tenant_id,
            packet=packet,
            expires_at=current
            + timedelta(seconds=self.config.warm_transfer_acceptance_timeout_seconds),
            steps=steps,
        )
