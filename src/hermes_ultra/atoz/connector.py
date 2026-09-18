from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectorOutcome(str, Enum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    RECONCILED = "reconciled"
    AMBIGUOUS = "ambiguous"


class AmbiguousExternalOutcome(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    kind: str
    live: bool
    permissions: tuple[str, ...]
    input_schema: str
    output_schema: str
    idempotency: str
    approval_points: tuple[str, ...]


@dataclass(frozen=True)
class BookingCommand:
    tenant_id: str
    case_id: str
    appointment_id: str
    start_iso: str
    service_location: str
    customer_reference: str
    idempotency_key: str


@dataclass(frozen=True)
class ConnectorReceipt:
    outcome: ConnectorOutcome
    idempotency_key: str
    crm_object_id: str
    calendar_object_id: str
    external_version: int


class ContractTestCrmCalendarAdapter:
    """Controlled endpoint used to prove idempotency/reconciliation semantics.

    It is intentionally not presented as a live CRM/calendar integration.
    """

    manifest = ConnectorManifest(connector_id="contract-test-crm-calendar", kind="crm+calendar", live=False, permissions=("crm.booking.write", "calendar.event.write", "crm.booking.read", "calendar.event.read"), input_schema="atoz-booking-command-v1", output_schema="atoz-connector-receipt-v1", idempotency="caller-supplied stable key; exactly-once external object pair", approval_points=("live external write requires configured authorized connector",))

    def __init__(self) -> None:
        self._objects: dict[str, ConnectorReceipt] = {}
        self._fingerprints: dict[str, tuple[object, ...]] = {}

    @staticmethod
    def _fingerprint(command: BookingCommand) -> tuple[object, ...]:
        return (command.tenant_id, command.case_id, command.appointment_id, command.start_iso, command.service_location, command.customer_reference)

    def apply(self, command: BookingCommand, *, lose_response_after_commit: bool = False) -> ConnectorReceipt:
        if not command.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        fp = self._fingerprint(command)
        prior = self._objects.get(command.idempotency_key)
        if prior is not None:
            if self._fingerprints[command.idempotency_key] != fp:
                raise ValueError("idempotency key reused for different booking command")
            return ConnectorReceipt(ConnectorOutcome.ALREADY_APPLIED, prior.idempotency_key, prior.crm_object_id, prior.calendar_object_id, prior.external_version)
        suffix = len(self._objects) + 1
        receipt = ConnectorReceipt(ConnectorOutcome.APPLIED, command.idempotency_key, f"crm-test-{suffix}", f"cal-test-{suffix}", 1)
        self._objects[command.idempotency_key] = receipt
        self._fingerprints[command.idempotency_key] = fp
        if lose_response_after_commit:
            raise AmbiguousExternalOutcome(command.idempotency_key)
        return receipt

    def reconcile(self, idempotency_key: str) -> ConnectorReceipt | None:
        prior = self._objects.get(idempotency_key)
        if prior is None:
            return None
        return ConnectorReceipt(ConnectorOutcome.RECONCILED, prior.idempotency_key, prior.crm_object_id, prior.calendar_object_id, prior.external_version)
