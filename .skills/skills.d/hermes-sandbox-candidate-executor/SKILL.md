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

## Boundary

This skill produces sandbox evidence only. It does not commit, validate,
promote, activate, or mutate the live checkout.

`sandbox_passed` remains below `trusted`, `validated`, and `promoted` in the
governance chain.
