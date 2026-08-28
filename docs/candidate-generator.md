# Hermes Candidate Generator v1

`src/system/candidate-generator.sh` creates governed candidate packages from
Failure Intelligence clusters.

It is not a patch applier.

```text
failure cluster -> representative failures -> causal hypothesis
-> regression test spec -> candidate manifest -> Trust Gate/sandbox path
```

## Command

```bash
src/system/candidate-generator.sh generate <cluster-id>
```

## Artifacts

By default packages are written under:

```text
.hermes/candidates/
```

Each generation creates a unique immutable package directory:

```text
.hermes/candidates/cand_<candidate-id>/
```

Each package contains:

- `regression-test-spec.json`
- `candidate-manifest.json`
- `candidate-receipt.json`

Artifacts are first written to a temporary staging directory and then moved into
place. If the final package directory already exists, generation fails closed
instead of overwriting it.

## Manifest Fields

The candidate manifest includes:

- `candidate_id`
- `source_cluster_id`
- `root_signature_hash`
- `source_trajectory_ids`
- `source_evidence_hashes`
- `causal_hypothesis`
- `hypothesis_confidence`
- `target_component`
- `change_type`
- `affected_paths`
- `base_version_hashes`
- `proposed_diff`
- `new_regression_tests`
- `expected_improvement`
- `possible_regressions`
- `security_classification`
- `risk_class`
- `existing_anchor_ids`
- `required_anchor_changes`
- `generator_model`
- `generator_version`
- `generated_at`
- `candidate_manifest_hash`

`candidate_manifest_hash` is the SHA-256 hash over canonical manifest JSON with
the `candidate_manifest_hash` field omitted. This is recorded explicitly in
`candidate_manifest_hash_scope` so verifiers do not hash the final file bytes and
mistake the self-hash field for tampering.

## Governance Boundary

Candidate Generator v1 writes proposal packages only.

It must not:

- modify source files
- modify skills
- modify anchors or frozen success criteria
- modify routing/model policy
- modify runtime config
- promote a candidate

`required_anchor_changes` is structurally empty for automatic candidates. If the
failure evidence suggests that a benchmark is missing or deficient, emit a
separate benchmark-gap proposal in a governed benchmark-maintenance workflow.

Regression specs are generated before the candidate implementation spec so the
test is anchored in failure evidence rather than in the proposed fix.
