from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .contracts import ExperimentStatus, TreasuryBucket, as_decimal
from .ledger import EconomicLedger
from .state import EconomicState, ExperimentState
from .strategies.base import RevenueExperiment, RevenueOpportunity
from .strategies.service_sales import ServiceSalesStrategy


class EconomicEngine:
    """Revenue OS economic lifecycle coordinator; contains no model/router authority."""

    def __init__(self, *, state: EconomicState, ledger: EconomicLedger, payment_adapter=None) -> None:
        self.state = state
        self.ledger = ledger
        self.payment_adapter = payment_adapter

    def start_service_sales_experiment(
        self,
        strategy: ServiceSalesStrategy,
        opportunity: RevenueOpportunity,
        *,
        run_id: str,
    ) -> RevenueExperiment:
        proposal = strategy.propose(run_id=run_id, opportunity=opportunity)
        running = replace(proposal, status=ExperimentStatus.RUNNING)
        prior = self.state.experiments.get(running.experiment_id)
        if prior is None:
            self.state.experiments[running.experiment_id] = ExperimentState(
                experiment_id=running.experiment_id,
                strategy_id=running.strategy_id,
                run_id=running.run_id,
                status=ExperimentStatus.RUNNING,
                reserved_budget=running.estimated_cost,
            )
        return running

    def stop_experiment(self, experiment_id: str) -> ExperimentState:
        current = self.state.experiments.get(experiment_id)
        if current is None:
            raise KeyError(experiment_id)
        stopped = replace(
            current,
            status=ExperimentStatus.STOPPED,
            reserved_budget=Decimal("0"),
        )
        self.state.experiments[experiment_id] = stopped
        return stopped

    def record_revenue(
        self,
        experiment_id: str,
        *,
        amount: Decimal | int | str,
        currency: str,
        idempotency_key: str,
    ):
        experiment = self.state.experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        if self.payment_adapter is None:
            raise RuntimeError("payment adapter is not configured")
        value = as_decimal(amount)
        result = self.payment_adapter.record_revenue(
            run_id=experiment.run_id,
            strategy_id=experiment.strategy_id,
            amount=value,
            currency=currency,
            idempotency_key=idempotency_key,
            mode=self.state.mode,
        )
        if not result.ok:
            return result

        event_key = f"revenue:{idempotency_key}"
        prior = self.ledger.find_event_by_key(event_key)
        self.ledger.record_revenue(
            run_id=experiment.run_id,
            strategy_id=experiment.strategy_id,
            bucket=TreasuryBucket.GROWTH,
            amount=value,
            currency=currency,
            metadata={"experiment_id": experiment_id, "provider_id": result.external_id},
            idempotency_key=idempotency_key,
        )
        if prior is None:
            self.state.experiments[experiment_id] = replace(
                experiment,
                realized_revenue=experiment.realized_revenue + value,
            )
        return result
