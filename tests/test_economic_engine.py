from decimal import Decimal

from hermes_ultra.economic.adapters.mock_stripe import MockStripeAdapter
from hermes_ultra.economic.contracts import EconomicMode, ExperimentStatus, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.engine import EconomicEngine
from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.economic.metrics import EconomicMetrics
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.strategies.base import RevenueOpportunity
from hermes_ultra.economic.strategies.service_sales import ServiceSalesStrategy


def opportunity():
    return RevenueOpportunity(
        prospect_id="plumber-42",
        offer="AI receptionist",
        contract_value=Decimal("499.00"),
        estimated_cost=Decimal("49.00"),
        currency="USD",
        evidence=("lead:plumber-42",),
    )


def test_engine_tracks_service_sales_lifecycle_and_stops_budget_use(tmp_path):
    state = EconomicState(mode=EconomicMode.SIMULATED)
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        engine = EconomicEngine(state=state, ledger=ledger, payment_adapter=MockStripeAdapter())
        experiment = engine.start_service_sales_experiment(
            ServiceSalesStrategy(), opportunity(), run_id="run-sales-1"
        )

        tracked = state.experiments[experiment.experiment_id]
        assert experiment.status is ExperimentStatus.RUNNING
        assert tracked.status is ExperimentStatus.RUNNING
        assert tracked.run_id == "run-sales-1"
        assert tracked.reserved_budget == Decimal("49.00")

        stopped = engine.stop_experiment(experiment.experiment_id)

        assert stopped.status is ExperimentStatus.STOPPED
        assert stopped.reserved_budget == Decimal("0")


def test_engine_records_mock_revenue_once_with_run_and_strategy_attribution(tmp_path):
    state = EconomicState(mode=EconomicMode.SIMULATED)
    stripe = MockStripeAdapter()
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        engine = EconomicEngine(state=state, ledger=ledger, payment_adapter=stripe)
        experiment = engine.start_service_sales_experiment(
            ServiceSalesStrategy(), opportunity(), run_id="run-sales-2"
        )

        first = engine.record_revenue(
            experiment.experiment_id,
            amount=Decimal("499.00"),
            currency="USD",
            idempotency_key="sale-1",
        )
        second = engine.record_revenue(
            experiment.experiment_id,
            amount=Decimal("499.00"),
            currency="USD",
            idempotency_key="sale-1",
        )
        revenue_entries = [entry for entry in ledger.entries() if entry.kind == "revenue"]

    assert first == second
    assert len(revenue_entries) == 1
    assert revenue_entries[0].run_id == "run-sales-2"
    assert revenue_entries[0].strategy_id == "service-sales"
    assert state.experiments[experiment.experiment_id].realized_revenue == Decimal("499.00")


def test_metrics_are_derived_from_recorded_economic_outcomes(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        tx = TransactionEnvelope.new(
            run_id="run-metrics",
            strategy_id="service-sales",
            bucket=TreasuryBucket.EXPERIMENTS,
            counterparty="vendor",
            amount="50.00",
            currency="USD",
            expected_value="500.00",
            maximum_loss="50.00",
            reason="acquisition test",
            source_evidence=(),
            authority_category="external_spend",
            mode=EconomicMode.SIMULATED,
        )
        ledger.record_transaction(tx)
        ledger.record_outcome(
            tx.transaction_id,
            status="success",
            amount=Decimal("50.00"),
            currency="USD",
        )
        ledger.record_revenue(
            run_id="run-metrics",
            strategy_id="service-sales",
            bucket=TreasuryBucket.GROWTH,
            amount=Decimal("500.00"),
            currency="USD",
        )

        metrics = EconomicMetrics.from_ledger(ledger, run_id="run-metrics")

    assert metrics.revenue == Decimal("500.00")
    assert metrics.cost == Decimal("50.00")
    assert metrics.gross_profit == Decimal("450.00")
    assert metrics.roi == Decimal("9")
