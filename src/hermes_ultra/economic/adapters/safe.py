from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

from ..authority import AuthorityDecision
from ..contracts import EconomicMode, TransactionEnvelope
from . import AdapterResult

Transport = Callable[..., Mapping[str, Any]]

_REQUIRED_TRANSACTION_FIELDS = (
    "to",
    "value",
    "data",
    "operation",
    "safeTxGas",
    "baseGas",
    "gasPrice",
    "gasToken",
    "refundReceiver",
    "nonce",
)


class SafeAdapter:
    """Safe Transaction Service proposal adapter for already-signed transactions.

    This boundary deliberately has no signing/private-key interface. Hermes may
    submit a proposal only after another trusted boundary has produced the Safe
    transaction hash and sender signature and financial authority is allowed.
    """

    def __init__(
        self,
        *,
        api_key: str,
        service_url: str,
        transport: Transport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not service_url.strip().lower().startswith("https://"):
            raise ValueError("service_url must use https")
        self._api_key = api_key
        self._service_url = service_url.rstrip("/")
        self._transport = transport or self._default_transport
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"SafeAdapter(service_url={self._service_url!r}, "
            f"timeout_seconds={self._timeout_seconds!r}, api_key='[REDACTED]')"
        )

    @staticmethod
    def _validate_authority(
        envelope: TransactionEnvelope,
        authority: AuthorityDecision | object,
    ) -> AuthorityDecision:
        if not isinstance(authority, AuthorityDecision):
            raise TypeError("authority must be an AuthorityDecision")
        if not authority.allowed:
            raise PermissionError(f"financial authority denied: {authority.reason}")
        if authority.category != envelope.authority_category:
            raise PermissionError("authority category does not match transaction category")
        if envelope.mode is EconomicMode.SIMULATED:
            raise PermissionError("Safe adapter is unavailable in simulated mode")
        return authority

    @staticmethod
    def _validate_proposal_fields(
        *,
        safe_address: str,
        safe_tx_hash: str,
        sender_address: str,
        sender_signature: str,
        transaction_data: Mapping[str, object],
    ) -> None:
        if not safe_address.strip():
            raise ValueError("safe_address is required")
        if not safe_tx_hash.strip():
            raise ValueError("safe_tx_hash is required")
        if not sender_address.strip():
            raise ValueError("sender_address is required")
        if not sender_signature.strip():
            raise ValueError("sender_signature is required")
        missing = [field for field in _REQUIRED_TRANSACTION_FIELDS if field not in transaction_data]
        if missing:
            raise ValueError(f"transaction_data missing required fields: {', '.join(missing)}")

    def propose_transaction(
        self,
        envelope: TransactionEnvelope,
        authority: AuthorityDecision | object,
        *,
        safe_address: str,
        safe_tx_hash: str,
        sender_address: str,
        sender_signature: str,
        transaction_data: Mapping[str, object],
    ) -> AdapterResult:
        self._validate_authority(envelope, authority)
        self._validate_proposal_fields(
            safe_address=safe_address,
            safe_tx_hash=safe_tx_hash,
            sender_address=sender_address,
            sender_signature=sender_signature,
            transaction_data=transaction_data,
        )

        payload = dict(transaction_data)
        payload.update(
            {
                "safeTxHash": safe_tx_hash,
                "sender": sender_address,
                "signature": sender_signature,
            }
        )
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._transport(
                method="POST",
                url=(
                    f"{self._service_url}/api/v2/safes/"
                    f"{safe_address}/multisig-transactions/"
                ),
                headers=headers,
                body=body,
            )
        except Exception:
            return AdapterResult(
                ok=False,
                external_id=None,
                amount=envelope.amount,
                currency=envelope.currency,
                status="transport_error",
                metadata={"provider": "safe", "error": "upstream request failed"},
            )

        response_hash = response.get("safeTxHash") if isinstance(response, Mapping) else None
        external_id = response_hash if isinstance(response_hash, str) and response_hash else safe_tx_hash
        response_status = response.get("status") if isinstance(response, Mapping) else None
        return AdapterResult(
            ok=True,
            external_id=external_id,
            amount=envelope.amount,
            currency=envelope.currency,
            status=str(response_status or "proposed"),
            metadata={"provider": "safe", "operation": "proposal"},
        )

    def _default_transport(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> Mapping[str, Any]:
        request = Request(url=url, data=body, headers=dict(headers), method=method)
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = response.read()
        if not payload:
            return {}
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise ValueError("Safe response must be a JSON object")
        return decoded
