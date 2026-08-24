from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, replace
from typing import Callable, Protocol, Sequence

from .contracts import CapabilityResult, FailureClass

Runner = Callable[..., object]


@dataclass(frozen=True)
class ImpactReport:
    provider: str
    changed: tuple[str, ...] = ()
    matches: tuple[str, ...] = ()
    degraded_context: bool = False


class CodeIntelligenceProvider(Protocol):
    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]: ...


class CodebaseMemoryAdapter:
    def __init__(
        self,
        binary: str = "codebase-memory",
        *,
        repo_path: str = ".",
        runner: Runner = subprocess.run,
    ) -> None:
        self.binary = binary
        self.repo_path = repo_path
        self._runner = runner

    def _run(self, args: Sequence[str]) -> CapabilityResult[str]:
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing code intelligence binary: {self.binary}",
                recoverable=True,
            )
        try:
            proc = self._runner(
                [self.binary, *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                "code intelligence command timed out",
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
                stderr.strip() or f"code intelligence exited {returncode}",
                recoverable=True,
                metadata={"returncode": returncode},
            )
        return CapabilityResult.success(stdout)

    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]:
        changed = tuple(changed_paths_or_symbols)
        result = self._run(["impact", "--repo", self.repo_path, *changed])
        if not result.ok:
            return CapabilityResult.failure(
                result.failure_class or FailureClass.UNKNOWN,
                result.message,
                recoverable=result.recoverable,
                metadata=result.metadata,
            )
        matches = tuple(line for line in (result.value or "").splitlines() if line.strip())
        return CapabilityResult.success(
            ImpactReport(provider="codebase-memory", changed=changed, matches=matches)
        )

    def health(self) -> CapabilityResult[str]:
        return self._run(["health"])


class NativeRepoSearchAdapter:
    def __init__(self, repo_path: str = ".", *, runner: Runner = subprocess.run) -> None:
        self.repo_path = repo_path
        self._runner = runner

    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]:
        changed = tuple(changed_paths_or_symbols)
        if not changed:
            return CapabilityResult.success(ImpactReport(provider="native-repo-search"))
        pattern = "|".join(changed)
        try:
            proc = self._runner(
                ["git", "-C", self.repo_path, "grep", "-nE", pattern, "--", "."],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                "native repository search timed out",
                recoverable=False,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                str(exc),
                recoverable=False,
            )
        returncode = int(getattr(proc, "returncode", 1))
        stdout = str(getattr(proc, "stdout", ""))
        stderr = str(getattr(proc, "stderr", ""))
        # git grep uses 1 for no matches; that is still a valid search result.
        if returncode not in (0, 1):
            return CapabilityResult.failure(
                FailureClass.UNKNOWN,
                stderr.strip() or f"git grep exited {returncode}",
                recoverable=False,
            )
        matches = tuple(line for line in stdout.splitlines() if line.strip())
        return CapabilityResult.success(
            ImpactReport(provider="native-repo-search", changed=changed, matches=matches)
        )

    def health(self) -> CapabilityResult[str]:
        return CapabilityResult.success("native-repo-search")


class CodeIntelligenceRouter:
    def __init__(self, *, primary: CodeIntelligenceProvider, fallback: CodeIntelligenceProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]:
        primary_result = self.primary.impact_analysis(changed_paths_or_symbols)
        if primary_result.ok:
            return primary_result

        fallback_result = self.fallback.impact_analysis(changed_paths_or_symbols)
        if fallback_result.ok and fallback_result.value is not None:
            report = replace(fallback_result.value, degraded_context=True)
            return CapabilityResult.success(
                report,
                metadata={
                    "primary_failure": (
                        primary_result.failure_class.value
                        if primary_result.failure_class is not None
                        else FailureClass.UNKNOWN.value
                    ),
                    "primary_message": primary_result.message,
                },
            )

        return CapabilityResult.failure(
            fallback_result.failure_class or primary_result.failure_class or FailureClass.UNKNOWN,
            fallback_result.message or primary_result.message,
            recoverable=False,
            metadata={"primary_failure": primary_result.message},
        )
