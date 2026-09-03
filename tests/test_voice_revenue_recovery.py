from datetime import datetime, timezone
from decimal import Decimal

import pytest

from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.voice import (
    CallContext,
    CallFacts,
    ContactChannel,
    DispositionKind,
    InvalidVoiceTransition,
    VoiceBenchmarkObservation,
    VoiceCallState,
    VoiceCallStateMachine,
    VoicePackage,
    VoicePolicyConfig,
    VoicePolicyEngine,
    VoiceReleaseGate,
    VoiceRevenueRuntime,
    VoiceTransitionReceipt,
    aggregate_voice_benchmark,
    home_services_offers,
)


def recovery_config(**overrides):
    values = {
        "package": VoicePackage.REVENUE_RECOVERY,
        "supported_postal_codes": frozenset({"90210", "90001"}),
        "allowed_services": frozenset({"plumbing", "hvac"}),
        "recovery_channels": (ContactChannel.SMS, ContactChannel.EMAIL),
        "max_recovery_attempts": 2,
        "recovery_window_hours": 24,
    }
    values.update(overrides)
    return VoicePolicyConfig(**values)


def context():
    return CallContext(call_id="call-42", run_id="run-42", tenant_id="plumber-42")


def recoverable_facts(**overrides):
    values = {
        "disclosure_complete": True,
        "requested_service": "plumbing",
        "postal_code": "90210",
        "qualified": True,
        "ended_before_booking": True,
        "follow_up_consent": True,
        "contact_reference": "crm-contact-42",
        "contact_channels": frozenset({ContactChannel.SMS}),
    }
    values.update(overrides)
    return CallFacts(**values)


def observation(provider, case, **overrides):
    values = {
        "booking_completed": True,
        "critical_fields_correct": True,
        "handoff_correct": True,
        "policy_violation": False,
        "recovery_attempted": True,
        "recovery_succeeded": True,
        "latency_ms": 500,
        "cost_usd": Decimal("2"),
        "evidence_complete": True,
    }
    values.update(overrides)
    return VoiceBenchmarkObservation(provider=provider, case=case, **values)


def test_call_state_machine_is_replayable_and_rejects_skips():
    machine = VoiceCallStateMachine()
    machine.transition(VoiceCallState.CONNECTED, reason="call answered")
    machine.transition(VoiceCallState.DISCLOSED, reason="required disclosure completed")
    machine.transition(VoiceCallState.QUALIFYING, reason="intake started")
    machine.transition(VoiceCallState.ELIGIBLE, reason="service and area eligible")
    machine.transition(VoiceCallState.BOOKING, reason="calendar lookup started")
    machine.transition(VoiceCallState.BOOKED, reason="appointment confirmed")
    machine.transition(VoiceCallState.ENDED, reason="call completed")

    replayed = VoiceCallStateMachine.replay(machine.receipts)

    assert replayed.state is VoiceCallState.ENDED
    assert replayed.receipts == machine.receipts
    with pytest.raises(InvalidVoiceTransition):
        VoiceCallStateMachine().transition(VoiceCallState.BOOKED, reason="unsafe skip")


def test_transition_replay_rejects_tampered_sequence():
    receipt = VoiceTransitionReceipt(
        sequence=4,
        previous=VoiceCallState.INITIATED,
        current=VoiceCallState.CONNECTED,
        reason="tampered",
    )

    with pytest.raises(InvalidVoiceTransition):
        VoiceCallStateMachine.replay((receipt,))


def test_policy_routes_emergencies_before_recovery():
    result = VoicePolicyEngine(recovery_config()).evaluate(
        recoverable_facts(emergency_detected=True)
    )

    assert result.kind is DispositionKind.HANDOFF_REQUIRED
    assert result.recovery_allowed is False


def test_policy_fails_closed_without_disclosure_or_qualification():
    engine = VoicePolicyEngine(recovery_config())

    disclosure = engine.evaluate(recoverable_facts(disclosure_complete=False))
    invalid_booking = engine.evaluate(
        recoverable_facts(qualified=False, appointment_booked=True)
    )

    assert disclosure.kind is DispositionKind.POLICY_BLOCKED
    assert invalid_booking.kind is DispositionKind.POLICY_BLOCKED


def test_receptionist_package_cannot_trigger_recovery():
    config = recovery_config(package=VoicePackage.RECEPTIONIST)

    result = VoicePolicyEngine(config).evaluate(recoverable_facts())

    assert result.kind is DispositionKind.INCOMPLETE_NOT_RECOVERABLE
    assert "package_does_not_include_recovery" in result.reasons


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"follow_up_consent": False}, "follow_up_consent_missing"),
        ({"do_not_contact": True}, "do_not_contact"),
        ({"contact_reference": None}, "contact_reference_missing"),
        ({"contact_channels": frozenset()}, "approved_contact_channel_missing"),
        ({"recovery_attempts": 2}, "recovery_attempt_limit_reached"),
    ],
)
def test_recovery_policy_blocks_missing_authority(overrides, reason):
    result = VoicePolicyEngine(recovery_config()).evaluate(recoverable_facts(**overrides))

    assert result.kind is DispositionKind.INCOMPLETE_NOT_RECOVERABLE
    assert reason in result.reasons


