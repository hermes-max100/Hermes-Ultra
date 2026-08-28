# Hermes Anchor Evaluator v1

`src/system/anchor-evaluator.sh` compares an incumbent output and a candidate
output against the same immutable anchor suite. It is an evaluation gate, not a
promotion tool.

The promotion rule is hard-gated:

```text
candidate_score > incumbent_score
AND zero critical regressions
AND zero security-policy failures
AND all mandatory anchors pass
AND independent_verifier = pass
AND evidence persisted successfully
```

No aggregate score can compensate for a critical failure. A candidate with a
forbidden action, classification downgrade, or forbidden failure predicate fails
even if its numeric score is otherwise high.

Security classification checks use the Hermes compartment lattice. Branch
classes are not interchangeable: `LEGAL_PRIVILEGED`, `FINANCIAL`, and
`SECURITY_SENSITIVE` do not satisfy one another merely because they have similar
sensitivity. A lateral compartment flow is a critical failure.

## Anchor Schema

Each anchor contains:

- `anchor_id`
- `version`
- `objective`
- `input_fixture_hash`
- `expected_invariants`
- `expected_evidence`
- `forbidden_actions`
- `security_classification`
- `success_predicates`
- `failure_predicates`
- `max_cost`
- `max_latency`
- `mandatory`

See `config/anchor-suite.example.json`.

## Output Schema

The incumbent and candidate output files are JSON objects. Recommended fields:

- `version`
- `security_classification`
- `latency_ms`
- `cost`
- `actions`
- `output`
- `artifacts`
- `evidence_refs`
- `citations`

## Commands

```bash
src/system/anchor-evaluator.sh run \
  --suite config/anchor-suite.example.json \
  --incumbent-output incumbent.json \
  --candidate-output candidate.json

src/system/anchor-evaluator.sh status
```

The evaluator writes signed local artifacts under
`.hermes/reports/anchor-evaluator/` and records a governed Memory Fabric
trajectory as producer `anchor-evaluator`.

## Independent Verifier

By default, v1 uses the deterministic local gate as the verifier floor. An
external verifier can be supplied:

```bash
src/system/anchor-evaluator.sh run \
  --suite anchors.json \
  --incumbent-output incumbent.json \
  --candidate-output candidate.json \
  --verifier-command ./verify-anchor-report
```

The verifier command receives the report JSON path and must print JSON:

```json
{"verdict": "pass"}
```

or:

```json
{"verdict": "fail", "reason": "unsupported evidence"}
```

The verifier cannot modify the candidate and cannot promote.

## Rollback Fields

Every report includes:

- `candidate_version`
- `previous_version`
- `promotion_evidence_id`
- `rollback_target`
- `canary_window`
- `rollback_conditions`

Canary execution and automatic rollback are the next promotion-layer milestone.
