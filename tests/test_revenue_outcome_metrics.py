from decimal import Decimal

import pytest

from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.engine import EconomicEngine
from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.economic.metrics import EconomicMetrics
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.strategies.base import RevenueOpportunity
from hermes_ultra.economic.strategies.service_sales import ServiceSalesStrategy


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


@pytest.mark.parametrize("idempotency_key", [None, "", "   "])
def test_business_outcome_requires_non_empty_idempotency_key(tmp_path, idempotency_key):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        with pytest.raises(ValueError, match="idempotency"):
            ledger.record_business_outcome(
                run_id="run-outcomes",
                strategy_id="service-sales",
                outcome_type="completed_outcome",
                currency="USD",
                idempotency_key=idempotency_key,
            )


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


def test_scorecard_requires_currency_scope_for_mixed_currency_ledger(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        ledger.record_business_outcome(
            run_id="run-currency",
            strategy_id="service-sales",
            outcome_type="qualified_lead",
            currency="USD",
            idempotency_key="lead:usd",
        )
        ledger.record_business_outcome(
            run_id="run-currency",
            strategy_id="service-sales",
            outcome_type="completed_outcome",
            currency="USD",
            idempotency_key="sale:usd",
        )
        ledger.record_revenue(
            run_id="run-currency",
            strategy_id="service-sales",
            bucket=TreasuryBucket.GROWTH,
            amount="500.00",
            currency="USD",
            idempotency_key="revenue:usd",
        )
        ledger.record_revenue(
            run_id="run-currency",
            strategy_id="service-sales",
            bucket=TreasuryBucket.GROWTH,
            amount="1000",
            currency="JPY",
            idempotency_key="revenue:jpy",
        )

        with pytest.raises(ValueError, match="mixed currencies"):
            EconomicMetrics.from_ledger(ledger, run_id="run-currency")

        usd_metrics = EconomicMetrics.from_ledger(
            ledger,
            run_id="run-currency",
            currency="usd",
        )

    assert usd_metrics.attributed_revenue == Decimal("500.00")
    assert usd_metrics.completed_outcomes == 1
    assert usd_metrics.conversion_rate == Decimal("1")


def test_engine_rejects_negative_revenue_before_payment_adapter_is_called(tmp_path):
    class AdapterMustNotRun:
        def record_revenue(self, **kwargs):
            raise AssertionError("payment adapter must not receive negative revenue")

    opportunity = RevenueOpportunity(
        prospect_id="plumber-negative",
        offer="AI receptionist",
        contract_value=Decimal("499"),
        estimated_cost=Decimal("49"),
        evidence=("lead:negative",),
    )
    state = EconomicState(mode=EconomicMode.SIMULATED)
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        engine = EconomicEngine(
            state=state,
            ledger=ledger,
            payment_adapter=AdapterMustNotRun(),
        )
        experiment = engine.start_service_sales_experiment(
            ServiceSalesStrategy(),
            opportunity,
            run_id="run-negative",
        )

        with pytest.raises(ValueError, match="negative"):
            engine.record_revenue(
                experiment.experiment_id,
                amount=Decimal("-1"),
                currency="USD",
                idempotency_key="negative:1",
            )


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


def test_resource_allocation_holds_non_positive_revenue_even_if_margin_is_malformed():
    metrics = EconomicMetrics(
        revenue=Decimal("-100"),
        cost=Decimal("10"),
        gross_profit=Decimal("-110"),
        roi=Decimal("-11"),
        qualified_leads=1,
        completed_outcomes=1,
        conversion_rate=Decimal("1"),
        attributed_revenue=Decimal("-100"),
        gross_margin=Decimal("1.1"),
        cost_per_completed_outcome=Decimal("10"),
    )

    signal = metrics.resource_allocation_signal(
        max_cost_per_completed_outcome=Decimal("100"),
        min_gross_margin=Decimal("0.5"),
        min_conversion_rate=Decimal("0.1"),
        min_completed_outcomes=1,
    )

    assert signal.action == "hold"
    assert "non_positive_attributed_revenue" in signal.reasons


def test_resource_allocation_holds_inconsistent_funnel_counts():
    metrics = EconomicMetrics(
        revenue=Decimal("500"),
        cost=Decimal("50"),
        gross_profit=Decimal("450"),
        roi=Decimal("9"),
        qualified_leads=1,
        completed_outcomes=2,
        conversion_rate=Decimal("2"),
        attributed_revenue=Decimal("500"),
        gross_margin=Decimal("0.9"),
        cost_per_completed_outcome=Decimal("25"),
    )

    signal = metrics.resource_allocation_signal(
        max_cost_per_completed_outcome=Decimal("100"),
        min_gross_margin=Decimal("0.5"),
        min_conversion_rate=Decimal("0.1"),
        min_completed_outcomes=1,
    )

    assert signal.action == "hold"
    assert "invalid_funnel_counts" in signal.reasons
