from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable
from uuid import uuid4


class EconomicMode(str, Enum):
    SIMULATED = "SIMULATED"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"


class TreasuryBucket(str, Enum):
    OPERATIONS = "OPERATIONS"
    GROWTH = "GROWTH"
    EXPERIMENTS = "EXPERIMENTS"


class ExperimentStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class TransactionEnvelope:
    transaction_id: str
    run_id: str
    strategy_id: str
    bucket: TreasuryBucket
    counterparty: str
    amount: Decimal
    currency: str
    expected_value: Decimal
    maximum_loss: Decimal
    reason: str
    source_evidence: tuple[str, ...]
    authority_category: str
    idempotency_key: str
    created_at: datetime
    expires_at: datetime
    mode: EconomicMode

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        strategy_id: str,
        bucket: TreasuryBucket,
        counterparty: str,
        amount: Decimal | int | str,
        currency: str,
        expected_value: Decimal | int | str,
        maximum_loss: Decimal | int | str,
        reason: str,
        source_evidence: Iterable[str],
        authority_category: str,
        mode: EconomicMode,
        ttl_seconds: int = 900,
    ) -> "TransactionEnvelope":
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not run_id or not strategy_id:
            raise ValueError("run_id and strategy_id are required")
        if not currency.strip():
            raise ValueError("currency is required")
        amount_value = as_decimal(amount)
        expected = as_decimal(expected_value)
        maximum = as_decimal(maximum_loss)
        if amount_value < 0 or maximum < 0:
            raise ValueError("amount and maximum_loss must be non-negative")
        now = utc_now()
        return cls(
            transaction_id=str(uuid4()),
            run_id=run_id,
            strategy_id=strategy_id,
            bucket=bucket,
            counterparty=counterparty,
            amount=amount_value,
            currency=currency.upper(),
            expected_value=expected,
            maximum_loss=maximum,
            reason=reason,
            source_evidence=tuple(source_evidence),
            authority_category=authority_category,
            idempotency_key=str(uuid4()),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            mode=mode,
        )

    @property
    def expired(self) -> bool:
        return utc_now() >= self.expires_at

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "bucket": self.bucket.value,
            "counterparty": self.counterparty,
            "amount": str(self.amount),
            "currency": self.currency,
            "expected_value": str(self.expected_value),
            "maximum_loss": str(self.maximum_loss),
            "reason": self.reason,
            "source_evidence": list(self.source_evidence),
            "authority_category": self.authority_category,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "mode": self.mode.value,
        }
