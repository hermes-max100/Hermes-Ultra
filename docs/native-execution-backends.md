# Native Execution Backends

Hermes may use optional execution accelerators beneath the governed graph. They do not select models, change routing, promote capabilities, or expand tool authority.

## Programmatic tool executor

`ProgrammaticToolExecutor` executes a caller-supplied bounded sequence of already-authorized tools. Intermediate results can be referenced by later steps with `{"$ref":"name.field"}`. The executor records the concrete tool trace and rejects tools outside the caller's allowlist or plans above the configured call bound. When supplied an `ExecutionStateLedger`, read-only steps can declare `requires` resources and reuse identical prior success only while those fingerprints remain fresh. Mutating steps always execute and emit deterministic mutation fingerprints.

Use it when a graph node contains deterministic tool work that does not need fresh model judgment between calls. Return to the normal graph/model loop whenever judgment is required.

## Native multi-agent executor

`NativeMultiAgentExecutor` runs caller-supplied independent subtasks concurrently up to a fixed subagent limit and performs one synthesis step. Hermes retains graph lifecycle, retries, verification, evidence, memory, routing, and promotion authority.

Provider-specific adapters can wrap official subscription/OAuth or API capabilities later without changing this contract.

## Invariants

- Existing Hermes routing remains untouched and authoritative.
- Executors receive authority; they do not create authority.
- No new approval is introduced for ordinary autonomous work.
- Existing approval-required categories remain outside these executors unless already authorized by their governing caller.
- Scout remains discovery/proposal only; these executors cannot promote Scout candidates.
