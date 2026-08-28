import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'system'))

from execution_state import DurableTaskStateStore, ExecutionStateLedger, StateError


class ExecutionStateLedgerTests(unittest.TestCase):
    def test_mutation_invalidates_direct_and_dependent_observations(self):
        ledger = ExecutionStateLedger()
        ledger.observe('repo:file:a.py', 'sha256:a1', source='filesystem')
        ledger.observe('analysis:a', 'sha256:analysis1', source='tool', depends_on=('repo:file:a.py',))
        self.assertTrue(ledger.is_fresh('repo:file:a.py'))
        self.assertTrue(ledger.is_fresh('analysis:a'))

        ledger.record_mutation('repo:file:a.py', 'sha256:a2', source='filesystem')

        self.assertTrue(ledger.is_fresh('repo:file:a.py'))
        self.assertFalse(ledger.is_fresh('analysis:a'))
        self.assertEqual(ledger.get('analysis:a')['stale_reason'], 'dependency_mutated:repo:file:a.py')

    def test_successful_operation_is_reusable_only_while_required_state_is_fresh(self):
        ledger = ExecutionStateLedger()
        ledger.observe('repo', 'sha256:r1', source='git')
        ledger.record_attempt('tests', {'suite': 'unit'}, status='success', result={'passed': 12}, requires=('repo',), evidence=('sha256:test1',))

        decision = ledger.preflight('tests', {'suite': 'unit'}, requires=('repo',))
        self.assertEqual(decision.action, 'reuse_success')
        self.assertEqual(decision.result, {'passed': 12})

        ledger.record_mutation('repo', 'sha256:r2', source='git')
        decision2 = ledger.preflight('tests', {'suite': 'unit'}, requires=('repo',))
        self.assertEqual(decision2.action, 'execute')
        self.assertEqual(decision2.reason, 'required_state_changed')

    def test_failed_attempt_is_never_reused_as_success(self):
        ledger = ExecutionStateLedger()
        ledger.record_attempt('deploy-check', {'target': 'x'}, status='failed', result={'error': 'nope'})
        decision = ledger.preflight('deploy-check', {'target': 'x'})
        self.assertEqual(decision.action, 'execute')


class DurableTaskStateTests(unittest.TestCase):
    def test_only_verified_evidence_backed_progress_can_complete_requirement(self):
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            store.initialize('task-1', 'finish repository upgrade', [{'id': 'r1', 'text': 'tests pass'}, {'id': 'r2', 'text': 'docs updated'}])
            with self.assertRaises(StateError):
                store.admit_verified('task-1', requirement_id='r1', output_hash='sha256:' + 'a' * 64, evidence=())
            state = store.load('task-1')
            self.assertEqual(state['completed_requirements'], [])
            self.assertEqual([x['id'] for x in state['remaining_requirements']], ['r1', 'r2'])

    def test_verified_progress_persists_environment_and_builds_fresh_context_without_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            store.initialize('task-1', 'finish repository upgrade', [{'id': 'r1', 'text': 'tests pass'}, {'id': 'r2', 'text': 'docs updated'}])
            store.admit_verified(
                'task-1', requirement_id='r1', output_hash='sha256:' + 'a' * 64,
                evidence=('sha256:test-receipt',), environment_state={'git_head': 'abc123'}, next_subtask='update docs'
            )
            store.record_rejected_attempt('task-1', 'r2', 'schema: bad output')
            context = store.fresh_context('task-1')
            self.assertEqual(context['objective'], 'finish repository upgrade')
            self.assertEqual(context['completed_requirements'][0]['id'], 'r1')
            self.assertEqual(context['remaining_requirements'][0]['id'], 'r2')
            self.assertEqual(context['environment_state']['git_head'], 'abc123')
            self.assertEqual(context['next_subtask'], 'update docs')
            self.assertEqual(context['rejected_attempts'][0]['requirement_id'], 'r2')
            self.assertNotIn('transcript', context)
            self.assertNotIn('messages', context)

    def test_replaying_verified_completion_is_idempotent_and_does_not_regress_next_subtask(self):
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            store.initialize('task-1', 'objective', [{'id': 'r1', 'text': 'one'}, {'id': 'r2', 'text': 'two'}])
            store.admit_verified('task-1', requirement_id='r1', output_hash='sha256:' + 'a' * 64, evidence=('e1',), next_subtask='two')
            store.admit_verified('task-1', requirement_id='r2', output_hash='sha256:' + 'b' * 64, evidence=('e2',))
            replayed = store.admit_verified('task-1', requirement_id='r1', output_hash='sha256:' + 'a' * 64, evidence=('e1',), next_subtask='two')
            self.assertEqual([x['id'] for x in replayed['completed_requirements']], ['r1', 'r2'])
            self.assertEqual(replayed['remaining_requirements'], [])
            self.assertEqual(replayed['next_subtask'], '')

    def test_tampered_durable_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            path = store.initialize('task-1', 'objective', [{'id': 'r1', 'text': 'one'}])
            raw = json.loads(path.read_text())
            raw['objective'] = 'tampered objective'
            path.write_text(json.dumps(raw))
            with self.assertRaises(StateError):
                store.load('task-1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
