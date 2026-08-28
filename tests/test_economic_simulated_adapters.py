from decimal import Decimal

from hermes_ultra.economic.adapters.mock_stripe import MockStripeAdapter
from hermes_ultra.economic.adapters.simulated_wallet import SimulatedWalletAdapter
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket


def make_transfer(amount="25.00", *, mode=EconomicMode.SIMULATED):
    return TransactionEnvelope.new(
        run_id="run-sim-1",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="vendor-1",
        amount=amount,
        currency="USD",
        expected_value="100.00",
        maximum_loss=amount,
        reason="simulated acquisition test",
        source_evidence=("lead:1",),
        authority_category="external_spend",
        mode=mode,
    )


def test_simulated_wallet_transfer_is_idempotent_and_debits_once():
    wallet = SimulatedWalletAdapter({TreasuryBucket.EXPERIMENTS: Decimal("100.00")})
    tx = make_transfer()

    first = wallet.transfer(tx)
    second = wallet.transfer(tx)

    assert first.ok is True
    assert second == first
    assert wallet.balance(TreasuryBucket.EXPERIMENTS) == Decimal("75.00")
    assert first.external_id.startswith("sim_")


def test_simulated_wallet_rejects_insufficient_funds_without_debit():
    wallet = SimulatedWalletAdapter({TreasuryBucket.EXPERIMENTS: Decimal("10.00")})

    result = wallet.transfer(make_transfer("25.00"))

    assert result.ok is False
    assert result.status == "insufficient_funds"
    assert wallet.balance(TreasuryBucket.EXPERIMENTS) == Decimal("10.00")


def test_simulated_wallet_rejects_non_simulated_mode():
    wallet = SimulatedWalletAdapter({TreasuryBucket.EXPERIMENTS: Decimal("100.00")})

    result = wallet.transfer(make_transfer(mode=EconomicMode.LIVE))

    assert result.ok is False
    assert result.status == "mode_blocked"
    assert wallet.balance(TreasuryBucket.EXPERIMENTS) == Decimal("100.00")


def test_mock_stripe_payment_and_revenue_are_deterministic_and_idempotent():
    stripe = MockStripeAdapter()

    payment_one = stripe.create_payment(
        run_id="run-1",
        strategy_id="service-sales",
        amount=Decimal("499.00"),
        currency="USD",
        idempotency_key="payment-key-1",
        mode=EconomicMode.SIMULATED,
    )
    payment_two = stripe.create_payment(
        run_id="run-1",
        strategy_id="service-sales",
        amount=Decimal("499.00"),
        currency="USD",
        idempotency_key="payment-key-1",
        mode=EconomicMode.SIMULATED,
    )
    revenue_one = stripe.record_revenue(
        run_id="run-1",
        strategy_id="service-sales",
        amount=Decimal("499.00"),
        currency="USD",
        idempotency_key="revenue-key-1",
        mode=EconomicMode.SIMULATED,
    )
    revenue_two = stripe.record_revenue(
        run_id="run-1",
        strategy_id="service-sales",
        amount=Decimal("499.00"),
        currency="USD",
        idempotency_key="revenue-key-1",
        mode=EconomicMode.SIMULATED,
    )

    assert payment_one == payment_two
    assert revenue_one == revenue_two
    assert payment_one.external_id.startswith("mock_pi_")
    assert revenue_one.external_id.startswith("mock_rev_")
    assert stripe.total_revenue == Decimal("499.00")


def test_mock_stripe_rejects_non_simulated_mode_without_recording_revenue():
    stripe = MockStripeAdapter()

    result = stripe.record_revenue(
        run_id="run-live",
        strategy_id="service-sales",
        amount=Decimal("1000.00"),
        currency="USD",
        idempotency_key="live-key",
        mode=EconomicMode.LIVE,
    )

    assert result.ok is False
    assert result.status == "mode_blocked"
    assert stripe.total_revenue == Decimal("0")
