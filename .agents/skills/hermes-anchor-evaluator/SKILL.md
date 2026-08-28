# Hermes Anchor Evaluator

Use this skill when work involves candidate-vs-incumbent evaluation, frozen
anchor suites, independent verification, promotion evidence, canary readiness,
or regression gates for Hermes/JARVIS self-evolution.

## Operating Rules

- The evaluator cannot promote candidates.
- Candidate and incumbent must be compared against the same anchor suite.
- Critical failures are hard failures, regardless of aggregate score.
- Security classification must be preserved; downgrades fail.
- Validation and promotion claims require persisted evidence.
- Independent verification emits a judgment artifact only; it cannot mutate the
  candidate or runtime.

## Commands

```bash
src/system/anchor-evaluator.sh run \
  --suite config/anchor-suite.example.json \
  --incumbent-output incumbent.json \
  --candidate-output candidate.json

src/system/anchor-evaluator.sh status
```

## Use With

- `hermes-memory-fabric` for governed evaluation trajectory storage.
- `hermes-trust-gate` for supply-chain review before evaluation.
- `hermes-jarvis-self-evolution` for proposal validation and promotion flow.
