from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from hermes_ultra.economic.authority import AuthorityPolicy, AuthorizationGrant, FinancialAuthority
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket

AUTHORITY_SECRET = b"test-financial-authority-key-32-bytes"


def transaction(*, amount="50.00", mode=EconomicMode.SIMULATED, category="external_spend"):
    return TransactionEnvelope.new(
        run_id="run-auth",
        strategy_id="service-sales",
        bucket=TreasuryBucket.EXPERIMENTS,
        counterparty="vendor",
        amount=amount,
        currency="USD",
        expected_value="250.00",
        maximum_loss=amount,
        reason="revenue experiment",
        source_evidence=("experiment:1",),
        authority_category=category,
        mode=mode,
    )


def policy():
    return AuthorityPolicy(
        policy_revision="finance-v1",
        registered_live_categories=frozenset({"external_spend", "financial_transfer"}),
        max_transaction_amount=Decimal("100.00"),
        bucket_limits={TreasuryBucket.EXPERIMENTS: Decimal("75.00")},
        simulated_auto_limit=Decimal("75.00"),
        sandbox_auto_limit=Decimal("60.00"),
    )


def authority():
    return FinancialAuthority(policy(), authority_secret=AUTHORITY_SECRET)


def test_simulated_and_sandbox_actions_are_autonomous_inside_configured_limits():
    gate = authority()

    simulated = gate.evaluate(transaction(mode=EconomicMode.SIMULATED))
    sandbox = gate.evaluate(transaction(mode=EconomicMode.SANDBOX))

    assert simulated.allowed is True
    assert simulated.authorization_required is False
    assert sandbox.allowed is True
    assert sandbox.authorization_required is False
    assert gate.validate_decision(transaction(mode=EconomicMode.SIMULATED), simulated) is False


def test_live_money_movement_requires_typed_exact_transaction_grant():
    gate = authority()
    tx = transaction(mode=EconomicMode.LIVE)

    missing = gate.evaluate(tx)
    model_text = gate.evaluate(tx, grant="APPROVED external_spend")
    wrong_tx = AuthorizationGrant.issue(
        transaction(mode=EconomicMode.LIVE), policy_revision="finance-v1", signing_secret=AUTHORITY_SECRET
    )
    mismatch = gate.evaluate(tx, grant=wrong_tx)
    valid_grant = AuthorizationGrant.issue(
        tx, policy_revision="finance-v1", signing_secret=AUTHORITY_SECRET
    )
    allowed = gate.evaluate(tx, grant=valid_grant)

    assert missing.allowed is False and missing.authorization_required is True
    assert model_text.allowed is False and model_text.authorization_required is True
    assert mismatch.allowed is False and mismatch.authorization_required is True
    assert allowed.allowed is True
    assert allowed.authorization_required is False
    assert allowed.category == "external_spend"
    assert gate.validate_decision(tx, allowed) is True


def test_live_unregistered_category_cannot_be_self_granted():
    gate = authority()
    tx = transaction(mode=EconomicMode.LIVE, category="trade_securities")
    forged = AuthorizationGrant.issue(
        tx, policy_revision="finance-v1", signing_secret=AUTHORITY_SECRET
    )

    decision = gate.evaluate(tx, grant=forged)

    assert decision.allowed is False
    assert decision.authorization_required is False
    assert decision.reason == "category_not_registered"


def test_expired_transactions_and_policy_limits_fail_closed():
    gate = authority()
    expired = transaction()
    expired = replace(expired, expires_at=expired.created_at - timedelta(seconds=1))
    over_bucket = transaction(amount="80.00")
    over_global = transaction(amount="101.00")

    assert gate.evaluate(expired).reason == "transaction_expired"
    assert gate.evaluate(over_bucket).reason == "bucket_limit_exceeded"
    assert gate.evaluate(over_global).reason == "transaction_limit_exceeded"
