# Hermes Canary Controller

Use for bounded canary rollout, promotion monitoring, rollback trigger
evaluation, candidate freeze, previous-version restore, and rollback evidence.

## Rules

- Candidate rollout must be bounded before global activation.
- Hard rollback triggers cannot be overridden by aggregate score.
- Canary completion is `canary_passed`; it is not global promotion.
- Canary policy is immutable after start.
- Rollback restores all configured previous known-good targets through a
  transaction journal. This is crash-recoverable, not true release-unit atomic
  rollback across arbitrary paths.
- Use `release_unit` policies for versioned release directories with one atomic
  active symlink switch.
- Rollback evidence uses immutable result artifacts plus separate receipt
  artifacts.
- Disk rollback without Memory Fabric evidence is `rollback_unverified`, not
  `rolled_back`.
- Failed canary evidence is preserved.

## Commands

```bash
src/system/canary-controller.sh start --policy canary-policy.json
src/system/canary-controller.sh record --promotion-id <id> --trajectory trajectory.json
src/system/canary-controller.sh rollback --promotion-id <id> --reason "reason"
```
