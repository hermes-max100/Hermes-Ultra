# Hermes Failure Intelligence

Use this skill when work involves recurring failure analysis, trajectory
clustering, failure signatures, recurrence/severity scoring, recovery evidence,
or bounded candidate proposals derived from Memory Fabric trajectories.

## Operating Rules

- Failure Intelligence is analysis-only and proposal-only.
- It may read governed Memory Fabric trajectory envelopes.
- It may write local cluster and proposal artifacts.
- It must not modify skills, anchors, routing, runtime config, MCP config, or
  promotion state.
- It must not redefine success criteria. Anchor-suite changes require a
  separate governed action.
- Proposals must include evidence references, causal hypothesis, expected
  improvement, risk class, and new regression tests.
- Any proposed fix still requires Trust Gate, Anchor Evaluator, independent
  verifier, canary rollout, rollback safety, and Memory Fabric evidence.

## Commands

```bash
src/system/failure-intelligence.sh scan
src/system/failure-intelligence.sh clusters
src/system/failure-intelligence.sh show <cluster-id>
src/system/failure-intelligence.sh propose <cluster-id>
```

## Use With

- `hermes-memory-fabric` for governed trajectory evidence.
- `hermes-jarvis-self-evolution` for bounded proposal handling.
- `hermes-trust-gate`, `hermes-anchor-evaluator`, and
  `hermes-canary-controller` before any candidate can be promoted.
