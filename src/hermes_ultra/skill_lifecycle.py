from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .contracts import CapabilityResult, FailureClass

Runner = Callable[..., object]
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class LifecycleState(str, Enum):
    DISCOVERED = "discovered"
    QUARANTINED = "quarantined"
    CANDIDATE = "candidate"
    TRUSTED = "trusted"
    INSTALLED_DISABLED = "installed_disabled"
    CANARY = "canary"
    ACTIVE = "active"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class DiscoverySource:
    name: str
    repository: str
    discovery_only: bool = True
    auto_install: bool = False


DEFAULT_DISCOVERY_SOURCES = (
    DiscoverySource("awesome-codex-skills", "https://github.com/composio-community/awesome-codex-skills"),
    DiscoverySource("awesome-codex-subagents", "https://github.com/VoltAgent/awesome-codex-subagents"),
    DiscoverySource("awesome-mcp-servers", "https://github.com/punkpeye/awesome-mcp-servers"),
    DiscoverySource("awesome", "https://github.com/sindresorhus/awesome"),
    DiscoverySource("skill-validator", "https://github.com/agent-ecosystem/skill-validator"),
    DiscoverySource("coder-eval", "https://github.com/UiPath/coder_eval"),
    DiscoverySource("horizon", "https://github.com/Thysrael/Horizon"),
    DiscoverySource("notebooklm-py", "https://github.com/teng-lin/notebooklm-py"),
    DiscoverySource("skill-manager", "https://github.com/abubakarsiddik31/skill-manager"),
    DiscoverySource("all-mcp-servers", "https://www.allmcpservers.com/"),
)


@dataclass(frozen=True)
class Provenance:
    repository: str
    commit_sha: str
    license: str
    discovered_from: str

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("repository is required")
        if not _COMMIT_RE.fullmatch(self.commit_sha):
            raise ValueError("commit_sha must be a full 40-character hexadecimal SHA")
        if not self.license.strip():
            raise ValueError("license is required")
        if not self.discovered_from.strip():
            raise ValueError("discovered_from is required")


@dataclass(frozen=True)
class AuthorityProfile:
    network: bool = False
    filesystem_read: bool = False
    filesystem_write: bool = False
    shell: bool = False
    git_write: bool = False
    credential_access: bool = False
    external_send: bool = False
    financial: bool = False

    @property
    def consequential(self) -> bool:
        return any((self.git_write, self.credential_access, self.external_send, self.financial))


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    capabilities: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    outputs: frozenset[str] = frozenset()

    @property
    def signature(self) -> frozenset[str]:
        return frozenset(
            {*(f"cap:{item}" for item in self.capabilities),
             *(f"tool:{item}" for item in self.tools),
             *(f"out:{item}" for item in self.outputs)}
        )


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    name: str
    provenance: Provenance
    authority: AuthorityProfile
    capability: CapabilityDescriptor
    state: LifecycleState = LifecycleState.CANDIDATE


@dataclass(frozen=True)
class ValidationReport:
    structural: bool
    links: bool
    contamination: bool
    secret_scan: bool
    dependency_scan: bool
    license_check: bool
    provenance_check: bool
    permissions_declared: bool
    evidence_contract: bool
    rollback_defined: bool

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(name for name, value in asdict(self).items() if not value)

    @property
    def passed(self) -> bool:
        return not self.failed_gates


