# Hermes Canary Controller v1

`src/system/canary-controller.sh` is the rollout layer after Anchor Evaluator.
It prevents a validated candidate from becoming globally active immediately.

The invariant:

```text
Promotion is reversible; evidence is not.
```

Rollback preserves the failed candidate's canary history so the evolution engine
can learn from it.

## Flow

```text
anchor pass -> canary start -> telemetry record -> hard trigger check
-> rollback or canary_passed -> later promotion decision
```

## Policy

See `config/canary-policy.example.json`.

The policy records:

- `promotion_id`
- `candidate_version`
- `previous_version`
- `promotion_evidence_id`
- `anchor_report_hash`
- `canary_policy`
- `canary_started_at`
- `canary_expires_at`
- `rollback_target`
- `rollback_conditions`
- exactly one rollback mode:
  - `rollback_targets`: crash-recoverable restore of explicit paths
  - `release_unit`: atomic active-pointer rollback for versioned releases

Canary scope is bounded by:

- execution count
- time window
- explicit task set
- permitted profiles/projects
- cost ceiling
- latency ceiling
- error-rate threshold
- security classification ceiling

## Hard Rollback Triggers

- critical security failure
- mandatory-anchor regression
- classification violation
- evidence persistence failure
- error-rate threshold exceeded
- latency/cost ceiling exceeded
- explicit governance rejection

## Commands

```bash
src/system/canary-controller.sh start --policy canary-policy.json
src/system/canary-controller.sh record --promotion-id <id> --trajectory trajectory.json
src/system/canary-controller.sh rollback --promotion-id <id> --reason "governance rejected"
src/system/canary-controller.sh status --promotion-id <id>
```

## Rollback Semantics

Rollback is transaction-journaled, crash-recoverable, and idempotent across all
configured targets:

1. Validate every configured backup exists.
2. Verify every configured backup hash before replacing anything.
3. Stage every restore payload under `.hermes/canary/staging/<promotion-id>/`.
4. Freeze current live targets under `.hermes/canary/frozen/<promotion-id>/`.
5. Write a rollback-intent journal under `.hermes/canary/journals/`.
6. Replace live targets from the staged payloads.
7. Verify restored hashes when provided.
8. Mark the rollback journal `committed`.
9. Write immutable rollback result evidence.
10. Record a Memory Fabric trajectory.
11. Write a separate rollback receipt artifact.

Rollback is idempotent. If a process dies during replacement, the journal lets
the next rollback attempt finish the rollback deterministically before reporting
completion.

`rollback_targets` is not true release-unit atomicity across arbitrary paths.
There can still be a short interval where one target has been restored and
another has not.

For runtime consistency across several paths, use `release_unit`. It requires a
versioned release layout and an active symlink:

```text
releases/
  previous/
  candidate/
  active -> candidate/
```

When rollback triggers, the controller atomically swaps the active symlink to
the previous release:

```text
active -> previous/
```

The release-unit mode rejects `active_path` if it is a real directory. Runtime
code must enter the deployment through the active symlink for the atomic switch
to protect consistency.

Disk rollback and evidence persistence are separate terminal states:

- `rolled_back`: all targets restored and rollback evidence persisted to Memory
  Fabric.
- `rollback_unverified`: all targets restored, but Memory Fabric did not return
  an evidence receipt.

`rollback_unverified` is not silently treated as success. It preserves the disk
restore while flagging that governance evidence is missing.

Rollback evidence uses two artifacts:

- `rollback-result-<promotion-id>.json`: immutable rollback facts, transaction
  ID, journal hash, restored target hashes, reason, and timestamps.
- `rollback-receipt-<promotion-id>.json`: Memory Fabric receipt that points to
  the immutable result hash.

The result artifact is never rewritten after hashing. The mutable compatibility
report `rollback-<promotion-id>.json` is status output only and is not used as
the Memory Fabric evidence artifact.

## Release-Unit Policy Shape

Use `release_unit` instead of `rollback_targets` when a candidate changes more
than one runtime file:

```json
{
  "release_unit": {
    "active_path": "/opt/hermes/releases/active",
    "previous_release_path": "/opt/hermes/releases/previous",
    "candidate_release_path": "/opt/hermes/releases/candidate"
  }
}
```

Do not provide both `rollback_targets` and `release_unit` in one policy.

## Promotion Invariants

- Canary completion is not global promotion. A bounded canary that reaches its
  execution limit without violations becomes `canary_passed`; promotion remains
  a separate governed transition.
- Canary policy is immutable after start. The controller stores a normalized
  policy snapshot hash and rejects mid-run policy changes. Start a new canary to
  change scope, thresholds, rollback targets, or rollback conditions.
- Missing rollback evidence is itself a failure. A disk restore without Memory
  Fabric evidence is `rollback_unverified`, not `rolled_back`.
