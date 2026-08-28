from dataclasses import replace
from decimal import Decimal

import pytest

from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.ledger import DuplicateTransactionError, EconomicLedger


def envelope():
    return TransactionEnvelope.new(
        run_id="run-ledger-1",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="prospect-1",
        amount="10.00",
        currency="USD",
        expected_value="50.00",
        maximum_loss="10.00",
        reason="lead experiment",
        source_evidence=("lead:1",),
        authority_category="external_spend",
        mode=EconomicMode.SIMULATED,
    )


def test_ledger_persists_transaction_and_events_across_reopen(tmp_path):
    path = tmp_path / "economic.sqlite3"
    tx = envelope()

    with EconomicLedger(path) as ledger:
        ledger.record_transaction(tx, metadata={"source": "test"})
        ledger.record_outcome(
            tx.transaction_id,
            status="success",
            amount=tx.amount,
            currency=tx.currency,
            metadata={"provider": "simulated-wallet"},
        )
        ledger.record_revenue(
            run_id=tx.run_id,
            strategy_id=tx.strategy_id,
            bucket=TreasuryBucket.GROWTH,
            amount=Decimal("125.00"),
            currency="USD",
            metadata={"invoice": "mock-invoice-1"},
        )

    with EconomicLedger(path) as reopened:
        stored = reopened.find_transaction(tx.transaction_id)
        entries = reopened.entries()

    assert stored is not None
    assert stored["run_id"] == "run-ledger-1"
    assert stored["strategy_id"] == "service-sales"
    assert [entry.kind for entry in entries] == ["outcome", "revenue"]
    assert entries[1].amount == Decimal("125.00")
    assert entries[1].run_id == tx.run_id
    assert entries[1].strategy_id == tx.strategy_id


def test_ledger_redacts_secret_metadata_before_persistence(tmp_path):
    path = tmp_path / "economic.sqlite3"
    tx = envelope()
    secret = "sensitive-value-12345"

    with EconomicLedger(path) as ledger:
        ledger.record_transaction(
            tx,
            metadata={"api_key": secret, "nested": {"authorization": secret}, "safe": "visible"},
        )
        stored = ledger.find_transaction(tx.transaction_id)

    assert stored is not None
    assert stored["metadata"]["api_key"] == "[REDACTED]"
    assert stored["metadata"]["nested"]["authorization"] == "[REDACTED]"
    assert stored["metadata"]["safe"] == "visible"
    assert secret not in path.read_bytes().decode("latin1", errors="ignore")


def test_ledger_rejects_duplicate_transaction_and_idempotency_identity(tmp_path):
    path = tmp_path / "economic.sqlite3"
    tx = envelope()
    collision = replace(tx, transaction_id="different-transaction")

    with EconomicLedger(path) as ledger:
        ledger.record_transaction(tx)
        with pytest.raises(DuplicateTransactionError):
            ledger.record_transaction(tx)
        with pytest.raises(DuplicateTransactionError):
            ledger.record_transaction(collision)


def test_outcome_requires_known_transaction(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        with pytest.raises(KeyError):
            ledger.record_outcome(
                "missing",
                status="success",
                amount=Decimal("1"),
                currency="USD",
            )
