from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..contracts import ExperimentStatus, as_decimal


@dataclass(frozen=True)
class RevenueOpportunity:
    prospect_id: str
    offer: str
    contract_value: Decimal
    estimated_cost: Decimal
    currency: str = "USD"
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_value", as_decimal(self.contract_value))
        object.__setattr__(self, "estimated_cost", as_decimal(self.estimated_cost))
        object.__setattr__(self, "currency", self.currency.upper())
        if self.contract_value < 0 or self.estimated_cost < 0:
            raise ValueError("opportunity economics must be non-negative")


@dataclass(frozen=True)
class RevenueExperiment:
    experiment_id: str
    run_id: str
    strategy_id: str
    prospect_id: str
    expected_contract_value: Decimal
    estimated_cost: Decimal
    expected_gross_profit: Decimal
    currency: str
    proposed_action: str
    authority_category: str
    evidence: tuple[str, ...]
    status: ExperimentStatus = ExperimentStatus.PLANNED
