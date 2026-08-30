from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ..contracts import CapabilityResult, FailureClass
from .contracts import (
    EconomicOperation,
    EconomicTask,
    ExperimentStatus,
    TreasuryBucket,
    as_decimal,
)
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
        self.service_sales_strategy = ServiceSalesStrategy()

    def run(self, task: EconomicTask | object) -> CapabilityResult:
        if not isinstance(task, EconomicTask):
            return CapabilityResult.failure(
                FailureClass.POLICY_BLOCKED,
                "economic task contract is required",
                recoverable=False,
            )
        try:
            if task.operation is EconomicOperation.START_SERVICE_SALES:
                opportunity = task.payload.get("opportunity")
                if not isinstance(opportunity, RevenueOpportunity):
                    return CapabilityResult.failure(
                        FailureClass.POLICY_BLOCKED,
                        "service-sales task requires a RevenueOpportunity",
                        recoverable=False,
                    )
                value = self.start_service_sales_experiment(
                    self.service_sales_strategy,
                    opportunity,
                    run_id=task.run_id,
                )
                return CapabilityResult.success(value, metadata={"operation": task.operation.value})

            if task.operation is EconomicOperation.STOP_EXPERIMENT:
                experiment_id = task.payload.get("experiment_id")
                if not isinstance(experiment_id, str) or not experiment_id:
                    return CapabilityResult.failure(
                        FailureClass.POLICY_BLOCKED,
                        "stop task requires experiment_id",
                        recoverable=False,
                    )
                value = self.stop_experiment(experiment_id)
                return CapabilityResult.success(value, metadata={"operation": task.operation.value})

            if task.operation is EconomicOperation.RECORD_REVENUE:
                experiment_id = task.payload.get("experiment_id")
                currency = task.payload.get("currency")
                idempotency_key = task.payload.get("idempotency_key")
                amount = task.payload.get("amount")
                if (
                    not isinstance(experiment_id, str)
                    or not experiment_id
                    or not isinstance(currency, str)
                    or not currency
                    or not isinstance(idempotency_key, str)
                    or not idempotency_key
                    or amount is None
                ):
                    return CapabilityResult.failure(
                        FailureClass.POLICY_BLOCKED,
                        "revenue task payload is incomplete",
                        recoverable=False,
                    )
                result = self.record_revenue(
                    experiment_id,
                    amount=amount,
                    currency=currency,
                    idempotency_key=idempotency_key,
                )
                if not result.ok:
                    return CapabilityResult.failure(
                        FailureClass.ADAPTER_REJECTED,
                        "payment adapter rejected revenue event",
                        recoverable=False,
                        metadata={"adapter_status": result.status},
                    )
                return CapabilityResult.success(result, metadata={"operation": task.operation.value})

            return CapabilityResult.failure(
                FailureClass.POLICY_BLOCKED,
                "unsupported economic operation",
                recoverable=False,
            )
        except KeyError:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                "referenced economic state was not found",
                recoverable=False,
            )
        except (TypeError, ValueError):
            return CapabilityResult.failure(
                FailureClass.POLICY_BLOCKED,
                "economic task failed contract validation",
                recoverable=False,
            )
        except RuntimeError:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                "economic execution dependency is not configured",
                recoverable=False,
            )

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
        if value < 0:
            raise ValueError("negative revenue is not allowed")
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
