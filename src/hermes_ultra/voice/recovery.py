from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .model import (
    CallContext,
    CallFacts,
    ContactChannel,
    DispositionKind,
    VoiceDisposition,
    VoicePolicyConfig,
)


class RecoveryStepKind(str, Enum):
    SEND_SMS = "send_sms"
    SEND_EMAIL = "send_email"
    CREATE_CRM_TASK = "create_crm_task"
    VERIFY_BOOKING = "verify_booking"


@dataclass(frozen=True)
class RecoveryStep:
    kind: RecoveryStepKind
    idempotency_key: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class RecoveryPlan:
    call_id: str
    tenant_id: str
    contact_reference: str
    attempt: int
    expires_at: datetime
    steps: tuple[RecoveryStep, ...]
    staged: bool = True


class RecoveryPlanner:
    """Creates consent-aware staged actions; it never performs remote writes."""

    def __init__(self, config: VoicePolicyConfig) -> None:
        self.config = config

    def build(
        self,
        context: CallContext,
        facts: CallFacts,
        disposition: VoiceDisposition,
        *,
        now: datetime | None = None,
    ) -> RecoveryPlan:
        if disposition.kind is not DispositionKind.INCOMPLETE_BUT_RECOVERABLE:
            raise ValueError("recovery plan requires a recoverable disposition")
        if not disposition.recovery_allowed:
            raise ValueError("disposition does not authorize recovery")
        if not facts.follow_up_consent or facts.do_not_contact or not facts.contact_reference:
            raise PermissionError("recovery requires consent and an allowed opaque contact reference")
        if facts.recovery_attempts >= self.config.max_recovery_attempts:
            raise PermissionError("recovery attempt limit reached")

        channel = next(
            (
                item
                for item in self.config.recovery_channels
                if item in facts.contact_channels
            ),
            None,
        )
        if channel is None:
            raise PermissionError("no policy-approved contact channel is available")

        attempt = facts.recovery_attempts + 1
        prefix = f"voice:{context.call_id}:recovery:{attempt}"
        message_kind = (
            RecoveryStepKind.SEND_SMS
            if channel is ContactChannel.SMS
            else RecoveryStepKind.SEND_EMAIL
        )
        shared_payload = {
            "call_id": context.call_id,
            "tenant_id": context.tenant_id,
            "contact_reference": facts.contact_reference,
            "attempt": attempt,
        }
        steps = (
            RecoveryStep(message_kind, f"{prefix}:{message_kind.value}", shared_payload),
            RecoveryStep(
                RecoveryStepKind.CREATE_CRM_TASK,
                f"{prefix}:create_crm_task",
                {**shared_payload, "reasons": disposition.reasons},
            ),
            RecoveryStep(
                RecoveryStepKind.VERIFY_BOOKING,
                f"{prefix}:verify_booking",
                {"call_id": context.call_id, "tenant_id": context.tenant_id},
            ),
        )
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return RecoveryPlan(
            call_id=context.call_id,
            tenant_id=context.tenant_id,
            contact_reference=facts.contact_reference,
            attempt=attempt,
            expires_at=current + timedelta(hours=self.config.recovery_window_hours),
            steps=steps,
        )
