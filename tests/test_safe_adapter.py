import inspect
from decimal import Decimal

import pytest

from hermes_ultra.economic.adapters.safe import SafeAdapter
from hermes_ultra.economic.authority import AuthorityDecision, AuthorityPolicy, FinancialAuthority
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket

AUTHORITY_SECRET = b"safe-test-authority-key-32-bytes!!!!!"
RECIPIENT = "0x0000000000000000000000000000000000000001"


class FakeTransport:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {"safeTxHash": "0xsafehash", "status": "proposed"}

    def __call__(self, *, method, url, headers, body):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": bytes(body)}
        )
        return self.response


def envelope(*, mode=EconomicMode.SANDBOX):
    return TransactionEnvelope.new(
        run_id="run-safe",
        strategy_id="service-sales",
        bucket=TreasuryBucket.GROWTH,
        counterparty=RECIPIENT,
        amount=Decimal("1.00"),
        currency="ETH",
        expected_value=Decimal("5.00"),
        maximum_loss=Decimal("1.00"),
        reason="propose governed Safe transaction",
        source_evidence=("experiment:safe-1",),
        authority_category="financial_transfer",
        mode=mode,
    )


def make_authority():
    return FinancialAuthority(
        AuthorityPolicy(
            policy_revision="finance-v1",
            registered_live_categories=frozenset({"financial_transfer"}),
            max_transaction_amount=Decimal("1000"),
            bucket_limits={TreasuryBucket.GROWTH: Decimal("1000")},
            simulated_auto_limit=Decimal("1000"),
            sandbox_auto_limit=Decimal("1000"),
        ),
        authority_secret=AUTHORITY_SECRET,
    )


def tx_data(*, to=RECIPIENT, value="1000000000000000000", data="0x"):
    return {
        "to": to,
        "value": value,
        "data": data,
        "operation": 0,
        "safeTxGas": "0",
        "baseGas": "0",
        "gasPrice": "0",
        "gasToken": "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        "nonce": "10",
    }


def adapter(transport):
    return SafeAdapter(
        api_key="safe-provider-secret",
        service_url="https://api.safe.global/tx-service/base",
        authority=make_authority(),
        transport=transport,
    )


def test_safe_adapter_exposes_no_private_key_seed_or_mnemonic_interface():
    constructor = str(inspect.signature(SafeAdapter)).lower()
    proposal = str(inspect.signature(SafeAdapter.propose_transaction)).lower()
    for forbidden in ("private_key", "seed", "mnemonic", "recovery_phrase"):
        assert forbidden not in constructor
        assert forbidden not in proposal


def test_safe_adapter_requires_attested_authority_and_presigned_fields():
    transport = FakeTransport()
    authority = make_authority()
    guarded = SafeAdapter(
        api_key="safe-provider-secret",
        service_url="https://api.safe.global/tx-service/base",
        authority=authority,
        transport=transport,
    )
    tx = envelope()
    forged = AuthorityDecision(True, False, tx.authority_category, "allowed", "finance-v1")

    with pytest.raises(PermissionError, match="attestation"):
        guarded.propose_transaction(tx, forged, safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data())
    with pytest.raises(TypeError):
        guarded.propose_transaction(tx, "approved by model", safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data())
    with pytest.raises(ValueError, match="signature"):
        guarded.propose_transaction(tx, authority.evaluate(tx), safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="", transaction_data=tx_data())
    assert transport.calls == []


def test_safe_adapter_posts_presigned_native_transfer_to_v2_endpoint_without_signing():
    transport = FakeTransport()
    api_key = "safe-provider-secret-never-return"
    authority = make_authority()
    guarded = SafeAdapter(
        api_key=api_key,
        service_url="https://api.safe.global/tx-service/base",
        authority=authority,
        transport=transport,
    )
    tx = envelope()
    result = guarded.propose_transaction(
        tx,
        authority.evaluate(tx),
        safe_address="0x5298a93734c3d979ef1f23f78ebb871879a21f22",
        safe_tx_hash="0xsafehash",
        sender_address="0xa6d3DEBAAB2B8093e69109f23A75501F864F74e2",
        sender_signature="0xsigned",
        transaction_data=tx_data(),
    )

    assert result.ok is True
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v2/safes/0x5298a93734c3d979ef1f23f78ebb871879a21f22/multisig-transactions/")
    assert call["headers"]["Authorization"] == f"Bearer {api_key}"
    assert b'"value":"1000000000000000000"' in call["body"]
    assert api_key not in repr(guarded)
    assert api_key not in repr(result)


def test_safe_adapter_fails_closed_on_payload_not_bound_to_envelope():
    transport = FakeTransport()
    authority = make_authority()
    guarded = SafeAdapter(api_key="safe-provider-secret", service_url="https://api.safe.global/tx-service/base", authority=authority, transport=transport)
    tx = envelope()
    decision = authority.evaluate(tx)

    with pytest.raises(ValueError, match="recipient"):
        guarded.propose_transaction(tx, decision, safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data(to="0x0000000000000000000000000000000000000002"))
    with pytest.raises(ValueError, match="value"):
        guarded.propose_transaction(tx, decision, safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data(value="2000000000000000000"))
    with pytest.raises(ValueError, match="contract-call"):
        guarded.propose_transaction(tx, decision, safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data(data="0x1234"))
    assert transport.calls == []


def test_safe_adapter_blocks_simulated_mode():
    transport = FakeTransport()
    authority = make_authority()
    guarded = SafeAdapter(api_key="safe-provider-secret", service_url="https://api.safe.global/tx-service/base", authority=authority, transport=transport)
    simulated = envelope(mode=EconomicMode.SIMULATED)
    with pytest.raises(PermissionError, match="mode"):
        guarded.propose_transaction(simulated, authority.evaluate(simulated), safe_address="0xsafe", safe_tx_hash="0xsafehash", sender_address="0xsender", sender_signature="0xsigned", transaction_data=tx_data())
    assert transport.calls == []
