from decimal import Decimal

from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.economic.metrics import EconomicMetrics


def test_business_outcome_events_are_first_class_and_idempotent(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        first = ledger.record_business_outcome(
            run_id="run-outcomes",
            strategy_id="service-sales",
            outcome_type="qualified_lead",
            currency="USD",
            metadata={"prospect_id": "plumber-42"},
            idempotency_key="lead:plumber-42",
        )
        second = ledger.record_business_outcome(
            run_id="run-outcomes",
            strategy_id="service-sales",
            outcome_type="qualified_lead",
            currency="USD",
            metadata={"prospect_id": "plumber-42"},
            idempotency_key="lead:plumber-42",
        )
        rows = [entry for entry in ledger.entries() if entry.kind == "business_outcome"]

    assert first == second
    assert len(rows) == 1
    assert rows[0].status == "qualified_lead"
    assert rows[0].metadata["prospect_id"] == "plumber-42"


def test_scorecard_derives_funnel_and_cost_per_completed_outcome(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        transaction = TransactionEnvelope.new(
            run_id="run-scorecard",
            strategy_id="service-sales",
            bucket=TreasuryBucket.EXPERIMENTS,
            counterparty="acquisition-channel",
            amount="50.00",
            currency="USD",
            expected_value="500.00",
            maximum_loss="50.00",
            reason="customer acquisition",
            source_evidence=(),
            authority_category="external_spend",
            mode=EconomicMode.SIMULATED,
        )
        ledger.record_transaction(transaction)
        ledger.record_outcome(
            transaction.transaction_id,
            status="success",
            amount="50.00",
            currency="USD",
        )
        for index in range(4):
            ledger.record_business_outcome(
                run_id="run-scorecard",
                strategy_id="service-sales",
                outcome_type="qualified_lead",
                currency="USD",
                idempotency_key=f"lead:{index}",
            )
        for index in range(2):
            ledger.record_business_outcome(
                run_id="run-scorecard",
                strategy_id="service-sales",
                outcome_type="appointment_booked",
                currency="USD",
                idempotency_key=f"appointment:{index}",
            )
        ledger.record_business_outcome(
            run_id="run-scorecard",
            strategy_id="service-sales",
            outcome_type="completed_outcome",
            currency="USD",
            idempotency_key="sale:1",
        )
        ledger.record_revenue(
            run_id="run-scorecard",
            strategy_id="service-sales",
            bucket=TreasuryBucket.GROWTH,
            amount="500.00",
            currency="USD",
            idempotency_key="sale:1",
        )

        metrics = EconomicMetrics.from_ledger(ledger, run_id="run-scorecard")

    assert metrics.qualified_leads == 4
    assert metrics.appointments_booked == 2
    assert metrics.completed_outcomes == 1
    assert metrics.conversion_rate == Decimal("0.25")
    assert metrics.attributed_revenue == Decimal("500.00")
    assert metrics.gross_margin == Decimal("0.9")
    assert metrics.cost_per_completed_outcome == Decimal("50.00")


def test_resource_allocation_signal_uses_outcomes_not_activity_volume():
    metrics = EconomicMetrics(
        revenue=Decimal("500"),
        cost=Decimal("50"),
        gross_profit=Decimal("450"),
        roi=Decimal("9"),
        qualified_leads=4,
        appointments_booked=2,
        completed_outcomes=1,
        conversion_rate=Decimal("0.25"),
        attributed_revenue=Decimal("500"),
        gross_margin=Decimal("0.9"),
        cost_per_completed_outcome=Decimal("50"),
    )

    increase = metrics.resource_allocation_signal(
        max_cost_per_completed_outcome=Decimal("100"),
        min_gross_margin=Decimal("0.5"),
        min_conversion_rate=Decimal("0.1"),
        min_completed_outcomes=1,
    )
    hold = metrics.resource_allocation_signal(
        max_cost_per_completed_outcome=Decimal("25"),
        min_gross_margin=Decimal("0.5"),
        min_conversion_rate=Decimal("0.1"),
        min_completed_outcomes=1,
    )

    assert increase.action == "increase"
    assert increase.reasons == ()
    assert hold.action == "hold"
    assert "cost_per_completed_outcome_above_limit" in hold.reasons
