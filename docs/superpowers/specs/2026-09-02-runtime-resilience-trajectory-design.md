# Runtime Resilience and Trajectory Adaptation

## Status

Approved for implementation on 2026-09-01 and implemented on `ai/runtime-resilience-trajectory`.

## Goals

1. Detect Relay replay discontinuities before incomplete state is accepted as lossless.
2. Rebuild from authoritative session state after replay truncation, replay-epoch change, or unseen sequence regression.
3. Keep cloud provider context/output limits provider-scoped so local Ollama settings cannot cap cloud sessions.
4. Ensure token-limit retries actually submit the corrected output cap and remain bounded.
5. Measure autonomous execution trajectories for repetition, exploration, exploitation, entropy, complexity, success, and near misses.
6. Emit automatic adaptation signals without adding routine human approval.

## Replay integrity

`RelayEventDeduper` now tracks replay epoch per `(session_id, run_id)` in addition to sequence state. Exact duplicates remain harmlessly rejected. Truncation, epoch changes, and unseen sequence regression mark the stream `requires_rebuild` and block subsequent events until `acknowledge_rebuild(...)` is called after authoritative session reconstruction.

This converts silent incomplete replay into explicit automatic recovery. The replay detector does not become a second session store; the durable/session evidence system remains the recovery authority.

## Provider-scoped limits

`ProviderRequestPolicy` resolves context and output limits from provider/model metadata first. Only explicitly local providers may fall back to local-runtime settings such as `ollama_num_ctx`.

`hermes-run.sh` uses this policy for the real OpenAI-compatible request path. Limit-related HTTP errors may trigger a small bounded retry budget. Each retry is generated as a new payload with a stricter corrected output cap actually written into the submitted request. No unbounded retry loop is introduced.

## Trajectory adaptation

`TrajectoryEvaluator` computes deterministic host-side metrics from action sequences:

- success and failure ratios,
- repetition ratio,
- Shannon entropy,
- normalized entropy,
- LZ-style trajectory complexity,
- exploration error,
- exploitation error,
- policy-near-miss ratio.

The evaluator returns one of `continue`, `narrow`, or `reroute`. These are adaptation signals, not permissions. Hermes dispatch persists them into its existing Memory Fabric trajectory metadata. Long-running loops may supply their accumulated action sequence through `HERMES_TRAJECTORY_ACTIONS_JSON`; ordinary dispatches use the current route action.

## Authority invariants

- Scout remains discovery/proposal-only.
- Governance remains authority over trusted, installed, canary, active, and runtime-enabled states.
- Existing approval-required categories remain unchanged.
- Replay recovery, output-cap correction, narrowing, and rerouting require no routine human approval.
- Trajectory metrics cannot authorize otherwise prohibited actions.
- No production deployment is performed by this change.

## Verification requirements

- RED contracts must fail because the new modules/behaviors are absent before implementation.
- Full Python test workflow must pass after implementation.
- Governed graph runtime validation must pass.
- Cloud foundation validation and deterministic release integrity checks must pass.
- Source and repository secret scans must remain green.
- Final PR merge-ref must be checked against current `main` immediately before merge.
