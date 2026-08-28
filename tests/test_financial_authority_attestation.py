from decimal import Decimal

from hermes_ultra.economic.authority import (
    AuthorityDecision,
    AuthorityPolicy,
    AuthorizationGrant,
    FinancialAuthority,
)
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket

OWNER_BOUNDARY_KEY = b"test-owner-boundary-key-32-bytes!!"
WRONG_KEY = b"wrong-owner-boundary-key-32-bytes!"


def policy():
    return AuthorityPolicy(
        policy_revision="finance-v2",
        registered_live_categories=frozenset({"financial_transfer"}),
        max_transaction_amount=Decimal("1000"),
        bucket_limits={TreasuryBucket.OPERATIONS: Decimal("1000")},
        simulated_auto_limit=Decimal("1000"),
        sandbox_auto_limit=Decimal("1000"),
    )


def transaction(mode=EconomicMode.LIVE):
    return TransactionEnvelope.new(
        run_id="run-attested",
        strategy_id="service-sales",
        bucket=TreasuryBucket.OPERATIONS,
        counterparty="provider",
        amount="49.99",
        currency="USD",
        expected_value="499.00",
        maximum_loss="49.99",
        reason="attested payment",
        source_evidence=("experiment:attested",),
        authority_category="financial_transfer",
        mode=mode,
    )


def test_wrong_key_cannot_mint_a_live_authorization_grant():
    authority = FinancialAuthority(policy(), authority_secret=OWNER_BOUNDARY_KEY)
    tx = transaction()
    forged = AuthorizationGrant.issue(
        tx,
        policy_revision="finance-v2",
        signing_secret=WRONG_KEY,
    )

    decision = authority.evaluate(tx, grant=forged)

    assert decision.allowed is False
    assert decision.authorization_required is True
    assert decision.reason == "grant_signature_invalid"


def test_correct_owner_boundary_key_produces_attested_live_decision():
    authority = FinancialAuthority(policy(), authority_secret=OWNER_BOUNDARY_KEY)
    tx = transaction()
    grant = AuthorizationGrant.issue(
        tx,
        policy_revision="finance-v2",
        signing_secret=OWNER_BOUNDARY_KEY,
    )

    decision = authority.evaluate(tx, grant=grant)

    assert decision.allowed is True
    assert authority.validate_decision(tx, decision) is True
    assert decision.attestation
    assert OWNER_BOUNDARY_KEY.decode() not in repr(decision)


def test_fabricated_allowed_decision_is_not_valid_authority():
    authority = FinancialAuthority(policy(), authority_secret=OWNER_BOUNDARY_KEY)
    tx = transaction(mode=EconomicMode.SANDBOX)
    forged = AuthorityDecision(
        allowed=True,
        authorization_required=False,
        category=tx.authority_category,
        reason="allowed",
        policy_revision="finance-v2",
        transaction_id=tx.transaction_id,
        mode=tx.mode,
        attestation="forged",
    )

    assert authority.validate_decision(tx, forged) is False


def test_decision_is_bound_to_exact_transaction_and_mode():
    authority = FinancialAuthority(policy(), authority_secret=OWNER_BOUNDARY_KEY)
    sandbox = transaction(mode=EconomicMode.SANDBOX)
    decision = authority.evaluate(sandbox)
    other = transaction(mode=EconomicMode.SANDBOX)

    assert decision.allowed is True
    assert authority.validate_decision(sandbox, decision) is True
    assert authority.validate_decision(other, decision) is False
