from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

_SECRET_KEY_PARTS = (
    "authorization",
    "token",
    "cookie",
    "password",
    "passwd",
    "session",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "signing_key",
    "seed_phrase",
    "recovery_phrase",
    "mnemonic",
)

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
_COOKIE_RE = re.compile(r"(?i)\b(auth_token|ct0|sessionid|session_id)=([^;\s]+)")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<key>[A-Za-z0-9_.-]*(?:"
    r"api[_-]?key|client[_-]?secret|secret[_-]?access[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|authorization|auth[_-]?token|token|"
    r"password|passwd|private[_-]?key|signing[_-]?key|seed[_-]?phrase|"
    r"recovery[_-]?phrase|mnemonic|cookie|session(?:[_-]?id)?"
    r")[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s;,]+)"
)
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?"
    r"-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
_OPENAI_STYLE_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_GITHUB_STYLE_KEY_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
)


def _is_secret_key(key: object) -> bool:
    text = str(key).lower().replace("-", "_")
    return any(part in text for part in _SECRET_KEY_PARTS)


def _redact_assignment(match: re.Match[str]) -> str:
    return f"{match.group('key')}{match.group('sep')}[REDACTED]"


def _redact_string(value: str) -> str:
    value = _PEM_PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _COOKIE_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    value = _SECRET_ASSIGNMENT_RE.sub(_redact_assignment, value)
    value = _OPENAI_STYLE_KEY_RE.sub("[REDACTED]", value)
    value = _GITHUB_STYLE_KEY_RE.sub("[REDACTED]", value)
    return value


def redact_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted[key] = "[REDACTED]" if _is_secret_key(key) else redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class EvidenceEnvelope:
    run_id: str
    task_id: str
    capability: str
    provider_version: str = "unknown"
    input_digest: str = ""
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    status: str = "success"
    failure_class: str | None = None
    artifacts: list[object] = field(default_factory=list)
    tests: list[object] = field(default_factory=list)
    health: dict[str, object] = field(default_factory=dict)
    provenance: dict[str, object] = field(default_factory=dict)
    redactions_applied: bool = True
    human_approval_required: bool = False
    approval_category: str | None = None

    @classmethod
    def new(cls, task_id: str, capability: str, *, run_id: str | None = None) -> "EvidenceEnvelope":
        return cls(run_id=run_id or f"{capability}:{task_id}", task_id=task_id, capability=capability)

    def finish(self, *, status: str | None = None, failure_class: str | None = None) -> None:
        if status is not None:
            self.status = status
        self.failure_class = failure_class
        self.finished_at = _now()

    def to_dict(self) -> dict[str, object]:
        return redact_secrets(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class EvidenceRecorder:
    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []

    def record(self, envelope: EvidenceEnvelope) -> dict[str, object]:
        payload = envelope.to_dict()
        self._records.append(payload)
        return payload

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        return tuple(self._records)
