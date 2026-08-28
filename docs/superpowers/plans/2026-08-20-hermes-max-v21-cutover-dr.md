# Hermes Max v2.1 Cutover and Disaster Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the authoritative Hermes/JARVIS runtime to AWS without losing state, preserve rollback to the current environment, and prove backup/restore and workstation recovery before decommissioning anything.

**Architecture:** Code releases remain immutable and separate from mutable state. State migration uses an explicit manifest, checksum, encrypted staging, restore verification, and parity checks. The legacy runtime remains untouched until AWS and mobile round-trip acceptance pass.

**Tech Stack:** Bash, tar, SHA-256, AWS S3 private backups, existing canary controller, existing export/restore scripts, AWS SSM, Tailscale.

**Spec:** `docs/superpowers/specs/2026-08-20-hermes-max-jarvis-ultimate-production-design.md`

## Global Constraints

- Do not terminate or delete the existing host/runtime during implementation.
- Do not copy plaintext secrets, browser cookies, or provider session stores into backup bundles.
- Every migrated state object is checksummed and listed in a manifest.
- Restore verification must precede production cutover.
- The old runtime stays available until `FINAL_VERIFICATION=PASS` and rollback is proven.
- Chromebook becomes development/recovery after cutover; it does not remain a second active production brain.
- Production AWS apply is a separate explicit deployment step after local implementation/tests and authenticated AWS preflight.

---
### Task 1: Define and test the production state manifest

**Files:**
- Create: `config/production-state-manifest.json`
- Create: `tests/test_production_state_manifest.py`
- Modify: `docs/deployment/disaster-recovery.md`

**Interfaces:**
- Consumes: known mutable Hermes/JARVIS state directories and files.
- Produces: an allowlisted state inventory with classification and restore destination metadata.

- [ ] **Step 1: Write the failing manifest test**

Assert every manifest entry has `source`, `restore_to`, `classification`, `required`, and `secret_policy`; reject globbing into browser profiles, `.env*`, OAuth auth stores, cookies, or raw credential files.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_production_state_manifest.py`
Expected: FAIL because the manifest does not exist.

- [ ] **Step 3: Create the allowlisted manifest**

Include only durable application state needed for continuity: approved `.hermes/state` content, Memory Fabric state, JARVIS evidence/approval ledger data, canary state, and other explicitly non-secret runtime data already documented by the project. Mark regenerable caches/logs as excluded.

- [ ] **Step 4: Document classifications and commit**

Update the DR document to distinguish immutable release, durable state, secrets, and regenerable data. Run the manifest test and commit with `git add config/production-state-manifest.json tests/test_production_state_manifest.py docs/deployment/disaster-recovery.md && git commit -m "feat: define production state manifest"`.
### Task 2: Build redacted state export and restore verification

**Files:**
- Create: `scripts/export-production-state.sh`
- Create: `scripts/restore-production-state.sh`
- Create: `tests/test_production_state_transfer.sh`

**Interfaces:**
- Consumes: `config/production-state-manifest.json` and a source runtime root.
- Produces: a tar.gz state bundle, `.sha256`, `STATE_MANIFEST.sha256`, and a verified restore into a target root.

- [ ] **Step 1: Write fixture-based transfer tests**

Create a temporary source tree with allowed state plus deliberately forbidden `.env`, cookie, token, and browser-profile files. Assert export contains only allowlisted state, restore reproduces file hashes, and a tampered bundle is rejected.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_production_state_transfer.sh`
Expected: FAIL because the export/restore commands do not exist.

- [ ] **Step 3: Implement export**

Walk only manifest paths, fail closed on symlinks escaping the runtime root, generate per-file SHA256 entries, create the bundle with owner/group normalized, and refuse any file whose path or scanned content matches the project's credential/cookie redaction rules.

- [ ] **Step 4: Implement restore**

Verify outer checksum and every internal manifest entry before writing. Restore into a staging directory first, preserve existing target state as a timestamped rollback copy, then atomically promote the verified state tree.

- [ ] **Step 5: Verify and commit**

Run `bash tests/test_production_state_transfer.sh`, `bash tests/test_restore_installer.sh`, and `git diff --check`. Commit with `git add scripts tests && git commit -m "feat: add verified production state transfer"`.
### Task 3: Add backup upload and restore-drill automation

**Files:**
- Create: `scripts/aws-state-backup.sh`
- Create: `scripts/verify-backup-restore.sh`
- Create: `tests/test_backup_restore.sh`
- Modify: `docs/deployment/disaster-recovery.md`