def test_runtime_stages_recovery_and_records_no_false_appointment(tmp_path):
    recorder = EvidenceRecorder()
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        runtime = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config()),
            evidence=recorder,
            ledger=ledger,
        )

        result = runtime.finalize_call(context(), recoverable_facts())
        metrics_entries = ledger.entries()

    assert result.disposition.kind is DispositionKind.INCOMPLETE_BUT_RECOVERABLE
    assert result.recovery_plan is not None and result.recovery_plan.staged
    assert [step.kind.value for step in result.recovery_plan.steps] == [
        "send_sms",
        "create_crm_task",
        "verify_booking",
    ]
    assert [entry.status for entry in metrics_entries] == ["qualified_lead"]
    assert result.evidence["artifacts"][0]["recovery_staged"] is True


def test_runtime_records_bookings_idempotently(tmp_path):
    recorder = EvidenceRecorder()
    booked = recoverable_facts(appointment_booked=True, ended_before_booking=False)
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        runtime = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config()),
            evidence=recorder,
            ledger=ledger,
        )

        runtime.finalize_call(context(), booked)
        runtime.finalize_call(context(), booked)
        entries = ledger.entries()

    assert [entry.status for entry in entries] == ["qualified_lead", "appointment_booked"]


def test_recovered_booking_is_separate_attributed_outcome(tmp_path):
    recorder = EvidenceRecorder()
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        runtime = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config()),
            evidence=recorder,
            ledger=ledger,
        )
        result = runtime.finalize_call(context(), recoverable_facts())
        assert result.recovery_plan is not None

        evidence = runtime.record_recovered_booking(
            context(), result.recovery_plan, booking_reference="booking-77"
        )
        runtime.record_recovered_booking(
            context(), result.recovery_plan, booking_reference="booking-provider-replay"
        )
        recovered = [entry for entry in ledger.entries() if entry.status == "appointment_booked"]

    assert len(recovered) == 1
    assert recovered[0].metadata["recovered"] is True
    assert recovered[0].metadata["recovery_attempt"] == 1
    assert evidence["capability"] == "voice-recovery-attribution"


def test_expired_recovery_plan_cannot_claim_an_appointment(tmp_path):
    recorder = EvidenceRecorder()
    start = datetime(2026, 9, 3, tzinfo=timezone.utc)
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        runtime = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config(recovery_window_hours=1)),
            evidence=recorder,
            ledger=ledger,
        )
        disposition = runtime.policy.evaluate(recoverable_facts())
        plan = runtime.recovery.build(context(), recoverable_facts(), disposition, now=start)

        with pytest.raises(PermissionError, match="not active"):
            runtime.record_recovered_booking(
                context(),
                plan,
                booking_reference="booking-too-late",
                now=datetime(2026, 9, 3, 1, tzinfo=timezone.utc),
            )

        assert all(entry.status != "appointment_booked" for entry in ledger.entries())


def test_evidence_redacts_contact_references_that_look_like_secrets(tmp_path):
    recorder = EvidenceRecorder()
    facts = recoverable_facts(contact_reference="session_id=private-contact")
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        result = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config()),
            evidence=recorder,
            ledger=ledger,
        ).finalize_call(context(), facts)

    assert "private-contact" not in repr(result.evidence)


def test_package_factory_preserves_prices_and_requires_real_usage_caps():
    receptionist, recovery = home_services_offers(
        receptionist_minutes=500,
        recovery_minutes=1000,
        overage_per_minute="0.25",
    )

    assert receptionist.monthly_fee == Decimal("499")
    assert recovery.monthly_fee == Decimal("749")
    assert receptionist.estimate_monthly_total(600) == Decimal("524.00")
    assert "recover_incomplete_calls" in recovery.capabilities
    with pytest.raises(ValueError):
        home_services_offers(
            receptionist_minutes=0,
            recovery_minutes=1000,
            overage_per_minute="0.25",
        )


def test_voice_release_gate_uses_outcomes_safety_latency_and_cost():
    baseline = aggregate_voice_benchmark(
        observation("elevenlabs", f"case-{index}") for index in range(3)
    )
    candidate = aggregate_voice_benchmark(
        observation("candidate", f"case-{index}", latency_ms=400, cost_usd="1")
        for index in range(3)
    )

    decision = VoiceReleaseGate(
        minimum_cases=3,
        max_p95_latency_ms=600,
        max_cost_per_completed_booking="5",
    ).evaluate(baseline, candidate)

    assert decision.promoted is True


def test_voice_release_gate_rejects_policy_or_quality_regression():
    baseline = aggregate_voice_benchmark(
        observation("elevenlabs", f"case-{index}") for index in range(2)
    )
    candidate = aggregate_voice_benchmark(
        (
            observation("candidate", "case-0", policy_violation=True),
            observation("candidate", "case-1", critical_fields_correct=False),
        )
    )

    decision = VoiceReleaseGate(minimum_cases=2).evaluate(baseline, candidate)

    assert decision.promoted is False
    assert "policy_violation" in decision.reason
    assert "critical_field_regression" in decision.reason


def test_recovery_plan_has_bounded_timezone_aware_expiry(tmp_path):
    recorder = EvidenceRecorder()
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        runtime = VoiceRevenueRuntime(
            policy=VoicePolicyEngine(recovery_config(recovery_window_hours=12)),
            evidence=recorder,
            ledger=ledger,
        )
        disposition = runtime.policy.evaluate(recoverable_facts())
        plan = runtime.recovery.build(context(), recoverable_facts(), disposition, now=now)

    assert plan.expires_at.isoformat() == "2026-09-03T12:00:00+00:00"
