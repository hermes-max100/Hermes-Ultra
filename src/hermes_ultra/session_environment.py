from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, TextIO

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback keeps thread safety.
    fcntl = None  # type: ignore[assignment]

from .evidence import EvidenceEnvelope, EvidenceRecorder, redact_secrets

_PAYLOAD_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: object) -> object:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item) for item in value), key=lambda item: repr(item))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_bytes(value: object) -> bytes:
    normalized = redact_secrets(_json_safe(value))
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _payload_ref(payload_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload_bytes).hexdigest()


class SessionIntegrityError(RuntimeError):
    """Raised when append-only session state fails an integrity check."""


@dataclass(frozen=True)
class SessionEvent:
    sequence: int
    event_type: str
    payload_ref: str
    recorded_at: str
    metadata: Mapping[str, object]
    binding: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload_ref": self.payload_ref,
            "recorded_at": self.recorded_at,
            "metadata": dict(self.metadata),
            "binding": self.binding,
        }


@dataclass(frozen=True)
class SessionProjection:
    event: SessionEvent
    payload: object


ComputeOperation = Callable[[tuple[object, ...], Mapping[str, object]], object]


class SessionComputeRegistry:
    """Registry of trusted host-side operations available to session compute."""

    def __init__(self) -> None:
        self._operations: dict[str, ComputeOperation] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("compute operation name is required")
        return normalized

    def register(self, name: str, operation: ComputeOperation) -> None:
        normalized = self._normalize_name(name)
        if not callable(operation):
            raise TypeError("compute operation must be callable")
        if normalized in self._operations:
            raise ValueError(f"duplicate compute operation: {normalized}")
        self._operations[normalized] = operation

    def require(self, name: str) -> ComputeOperation:
        normalized = self._normalize_name(name)
        operation = self._operations.get(normalized)
        if operation is None:
            raise KeyError(f"unknown compute operation: {normalized}")
        return operation

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._operations)


