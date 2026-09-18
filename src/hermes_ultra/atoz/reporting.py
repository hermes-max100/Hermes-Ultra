from __future__ import annotations

from dataclasses import dataclass

from .persistence import RecoveryCaseStore


@dataclass(frozen=True)
class OutcomeDashboard:
    cases: int
    booked: int
    completed: int
    paid: int
    cancelled: int
    refunded: int
    disputed: int
    attributed_revenue_minor: int
    provider_cost_minor: int
    human_review_minutes: int
    proven_incremental_revenue_minor: int | None


def build_outcome_dashboard(store: RecoveryCaseStore) -> OutcomeDashboard:
    cases = store.list_cases()
    return OutcomeDashboard(len(cases), sum(c.appointment_id is not None for c in cases), sum(c.completion_at is not None for c in cases), sum(c.collected_amount_minor > 0 for c in cases), sum(c.cancellation_at is not None for c in cases), sum(c.refunded_amount_minor > 0 for c in cases), sum(c.dispute_status.value == "open" for c in cases), sum(c.net_collected_minor for c in cases), sum(c.provider_cost_minor for c in cases), sum(c.human_review_minutes for c in cases), None)


def reconcile_dashboard(store: RecoveryCaseStore, dashboard: OutcomeDashboard) -> None:
    cases = store.list_cases()
    if dashboard.attributed_revenue_minor != sum(c.net_collected_minor for c in cases): raise AssertionError("attributed revenue does not reconcile")
    if dashboard.provider_cost_minor != sum(c.provider_cost_minor for c in cases): raise AssertionError("provider costs do not reconcile")
    if dashboard.human_review_minutes != sum(c.human_review_minutes for c in cases): raise AssertionError("human review minutes do not reconcile")


def render_monthly_report(dashboard: OutcomeDashboard, *, currency: str = "USD") -> str:
    return ("# AtoZ Revenue Coverage — Monthly Evidence Report\n\n" f"- Cases: {dashboard.cases}\n" f"- Bookings: {dashboard.booked}\n" f"- Completed jobs: {dashboard.completed}\n" f"- Paid jobs: {dashboard.paid}\n" f"- Refund-bearing cases: {dashboard.refunded}\n" f"- Provider cost ({currency} minor units): {dashboard.provider_cost_minor}\n" f"- Human review minutes: {dashboard.human_review_minutes}\n" f"- Attributed revenue ({currency} minor units): {dashboard.attributed_revenue_minor}\n" "- Proven incremental revenue: not proven by attribution ledger\n")
