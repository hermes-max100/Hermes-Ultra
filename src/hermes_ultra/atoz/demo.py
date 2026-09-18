from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..autonomy import ApprovalRegistry
from .connector import AmbiguousExternalOutcome, BookingCommand, ContractTestCrmCalendarAdapter
from .controls import ActionRequest, AgentIdentity, DataHandlingPolicy, ExecutionPolicyGateway, SpendPolicy
from .job_packet import JobPacketBuilder
from .lead import LeadConversation, LeadIngestor
from .model import RecoveryEvent, RecoveryEventKind
from .persistence import RecoveryCaseStore
from .reporting import build_outcome_dashboard, reconcile_dashboard


def run_synthetic_demo(db_path: str | Path) -> dict[str, object]:
    now = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
    lead = LeadConversation("lead-demo-1", "tenant-demo", "synthetic-after-hours-call", "synthetic-001", "pilot-validation", ("synthetic-consent:1",), "No-cool HVAC after hours", True, False, 0, "USD", now)
    _, created = LeadIngestor().ingest(lead)
    if not created: raise AssertionError("synthetic lead unexpectedly deduplicated")
    with RecoveryCaseStore(db_path) as store:
        case = store.open_case(case_id="case-demo-1", tenant_id=lead.tenant_id, lead_conversation_id=lead.lead_conversation_id, original_lead_source=lead.source, intake_at=now, evidence_refs=("synthetic-lead:1",))
        store.append_event(RecoveryEvent("event-demo-booked", case.case_id, case.tenant_id, RecoveryEventKind.APPOINTMENT_BOOKED, now, {"appointment_id": "appt-demo-1"}, ("synthetic-booking:1",)))
        case = store.require_case(case.case_id)
        packet = JobPacketBuilder.build(case, customer_need=lead.customer_need, service_location="123 Synthetic Ave, Test City, CA 90001", scheduling_constraints=("after-hours",), equipment_details=("customer reports rooftop package unit",), approved_reference_ids=("synthetic-lead:1",))
        gateway = ExecutionPolicyGateway(approval_registry=ApprovalRegistry(), spend_policy=SpendPolicy(5000), data_policy=DataHandlingPolicy(permitted_tags=frozenset({"contact_reference", "service_location"})))
        gateway.register(AgentIdentity("atoz-booker", case.tenant_id, "atoz-pilot", frozenset({"crm.booking.write", "calendar.event.write"})))
        action = ActionRequest("action-demo-booking", "atoz-booker", case.tenant_id, "demo-run-1", "crm.booking.write", "pilot_booking", True, True, 0, frozenset({"contact_reference", "service_location"}))
        if not gateway.begin_dispatch(action).allowed: raise AssertionError("synthetic authorized booking was blocked")
        connector = ContractTestCrmCalendarAdapter()
        command = BookingCommand(case.tenant_id, case.case_id, case.appointment_id or "", "2026-09-18T01:00:00-07:00", packet.service_location, "synthetic-contact-1", "booking:case-demo-1:appt-demo-1")
        try: connector.apply(command, lose_response_after_commit=True)
        except AmbiguousExternalOutcome: gateway.mark_ambiguous(action.action_id)
        receipt = connector.reconcile(command.idempotency_key)
        if receipt is None: raise AssertionError("ambiguous booking failed reconciliation")
        for ev in (
            RecoveryEvent("event-demo-job", case.case_id, case.tenant_id, RecoveryEventKind.JOB_SCHEDULED, now, {"job_id": "job-demo-1"}, ("synthetic-crm:1",)),
            RecoveryEvent("event-demo-complete", case.case_id, case.tenant_id, RecoveryEventKind.JOB_COMPLETED, now, {}, ("synthetic-completion:1",)),
            RecoveryEvent("event-demo-paid", case.case_id, case.tenant_id, RecoveryEventKind.PAYMENT_COLLECTED, now, {"payment_id": "payment-demo-1", "amount_minor": 42500}, ("synthetic-payment:1",)),
            RecoveryEvent("event-demo-provider-cost", case.case_id, case.tenant_id, RecoveryEventKind.PROVIDER_COST_RECORDED, now, {"amount_minor": 125}, ("synthetic-cost:1",)),
            RecoveryEvent("event-demo-review", case.case_id, case.tenant_id, RecoveryEventKind.HUMAN_REVIEW_RECORDED, now, {"minutes": 3}, ("synthetic-review:1",)),
        ): store.append_event(ev)
        billable = store.decide_billable_outcome(case.case_id, now=now)
        dashboard = build_outcome_dashboard(store); reconcile_dashboard(store, dashboard)
        return {"lead_id": lead.lead_conversation_id, "case_id": case.case_id, "job_packet_id": packet.packet_id, "connector_outcome": receipt.outcome.value, "crm_object_id": receipt.crm_object_id, "calendar_object_id": receipt.calendar_object_id, "billable_eligible": billable.eligible, "success_fee_enabled": billable.success_fee_enabled, "attributed_revenue_minor": dashboard.attributed_revenue_minor, "provider_cost_minor": dashboard.provider_cost_minor, "human_review_minutes": dashboard.human_review_minutes, "proven_incremental_revenue_minor": dashboard.proven_incremental_revenue_minor}
