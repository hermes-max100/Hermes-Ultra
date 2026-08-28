from __future__ import annotations

import hashlib
from decimal import Decimal

from ..contracts import EconomicMode, as_decimal
from . import AdapterResult


def _stable_id(prefix: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}"


class MockStripeAdapter:
    """Deterministic, zero-network Stripe simulator for Revenue OS tests."""

    def __init__(self) -> None:
        self._payments: dict[str, AdapterResult] = {}
        self._revenues: dict[str, AdapterResult] = {}
        self._total_revenue = Decimal("0")

    @property
    def total_revenue(self) -> Decimal:
        return self._total_revenue

    def create_payment(
        self,
        *,
        run_id: str,
        strategy_id: str,
        amount: Decimal | int | str,
        currency: str,
        idempotency_key: str,
        mode: EconomicMode,
    ) -> AdapterResult:
        prior = self._payments.get(idempotency_key)
        if prior is not None:
            return prior
        value = as_decimal(amount)
        if mode is not EconomicMode.SIMULATED:
            result = AdapterResult(False, None, value, currency.upper(), "mode_blocked")
            self._payments[idempotency_key] = result
            return result
        result = AdapterResult(
            ok=True,
            external_id=_stable_id("mock_pi_", idempotency_key),
            amount=value,
            currency=currency.upper(),
            status="created",
            metadata={"run_id": run_id, "strategy_id": strategy_id},
        )
        self._payments[idempotency_key] = result
        return result

    def record_revenue(
        self,
        *,
        run_id: str,
        strategy_id: str,
        amount: Decimal | int | str,
        currency: str,
        idempotency_key: str,
        mode: EconomicMode,
    ) -> AdapterResult:
        prior = self._revenues.get(idempotency_key)
        if prior is not None:
            return prior
        value = as_decimal(amount)
        if mode is not EconomicMode.SIMULATED:
            result = AdapterResult(False, None, value, currency.upper(), "mode_blocked")
            self._revenues[idempotency_key] = result
            return result
        result = AdapterResult(
            ok=True,
            external_id=_stable_id("mock_rev_", idempotency_key),
            amount=value,
            currency=currency.upper(),
            status="received",
            metadata={"run_id": run_id, "strategy_id": strategy_id},
        )
        self._revenues[idempotency_key] = result
        self._total_revenue += value
        return result
