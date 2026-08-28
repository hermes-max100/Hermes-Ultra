from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from ..evidence import redact_secrets
from .contracts import TransactionEnvelope, TreasuryBucket, as_decimal, utc_now


class DuplicateTransactionError(ValueError):
    pass


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: int
    kind: str
    transaction_id: str | None
    run_id: str
    strategy_id: str
    bucket: TreasuryBucket | None
    amount: Decimal
    currency: str
    status: str
    metadata: Mapping[str, object]
    created_at: datetime
    event_key: str | None = None


class EconomicLedger:
    """SQLite-backed economic ledger with redaction-before-persistence semantics."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    transaction_id TEXT,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    bucket TEXT,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_key TEXT,
                    FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id)
                )
                """
            )
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "event_key" not in columns:
                self._conn.execute("ALTER TABLE events ADD COLUMN event_key TEXT")
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_key "
                "ON events(event_key) WHERE event_key IS NOT NULL"
            )

    def __enter__(self) -> "EconomicLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _metadata_json(metadata: Mapping[str, object] | None) -> str:
        safe = redact_secrets(dict(metadata or {}))
        return json.dumps(safe, sort_keys=True, separators=(",", ":"), default=str)

    def record_transaction(
        self,
        envelope: TransactionEnvelope,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO transactions (
                        transaction_id, idempotency_key, run_id, strategy_id,
                        bucket, amount, currency, envelope_json, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.transaction_id,
                        envelope.idempotency_key,
                        envelope.run_id,
                        envelope.strategy_id,
                        envelope.bucket.value,
                        str(envelope.amount),
                        envelope.currency,
                        json.dumps(envelope.to_dict(), sort_keys=True, separators=(",", ":")),
                        self._metadata_json(metadata),
                        envelope.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateTransactionError(
                "transaction_id or idempotency_key already exists"
            ) from exc

    def find_transaction(self, transaction_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "transaction_id": row["transaction_id"],
            "idempotency_key": row["idempotency_key"],
            "run_id": row["run_id"],
            "strategy_id": row["strategy_id"],
            "bucket": row["bucket"],
            "amount": Decimal(row["amount"]),
            "currency": row["currency"],
            "envelope": json.loads(row["envelope_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }

    def record_outcome(
        self,
        transaction_id: str,
        *,
        status: str,
        amount: Decimal | int | str,
        currency: str,
        metadata: Mapping[str, object] | None = None,
    ) -> LedgerEntry:
        transaction = self.find_transaction(transaction_id)
        if transaction is None:
            raise KeyError(transaction_id)
        return self._insert_event(
            kind="outcome",
            transaction_id=transaction_id,
            run_id=str(transaction["run_id"]),
            strategy_id=str(transaction["strategy_id"]),
            bucket=TreasuryBucket(str(transaction["bucket"])),
            amount=as_decimal(amount),
            currency=currency,
            status=status,
            metadata=metadata,
        )

    def record_revenue(
        self,
        *,
        run_id: str,
        strategy_id: str,
        bucket: TreasuryBucket,
        amount: Decimal | int | str,
        currency: str,
        metadata: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> LedgerEntry:
        event_key = None if idempotency_key is None else f"revenue:{idempotency_key}"
        return self._insert_event(
            kind="revenue",
            transaction_id=None,
            run_id=run_id,
            strategy_id=strategy_id,
            bucket=bucket,
            amount=as_decimal(amount),
            currency=currency,
            status="received",
            metadata=metadata,
            event_key=event_key,
        )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> LedgerEntry:
        return LedgerEntry(
            entry_id=int(row["entry_id"]),
            kind=row["kind"],
            transaction_id=row["transaction_id"],
            run_id=row["run_id"],
            strategy_id=row["strategy_id"],
            bucket=None if row["bucket"] is None else TreasuryBucket(row["bucket"]),
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            event_key=row["event_key"],
        )

    def find_event_by_key(self, event_key: str) -> LedgerEntry | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE event_key = ?", (event_key,)
        ).fetchone()
        return None if row is None else self._row_to_entry(row)

    def _insert_event(
        self,
        *,
        kind: str,
        transaction_id: str | None,
        run_id: str,
        strategy_id: str,
        bucket: TreasuryBucket | None,
        amount: Decimal,
        currency: str,
        status: str,
        metadata: Mapping[str, object] | None,
        event_key: str | None = None,
    ) -> LedgerEntry:
        if event_key is not None:
            prior = self.find_event_by_key(event_key)
            if prior is not None:
                return prior
        created_at = utc_now()
        metadata_json = self._metadata_json(metadata)
        try:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    INSERT INTO events (
                        kind, transaction_id, run_id, strategy_id, bucket,
                        amount, currency, status, metadata_json, created_at, event_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kind,
                        transaction_id,
                        run_id,
                        strategy_id,
                        None if bucket is None else bucket.value,
                        str(amount),
                        currency.upper(),
                        status,
                        metadata_json,
                        created_at.isoformat(),
                        event_key,
                    ),
                )
        except sqlite3.IntegrityError:
            if event_key is not None:
                prior = self.find_event_by_key(event_key)
                if prior is not None:
                    return prior
            raise
        return LedgerEntry(
            entry_id=int(cursor.lastrowid),
            kind=kind,
            transaction_id=transaction_id,
            run_id=run_id,
            strategy_id=strategy_id,
            bucket=bucket,
            amount=amount,
            currency=currency.upper(),
            status=status,
            metadata=json.loads(metadata_json),
            created_at=created_at,
            event_key=event_key,
        )

    def entries(self) -> list[LedgerEntry]:
        rows = self._conn.execute("SELECT * FROM events ORDER BY entry_id ASC").fetchall()
        return [self._row_to_entry(row) for row in rows]
