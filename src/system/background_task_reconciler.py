#!/usr/bin/env python3
"""Provider-independent background task reconciliation for Hermes.

Provider notifications are advisory. Success is admitted only after an
independent provider inspection plus evidence verification.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from execution_state import DurableTaskStateStore, ExecutionStateLedger, ID_RE, SHA256_RE, StateError, digest, utc_now


@dataclass(frozen=True)
class ProviderInspection:
    status: str
    result: Any = None
    evidence: tuple[str, ...] = ()
    output_hash: str = ''
    metadata: Mapping[str, Any] = field(default_factory=dict)


class BackgroundTaskStore:
    SCHEMA = 'hermes-background-task-v1'

    def __init__(self, root: Path | str):
        self.root = Path(root)

    @classmethod
    def default(cls) -> 'BackgroundTaskStore':
        return cls(os.environ.get('HERMES_BACKGROUND_TASK_STATE_DIR', '.hermes/state/provider-tasks'))

    def _path(self, task_id: str) -> Path:
        if not ID_RE.fullmatch(str(task_id)):
            raise StateError('invalid background task id')
        return self.root / f'{task_id}.json'

    @staticmethod
    def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.pop('content_hash', None)
        body['content_hash'] = digest(body)
        return body

    @classmethod
    def _verify(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        expected = value.pop('content_hash', '')
        if value.get('schema_version') != cls.SCHEMA:
            raise StateError('background task schema mismatch')
        if expected != digest(value):
            raise StateError('background task content hash mismatch')
        value['content_hash'] = expected
        return value

    def _write(self, task_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        sealed = self._seal(row)
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
        return self.load(task_id)

    def register(
        self,
        task_id: str,
        *,
        provider: str,
        provider_task_id: str,
        durable_task_id: str = '',
        requirement_id: str = '',
    ) -> dict[str, Any]:
        if not str(provider).strip() or not str(provider_task_id).strip():
            raise StateError('provider and provider_task_id are required')
        path = self._path(task_id)
        if path.exists():
            existing = self.load(task_id)
            identity = (existing['provider'], existing['provider_task_id'], existing.get('durable_task_id', ''), existing.get('requirement_id', ''))
            requested = (str(provider), str(provider_task_id), str(durable_task_id), str(requirement_id))
            if identity != requested:
                raise StateError('background task id already belongs to a different provider task')
            return existing
        now = utc_now()
        return self._write(task_id, {
            'schema_version': self.SCHEMA,
            'task_id': str(task_id),
            'provider': str(provider),
            'provider_task_id': str(provider_task_id),
            'durable_task_id': str(durable_task_id),
            'requirement_id': str(requirement_id),
            'status': 'running',
            'provider_status': 'unknown',
            'result': None,
            'evidence': [],
            'output_hash': '',
            'last_notification': None,
            'progress_fingerprint': '',
            'last_progress_at': now,
            'created_at': now,
            'updated_at': now,
        })

    def load(self, task_id: str) -> dict[str, Any]:
        try:
            raw = json.loads(self._path(task_id).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f'cannot load background task state: {exc}') from exc
        if not isinstance(raw, Mapping):
            raise StateError('background task state must be an object')
        return self._verify(raw)

    def update(self, task_id: str, **changes: Any) -> dict[str, Any]:
        row = self.load(task_id)
        row.update(changes)
        row['updated_at'] = utc_now()
        return self._write(task_id, row)

    def observe_notification(self, task_id: str, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.update(task_id, last_notification={
            'method': str(method),
            'params': dict(params or {}),
            'observed_at': utc_now(),
        })

    def list_reconcilable(self) -> list[dict[str, Any]]:
        rows = []
        if not self.root.exists():
            return rows
        for path in sorted(self.root.glob('*.json')):
            row = self.load(path.stem)
            if row.get('status') in {'running', 'verificationPending', 'stalled'}:
                rows.append(row)
        return rows


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class BackgroundTaskReconciler:
    """Reconcile provider work into Hermes only after independent proof."""

    def __init__(
        self,
        store: BackgroundTaskStore,
        *,
        inspectors: Mapping[str, Callable[[str], Any]],
        evidence_verifier: Callable[[str, str, ProviderInspection], Any],
        execution_ledger: ExecutionStateLedger | None = None,
        durable_task_store: DurableTaskStateStore | None = None,
        stale_after_seconds: float = 900.0,
    ):
        self.store = store
        self.inspectors = dict(inspectors)
        self.evidence_verifier = evidence_verifier
        self.execution_ledger = execution_ledger
        self.durable_task_store = durable_task_store
        self.stale_after_seconds = max(0.0, float(stale_after_seconds))

    def observe_notification(self, task_id: str, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.store.observe_notification(task_id, method, params)

    async def reconcile(self, task_id: str) -> dict[str, Any]:
        row = self.store.load(task_id)
        if row['status'] in {'success', 'failed'}:
            return row
        provider = row['provider']
        inspector = self.inspectors.get(provider)
        if inspector is None:
            raise StateError(f'no background task inspector registered for provider {provider}')
        inspection = await _await(inspector(row['provider_task_id']))
        if not isinstance(inspection, ProviderInspection):
            raise StateError('provider inspector must return ProviderInspection')
        normalized = str(inspection.status).strip().lower()

        if normalized in {'completed', 'complete', 'success', 'succeeded'}:
            if not inspection.evidence or not SHA256_RE.fullmatch(str(inspection.output_hash)):
                return self.store.update(
                    task_id,
                    status='verificationPending',
                    provider_status=inspection.status,
                    result=inspection.result,
                    evidence=list(inspection.evidence),
                    output_hash=str(inspection.output_hash),
                )
            verified = bool(await _await(self.evidence_verifier(provider, row['provider_task_id'], inspection)))
            if not verified:
                return self.store.update(
                    task_id,
                    status='verificationPending',
                    provider_status=inspection.status,
                    result=inspection.result,
                    evidence=list(inspection.evidence),
                    output_hash=str(inspection.output_hash),
                )
            accepted = self.store.update(
                task_id,
                status='success',
                provider_status=inspection.status,
                result=inspection.result,
                evidence=list(inspection.evidence),
                output_hash=inspection.output_hash,
                verified_at=utc_now(),
            )
            if self.execution_ledger is not None:
                resource = f'provider-task:{task_id}'
                self.execution_ledger.record_mutation(resource, inspection.output_hash, source=f'provider-inspector:{provider}')
                self.execution_ledger.record_attempt(
                    'reconcile-provider-task',
                    {'provider': provider, 'provider_task_id': row['provider_task_id']},
                    status='success',
                    result=inspection.result,
                    requires=(resource,),
                    evidence=inspection.evidence,
                )
            if self.durable_task_store is not None and row.get('durable_task_id') and row.get('requirement_id'):
                self.durable_task_store.admit_verified(
                    row['durable_task_id'],
                    requirement_id=row['requirement_id'],
                    output_hash=inspection.output_hash,
                    evidence=inspection.evidence,
                    environment_state={f'provider_task:{provider}': row['provider_task_id']},
                )
            return accepted

        if normalized in {'failed', 'error', 'errored', 'interrupted', 'cancelled', 'canceled'}:
            failed = self.store.update(task_id, status='failed', provider_status=inspection.status, result=inspection.result)
            if self.execution_ledger is not None:
                self.execution_ledger.record_attempt(
                    'reconcile-provider-task',
                    {'provider': provider, 'provider_task_id': row['provider_task_id']},
                    status='failed',
                    result=inspection.result,
                )
            if self.durable_task_store is not None and row.get('durable_task_id') and row.get('requirement_id'):
                self.durable_task_store.record_rejected_attempt(
                    row['durable_task_id'], row['requirement_id'], f'{provider} task {inspection.status}'
                )
            return failed

        progress_fingerprint = str(inspection.metadata.get('progressFingerprint', '')).strip() or digest({
            'status': inspection.status, 'result': inspection.result, 'metadata': dict(inspection.metadata),
        })
        if progress_fingerprint != row.get('progress_fingerprint', ''):
            return self.store.update(
                task_id, status='running', provider_status=inspection.status, result=inspection.result,
                progress_fingerprint=progress_fingerprint, last_progress_at=utc_now(), last_reconcile_error='',
            )
        last_progress = str(row.get('last_progress_at') or row.get('created_at') or '')
        try:
            last_dt = datetime.fromisoformat(last_progress.replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        except ValueError:
            age = self.stale_after_seconds
        if age >= self.stale_after_seconds:
            return self.store.update(
                task_id, status='stalled', provider_status=inspection.status, result=inspection.result,
                progress_fingerprint=progress_fingerprint, last_reconcile_error='',
            )
        return self.store.update(
            task_id, status='running', provider_status=inspection.status, result=inspection.result,
            progress_fingerprint=progress_fingerprint, last_reconcile_error='',
        )

    async def reconcile_pending(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in self.store.list_reconcilable():
            try:
                results.append(await self.reconcile(row['task_id']))
            except Exception as exc:
                results.append(self.store.update(
                    row['task_id'], last_reconcile_error=f'{type(exc).__name__}: {exc}',
                ))
        return results

    async def run_forever(self, *, interval_seconds: float = 5.0, stop_event: asyncio.Event | None = None) -> None:
        interval = max(0.1, float(interval_seconds))
        while stop_event is None or not stop_event.is_set():
            await self.reconcile_pending()
            if stop_event is None:
                await asyncio.sleep(interval)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
