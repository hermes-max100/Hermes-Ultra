def test_top_level_package_exports_economic_engine_surface():
    from hermes_ultra import (
        AuthorityPolicy,
        EconomicEngine,
        EconomicMode,
        EconomicOperation,
        EconomicTask,
        FinancialAuthority,
        SafeAdapter,
        ServiceSalesStrategy,
        StripeAdapter,
        TransactionEnvelope,
        TreasuryBucket,
        TreasuryManager,
    )

    assert EconomicEngine
    assert EconomicMode.SIMULATED.value == "SIMULATED"
    assert EconomicOperation.START_SERVICE_SALES.value == "START_SERVICE_SALES"
    assert EconomicTask
    assert TransactionEnvelope
    assert TreasuryBucket.EXPERIMENTS.value == "EXPERIMENTS"
    assert AuthorityPolicy
    assert FinancialAuthority
    assert TreasuryManager
    assert ServiceSalesStrategy
    assert StripeAdapter
    assert SafeAdapter
