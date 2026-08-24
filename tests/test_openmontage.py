from __future__ import annotations

from types import SimpleNamespace

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.openmontage import MediaJob, OpenMontageAdapter


STAGES = ("research", "script", "assets", "narration", "subtitles", "render", "qa")


def test_staging_job_runs_all_stages_without_human_approval():
    calls = []

    def runner(stage, job):
        calls.append(stage)
        return SimpleNamespace(returncode=0, stdout=f"{stage}-ok", stderr="")

    adapter = OpenMontageAdapter(runner=runner, approval_registry=ApprovalRegistry())
    job = MediaJob(
        task_id="media-1",
        objective="Create launch video",
        audience="small businesses",
        publication_intent=False,
    )

    result = adapter.run(job)

    assert result.ok
    assert calls == list(STAGES)
    assert result.value.completed_stages == STAGES
    assert result.value.human_approval_required is False
    assert result.value.publication_ready is False


def test_publication_boundary_does_not_stop_rendering():
    calls = []

    def runner(stage, job):
        calls.append(stage)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    registry = ApprovalRegistry({"external_communication"})
    adapter = OpenMontageAdapter(runner=runner, approval_registry=registry)
    job = MediaJob(
        task_id="media-2",
        objective="Create campaign video",
        audience="buyers",
        publication_intent=True,
    )

    result = adapter.run(job)

    assert result.ok
    assert calls == list(STAGES)
    assert result.value.render_complete is True
    assert result.value.human_approval_required is True
    assert result.value.approval_category == "external_communication"
    assert result.value.publication_ready is False


def test_publication_can_be_ready_autonomously_when_category_not_registered():
    def runner(stage, job):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    adapter = OpenMontageAdapter(runner=runner, approval_registry=ApprovalRegistry())
    job = MediaJob(
        task_id="media-3",
        objective="Create internal promo",
        audience="team",
        publication_intent=True,
    )

    result = adapter.run(job)

    assert result.ok
    assert result.value.publication_ready is True
    assert result.value.human_approval_required is False


def test_recoverable_stage_failure_retries_before_blocking():
    attempts = {stage: 0 for stage in STAGES}

    def runner(stage, job):
        attempts[stage] += 1
        if stage == "render" and attempts[stage] == 1:
            return SimpleNamespace(returncode=2, stdout="", stderr="temporary renderer failure")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    adapter = OpenMontageAdapter(
        runner=runner,
        approval_registry=ApprovalRegistry(),
        max_attempts=2,
    )
    job = MediaJob(task_id="media-4", objective="Retry render", audience="users")

    result = adapter.run(job)

    assert result.ok
    assert attempts["render"] == 2
