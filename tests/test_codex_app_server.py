import asyncio
import unittest
from collections import deque
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'system'))

from codex_app_server import CodexAppServerClient, SubprocessJsonlTransport


class FakeTransport:
    def __init__(self, incoming):
        self.incoming = deque(incoming)
        self.sent = []
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if not self.incoming:
            raise RuntimeError('no fake response available')
        return self.incoming.popleft()

    async def close(self):
        self.closed = True


class CodexAppServerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_handshake_is_mandatory_and_acknowledged(self):
        transport = FakeTransport([{'id': 1, 'result': {'codexHome': '/tmp/codex'}}])
        client = CodexAppServerClient(transport=transport, client_name='hermes', client_version='1.0')

        result = await client.connect()

        self.assertEqual(result['codexHome'], '/tmp/codex')
        self.assertEqual(transport.sent[0], {
            'method': 'initialize', 'id': 1,
            'params': {'clientInfo': {'name': 'hermes', 'title': 'Hermes/JARVIS', 'version': '1.0'}},
        })
        self.assertEqual(transport.sent[1], {'method': 'initialized'})

    async def test_interleaved_notifications_are_preserved_while_waiting_for_response(self):
        transport = FakeTransport([
            {'method': 'thread/started', 'params': {'thread': {'id': 'thr-1'}}},
            {'id': 1, 'result': {'ok': True}},
        ])
        client = CodexAppServerClient(transport=transport)

        result = await client.request('thread/list', {'limit': 1}, require_connected=False)

        self.assertEqual(result, {'ok': True})
        event = await client.next_event()
        self.assertEqual(event['method'], 'thread/started')

    async def test_thread_and_turn_helpers_use_app_server_v2_wire_shape(self):
        transport = FakeTransport([
            {'id': 1, 'result': {}},
            {'id': 2, 'result': {'thread': {'id': 'thr-7'}}},
            {'id': 3, 'result': {'turn': {'id': 'turn-9', 'status': 'inProgress'}}},
        ])
        client = CodexAppServerClient(transport=transport)
        await client.connect()
        thread_id = await client.start_thread(cwd='/work', model='gpt-test')
        turn_id = await client.start_turn(thread_id, 'Run tests', cwd='/work')

        self.assertEqual(thread_id, 'thr-7')
        self.assertEqual(turn_id, 'turn-9')
        self.assertEqual(transport.sent[2]['method'], 'thread/start')
        self.assertEqual(transport.sent[2]['params'], {'cwd': '/work', 'model': 'gpt-test'})
        self.assertEqual(transport.sent[3]['method'], 'turn/start')
        self.assertEqual(transport.sent[3]['params']['threadId'], 'thr-7')
        self.assertEqual(transport.sent[3]['params']['input'], [{'type': 'text', 'text': 'Run tests'}])
        self.assertEqual(transport.sent[3]['params']['cwd'], '/work')

    def test_subprocess_transport_uses_app_server_not_deprecated_mcp_server(self):
        transport = SubprocessJsonlTransport()
        self.assertEqual(transport.command, ('codex', 'app-server', '--stdio'))
        self.assertNotIn('mcp-server', transport.command)


    async def test_server_request_without_external_authority_handler_fails_closed(self):
        transport = FakeTransport([
            {'method': 'commandExecution/requestApproval', 'id': 90, 'params': {'command': 'example'}},
            {'id': 1, 'result': {'ok': True}},
        ])
        client = CodexAppServerClient(transport=transport)

        with self.assertRaisesRegex(Exception, 'server request'):
            await client.request('thread/list', {'limit': 1}, require_connected=False)

    async def test_server_request_is_routed_to_external_handler_before_rpc_continues(self):
        handled = []
        async def authority(message):
            handled.append(message['method'])
            return {'decision': 'accept'}
        transport = FakeTransport([
            {'method': 'tool/requestUserInput', 'id': 'srv-1', 'params': {'questions': []}},
            {'id': 1, 'result': {'ok': True}},
        ])
        client = CodexAppServerClient(transport=transport, server_request_handler=authority)

        result = await client.request('thread/list', {'limit': 1}, require_connected=False)

        self.assertEqual(result, {'ok': True})
        self.assertEqual(handled, ['tool/requestUserInput'])
        self.assertEqual(transport.sent[1], {'id': 'srv-1', 'result': {'decision': 'accept'}})

    async def test_server_overload_is_retried_with_a_new_request_id(self):
        transport = FakeTransport([
            {'id': 1, 'error': {'code': -32001, 'message': 'Server overloaded; retry later.'}},
            {'id': 2, 'result': {'ok': True}},
        ])
        client = CodexAppServerClient(transport=transport, overload_retries=1, overload_backoff_seconds=0)

        result = await client.request('thread/list', {'limit': 1}, require_connected=False)

        self.assertEqual(result, {'ok': True})
        self.assertEqual([m['id'] for m in transport.sent], [1, 2])


    async def test_concurrent_control_requests_do_not_compete_for_transport_reads(self):
        class NonReentrantTransport(FakeTransport):
            def __init__(self, incoming):
                super().__init__(incoming)
                self.reading = False
            async def recv(self):
                if self.reading:
                    raise RuntimeError('concurrent recv')
                self.reading = True
                try:
                    await asyncio.sleep(0.01)
                    return await super().recv()
                finally:
                    self.reading = False

        transport = NonReentrantTransport([
            {'id': 1, 'result': {'n': 1}},
            {'id': 2, 'result': {'n': 2}},
        ])
        client = CodexAppServerClient(transport=transport)

        first, second = await asyncio.gather(
            client.request('thread/list', {'limit': 1}, require_connected=False),
            client.request('thread/list', {'limit': 2}, require_connected=False),
        )

        self.assertEqual(first, {'n': 1})
        self.assertEqual(second, {'n': 2})


class CodexBackgroundIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_executor_registers_turn_handle_without_waiting_for_completion_notification(self):
        import tempfile
        from background_task_reconciler import BackgroundTaskStore
        from codex_app_server import CodexBackgroundExecutor

        transport = FakeTransport([
            {'id': 1, 'result': {}},
            {'id': 2, 'result': {'thread': {'id': 'thr-bg'}}},
            {'id': 3, 'result': {'turn': {'id': 'turn-bg', 'status': 'inProgress'}}},
        ])
        client = CodexAppServerClient(transport=transport)
        await client.connect()
        with tempfile.TemporaryDirectory() as td:
            store = BackgroundTaskStore(Path(td))
            executor = CodexBackgroundExecutor(client, store)
            row = await executor.start('hermes-task', 'Run the bounded task', cwd='/work')

            self.assertEqual(row['provider'], 'codex')
            self.assertEqual(row['provider_task_id'], 'thr-bg/turn-bg')
            self.assertEqual(row['status'], 'running')
            self.assertEqual(len(transport.incoming), 0)

    async def test_turn_inspector_uses_thread_read_and_external_evidence_resolver(self):
        from codex_app_server import CodexTurnInspector

        class ReadClient:
            async def read_thread(self, thread_id, include_turns=True):
                self.thread_id = thread_id
                return {'thread': {'turns': [{'id': 'turn-4', 'status': 'completed', 'items': [{'type': 'agentMessage'}]}]}}

        client = ReadClient()
        async def evidence(handle, turn):
            self.assertEqual(handle, 'thr-4/turn-4')
            self.assertEqual(turn['status'], 'completed')
            return ('artifact:/tmp/proof.json',), 'sha256:' + 'b' * 64

        inspection = await CodexTurnInspector(client, evidence_resolver=evidence)('thr-4/turn-4')

        self.assertEqual(client.thread_id, 'thr-4')
        self.assertEqual(inspection.status, 'completed')
        self.assertEqual(inspection.evidence, ('artifact:/tmp/proof.json',))
        self.assertEqual(inspection.output_hash, 'sha256:' + 'b' * 64)

if __name__ == '__main__':
    unittest.main(verbosity=2)
