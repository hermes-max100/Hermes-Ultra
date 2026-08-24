from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkMetrics:
    latency_seconds: float
    tool_calls: int
    tokens: int
    success_rate: float
    tests_pass_rate: float
    wrong_file_edit_rate: float
    regression_rate: float
    evidence_complete: bool


@dataclass(frozen=True)
class BenchmarkReport:
    baseline: BenchmarkMetrics
    codebase_memory: BenchmarkMetrics
    graft: BenchmarkMetrics


@dataclass(frozen=True)
class PromotionDecision:
    promoted: bool
    reason: str
    human_approval_required: bool = False


class ProviderRegistry:
    def __init__(self, *, current: str) -> None:
        self.current = current
        self._history: list[str] = []

    @property
    def previous(self) -> str | None:
        return self._history[-1] if self._history else None

    def promote(self, provider: str) -> None:
        if provider == self.current:
            return
        self._history.append(self.current)
        self.current = provider

    def rollback(self) -> str:
        if not self._history:
            return self.current
        self.current = self._history.pop()
        return self.current


class PromotionPolicy:
    def __init__(
        self,
        *,
        min_success_rate: float = 0.95,
        min_tests_pass_rate: float = 1.0,
        max_wrong_file_edit_rate: float = 0.0,
        max_regression_rate: float = 0.0,
        require_evidence_complete: bool = True,
    ) -> None:
        self.min_success_rate = min_success_rate
        self.min_tests_pass_rate = min_tests_pass_rate
        self.max_wrong_file_edit_rate = max_wrong_file_edit_rate
        self.max_regression_rate = max_regression_rate
        self.require_evidence_complete = require_evidence_complete

    def _failure_reason(self, metrics: BenchmarkMetrics) -> str | None:
        if metrics.success_rate < self.min_success_rate:
            return (
                f"success_rate {metrics.success_rate:.3f} below "
                f"{self.min_success_rate:.3f}"
            )
        if metrics.tests_pass_rate < self.min_tests_pass_rate:
            return (
                f"tests_pass_rate {metrics.tests_pass_rate:.3f} below "
                f"{self.min_tests_pass_rate:.3f}"
            )
        if metrics.wrong_file_edit_rate > self.max_wrong_file_edit_rate:
            return (
                f"wrong_file_edit_rate {metrics.wrong_file_edit_rate:.3f} above "
                f"{self.max_wrong_file_edit_rate:.3f}"
            )
        if metrics.regression_rate > self.max_regression_rate:
            return (
                f"regression_rate {metrics.regression_rate:.3f} above "
                f"{self.max_regression_rate:.3f}"
            )
        if self.require_evidence_complete and not metrics.evidence_complete:
            return "evidence_complete is false"
        return None

    def evaluate_and_promote(
        self,
        report: BenchmarkReport,
        registry: ProviderRegistry,
    ) -> PromotionDecision:
        reason = self._failure_reason(report.graft)
        if reason is not None:
            return PromotionDecision(False, reason)

        # Require a material operational advantage in at least one observable
        # efficiency dimension when task quality is not worse.
        quality_not_worse = (
            report.graft.success_rate >= report.codebase_memory.success_rate
            and report.graft.tests_pass_rate >= report.codebase_memory.tests_pass_rate
            and report.graft.regression_rate <= report.codebase_memory.regression_rate
            and report.graft.wrong_file_edit_rate <= report.codebase_memory.wrong_file_edit_rate
        )
        efficiency_better = (
            report.graft.latency_seconds < report.codebase_memory.latency_seconds
            or report.graft.tool_calls < report.codebase_memory.tool_calls
            or report.graft.tokens < report.codebase_memory.tokens
        )
        if not quality_not_worse:
            return PromotionDecision(False, "graft quality regresses versus codebase-memory")
        if not efficiency_better:
            return PromotionDecision(False, "graft has no measured advantage")

        registry.promote("graft")
        return PromotionDecision(
            True,
            "promotion thresholds passed",
            human_approval_required=False,
        )
