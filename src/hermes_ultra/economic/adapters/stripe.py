from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..authority import AuthorityDecision, FinancialAuthority
from ..contracts import EconomicMode, TransactionEnvelope
from . import AdapterResult

Transport = Callable[..., Mapping[str, Any]]

_CURRENCY_MINOR_UNITS = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CAD": 2,
    "AUD": 2,
    "NZD": 2,
    "JPY": 0,
    "KRW": 0,
    "BHD": 3,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
}


class StripeAdapter:
    """Guarded Stripe API v1 adapter.

    The adapter owns no policy authority. It requires a FinancialAuthority
    validator and an attested allowed decision bound to the exact transaction.
    Provider credentials are used only in request headers and are never returned
    in adapter metadata.
    """

    def __init__(
        self,
        *,
        api_key: str,
        authority: FinancialAuthority,
        transport: Transport | None = None,
        base_url: str = "https://api.stripe.com/v1",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not isinstance(authority, FinancialAuthority):
            raise TypeError("authority must be a FinancialAuthority")
        self._api_key = api_key
        self._authority = authority
        self._transport = transport or self._default_transport
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"StripeAdapter(base_url={self._base_url!r}, "
            f"timeout_seconds={self._timeout_seconds!r}, api_key='[REDACTED]')"
        )

    def _validate_authority(
        self,
        envelope: TransactionEnvelope,
        authority: AuthorityDecision | object,
    ) -> AuthorityDecision:
        if not isinstance(authority, AuthorityDecision):
            raise TypeError("authority must be an AuthorityDecision")
        if not self._authority.validate_decision(envelope, authority):
            raise PermissionError("invalid financial authority attestation")
        if not authority.allowed:
            raise PermissionError(f"financial authority denied: {authority.reason}")
        if envelope.mode is EconomicMode.SIMULATED:
            raise PermissionError("Stripe adapter is unavailable in simulated mode")
        return authority

    @staticmethod
    def _expected_amount_minor(envelope: TransactionEnvelope, currency: str) -> int:
        normalized = currency.strip().upper()
        if normalized != envelope.currency.upper():
            raise ValueError("currency does not match authorized transaction envelope")
        exponent = _CURRENCY_MINOR_UNITS.get(normalized)
        if exponent is None:
            raise ValueError(f"unsupported currency minor-unit mapping: {normalized}")
        scaled = envelope.amount * (Decimal(10) ** exponent)
        if scaled != scaled.to_integral_value():
            raise ValueError("authorized amount has excess precision for currency")
        expected = int(scaled)
        if expected <= 0:
            raise ValueError("authorized amount must be positive")
        return expected

    @staticmethod
    def _flatten_form(
        *,
        amount_minor: int,
        currency: str,
        metadata: Mapping[str, object] | None,
    ) -> bytes:
        normalized_currency = currency.strip().lower()
        fields: list[tuple[str, str]] = [
            ("amount", str(amount_minor)),
            ("currency", normalized_currency),
            ("automatic_payment_methods[enabled]", "true"),
        ]
        for key, value in sorted((metadata or {}).items()):
            fields.append((f"metadata[{key}]", str(value)))
        return urlencode(fields).encode("utf-8")

    def create_payment_intent(
        self,
        envelope: TransactionEnvelope,
        authority: AuthorityDecision | object,
        *,
        amount_minor: int,
        currency: str,
        metadata: Mapping[str, object] | None = None,
    ) -> AdapterResult:
        self._validate_authority(envelope, authority)
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
            raise ValueError("amount_minor must be an integer")
        expected_minor = self._expected_amount_minor(envelope, currency)
        if amount_minor != expected_minor:
            raise ValueError("amount_minor does not match authorized transaction envelope")
        body = self._flatten_form(
            amount_minor=expected_minor,
            currency=currency,
            metadata=metadata,
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": envelope.idempotency_key,
        }
        try:
            response = self._transport(
                method="POST",
                url=f"{self._base_url}/payment_intents",
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
                metadata={"provider": "stripe", "error": "upstream request failed"},
            )

        external_id = response.get("id") if isinstance(response, Mapping) else None
        status = response.get("status") if isinstance(response, Mapping) else None
        if not isinstance(external_id, str) or not external_id:
            return AdapterResult(
                ok=False,
                external_id=None,
                amount=envelope.amount,
                currency=envelope.currency,
                status="invalid_response",
                metadata={"provider": "stripe"},
            )
        return AdapterResult(
            ok=True,
            external_id=external_id,
            amount=envelope.amount,
            currency=envelope.currency,
            status=str(status or "created"),
            metadata={"provider": "stripe", "object": "payment_intent"},
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
            raise ValueError("Stripe response must be a JSON object")
        return decoded
