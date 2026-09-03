from __future__ import annotations

from .model import (
    CallFacts,
    DispositionKind,
    VoiceDisposition,
    VoicePackage,
    VoicePolicyConfig,
)


class VoicePolicyEngine:
    """Determines business disposition from structured facts, not model prose."""

    def __init__(self, config: VoicePolicyConfig) -> None:
        self.config = config

    def evaluate(self, facts: CallFacts) -> VoiceDisposition:
        if not facts.disclosure_complete:
            return VoiceDisposition(
                DispositionKind.POLICY_BLOCKED,
                ("required_disclosure_missing",),
            )
        if facts.emergency_detected:
            return VoiceDisposition(
                DispositionKind.HANDOFF_REQUIRED,
                ("emergency_detected",),
            )
        if facts.handoff_requested:
            return VoiceDisposition(
                DispositionKind.HANDOFF_REQUIRED,
                ("caller_requested_handoff",),
            )
        if facts.requested_service and facts.requested_service not in self.config.allowed_services:
            return VoiceDisposition(
                DispositionKind.POLICY_BLOCKED,
                ("unsupported_service",),
            )
        if facts.postal_code and facts.postal_code not in self.config.supported_postal_codes:
            return VoiceDisposition(
                DispositionKind.OUT_OF_AREA,
                ("outside_service_area",),
            )
        if facts.appointment_booked:
            if not facts.qualified:
                return VoiceDisposition(
                    DispositionKind.POLICY_BLOCKED,
                    ("booking_without_qualification",),
                )
            return VoiceDisposition(DispositionKind.BOOKED, ("appointment_confirmed",))

        missing = []
        if not facts.requested_service:
            missing.append("service_missing")
        if not facts.postal_code:
            missing.append("postal_code_missing")
        if not facts.qualified:
            missing.append("qualification_incomplete")
        if facts.ended_before_booking:
            missing.append("call_ended_before_booking")
        if not missing:
            missing.append("booking_not_completed")

        blockers = self._recovery_blockers(facts)
        if not blockers:
            return VoiceDisposition(
                DispositionKind.INCOMPLETE_BUT_RECOVERABLE,
                tuple(missing),
                recovery_allowed=True,
            )
        return VoiceDisposition(
            DispositionKind.INCOMPLETE_NOT_RECOVERABLE,
            tuple((*missing, *blockers)),
        )

    def _recovery_blockers(self, facts: CallFacts) -> tuple[str, ...]:
        blockers = []
        if self.config.package is not VoicePackage.REVENUE_RECOVERY:
            blockers.append("package_does_not_include_recovery")
        if not facts.follow_up_consent:
            blockers.append("follow_up_consent_missing")
        if facts.do_not_contact:
            blockers.append("do_not_contact")
        if not facts.contact_reference:
            blockers.append("contact_reference_missing")
        if not set(facts.contact_channels).intersection(self.config.recovery_channels):
            blockers.append("approved_contact_channel_missing")
        if facts.recovery_attempts >= self.config.max_recovery_attempts:
            blockers.append("recovery_attempt_limit_reached")
        return tuple(blockers)

