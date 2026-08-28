---
name: hermes-sandbox-candidate-executor
description: Execute explicit Hermes candidate patches in disposable Git worktrees and emit governed sandbox evidence.
---

# Hermes Sandbox Candidate Executor

Use this skill when a governed candidate package needs isolated execution before
Trust Gate, Anchor Evaluator, verifier, canary, or promotion.

## Driver

```bash
src/system/sandbox-candidate-executor.sh .hermes/candidates/cand_<id>
```

## Role

This skill completes the self-evolution v1 loop from candidate package to
evidence-bearing patch bundle.

It may:

- verify candidate package hashes
- create disposable detached Git worktrees
- apply explicit bounded patches inside the sandbox
- run candidate regression specs
- run affected subsystem tests
- run mandatory governance regressions
- produce immutable sandbox result artifacts
- persist sandbox evidence through Memory Fabric
- hand the sandbox result bundle to Trust Gate

It must not:

- edit the live checkout
- commit
- promote
- modify runtime state
- alter anchors or success criteria
- weaken Trust Gate, Memory Fabric, Anchor Evaluator, Canary/Rollback, or
  approval policy

## Required Boundary

`sandbox_passed` means only that the explicit patch survived isolated execution.
It does not mean the candidate is trusted, validated, promoted, or active.

The next required gates are:

```text
Sandbox Candidate Executor
-> Trust Gate
-> Anchor Evaluator
-> independent verifier
-> Canary Controller
-> governed promotion
```

## Protected Paths

Protected governance paths are rejected by default. Use
`--allow-governance-paths` only for a separately authorized governance-specific
candidate.
