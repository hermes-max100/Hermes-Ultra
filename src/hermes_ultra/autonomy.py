from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AutonomyDecision:
    human_approval_required: bool
    category: str | None = None


class ApprovalRegistry:
    """Exact-match registry for pre-existing high-consequence categories.

    The registry never infers new approval categories from authentication,
    provider familiarity, health state, or generic risk labels.
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
