# Hermes Candidate Generator

Use this skill when work involves turning a Failure Intelligence cluster into a
governed candidate package, manifest, regression-test spec, or candidate receipt.

## Operating Rules

- Candidate Generator is package-only.
- It may read Failure Intelligence cluster artifacts.
- It may write local candidate package artifacts.
- It must not modify source files, skills, anchors, routing, runtime config,
  MCP config, or promotion state.
- It must not redefine success criteria.
- `required_anchor_changes` must remain empty for automatic candidates.
- Benchmark gaps require a separate benchmark-gap proposal.
- Regression test specs should be generated from failure evidence before or
  independently from the candidate implementation spec.
- Candidate packages must still pass Trust Gate, sandbox tests, Anchor
  Evaluator, independent verifier, canary rollout, rollback safety, and Memory
  Fabric evidence persistence.

## Commands

```bash
src/system/candidate-generator.sh generate <cluster-id>
```

## Use With

- `hermes-failure-intelligence` for source clusters.
- `hermes-memory-fabric` for trajectory/evidence provenance.
- `hermes-jarvis-self-evolution` for bounded proposal handling.
