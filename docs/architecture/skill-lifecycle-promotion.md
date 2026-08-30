# Hermes Ultra Governed Skill Lifecycle

Hermes Ultra treats public skill catalogs and MCP directories as discovery inputs, never trust roots. A listing can create a discovered candidate; it cannot install or activate code.

## State machine

`discovered -> quarantined -> candidate -> trusted -> installed_disabled -> canary -> active`

`canary -> rolled_back` and `active -> rolled_back` are always available. A rolled-back capability may return only to `installed_disabled` for renewed review.

## Required promotion evidence

A candidate must carry repository provenance, a full 40-character commit SHA, a declared license, discovery source, authority profile, capability signature, evidence contract, and rollback definition.

The validation gate is fail closed. Structural validation, link validation, contamination analysis, secret scanning, dependency scanning, license validation, provenance validation, permission declaration, evidence-contract validation, and rollback readiness must all pass.

`skill-validator check --strict` is the external structural/content validator boundary. Non-zero exit status is rejection. Hermes does not shell-interpolate candidate paths.

`coder-eval` is the external behavior-evaluation boundary. Hermes disables Coder Eval usage telemetry by setting `TELEMETRY_ENABLED=false`. A non-zero evaluation exit status is a benchmark regression.

## Promotion policy

Passing validation is necessary but insufficient. Candidate evaluation must satisfy minimum success and test-pass thresholds, produce no wrong-file edits or regressions, have complete evidence, and strictly improve the aggregate evaluation score without quality regression relative to the baseline.

Capability overlap is measured before trust promotion. Near-exact duplicates are blocked. Significant partial overlap requires review instead of silently multiplying specialist agents.

A successful evaluation promotes only to `trusted`. It never installs or activates the capability.

## Authority and activation

Installation is disabled-by-default and requires review approval. Canary execution requires review approval; capabilities requesting consequential authority such as Git writes, credential access, external sends, or financial actions also require explicit authority approval.

Activation requires a passed canary and verified rollback readiness. This keeps economic, communication, credential, and repository authority separate from skill quality.

## Receipts

Every lifecycle transition produces a SHA-256 receipt over canonical transition data, including candidate identity, source provenance, authority declaration, old state, new state, timestamp, and reason.

`ImmutableReceiptStore` writes receipts create-only by receipt hash. Existing receipts are never overwritten. Receipt verification detects payload tampering.

## Discovery sources

The default discovery registry includes Awesome Codex Skills, Awesome Codex Subagents, Awesome MCP Servers, sindresorhus/awesome, Skill Validator, Coder Eval, Horizon, and NotebookLM-py. Every default source is `discovery_only=true` and `auto_install=false`.

NotebookLM-py remains an optional research adapter, not an authentication provider. Browser-session credential extraction and replay are outside this lifecycle and remain prohibited by the existing Hermes authentication policy.
