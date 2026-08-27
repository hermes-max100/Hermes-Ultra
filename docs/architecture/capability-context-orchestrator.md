# Capability + Context Orchestrator

The Capability + Context Orchestrator is an additive layer above the existing Hermes model router. It improves task preparation, evidence use, and tool escalation without becoming a replacement router or an approval system.

## Position in the stack

```text
TASK
  |
  v
Capability + Context Orchestrator
  |
  |-- classify capability requirements
  |-- assemble bounded relevant context
  |-- call existing Hermes router (quality_first=true)
  |-- execute selected model
  |-- verify result
  |-- escalate tools only when evidence is insufficient
  |-- write verified result to memory
  |
  v
Existing Hermes Model / Subscription Router
  |
  +-- subscription-authenticated lanes
  +-- free/provider endpoints
  +-- governed API fallbacks
```

The existing router remains the only component responsible for model/provider selection. This module contains no provider ranking table, no pricing optimization, and no credential/session handling.

## Capability resolution

The built-in deterministic classifier recognizes these capability labels:

- `reasoning`
- `coding`
- `research`
- `long_context`
- `vision`
- `audio`
- `tool_use`
- `speed`
- `files`
- `compute`
- `connectors`
- `specialist`

Every task starts with `reasoning`. Explicit task hints are honored first; conservative keyword inference supplements them. Tool-oriented capabilities automatically imply `tool_use`.

`quality_first` defaults to `true`. The orchestrator does not introduce a cost-first decision path.

## Context hygiene

`ContextBuilder` always preserves the current task and then selects additional context by priority until the configured token budget is full.

Typical sources are:

```text
current task                 always retained
relevant evidence            high priority
recent tool results          high priority
relevant memories            medium/high priority
previous task state          medium priority
stale/unrelated history      dropped first
```

Context items are deduplicated by key. If two sources provide the same key, the higher-priority item wins. Dropped keys are surfaced in result metadata so context reduction is observable rather than silent.

The task itself is never truncated merely to satisfy the configured context budget. If the task alone exceeds that budget, the effective budget expands enough to preserve the task while lower-value context remains bounded.

## Tool escalation graph

Tool escalation is evidence-driven rather than a blanket preflight gate.

```text
MODEL ANSWER
    |
    v
VERIFY
    |
    +-- accepted ------------------------------> MEMORY WRITEBACK -> RESULT
    |
    +-- rejected, evidence sufficient --------> explicit recoverable failure
    |
    +-- insufficient evidence
            |
            +-- files ----------> FILE RETRIEVAL
            +-- research -------> SEARCH -> DEEP RESEARCH
            +-- coding/compute -> CODE EXECUTION
            +-- connectors -----> CONNECTOR
            +-- specialist -----> SPECIALIST
                                      |
                                      v
                                rebuild context
                                      |
                                      v
                                  ROUTER + MODEL
```

A recoverable tool failure does not stop ordinary work. The policy advances to the next eligible step automatically. A non-recoverable tool failure is returned explicitly.

## Verification

The injected verifier is authoritative for whether a model result is accepted and whether more evidence is needed. The orchestrator never reports success after a rejected verification.

If evidence remains insufficient after the configured escalation budget is exhausted, the result is `EVIDENCE_INCOMPLETE` with the attempted escalation steps recorded in metadata.

## Memory writeback

Verified responses can be sent to an injected memory writer. Memory write failure does not erase an otherwise verified task result; it is reported in result metadata and `memory_written=false`.

This keeps memory useful without turning memory availability into a routine stop condition.

## Autonomy boundary

This component does not import or own `ApprovalRegistry` and does not create approval categories.

It therefore cannot convert any of the following into a new human-approval requirement:

- provider unfamiliarity;
- authentication state;
- tool escalation;
- context fallback;
- research/deep research;
- memory writeback;
- verification;
- ordinary coding or analysis.

High-consequence action approval remains where it already exists in Hermes policy and is evaluated only when the specific action is exercised.

## Integration

`HermesUltraOrchestrator` accepts an optional `capability_context` dependency and exposes `run_task(task)` as the generic entry point. Existing `run_coding_task`, `run_research_task`, and `run_media_job` paths are unchanged.

Example composition:

```python
from hermes_ultra import (
    CapabilityContextOrchestrator,
    HermesUltraOrchestrator,
    TaskSpec,
)

capability_context = CapabilityContextOrchestrator(
    router=existing_subscription_router,
    model_executor=model_executor,
    verifier=result_verifier,
    context_sources=(memory_source, evidence_source),
    tool_executor=tool_executor,
    memory_writer=memory_writer,
)

hermes = HermesUltraOrchestrator(capability_context=capability_context)

result = hermes.run_task(
    TaskSpec(
        task_id="task-123",
        objective="Research the current upstream API and propose the code change.",
        capability_hints=frozenset({"research", "coding"}),
    )
)
```

## Tests

`tests/test_capability_context.py` covers:

- deterministic capability classification;
- quality-first delegation to the existing router;
- context-budget prioritization;
- automatic search escalation;
- recoverable search -> deep-research fallback;
- explicit evidence-incomplete failure after exhaustion;
- memory writeback after verification;
- delegation from the existing Hermes Ultra orchestrator.
