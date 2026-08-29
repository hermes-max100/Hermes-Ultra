from hermes_ultra.economic.ledger import EconomicLedger


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
