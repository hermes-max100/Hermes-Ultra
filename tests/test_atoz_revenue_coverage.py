from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.atoz import (
    ActionRequest, AgentIdentity, AmbiguousExternalOutcome,
    BookingBenchmarkObservation, BookingCommand, ContractTestCrmCalendarAdapter,
    DataHandlingPolicy, DispatchState, EventConflictError, ExecutionPolicyGateway,
    JobPacketBuilder, JobPacketValidationError, LeadConversation, LeadIngestor,
    RecoveryCaseStore, RecoveryEvent, RecoveryEventKind, SpendPolicy,
    VisualObservation, aggregate_booking_benchmark, build_outcome_dashboard,
    build_visual_extension, reconcile_dashboard, run_synthetic_demo,
)

NOW = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)


def ev(event_id, kind, payload=None, *, case="case-1", tenant="tenant-1", at=NOW, refs=("evidence:test",)):
    return RecoveryEvent(event_id, case, tenant, kind, at, payload or {}, refs)


def open_case(store, case="case-1", tenant="tenant-1", window=720):
    return store.open_case(case_id=case, tenant_id=tenant, lead_conversation_id=f"lead-{case}", original_lead_source="after-hours-phone", intake_at=NOW, attribution_window_hours=window, evidence_refs=("lead:1",))


def paid_case(store):
    open_case(store)
    store.append_event(ev("book", RecoveryEventKind.APPOINTMENT_BOOKED, {"appointment_id":"appt-1"}))
    store.append_event(ev("job", RecoveryEventKind.JOB_SCHEDULED, {"job_id":"job-1"}))
    store.append_event(ev("done", RecoveryEventKind.JOB_COMPLETED))
    store.append_event(ev("paid", RecoveryEventKind.PAYMENT_COLLECTED, {"payment_id":"pay-1","amount_minor":25000}))


def gateway():
    g = ExecutionPolicyGateway(approval_registry=ApprovalRegistry({"payment"}), spend_policy=SpendPolicy(100), data_policy=DataHandlingPolicy(permitted_tags=frozenset({"contact_reference"})))
    g.register(AgentIdentity("agent-1", "tenant-1", "owner-1", frozenset({"crm.write"})))
    return g


def req(**changes):
    values = dict(action_id="action-1", agent_id="agent-1", tenant_id="tenant-1", run_id="run-1", permission="crm.write", action_category="booking", reversible=True, remote=True, estimated_cost_minor=25, data_tags=frozenset({"contact_reference"}))
    values.update(changes)
    return ActionRequest(**values)


