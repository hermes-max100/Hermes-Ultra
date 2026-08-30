from __future__ import annotations

import hashlib

from .base import RevenueExperiment, RevenueOpportunity


class ServiceSalesStrategy:
    strategy_id = "service-sales"

    def propose(self, *, run_id: str, opportunity: RevenueOpportunity) -> RevenueExperiment:
        identity = "\0".join(
            (
                run_id,
                self.strategy_id,
                opportunity.prospect_id,
                opportunity.offer,
                str(opportunity.contract_value),
                str(opportunity.estimated_cost),
                opportunity.currency,
            )
        )
        experiment_id = "sales_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return RevenueExperiment(
            experiment_id=experiment_id,
            run_id=run_id,
            strategy_id=self.strategy_id,
            prospect_id=opportunity.prospect_id,
            expected_contract_value=opportunity.contract_value,
            estimated_cost=opportunity.estimated_cost,
            expected_gross_profit=opportunity.contract_value - opportunity.estimated_cost,
            currency=opportunity.currency,
            proposed_action="prepare_personalized_offer",
            authority_category="external_communication",
            evidence=opportunity.evidence,
        )
