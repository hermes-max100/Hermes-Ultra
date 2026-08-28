# Discovery, Plugin Intake, and Stateless MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add governed progressive tool discovery, Agent Plugins 1.0 intake, and MCP 2026-07-28 stateless compatibility while preserving Hermes governance boundaries.

**Architecture:** Focused standard-library modules feed existing Hermes authorities. Dispatch consumes tool discovery; plugin intake only creates Trust-Gate-ready evidence; MCP stateless routing derives scope for the existing containment gateway.

**Tech Stack:** Python 3.12, Bash, JSON, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-19-discovery-plugin-mcp-design.md`

## Global Constraints
- Base `hermes-max-setup`; branch `ai/hermes-discovery-plugin-mcp-v2`.
- TDD RED before production code.
- Trust Gate, containment, approvals, Memory/Trajectory remain authoritative.
- Plugin intake cannot install/activate.
- Actions references must be immutable SHAs.

### Task 1: Progressive tool discovery
**Files:** create `src/system/tool-discovery.py`, `config/tool-registry.json`; modify `src/system/hermes-dispatch.sh`; test `tests/test_tool_discovery.py`, `tests/test_hermes_dispatch_tool_discovery.sh`.
- [ ] Observe RED.
- [ ] Implement strict registry validation, eligibility-first search, compact selected schemas, stable hashes and CLI.
- [ ] Seed bounded core registry.
- [ ] Wire selected tools to dispatch OTel/Trajectory metadata.
- [ ] Run new and existing dispatch/skill regressions.

### Task 2: Governed Agent Plugin intake
**Files:** create `src/system/plugin-intake.py`; test `tests/test_plugin_intake.py`.
- [ ] Observe RED.
- [ ] Validate manifest/name/schema and root-contained fixed discovery.
- [ ] Validate stdio/HTTP/SSE MCP entries and secret/path safety.
- [ ] Add bounded capability scan, package fingerprint and create-only report.
- [ ] Emit package/candidate Trust Gate handoff only.

### Task 3: MCP 2026-07-28 compatibility
**Files:** create `src/system/mcp-stateless-gateway.py`, `docs/deployment/mcp-stateless.md`; test `tests/test_mcp_stateless_gateway.py`.
- [ ] Observe RED.
- [ ] Implement strict stateless protocol validation/default-deny legacy behavior.
- [ ] Add issuer validation, deterministic cache normalization and MRTR approval mapping.
- [ ] Derive containment scope without argument influence.
- [ ] Document canary/rollback and compatibility flag.

### Task 4: Hosted integration gate
**Files:** create `.github/workflows/discovery-plugin-mcp-validate.yml`.
- [ ] Confirm hosted RED is missing production modules.
- [ ] Implement minimal production code and reach GREEN.
- [ ] Widen gate to dispatch/OTel, Memory/Trajectory, Trust Gate, skill-router, containment and supply-chain regressions.
- [ ] Red-team final diff and fix regressions with failing tests first.
- [ ] Merge only after fresh hosted green evidence.
