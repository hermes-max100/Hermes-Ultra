from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .contracts import CapabilityResult, FailureClass

Runner = Callable[..., object]


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    task: str
    repo_path: str


@dataclass(frozen=True)
class BenchmarkObservation:
    provider: str
    case: str
    latency_seconds: float
    tool_calls: float
    tokens: float
    success: bool
    tests_passed: bool
    wrong_file_edit: bool
    regression: bool
    evidence_complete: bool


@dataclass(frozen=True)
class BenchmarkMetrics:
    latency_seconds: float
    tool_calls: float
    tokens: float
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


class GraftAdapter:
    """Native CLI boundary for NanoNets Graft structural context operations."""

    def __init__(
        self,
        binary: str = "graft",
        *,
        runner: Runner = subprocess.run,
    ) -> None:
        self.binary = binary
        self._runner = runner

    def _run(
        self,
        args: Sequence[str],
        *,
        expect_json: bool = False,
        timeout: int = 120,
    ) -> CapabilityResult[object]:
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing Graft binary: {self.binary}",
                recoverable=True,
            )
        try:
            proc = self._runner(
                [self.binary, *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                "Graft command timed out",
                recoverable=True,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                str(exc),
                recoverable=True,
            )
        returncode = int(getattr(proc, "returncode", 1))
        stdout = str(getattr(proc, "stdout", ""))
        stderr = str(getattr(proc, "stderr", ""))
        if returncode != 0:
            return CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                stderr.strip() or f"Graft exited {returncode}",
                recoverable=True,
                metadata={"returncode": returncode},
            )
        if not expect_json:
            return CapabilityResult.success(stdout)
        try:
            payload = json.loads(stdout or "null")
        except json.JSONDecodeError as exc:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                f"Graft returned malformed JSON: {exc}",
                recoverable=True,
            )
        return CapabilityResult.success(payload)

    def build(self, repo_path: str) -> CapabilityResult[object]:
        return self._run(["build", repo_path], timeout=300)

    def ask(self, task: str, repo_path: str) -> CapabilityResult[object]:
        return self._run(["ask", task, repo_path, "--json"], expect_json=True)

    def check(self, repo_path: str) -> CapabilityResult[object]:
        return self._run(["check", repo_path, "--json"], expect_json=True)

    def callers(
        self,
        symbol: str,
        repo_path: str,
        *,
        direction: str = "in",
    ) -> CapabilityResult[object]:
        if direction not in {"in", "out"}:
            raise ValueError("Graft callers direction must be in or out")
        args = ["callers", symbol, repo_path]
        if direction == "out":
            args.extend(["--direction", "out"])
        return self._run(args)


class BenchmarkRunner:
    """Runs identical cases against baseline, Codebase Memory, and Graft.

    The injected executor owns the actual agent invocation and measurement. This
    runner owns experiment symmetry and aggregation, preventing providers from
    silently receiving different task sets.
    """

    PROVIDERS = ("baseline", "codebase-memory", "graft")

    def __init__(
        self,
        execute: Callable[[str, BenchmarkCase], BenchmarkObservation],
    ) -> None:
        self._execute = execute

    @staticmethod
    def _aggregate(observations: Sequence[BenchmarkObservation]) -> BenchmarkMetrics:
        if not observations:
            raise ValueError("benchmark provider has no observations")
        n = len(observations)
        return BenchmarkMetrics(
            latency_seconds=sum(item.latency_seconds for item in observations) / n,
            tool_calls=sum(item.tool_calls for item in observations) / n,
            tokens=sum(item.tokens for item in observations) / n,
            success_rate=sum(item.success for item in observations) / n,
            tests_pass_rate=sum(item.tests_passed for item in observations) / n,
            wrong_file_edit_rate=sum(item.wrong_file_edit for item in observations) / n,
            regression_rate=sum(item.regression for item in observations) / n,
            evidence_complete=all(item.evidence_complete for item in observations),
        )

    def run(self, cases: Iterable[BenchmarkCase]) -> BenchmarkReport:
        case_list = tuple(cases)
        if not case_list:
            raise ValueError("at least one benchmark case is required")
        grouped: dict[str, list[BenchmarkObservation]] = {
            provider: [] for provider in self.PROVIDERS
        }
        for case in case_list:
            for provider in self.PROVIDERS:
                observation = self._execute(provider, case)
                if observation.provider != provider:
                    raise ValueError(
                        f"executor returned provider {observation.provider!r} for {provider!r}"
                    )
                if observation.case != case.name:
                    raise ValueError(
                        f"executor returned case {observation.case!r} for {case.name!r}"
                    )
                grouped[provider].append(observation)
        return BenchmarkReport(
            baseline=self._aggregate(grouped["baseline"]),
            codebase_memory=self._aggregate(grouped["codebase-memory"]),
            graft=self._aggregate(grouped["graft"]),
        )


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
