#!/usr/bin/env python3
"""Pinned Hermes-Relay protocol validation and evidence receipts."""
from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Mapping

PINNED_RELAY_SERVER_VERSION = "1.10.0"
COMPLETION_SCHEMA = "hermes-relay-completion-receipt-v1"
SUCCESS_STREAM_EVENTS = {"assistant.completed", "run.completed", "done"}
SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "session_token", "refresh_token",
    "route_credential", "token", "clipboard", "screen", "notification_body",
    "notification", "body", "content",
}


class RelayProtocolError(ValueError):
    pass


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            out[name] = "[REDACTED]" if name.lower() in SENSITIVE_KEYS else redact_sensitive(item)
        return out
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value


def _payload(envelope: Mapping[str, Any], expected_type: str) -> Mapping[str, Any]:
    if envelope.get("type") != expected_type:
        raise RelayProtocolError(f"expected {expected_type}")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise RelayProtocolError(f"{expected_type} payload must be an object")
    return payload


def _expiry(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RelayProtocolError(f"invalid {label}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise RelayProtocolError(f"invalid {label}")
    return number


@dataclass(frozen=True)
class RelaySessionState:
    server_version: str
    token_sha256: str
    expires_at: float | None
    grants: Mapping[str, float | None]
    client_surface: str
    device_form_factor: str

    @classmethod
    def from_auth_ok(cls, envelope: Mapping[str, Any]) -> "RelaySessionState":
        payload = _payload(envelope, "auth.ok")
        version = str(payload.get("server_version") or "").strip()
        if version != PINNED_RELAY_SERVER_VERSION:
            raise RelayProtocolError(f"Relay server version incompatible: {version or '<missing>'}")
        token = str(payload.get("session_token") or "")
        if not token:
            raise RelayProtocolError("auth.ok missing session token")
        raw_grants = payload.get("grants")
        if not isinstance(raw_grants, Mapping):
            raise RelayProtocolError("auth.ok grants must be an object")
        grants = {str(name): _expiry(value, f"grant expiry {name}") for name, value in raw_grants.items()}
        return cls(
            server_version=version,
            token_sha256="sha256:" + hashlib.sha256(token.encode()).hexdigest(),
            expires_at=_expiry(payload.get("expires_at"), "session expiry"),
            grants=grants,
            client_surface=str(payload.get("client_surface") or "unknown"),
            device_form_factor=str(payload.get("device_form_factor") or "unknown"),
        )

    def session_active(self, now_epoch: float) -> bool:
        return self.expires_at is None or float(now_epoch) < self.expires_at

    def grant_active(self, grant: str, now_epoch: float) -> bool:
        if grant not in self.grants:
            return False
        expiry = self.grants[grant]
        return expiry is None or float(now_epoch) < expiry


@dataclass(frozen=True)
class RelayBridgeCapabilities:
    schema_version: int
    permanent: tuple[str, ...]
    timed: tuple[tuple[str, float], ...]
    unlimited: tuple[str, ...]

    @classmethod
    def from_status_payload(cls, payload: Mapping[str, Any]) -> "RelayBridgeCapabilities":
        caps = payload.get("capabilities")
        if not isinstance(caps, Mapping):
            raise RelayProtocolError("bridge capabilities missing")
        if caps.get("schema_version") != 1:
            raise RelayProtocolError("unsupported bridge capability schema")
        permanent = caps.get("permanent", [])
        unlimited = caps.get("unlimited", [])
        timed = caps.get("timed", {})
        if not isinstance(permanent, list) or not all(isinstance(x, str) and x for x in permanent):
            raise RelayProtocolError("invalid permanent capabilities")
        if not isinstance(unlimited, list) or not all(isinstance(x, str) and x for x in unlimited):
            raise RelayProtocolError("invalid unlimited capabilities")
        if not isinstance(timed, Mapping):
            raise RelayProtocolError("invalid timed capabilities")
        timed_rows: list[tuple[str, float]] = []
        for name, expiry in timed.items():
            value = _expiry(expiry, f"capability expiry {name}")
            if value is None:
                raise RelayProtocolError("timed capability cannot use null expiry")
            timed_rows.append((str(name), value))
        return cls(1, tuple(sorted(set(permanent))), tuple(sorted(timed_rows)), tuple(sorted(set(unlimited))))


@dataclass(frozen=True)
class RelayCompletionReceipt:
    schema_version: str
    task_id: str
    target_device_id: str
    channel: str
    operation: str
    request_id: str
    authorization_id: str
    terminal_status: str
    result_digest: str
    verification_source: str

    @classmethod
    def from_bridge_response(
        cls,
        envelope: Mapping[str, Any],
        *,
        task_id: str,
        target_device_id: str,
        actual_device_id: str,
        operation: str,
        expected_request_id: str,
        authorization_id: str,
    ) -> "RelayCompletionReceipt":
        payload = _payload(envelope, "bridge.response")
        request_id = str(payload.get("request_id") or "")
        if not request_id or request_id != expected_request_id:
            raise RelayProtocolError("bridge response request correlation mismatch")
        if not target_device_id or actual_device_id != target_device_id:
            raise RelayProtocolError("bridge response device correlation mismatch")
        status = payload.get("status")
        if isinstance(status, bool) or not isinstance(status, int):
            raise RelayProtocolError("bridge response status must be an integer")
        evidence = {
            "status": status,
            "result": payload.get("result"),
            "error": payload.get("error"),
            "blocked": payload.get("blocked"),
        }
        success = 200 <= status < 300 and payload.get("blocked") is not True and not payload.get("error")
        return cls(
            schema_version=COMPLETION_SCHEMA,
            task_id=str(task_id),
            target_device_id=str(target_device_id),
            channel="bridge",
            operation=str(operation),
            request_id=request_id,
            authorization_id=str(authorization_id),
            terminal_status="success" if success else "failed",
            result_digest=canonical_digest(evidence),
            verification_source="relay_response",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelayStreamObservation:
    accepted: bool
    reason: str
    terminal_success: bool
    session_id: str
    run_id: str | None
    seq: int
    event: str


class RelayEventDeduper:
    def __init__(self, max_entries: int = 4096):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0:
            raise RelayProtocolError("max_entries must be a positive integer")
        self.max_entries = min(max_entries, 4096)
        self._seen: OrderedDict[tuple[str, str | None, int], None] = OrderedDict()
        self._highest: OrderedDict[tuple[str, str | None], int] = OrderedDict()

    @property
    def size(self) -> int:
        return len(self._seen)

    @staticmethod
    def _validate(event: Mapping[str, Any]) -> tuple[str, str | None, int, str]:
        if event.get("type") != "stream.event" or event.get("schema_version") != 1:
            raise RelayProtocolError("unsupported stream event schema")
        session_id = event.get("session_id")
        run_id = event.get("run_id")
        seq = event.get("seq")
        event_name = event.get("event")
        if not isinstance(session_id, str) or not session_id:
            raise RelayProtocolError("stream event session id missing")
        if run_id is not None and (not isinstance(run_id, str) or not run_id):
            raise RelayProtocolError("stream event run id invalid")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise RelayProtocolError("stream event sequence invalid")
        if not isinstance(event_name, str) or not event_name:
            raise RelayProtocolError("stream event name missing")
        if not isinstance(event.get("payload"), Mapping):
            raise RelayProtocolError("stream event payload invalid")
        return session_id, run_id, seq, event_name

    def _remember(self, key: tuple[str, str | None, int]) -> None:
        self._seen[key] = None
        self._seen.move_to_end(key)
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)

    def observe(self, event: Mapping[str, Any]) -> RelayStreamObservation:
        session_id, run_id, seq, event_name = self._validate(event)
        key = (session_id, run_id, seq)
        stream = (session_id, run_id)
        if key in self._seen:
            self._seen.move_to_end(key)
            return RelayStreamObservation(False, "duplicate", False, session_id, run_id, seq, event_name)
        highest = self._highest.get(stream)
        if highest is not None and seq <= highest:
            self._remember(key)
            return RelayStreamObservation(False, "out_of_order", False, session_id, run_id, seq, event_name)
        self._remember(key)
        self._highest[stream] = seq
        self._highest.move_to_end(stream)
        while len(self._highest) > self.max_entries:
            self._highest.popitem(last=False)
        return RelayStreamObservation(
            True,
            "accepted",
            event_name in SUCCESS_STREAM_EVENTS,
            session_id,
            run_id,
            seq,
            event_name,
        )
