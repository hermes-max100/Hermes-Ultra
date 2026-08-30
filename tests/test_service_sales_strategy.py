from decimal import Decimal

from hermes_ultra.economic.contracts import ExperimentStatus
from hermes_ultra.economic.strategies.base import RevenueOpportunity
from hermes_ultra.economic.strategies.service_sales import ServiceSalesStrategy


def test_service_sales_strategy_builds_deterministic_economic_hypothesis():
    opportunity = RevenueOpportunity(
        prospect_id="plumber-42",
        offer="AI receptionist",
        contract_value=Decimal("499.00"),
        estimated_cost=Decimal("49.00"),
        currency="USD",
        evidence=("lead:plumber-42", "pricing:voice-agent"),
    )
    strategy = ServiceSalesStrategy()

    first = strategy.propose(run_id="run-sales-1", opportunity=opportunity)
    second = strategy.propose(run_id="run-sales-1", opportunity=opportunity)

    assert first == second
    assert first.strategy_id == "service-sales"
    assert first.prospect_id == "plumber-42"
    assert first.expected_contract_value == Decimal("499.00")
    assert first.estimated_cost == Decimal("49.00")
    assert first.expected_gross_profit == Decimal("450.00")
    assert first.proposed_action == "prepare_personalized_offer"
    assert first.authority_category == "external_communication"
    assert first.status is ExperimentStatus.PLANNED


def test_service_sales_strategy_has_no_external_execution_surface():
    strategy = ServiceSalesStrategy()

    assert not hasattr(strategy, "send_message")
    assert not hasattr(strategy, "charge_customer")
    assert not hasattr(strategy, "trade")
