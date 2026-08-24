from __future__ import annotations

from hermes_ultra.evidence import EvidenceEnvelope, redact_secrets


def test_redaction_removes_known_secret_shapes():
    data = {
        "Authorization": "Bearer abc123",
        "cookie": "auth_token=secret; ct0=xyz",
        "password": "hunter2",
        "message": "safe",
    }

    redacted = redact_secrets(data)
    rendered = repr(redacted)

    assert "abc123" not in rendered
    assert "secret" not in rendered
    assert "hunter2" not in rendered
    assert redacted["message"] == "safe"


def test_redaction_handles_nested_sequences():
    data = {"events": [{"session_id": "sess-123", "detail": "ok"}]}

    redacted = redact_secrets(data)

    assert redacted["events"][0]["session_id"] == "[REDACTED]"
    assert redacted["events"][0]["detail"] == "ok"


def test_approval_defaults_false():
    envelope = EvidenceEnvelope.new("task-1", "agent-reach")

    assert envelope.human_approval_required is False
    assert envelope.approval_category is None
    assert envelope.redactions_applied is True


def test_serialization_is_secret_safe():
    envelope = EvidenceEnvelope.new("task-1", "agent-reach")
    envelope.health = {"token": "super-secret", "status": "ok"}

    serialized = envelope.to_json()

    assert "super-secret" not in serialized
    assert "[REDACTED]" in serialized
