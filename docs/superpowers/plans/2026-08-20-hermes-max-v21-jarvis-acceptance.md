# Hermes Max v2.1 JARVIS Governance and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JARVIS ADVANCED v1.2.0 a reproducible, checksummed governed action layer under Hermes and prove the production acceptance gates without duplicating Hermes core responsibilities.

**Architecture:** Hermes owns reasoning/session/model/MCP runtime primitives. JARVIS runs loopback-only on `127.0.0.1:4700`, owns approvals/evidence/tool authorization, and is installed from verified immutable artifacts embedded or staged by the production build.

**Tech Stack:** Bash, Python wheel, JARVIS Tool Armory v1.2.0, HMAC/evidence ledger, systemd, JSON configuration, existing Hermes/JARVIS tests.

**Spec:** `docs/superpowers/specs/2026-08-20-hermes-max-jarvis-ultimate-production-design.md`

## Global Constraints

- JARVIS is not a second model/session/memory authority.
- JARVIS binds only `127.0.0.1:4700`.
- Artifact SHA256 values must match the verified v1.2.0 files.
- Archive SHA256: `dd0ad92cf02cc14b474f712c4e41ba194474471a5c38975d57e15808921578bf`.
- Wheel SHA256: `7ca6a0a5b02031507345dc3791e4579a50522743b77d76dc807292e344f604a8`.
- Approval/evidence gates remain mandatory for sensitive tool actions.
- `PASS` is emitted only after the corresponding check actually executes.

---
### Task 1: Pin JARVIS artifacts in production metadata

**Files:**
- Modify: `config/production-versions.json`
- Modify: `tests/test_production_versions.sh`
- Modify: `src/system/jarvis-armory.sh`

**Interfaces:**
- Consumes: JARVIS v1.2.0 archive and wheel.
- Produces: stable artifact names/digests and portable default artifact locations.

- [ ] **Step 1: Extend the failing production-pin test**

Assert `jarvis_advanced.version == "1.2.0"`, archive SHA256 equals `dd0ad92cf02cc14b474f712c4e41ba194474471a5c38975d57e15808921578bf`, and wheel SHA256 equals `7ca6a0a5b02031507345dc3791e4579a50522743b77d76dc807292e344f604a8`.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_production_versions.sh`
Expected: FAIL until the JARVIS section is added.

- [ ] **Step 3: Add metadata and remove `/tmp/codex-web-uploads` defaults**

Add `jarvis_advanced` to `config/production-versions.json`. Change `jarvis-armory.sh` defaults to `$ROOT_DIR/vendor/jarvis/1.2.0/...` while preserving environment overrides for test fixtures and recovery.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_production_versions.sh` and `bash tests/test_jarvis_armory_integration.sh`. Commit with `git add config/production-versions.json src/system/jarvis-armory.sh tests/test_production_versions.sh && git commit -m "feat: pin JARVIS production artifacts"`.
### Task 2: Stage verified JARVIS artifacts into production releases

**Files:**
- Create: `scripts/stage-jarvis-artifacts.sh`
- Create: `tests/test_stage_jarvis_artifacts.sh`
- Modify: `scripts/build-cloud-release.sh`

**Interfaces:**
- Consumes: `JARVIS_ARMORY_ARCHIVE_SOURCE` and `JARVIS_ARMORY_WHEEL_SOURCE` paths plus production metadata digests.
- Produces: `vendor/jarvis/1.2.0/JARVIS-OS-v1.2.0-tool-armory.zip`, matching `.sha256`, wheel, and wheel `.sha256` inside the staged release.

- [ ] **Step 1: Write fixture-based failing tests**

