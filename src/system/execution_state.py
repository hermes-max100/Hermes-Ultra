#!/usr/bin/env python3
"""Deterministic execution state and verified long-horizon task state for Hermes."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class StateError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class PreflightDecision:
    action: str
    reason: str
    result: Any = None


class ExecutionStateLedger:
    """Tracks observations, deterministic invalidation, and operation attempts.

    This object does not infer truth. Callers must supply fingerprints derived from
    filesystem/process/tool events. A mutation refreshes its own resource and
    invalidates observations that depended on the prior resource state.
    """

    def __init__(self) -> None:
        self._resources: dict[str, dict[str, Any]] = {}
        self._attempts: dict[str, dict[str, Any]] = {}
        self._sequence = 0

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _check_resource(resource: str) -> str:
        value = str(resource).strip()
        if not value or len(value) > 512:
            raise StateError('resource key must be a bounded non-empty string')
        return value

    def observe(self, resource: str, fingerprint: str, *, source: str, depends_on: Sequence[str] = ()) -> dict[str, Any]:
        resource = self._check_resource(resource)
        dependencies = tuple(sorted({self._check_resource(x) for x in depends_on}))
        row = {
            'resource': resource,
            'fingerprint': str(fingerprint),
            'source': str(source),
            'depends_on': dependencies,
            'fresh': True,
            'stale_reason': '',
            'sequence': self._next(),
            'observed_at': utc_now(),
        }
        self._resources[resource] = row
        return dict(row)

    def record_mutation(self, resource: str, fingerprint: str, *, source: str) -> dict[str, Any]:
        resource = self._check_resource(resource)
        changed = self._resources.get(resource, {}).get('fingerprint') != str(fingerprint)
        row = self.observe(resource, fingerprint, source=source)
        if changed:
            queue = [resource]
            seen = {resource}
            while queue:
                mutated = queue.pop(0)
                for key, item in self._resources.items():
                    if key in seen or not item.get('fresh', False):
                        continue
                    if mutated in item.get('depends_on', ()):
                        item['fresh'] = False
                        item['stale_reason'] = f'dependency_mutated:{mutated}'
                        item['sequence'] = self._next()
                        seen.add(key)
                        queue.append(key)
        return dict(row)

    def is_fresh(self, resource: str) -> bool:
        return bool(self._resources.get(resource, {}).get('fresh', False))

    def get(self, resource: str) -> dict[str, Any] | None:
        row = self._resources.get(resource)
        return None if row is None else dict(row)

    @staticmethod
    def _operation_key(operation: str, args: Mapping[str, Any]) -> str:
        return digest({'operation': str(operation), 'args': dict(args)})

    def record_attempt(
        self,
        operation: str,
        args: Mapping[str, Any],
        *,
        status: str,
        result: Any = None,
        requires: Sequence[str] = (),
        evidence: Sequence[str] = (),
    ) -> dict[str, Any]:
        if status not in {'success', 'failed', 'rejected'}:
            raise StateError('attempt status must be success, failed, or rejected')
        required = tuple(sorted({self._check_resource(x) for x in requires}))
        required_state = {
            key: self._resources[key]['fingerprint']
            for key in required
            if key in self._resources and self._resources[key].get('fresh', False)
        }
        row = {
            'operation': str(operation),
            'args_hash': digest(dict(args)),
            'status': status,
            'result': result,
            'requires': required,
            'required_state': required_state,
            'evidence': tuple(str(x) for x in evidence),
            'sequence': self._next(),
            'recorded_at': utc_now(),
        }
        self._attempts[self._operation_key(operation, args)] = row
        return dict(row)

    def preflight(self, operation: str, args: Mapping[str, Any], *, requires: Sequence[str] = ()) -> PreflightDecision:
        required = tuple(sorted({self._check_resource(x) for x in requires}))
        prior = self._attempts.get(self._operation_key(operation, args))
        if prior is None or prior.get('status') != 'success':
            return PreflightDecision('execute', 'no_reusable_success')
        if tuple(prior.get('requires', ())) != required:
            return PreflightDecision('execute', 'required_state_changed')
        for key in required:
            current = self._resources.get(key)
            if not current or not current.get('fresh', False):
                return PreflightDecision('execute', 'required_state_changed')
            if prior.get('required_state', {}).get(key) != current.get('fingerprint'):
                return PreflightDecision('execute', 'required_state_changed')
        return PreflightDecision('reuse_success', 'identical_success_with_fresh_state', prior.get('result'))

    def compact_snapshot(self, *, max_resources: int = 32, max_attempts: int = 16) -> dict[str, Any]:
        resources = sorted(self._resources.values(), key=lambda x: x['sequence'], reverse=True)[:max_resources]
        attempts = sorted(self._attempts.values(), key=lambda x: x['sequence'], reverse=True)[:max_attempts]
        return {
            'schema_version': 'hermes-execution-state-v1',
            'resources': [dict(x) for x in resources],
            'attempts': [dict(x) for x in attempts],
            'sequence': self._sequence,
        }


class DurableTaskStateStore:
    """Atomic content-bound task progress admitted only with verified evidence."""

    SCHEMA = 'hermes-durable-task-state-v1'

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, task_id: str) -> Path:
        if not ID_RE.fullmatch(str(task_id)):
            raise StateError('invalid task id')
        return self.root / f'{task_id}.json'

    @staticmethod
    def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.pop('content_hash', None)
        body['content_hash'] = digest(body)
        return body

    @staticmethod
    def _verify(raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        expected = value.pop('content_hash', '')
        if value.get('schema_version') != DurableTaskStateStore.SCHEMA:
            raise StateError('durable task state schema mismatch')
        if expected != digest(value):
            raise StateError('durable task state content hash mismatch')
        value['content_hash'] = expected
        return value

    def _write(self, path: Path, payload: Mapping[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        sealed = self._seal(payload)
        tmp = path.with_name(path.name + f'.tmp-{os.getpid()}')
        with tmp.open('w', encoding='utf-8') as handle:
            json.dump(sealed, handle, indent=2, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        return path

    def initialize(self, task_id: str, objective: str, requirements: Sequence[Mapping[str, Any]]) -> Path:
        path = self._path(task_id)
        normalized = []
        seen = set()
        for item in requirements:
            rid = str(item.get('id', '')).strip()
            text = str(item.get('text', '')).strip()
            if not ID_RE.fullmatch(rid) or rid in seen or not text:
                raise StateError('requirements need unique valid ids and non-empty text')
            seen.add(rid)
            normalized.append({'id': rid, 'text': text})
        if not normalized:
            raise StateError('at least one requirement is required')
        payload = {
            'schema_version': self.SCHEMA,
            'task_id': task_id,
            'objective': str(objective).strip(),
            'requirements': normalized,
            'completed_requirements': [],
            'remaining_requirements': list(normalized),
            'environment_state': {},
            'rejected_attempts': [],
            'next_subtask': normalized[0]['text'],
            'created_at': utc_now(),
            'updated_at': utc_now(),
        }
        return self._write(path, payload)

    def load(self, task_id: str) -> dict[str, Any]:
        path = self._path(task_id)
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f'cannot load durable task state: {exc}') from exc
        if not isinstance(raw, Mapping):
            raise StateError('durable task state must be an object')
        return self._verify(raw)

    def ensure_initialized(self, task_id: str, objective: str, requirements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        path = self._path(task_id)
        if not path.exists():
            self.initialize(task_id, objective, requirements)
        state = self.load(task_id)
        if state['objective'] != str(objective).strip() or state['requirements'] != [dict(x) for x in requirements]:
            raise StateError('existing durable task contract does not match plan')
        return state

    def admit_verified(
        self,
        task_id: str,
        *,
        requirement_id: str,
        output_hash: str,
        evidence: Sequence[str],
        environment_state: Mapping[str, Any] | None = None,
        next_subtask: str | None = None,
    ) -> dict[str, Any]:
        if not SHA256_RE.fullmatch(str(output_hash)):
            raise StateError('verified progress requires a canonical sha256 output hash')
        evidence_rows = [str(x).strip() for x in evidence if str(x).strip()]
        if not evidence_rows:
            raise StateError('verified progress requires evidence')
        state = self.load(task_id)
        requirement = next((x for x in state['requirements'] if x['id'] == requirement_id), None)
        if requirement is None:
            raise StateError('unknown requirement id')
        completed = [dict(x) for x in state['completed_requirements'] if x['id'] != requirement_id]
        completed.append({
            'id': requirement['id'],
            'text': requirement['text'],
            'output_hash': output_hash,
            'evidence': evidence_rows,
            'verified_at': utc_now(),
        })
        order = {item['id']: index for index, item in enumerate(state['requirements'])}
        completed.sort(key=lambda item: order[item['id']])
        completed_ids = {x['id'] for x in completed}
        remaining = [dict(x) for x in state['requirements'] if x['id'] not in completed_ids]
        env = dict(state.get('environment_state', {}))
        if environment_state:
            env.update(dict(environment_state))
        state.update({
            'completed_requirements': completed,
            'remaining_requirements': remaining,
            'environment_state': env,
            'next_subtask': (str(next_subtask).strip() if next_subtask is not None else remaining[0]['text']) if remaining else '',
            'updated_at': utc_now(),
        })
        self._write(self._path(task_id), state)
        return self.load(task_id)

    def record_rejected_attempt(self, task_id: str, requirement_id: str, reason: str) -> dict[str, Any]:
        state = self.load(task_id)
        if requirement_id and not any(x['id'] == requirement_id for x in state['requirements']):
            raise StateError('unknown requirement id')
        rows = [dict(x) for x in state.get('rejected_attempts', [])]
        rows.append({'requirement_id': requirement_id, 'reason': str(reason), 'recorded_at': utc_now()})
        state['rejected_attempts'] = rows[-64:]
        state['updated_at'] = utc_now()
        self._write(self._path(task_id), state)
        return self.load(task_id)

    def fresh_context(self, task_id: str) -> dict[str, Any]:
        state = self.load(task_id)
        return {
            'schema_version': self.SCHEMA,
            'task_id': state['task_id'],
            'objective': state['objective'],
            'completed_requirements': [dict(x) for x in state['completed_requirements']],
            'remaining_requirements': [dict(x) for x in state['remaining_requirements']],
            'environment_state': dict(state['environment_state']),
            'rejected_attempts': [dict(x) for x in state['rejected_attempts'][-16:]],
            'next_subtask': state['next_subtask'],
            'state_hash': state['content_hash'],
        }
