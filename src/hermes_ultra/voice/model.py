from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class VoicePackage(str, Enum):
    RECEPTIONIST = "receptionist"
    REVENUE_RECOVERY = "revenue_recovery"


class ContactChannel(str, Enum):
    SMS = "sms"
    EMAIL = "email"


class VoiceCallState(str, Enum):
    INITIATED = "initiated"
    CONNECTED = "connected"
    DISCLOSED = "disclosed"
    QUALIFYING = "qualifying"
    ELIGIBLE = "eligible"
    BOOKING = "booking"
    BOOKED = "booked"
    HANDOFF = "handoff"
    TRANSFER_CONNECTING = "transfer_connecting"
    TRANSFER_ACCEPTED = "transfer_accepted"
    TRANSFER_FAILED = "transfer_failed"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    ENDED = "ended"


class DispositionKind(str, Enum):
    BOOKED = "booked"
    HANDOFF_REQUIRED = "handoff_required"
    WARM_TRANSFER_REQUIRED = "warm_transfer_required"
    INCOMPLETE_BUT_RECOVERABLE = "incomplete_but_recoverable"
    INCOMPLETE_NOT_RECOVERABLE = "incomplete_not_recoverable"
    OUT_OF_AREA = "out_of_area"
    POLICY_BLOCKED = "policy_blocked"


@dataclass(frozen=True)
class CallContext:
    call_id: str
    run_id: str
    tenant_id: str
    currency: str = "USD"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.run_id.strip() or not self.tenant_id.strip():
            raise ValueError("call_id, run_id, and tenant_id are required")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class CallFacts:
    disclosure_complete: bool
    requested_service: str | None = None
    postal_code: str | None = None
    qualified: bool = False
    appointment_booked: bool = False
    handoff_requested: bool = False
    emergency_detected: bool = False
    ended_before_booking: bool = False
    follow_up_consent: bool = False
    contact_reference: str | None = None
    contact_channels: frozenset[ContactChannel] = frozenset()
    do_not_contact: bool = False
    recovery_attempts: int = 0
    actions_attempted: tuple[str, ...] = ()
    requested_next_step: str | None = None

    def __post_init__(self) -> None:
        if self.recovery_attempts < 0:
            raise ValueError("recovery_attempts cannot be negative")
        channels = frozenset(ContactChannel(item) for item in self.contact_channels)
        object.__setattr__(self, "contact_channels", channels)
        if self.requested_service is not None:
            object.__setattr__(self, "requested_service", self.requested_service.strip().lower())
        if self.postal_code is not None:
            object.__setattr__(self, "postal_code", self.postal_code.strip().upper())
        if self.contact_reference is not None:
            object.__setattr__(self, "contact_reference", self.contact_reference.strip())
        actions = tuple(item.strip() for item in self.actions_attempted if item.strip())
        object.__setattr__(self, "actions_attempted", actions)
        if self.requested_next_step is not None:
            object.__setattr__(self, "requested_next_step", self.requested_next_step.strip())


@dataclass(frozen=True)
class VoicePolicyConfig:
    package: VoicePackage
    supported_postal_codes: frozenset[str]
    allowed_services: frozenset[str]
    recovery_channels: tuple[ContactChannel, ...] = (
        ContactChannel.SMS,
        ContactChannel.EMAIL,
    )
    max_recovery_attempts: int = 2
    recovery_window_hours: int = 24
    warm_transfer_target_reference: str | None = None
    warm_transfer_acceptance_timeout_seconds: int = 30
    secondary_languages: tuple[str, ...] = ("es",)
    minimum_end_of_turn_confidence: Decimal = Decimal("0.65")

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", VoicePackage(self.package))
        postal_codes = frozenset(item.strip().upper() for item in self.supported_postal_codes if item.strip())
        services = frozenset(item.strip().lower() for item in self.allowed_services if item.strip())
        channels = tuple(dict.fromkeys(ContactChannel(item) for item in self.recovery_channels))
        if not postal_codes:
            raise ValueError("at least one supported postal code is required")
        if not services:
            raise ValueError("at least one allowed service is required")
        if not channels:
            raise ValueError("at least one recovery channel is required")
        if not 1 <= self.max_recovery_attempts <= 5:
            raise ValueError("max_recovery_attempts must be between 1 and 5")
        if not 1 <= self.recovery_window_hours <= 168:
            raise ValueError("recovery_window_hours must be between 1 and 168")
        if not 5 <= self.warm_transfer_acceptance_timeout_seconds <= 300:
            raise ValueError("warm transfer timeout must be between 5 and 300 seconds")
        target = self.warm_transfer_target_reference
        if target is not None:
            target = target.strip()
            if not target:
                target = None
        languages = tuple(
            dict.fromkeys(item.strip().lower() for item in self.secondary_languages if item.strip())
        )
        confidence = Decimal(str(self.minimum_end_of_turn_confidence))
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError("minimum_end_of_turn_confidence must be between 0 and 1")
        object.__setattr__(self, "supported_postal_codes", postal_codes)
        object.__setattr__(self, "allowed_services", services)
        object.__setattr__(self, "recovery_channels", channels)
        object.__setattr__(self, "warm_transfer_target_reference", target)
        object.__setattr__(self, "secondary_languages", languages)
        object.__setattr__(self, "minimum_end_of_turn_confidence", confidence)


@dataclass(frozen=True)
class VoiceDisposition:
    kind: DispositionKind
    reasons: tuple[str, ...]
    recovery_allowed: bool = False