Create fake archive/wheel files and metadata in a temporary fixture. Assert the staging script refuses digest mismatches, copies exact matching artifacts, writes GNU-compatible `.sha256` files, and never mutates the source files.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_stage_jarvis_artifacts.sh`
Expected: FAIL because the staging script does not exist.

- [ ] **Step 3: Implement staging and production-build enforcement**

Implement `stage-jarvis-artifacts.sh SOURCE_ARCHIVE SOURCE_WHEEL DEST_ROOT`, read expected hashes from `config/production-versions.json`, verify before copy, and chmod staged artifacts read-only. Make `build-cloud-release.sh` require and stage them when `HERMES_PRODUCTION_BUILD=1`; ordinary test builds may omit them but must mark JARVIS runtime acceptance `N/A`.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_stage_jarvis_artifacts.sh` and `bash tests/test_release_supply_chain.sh`. Commit with `git add scripts tests && git commit -m "feat: stage verified JARVIS release artifacts"`.
### Task 3: Run JARVIS as a hardened loopback service

**Files:**
- Create: `infra/aws-primary/templates/jarvis-armory.service.tftpl`
- Modify: `infra/aws-primary/templates/bootstrap-hermes.sh.tftpl`
- Modify: `tests/test_cloud_foundation.sh`

**Interfaces:**
- Consumes: verified `vendor/jarvis/1.2.0` artifacts and `/opt/hermes-max/current/src/system/jarvis-armory.sh`.
- Produces: boot-persistent JARVIS on `127.0.0.1:4700` with hardened systemd controls.

- [ ] **Step 1: Add failing unit assertions**

Assert `User=hermes`, loopback host environment, `ExecStart=/opt/hermes-max/current/src/system/jarvis-armory.sh start`, `ExecStop=/opt/hermes-max/current/src/system/jarvis-armory.sh stop`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, and no public bind.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_cloud_foundation.sh`
Expected: FAIL because the JARVIS unit template does not exist.

- [ ] **Step 3: Render and install the unit after release verification**

Install the unit during bootstrap only after the active release and JARVIS artifact hashes verify. Keep writable paths limited to `/var/lib/hermes`, `/opt/hermes-max`, and the JARVIS runtime data path.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_cloud_foundation.sh`, `bash tests/test_jarvis_armory_integration.sh`, and `bash scripts/verify-cloud-foundation.sh`. Commit with `git add infra/aws-primary tests/test_cloud_foundation.sh && git commit -m "feat: run JARVIS as hardened service"`.
### Task 4: Add the canonical production acceptance runner

**Files:**
- Create: `scripts/final-production-acceptance.sh`
- Create: `tests/test_final_production_acceptance.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: outputs from cloud foundation, production pins, auth policy, router, JARVIS, Relay/Tailscale, release, rollback, and secret-scan checks.
- Produces: a machine-readable acceptance report where each gate is `PASS`, `FAIL`, or `N/A:<reason>`.

- [ ] **Step 1: Write failing acceptance-runner tests**

Use fixture scripts that emit controlled exit codes. Assert the runner never converts a skipped check into `PASS`, stops final promotion when any mandatory gate fails, redacts environment values, and emits `FINAL_VERIFICATION=PASS` only when every mandatory gate passes.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_final_production_acceptance.sh`
Expected: FAIL because the acceptance runner does not exist.

- [ ] **Step 3: Implement the runner**

Run the exact mandatory gates from the approved spec in deterministic order. Write JSON and text reports under `.hermes/reports/` with timestamps, command names, exit codes, and redacted summaries. Do not write prompts, tokens, cookies, API keys, or full secret-bearing environment dumps.

- [ ] **Step 4: Integrate existing JARVIS evidence checks**

Require `jarvis-armory.sh verify-artifacts`, `jarvis-armory.sh doctor`, approval-ledger/evidence tests already shipped by JARVIS when available, and explicitly report `N/A` when a runtime-only check cannot be executed in the local build environment.

- [ ] **Step 5: Verify and commit**

Run `bash tests/test_final_production_acceptance.sh`, `bash tests/test_jarvis_armory_integration.sh`, and `git diff --check`. Commit with `git add scripts/final-production-acceptance.sh tests/test_final_production_acceptance.sh README.md && git commit -m "feat: add production acceptance gate"`.
