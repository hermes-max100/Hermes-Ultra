#!/usr/bin/env python3
"""Official Codex app-server transport adapter for Hermes.

The adapter owns protocol transport only. Hermes retains routing, authority,
verification, durable state, and approval policy outside this module.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from collections import deque
from typing import Any, Mapping, Sequence


class AppServerError(RuntimeError):
    pass


class SubprocessJsonlTransport:
    """Newline-delimited JSON transport for `codex app-server --stdio`."""

    def __init__(self, command: Sequence[str] = ('codex', 'app-server', '--stdio')):
        self.command = tuple(str(x) for x in command)
        if not self.command or 'mcp-server' in self.command:
            raise AppServerError('Codex transport must use app-server, not mcp-server')
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[Any] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=32)

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode('utf-8', errors='replace').rstrip())

    async def send(self, message: Mapping[str, Any]) -> None:
        if self._process is None or self._process.stdin is None or self._process.returncode is not None:
            raise AppServerError('Codex app-server transport is not running')
        payload = json.dumps(dict(message), separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n'
        self._process.stdin.write(payload)
        await self._process.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise AppServerError('Codex app-server transport is not running')
        line = await self._process.stdout.readline()
        if not line:
            detail = '; '.join(self._stderr_tail)
            raise AppServerError(f'Codex app-server closed the transport{": " + detail if detail else ""}')
        try:
            message = json.loads(line.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise AppServerError(f'invalid JSON from Codex app-server: {exc}') from exc
        if not isinstance(message, dict):
            raise AppServerError('Codex app-server message must be an object')
        return message

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
            self._stderr_task = None
        self._process = None


class CodexAppServerClient:
    """Small v2 app-server client used beneath Hermes provider authority."""

    def __init__(
        self,
        *,
        transport: Any | None = None,
        client_name: str = 'hermes_jarvis',
        client_title: str = 'Hermes/JARVIS',
        client_version: str = '1.0',
        server_request_handler: Any | None = None,
        overload_retries: int = 2,
        overload_backoff_seconds: float = 0.05,
        request_timeout_seconds: float = 30.0,
    ):
        self.transport = transport or SubprocessJsonlTransport()
        self.client_name = str(client_name)
        self.client_title = str(client_title)
        self.client_version = str(client_version)
        self.server_request_handler = server_request_handler
        self.overload_retries = max(0, int(overload_retries))
        self.overload_backoff_seconds = max(0.0, float(overload_backoff_seconds))
        self.request_timeout_seconds = max(0.1, float(request_timeout_seconds))
        self.connected = False
        self._next_id = 1
        self._pending_events: deque[dict[str, Any]] = deque()
        self._request_lock = asyncio.Lock()

    async def connect(self) -> Mapping[str, Any]:
        if self.connected:
            raise AppServerError('Codex app-server client is already initialized')
        await self.transport.start()
        result = await self.request(
            'initialize',
            {'clientInfo': {'name': self.client_name, 'title': self.client_title, 'version': self.client_version}},
            require_connected=False,
        )
        await self.transport.send({'method': 'initialized'})
        self.connected = True
        return result if isinstance(result, Mapping) else {}

    async def _handle_server_request(self, incoming: Mapping[str, Any]) -> None:
        if self.server_request_handler is None:
            raise AppServerError(f"unhandled Codex app-server server request: {incoming.get('method')}")
        result = self.server_request_handler(dict(incoming))
        if inspect.isawaitable(result):
            result = await result
        await self.transport.send({'id': incoming.get('id'), 'result': result})

    @staticmethod
    def _is_server_request(incoming: Mapping[str, Any]) -> bool:
        return 'method' in incoming and 'id' in incoming and 'result' not in incoming and 'error' not in incoming

    async def request(self, method: str, params: Mapping[str, Any] | None = None, *, require_connected: bool = True) -> Any:
        async with self._request_lock:
            return await self._request_locked(method, params, require_connected=require_connected)

    async def _request_locked(self, method: str, params: Mapping[str, Any] | None = None, *, require_connected: bool = True) -> Any:
        if require_connected and not self.connected:
            raise AppServerError('Codex app-server client is not initialized')
        retry = 0
        while True:
            request_id = self._next_id
            self._next_id += 1
            message: dict[str, Any] = {'method': str(method), 'id': request_id}
            if params is not None:
                message['params'] = dict(params)
            await self.transport.send(message)
            while True:
                try:
                    incoming = await asyncio.wait_for(self.transport.recv(), timeout=self.request_timeout_seconds)
                except asyncio.TimeoutError as exc:
                    raise AppServerError(f'Codex app-server request timed out: {method}') from exc
                if self._is_server_request(incoming):
                    await self._handle_server_request(incoming)
                    continue
                if incoming.get('id') == request_id:
                    if 'error' in incoming:
                        error = incoming.get('error')
                        code = error.get('code') if isinstance(error, Mapping) else None
                        if code == -32001 and retry < self.overload_retries:
                            delay = self.overload_backoff_seconds * (2 ** retry)
                            retry += 1
                            if delay:
                                await asyncio.sleep(delay)
                            break
                        raise AppServerError(f'Codex app-server request {method} failed: {error}')
                    return incoming.get('result')
                self._pending_events.append(dict(incoming))

    async def next_event(self) -> dict[str, Any]:
        while True:
            if self._pending_events:
                incoming = self._pending_events.popleft()
            else:
                incoming = await self.transport.recv()
            if self._is_server_request(incoming):
                await self._handle_server_request(incoming)
                continue
            return dict(incoming)

    async def start_thread(self, *, cwd: str | None = None, model: str | None = None, developer_instructions: str | None = None) -> str:
        params: dict[str, Any] = {}
        if cwd is not None:
            params['cwd'] = str(cwd)
        if model is not None:
            params['model'] = str(model)
        if developer_instructions is not None:
            params['developerInstructions'] = str(developer_instructions)
        result = await self.request('thread/start', params)
        try:
            thread_id = result['thread']['id']
        except (TypeError, KeyError) as exc:
            raise AppServerError('thread/start response did not contain thread.id') from exc
        if not isinstance(thread_id, str) or not thread_id:
            raise AppServerError('thread/start returned an invalid thread.id')
        return thread_id

    async def start_turn(self, thread_id: str, prompt: str, *, cwd: str | None = None) -> str:
        params: dict[str, Any] = {
            'threadId': str(thread_id),
            'input': [{'type': 'text', 'text': str(prompt)}],
        }
        if cwd is not None:
            params['cwd'] = str(cwd)
        result = await self.request('turn/start', params)
        try:
            turn_id = result['turn']['id']
        except (TypeError, KeyError) as exc:
            raise AppServerError('turn/start response did not contain turn.id') from exc
        if not isinstance(turn_id, str) or not turn_id:
            raise AppServerError('turn/start returned an invalid turn.id')
        return turn_id

    async def read_thread(self, thread_id: str, *, include_turns: bool = True) -> Mapping[str, Any]:
        result = await self.request('thread/read', {'threadId': str(thread_id), 'includeTurns': bool(include_turns)})
        if not isinstance(result, Mapping):
            raise AppServerError('thread/read returned a non-object result')
        return result

    async def close(self) -> None:
        self.connected = False
        await self.transport.close()

class CodexBackgroundExecutor:
    """Start Codex app-server work and register the provider handle for reconciliation."""

    def __init__(self, client: CodexAppServerClient, task_store: Any):
        self.client = client
        self.task_store = task_store

    async def start(
        self,
        task_id: str,
        prompt: str,
        *,
        cwd: str | None = None,
        model: str | None = None,
        durable_task_id: str = '',
        requirement_id: str = '',
    ) -> Mapping[str, Any]:
        thread_id = await self.client.start_thread(cwd=cwd, model=model)
        turn_id = await self.client.start_turn(thread_id, prompt, cwd=cwd)
        return self.task_store.register(
            task_id,
            provider='codex',
            provider_task_id=f'{thread_id}/{turn_id}',
            durable_task_id=durable_task_id,
            requirement_id=requirement_id,
        )


class CodexTurnInspector:
    """Independently inspect a Codex turn through thread/read.

    Evidence is deliberately supplied by a Hermes-side resolver rather than by
    completion notifications. Without that resolver a completed turn has no
    admissible evidence and the generic reconciler will keep it pending.
    """

    def __init__(self, client: CodexAppServerClient, *, evidence_resolver: Any | None = None):
        self.client = client
        self.evidence_resolver = evidence_resolver

    async def __call__(self, provider_task_id: str):
        from background_task_reconciler import ProviderInspection
        import inspect as _inspect

        try:
            thread_id, turn_id = str(provider_task_id).split('/', 1)
        except ValueError as exc:
            raise AppServerError('Codex provider task id must be threadId/turnId') from exc
        if not thread_id or not turn_id:
            raise AppServerError('Codex provider task id must contain non-empty thread and turn ids')
        result = await self.client.read_thread(thread_id, include_turns=True)
        thread = result.get('thread', {}) if isinstance(result, Mapping) else {}
        turns = thread.get('turns', []) if isinstance(thread, Mapping) else []
        turn = next((item for item in turns if isinstance(item, Mapping) and item.get('id') == turn_id), None)
        if turn is None:
            return ProviderInspection(status='notFound', result={'threadId': thread_id, 'turnId': turn_id})
        evidence: tuple[str, ...] = ()
        output_hash = ''
        if self.evidence_resolver is not None and str(turn.get('status', '')).lower() in {'completed', 'success', 'succeeded'}:
            resolved = self.evidence_resolver(provider_task_id, turn)
            if _inspect.isawaitable(resolved):
                resolved = await resolved
            try:
                raw_evidence, output_hash = resolved
                evidence = tuple(str(x) for x in raw_evidence)
                output_hash = str(output_hash)
            except (TypeError, ValueError) as exc:
                raise AppServerError('evidence resolver must return (evidence, output_hash)') from exc
        return ProviderInspection(
            status=str(turn.get('status', 'unknown')),
            result=dict(turn),
            evidence=evidence,
            output_hash=output_hash,
            metadata={'threadId': thread_id, 'turnId': turn_id},
        )
