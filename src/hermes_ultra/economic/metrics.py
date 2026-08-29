from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .ledger import EconomicLedger


@dataclass(frozen=True)
class EconomicMetrics:
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    roi: Decimal | None
    qualified_leads: int = 0
    appointments_booked: int = 0
    completed_outcomes: int = 0
    conversion_rate: Decimal | None = None
    attributed_revenue: Decimal = Decimal("0")
    gross_margin: Decimal | None = None
    cost_per_completed_outcome: Decimal | None = None

    @classmethod
    def from_ledger(
        cls,
        ledger: EconomicLedger,
        *,
        run_id: str | None = None,
        strategy_id: str | None = None,
    ) -> "EconomicMetrics":
        revenue = Decimal("0")
        cost = Decimal("0")
        qualified_leads = 0
        appointments_booked = 0
        completed_outcomes = 0
        for entry in ledger.entries():
            if run_id is not None and entry.run_id != run_id:
                continue
            if strategy_id is not None and entry.strategy_id != strategy_id:
                continue
            if entry.kind == "revenue" and entry.status == "received":
                revenue += entry.amount
            elif entry.kind == "outcome" and entry.status in {"success", "executed"}:
                cost += entry.amount
            elif entry.kind == "business_outcome":
                if entry.status == "qualified_lead":
                    qualified_leads += 1
                elif entry.status == "appointment_booked":
                    appointments_booked += 1
                elif entry.status == "completed_outcome":
                    completed_outcomes += 1

        gross_profit = revenue - cost
        roi = None if cost == 0 else gross_profit / cost
        conversion_rate = (
            None
            if qualified_leads == 0
            else Decimal(completed_outcomes) / Decimal(qualified_leads)
        )
        gross_margin = None if revenue == 0 else gross_profit / revenue
        cost_per_completed_outcome = (
            None
            if completed_outcomes == 0
            else cost / Decimal(completed_outcomes)
        )
        return cls(
            revenue=revenue,
            cost=cost,
            gross_profit=gross_profit,
            roi=roi,
            qualified_leads=qualified_leads,
            appointments_booked=appointments_booked,
            completed_outcomes=completed_outcomes,
            conversion_rate=conversion_rate,
            attributed_revenue=revenue,
            gross_margin=gross_margin,
            cost_per_completed_outcome=cost_per_completed_outcome,
        )
