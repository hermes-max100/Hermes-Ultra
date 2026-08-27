from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .autonomy import ApprovalRegistry
from .contracts import CapabilityResult, FailureClass

MEDIA_STAGES = ("research", "script", "assets", "narration", "subtitles", "render", "qa")


@dataclass(frozen=True)
class MediaJob:
    task_id: str
    objective: str
    audience: str
    source_material: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    brand_constraints: tuple[str, ...] = ()
    publication_intent: bool = False


@dataclass(frozen=True)
class MediaStageResult:
    stage: str
    attempts: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MediaPipelineResult:
    completed_stages: tuple[str, ...]
    stage_results: tuple[MediaStageResult, ...]
    render_complete: bool
    publication_ready: bool
    human_approval_required: bool
    approval_category: str | None


class OpenMontageAdapter:
    """Revenue OS boundary for autonomous media production.

    Rendering completes before publication policy is evaluated. A publication
    approval requirement therefore never blocks research, scripting, assets,
    narration, subtitles, rendering, or QA.
    """

    def __init__(
        self,
        *,
        runner: Callable[[str, MediaJob], object],
        approval_registry: ApprovalRegistry,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._runner = runner
        self._approval_registry = approval_registry
        self.max_attempts = max_attempts

    def _run_stage(self, stage: str, job: MediaJob) -> CapabilityResult[MediaStageResult]:
        last_stderr = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                proc = self._runner(stage, job)
            except OSError as exc:
                last_stderr = str(exc)
                continue
            returncode = int(getattr(proc, "returncode", 1))
            stdout = str(getattr(proc, "stdout", ""))
            stderr = str(getattr(proc, "stderr", ""))
            if returncode == 0:
                return CapabilityResult.success(
                    MediaStageResult(
                        stage=stage,
                        attempts=attempt,
                        stdout=stdout,
                        stderr=stderr,
                    )
                )
            last_stderr = stderr or f"{stage} exited {returncode}"
        return CapabilityResult.failure(
            FailureClass.UPSTREAM_UNAVAILABLE,
            last_stderr or f"{stage} failed",
            recoverable=False,
            metadata={"stage": stage, "attempts": self.max_attempts},
        )

    def run(self, job: MediaJob) -> CapabilityResult[MediaPipelineResult]:
        completed: list[str] = []
        stage_results: list[MediaStageResult] = []
        for stage in MEDIA_STAGES:
            result = self._run_stage(stage, job)
            if not result.ok or result.value is None:
                return CapabilityResult.failure(
                    result.failure_class or FailureClass.UNKNOWN,
                    result.message,
                    recoverable=False,
                    metadata={
                        "completed_stages": tuple(completed),
                        **dict(result.metadata),
                    },
                )
            completed.append(stage)
            stage_results.append(result.value)

        approval_category = None
        human_approval_required = False
        publication_ready = False
        if job.publication_intent:
            decision = self._approval_registry.evaluate("external_communication")
            human_approval_required = decision.human_approval_required
            approval_category = decision.category
            publication_ready = not human_approval_required

        return CapabilityResult.success(
            MediaPipelineResult(
                completed_stages=tuple(completed),
                stage_results=tuple(stage_results),
                render_complete="render" in completed,
                publication_ready=publication_ready,
                human_approval_required=human_approval_required,
                approval_category=approval_category,
            )
        )
