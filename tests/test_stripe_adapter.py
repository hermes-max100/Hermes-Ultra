from decimal import Decimal

import pytest

from hermes_ultra.economic.authority import AuthorityDecision, AuthorityPolicy, FinancialAuthority
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.adapters.stripe import StripeAdapter

AUTHORITY_SECRET = b"stripe-test-authority-key-32-bytes!!"


class FakeTransport:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "id": "pi_test_123",
            "object": "payment_intent",
            "status": "requires_payment_method",
        }

    def __call__(self, *, method, url, headers, body):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": bytes(body)}
        )
        return self.response


def envelope(*, mode=EconomicMode.SANDBOX):
    return TransactionEnvelope.new(
        run_id="run-stripe",
        strategy_id="service-sales",
        bucket=TreasuryBucket.OPERATIONS,
        counterparty="stripe-customer",
        amount=Decimal("49.99"),
        currency="USD",
        expected_value=Decimal("499.00"),
        maximum_loss=Decimal("49.99"),
        reason="create payment intent",
        source_evidence=("experiment:sales-1",),
        authority_category="financial_transfer",
        mode=mode,
    )


def make_authority():
    return FinancialAuthority(
        AuthorityPolicy(
            policy_revision="finance-v1",
            registered_live_categories=frozenset({"financial_transfer"}),
            max_transaction_amount=Decimal("1000"),
            bucket_limits={TreasuryBucket.OPERATIONS: Decimal("1000")},
            simulated_auto_limit=Decimal("1000"),
            sandbox_auto_limit=Decimal("1000"),
        ),
        authority_secret=AUTHORITY_SECRET,
    )


def test_stripe_adapter_never_calls_transport_without_attested_allowed_authority():
    transport = FakeTransport()
    authority = make_authority()
    adapter = StripeAdapter(api_key="test-provider-secret", authority=authority, transport=transport)
    tx = envelope()
    denied = AuthorityDecision(False, True, tx.authority_category, "grant_required", "finance-v1")

    with pytest.raises(PermissionError):
        adapter.create_payment_intent(tx, denied, amount_minor=4999, currency="usd")
    with pytest.raises(TypeError):
        adapter.create_payment_intent(tx, "approved by model", amount_minor=4999, currency="usd")
    assert transport.calls == []


def test_stripe_adapter_blocks_simulated_mode_and_fabricated_decisions():
    transport = FakeTransport()
    authority = make_authority()
    adapter = StripeAdapter(api_key="test-provider-secret", authority=authority, transport=transport)
    simulated = envelope(mode=EconomicMode.SIMULATED)
    decision = authority.evaluate(simulated)
    with pytest.raises(PermissionError, match="mode"):
        adapter.create_payment_intent(simulated, decision, amount_minor=4999, currency="usd")

    tx = envelope()
    forged = AuthorityDecision(True, False, tx.authority_category, "allowed", "finance-v1")
    with pytest.raises(PermissionError, match="attestation"):
        adapter.create_payment_intent(tx, forged, amount_minor=4999, currency="usd")
    assert transport.calls == []


def test_stripe_payment_intent_uses_exact_authorized_amount_idempotency_and_v1_endpoint():
    transport = FakeTransport()
    provider_secret = "test-provider-secret-never-return"
    authority = make_authority()
    adapter = StripeAdapter(api_key=provider_secret, authority=authority, transport=transport)
    tx = envelope()
    decision = authority.evaluate(tx)

    result = adapter.create_payment_intent(
        tx,
        decision,
        amount_minor=4999,
        currency="usd",
        metadata={"run_id": tx.run_id, "strategy_id": tx.strategy_id},
    )

    assert result.ok is True
    assert result.external_id == "pi_test_123"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["headers"]["Idempotency-Key"] == tx.idempotency_key
    assert b"amount=4999" in call["body"]
    assert provider_secret not in repr(result)
    assert provider_secret not in repr(adapter)


def test_stripe_rejects_amount_or_currency_not_bound_to_authorized_envelope():
    transport = FakeTransport()
    authority = make_authority()
    adapter = StripeAdapter(api_key="test-provider-secret", authority=authority, transport=transport)
    tx = envelope()
    decision = authority.evaluate(tx)

    with pytest.raises(ValueError, match="amount_minor"):
        adapter.create_payment_intent(tx, decision, amount_minor=9999, currency="usd")
    with pytest.raises(ValueError, match="currency"):
        adapter.create_payment_intent(tx, decision, amount_minor=4999, currency="eur")
    assert transport.calls == []


def test_stripe_transport_failure_returns_redacted_adapter_result():
    provider_secret = "test-provider-secret-never-return"

    def broken_transport(**kwargs):
        raise RuntimeError(f"upstream failed with key {provider_secret}")

    authority = make_authority()
    adapter = StripeAdapter(api_key=provider_secret, authority=authority, transport=broken_transport)
    tx = envelope()
    result = adapter.create_payment_intent(tx, authority.evaluate(tx), amount_minor=4999, currency="usd")

    assert result.ok is False
    assert result.status == "transport_error"
    assert provider_secret not in repr(result)
    assert result.metadata["error"] == "upstream request failed"
