from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .contracts import CapabilityResult, FailureClass

Runner = Callable[..., object]


@dataclass(frozen=True)
class ImpactReport:
    provider: str
    changed: tuple[str, ...] = ()
    matches: tuple[str, ...] = ()
    degraded_context: bool = False
    payload: object | None = None


class CodeIntelligenceProvider(Protocol):
    def index_repository(self) -> CapabilityResult[object]: ...
    def lookup_symbol(self, symbol: str) -> CapabilityResult[object]: ...
    def find_callers(self, symbol: str) -> CapabilityResult[object]: ...
    def find_dependencies(self, symbol: str) -> CapabilityResult[object]: ...
    def find_routes(self, pattern: str) -> CapabilityResult[object]: ...
    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]: ...
    def health(self) -> CapabilityResult[object]: ...


class CodebaseMemoryAdapter:
    """One-shot CLI adapter for DeusData/codebase-memory-mcp.

    The adapter deliberately uses upstream `cli` mode instead of managing the
    long-lived coordination daemon. Every query is local and bounded, and the
    Hermes-facing interface stays stable if upstream implementation details move.
    """

    def __init__(
        self,
        binary: str = "codebase-memory-mcp",
        *,
        repo_path: str = ".",
        project: str | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self.binary = binary
        self.repo_path = repo_path
        self.project = project or Path(repo_path).resolve().name
        self._runner = runner

    def _run_raw(self, args: Sequence[str]) -> CapabilityResult[str]:
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
                "Codebase Memory command timed out",
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
                stderr.strip() or f"Codebase Memory exited {returncode}",
                recoverable=True,
                metadata={"returncode": returncode},
            )
        return CapabilityResult.success(stdout)

    def _cli(self, tool: str, *flags: str) -> CapabilityResult[object]:
        result = self._run_raw(["cli", "--json", tool, *flags])
        if not result.ok:
            return CapabilityResult.failure(
                result.failure_class or FailureClass.UNKNOWN,
                result.message,
                recoverable=result.recoverable,
                metadata=result.metadata,
            )
        try:
            payload = json.loads(result.value or "null")
        except json.JSONDecodeError as exc:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                f"Codebase Memory returned malformed JSON: {exc}",
                recoverable=True,
            )
        return CapabilityResult.success(payload)

    def index_repository(self) -> CapabilityResult[object]:
        return self._cli("index_repository", "--repo-path", self.repo_path)

    def lookup_symbol(self, symbol: str) -> CapabilityResult[object]:
        return self._cli(
            "search_graph",
            "--project", self.project,
            "--name-pattern", symbol,
            "--label", "Function",
        )

    def find_callers(self, symbol: str) -> CapabilityResult[object]:
        return self._cli(
            "trace_path",
            "--project", self.project,
            "--function-name", symbol,
            "--direction", "in",
        )

    def find_dependencies(self, symbol: str) -> CapabilityResult[object]:
        return self._cli(
            "trace_path",
            "--project", self.project,
            "--function-name", symbol,
            "--direction", "out",
        )

    def find_routes(self, pattern: str) -> CapabilityResult[object]:
        return self._cli(
            "search_graph",
            "--project", self.project,
            "--name-pattern", pattern,
            "--label", "Route",
        )

    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]:
        changed = tuple(changed_paths_or_symbols)
        result = self._cli("detect_changes", "--project", self.project)
        if not result.ok:
            return CapabilityResult.failure(
                result.failure_class or FailureClass.UNKNOWN,
                result.message,
                recoverable=result.recoverable,
                metadata=result.metadata,
            )
        return CapabilityResult.success(
            ImpactReport(
                provider="codebase-memory",
                changed=changed,
                payload=result.value,
            )
        )

    def health(self) -> CapabilityResult[object]:
        # list_projects has no input schema and is a cheap one-shot readiness check.
        return self._cli("list_projects")


class NativeRepoSearchAdapter:
    def __init__(self, repo_path: str = ".", *, runner: Runner = subprocess.run) -> None:
        self.repo_path = repo_path
        self._runner = runner

    def index_repository(self) -> CapabilityResult[object]:
        return CapabilityResult.success({"provider": "native-repo-search", "indexed": False})

    def lookup_symbol(self, symbol: str) -> CapabilityResult[object]:
        return self._search((symbol,))

    def find_callers(self, symbol: str) -> CapabilityResult[object]:
        return self._search((symbol,))

    def find_dependencies(self, symbol: str) -> CapabilityResult[object]:
        return self._search((symbol,))

    def find_routes(self, pattern: str) -> CapabilityResult[object]:
        return self._search((pattern,))

    def _search(self, terms: Sequence[str]) -> CapabilityResult[ImpactReport]:
        changed = tuple(terms)
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

    def impact_analysis(self, changed_paths_or_symbols: Sequence[str]) -> CapabilityResult[ImpactReport]:
        return self._search(changed_paths_or_symbols)

    def health(self) -> CapabilityResult[object]:
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
