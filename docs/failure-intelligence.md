# Hermes Failure Intelligence v1

`src/system/failure-intelligence.sh` is the analysis layer above governed
trajectory capture. It reads trajectory envelopes through the Memory Fabric
export contract, extracts failure signatures, clusters recurring failures, and
writes bounded proposal artifacts.

It is proposal-only.

```text
Memory/Trajectory Fabric -> failure normalization -> signature extraction
-> clustering -> recurrence/severity scoring -> causal hypothesis
-> bounded candidate proposal
```

## Commands

```bash
src/system/failure-intelligence.sh scan
src/system/failure-intelligence.sh clusters
src/system/failure-intelligence.sh show <cluster-id>
src/system/failure-intelligence.sh propose <cluster-id>
```

## Artifacts

By default artifacts are written under:

```text
.hermes/failure-intelligence/
```

Generated files:

- `clusters.json`
- `clusters.jsonl`
- `proposals/<proposal-id>.json`

## Signature Model

Failure Intelligence uses two identities:

- `root_signature`: normalized failure class, subsystem/operation, observed
  failure fingerprint, security compartment, and relevant action type.
- `context_signature`: model, provider, selected agent/profile/project, and
  selected skills.

Clusters are formed on `root_signature`. Context signatures are aggregated as
dimensions so Hermes can see whether a failure is cross-model, isolated to one
skill, isolated to one provider, or limited to a sensitive workload class.

`observed_failure` is normalized before hashing. Obvious volatile values such as
UUIDs, timestamps, SHA/hex values, long numeric IDs, absolute paths, durations,
and URL query strings are canonicalized so recurring failures do not split only
because request IDs or timestamps changed. The cluster preserves
`raw_observed_hashes` separately for forensic specificity.

Successful or recovered trajectories are excluded from failure clusters even if
they retain a historical `failure_class`. `rollback_unverified` remains a
failure because rollback governance evidence is incomplete.

## Cluster Schema

Each cluster includes:

- `cluster_id`
- `signature_hash`
- `root_signature_hash`
- `root_signature`
- `context_signatures`
- `context_dimensions`
- `failure_class`
- `affected_skills`
- `affected_models`
- `affected_profiles`
- `security_classifications`
- `occurrence_count`
- `first_seen`
- `last_seen`
- `severity`
- `representative_trajectory_ids`
- `successful_recoveries`
- `failed_recoveries`
- `suspected_causes`
- `confidence`

## Proposal Schema

Each proposal includes:

- `source_cluster_id`
- `root_signature`
- `evidence_trajectory_ids`
- `causal_hypothesis`
- `hypothesis_confidence`
- `target_component`
- `proposed_change`
- `affected_files_or_skills`
- `affected_paths`
- `expected_improvement`
- `possible_regressions`
- `security_classification`
- `risk_class`
- `existing_anchor_ids`
- `required_anchor_changes`
- `new_regression_tests`
- `evidence_refs`

## Governance Boundary

Failure Intelligence may propose a fix, but it may not alter the frozen success
criteria used to judge that fix.

This means:

- no automatic mutation
- no skill promotion
- no router changes
- no anchor-suite changes
- no runtime config edits

Anchor-suite maintenance remains a separate governed action. Candidate
proposals must pass Trust Gate, Anchor Evaluator, independent verification,
canary rollout, rollback safety, and Memory Fabric evidence persistence.
