from __future__ import annotations

from .contracts import OrcaPolicyDecision

DEFAULT_ALLOWED_ACTIONS = frozenset(
    {
        "benchmark",
        "browser_dev",
        "build",
        "code_edit",
        "dependency_inspect",
        "documentation",
        "git_commit",
        "git_diff",
        "lint",
        "repo_search",
        "static_analysis",
        "test",
    }
)


class OrcaAuthorityPolicy:
    """Fail-closed authority boundary for the Orca execution plane.

    Orca is a developer execution substrate. Unknown or consequential action
    categories are denied here rather than inferred as safe.
    """

    def __init__(self, allowed_actions: frozenset[str] = DEFAULT_ALLOWED_ACTIONS) -> None:
        self._allowed_actions = frozenset(allowed_actions)

    @property
    def allowed_actions(self) -> frozenset[str]:
        return self._allowed_actions

    def evaluate(self, action_category: str) -> OrcaPolicyDecision:
        normalized = action_category.strip()
        if normalized in self._allowed_actions:
            return OrcaPolicyDecision(True, normalized, "allowed developer action")
        return OrcaPolicyDecision(
            False,
            normalized,
            "Orca has no authority for this action category",
        )
