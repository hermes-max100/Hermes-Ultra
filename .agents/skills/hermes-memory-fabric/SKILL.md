# Hermes Memory Fabric

Use this skill when work involves durable Hermes/JARVIS memory, governed
trajectory capture, evidence provenance, repeated-failure analysis, promotion
history, or graph-backed retrieval.

## Operating Rules

- Treat the Memory Fabric as an evidence store, not an autonomous authority.
- Add records with source, confidence, validation state, and security
  classification.
- Prefer append-first corrections using `SUPERSEDES`; do not silently rewrite
  prior evidence.
- Retrieval must exclude deprecated, disputed, and untrusted evidence unless the
  user explicitly asks for an audit view.
- Do not store secrets, credentials, OTPs, cookies, raw tokens, or private
  session material.
- Routing access is not write authority. Producer writes must use governed
  trajectory ingestion.
- Validation, promotion, and safety claims require evidence references.

## Commands

```bash
src/system/memory-fabric.sh status
src/system/memory-fabric.sh add-node --type FACT --title "..." --body "..."
src/system/memory-fabric.sh record-trajectory --objective "..." --status "..."
src/system/memory-fabric.sh ingest-trajectory --json-file trajectory.json
src/system/memory-fabric.sh list-trajectories --producer trust-gate
src/system/memory-fabric.sh export-trajectories --failures-only --jsonl
src/system/memory-fabric.sh retrieve "query"
```

## Use With

- `hermes-trust-gate` for source/candidate provenance.
- `hermes-jarvis-self-evolution` for proposal and promotion trajectories.
- `codebase-memory-mcp` for code graph sources that should become governed
  `CODE` or `PROVENANCE` nodes.
