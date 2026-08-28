# Hermes Failure Intelligence

Use for recurring failure analysis, trajectory clustering, recurrence/severity
scoring, recovery evidence review, and bounded proposal drafts.

## Rules

- Analysis-only and proposal-only.
- Reads governed Memory Fabric trajectories.
- Writes local cluster/proposal artifacts.
- Does not modify skills, anchors, routing, runtime config, or promotion state.
- Does not redefine success criteria.
- Proposals still require Trust Gate, Anchor Evaluator, independent verifier,
  canary, rollback safety, and Memory Fabric evidence.

## Commands

```bash
src/system/failure-intelligence.sh scan
src/system/failure-intelligence.sh clusters
src/system/failure-intelligence.sh show <cluster-id>
src/system/failure-intelligence.sh propose <cluster-id>
```
