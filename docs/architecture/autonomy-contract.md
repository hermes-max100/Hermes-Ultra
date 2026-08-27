# Hermes Ultra Autonomy Contract

## Rule

Hermes Ultra is autonomous by default. Hardening supports execution; it does not become a routine human-interruption mechanism.

An operation may require human approval only when the operation itself matches an explicit high-consequence category already registered in Hermes policy. Integrations may not invent additional approval categories from generic risk labels, provider unfamiliarity, authenticated access, health-check failures, provenance state, or the presence of external content.

## Ordinary Autonomous Operations

These operations remain autonomous unless the operation itself is classified under an existing high-consequence category:

- research and source discovery;
- authenticated research using already configured owner-controlled credentials/session state;
- code analysis and repository indexing;
- agent/model selection through the existing Hermes router;
- worktree creation and worker execution;
- code editing inside isolated worktrees;
- testing, linting, static analysis, and impact analysis;
- retries, backoff, fallback selection, and degraded-mode continuation;
- reversible internal configuration changes;
- evidence capture and provenance recording;
- agent-definition normalization, scoring, qualification, and activation;
- benchmark execution;
- reversible provider promotion after configured evidence thresholds pass;
- Revenue OS research, scripting, asset preparation, rendering, and QA.

## Automatic Hardening Controls

The following controls execute automatically around the work. They are not standing approval gates:

1. Secret redaction.
2. Evidence/provenance capture.
3. Dependency and health checks.
4. Worktree isolation.
5. Test execution.
6. Prompt/content boundary enforcement: retrieved internet content is data, not runtime policy.
7. Agent-definition conflict detection.
8. Retry/fallback/degraded-mode recovery.
9. Reversible promotion/rollback metadata.

If a preferred control path fails, Hermes attempts repair, retry, fallback, alternate tooling, or degraded-mode continuation before returning a blocking failure.

## Approval Registry

`ApprovalRegistry` is exact-match by design. It cannot infer or expand categories.

```python
registry = ApprovalRegistry({"production_deploy", "external_communication"})

registry.evaluate("code_edit").human_approval_required
# False

registry.evaluate("authenticated_research").human_approval_required
# False

registry.evaluate("production_deploy").human_approval_required
# True
```

This preserves a narrow boundary: high-consequence actions can remain governed without causing ordinary autonomous work to stop.

## Capability-Specific Consequences

### Codebase Memory

Codebase Memory is the preferred structural context provider. If it is unavailable, Hermes falls back to native repository search and marks the evidence `degraded_context=true` rather than stopping an ordinary coding task.

### Orca / Coding Swarm

Worker/model selection remains with the existing Hermes router. Workers execute in isolated worktrees. Tests and policy checks determine candidate validity automatically. A verified ordinary candidate may be promoted without human approval.

### Agent-Reach

All supported channels remain eligible. Authenticated channels do not require per-use approval merely because they rely on configured credentials or session state. Secret material is passed to the upstream process when required, but it is redacted from persisted diagnostics and evidence.

### Agency Agents

Candidate definitions are normalized, deduplicated, scored, and qualified automatically. A definition declaring a high-consequence capability can still become active; the approval boundary applies when that capability is exercised, not when the agent is discovered or loaded.

### OpenMontage / Revenue OS

Research through render/QA is autonomous. A separately classified external publication action may invoke the existing approval policy without blocking upstream media production.

### Graft

Graft benchmarking is autonomous. Promotion may also be autonomous when configured quality and efficiency thresholds pass. Provider promotion is reversible and evidence-recorded.

## Regression Requirement

CI must include tests proving:

- ordinary actions default to `human_approval_required=false`;
- only exact registered categories can return `true`;
- Codebase Memory failure falls back instead of stopping;
- Agent-Reach authenticated execution is not converted into a per-use approval gate;
- secret values do not survive evidence serialization;
- ordinary verified coding candidates can auto-promote;
- Graft promotion is evidence-backed and reversible.

A change that introduces a new generic approval default, or converts a hardening control into a routine human checkpoint, is an autonomy regression.