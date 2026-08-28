# Hermes Execution-State Ledger and Durable Continuation

Hermes separates **current execution state** from **durable verified task progress**. Neither mechanism changes model routing, Scout authority, or approval boundaries.

## Execution-state ledger

`src/system/execution_state.py` provides `ExecutionStateLedger`, an in-process deterministic ledger for observations, mutations, and operation attempts.

Observations contain a caller-supplied resource fingerprint and source. A mutation refreshes that resource and automatically marks dependent observations stale. Successful operations may be reused only when the operation arguments match and every declared required resource is still fresh at the same fingerprint.

The ledger never asks a model whether state is fresh. Filesystem, process, Git, tool, or other trusted runtime adapters supply the fingerprints and mutation events.

Graph-level reuse is opt-in with node metadata:

```json
{
  "metadata": {
    "execution_state_reusable": true
  }
}
```

Without that explicit contract, the graph records execution state but executes the node normally. This prevents an externally observing root task from becoming stale simply because its graph inputs did not change.

Programmatic tool steps can declare state dependencies:

```json
{
  "tool": "inspect_repo",
  "args": {},
  "requires": ["repo"],
  "mutates": []
}
```

Read-only steps with declared `requires` may reuse an identical prior success while those resources remain fresh. Steps declaring `mutates` always execute. A step with no state dependencies is not reused by default; it must explicitly set `"reusable": true` if the caller can prove that is correct.

## Durable long-horizon state

`DurableTaskStateStore` persists only the compact task state needed to resume work:

- original objective;
- complete requirement contract;
- evidence-backed completed requirements;
- remaining requirements;
- verified environment state;
- rejected/failed attempts;
- next executable subtask;
- content hash.

Files are written atomically and fsynced. Every load recomputes the content hash and fails closed on tampering or corruption.

A graph opts into durable continuation through plan metadata:

```json
{
  "metadata": {
    "long_horizon": {
      "task_id": "upgrade-2026-08",
      "objective": "Finish the repository upgrade",
      "requirements": [
        {"id": "build", "text": "Implementation complete"},
        {"id": "verify", "text": "Verification passes"}
      ]
    }
  }
}
```

A node can satisfy one durable requirement only after ordinary Hermes output verification succeeds:

```json
{
  "require_evidence": true,
  "metadata": {
    "completes_requirement": "build",
    "environment_fields": ["git_head"],
    "next_subtask": "Run verification"
  }
}
```

`completes_requirement` requires `require_evidence=true`. The runtime uses the verified node output hash and evidence receipts when admitting progress. A rejected or failed node is recorded as an attempted requirement but never moves that requirement into the completed set.

## Fresh-context execution

Before every actual handler attempt, the runtime constructs a new `NodeContext.continuation_state` directly from the durable store. It contains compact accepted state, not prior conversation messages or an accumulated transcript.

The handler therefore receives the current objective, completed and remaining requirements, environment state, rejected attempts, and next subtask without dragging an ever-growing reasoning history into the next execution round.

`NodeContext.execution_state` separately exposes a compact snapshot of current runtime observations and attempts for adapters that need it.

## Authority invariants

- Existing Hermes routing is unchanged and remains authoritative.
- Durable progress is admitted only after the existing schema/trust/evidence/provenance/policy verification path accepts a node output.
- State freshness is determined by runtime events and fingerprints, not model assertions.
- Scout remains discovery/proposal only.
- No routine human approval is added.
- Existing approval-required consequential actions retain their existing authority boundary.
