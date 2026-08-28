# Hermes Canary Controller

Use this skill when work involves bounded canary execution, promotion rollout,
rollback conditions, previous-version restore, candidate freeze, or rollback
evidence for Hermes/JARVIS self-evolution.

## Operating Rules

- Promotion is reversible; evidence is not.
- Candidates never become globally active immediately.
- Canary scope must be bounded by execution count, time window, profile/project
  scope, cost, latency, and security classification.
- Critical security failures, mandatory-anchor regressions, classification
  violations, evidence persistence failures, cost/latency ceiling breaches, and
  governance rejections trigger rollback.
- Rollback must be transaction-journaled, crash-recoverable, and idempotent
  across configured targets.
- Do not describe arbitrary multi-target file restore as true atomic rollback.
  Use `release_unit` policies for versioned release directories with one atomic
  active symlink switch.
- Do not delete failed candidate history after rollback.
- Rollback evidence must use immutable result artifacts plus separate receipt
  artifacts; do not persist hashes for rollback reports that will be rewritten.
- Canary completion is `canary_passed`; it is not global promotion.
- Canary policy must be immutable after start. Start a new canary to change
  scope, thresholds, targets, or rollback conditions.
- If disk rollback succeeds but Memory Fabric evidence persistence fails, state
  is `rollback_unverified`, not `rolled_back`.

## Commands

```bash
src/system/canary-controller.sh start --policy canary-policy.json
src/system/canary-controller.sh record --promotion-id <id> --trajectory trajectory.json
src/system/canary-controller.sh rollback --promotion-id <id> --reason "reason"
src/system/canary-controller.sh status --promotion-id <id>
```

## Use With

- `hermes-anchor-evaluator` before starting canary.
- `hermes-memory-fabric` for immutable canary and rollback trajectories.
- `hermes-jarvis-self-evolution` for promotion governance.
