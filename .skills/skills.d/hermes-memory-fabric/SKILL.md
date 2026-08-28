# Hermes Memory Fabric

Use for governed Hermes/JARVIS memory, trajectory storage, trajectory
ingestion, evidence graph retrieval, failure history, and promotion provenance.

## Rules

- Store evidence with type, source hash, confidence, validation state, and
  security classification.
- Use append-first correction through supersession.
- Exclude deprecated, disputed, and untrusted evidence by default.
- Never store secrets, tokens, OTPs, cookies, passwords, or raw credentials.
- Routing access is not write authority.
- Validation, promotion, and safety claims require evidence references.

## Commands

```bash
src/system/memory-fabric.sh status
src/system/memory-fabric.sh record-trajectory --objective skill-evolution --status promoted
src/system/memory-fabric.sh ingest-trajectory --json-file trajectory.json
src/system/memory-fabric.sh list-trajectories --producer trust-gate
src/system/memory-fabric.sh retrieve "prior routing regression"
```
