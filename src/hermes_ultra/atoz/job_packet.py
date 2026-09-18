from __future__ import annotations

from dataclasses import dataclass

from .model import RecoveryCase


class JobPacketValidationError(ValueError):
    pass


@dataclass(frozen=True)
class JobPacket:
    schema_version: str
    packet_id: str
    case_id: str
    case_revision: int
    tenant_id: str
    customer_need: str
    service_location: str
    scheduling_constraints: tuple[str, ...]
    equipment_details: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    approved_reference_ids: tuple[str, ...]
    review_required: bool


class JobPacketBuilder:
    SCHEMA_VERSION = "atoz-job-packet-v1"

    @classmethod
    def build(cls, case: RecoveryCase, *, customer_need: str, service_location: str, scheduling_constraints: tuple[str, ...] = (), equipment_details: tuple[str, ...] = (), unresolved_questions: tuple[str, ...] = (), approved_reference_ids: tuple[str, ...] = ()) -> JobPacket:
        missing = []
        if not customer_need.strip():
            missing.append("customer_need")
        if not service_location.strip():
            missing.append("service_location")
        if case.appointment_id is None:
            missing.append("appointment_id")
        if missing:
            raise JobPacketValidationError("dispatch blocked; missing: " + ", ".join(missing))
        return JobPacket(schema_version=cls.SCHEMA_VERSION, packet_id=f"job-packet:{case.case_id}:r{case.revision}", case_id=case.case_id, case_revision=case.revision, tenant_id=case.tenant_id, customer_need=customer_need.strip(), service_location=service_location.strip(), scheduling_constraints=tuple(item.strip() for item in scheduling_constraints if item.strip()), equipment_details=tuple(item.strip() for item in equipment_details if item.strip()), unresolved_questions=tuple(item.strip() for item in unresolved_questions if item.strip()), approved_reference_ids=tuple(dict.fromkeys(item.strip() for item in approved_reference_ids if item.strip())), review_required=bool(unresolved_questions))
