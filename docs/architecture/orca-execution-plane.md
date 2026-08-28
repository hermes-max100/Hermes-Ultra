# Hermes Ultra — Orca Development Execution Plane

## Decision

Hermes remains the routing, governance, evidence, verification, and promotion authority. `stablyai/orca` is an execution substrate for developer work only.

- **Hermes decides** which agent is used and what authority category applies.
- **Orca executes** worktree/terminal/agent mechanics.
- **Hermes verifies** tests, policy checks, evidence completeness, and promotion.
- Orca output, terminal-idle state, or a worker completion claim is never equivalent to Hermes success.

## Authority boundary

The Orca plane is fail-closed. Its default allowlist is limited to reversible developer actions such as code edits, tests, linting, builds, static analysis, repository search, diffs, commits, documentation, benchmarks, and development browser work.

Production deployment/deletion, credentials, financial actions, legal filing or service, settlement, and external communications are outside Orca authority.

## Canonical interface

Use `hermes_ultra.orca` (or `hermes_ultra.integrations.orca`) for new work. The earlier `swarm.OrcaAdapter` remains a compatibility prototype until callers are migrated; it is not the authority boundary described here.

## Current integration mode

`HermesOrcaRuntime` uses the stable JSON CLI surface:

1. `orca status --json`
2. agent-first `orca worktree create`
3. `orca terminal wait --for tui-idle`
4. `orca terminal send`
5. a second idle observation
6. `orca terminal read`
7. Hermes evidence recording
8. independent Hermes verification

The client understands current Orca terminal handle fields (`agentTerminalHandle`, `startupTerminal.handle`) and retains legacy response fallbacks. If the create response omits a handle, it performs a bounded `terminal list` recovery and fails when a unique agent terminal cannot be proven.

## Experimental orchestration

Orca's structured Run/Task/Dispatch/Worker orchestration is useful, but it remains experimental upstream. Hermes does not make it its canonical state machine.

The current production integration therefore keeps Hermes orchestration authoritative and does not enable automatic promotion or consequential authority through Orca orchestration receipts.

When upstream worker-start/task-DAG reliability is demonstrated by regression tests, structured Orca orchestration can be added behind this same policy and evidence boundary without changing Hermes authority semantics.

## Telemetry and network deployment

On Hermes-managed hosts:

```bash
export DO_NOT_TRACK=1
export ORCA_TELEMETRY_DISABLED=1
```

Run the Orca server only on a private management path such as Tailscale. Do not expose its control port directly to the public internet.

## Invariant

> `ORCA worker_done != HERMES success`

Hermes success requires independent verification and a separate Hermes promotion decision.
