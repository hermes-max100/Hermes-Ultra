from decimal import Decimal

import pytest

from hermes_ultra.economic.contracts import (
    EconomicMode,
    ExperimentStatus,
    TransactionEnvelope,
    TreasuryBucket,
)
from hermes_ultra.economic.state import EconomicState, ExperimentState


def test_transaction_envelope_normalizes_decimal_and_has_stable_identity():
    envelope = TransactionEnvelope.new(
        run_id="run-1",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="prospect-1",
        amount="12.50",
        currency="USD",
        expected_value="50.00",
        maximum_loss="12.50",
        reason="demo campaign",
        source_evidence=("lead:1",),
        authority_category="external_spend",
        mode=EconomicMode.SIMULATED,
        ttl_seconds=60,
    )

    assert envelope.amount == Decimal("12.50")
    assert envelope.expected_value == Decimal("50.00")
    assert envelope.maximum_loss == Decimal("12.50")
    assert envelope.transaction_id
    assert envelope.idempotency_key
    assert envelope.transaction_id != envelope.idempotency_key
    assert envelope.mode is EconomicMode.SIMULATED
    assert envelope.expires_at > envelope.created_at


def test_transaction_envelope_is_immutable():
    envelope = TransactionEnvelope.new(
        run_id="run-1",
        strategy_id="service-sales",
        bucket=TreasuryBucket.OPERATIONS,
        counterparty="vendor",
        amount="1",
        currency="USD",
        expected_value="1",
        maximum_loss="1",
        reason="test",
        source_evidence=(),
        authority_category="external_spend",
        mode=EconomicMode.SIMULATED,
    )

    with pytest.raises(Exception):
        envelope.amount = Decimal("2")


def test_economic_state_round_trip_preserves_mode_balances_and_experiments():
    state = EconomicState(
        mode=EconomicMode.SANDBOX,
        balances={
            TreasuryBucket.OPERATIONS: Decimal("100.00"),
            TreasuryBucket.GROWTH: Decimal("250.50"),
            TreasuryBucket.EXPERIMENTS: Decimal("25.25"),
        },
        experiments={
            "exp-1": ExperimentState(
                experiment_id="exp-1",
                strategy_id="service-sales",
                status=ExperimentStatus.RUNNING,
                reserved_budget=Decimal("10.00"),
                realized_revenue=Decimal("0"),
                realized_cost=Decimal("3.00"),
            )
        },
    )

    restored = EconomicState.from_dict(state.to_dict())

    assert restored == state
    assert restored.mode is EconomicMode.SANDBOX
    assert set(restored.balances) == {
        TreasuryBucket.OPERATIONS,
        TreasuryBucket.GROWTH,
        TreasuryBucket.EXPERIMENTS,
    }


def test_state_rejects_unknown_mode_instead_of_promoting_to_live():
    payload = EconomicState(mode=EconomicMode.SIMULATED).to_dict()
    payload["mode"] = "auto"

    with pytest.raises(ValueError):
        EconomicState.from_dict(payload)
