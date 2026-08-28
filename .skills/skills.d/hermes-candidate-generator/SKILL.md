# Hermes Candidate Generator

Use for creating governed candidate packages from Failure Intelligence clusters.

## Rules

- Package-only; no source, skill, anchor, routing, runtime, or promotion edits.
- Reads Failure Intelligence cluster artifacts.
- Writes local manifest, regression-test spec, and receipt artifacts.
- Does not redefine success criteria.
- `required_anchor_changes` stays empty for automatic candidates.
- Benchmark gaps require a separate governed benchmark-gap proposal.

## Commands

```bash
src/system/candidate-generator.sh generate <cluster-id>
```
