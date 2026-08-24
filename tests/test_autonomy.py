from __future__ import annotations

from hermes_ultra.autonomy import ApprovalRegistry


def test_ordinary_action_never_requires_approval():
    registry = ApprovalRegistry({"production_deploy", "external_communication"})

    decision = registry.evaluate("code_edit")

    assert decision.human_approval_required is False
    assert decision.category is None


def test_only_registered_high_consequence_category_can_require_approval():
    registry = ApprovalRegistry({"production_deploy"})

    decision = registry.evaluate("production_deploy")

    assert decision.human_approval_required is True
    assert decision.category == "production_deploy"


def test_authentication_does_not_create_approval_category():
    registry = ApprovalRegistry({"production_deploy"})

    decision = registry.evaluate("authenticated_research")

    assert decision.human_approval_required is False
    assert decision.category is None


def test_unknown_risk_label_does_not_expand_registry():
    registry = ApprovalRegistry({"production_deploy"})

    registry.evaluate("unfamiliar_provider")

    assert registry.categories == frozenset({"production_deploy"})