@dataclass(frozen=True)
class ExternalToolResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class EvaluationMetrics:
    score: float
    success_rate: float
    tests_pass_rate: float
    wrong_file_edit_rate: float
    regression_rate: float
    evidence_complete: bool
    latency_seconds: float
    tool_calls: float
    tokens: float

    def __post_init__(self) -> None:
        for name in ("score", "success_rate", "tests_pass_rate", "wrong_file_edit_rate", "regression_rate"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        for name in ("latency_seconds", "tool_calls", "tokens"):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class EvaluationReport:
    baseline: EvaluationMetrics
    candidate: EvaluationMetrics
    evaluator: str
    evidence_uri: str


@dataclass(frozen=True)
class DeduplicationDecision:
    blocked: bool
    review_required: bool
    overlap_score: float
    nearest_capability_id: str | None = None


class CapabilityDeduplicator:
    def __init__(self, *, duplicate_threshold: float = 0.90, review_threshold: float = 0.60) -> None:
        if not 0.0 <= review_threshold <= duplicate_threshold <= 1.0:
            raise ValueError("require 0 <= review_threshold <= duplicate_threshold <= 1")
        self.duplicate_threshold = duplicate_threshold
        self.review_threshold = review_threshold

    @staticmethod
    def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    def compare(
        self,
        candidate: CapabilityDescriptor,
        existing: Iterable[CapabilityDescriptor],
    ) -> DeduplicationDecision:
        nearest_id: str | None = None
        nearest_score = 0.0
        for descriptor in existing:
            score = self._jaccard(candidate.signature, descriptor.signature)
            if score > nearest_score:
                nearest_score = score
                nearest_id = descriptor.capability_id
        return DeduplicationDecision(
            blocked=nearest_score >= self.duplicate_threshold,
            review_required=self.review_threshold <= nearest_score < self.duplicate_threshold,
            overlap_score=nearest_score,
            nearest_capability_id=nearest_id,
        )


@dataclass(frozen=True)
class PromotionDecision:
    promoted: bool
    target_state: LifecycleState
    reason: str
    activation_allowed: bool = False


class PromotionPolicy:
    def __init__(
        self,
        *,
        min_success_rate: float = 0.95,
        min_tests_pass_rate: float = 1.0,
        max_wrong_file_edit_rate: float = 0.0,
        max_regression_rate: float = 0.0,
    ) -> None:
        self.min_success_rate = min_success_rate
        self.min_tests_pass_rate = min_tests_pass_rate
        self.max_wrong_file_edit_rate = max_wrong_file_edit_rate
        self.max_regression_rate = max_regression_rate

    def evaluate(
        self,
        *,
        candidate: SkillCandidate,
        validation: ValidationReport,
        evaluation: EvaluationReport,
        dedupe: DeduplicationDecision | None,
    ) -> PromotionDecision:
        if candidate.state is not LifecycleState.CANDIDATE:
            return PromotionDecision(False, candidate.state, "candidate is not in candidate state")
        if not validation.passed:
            return PromotionDecision(
                False,
                LifecycleState.CANDIDATE,
                "validation failed: " + ", ".join(validation.failed_gates),
            )
        if dedupe is not None and dedupe.blocked:
            return PromotionDecision(False, LifecycleState.CANDIDATE, "duplicate capability blocked")
        if dedupe is not None and dedupe.review_required:
            return PromotionDecision(False, LifecycleState.CANDIDATE, "capability overlap requires review")

        baseline = evaluation.baseline
        metrics = evaluation.candidate
        failures: list[str] = []
        if metrics.success_rate < self.min_success_rate:
            failures.append("success_rate")
        if metrics.tests_pass_rate < self.min_tests_pass_rate:
            failures.append("tests_pass_rate")
        if metrics.wrong_file_edit_rate > self.max_wrong_file_edit_rate:
            failures.append("wrong_file_edit_rate")
        if metrics.regression_rate > self.max_regression_rate:
            failures.append("regression_rate")
        if not metrics.evidence_complete:
            failures.append("evidence_complete")
        if failures:
            return PromotionDecision(
                False,
                LifecycleState.CANDIDATE,
                "evaluation thresholds failed: " + ", ".join(failures),
            )

        quality_not_worse = (
            metrics.success_rate >= baseline.success_rate
            and metrics.tests_pass_rate >= baseline.tests_pass_rate
            and metrics.wrong_file_edit_rate <= baseline.wrong_file_edit_rate
            and metrics.regression_rate <= baseline.regression_rate
        )
        if not quality_not_worse or metrics.score <= baseline.score:
            return PromotionDecision(
                False,
                LifecycleState.CANDIDATE,
                "candidate must strictly improve score without quality regression",
            )

        return PromotionDecision(
            True,
            LifecycleState.TRUSTED,
            "all validation and evaluation gates passed",
            activation_allowed=False,
        )


class SkillValidatorAdapter:
    def __init__(self, binary: str = "skill-validator", *, runner: Runner = subprocess.run) -> None:
        self.binary = binary
        self._runner = runner

    def validate(self, path: str | Path) -> CapabilityResult[ExternalToolResult]:
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing skill validator binary: {self.binary}",
                recoverable=True,
            )
        command = [self.binary, "check", "--strict", str(path)]
        try:
            proc = self._runner(command, text=True, capture_output=True, check=False, timeout=180)
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(FailureClass.TIMEOUT, "skill validation timed out", recoverable=True)
        except OSError as exc:
            return CapabilityResult.failure(FailureClass.UPSTREAM_UNAVAILABLE, str(exc), recoverable=True)
        result = ExternalToolResult(
            command=tuple(command),
            returncode=int(getattr(proc, "returncode", 1)),
            stdout=str(getattr(proc, "stdout", "")),
            stderr=str(getattr(proc, "stderr", "")),
        )
        if not result.passed:
            return CapabilityResult.failure(
                FailureClass.TEST_FAILED,
                "skill-validator rejected candidate",
                recoverable=False,
                metadata={"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
            )
        return CapabilityResult.success(result)


class CoderEvalAdapter:
    def __init__(self, binary: str = "coder-eval", *, runner: Runner = subprocess.run) -> None:
        self.binary = binary
        self._runner = runner

    def _invoke(self, action: str, task: str | Path) -> CapabilityResult[ExternalToolResult]:
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing coder-eval binary: {self.binary}",
                recoverable=True,
            )
        command = [self.binary, action, str(task)]
        env = dict(os.environ)
        env["TELEMETRY_ENABLED"] = "false"
        try:
            proc = self._runner(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=900 if action == "run" else 180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(FailureClass.TIMEOUT, f"coder-eval {action} timed out", recoverable=True)
        except OSError as exc:
            return CapabilityResult.failure(FailureClass.UPSTREAM_UNAVAILABLE, str(exc), recoverable=True)
        result = ExternalToolResult(
            command=tuple(command),
            returncode=int(getattr(proc, "returncode", 1)),
            stdout=str(getattr(proc, "stdout", "")),
            stderr=str(getattr(proc, "stderr", "")),
        )
        if not result.passed:
            failure = FailureClass.BENCHMARK_REGRESSION if action == "run" else FailureClass.TEST_FAILED
            return CapabilityResult.failure(
                failure,
                f"coder-eval {action} rejected candidate",
                recoverable=False,
                metadata={"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
            )
        return CapabilityResult.success(result)

    def plan(self, task: str | Path) -> CapabilityResult[ExternalToolResult]:
        return self._invoke("plan", task)

    def run(self, task: str | Path) -> CapabilityResult[ExternalToolResult]:
        return self._invoke("run", task)


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, frozenset):
        return sorted(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class LifecycleReceipt:
    candidate_id: str
    name: str
    from_state: LifecycleState
    to_state: LifecycleState
    timestamp: str
    reason: str
    provenance: Provenance
    authority: AuthorityProfile
    receipt_hash: str

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "provenance": _jsonable(self.provenance),
            "authority": _jsonable(self.authority),
        }

    @staticmethod
    def _hash(payload: Mapping[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "receipt_hash": self.receipt_hash}

    def verify(self) -> bool:
        return self._hash(self.unsigned_dict()) == self.receipt_hash

    def verify_payload(self, payload: Mapping[str, object]) -> bool:
        unsigned = {key: value for key, value in payload.items() if key != "receipt_hash"}
        return self._hash(unsigned) == self.receipt_hash


class ImmutableReceiptStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def persist(self, receipt: LifecycleReceipt) -> Path:
        if not receipt.verify():
            raise ValueError("receipt hash verification failed")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{receipt.receipt_hash}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt.to_dict(), handle, sort_keys=True, indent=2)
            handle.write("\n")
        return path


class LifecycleController:
    _LEGAL = {
        LifecycleState.DISCOVERED: {LifecycleState.QUARANTINED},
        LifecycleState.QUARANTINED: {LifecycleState.CANDIDATE},
        LifecycleState.CANDIDATE: {LifecycleState.TRUSTED},
        LifecycleState.TRUSTED: {LifecycleState.INSTALLED_DISABLED},
        LifecycleState.INSTALLED_DISABLED: {LifecycleState.CANARY},
        LifecycleState.CANARY: {LifecycleState.ACTIVE, LifecycleState.ROLLED_BACK},
        LifecycleState.ACTIVE: {LifecycleState.ROLLED_BACK},
        LifecycleState.ROLLED_BACK: {LifecycleState.INSTALLED_DISABLED},
    }

    def __init__(self, *, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or self._utc_now

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def transition(
        self,
        candidate: SkillCandidate,
        target: LifecycleState,
        *,
        review_approved: bool = False,
        authority_approved: bool = False,
        canary_passed: bool = False,
        rollback_ready: bool = False,
        reason: str = "policy transition",
    ) -> tuple[SkillCandidate, LifecycleReceipt]:
        allowed = self._LEGAL.get(candidate.state, set())
        if target not in allowed:
            raise ValueError(f"illegal lifecycle transition: {candidate.state.value} -> {target.value}")

        if target is LifecycleState.INSTALLED_DISABLED and not review_approved:
            raise PermissionError("review approval is required before installation")
        if target is LifecycleState.CANARY:
            if not review_approved:
                raise PermissionError("review approval is required before canary")
            if candidate.authority.consequential and not authority_approved:
                raise PermissionError("consequential authority requires explicit approval")
        if target is LifecycleState.ACTIVE:
            if not canary_passed:
                raise PermissionError("canary pass is required before activation")
            if not rollback_ready:
                raise PermissionError("rollback readiness is required before activation")

        timestamp = self._clock()
        unsigned = {
            "candidate_id": candidate.candidate_id,
            "name": candidate.name,
            "from_state": candidate.state.value,
            "to_state": target.value,
            "timestamp": timestamp,
            "reason": reason,
            "provenance": _jsonable(candidate.provenance),
            "authority": _jsonable(candidate.authority),
        }
        receipt_hash = LifecycleReceipt._hash(unsigned)
        receipt = LifecycleReceipt(
            candidate_id=candidate.candidate_id,
            name=candidate.name,
            from_state=candidate.state,
            to_state=target,
            timestamp=timestamp,
            reason=reason,
            provenance=candidate.provenance,
            authority=candidate.authority,
            receipt_hash=receipt_hash,
        )
        return replace(candidate, state=target), receipt


class CandidatePromotionPipeline:
    """Fail-closed, evidence-backed promotion from candidate to trusted.

    Discovery sources never confer trust. Installation and activation are deliberately
    separate lifecycle transitions so a successful evaluation cannot silently grant
    runtime authority.
    """

    def __init__(
        self,
        *,
        policy: PromotionPolicy | None = None,
        deduplicator: CapabilityDeduplicator | None = None,
    ) -> None:
        self.policy = policy or PromotionPolicy()
        self.deduplicator = deduplicator or CapabilityDeduplicator()

    def evaluate(
        self,
        *,
        candidate: SkillCandidate,
        validation: ValidationReport,
        evaluation: EvaluationReport,
        existing_capabilities: Sequence[CapabilityDescriptor] = (),
    ) -> PromotionDecision:
        dedupe = self.deduplicator.compare(candidate.capability, existing_capabilities)
        return self.policy.evaluate(
            candidate=candidate,
            validation=validation,
            evaluation=evaluation,
            dedupe=dedupe,
        )
