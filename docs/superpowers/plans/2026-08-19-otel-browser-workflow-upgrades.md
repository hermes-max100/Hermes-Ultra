# Hermes OTel + Browser Workflow Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add privacy-preserving GenAI telemetry correlation and governed deterministic browser workflow replay without weakening existing Hermes containment controls.

**Architecture:** The OTel bridge writes local append-only spans and optionally emits OTLP/HTTP while propagating trace IDs into Memory Fabric trajectories. The browser workflow cache compiles evidence-backed same-site action traces into immutable specs and requires the existing containment gateway before any live Playwright replay.

**Tech Stack:** Python 3.12 standard library, Bash, existing Playwright runtime when live replay is used, existing Hermes containment gateway, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-19-otel-browser-workflow-upgrades-design.md`

## Global Constraints

- Preserve existing Trust Gate, Memory Fabric, containment, Revenue OS, and approval boundaries.
- No new mandatory network service or paid dependency.
- Telemetry content capture is disabled by default.
- Sensitive Hermes classifications remain metadata-only.
- Browser live replay requires exact single-use containment authorization.
- Browser workflows never self-heal or silently rewrite themselves.

---

### Task 1: OpenTelemetry bridge

**Files:**
- Create: `src/system/otel-bridge.py`
- Test: `tests/test_otel_bridge.py`

**Interfaces:**
- Produces: `new_trace_context()`, `sanitize_attributes()`, `build_span()`, `append_local_span()`, CLI `new` and `emit`.
- Consumes: optional `HERMES_OTEL_*` environment variables only.

- [ ] Write tests that import `src/system/otel-bridge.py` and assert ID shape, content omission, secret redaction, sensitive-class metadata-only behavior, append-only JSONL output, and non-strict exporter failure behavior.
- [ ] Run `python3 tests/test_otel_bridge.py`; expected RED because `src/system/otel-bridge.py` does not exist.
- [ ] Implement the minimal bridge with secure sanitization and optional OTLP/HTTP JSON export.
- [ ] Run `python3 tests/test_otel_bridge.py`; expected PASS.

### Task 2: Dispatch trace propagation

**Files:**
- Modify: `src/system/hermes-dispatch.sh`
- Test: `tests/test_hermes_dispatch_otel.sh`

**Interfaces:**
- Consumes: `src/system/otel-bridge.py`.
- Produces: `HERMES_TRACE_ID`, `HERMES_TRACE_SPAN_ID`; trajectory metadata keys `trace_id` and `span_id`.

- [ ] Build a temporary Hermes fixture with real `hermes-dispatch.sh` plus boundary test doubles and assert one local dispatch span and trajectory trace correlation.
- [ ] Run `bash tests/test_hermes_dispatch_otel.sh`; expected RED because dispatch does not initialize or emit OTel spans.
- [ ] Add trace initialization, trajectory correlation, and completion emission without logging query content.
- [ ] Run `bash tests/test_hermes_dispatch_otel.sh`; expected PASS.

### Task 3: Deterministic browser workflow compiler/cache

**Files:**
- Create: `src/system/browser-workflow-cache.py`
- Test: `tests/test_browser_workflow_cache.py`

**Interfaces:**
- Produces: `compile_workflow()`, `validate_workflow()`, `render_workflow()`, CLI `compile`, `validate`, `replay`.
- Consumes: successful browser trace JSON with `status=success`, `evidence_refs`, `source_url`, and bounded actions.

- [ ] Write tests for successful compile, conflicting immutable ID, missing evidence, cross-site navigation, sensitive parameters/fields, deterministic parameter rendering, and `--execute` authorization requirement.
- [ ] Run `python3 tests/test_browser_workflow_cache.py`; expected RED because the module does not exist.
- [ ] Implement compiler, validator, dry-run renderer, containment check, and Playwright replay path.
- [ ] Run `python3 tests/test_browser_workflow_cache.py`; expected PASS.

### Task 4: Hosted verification

**Files:**
- Create: `.github/workflows/agent-runtime-upgrades-validate.yml`

**Interfaces:**
- Consumes the three test files and modified runtime files.
- Produces a required clean hosted validation signal for the upgrade branch/PR.

- [ ] Add a least-privilege workflow using immutable action SHAs already used by Hermes.
- [ ] Run Python tests and `bash -n src/system/hermes-dispatch.sh` in GitHub Actions.
- [ ] Open a PR from `ai/otel-browser-workflow-upgrades` to `hermes-max-setup`.
- [ ] Inspect hosted results; do not merge on failure.