class SessionEnvironment:
    """Durable, append-only, rebuildable operational context for one task.

    Payloads are content-addressed and stored outside the event log. The event
    stream is the only workspace authority; current bindings are reconstructed
    by replay and never trusted from a mutable snapshot. Appends are serialized
    per instance and, on POSIX systems, across processes with `flock` so parallel
    autonomous workers cannot allocate duplicate event sequence numbers.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        task_id: str,
        compute_registry: SessionComputeRegistry | None = None,
        evidence_recorder: EvidenceRecorder | None = None,
    ) -> None:
        normalized_task_id = str(task_id).strip()
        if not normalized_task_id:
            raise ValueError("task_id is required")
        self.root = Path(root)
        self.task_id = normalized_task_id
        task_digest = hashlib.sha256(normalized_task_id.encode("utf-8")).hexdigest()[:24]
        self.session_dir = self.root / "sessions" / task_digest
        self.payload_dir = self.session_dir / "payloads"
        self.events_path = self.session_dir / "events.jsonl"
        self.compute_registry = compute_registry or SessionComputeRegistry()
        self.evidence_recorder = evidence_recorder
        self._thread_lock = threading.RLock()

        self.payload_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            try:
                with self.events_path.open("xb") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass

    @staticmethod
    def _lock_handle(handle: TextIO, *, exclusive: bool) -> None:
        if fcntl is None:
            return
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), operation)

    @staticmethod
    def _unlock_handle(handle: TextIO) -> None:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _validate_payload_ref(payload_ref: str) -> str:
        if _PAYLOAD_REF_RE.fullmatch(payload_ref) is None:
            raise SessionIntegrityError(f"invalid payload reference: {payload_ref!r}")
        return payload_ref

    def payload_path(self, payload_ref: str) -> Path:
        validated = self._validate_payload_ref(payload_ref)
        return self.payload_dir / f"{validated.split(':', 1)[1]}.json"

    def _store_payload(self, payload: object) -> str:
        payload_bytes = _canonical_bytes(payload)
        payload_ref = _payload_ref(payload_bytes)
        path = self.payload_path(payload_ref)
        if path.exists():
            existing = path.read_bytes()
            if _payload_ref(existing) != payload_ref:
                raise SessionIntegrityError(f"payload digest mismatch: {payload_ref}")
            return payload_ref

        try:
            with path.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            existing = path.read_bytes()
            if _payload_ref(existing) != payload_ref:
                raise SessionIntegrityError(f"payload digest mismatch: {payload_ref}")
        return payload_ref

    def load_payload(self, payload_ref: str) -> object:
        path = self.payload_path(payload_ref)
        if not path.exists():
            raise SessionIntegrityError(f"missing payload: {payload_ref}")
        payload_bytes = path.read_bytes()
        actual = _payload_ref(payload_bytes)
        if actual != payload_ref:
            raise SessionIntegrityError(
                f"payload digest mismatch: expected {payload_ref}, got {actual}"
            )
        try:
            return json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionIntegrityError(f"invalid payload JSON: {payload_ref}") from exc

    @staticmethod
    def _event_from_mapping(raw: Mapping[str, object], *, expected_sequence: int) -> SessionEvent:
        try:
            sequence = int(raw["sequence"])
            event_type = str(raw["event_type"])
            payload_ref = str(raw["payload_ref"])
            recorded_at = str(raw["recorded_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionIntegrityError("malformed session event") from exc
        if sequence != expected_sequence:
            raise SessionIntegrityError(
                f"event sequence discontinuity: expected {expected_sequence}, got {sequence}"
            )
        if not event_type.strip():
            raise SessionIntegrityError("event_type is required")
        if _PAYLOAD_REF_RE.fullmatch(payload_ref) is None:
            raise SessionIntegrityError(f"invalid payload reference: {payload_ref!r}")
        metadata_value = raw.get("metadata", {})
        if not isinstance(metadata_value, Mapping):
            raise SessionIntegrityError("event metadata must be an object")
        binding_value = raw.get("binding")
        if binding_value is not None and not isinstance(binding_value, str):
            raise SessionIntegrityError("event binding must be a string or null")
        return SessionEvent(
            sequence=sequence,
            event_type=event_type,
            payload_ref=payload_ref,
            recorded_at=recorded_at,
            metadata=dict(metadata_value),
            binding=binding_value,
        )

    def _read_events(self, handle: TextIO) -> tuple[SessionEvent, ...]:
        handle.seek(0)
        events: list[SessionEvent] = []
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SessionIntegrityError(
                    f"invalid event JSON at line {line_number}"
                ) from exc
            if not isinstance(raw, Mapping):
                raise SessionIntegrityError(
                    f"event record at line {line_number} must be an object"
                )
            events.append(
                self._event_from_mapping(raw, expected_sequence=len(events) + 1)
            )
        return tuple(events)

    def events(self) -> tuple[SessionEvent, ...]:
        with self._thread_lock:
            with self.events_path.open("r", encoding="utf-8") as handle:
                self._lock_handle(handle, exclusive=False)
                try:
                    return self._read_events(handle)
                finally:
                    self._unlock_handle(handle)

    def _record_evidence(self, event: SessionEvent) -> None:
        if self.evidence_recorder is None:
            return
        envelope = EvidenceEnvelope.new(
            self.task_id,
            "session-context",
            run_id=f"session-context:{self.task_id}:{event.sequence}",
        )
        envelope.health = {"session_event": event.to_dict()}
        envelope.provenance = {
            "payload_ref": event.payload_ref,
            "storage": "content_addressed_external_payload",
        }
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)

    def append(
        self,
        event_type: str,
        payload: object,
        *,
        metadata: Mapping[str, object] | None = None,
        bind_as: str | None = None,
    ) -> SessionEvent:
        normalized_type = str(event_type).strip()
        if not normalized_type:
            raise ValueError("event_type is required")
        binding = None if bind_as is None else str(bind_as).strip()
        if bind_as is not None and not binding:
            raise ValueError("bind_as cannot be blank")

        payload_ref = self._store_payload(payload)
        normalized_metadata = dict(_json_safe(dict(metadata or {})))
        with self._thread_lock:
            with self.events_path.open("a+", encoding="utf-8") as handle:
                self._lock_handle(handle, exclusive=True)
                try:
                    sequence = len(self._read_events(handle)) + 1
                    event = SessionEvent(
                        sequence=sequence,
                        event_type=normalized_type,
                        payload_ref=payload_ref,
                        recorded_at=_now(),
                        metadata=normalized_metadata,
                        binding=binding,
                    )
                    handle.seek(0, os.SEEK_END)
                    handle.write(_canonical_bytes(event.to_dict()).decode("utf-8") + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                finally:
                    self._unlock_handle(handle)
        self._record_evidence(event)
        return event

    def rebuild_workspace(self) -> dict[str, str]:
        workspace: dict[str, str] = {}
        for event in self.events():
            if event.binding is not None:
                workspace[event.binding] = event.payload_ref
        return workspace

    def resolve_binding(self, binding: str) -> object:
        normalized = str(binding).strip()
        workspace = self.rebuild_workspace()
        payload_ref = workspace.get(normalized)
        if payload_ref is None:
            raise KeyError(normalized)
        return self.load_payload(payload_ref)

    def select(
        self,
        *,
        event_type: str | None = None,
        binding: str | None = None,
        query: str | None = None,
        limit: int | None = 20,
    ) -> tuple[SessionEvent, ...]:
        if limit is not None and limit <= 0:
            return ()
        normalized_query = query.lower().strip() if isinstance(query, str) else ""
        selected: list[SessionEvent] = []
        for event in self.events():
            if event_type is not None and event.event_type != event_type:
                continue
            if binding is not None and event.binding != binding:
                continue
            if normalized_query:
                payload = self.load_payload(event.payload_ref)
                haystack = json.dumps(
                    payload,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).lower()
                if normalized_query not in haystack:
                    continue
            selected.append(event)
            if limit is not None and len(selected) >= limit:
                break
        return tuple(selected)

    def project(
        self,
        *,
        event_type: str | None = None,
        binding: str | None = None,
        query: str | None = None,
        limit: int | None = 20,
    ) -> tuple[SessionProjection, ...]:
        return tuple(
            SessionProjection(event=event, payload=self.load_payload(event.payload_ref))
            for event in self.select(
                event_type=event_type,
                binding=binding,
                query=query,
                limit=limit,
            )
        )

    def compute(
        self,
        operation: str,
        *,
        input_refs: Iterable[str],
        params: Mapping[str, object] | None = None,
        bind_as: str | None = None,
    ) -> SessionEvent:
        compute_operation = self.compute_registry.require(operation)
        refs = tuple(str(ref) for ref in input_refs)
        inputs = tuple(self.load_payload(ref) for ref in refs)
        normalized_params = dict(_json_safe(dict(params or {})))
        result = compute_operation(inputs, normalized_params)
        return self.append(
            "compute",
            result,
            metadata={
                "operation": operation,
                "input_refs": list(refs),
                "params": normalized_params,
            },
            bind_as=bind_as,
        )
