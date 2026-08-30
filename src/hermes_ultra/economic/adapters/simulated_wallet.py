from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from ..contracts import EconomicMode, TransactionEnvelope, TreasuryBucket, as_decimal
from . import AdapterResult


class SimulatedWalletAdapter:
    """Side-effect-free wallet model for economic acceptance testing."""

    def __init__(
        self,
        balances: Mapping[TreasuryBucket, Decimal | int | str] | None = None,
    ) -> None:
        self._balances = {bucket: Decimal("0") for bucket in TreasuryBucket}
        for bucket, amount in (balances or {}).items():
            self._balances[TreasuryBucket(bucket)] = as_decimal(amount)
        self._results: dict[str, tuple[str, AdapterResult]] = {}

    def balance(self, bucket: TreasuryBucket) -> Decimal:
        return self._balances[TreasuryBucket(bucket)]

    def transfer(self, envelope: TransactionEnvelope) -> AdapterResult:
        prior = self._results.get(envelope.idempotency_key)
        if prior is not None:
            transaction_id, result = prior
            if transaction_id == envelope.transaction_id:
                return result
            return AdapterResult(
                ok=False,
                external_id=None,
                amount=envelope.amount,
                currency=envelope.currency,
                status="duplicate_identity",
            )

        if envelope.mode is not EconomicMode.SIMULATED:
            result = AdapterResult(
                ok=False,
                external_id=None,
                amount=envelope.amount,
                currency=envelope.currency,
                status="mode_blocked",
            )
            self._results[envelope.idempotency_key] = (envelope.transaction_id, result)
            return result

        available = self.balance(envelope.bucket)
        if available < envelope.amount:
            result = AdapterResult(
                ok=False,
                external_id=None,
                amount=envelope.amount,
                currency=envelope.currency,
                status="insufficient_funds",
                metadata={"available": str(available)},
            )
            self._results[envelope.idempotency_key] = (envelope.transaction_id, result)
            return result

        self._balances[envelope.bucket] = available - envelope.amount
        result = AdapterResult(
            ok=True,
            external_id=f"sim_{envelope.transaction_id}",
            amount=envelope.amount,
            currency=envelope.currency,
            status="executed",
            metadata={"bucket": envelope.bucket.value},
        )
        self._results[envelope.idempotency_key] = (envelope.transaction_id, result)
        return result