def test_recovery_case_paid_path_is_traceable_and_billable_is_separate(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        paid_case(store)
        decision = store.decide_billable_outcome("case-1", now=NOW)
        case = store.require_case("case-1")
        assert decision.eligible and not decision.success_fee_enabled
        assert (case.appointment_id, case.job_id, case.payment_id, case.net_collected_minor) == ("appt-1","job-1","pay-1",25000)
        assert len(store.events("case-1")) == 5


def test_duplicate_event_replay_is_noop_but_conflicting_reuse_fails(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        open_case(store)
        item = ev("same", RecoveryEventKind.RECOVERY_ATTEMPTED, {"attempt":1})
        assert store.append_event(item) is True
        assert store.append_event(item) is False
        with pytest.raises(EventConflictError):
            store.append_event(ev("same", RecoveryEventKind.RECOVERY_ATTEMPTED, {"attempt":2}))


def test_refund_dispute_duplicate_and_window_exclude_billable(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        paid_case(store)
        store.append_event(ev("refund", RecoveryEventKind.REFUNDED, {"amount_minor":5000}))
        assert "refund_present" in store.decide_billable_outcome("case-1", now=NOW).reasons
        open_case(store, "case-2")
        store.append_event(ev("dup", RecoveryEventKind.MARKED_DUPLICATE, {"duplicate_of_case_id":"case-1"}, case="case-2"))
        assert "duplicate_case" in store.decide_billable_outcome("case-2", now=NOW).reasons
        open_case(store, "case-3")
        store.append_event(ev("dispute", RecoveryEventKind.DISPUTE_OPENED, case="case-3"))
        assert "dispute_open" in store.decide_billable_outcome("case-3", now=NOW).reasons
        open_case(store, "case-4", window=1)
        late = NOW + timedelta(hours=2)
        for item in (
            ev("b4", RecoveryEventKind.APPOINTMENT_BOOKED, {"appointment_id":"a"}, case="case-4", at=late),
            ev("j4", RecoveryEventKind.JOB_SCHEDULED, {"job_id":"j"}, case="case-4", at=late),
            ev("d4", RecoveryEventKind.JOB_COMPLETED, case="case-4", at=late),
            ev("p4", RecoveryEventKind.PAYMENT_COLLECTED, {"payment_id":"p","amount_minor":1000}, case="case-4", at=late),
        ): store.append_event(item)
        assert "outside_attribution_window" in store.decide_billable_outcome("case-4", now=late).reasons


def test_cross_tenant_case_mutation_fails_closed(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        open_case(store)
        with pytest.raises(PermissionError):
            store.append_event(ev("cross", RecoveryEventKind.RECOVERY_ATTEMPTED, tenant="tenant-2"))


def test_job_packet_blocks_missing_critical_fields_and_flags_review(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        case = open_case(store)
        with pytest.raises(JobPacketValidationError):
            JobPacketBuilder.build(case, customer_need="leak", service_location="123 Test St")
        store.append_event(ev("book", RecoveryEventKind.APPOINTMENT_BOOKED, {"appointment_id":"a"}))
        packet = JobPacketBuilder.build(store.require_case("case-1"), customer_need="leak", service_location="123 Test St", unresolved_questions=("shutoff unknown",))
        assert packet.review_required


def test_connector_timeout_reconciles_exactly_once():
    adapter = ContractTestCrmCalendarAdapter()
    command = BookingCommand("tenant-1","case-1","appt-1","2026-09-18T09:00:00-07:00","123 Test St","opaque-contact","booking-1")
    with pytest.raises(AmbiguousExternalOutcome): adapter.apply(command, lose_response_after_commit=True)
    reconciled = adapter.reconcile("booking-1")
    replay = adapter.apply(command)
    assert reconciled and replay.crm_object_id == reconciled.crm_object_id and replay.calendar_object_id == reconciled.calendar_object_id


def test_gateway_blocks_cross_tenant_revoked_budget_forbidden_and_publication():
    assert gateway().begin_dispatch(req(tenant_id="tenant-2")).reason == "cross_tenant_access"
    g=gateway(); g.revoke("agent-1"); assert g.begin_dispatch(req()).reason == "agent_revoked"
    assert gateway().begin_dispatch(req(estimated_cost_minor=101)).reason == "budget_exhausted"
    assert gateway().begin_dispatch(req(data_tags=frozenset({"host_credentials"}))).reason == "forbidden_data"
    decision = gateway().begin_dispatch(req(action_id="publish", action_category="external_publication", reversible=False, external_irreversible_effect=True))
    assert not decision.allowed and decision.state is DispatchState.BLOCKED_PRE_DISPATCH


def test_pause_and_cancel_block_new_work_without_claiming_reversal():
    g = gateway()
    assert g.begin_dispatch(req(action_id="inflight")).allowed
    g.mark_external_accepted("inflight")
    g.pause()
    assert g.state("inflight") is DispatchState.EXTERNAL_ACCEPTED
    assert g.begin_dispatch(req(action_id="queued-pause")).reason == "global_pause"
    g.resume(); g.cancel_run("run-1")
    assert g.begin_dispatch(req(action_id="queued-cancel")).reason == "run_cancelled"
    assert g.state("inflight") is DispatchState.EXTERNAL_ACCEPTED


def test_idempotent_action_replay_does_not_spend_twice():
    g=gateway()
    assert g.begin_dispatch(req(estimated_cost_minor=75)).allowed
    assert g.begin_dispatch(req(estimated_cost_minor=75)).reason == "idempotent_replay"
    assert g.begin_dispatch(req(action_id="action-2", estimated_cost_minor=25)).allowed


def test_channel_neutral_lead_deduplicates():
    lead = LeadConversation("lead-1","tenant-1","web-chat","external-1","fall",("consent:1",),"water heater",True,False,1200,"USD",NOW)
    ingestor=LeadIngestor(); assert ingestor.ingest(lead)[1] is True; assert ingestor.ingest(lead)[1] is False


def test_dashboard_reconciles_and_never_claims_incrementality(tmp_path):
    with RecoveryCaseStore(tmp_path/"db.sqlite3") as store:
        paid_case(store)
        store.append_event(ev("cost", RecoveryEventKind.PROVIDER_COST_RECORDED, {"amount_minor":50}))
        store.append_event(ev("review", RecoveryEventKind.HUMAN_REVIEW_RECORDED, {"minutes":4}))
        dashboard=build_outcome_dashboard(store); reconcile_dashboard(store,dashboard)
        assert dashboard.attributed_revenue_minor == 25000 and dashboard.proven_incremental_revenue_minor is None


def test_voice_benchmark_reports_task_accuracy_safety_latency_transfer_and_loaded_cost():
    rows=[
        BookingBenchmarkObservation("fixture","1",False,True,5,5,0,400,False,False,0,Decimal("0.05"),Decimal("0")),
        BookingBenchmarkObservation("fixture","2",False,False,4,5,1,900,True,False,60,Decimal("0.06"),Decimal("0.50")),
    ]
    metrics=aggregate_booking_benchmark(rows)
    assert metrics.critical_field_accuracy == Decimal("0.9")
    assert metrics.unauthorized_tool_actions == 1
    assert metrics.p95_latency_ms == 900
    assert metrics.transfer_success_rate == Decimal("0")
    assert metrics.fully_loaded_cost_per_correct_booking == Decimal("0.61")
    assert metrics.all_measured_live is False


def test_visual_extension_preserves_provenance_and_requires_confirmation():
    result=build_visual_extension("case-1", (VisualObservation("photo-1","case-1","upload:sha256:abc",("data plate visible",),("appears rooftop HVAC",),"MODEL-123",Decimal("0.72")),))
    assert result.confirmation_required and result.observations[0].provenance_reference == "upload:sha256:abc"


def test_synthetic_end_to_end_trace(tmp_path):
    result=run_synthetic_demo(tmp_path/"demo.sqlite3")
    assert result["connector_outcome"] == "reconciled"
    assert result["billable_eligible"] is True and result["success_fee_enabled"] is False
    assert result["attributed_revenue_minor"] == 42500
    assert result["proven_incremental_revenue_minor"] is None
