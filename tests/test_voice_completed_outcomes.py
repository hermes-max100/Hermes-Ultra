from __future__ import annotations

from decimal import Decimal

import pytest

from hermes_ultra.economic import EconomicLedger, EconomicMetrics
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.voice import CallContext, VoicePackage, VoicePolicyConfig, VoicePolicyEngine, VoiceRevenueRuntime


def _runtime(tmp_path):
    ledger = EconomicLedger(tmp_path / "voice.sqlite3")
    policy = VoicePolicyEngine(
        VoicePolicyConfig(
            package=VoicePackage.REVENUE_RECOVERY,
            supported_postal_codes=frozenset({"90210"}),
            allowed_services=frozenset({"plumbing"}),
        )
    )
    return VoiceRevenueRuntime(policy=policy, evidence=EvidenceRecorder(), ledger=ledger), ledger


def test_completed_job_records_one_completed_outcome_and_attributed_revenue(tmp_path) -> None:
    runtime, ledger = _runtime(tmp_path)
    context = CallContext(call_id="call-1", run_id="run-1", tenant_id="tenant-1")
    ledger.record_business_outcome(
        run_id=context.run_id,
        strategy_id=runtime.strategy_id,
        outcome_type="appointment_booked",
        currency=context.currency,
        metadata={"call_id": context.call_id, "booking_reference": "booking-1"},
        idempotency_key="voice:call-1:appointment",
    )

    first = runtime.record_completed_job(
        context,
        booking_reference="booking-1",
        job_reference="job-1",
        attributed_revenue=Decimal("1250.00"),
    )
    second = runtime.record_completed_job(
        context,
        booking_reference="booking-1",
        job_reference="job-1",
        attributed_revenue=Decimal("1250.00"),
    )

    metrics = EconomicMetrics.from_ledger(ledger, run_id=context.run_id)
    completed = [
        item for item in ledger.entries()
        if item.kind == "business_outcome" and item.status == "completed_outcome"
    ]
    revenue = [item for item in ledger.entries() if item.kind == "revenue"]

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert len(completed) == 1
    assert len(revenue) == 1
    assert metrics.completed_outcomes == 1
    assert metrics.attributed_revenue == Decimal("1250.00")


def test_completed_job_fails_closed_without_prior_booking(tmp_path) -> None:
    runtime, _ledger = _runtime(tmp_path)
    context = CallContext(call_id="call-2", run_id="run-2", tenant_id="tenant-1")

    with pytest.raises(PermissionError, match="appointment"):
        runtime.record_completed_job(
            context,
            booking_reference="booking-2",
            job_reference="job-2",
            attributed_revenue=Decimal("500"),
        )


def test_completed_job_rejects_conflicting_idempotent_revenue_retry(tmp_path) -> None:
    runtime, ledger = _runtime(tmp_path)
    context = CallContext(call_id="call-3", run_id="run-3", tenant_id="tenant-1")
    ledger.record_business_outcome(
        run_id=context.run_id,
        strategy_id=runtime.strategy_id,
        outcome_type="appointment_booked",
        currency=context.currency,
        metadata={"call_id": context.call_id, "booking_reference": "booking-3"},
        idempotency_key="voice:call-3:appointment",
    )
    runtime.record_completed_job(
        context,
        booking_reference="booking-3",
        job_reference="job-3",
        attributed_revenue=Decimal("900"),
    )

    with pytest.raises(ValueError, match="conflicting"):
        runtime.record_completed_job(
            context,
            booking_reference="booking-3",
            job_reference="job-3",
            attributed_revenue=Decimal("901"),
        )
