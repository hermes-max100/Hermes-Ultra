from decimal import Decimal

import pytest

from hermes_ultra.economic.authority import AuthorityDecision
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket
from hermes_ultra.economic.adapters.stripe import StripeAdapter


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


def allowed(tx):
    return AuthorityDecision(
        allowed=True,
        authorization_required=False,
        category=tx.authority_category,
        reason="allowed",
        policy_revision="finance-v1",
    )


def denied(tx):
    return AuthorityDecision(
        allowed=False,
        authorization_required=True,
        category=tx.authority_category,
        reason="grant_required",
        policy_revision="finance-v1",
    )


def test_stripe_adapter_never_calls_transport_without_allowed_typed_authority():
    transport = FakeTransport()
    adapter = StripeAdapter(api_key="test-provider-secret", transport=transport)
    tx = envelope()

    with pytest.raises(PermissionError):
        adapter.create_payment_intent(
            tx,
            denied(tx),
            amount_minor=4999,
            currency="usd",
        )
    with pytest.raises(TypeError):
        adapter.create_payment_intent(
            tx,
            "approved by model",
            amount_minor=4999,
            currency="usd",
        )

    assert transport.calls == []


def test_stripe_adapter_requires_authority_category_match_and_non_simulated_mode():
    transport = FakeTransport()
    adapter = StripeAdapter(api_key="test-provider-secret", transport=transport)
    tx = envelope()
    wrong = AuthorityDecision(True, False, "external_spend", "allowed", "finance-v1")

    with pytest.raises(PermissionError, match="category"):
        adapter.create_payment_intent(tx, wrong, amount_minor=4999, currency="usd")

    simulated = envelope(mode=EconomicMode.SIMULATED)
    with pytest.raises(PermissionError, match="mode"):
        adapter.create_payment_intent(
            simulated,
            allowed(simulated),
            amount_minor=4999,
            currency="usd",
        )

    assert transport.calls == []


def test_stripe_payment_intent_uses_exact_envelope_idempotency_key_and_v1_endpoint():
    transport = FakeTransport()
    provider_secret = "test-provider-secret-never-return"
    adapter = StripeAdapter(api_key=provider_secret, transport=transport)
    tx = envelope()

    result = adapter.create_payment_intent(
        tx,
        allowed(tx),
        amount_minor=4999,
        currency="usd",
        metadata={"run_id": tx.run_id, "strategy_id": tx.strategy_id},
    )

    assert result.ok is True
    assert result.external_id == "pi_test_123"
    assert result.status == "requires_payment_method"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.stripe.com/v1/payment_intents"
    assert call["headers"]["Idempotency-Key"] == tx.idempotency_key
    assert call["headers"]["Authorization"] == f"Bearer {provider_secret}"
    assert b"amount=4999" in call["body"]
    assert b"currency=usd" in call["body"]
    assert provider_secret not in repr(result)
    assert provider_secret not in repr(adapter)


def test_stripe_transport_failure_returns_redacted_adapter_result():
    provider_secret = "test-provider-secret-never-return"

    def broken_transport(**kwargs):
        raise RuntimeError(f"upstream failed with key {provider_secret}")

    adapter = StripeAdapter(api_key=provider_secret, transport=broken_transport)
    tx = envelope()
    result = adapter.create_payment_intent(
        tx,
        allowed(tx),
        amount_minor=4999,
        currency="usd",
    )

    assert result.ok is False
    assert result.status == "transport_error"
    assert provider_secret not in repr(result)
    assert result.metadata["error"] == "upstream request failed"
