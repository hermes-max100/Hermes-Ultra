# Skill Manager Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed Hermes Ultra skill supply-chain layer that turns untrusted discovery results into commit-pinned, hash-attested, quarantined artifacts and permits installation only after the existing lifecycle reaches `trusted`.

**Architecture:** Keep `skill_lifecycle.py` as the governance/state-machine authority and add a focused `skill_supply_chain.py` module for immutable source identity, safe tar extraction, deterministic hashing, quarantine staging, managed-root installation, optimistic manifest editing, and recoverable local archive/restore. Discovery catalogs—including Skill Manager and allMCPservers—remain discovery-only inputs. No branch name or `HEAD` is accepted as artifact identity; full Git commit and tree SHAs are required.

**Tech Stack:** Python 3.10+ standard library, dataclasses, hashlib, tarfile, tempfile/pathlib, pytest, existing Hermes Ultra `LifecycleState` / `SkillCandidate` contracts.

**Spec:** `docs/architecture/skill-lifecycle-promotion.md` plus the user-approved Skill Manager hardening design from 2026-08-30.

## Global Constraints

- Public catalogs and MCP directories are discovery inputs, never trust roots.
- Required lifecycle remains `discovered -> quarantined -> candidate -> trusted -> installed_disabled -> canary -> active`.
- Installation must be disabled-by-default and may not imply activation.
- Source identity must use full 40-character Git commit and tree SHAs; branch names and `HEAD` are not artifact identities.
- Remote archive extraction must reject traversal, absolute paths, symlinks, hardlinks, devices, and other non-regular entries.
- Installation targets must be exact configured managed roots.
- Every staged/installed artifact must carry deterministic SHA-256 evidence.
- Destructive replacement is not allowed in the install path; archive/restore is explicit and local.
- Manifest writes use optimistic concurrency and reject stale revisions.
- No new runtime dependency is added.

---

### Task 1: Commit-pinned source and artifact contracts

**Files:**
- Create: `src/hermes_ultra/skill_supply_chain.py`
- Test: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `PinnedSkillSource`, `SkillFile`, `SkillArtifactManifest`, `QuarantinedSkillArtifact`, `SkillSupplyChainError`.
- Produces: `PinnedSkillSource.codeload_url() -> str` that only works with full immutable commit identity.

- [ ] **Step 1: Write failing tests** for rejection of `HEAD`, short SHAs, malformed tree SHAs, empty skill paths, and for a codeload URL containing the full commit SHA.
- [ ] **Step 2: Run** `pytest tests/test_skill_supply_chain.py -q` and verify failures are caused by missing contracts.
- [ ] **Step 3: Implement immutable dataclasses** with strict validation and canonical repository parsing for `https://github.com/<owner>/<repo>` and `<owner>/<repo>` inputs.
- [ ] **Step 4: Run** `pytest tests/test_skill_supply_chain.py -q` and verify the contract tests pass.

### Task 2: Safe archive extraction and deterministic identity

**Files:**
- Modify: `src/hermes_ultra/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `SkillArchiveInspector.inspect(source: PinnedSkillSource, archive_bytes: bytes) -> QuarantinedSkillArtifact`.
- Produces: `hash_skill_files(files: Sequence[SkillFile]) -> str`.

- [ ] **Step 1: Write failing tests** for a valid GitHub-style tar.gz, traversal paths, absolute paths, symlink/hardlink/device entries, missing `SKILL.md`, archive byte caps, file-count caps, and stable directory hashes independent of archive order.
- [ ] **Step 2: Run** the focused tests and verify each security case fails before implementation.
- [ ] **Step 3: Implement extraction** with `tarfile`, one stripped repository root component, selected skill subpath only, regular files only, safe relative paths, total/file count limits, and preserved `0o777` permission bits.
- [ ] **Step 4: Compute and store** archive SHA-256, skill-directory SHA-256, `SKILL.md` SHA-256, commit SHA, tree SHA, source URL, discovery source, license, and staged timestamp.
- [ ] **Step 5: Run** focused tests until green.

### Task 3: Managed-root trusted installer

**Files:**
- Modify: `src/hermes_ultra/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `ManagedSkillInstaller(managed_roots, receipt_dir)`.
- Produces: `install(candidate, artifact, *, profile, target_root, review_approved, authorized_by) -> SkillInstallReceipt`.

- [ ] **Step 1: Write failing tests** proving install is rejected when candidate state is not `trusted`, review approval is false, candidate/source provenance disagrees, target root is not exactly configured for the selected profile, or target skill directory already exists.
- [ ] **Step 2: Run** focused tests and verify RED.
- [ ] **Step 3: Implement atomic installation** by writing to a temporary sibling directory, re-hashing written content, writing `.hermes-skill-provenance.json`, then renaming into place without overwriting an existing skill.
- [ ] **Step 4: Implement create-only `SkillInstallReceipt`** containing source hashes, target/profile, authorizer, timestamp, and a canonical receipt SHA-256.
- [ ] **Step 5: Run** focused tests until green.

### Task 4: Recoverable archive/restore and optimistic manifest editing

**Files:**
- Modify: `src/hermes_ultra/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `LocalSkillArchive.archive(skill_dir, *, reason) -> ArchivedSkill` and `restore(archive_id, target_root) -> Path`.
- Produces: `SkillManifestEditor.read(path) -> ManifestSnapshot` and `write(path, content, *, expected_sha256) -> ManifestSnapshot`.

- [ ] **Step 1: Write failing tests** for archive being a move (not delete), restore refusing collisions, archive hashes detecting tampering, and stale manifest revisions being rejected.
- [ ] **Step 2: Run** focused tests and verify RED.
- [ ] **Step 3: Implement archive/restore** under an app-managed archive root with metadata and content hash verification.
- [ ] **Step 4: Implement optimistic editing** with SHA-256 revision tokens and atomic replace only when the expected revision matches current bytes.
- [ ] **Step 5: Run** focused tests until green.

### Task 5: Discovery registry and public API integration

**Files:**
- Modify: `src/hermes_ultra/skill_lifecycle.py`
- Modify: `src/hermes_ultra/__init__.py`
- Modify: `tests/test_skill_lifecycle.py`
- Create: `docs/architecture/skill-supply-chain.md`

**Interfaces:**
- `DEFAULT_DISCOVERY_SOURCES` adds `skill-manager` and `all-mcp-servers`, both `discovery_only=True`, `auto_install=False`.
- Package exports expose the new supply-chain contracts without changing existing aliases.

- [ ] **Step 1: Write failing lifecycle tests** asserting the new sources exist and remain discovery-only.
- [ ] **Step 2: Update discovery registry** and keep every default source non-installing.
- [ ] **Step 3: Export supply-chain classes** from `hermes_ultra.__init__`.
- [ ] **Step 4: Document** the trust boundary, immutable source identity, quarantine data flow, install/activation separation, archive/restore, and concurrency behavior.
- [ ] **Step 5: Run** `pytest tests/test_skill_lifecycle.py tests/test_skill_supply_chain.py -q`.

### Task 6: Repository verification

**Files:**
- No production changes unless verification exposes a defect.

- [ ] **Step 1: Run** `python -m compileall -q src`.
- [ ] **Step 2: Run** `pytest -q`.
- [ ] **Step 3: Run** `pytest tests/test_skill_lifecycle.py -q`.
- [ ] **Step 4: Run** the source secret scan already encoded in `.github/workflows/test.yml`.
- [ ] **Step 5: Verify GitHub Actions** for the branch commit and report exact status; do not claim success from an unexecuted local suite.
