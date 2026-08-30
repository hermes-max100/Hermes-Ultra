from decimal import Decimal

from hermes_ultra.contracts import CapabilityResult, FailureClass
from hermes_ultra.economic.contracts import EconomicOperation, EconomicTask
from hermes_ultra.economic.engine import EconomicEngine
from hermes_ultra.economic.ledger import EconomicLedger
from hermes_ultra.economic.state import EconomicState
from hermes_ultra.economic.contracts import EconomicMode
from hermes_ultra.economic.adapters.mock_stripe import MockStripeAdapter
from hermes_ultra.economic.strategies.base import RevenueOpportunity
from hermes_ultra.orchestrator import HermesUltraOrchestrator


def test_economic_failure_classes_are_explicit():
    assert FailureClass.AUTHORITY_REQUIRED.value == "AUTHORITY_REQUIRED"
    assert FailureClass.INSUFFICIENT_FUNDS.value == "INSUFFICIENT_FUNDS"
    assert FailureClass.DUPLICATE_TRANSACTION.value == "DUPLICATE_TRANSACTION"
    assert FailureClass.TRANSACTION_EXPIRED.value == "TRANSACTION_EXPIRED"
    assert FailureClass.ADAPTER_REJECTED.value == "ADAPTER_REJECTED"


def test_orchestrator_fails_closed_when_economic_engine_is_missing():
    orchestrator = HermesUltraOrchestrator()
    task = EconomicTask(
        task_id="econ-missing",
        run_id="run-missing",
        operation=EconomicOperation.STOP_EXPERIMENT,
        payload={"experiment_id": "missing"},
    )

    result = orchestrator.run_economic_task(task)

    assert result.ok is False
    assert result.failure_class is FailureClass.DEPENDENCY_MISSING
    assert result.blocking is True


def test_real_economic_engine_dispatches_service_sales_through_hermes_and_records_evidence(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        engine = EconomicEngine(
            state=EconomicState(mode=EconomicMode.SIMULATED),
            ledger=ledger,
            payment_adapter=MockStripeAdapter(),
        )
        orchestrator = HermesUltraOrchestrator(economic_engine=engine)
        task = EconomicTask(
            task_id="econ-sales-1",
            run_id="run-sales-1",
            operation=EconomicOperation.START_SERVICE_SALES,
            payload={
                "opportunity": RevenueOpportunity(
                    prospect_id="plumber-1",
                    offer="AI receptionist",
                    contract_value=Decimal("499"),
                    estimated_cost=Decimal("49"),
                    evidence=("lead:1",),
                )
            },
        )

        result = orchestrator.run_economic_task(task)

    assert result.ok is True
    assert result.value.strategy_id == "service-sales"
    assert result.value.run_id == "run-sales-1"
    record = orchestrator.evidence_recorder.records[-1]
    assert record["task_id"] == "econ-sales-1"
    assert record["capability"] == "economic-engine"
    assert record["status"] == "success"
    assert record["health"]["operation"] == "START_SERVICE_SALES"


def test_economic_engine_failure_is_normalized_and_evidence_redacts_metadata():
    class FailingEngine:
        def run(self, task):
            return CapabilityResult.failure(
                FailureClass.AUTHORITY_REQUIRED,
                "financial authority required",
                recoverable=False,
                metadata={"private_key": "must-not-survive", "policy_revision": "v1"},
            )

    orchestrator = HermesUltraOrchestrator(economic_engine=FailingEngine())
    task = EconomicTask(
        task_id="econ-denied",
        run_id="run-denied",
        operation=EconomicOperation.STOP_EXPERIMENT,
        payload={"experiment_id": "exp-1"},
    )

    result = orchestrator.run_economic_task(task)

    assert result.ok is False
    assert result.failure_class is FailureClass.AUTHORITY_REQUIRED
    record = orchestrator.evidence_recorder.records[-1]
    assert record["failure_class"] == "AUTHORITY_REQUIRED"
    assert record["health"]["metadata"]["private_key"] == "[REDACTED]"
    assert record["health"]["metadata"]["policy_revision"] == "v1"


def test_economic_engine_invalid_task_payload_returns_policy_failure_not_exception(tmp_path):
    with EconomicLedger(tmp_path / "economic.sqlite3") as ledger:
        engine = EconomicEngine(
            state=EconomicState(mode=EconomicMode.SIMULATED),
            ledger=ledger,
            payment_adapter=MockStripeAdapter(),
        )
        task = EconomicTask(
            task_id="econ-invalid",
            run_id="run-invalid",
            operation=EconomicOperation.START_SERVICE_SALES,
            payload={"opportunity": "model-invented-payload"},
        )

        result = engine.run(task)

    assert result.ok is False
    assert result.failure_class is FailureClass.POLICY_BLOCKED