**Interfaces:**
- Consumes: verified state bundle and Terraform `backups` bucket output.
- Produces: versioned S3 backup plus a restore-drill report with object ID, SHA256, and parity result.

- [ ] **Step 1: Write tests with an `aws` shim**

Assert upload refuses an unverified bundle, uses `aws s3 cp` only to the configured private backups bucket, verifies the uploaded object's metadata/checksum where available, and writes no credential values to logs.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_backup_restore.sh`
Expected: FAIL because the backup scripts do not exist.

- [ ] **Step 3: Implement upload and restore drill**

Upload the state archive and checksum under `state/<UTC timestamp>/`. `verify-backup-restore.sh` downloads to a temporary directory, verifies digest, restores to an isolated target root, and compares manifest hashes without touching production state.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_backup_restore.sh` and `git diff --check`. Commit with `git add scripts tests docs/deployment/disaster-recovery.md && git commit -m "feat: add backup restore drill"`.
### Task 4: Verify Chromebook engineering/recovery readiness

**Files:**
- Create: `scripts/verify-dev-workstation.sh`
- Create: `tests/test_dev_workstation.sh`
- Create: `docs/deployment/chromebook-workstation.md`

**Interfaces:**
- Consumes: local CLI installations and Git checkout state.
- Produces: redacted readiness output for Git, AWS CLI, Terraform/OpenTofu, Tailscale, Hermes, Claude Code, Codex, Antigravity `agy`, OpenCode, Docker, and Kiro when installed.

- [ ] **Step 1: Write PATH-shim tests**

Assert the verifier distinguishes `present`, `missing`, and `auth-required` without printing tokens. Assert it fails production-admin readiness when AWS CLI exists but `aws sts get-caller-identity` fails.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_dev_workstation.sh`
Expected: FAIL because the verifier does not exist.

- [ ] **Step 3: Implement verifier and workstation documentation**

Report tool path/version, Git worktree cleanliness, Tailscale state, and AWS identity availability. Do not attempt subscription logins automatically and do not read auth/token files. Document isolated worktrees for concurrent coding agents and state that local Hermes becomes recovery-only after cutover.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_dev_workstation.sh` and `bash scripts/verify-dev-workstation.sh || true`; the latter may report real missing/auth-required tools without leaking credentials. Commit with `git add scripts/verify-dev-workstation.sh tests/test_dev_workstation.sh docs/deployment/chromebook-workstation.md && git commit -m "feat: add engineering workstation verification"`.
### Task 5: Add staged production cutover orchestration

**Files:**
- Create: `scripts/production-cutover.sh`
- Create: `tests/test_production_cutover.sh`
- Modify: `docs/deployment/aws.md`
- Modify: `docs/deployment/disaster-recovery.md`

**Interfaces:**
- Consumes: successful local release build, AWS preflight, state backup/restore drill, Relay/Tailscale verifier, JARVIS doctor, and final acceptance runner.
- Produces: a resumable cutover state machine and evidence report; it does not silently terminate the legacy runtime.

- [ ] **Step 1: Write state-machine tests**

Assert cutover phases are `preflight`, `backup`, `provision`, `restore`, `runtime_verify`, `relay_verify`, `rollback_drill`, `promote`, and `legacy_hold`. Assert a failed phase prevents later phases and rerun resumes only from a verified checkpoint.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_production_cutover.sh`
Expected: FAIL because the cutover orchestrator does not exist.

- [ ] **Step 3: Implement dry-run and execution modes**

Default to `--dry-run`. Require `--execute` plus authenticated AWS preflight before any Terraform apply. Record every phase result under `.hermes/cutover/` without secret values. Never call Terraform destroy, EC2 terminate, or stop the legacy runtime.

- [ ] **Step 4: Enforce the legacy hold**

Promotion may mark AWS as authoritative only after `FINAL_VERIFICATION=PASS`, a real Samsung Relay round-trip, state parity, and a successful rollback drill. The script ends at `legacy_hold`; decommissioning is intentionally a separate later decision.

- [ ] **Step 5: Verify and commit**

Run `bash tests/test_production_cutover.sh`, `bash tests/test_final_production_acceptance.sh`, and `git diff --check`. Commit with `git add scripts/production-cutover.sh tests/test_production_cutover.sh docs/deployment && git commit -m "feat: add staged production cutover"`.
