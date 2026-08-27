from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .authority import AuthorityDecision
from .contracts import TransactionEnvelope, TreasuryBucket, as_decimal
from .state import EconomicState, TreasuryReservationState


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class Reservation:
    transaction_id: str
    bucket: TreasuryBucket
    amount: Decimal
    status: ReservationStatus


class TreasuryManager:
    """State-backed reservation accounting with retry/restart idempotency."""

    def __init__(self, state: EconomicState) -> None:
        self.state = state

    @staticmethod
    def _reservation_from_state(value: TreasuryReservationState) -> Reservation:
        return Reservation(
            transaction_id=value.transaction_id,
            bucket=value.bucket,
            amount=value.amount,
            status=ReservationStatus(value.status),
        )

    def available(self, bucket: TreasuryBucket) -> Decimal:
        bucket = TreasuryBucket(bucket)
        reserved = sum(
            (
                reservation.amount
                for reservation in self.state.reservations.values()
                if reservation.bucket is bucket
                and reservation.status == ReservationStatus.RESERVED.value
            ),
            Decimal("0"),
        )
        return self.state.balances[bucket] - reserved

    def reserve(
        self,
        envelope: TransactionEnvelope,
        decision: AuthorityDecision,
    ) -> Reservation:
        if not decision.allowed:
            raise PermissionError(f"financial authority denied: {decision.reason}")
        if envelope.mode is not self.state.mode:
            raise PermissionError("transaction mode does not match treasury mode")

        existing = self.state.reservations.get(envelope.transaction_id)
        if existing is not None:
            if existing.bucket is not envelope.bucket or existing.amount != envelope.amount:
                raise ValueError("transaction reservation identity mismatch")
            return self._reservation_from_state(existing)

        available = self.available(envelope.bucket)
        if envelope.amount > available:
            raise ValueError("insufficient available treasury funds")
        stored = TreasuryReservationState(
            transaction_id=envelope.transaction_id,
            bucket=envelope.bucket,
            amount=envelope.amount,
            status=ReservationStatus.RESERVED.value,
        )
        self.state.reservations[envelope.transaction_id] = stored
        return self._reservation_from_state(stored)

    def commit(self, transaction_id: str) -> Reservation:
        current = self.state.reservations.get(transaction_id)
        if current is None:
            raise KeyError(transaction_id)
        status = ReservationStatus(current.status)
        if status is not ReservationStatus.RESERVED:
            return self._reservation_from_state(current)
        balance = self.state.balances[current.bucket]
        if balance < current.amount:
            raise ValueError("insufficient treasury funds at commit")
        self.state.balances[current.bucket] = balance - current.amount
        committed = TreasuryReservationState(
            transaction_id=current.transaction_id,
            bucket=current.bucket,
            amount=current.amount,
            status=ReservationStatus.COMMITTED.value,
        )
        self.state.reservations[transaction_id] = committed
        return self._reservation_from_state(committed)

    def release(self, transaction_id: str) -> Reservation:
        current = self.state.reservations.get(transaction_id)
        if current is None:
            raise KeyError(transaction_id)
        status = ReservationStatus(current.status)
        if status is not ReservationStatus.RESERVED:
            return self._reservation_from_state(current)
        released = TreasuryReservationState(
            transaction_id=current.transaction_id,
            bucket=current.bucket,
            amount=current.amount,
            status=ReservationStatus.RELEASED.value,
        )
        self.state.reservations[transaction_id] = released
        return self._reservation_from_state(released)

    def credit_revenue(
        self,
        bucket: TreasuryBucket,
        amount: Decimal | int | str,
        *,
        event_key: str,
    ) -> Decimal:
        bucket = TreasuryBucket(bucket)
        value = as_decimal(amount)
        if value < 0:
            raise ValueError("revenue credit must be non-negative")
        prior = self.state.revenue_credit_keys.get(event_key)
        if prior is not None:
            if prior != value:
                raise ValueError("revenue event key amount mismatch")
            return prior
        self.state.balances[bucket] += value
        self.state.revenue_credit_keys[event_key] = value
        return value
