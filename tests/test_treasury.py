from decimal import Decimal

import pytest

from hermes_ultra.economic.authority import AuthorityDecision, AuthorityPolicy, FinancialAuthority
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.treasury import ReservationStatus, TreasuryManager

AUTHORITY_SECRET = b"test-treasury-authority-key-32-bytes"


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


def make_authority():
    return FinancialAuthority(
        AuthorityPolicy(
            policy_revision="finance-v1",
            registered_live_categories=frozenset({"external_spend"}),
            max_transaction_amount=Decimal("1000"),
            bucket_limits={TreasuryBucket.EXPERIMENTS: Decimal("1000")},
            simulated_auto_limit=Decimal("1000"),
            sandbox_auto_limit=Decimal("1000"),
        ),
        authority_secret=AUTHORITY_SECRET,
    )


def test_reserve_commit_and_replay_debit_exactly_once():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("100.00")},
    )
    authority = make_authority()
    treasury = TreasuryManager(state, authority)
    envelope = tx()
    decision = authority.evaluate(envelope)

    first = treasury.reserve(envelope, decision)
    replay = treasury.reserve(envelope, decision)

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
    authority = make_authority()
    treasury = TreasuryManager(state, authority)
    envelope = tx("25.00")

    treasury.reserve(envelope, authority.evaluate(envelope))
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("75.00")

    released = treasury.release(envelope.transaction_id)
    released_again = treasury.release(envelope.transaction_id)

    assert released.status is ReservationStatus.RELEASED
    assert released_again == released
    assert treasury.available(TreasuryBucket.EXPERIMENTS) == Decimal("100.00")
    assert state.balances[TreasuryBucket.EXPERIMENTS] == Decimal("100.00")


def test_treasury_rejects_fabricated_authority_insufficient_funds_and_mode_mismatch():
    state = EconomicState(
        mode=EconomicMode.SIMULATED,
        balances={TreasuryBucket.EXPERIMENTS: Decimal("30.00")},
    )
    authority = make_authority()
    treasury = TreasuryManager(state, authority)
    envelope = tx("10.00")
    forged = AuthorityDecision(True, False, "external_spend", "allowed", "finance-v1")

    with pytest.raises(PermissionError, match="attestation"):
        treasury.reserve(envelope, forged)

    over = tx("40.00")
    with pytest.raises(ValueError, match="insufficient"):
        treasury.reserve(over, authority.evaluate(over))

    live = tx("10.00", mode=EconomicMode.LIVE)
    live_decision = AuthorityDecision(
        allowed=True,
        authorization_required=False,
        category=live.authority_category,
        reason="allowed",
        policy_revision="finance-v1",
    )
    with pytest.raises(PermissionError):
        treasury.reserve(live, live_decision)


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
