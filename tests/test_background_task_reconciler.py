import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'system'))

from background_task_reconciler import BackgroundTaskReconciler, BackgroundTaskStore, ProviderInspection
from execution_state import DurableTaskStateStore, ExecutionStateLedger

HASH = 'sha256:' + 'a' * 64


class BackgroundTaskReconcilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_completion_notification_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td) / 'provider')
            store.register('task-1', provider='codex', provider_task_id='thr-1/turn-1')
            reconciler = BackgroundTaskReconciler(store, inspectors={}, evidence_verifier=lambda *args: True)

            row = reconciler.observe_notification('task-1', 'turn/completed', {'turn': {'status': 'completed'}})

            self.assertEqual(row['status'], 'running')
            self.assertEqual(row['last_notification']['method'], 'turn/completed')

    async def test_poll_discovers_completion_without_notification_and_advances_verified_durable_state(self):
        with tempfile.TemporaryDirectory() as td:
            provider_store = BackgroundTaskStore(Path(td) / 'provider')
            durable = DurableTaskStateStore(Path(td) / 'durable')
            durable.initialize('upgrade', 'finish upgrade', [{'id': 'r1', 'text': 'provider task complete'}])
            provider_store.register(
                'task-2', provider='codex', provider_task_id='thr-2/turn-2',
                durable_task_id='upgrade', requirement_id='r1',
            )
            calls = 0
            async def inspect(provider_task_id):
                self.assertEqual(provider_task_id, 'thr-2/turn-2')
                return ProviderInspection(status='completed', result={'answer': 'done'}, evidence=('artifact:proof',), output_hash=HASH)
            async def verify(provider, provider_task_id, inspection):
                nonlocal calls
                calls += 1
                return inspection.evidence == ('artifact:proof',) and inspection.output_hash == HASH

            ledger = ExecutionStateLedger()
            reconciler = BackgroundTaskReconciler(
                provider_store, inspectors={'codex': inspect}, evidence_verifier=verify,
                execution_ledger=ledger, durable_task_store=durable,
            )
            first = await reconciler.reconcile('task-2')
            second = await reconciler.reconcile('task-2')

            self.assertEqual(first['status'], 'success')
            self.assertEqual(second['status'], 'success')
            self.assertEqual(calls, 1)
            state = durable.load('upgrade')
            self.assertEqual([x['id'] for x in state['completed_requirements']], ['r1'])
            self.assertEqual(ledger.compact_snapshot()['attempts'][0]['status'], 'success')

    async def test_completed_provider_state_without_verified_evidence_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td) / 'provider')
            store.register('task-3', provider='claude', provider_task_id='child-3')
            async def inspect(_):
                return ProviderInspection(status='completed', result={'answer': 'claimed'}, evidence=(), output_hash=HASH)
            reconciler = BackgroundTaskReconciler(store, inspectors={'claude': inspect}, evidence_verifier=lambda *args: True)

            row = await reconciler.reconcile('task-3')

            self.assertEqual(row['status'], 'verificationPending')

    async def test_provider_failure_is_terminal_but_never_admitted_as_durable_success(self):
        with tempfile.TemporaryDirectory() as td:
            provider_store = BackgroundTaskStore(Path(td) / 'provider')
            durable = DurableTaskStateStore(Path(td) / 'durable')
            durable.initialize('upgrade', 'finish upgrade', [{'id': 'r1', 'text': 'provider task complete'}])
            provider_store.register('task-4', provider='gemini', provider_task_id='job-4', durable_task_id='upgrade', requirement_id='r1')
            async def inspect(_):
                return ProviderInspection(status='failed', result={'error': 'provider failed'})
            reconciler = BackgroundTaskReconciler(provider_store, inspectors={'gemini': inspect}, evidence_verifier=lambda *args: True, durable_task_store=durable)

            row = await reconciler.reconcile('task-4')

            self.assertEqual(row['status'], 'failed')
            self.assertEqual(durable.load('upgrade')['completed_requirements'], [])


    async def test_tampered_task_state_is_not_silently_dropped_from_reconciliation(self):
        import json
        from execution_state import StateError
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td))
            store.register('tampered', provider='codex', provider_task_id='turn-1')
            path = Path(td) / 'tampered.json'
            raw = json.loads(path.read_text())
            raw['provider_task_id'] = 'changed-without-resealing'
            path.write_text(json.dumps(raw))

            with self.assertRaises(StateError):
                store.list_reconcilable()


class BackgroundTaskStoreDefaultsTests(unittest.TestCase):
    def test_default_store_honors_environment_override(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'HERMES_BACKGROUND_TASK_STATE_DIR': td}):
            store = BackgroundTaskStore.default()
            store.register('default-path', provider='codex', provider_task_id='thr/turn')
            self.assertTrue((Path(td) / 'default-path.json').is_file())


class BackgroundTaskLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_pending_polls_all_nonterminal_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td))
            store.register('a', provider='codex', provider_task_id='a1')
            store.register('b', provider='codex', provider_task_id='b1')
            seen = []
            async def inspect(handle):
                seen.append(handle)
                return ProviderInspection(status='running', result={'heartbeat': 1})
            reconciler = BackgroundTaskReconciler(store, inspectors={'codex': inspect}, evidence_verifier=lambda *args: True)

            rows = await reconciler.reconcile_pending()

            self.assertEqual(seen, ['a1', 'b1'])
            self.assertEqual([x['task_id'] for x in rows], ['a', 'b'])

    async def test_unchanged_running_task_becomes_stalled_but_remains_reconcilable(self):
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td))
            store.register('stale', provider='codex', provider_task_id='turn-stale')
            old = '2026-01-01T00:00:00Z'
            store.update('stale', progress_fingerprint='same', last_progress_at=old)
            async def inspect(_):
                return ProviderInspection(status='running', result={'same': True}, metadata={'progressFingerprint': 'same'})
            reconciler = BackgroundTaskReconciler(
                store, inspectors={'codex': inspect}, evidence_verifier=lambda *args: True,
                stale_after_seconds=1,
            )

            row = await reconciler.reconcile('stale')

            self.assertEqual(row['status'], 'stalled')
            self.assertIn('stale', [x['task_id'] for x in store.list_reconcilable()])

if __name__ == '__main__':
    unittest.main(verbosity=2)
