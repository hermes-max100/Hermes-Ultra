import inspect
from decimal import Decimal

import pytest

from hermes_ultra.economic.adapters.safe import SafeAdapter
from hermes_ultra.economic.authority import AuthorityDecision
from hermes_ultra.economic.contracts import EconomicMode, TransactionEnvelope, TreasuryBucket


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
        counterparty="0xrecipient",
        amount=Decimal("1.00"),
        currency="USDC",
        expected_value=Decimal("5.00"),
        maximum_loss=Decimal("1.00"),
        reason="propose governed Safe transaction",
        source_evidence=("experiment:safe-1",),
        authority_category="financial_transfer",
        mode=mode,
    )


def allowed(tx):
    return AuthorityDecision(True, False, tx.authority_category, "allowed", "finance-v1")


def tx_data():
    return {
        "to": "0x0000000000000000000000000000000000000001",
        "value": "0",
        "data": "0x",
        "operation": 0,
        "safeTxGas": "0",
        "baseGas": "0",
        "gasPrice": "0",
        "gasToken": "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        "nonce": "10",
    }


def test_safe_adapter_exposes_no_private_key_seed_or_mnemonic_interface():
    constructor = str(inspect.signature(SafeAdapter)).lower()
    proposal = str(inspect.signature(SafeAdapter.propose_transaction)).lower()

    for forbidden in ("private_key", "seed", "mnemonic", "recovery_phrase"):
        assert forbidden not in constructor
        assert forbidden not in proposal


def test_safe_adapter_requires_allowed_typed_authority_and_presigned_fields():
    transport = FakeTransport()
    adapter = SafeAdapter(
        api_key="safe-provider-secret",
        service_url="https://api.safe.global/tx-service/base",
        transport=transport,
    )
    tx = envelope()
    denied = AuthorityDecision(False, True, tx.authority_category, "grant_required", "finance-v1")

    with pytest.raises(PermissionError):
        adapter.propose_transaction(
            tx,
            denied,
            safe_address="0xsafe",
            safe_tx_hash="0xsafehash",
            sender_address="0xsender",
            sender_signature="0xsigned",
            transaction_data=tx_data(),
        )
    with pytest.raises(TypeError):
        adapter.propose_transaction(
            tx,
            "approved by model",
            safe_address="0xsafe",
            safe_tx_hash="0xsafehash",
            sender_address="0xsender",
            sender_signature="0xsigned",
            transaction_data=tx_data(),
        )
    with pytest.raises(ValueError, match="signature"):
        adapter.propose_transaction(
            tx,
            allowed(tx),
            safe_address="0xsafe",
            safe_tx_hash="0xsafehash",
            sender_address="0xsender",
            sender_signature="",
            transaction_data=tx_data(),
        )

    assert transport.calls == []


def test_safe_adapter_posts_presigned_proposal_to_current_v2_endpoint_without_signing():
    transport = FakeTransport()
    api_key = "safe-provider-secret-never-return"
    adapter = SafeAdapter(
        api_key=api_key,
        service_url="https://api.safe.global/tx-service/base",
        transport=transport,
    )
    tx = envelope()

    result = adapter.propose_transaction(
        tx,
        allowed(tx),
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
    assert call["url"].endswith(
        "/api/v2/safes/0x5298a93734c3d979ef1f23f78ebb871879a21f22/multisig-transactions/"
    )
    assert call["headers"]["Authorization"] == f"Bearer {api_key}"
    assert b'"safeTxHash":"0xsafehash"' in call["body"]
    assert b'"sender":"0xa6d3DEBAAB2B8093e69109f23A75501F864F74e2"' in call["body"]
    assert b'"signature":"0xsigned"' in call["body"]
    assert b'"nonce":"10"' in call["body"]
    assert api_key not in repr(adapter)
    assert api_key not in repr(result)
    assert "private_key" not in repr(call["body"]).lower()


def test_safe_adapter_blocks_simulated_mode_and_authority_category_mismatch():
    transport = FakeTransport()
    adapter = SafeAdapter(
        api_key="safe-provider-secret",
        service_url="https://api.safe.global/tx-service/base",
        transport=transport,
    )
    simulated = envelope(mode=EconomicMode.SIMULATED)
    with pytest.raises(PermissionError, match="mode"):
        adapter.propose_transaction(
            simulated,
            allowed(simulated),
            safe_address="0xsafe",
            safe_tx_hash="0xsafehash",
            sender_address="0xsender",
            sender_signature="0xsigned",
            transaction_data=tx_data(),
        )

    tx = envelope()
    wrong = AuthorityDecision(True, False, "external_spend", "allowed", "finance-v1")
    with pytest.raises(PermissionError, match="category"):
        adapter.propose_transaction(
            tx,
            wrong,
            safe_address="0xsafe",
            safe_tx_hash="0xsafehash",
            sender_address="0xsender",
            sender_signature="0xsigned",
            transaction_data=tx_data(),
        )

    assert transport.calls == []
