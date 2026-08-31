from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .capability_projection import ConsequenceClass


@dataclass(frozen=True)
class ActionContext:
    action_category: str
    reversible: bool
    remote: bool = False
    within_authorized_scope: bool = True
    credential_boundary: bool = False
    destructive: bool = False
    external_irreversible_effect: bool = False
    material_spend: bool = False


@dataclass(frozen=True)
class AutonomyDecision:
    human_approval_required: bool
    category: str | None = None
    consequence_class: ConsequenceClass | None = None
    reason: str | None = None


class ActionConsequenceClassifier:
    """Classify concrete action effects without treating tool power as consequence."""

    def classify(self, action: ActionContext) -> ConsequenceClass:
        if (
            not action.reversible
            or action.credential_boundary
            or action.destructive
            or action.external_irreversible_effect
            or action.material_spend
        ):
            return ConsequenceClass.CONSEQUENTIAL
        if action.remote:
            return ConsequenceClass.REVERSIBLE_REMOTE
        return ConsequenceClass.REVERSIBLE_LOCAL


class ApprovalRegistry:
    """Exact-match registry for pre-existing high-consequence categories.

    The registry never infers new approval categories from authentication,
    provider familiarity, health state, or generic risk labels. Action-level
    evaluation may still identify an explicit irreversible effect or missing
    remote authorization scope; those are concrete consequence boundaries,
    not generic tool-risk labels.
    """

    def __init__(self, categories: Iterable[str] = ()) -> None:
        normalized = {category.strip() for category in categories if category.strip()}
        self._categories = frozenset(normalized)

    @property
    def categories(self) -> frozenset[str]:
        return self._categories

    def evaluate(self, action_category: str) -> AutonomyDecision:
        if action_category in self._categories:
            return AutonomyDecision(True, action_category)
        return AutonomyDecision(False, None)

    def evaluate_action(
        self,
        action: ActionContext,
        classifier: ActionConsequenceClassifier | None = None,
    ) -> AutonomyDecision:
        consequence = (classifier or ActionConsequenceClassifier()).classify(action)
        if action.action_category in self._categories:
            return AutonomyDecision(
                True,
                action.action_category,
                consequence,
                "registered_consequential_boundary",
            )
        if consequence is ConsequenceClass.CONSEQUENTIAL:
            return AutonomyDecision(
                True,
                action.action_category,
                consequence,
                "explicit_consequential_effect",
            )
        if consequence is ConsequenceClass.REVERSIBLE_REMOTE and not action.within_authorized_scope:
            return AutonomyDecision(
                True,
                None,
                consequence,
                "authorization_scope_required",
            )
        return AutonomyDecision(
            False,
            None,
            consequence,
            "autonomous_within_existing_scope",
        )
