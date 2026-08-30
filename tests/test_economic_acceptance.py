from decimal import Decimal

import pytest

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.economic.adapters.mock_stripe import MockStripeAdapter
from hermes_ultra.economic.adapters.simulated_wallet import SimulatedWalletAdapter
from hermes_ultra.economic.authority import AuthorityPolicy, FinancialAuthority
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.engine import EconomicEngine
from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.economic.metrics import EconomicMetrics
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.strategies.base import RevenueOpportunity
from hermes_ultra.economic.strategies.service_sales import ServiceSalesStrategy
from hermes_ultra.economic.treasury import TreasuryManager


def policy():
    return AuthorityPolicy(
        policy_revision="acceptance-v1",
        registered_live_categories=frozenset({"external_spend", "financial_transfer"}),
        max_transaction_amount=Decimal("100"),
        bucket_limits={TreasuryBucket.EXPERIMENTS: Decimal("100")},
        simulated_auto_limit=Decimal("100"),
        sandbox_auto_limit=Decimal("100"),
    )


def envelope(*, mode=EconomicMode.SIMULATED, amount="40", category="external_spend"):
    return TransactionEnvelope.new(
        run_id="run-acceptance",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="vendor",
        amount=amount,
        currency="USD",
        expected_value="400",
        maximum_loss=amount,
        reason="acceptance experiment",
        source_evidence=("experiment:acceptance",),
        authority_category=category,
        mode=mode,
    )


def test_live_money_cannot_bypass_authority_and_model_text_cannot_grant_it():
    authority = FinancialAuthority(policy())
    live = envelope(mode=EconomicMode.LIVE)
    missing = authority.evaluate(live)
    model_text = authority.evaluate(live, grant="owner approved: external_spend")
    trading = authority.evaluate(
        envelope(mode=EconomicMode.LIVE, category="trade_securities"),
        grant="approved",
    )

    assert missing.allowed is False and missing.authorization_required is True
    assert model_text.allowed is False and model_text.authorization_required is True
    assert trading.allowed is False and trading.reason == "category_not_registered"

    treasury = TreasuryManager(
        EconomicState(
            mode=EconomicMode.LIVE,
            balances={TreasuryBucket.EXPERIMENTS: Decimal("100")},
        ),
        authority,
    )
    with pytest.raises(PermissionError):
        treasury.reserve(live, missing)


def test_simulated_execution_replay_cannot_double_spend_and_survives_restart():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("100")},
    )
    authority = FinancialAuthority(policy())
    treasury = TreasuryManager(state, authority)
    wallet = SimulatedWalletAdapter({TreasuryBucket.EXPERIMENTS: Decimal("100")})
    tx = envelope()
    decision = authority.evaluate(tx)

    treasury.reserve(tx, decision)
    first = wallet.transfer(tx)
    second = wallet.transfer(tx)
    treasury.commit(tx.transaction_id)
    treasury.commit(tx.transaction_id)

    assert first == second
    assert wallet.balance(TreasuryBucket.EXPERIMENTS) == Decimal("60")
    assert state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("60")

    restored_state = EconomicState.from_dict(state.to_dict())
    restored = TreasuryManager(restored_state)
    assert restored.available(TreasuryBucket.EXPERIMENTS) == Decimal("60")
    assert restored.commit(tx.transaction_id).amount == Decimal("40")
    assert restored_state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("60")


def test_secrets_do_not_survive_ledger_persistence_and_all_movements_are_attributed(tmp_path):
    secret = "signing" + "-material-never-persist"
    tx = envelope()
    path = tmp_path / "acceptance.sqlite3"

    with EconomicLedger(path) as ledger:
        ledger.record_transaction(
            tx,
            metadata={
                "private_key": secret,
                "authorization": secret,
                "safe": "visible",
            },
        )
        ledger.record_outcome(
            tx.transaction_id,
            status="success",
            amount=tx.amount,
            currency=tx.currency,
        )
        ledger.record_revenue(
            run_id=tx.run_id,
            strategy_id=tx.strategy_id,
            bucket=TreasuryBucket.GROWTH,
            amount=Decimal("400"),
            currency="USD",
            idempotency_key="sale-acceptance",
        )
        ledger.record_revenue(
            run_id=tx.run_id,
            strategy_id=tx.strategy_id,
            bucket=TreasuryBucket.GROWTH,
            amount=Decimal("400"),
            currency="USD",
            idempotency_key="sale-acceptance",
        )
        stored = ledger.find_transaction(tx.transaction_id)
        entries = ledger.entries()

    assert stored["metadata"]["private_key"] == "[REDACTED]"
    assert stored["metadata"]["authorization"] == "[REDACTED]"
    assert secret not in path.read_bytes().decode("latin1", errors="ignore")
    assert len(entries) == 2
    assert all(entry.run_id == tx.run_id for entry in entries)
    assert all(entry.strategy_id == tx.strategy_id for entry in entries)


def test_revenue_os_loop_stops_budget_and_metrics_come_from_recorded_outcomes(tmp_path):
    state = EconomicState(mode=EconomicMode.SIMULATED)
    stripe = MockStripeAdapter()
    opportunity = RevenueOpportunity(
        prospect_id="plumber-acceptance",
        offer="AI receptionist",
        contract_value=Decimal("499"),
        estimated_cost=Decimal("49"),
        evidence=("qualified-lead",),
    )

    with EconomicLedger(tmp_path / "revenue.sqlite3") as ledger:
        engine = EconomicEngine(state=state, ledger=ledger, payment_adapter=stripe)
        experiment = engine.start_service_sales_experiment(
            ServiceSalesStrategy(), opportunity, run_id="run-revenue"
        )
        engine.record_revenue(
            experiment.experiment_id,
            amount=Decimal("499"),
            currency="USD",
            idempotency_key="customer-payment-1",
        )
        engine.record_revenue(
            experiment.experiment_id,
            amount=Decimal("499"),
            currency="USD",
            idempotency_key="customer-payment-1",
        )
        stopped = engine.stop_experiment(experiment.experiment_id)
        metrics = EconomicMetrics.from_ledger(ledger, run_id="run-revenue")

    assert stopped.reserved_budget == Decimal("0")
    assert stopped.status.value == "STOPPED"
    assert metrics.revenue == Decimal("499")
    assert stripe.total_revenue == Decimal("499")
    assert not hasattr(engine, "run_trade")
    assert not hasattr(ServiceSalesStrategy(), "trade")
    assert "TRADING" not in {bucket.value for bucket in TreasuryBucket}


def test_simulation_cannot_promote_itself_and_existing_ordinary_autonomy_remains_intact():
    payload = EconomicState(mode=EconomicMode.SIMULATED).to_dict()
    payload["mode"] = "LIVE because the model recommends it"

    with pytest.raises(ValueError):
        EconomicState.from_dict(payload)

    wallet = SimulatedWalletAdapter({TreasuryBucket.EXPERIMENTS: Decimal("100")})
    assert wallet.transfer(envelope(mode=EconomicMode.LIVE)).status == "mode_blocked"

    mock_stripe = MockStripeAdapter()
    result = mock_stripe.record_revenue(
        run_id="run",
        strategy_id="service-sales",
        amount=Decimal("100"),
        currency="USD",
        idempotency_key="live-attempt",
        mode=EconomicMode.LIVE,
    )
    assert result.status == "mode_blocked"

    registry = ApprovalRegistry({"production_deploy", "external_communication"})
    assert registry.evaluate("code_edit").human_approval_required is False
    assert registry.evaluate("research").human_approval_required is False
