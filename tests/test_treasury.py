from decimal import Decimal

import pytest

from hermes_ultra.economic.authority import AuthorityDecision
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.treasury import ReservationStatus, TreasuryManager


def tx(amount="40.00", *, mode=EconomicMode.SIMULATED):
    return TransactionEnvelope.new(
        run_id="run-treasury",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="vendor",
        amount=amount,
        currency="USD",
        expected_value="200.00",
        maximum_loss=amount,
        reason="experiment",
        source_evidence=(),
        authority_category="external_spend",
        mode=mode,
    )


def allowed():
    return AuthorityDecision(
        allowed=True,
        authorization_required=False,
        category="external_spend",
        reason="allowed",
        policy_revision="finance-v1",
    )


def test_reserve_commit_and_replay_debit_exactly_once():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("100.00")},
    )
    treasury = TreasuryManager(state)
    envelope = tx()

    first = treasury.reserve(envelope, allowed())
    replay = treasury.reserve(envelope, allowed())

    assert replay == first
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("60.00")
    assert state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("100.00")

    committed = treasury.commit(envelope.transaction_id)
    committed_again = treasury.commit(envelope.transaction_id)

    assert committed.status is ReservationStatus.COMMITTED
    assert committed_again == committed
    assert state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("60.00")
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("60.00")


def test_release_restores_available_capital_without_debit():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("100.00")},
    )
    treasury = TreasuryManager(state)
    envelope = tx("25.00")

    treasury.reserve(envelope, allowed())
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("75.00")

    released = treasury.release(envelope.transaction_id)
    released_again = treasury.release(envelope.transaction_id)

    assert released.status is ReservationStatus.RELEASED
    assert released_again == released
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("100.00")
    assert state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("100.00")


def test_treasury_rejects_denied_authority_insufficient_funds_and_mode_mismatch():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("30.00")},
    )
    treasury = TreasuryManager(state)
    denied = AuthorityDecision(False, True, "external_spend", "grant_required", "finance-v1")

    with pytest.raises(PermissionError):
        treasury.reserve(tx("10.00"), denied)
    with pytest.raises(ValueError, match="insufficient"):
        treasury.reserve(tx("40.00"), allowed())
    with pytest.raises(PermissionError, match="mode"):
        treasury.reserve(tx("10.00", mode=EconomicMode.LIVE), allowed())


def test_revenue_credit_is_idempotent():
    state = EconomicState(mode=EconomicMode.SIMULATED)
    treasury = TreasuryManager(state)

    first = treasury.credit_revenue(
        TreasuryBucket.GROWTH, Decimal("125.00"), event_key="sale-1"
    )
    second = treasury.credit_revenue(
        TreasuryBucket.GROWTH, Decimal("125.00"), event_key="sale-1"
    )

    assert first == second == Decimal("125.00")
    assert state.balances[TreasuryBucket.GROWTH] == Decimal("125.00")
