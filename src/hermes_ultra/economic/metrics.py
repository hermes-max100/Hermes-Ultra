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
        for entry in ledger.entries():
            if run_id is not None and entry.run_id != run_id:
                continue
            if strategy_id is not None and entry.strategy_id != strategy_id:
                continue
            if entry.kind == "revenue" and entry.status == "received":
                revenue += entry.amount
            elif entry.kind == "outcome" and entry.status in {"success", "executed"}:
                cost += entry.amount
        gross_profit = revenue - cost
        roi = None if cost == 0 else gross_profit / cost
        return cls(revenue=revenue, cost=cost, gross_profit=gross_profit, roi=roi)
