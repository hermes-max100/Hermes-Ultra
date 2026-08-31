from __future__ import annotations

import hermes_ultra as hermes


def test_omh_autonomy_primitives_are_exported_from_package_root():
    expected = (
        "ActionContext",
        "ActionConsequenceClassifier",
        "CapabilityCatalog",
        "CapabilityDiagnostic",
        "CapabilityDiagnosticReport",
        "CapabilityDoctor",
        "CapabilityExpansionController",
        "CapabilityExpansionDecision",
        "CapabilityExpansionEvent",
        "CapabilityObservation",
        "CapabilityProjection",
        "CapabilityProjector",
        "ConsequenceClass",
        "EvidenceState",
        "ProjectedCapability",
        "ProjectionExclusionReason",
        "RuntimeCapabilityDescriptor",
        "RuntimeCapabilityObservation",
        "VerificationHookRegistry",
        "VerificationHookResult",
        "default_runtime_capability_catalog",
    )

    missing = [name for name in expected if not hasattr(hermes, name)]

    assert missing == []
