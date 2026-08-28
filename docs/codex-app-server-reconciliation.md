# Codex App-Server and Background Task Reconciliation

Hermes uses the supported Codex app-server transport for subscription-backed Codex execution and keeps provider completion advisory. Routing, authority, verification, evidence admission, and durable progress remain owned by Hermes.

## Codex transport

`src/system/codex_app_server.py` uses `codex app-server --stdio` and the v2 app-server lifecycle:

1. start the JSONL stdio transport;
2. send `initialize` with Hermes client metadata;
3. acknowledge with `initialized`;
4. use `thread/start` or `thread/resume` semantics for conversation state;
5. use `turn/start` for work;
6. preserve interleaved notifications while waiting for request responses;
7. use `thread/read` for independent turn inspection.

The adapter does not call or wrap `codex mcp-server` and does not modify Hermes model routing. Control-plane requests are serialized per connection, app-server overload responses are retried with bounded exponential backoff, and server-to-client requests are routed only through a caller-supplied external authority handler; without one they fail closed. Authentication remains the official Codex CLI/app-server authentication state; Hermes never extracts browser cookies or replays session credentials. `codex login status` can be used to verify whether generative subscription-backed turns are currently available.

`CodexBackgroundExecutor` starts a thread/turn and immediately persists the provider handle as `threadId/turnId`. It does not wait for a completion notification before returning control to Hermes.

`CodexTurnInspector` independently reads the thread and locates the turn. A completed turn has no admissible evidence unless a Hermes-side `evidence_resolver` supplies evidence references plus a canonical `sha256:` output hash.

## Provider-independent reconciliation

`src/system/background_task_reconciler.py` stores content-hash-bound provider task records with atomic fsynced writes. The default state path is `.hermes/state/provider-tasks`, overrideable with `HERMES_BACKGROUND_TASK_STATE_DIR`. Tampered state fails closed instead of disappearing from reconciliation. Supported nonterminal states are:

- `running`
- `verificationPending`
- `stalled`

Terminal states are `success` and `failed`.

Provider notifications are saved as `last_notification` only. They never transition a task to `success`.

Each reconciliation pass calls a provider-specific inspector. A provider-reported completion is admitted only when all of the following hold:

1. independent inspection reports terminal success;
2. evidence references are present;
3. the output hash is canonical SHA-256;
4. the configured Hermes evidence verifier accepts the evidence.

After verification, the reconciler records the result in `ExecutionStateLedger`. When a background task is bound to a durable Hermes task requirement, the same verified evidence advances `DurableTaskStateStore` automatically.

Provider failure is terminal but cannot satisfy a durable requirement. Duplicate completion is idempotent. Missing notifications do not matter because `reconcile_pending()` polls registered tasks independently. Repeated unchanged running state becomes `stalled` after the configured threshold but remains reconcilable, allowing recovery after provider reconnects or delayed wakeups.

`run_forever()` provides the external reconciliation loop. Existing Hermes supervisors may own its process lifecycle; provider adapters only supply inspectors and cannot promote their own result.

## Authority invariants

- Existing model routing remains authoritative and unchanged.
- Scout remains discovery/proposal only.
- Provider notifications are signals, not proof.
- Ordinary autonomous work gains no new human approval step.
- Existing consequential-action approval boundaries remain unchanged.
- Provider adapters cannot self-certify evidence or durable success.
- Failed, interrupted, cancelled, unverified, or stale work never becomes verified success.

## Verification

Run:

```bash
python3 -m unittest tests.test_codex_app_server tests.test_background_task_reconciler -v
bash tests/test_governed_graph_runtime.sh
```

When a local Codex CLI is installed, a non-generative handshake smoke test is also safe:

```bash
PYTHONPATH=src/system python3 - <<'PY'
import asyncio
from codex_app_server import CodexAppServerClient

async def main():
    client = CodexAppServerClient()
    try:
        await client.connect()
        print("CODEX_APP_SERVER_HANDSHAKE=PASS")
    finally:
        await client.close()

asyncio.run(main())
PY
```
