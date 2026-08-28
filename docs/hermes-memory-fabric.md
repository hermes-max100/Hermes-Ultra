# Hermes Memory Fabric v1

Hermes Memory Fabric is a governed SQLite evidence graph for long-lived
Hermes/JARVIS operation. It is not an autonomous memory authority. Agents,
Scout, Trust Gate, and the skill evolver may submit evidence; durable use is
controlled by typed records, provenance, validation state, and safe retrieval
defaults.

The core invariant is:

```text
routing access != write authority
```

Router profiles may include Memory Fabric for retrieval, but that does not
grant unrestricted write authority. Durable trajectory writes go through the
ingestion policy, which validates producer identity, security classification,
status, evidence requirements, and secret redaction before appending records.

## Design

V1 uses SQLite so it can move with the repo and run in Termux, Debian, or a VPS
without extra services. It can later migrate to a graph backend because nodes
and edges are already explicit.

Node types:

- `FACT`
- `DECISION`
- `EXPERIENCE`
- `FAILURE`
- `SKILL`
- `CODE`
- `PROVENANCE`

Edge types:

- `DERIVED_FROM`
- `SUPERSEDES`
- `CAUSED`
- `RESOLVED_BY`
- `USED_SKILL`
- `AFFECTS`
- `VALIDATED_BY`

Every node stores:

- immutable `source_hash`
- `run_id`
- `agent`
- `model`
- timestamp
- confidence
- security classification
- validation state
- optional TTL
- optional supersession target
- JSON metadata

Canonical security classifications:

- `PUBLIC`
- `INTERNAL`
- `CONFIDENTIAL`
- `LEGAL_PRIVILEGED`
- `FINANCIAL`
- `CREDENTIAL`
- `SECURITY_SENSITIVE`

Classification input is normalized at the Memory Fabric boundary, so older
`internal`, `confidential`, and `restricted` values remain accepted as aliases.
Unknown classifications fail closed.

Classification flow is a lattice, not a simple numeric rank:

```text
PUBLIC
  -> INTERNAL
    -> CONFIDENTIAL
      -> LEGAL_PRIVILEGED
      -> FINANCIAL
      -> SECURITY_SENSITIVE
        -> CREDENTIAL
```

The branch classes are compartments, not interchangeable labels.
`LEGAL_PRIVILEGED -> FINANCIAL`, `FINANCIAL -> SECURITY_SENSITIVE`, and
`SECURITY_SENSITIVE -> LEGAL_PRIVILEGED` are rejected unless a future explicit
composite-class policy permits that flow.

Memory Fabric rejects invalid security flows when a record supersedes another
record. For example, both `LEGAL_PRIVILEGED -> INTERNAL` and
`LEGAL_PRIVILEGED -> FINANCIAL` are rejected. Trajectory envelopes are also
rejected when metadata declares a source/input classification that cannot flow
into the envelope classification.

`CREDENTIAL` is non-persistable except as redacted `PROVENANCE` metadata.
Credential-like values are redacted before storage.

Mutation is append-first. Corrections create new nodes and `SUPERSEDES` edges.
The prior record is marked deprecated instead of silently rewritten.

Retrieval excludes `deprecated`, `disputed`, and `untrusted` evidence by
default.

## Trajectory Fabric

Trajectory Fabric v1 adds a normalized execution envelope beside the legacy
trajectory table. Producers submit:

- `trust-gate`
- `external-source-sweep`
- `video-watch`
- `hermes-dispatch`
- `skill-evolver`
- `anchor-evaluator`
- `canary-controller`

Envelope core:

- `trajectory_id`
- `run_id`
- `parent_run_id`
- `timestamp`
- `producer`
- `objective`
- `input_hash`
- `selected_agent`
- `selected_skills`
- `model`
- `actions`
- `predicted_outcome`
- `observed_outcome`
- `status`
- `failure_class`
- `evidence_refs`
- `memory_refs`
- `security_classification`
- `duration_ms`
- `cost`
- `metadata`

The ingestion policy rejects unknown producers and unsupported security
classifications. It also requires `evidence_refs` for claims that a candidate is
`allow`, `trusted_candidate`, `validated`, or `promoted`, or when metadata marks
the record as a validation, promotion, or safety claim.

Secret-like fields and values are redacted before storage. Keys matching tokens,
passwords, cookies, credentials, authorization headers, API keys, OTPs, sessions,
or secrets are replaced with `[REDACTED_SECRET]`.

## Commands

```bash
src/system/memory-fabric.sh init
src/system/memory-fabric.sh status
src/system/memory-fabric.sh add-node \
  --type DECISION \
  --title "Trust Gate promotion boundary" \
  --body "Scout discovers; Trust Gate evaluates; governance promotes." \
  --validation-state validated \
  --confidence 0.95

src/system/memory-fabric.sh record-trajectory \
  --objective skill-evolution \
  --status promoted \
  --skill legal-evidence-os \
  --proposal-id 20260815T000000Z-amazon-appeal-legal-evidence-os \
  --evidence-refs '[".skills/proposals/.../proposal.env"]' \
  --observed "proposal promoted after validation"

src/system/memory-fabric.sh ingest-trajectory --json-file trajectory.json
src/system/memory-fabric.sh list-trajectories --producer trust-gate
src/system/memory-fabric.sh retrieve "routing regression" --type FAILURE
```

## Skill Evolver Integration

`src/system/skill-evolver.sh` records proposal, validation, promotion, and
rejection trajectories. Proposal and rejection records are best-effort because
they do not mutate live skills. Validation and promotion records are fail-closed:
if Memory Fabric cannot persist the evidence, the evolver refuses to claim that
a candidate is validated or promoted.

This sets up the larger loop:

```text
execution -> trajectory -> Memory Fabric -> repeated-failure detection
-> proposal -> Trust Gate -> sandbox evaluation -> anchor suite
-> independent verifier -> canary -> promotion -> Memory Fabric writeback
```
