from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.session_environment import (
    SessionComputeRegistry,
    SessionEnvironment,
    SessionIntegrityError,
)


def test_append_externalizes_redacted_payload_and_keeps_event_log_compact(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-1", evidence_recorder=EvidenceRecorder())

    event = env.append(
        "tool_result",
        {
            "message": "hello world",
            "authorization": "Bearer super-secret-token",
            "nested": {"api_key": "sk-example-secret"},
        },
        metadata={"source": "search"},
        bind_as="latest_result",
    )

    assert event.sequence == 1
    assert event.payload_ref.startswith("sha256:")
    assert env.events_path.exists()
    assert env.payload_path(event.payload_ref).exists()

    event_log = env.events_path.read_text(encoding="utf-8")
    assert "hello world" not in event_log
    assert "super-secret-token" not in event_log

    payload = env.load_payload(event.payload_ref)
    assert payload["message"] == "hello world"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"]["api_key"] == "[REDACTED]"


def test_reopen_rebuilds_workspace_from_append_only_events(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-2")
    first = env.append("note", {"value": 1}, bind_as="answer")
    second = env.append("note", {"value": 2}, bind_as="answer")

    reopened = SessionEnvironment(tmp_path, task_id="task-2")
    workspace = reopened.rebuild_workspace()

    assert workspace == {"answer": second.payload_ref}
    assert first.payload_ref != second.payload_ref
    assert reopened.resolve_binding("answer") == {"value": 2}
    assert tuple(event.sequence for event in reopened.events()) == (1, 2)


def test_payload_tampering_is_detected_before_materialization(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-3")
    event = env.append("note", {"value": "original"})
    payload_path = env.payload_path(event.payload_ref)
    payload_path.write_text(json.dumps({"value": "tampered"}), encoding="utf-8")

    with pytest.raises(SessionIntegrityError, match="payload digest mismatch"):
        env.load_payload(event.payload_ref)


def test_event_sequence_corruption_is_detected(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-4")
    env.append("note", {"value": 1})
    with env.events_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "sequence": 9,
                    "event_type": "note",
                    "payload_ref": "sha256:" + "0" * 64,
                    "recorded_at": "2026-09-01T00:00:00Z",
                    "metadata": {},
                    "binding": None,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )

    with pytest.raises(SessionIntegrityError, match="event sequence discontinuity"):
        env.events()


def test_registered_compute_operation_creates_derived_payload_with_provenance(tmp_path: Path):
    registry = SessionComputeRegistry()
    registry.register("sum_numbers", lambda inputs, params: sum(inputs) + int(params.get("offset", 0)))
    env = SessionEnvironment(tmp_path, task_id="task-5", compute_registry=registry)
    left = env.append("value", 3)
    right = env.append("value", 4)

    derived = env.compute(
        "sum_numbers",
        input_refs=(left.payload_ref, right.payload_ref),
        params={"offset": 2},
        bind_as="total",
    )

    assert env.load_payload(derived.payload_ref) == 9
    assert derived.event_type == "compute"
    assert derived.metadata["operation"] == "sum_numbers"
    assert derived.metadata["input_refs"] == [left.payload_ref, right.payload_ref]
    assert env.resolve_binding("total") == 9

    reopened = SessionEnvironment(tmp_path, task_id="task-5", compute_registry=registry)
    assert reopened.resolve_binding("total") == 9


def test_select_and_project_are_bounded_and_materialize_only_selected_payloads(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-6")
    env.append("research", {"text": "alpha evidence"}, metadata={"source": "a"})
    env.append("research", {"text": "beta evidence"}, metadata={"source": "b"})
    env.append("tool", {"text": "alpha tool result"}, metadata={"source": "c"})

    selected = env.select(event_type="research", query="alpha", limit=1)
    projected = env.project(event_type="research", query="alpha", limit=1)

    assert len(selected) == 1
    assert selected[0].event_type == "research"
    assert selected[0].metadata["source"] == "a"
    assert len(projected) == 1
    assert projected[0].event.sequence == selected[0].sequence
    assert projected[0].payload == {"text": "alpha evidence"}


def test_compute_rejects_unregistered_operation_without_writing_event(tmp_path: Path):
    env = SessionEnvironment(tmp_path, task_id="task-7")
    value = env.append("value", 1)

    with pytest.raises(KeyError, match="unknown compute operation"):
        env.compute("arbitrary_python", input_refs=(value.payload_ref,), params={})

    assert tuple(event.event_type for event in env.events()) == ("value",)
