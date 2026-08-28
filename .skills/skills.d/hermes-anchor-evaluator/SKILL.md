# Hermes Anchor Evaluator

Use for frozen anchor suites, incumbent-vs-candidate comparison, independent
verification, regression gates, promotion evidence, and canary readiness.

## Rules

- Evaluation is not promotion.
- Critical security or policy failures hard-fail the candidate.
- Candidate score must beat incumbent score.
- Mandatory anchors must pass.
- Evidence must persist before a candidate can be treated as validated.

## Commands

```bash
src/system/anchor-evaluator.sh run --suite anchors.json --incumbent-output incumbent.json --candidate-output candidate.json
src/system/anchor-evaluator.sh status
```
