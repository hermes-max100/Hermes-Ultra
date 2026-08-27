from decimal import Decimal

from hermes_ultra.economic.authority import AuthorityDecision
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.treasury import TreasuryManager


def test_reservations_and_revenue_credit_keys_survive_state_restart():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("100"), TreasuryBucket.GROWTH: Decimal("0")},
    )
    treasury = TreasuryManager(state)
    envelope = TransactionEnvelope.new(
        run_id="run-restart",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="vendor",
        amount="40",
        currency="USD",
        expected_value="200",
        maximum_loss="40",
        reason="restart test",
        source_evidence=(),
        authority_category="external_spend",
        mode=EconomicMode.SIMULATED,
    )
    decision = AuthorityDecision(True, False, "external_spend", "allowed", "finance-v1")

    treasury.reserve(envelope, decision)
    treasury.credit_revenue(TreasuryBucket.GROWTH, Decimal("125"), event_key="sale-restart")

    restored_state = EconomicState.from_dict(state.to_dict())
    restored = TreasuryManager(restored_state)

    assert restored.available(TreasuryBucket.EXPERIMENTS) == Decimal("60")
    assert restored.reserve(envelope, decision).transaction_id == envelope.transaction_id
    assert restored.credit_revenue(
        TreasuryBucket.GROWTH, Decimal("125"), event_key="sale-restart"
    ) == Decimal("125")
    assert restored_state.balances[TreasuryBucket.GROWTH] == Decimal("125")
