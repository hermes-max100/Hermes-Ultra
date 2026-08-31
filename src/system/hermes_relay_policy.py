#!/usr/bin/env python3
"""Fail-closed capability policy for pinned Hermes-Relay tools."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

TARGET_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ACTION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
AMBIGUOUS_TARGETS = {"all", "any", "default", "*"}


class RelayPolicyError(ValueError):
    pass


class RelayPolicyDecision:
    def __init__(self, *, operation: str, policy_class: str, consequential: bool,
                 action_type: str, risk_class: str, target_device_id: str,
                 access_mode: str):
        self.operation = operation
        self.policy_class = policy_class
        self.consequential = consequential
        self.action_type = action_type
        self.risk_class = risk_class
        self.target_device_id = target_device_id
        self.access_mode = access_mode

    def to_gate_request(self, *, action_id: str, principal: str, actor: str,
                        purpose: str) -> dict[str, Any]:
        if not self.consequential:
            raise RelayPolicyError("non-consequential operation has no gate request")
        if not ACTION_ID_RE.fullmatch(str(action_id or "")):
            raise RelayPolicyError("invalid action id")
        if not str(principal or "").strip() or not str(actor or "").strip():
            raise RelayPolicyError("principal and actor are required")
        if not str(purpose or "").strip():
            raise RelayPolicyError("purpose is required")
        destination = f"device:{self.target_device_id}"
        return {
            "schema_version": "hermes-consequential-action-v1",
            "action_id": str(action_id),
            "principal": str(principal),
            "actor": str(actor),
            "action_type": self.action_type,
            "purpose": str(purpose),
            "tool": self.operation,
            "destination": destination,
            "counterparty": destination,
            "amount": 0.0,
            "risk_class": self.risk_class,
            "evidence_refs": [
                {
                    "type": "relay_policy",
                    "ref": f"relay-policy:{self.policy_class}:{self.operation}",
                }
            ],
        }


class RelayPolicy:
    def __init__(self, config: Mapping[str, Any]):
        if config.get("schema_version") != 1:
            raise RelayPolicyError("Relay policy schema mismatch")
        defaults = config.get("defaults")
        classes = config.get("classes")
        if not isinstance(defaults, Mapping) or not isinstance(classes, Mapping):
            raise RelayPolicyError("Relay policy structure invalid")
        if defaults.get("full_access_auto") is not False:
            raise RelayPolicyError("automatic Full Access is forbidden")
        self.defaults = dict(defaults)
        self.operations: dict[str, dict[str, Any]] = {}
        for class_name, raw in classes.items():
            if not isinstance(raw, Mapping):
                raise RelayPolicyError("Relay policy class invalid")
            operations = raw.get("operations")
            if not isinstance(operations, list) or not operations:
                raise RelayPolicyError("Relay policy class operations missing")
            consequential = raw.get("consequential") is True
            action_type = str(raw.get("action_type") or "")
            risk_class = str(raw.get("risk_class") or "")
            if consequential and not action_type:
                raise RelayPolicyError("consequential Relay class missing action type")
            if risk_class not in {"low", "medium", "high"}:
                raise RelayPolicyError("Relay policy risk class invalid")
            for operation in operations:
                name = str(operation or "").strip()
                if not name or "*" in name:
                    raise RelayPolicyError("wildcard or empty Relay operation forbidden")
                if name in self.operations:
                    raise RelayPolicyError("duplicate Relay operation")
                self.operations[name] = {
                    "policy_class": str(class_name),
                    "consequential": consequential,
                    "action_type": action_type,
                    "risk_class": risk_class,
                }

    @classmethod
    def from_file(cls, path: Path | str) -> "RelayPolicy":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RelayPolicyError(f"cannot load Relay policy: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise RelayPolicyError("Relay policy must be an object")
        return cls(raw)

    @staticmethod
    def _target(value: str) -> str:
        target = str(value or "").strip()
        if target.lower() in AMBIGUOUS_TARGETS or not TARGET_RE.fullmatch(target):
            raise RelayPolicyError("target device id is missing or ambiguous")
        return target

    def classify(self, operation: str, *, target_device_id: str) -> RelayPolicyDecision:
        name = str(operation or "").strip()
        entry = self.operations.get(name)
        if entry is None:
            raise RelayPolicyError(f"unknown relay operation: {name or '<empty>'}")
        target = self._target(target_device_id)
        access_mode = (
            str(self.defaults.get("desktop_access"))
            if name.startswith("desktop_")
            else str(self.defaults.get("unconfigured_access"))
        )
        return RelayPolicyDecision(
            operation=name,
            policy_class=entry["policy_class"],
            consequential=bool(entry["consequential"]),
            action_type=entry["action_type"],
            risk_class=entry["risk_class"],
            target_device_id=target,
            access_mode=access_mode,
        )
