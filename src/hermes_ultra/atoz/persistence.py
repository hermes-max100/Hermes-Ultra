from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .model import BillableOutcomeDecision, DisputeStatus, RecoveryCase, RecoveryCaseStatus, RecoveryEvent, RecoveryEventKind, utc_now

SCHEMA_VERSION = 1


class EventConflictError(ValueError):
    pass


class InvalidLifecycleTransition(ValueError):
    pass


class RecoveryCaseStore:
    """Durable event ledger + projected RecoveryCase state.

    Event IDs are idempotency keys. Replaying the same event is a no-op; reusing an
    event ID with different content fails closed.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def __enter__(self) -> "RecoveryCaseStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {current} is newer than supported {SCHEMA_VERSION}")
        if current == 0:
            with self._conn:
                self._conn.executescript("""
                    CREATE TABLE recovery_cases (
                        case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                        lead_conversation_id TEXT NOT NULL, original_lead_source TEXT NOT NULL,
                        intake_at TEXT NOT NULL, currency TEXT NOT NULL,
                        attribution_window_hours INTEGER NOT NULL, attribution_rule_version TEXT NOT NULL,
                        status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                        appointment_id TEXT, job_id TEXT, payment_id TEXT,
                        collected_amount_minor INTEGER NOT NULL DEFAULT 0,
                        refunded_amount_minor INTEGER NOT NULL DEFAULT 0,
                        provider_cost_minor INTEGER NOT NULL DEFAULT 0,
                        human_review_minutes INTEGER NOT NULL DEFAULT 0,
                        completion_at TEXT, collection_at TEXT, cancellation_at TEXT,
                        duplicate_of_case_id TEXT,
                        dispute_status TEXT NOT NULL DEFAULT 'none',
                        evidence_refs_json TEXT NOT NULL DEFAULT '[]'
                    );
                    CREATE TABLE recovery_events (
                        event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL,
                        case_id TEXT NOT NULL, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
                        occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                        evidence_refs_json TEXT NOT NULL,
                        FOREIGN KEY(case_id) REFERENCES recovery_cases(case_id)
                    );
                    CREATE INDEX idx_recovery_events_case ON recovery_events(case_id, occurred_at, event_id);
                    CREATE TABLE billable_outcome_decisions (
                        case_id TEXT NOT NULL, rule_version TEXT NOT NULL, eligible INTEGER NOT NULL,
                        reasons_json TEXT NOT NULL, evidence_refs_json TEXT NOT NULL,
                        decided_at TEXT NOT NULL, success_fee_enabled INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(case_id, rule_version),
                        FOREIGN KEY(case_id) REFERENCES recovery_cases(case_id)
                    );
                    PRAGMA user_version = 1;
                """)

    @staticmethod
    def _event_serialization(event: RecoveryEvent) -> str:
        return json.dumps({"event_id": event.event_id, "case_id": event.case_id, "tenant_id": event.tenant_id, "kind": event.kind.value, "occurred_at": event.occurred_at.isoformat(), "payload": dict(event.payload), "evidence_refs": list(event.evidence_refs)}, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _event_hash(cls, event: RecoveryEvent) -> str:
        return hashlib.sha256(cls._event_serialization(event).encode()).hexdigest()

    def open_case(self, *, case_id: str, tenant_id: str, lead_conversation_id: str, original_lead_source: str, intake_at: datetime, currency: str = "USD", attribution_window_hours: int = 720, attribution_rule_version: str = "atoz-attribution-v1", evidence_refs: Iterable[str] = (), event_id: str | None = None) -> RecoveryCase:
        if attribution_window_hours <= 0:
            raise ValueError("attribution_window_hours must be positive")
        if len(currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        event = RecoveryEvent(event_id or f"{case_id}:opened", case_id, tenant_id, RecoveryEventKind.CASE_OPENED, intake_at, {"lead_conversation_id": lead_conversation_id, "original_lead_source": original_lead_source, "currency": currency.upper(), "attribution_window_hours": attribution_window_hours, "attribution_rule_version": attribution_rule_version}, tuple(evidence_refs))
        self.append_event(event)
        return self.require_case(case_id)

    def append_event(self, event: RecoveryEvent) -> bool:
        event_hash = self._event_hash(event)
        prior = self._conn.execute("SELECT event_hash FROM recovery_events WHERE event_id = ?", (event.event_id,)).fetchone()
        if prior is not None:
            if prior["event_hash"] != event_hash:
                raise EventConflictError(f"event_id {event.event_id!r} was reused with different content")
            return False
        existing = self._conn.execute("SELECT tenant_id FROM recovery_cases WHERE case_id = ?", (event.case_id,)).fetchone()
        if event.kind is RecoveryEventKind.CASE_OPENED:
            if existing is not None and existing["tenant_id"] != event.tenant_id:
                raise EventConflictError("case_id already belongs to a different tenant")
        else:
            if existing is None:
                raise KeyError(event.case_id)
            if existing["tenant_id"] != event.tenant_id:
                raise PermissionError("cross-tenant RecoveryCase event rejected")
        with self._conn:
            if event.kind is RecoveryEventKind.CASE_OPENED and existing is None:
                p = event.payload
                self._conn.execute("""INSERT INTO recovery_cases (case_id, tenant_id, lead_conversation_id, original_lead_source, intake_at, currency, attribution_window_hours, attribution_rule_version, status, revision, evidence_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""", (event.case_id, event.tenant_id, str(p["lead_conversation_id"]), str(p["original_lead_source"]), event.occurred_at.isoformat(), str(p["currency"]).upper(), int(p["attribution_window_hours"]), str(p["attribution_rule_version"]), RecoveryCaseStatus.OPEN.value, json.dumps(list(event.evidence_refs))))
            elif event.kind is RecoveryEventKind.CASE_OPENED:
                raise EventConflictError("case already exists with a different open event")
            self._validate_transition(event)
            self._conn.execute("""INSERT INTO recovery_events (event_id, event_hash, case_id, tenant_id, kind, occurred_at, payload_json, evidence_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (event.event_id, event_hash, event.case_id, event.tenant_id, event.kind.value, event.occurred_at.isoformat(), json.dumps(dict(event.payload), sort_keys=True, separators=(",", ":"), default=str), json.dumps(list(event.evidence_refs))))
            if event.kind is not RecoveryEventKind.CASE_OPENED:
                self._project(event)
            else:
                self._merge_evidence(event.case_id, event.evidence_refs)
        return True

    def _validate_transition(self, event: RecoveryEvent) -> None:
        if event.kind is RecoveryEventKind.CASE_OPENED:
            return
        case = self.require_case(event.case_id)
        if case.status in {RecoveryCaseStatus.CANCELLED, RecoveryCaseStatus.DUPLICATE} and event.kind not in {RecoveryEventKind.DISPUTE_OPENED, RecoveryEventKind.DISPUTE_RESOLVED, RecoveryEventKind.REFUNDED}:
            raise InvalidLifecycleTransition(f"cannot apply {event.kind.value} after terminal status {case.status.value}")
        if event.kind is RecoveryEventKind.JOB_COMPLETED and not case.job_id:
            raise InvalidLifecycleTransition("job completion requires a scheduled job")
        if event.kind is RecoveryEventKind.PAYMENT_COLLECTED and case.completion_at is None:
            raise InvalidLifecycleTransition("payment attribution requires a completed job")
        if event.kind is RecoveryEventKind.REFUNDED and case.collected_amount_minor <= 0:
            raise InvalidLifecycleTransition("refund requires a collected payment")

    def _merge_evidence(self, case_id: str, refs: Iterable[str]) -> None:
        row = self._conn.execute("SELECT evidence_refs_json FROM recovery_cases WHERE case_id = ?", (case_id,)).fetchone()
        current = list(json.loads(row["evidence_refs_json"])) if row else []
        merged = list(dict.fromkeys([*current, *(ref for ref in refs if ref)]))
        self._conn.execute("UPDATE recovery_cases SET evidence_refs_json = ? WHERE case_id = ?", (json.dumps(merged), case_id))

    def _project(self, event: RecoveryEvent) -> None:
        p = event.payload
        assignments: dict[str, object] = {"revision": self.require_case(event.case_id).revision + 1}
        kind = event.kind
        if kind is RecoveryEventKind.RECOVERY_ATTEMPTED:
            assignments["status"] = RecoveryCaseStatus.RECOVERY_ACTIVE.value
        elif kind is RecoveryEventKind.APPOINTMENT_BOOKED:
            reference = str(p.get("appointment_id", "")).strip()
            if not reference:
                raise ValueError("appointment_id is required")
            assignments.update(status=RecoveryCaseStatus.APPOINTMENT_BOOKED.value, appointment_id=reference)
        elif kind is RecoveryEventKind.JOB_SCHEDULED:
            reference = str(p.get("job_id", "")).strip()
            if not reference:
                raise ValueError("job_id is required")
            assignments.update(status=RecoveryCaseStatus.JOB_SCHEDULED.value, job_id=reference)
        elif kind is RecoveryEventKind.JOB_COMPLETED:
            assignments.update(status=RecoveryCaseStatus.JOB_COMPLETED.value, completion_at=event.occurred_at.isoformat())
        elif kind is RecoveryEventKind.PAYMENT_COLLECTED:
            payment_id = str(p.get("payment_id", "")).strip(); amount = int(p.get("amount_minor", 0))
            if not payment_id or amount <= 0:
                raise ValueError("payment_id and positive amount_minor are required")
            case = self.require_case(event.case_id)
            assignments.update(status=RecoveryCaseStatus.PAID.value, payment_id=payment_id, collected_amount_minor=case.collected_amount_minor + amount, collection_at=event.occurred_at.isoformat())
        elif kind is RecoveryEventKind.CANCELLED:
            assignments.update(status=RecoveryCaseStatus.CANCELLED.value, cancellation_at=event.occurred_at.isoformat())
        elif kind is RecoveryEventKind.REFUNDED:
            amount = int(p.get("amount_minor", 0)); case = self.require_case(event.case_id)
            if amount <= 0:
                raise ValueError("positive refund amount_minor is required")
            if case.refunded_amount_minor + amount > case.collected_amount_minor:
                raise ValueError("refund cannot exceed collected amount")
            assignments.update(status=RecoveryCaseStatus.REFUNDED.value, refunded_amount_minor=case.refunded_amount_minor + amount)
        elif kind is RecoveryEventKind.MARKED_DUPLICATE:
            duplicate_of = str(p.get("duplicate_of_case_id", "")).strip()
            if not duplicate_of or duplicate_of == event.case_id:
                raise ValueError("valid duplicate_of_case_id is required")
            assignments.update(status=RecoveryCaseStatus.DUPLICATE.value, duplicate_of_case_id=duplicate_of)
        elif kind is RecoveryEventKind.DISPUTE_OPENED:
            assignments.update(status=RecoveryCaseStatus.DISPUTED.value, dispute_status=DisputeStatus.OPEN.value)
        elif kind is RecoveryEventKind.DISPUTE_RESOLVED:
            case = self.require_case(event.case_id)
            restored = RecoveryCaseStatus.PAID if case.collected_amount_minor > case.refunded_amount_minor else RecoveryCaseStatus.JOB_COMPLETED
            assignments.update(status=restored.value, dispute_status=DisputeStatus.RESOLVED.value)
        elif kind is RecoveryEventKind.PROVIDER_COST_RECORDED:
            amount = int(p.get("amount_minor", 0)); case = self.require_case(event.case_id)
            if amount < 0:
                raise ValueError("provider cost cannot be negative")
            assignments["provider_cost_minor"] = case.provider_cost_minor + amount
        elif kind is RecoveryEventKind.HUMAN_REVIEW_RECORDED:
            minutes = int(p.get("minutes", 0)); case = self.require_case(event.case_id)
            if minutes < 0:
                raise ValueError("human review minutes cannot be negative")
            assignments["human_review_minutes"] = case.human_review_minutes + minutes
        columns = ", ".join(f"{name} = ?" for name in assignments)
        self._conn.execute(f"UPDATE recovery_cases SET {columns} WHERE case_id = ?", (*assignments.values(), event.case_id))
        self._merge_evidence(event.case_id, event.evidence_refs)

    def require_case(self, case_id: str) -> RecoveryCase:
        row = self._conn.execute("SELECT * FROM recovery_cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        def dt(name: str) -> datetime | None:
            value = row[name]
            return None if value is None else datetime.fromisoformat(value)
        return RecoveryCase(case_id=row["case_id"], tenant_id=row["tenant_id"], lead_conversation_id=row["lead_conversation_id"], original_lead_source=row["original_lead_source"], intake_at=datetime.fromisoformat(row["intake_at"]), currency=row["currency"], attribution_window_hours=int(row["attribution_window_hours"]), attribution_rule_version=row["attribution_rule_version"], status=RecoveryCaseStatus(row["status"]), revision=int(row["revision"]), appointment_id=row["appointment_id"], job_id=row["job_id"], payment_id=row["payment_id"], collected_amount_minor=int(row["collected_amount_minor"]), refunded_amount_minor=int(row["refunded_amount_minor"]), provider_cost_minor=int(row["provider_cost_minor"]), human_review_minutes=int(row["human_review_minutes"]), completion_at=dt("completion_at"), collection_at=dt("collection_at"), cancellation_at=dt("cancellation_at"), duplicate_of_case_id=row["duplicate_of_case_id"], dispute_status=DisputeStatus(row["dispute_status"]), evidence_refs=tuple(json.loads(row["evidence_refs_json"])))

    def decide_billable_outcome(self, case_id: str, *, rule_version: str = "atoz-billable-v1", now: datetime | None = None) -> BillableOutcomeDecision:
        case = self.require_case(case_id); reasons: list[str] = []
        if case.completion_at is None: reasons.append("job_not_completed")
        if case.collected_amount_minor <= 0: reasons.append("payment_not_collected")
        if case.net_collected_minor <= 0: reasons.append("no_net_collection")
        if case.cancellation_at is not None: reasons.append("cancelled")
        if case.refunded_amount_minor > 0: reasons.append("refund_present")
        if case.duplicate_of_case_id is not None: reasons.append("duplicate_case")
        if case.dispute_status is DisputeStatus.OPEN: reasons.append("dispute_open")
        if case.collection_at and (case.collection_at - case.intake_at).total_seconds() > case.attribution_window_hours * 3600: reasons.append("outside_attribution_window")
        if not case.evidence_refs: reasons.append("supporting_evidence_missing")
        decision = BillableOutcomeDecision(case.case_id, not reasons, rule_version, tuple(reasons) if reasons else ("eligible_completed_paid_job",), case.evidence_refs, now or utc_now(), False)
        with self._conn:
            self._conn.execute("""INSERT INTO billable_outcome_decisions (case_id, rule_version, eligible, reasons_json, evidence_refs_json, decided_at, success_fee_enabled) VALUES (?, ?, ?, ?, ?, ?, 0) ON CONFLICT(case_id, rule_version) DO UPDATE SET eligible=excluded.eligible, reasons_json=excluded.reasons_json, evidence_refs_json=excluded.evidence_refs_json, decided_at=excluded.decided_at, success_fee_enabled=0""", (decision.case_id, decision.rule_version, int(decision.eligible), json.dumps(list(decision.reasons)), json.dumps(list(decision.evidence_refs)), decision.decided_at.isoformat()))
        return decision

    def events(self, case_id: str | None = None) -> list[dict[str, object]]:
        rows = self._conn.execute("SELECT * FROM recovery_events ORDER BY occurred_at, event_id" if case_id is None else "SELECT * FROM recovery_events WHERE case_id = ? ORDER BY occurred_at, event_id", () if case_id is None else (case_id,)).fetchall()
        return [{"event_id": row["event_id"], "case_id": row["case_id"], "tenant_id": row["tenant_id"], "kind": row["kind"], "occurred_at": row["occurred_at"], "payload": json.loads(row["payload_json"]), "evidence_refs": json.loads(row["evidence_refs_json"])} for row in rows]

    def list_cases(self) -> list[RecoveryCase]:
        return [self.require_case(row[0]) for row in self._conn.execute("SELECT case_id FROM recovery_cases ORDER BY case_id")]
