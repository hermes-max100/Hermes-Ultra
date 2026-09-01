# Nightcrawler Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Nightcrawler as a first-class Hermes-Ultra capability enclave that preserves admitted tools' full upstream functionality, exposes capability metadata globally, and gates cross-profile execution through owner-authorized grants with no automatic privilege inheritance.

**Architecture:** Nightcrawler is an execution-authority domain, not a second router or security model. A checked-in capability catalog describes provenance, risk placement, executor identity, and dependencies. All profiles can query catalog metadata through a read-only Nightcrawler discovery tool. Nightcrawler-native invocations pass through to admitted executors without a new Nightcrawler-specific capability reduction. Cross-profile invocations must pass a dedicated Nightcrawler authority evaluator built on the existing `hermes-authority-grant-v1` vocabulary and authenticated approval receipts from `approval-security.py`. Immutable receipts record grants, provenance, execution identity, and outcomes without secrets.

**Tech Stack:** Python 3.11/3.12, Bash, JSON, existing Hermes `approval-security.py`, `consequential-action-gate.py`, `tool-discovery.py`, `hermes-dispatch.sh`, governed runtime/evidence primitives, Git source provenance, SHA-256 manifests, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-01-nightcrawler-profile-design.md`

## Global Constraints

- Work only on `ai/nightcrawler-profile` in an isolated worktree.
- Do not edit `src/system/dynamic-router.sh`, `config/cloud-model-catalog.json`, or `tests/test_dynamic_router.sh`.
- Capture fresh SHA256 values for those protected files at implementation start and prove them unchanged at final verification.
- Nightcrawler placement MUST NOT weaken, stub, simulate, remove, or silently replace an admitted capability.
- Do not introduce a new approval requirement merely because Nightcrawler itself invokes one of its admitted tools.
- Existing platform-wide controls already present in a tool/wrapper remain unchanged unless the owner separately approves changing them.
- Catalog visibility is global; raw credentials, tokens, passwords, private keys, cookies, and secret environment values are never catalog metadata.
- Cross-profile authority is deny-by-default and owner-granted. Grants may be narrow, broad, temporary, or explicitly persistent.
- One grant does not imply another. Delegation is disabled unless the owner explicitly authorizes it.
- Risk classification determines Nightcrawler placement and cross-profile access; it is not a mechanism for deleting functionality.
- External artifacts are immutable/provenance-pinned before activation. Wrappers normalize invocation/evidence only; they do not rewrite upstream code.
- Do not deploy to production or merge `main` as part of this plan. Finish with a verified feature branch ready for owner review.

Initial external provenance baselines observed on 2026-09-01:

```text
Robin repo:       apurvsinghgautam/robin
Robin commit:     575d105e2f0fd61a450d5b4368535d0e83060354
Robin git tree:   31bf3a7838db3b006f2c0fc2bd9a170ae8b15946
Robin license:    MIT

OSINT catalog:    apurvsinghgautam/dark-web-osint-tools
Catalog commit:   70fd03b027d3e03c362d862a889dc2b4cd133382
Catalog git tree: 9101f45d7c0db371fb27a5ed5fc4aca098cadfb4
Catalog license:  NOASSERTION

HTTP shell repo:  apurvsinghgautam/HTTP-Reverse-Shell
HTTP shell commit:80a0a545a406fb5dd55854c12355cc4b81a016ba
HTTP shell tree:  21717380b92035bf35ea6302afaafa50d39fc6c2
HTTP shell license:NOASSERTION

OBLITERATUS local package baseline: 0.1.2
Existing wrapper: src/system/obliteratus-runner.sh
```

At implementation start, re-verify those repository refs. If upstream has changed, do not silently advance the pin; keep these exact identities unless the owner explicitly chooses a newer artifact.

---

## Task 1: Establish the Nightcrawler profile and explicit catalog schema

**Files:**
- Create: `config/nightcrawler-profile.json`
- Create: `config/nightcrawler-capabilities.json`
- Create: `src/system/nightcrawler_catalog.py`
- Create: `tests/test_nightcrawler_catalog.py`

- [ ] **Write RED tests first** for profile identity, unique capability IDs, required provenance fields, native-owner profile `nightcrawler`, risk metadata, and secret-field rejection.

Required catalog entry shape:

```json
{
  "capability_id": "nightcrawler:obliteratus",
  "name": "OBLITERATUS",
  "category": "model-security",
  "risk_class": "high",
  "risk_reason": "model mutation and high-power local execution surface",
  "availability": "installed",
  "provenance": {"kind": "local-package", "version": "0.1.2"},
  "executor": {"kind": "existing-runner", "path": "src/system/obliteratus-runner.sh"},
  "dependencies": [],
  "capability_summary": []
}
```

- [ ] Run RED:

```bash
python3 -m unittest tests.test_nightcrawler_catalog -v
```

- [ ] Implement `Capability`, `load_catalog(path)`, `get_capability(catalog, capability_id)`, `public_metadata(capability, requester_profile, access_state)`, and strict schema validation.
- [ ] Use an explicit metadata allowlist in `public_metadata`; do not redact by regex after serialization.
- [ ] Seed the catalog with `nightcrawler:obliteratus`, `nightcrawler:robin`, `nightcrawler:dark-web-osint-tools`, and `nightcrawler:http-reverse-shell` plus discovered high-risk entries added in Task 9.
- [ ] Verify GREEN and commit:

```bash
python3 -m unittest tests.test_nightcrawler_catalog -v
git add config/nightcrawler-profile.json config/nightcrawler-capabilities.json src/system/nightcrawler_catalog.py tests/test_nightcrawler_catalog.py
git commit -m "feat: define Nightcrawler capability catalog"
```

---

## Task 2: Pin and stage external Nightcrawler source without modifying it

**Files:**
- Create: `config/nightcrawler-upstream.json`
- Create: `scripts/stage-nightcrawler-source.sh`
- Create: `tests/test_nightcrawler_upstream.py`
- Create: `tests/test_stage_nightcrawler_source.sh`

- [ ] Write RED fixture tests requiring exact repository URL, commit, Git tree, source manifest, and license metadata for Robin, dark-web-osint-tools, and HTTP-Reverse-Shell.
- [ ] Test rejection of dirty source trees, wrong commits, symlinks escaping source roots, missing expected files, and source-manifest tampering.
- [ ] Implement a generic stager that copies the exact Git-tracked tree at the pinned commit, excluding only `.git`, generated caches, and local runtime state. It MUST NOT edit source files or remove upstream entrypoints/features.
- [ ] Record `SOURCE_COMMIT`, `SOURCE_GIT_TREE`, `SOURCE_MANIFEST.sha256`, and `SOURCE_PROVENANCE.json` beside each staged artifact.
- [ ] Represent missing upstream license declarations as `NOASSERTION`; do not invent a license.
- [ ] Verify GREEN and commit.

---

## Task 3: Build global, secret-safe Nightcrawler visibility

**Files:**
- Modify: `config/tool-registry.json`
- Create: `src/system/nightcrawler_cli.py`
- Create: `tests/test_nightcrawler_visibility.py`
- Modify: `tests/test_tool_discovery.py`

- [ ] Write RED tests showing `revenue-os`, `trading`, `scout`, and an arbitrary profile can enumerate/search Nightcrawler metadata even with zero execution grants.
- [ ] Add a read-only `nightcrawler.catalog` registry tool and a read-only `nightcrawler.access` tool. These expose metadata/effective access only, never secrets or executor environment values.
- [ ] Keep executable Nightcrawler schemas separate from authorization: seeing a capability is not execution permission.
- [ ] Add CLI commands:

```text
nightcrawler_cli.py catalog [--query TEXT] [--requester PROFILE]
nightcrawler_cli.py access --requester PROFILE [--capability ID]
```

- [ ] Assert a profile granted only Obliteratus still sees HTTP Reverse Shell metadata with `execution_allowed=false`.
- [ ] Verify existing progressive tool-discovery tests still pass and commit.

---

## Task 4: Implement the Nightcrawler authority evaluator on the existing grant vocabulary

**Files:**
- Create: `src/system/nightcrawler_authority.py`
- Create: `config/nightcrawler-grant.example.json`
- Create: `tests/test_nightcrawler_authority.py`

Use `schema_version: hermes-authority-grant-v1`, `principal: owner`, `actor` as requesting profile, and `allowed_tools` as Nightcrawler capability IDs. Add Nightcrawler-specific fields without changing the existing consequential-action gate:

```json
{
  "schema_version": "hermes-authority-grant-v1",
  "authority_domain": "nightcrawler",
  "grant_id": "grant-nightcrawler-example",
  "principal": "owner",
  "actor": "scout",
  "allowed_tools": ["nightcrawler:robin"],
  "allowed_categories": [],
  "allow_all_nightcrawler": false,
  "scope": {"kind": "task", "value": "investigation-123"},
  "issued_at": "2026-09-01T00:00:00Z",
  "expires_at": "2026-09-01T02:00:00Z",
  "persistence": "temporary",
  "delegation": {"allowed": false},
  "required_evidence_types": ["owner_approval"]
}
```

- [ ] Write RED tests for: Nightcrawler-native ALLOW with no grant; normal-profile DENY without grant; exact-tool ALLOW; category grant; full-Nightcrawler grant; persistent grant; expiry; revocation; wrong actor; wrong domain; one-tool non-inheritance; provenance mismatch.
- [ ] Implement immutable `AccessDecision` plus `evaluate_access(requester_profile, capability, grants, revoked_grant_ids, task_scope, now)`.
- [ ] Native Nightcrawler returns `ALLOW/native` without synthesizing a fake owner grant.
- [ ] Cross-profile grants never widen themselves. A child/delegated grant is valid only when an owner-authorized parent explicitly permits delegation and the child is a strict subset of the parent's capability/scope/time bounds.
- [ ] Verify GREEN and commit.

---

## Task 5: Add authenticated owner grant issuance and revocation

**Files:**
- Create: `src/system/nightcrawler_grants.py`
- Create: `tests/test_nightcrawler_grants.py`

- [ ] Write RED tests using the existing `src/system/approval-security.py` HMAC verifier.
- [ ] Define owner approval receipt schema `nightcrawler-owner-approval-v1` whose signed body binds `grant_body_hash`, requester, requested tools/categories/full-access flag, scope, persistence, delegation, approval ID, approver `owner`, approval time, and approval expiry.
- [ ] Implement `GrantStore` under `.hermes/nightcrawler/grants` and `.hermes/nightcrawler/revocations` with regular-file checks, mode `0600`, atomic create-only writes, fsync, and content hashes.
- [ ] `issue_grant()` MUST verify the authenticated owner approval receipt and exact grant-body hash before persistence.
- [ ] `revoke_grant()` creates an immutable revocation record; never deletes history.
- [ ] Persistent access is allowed only when both proposed grant and signed owner approval explicitly select persistence.
- [ ] Verify tests plus existing consequential-action gate tests and commit.

---

## Task 6: Implement a capability-preserving execution broker

**Files:**
- Create: `src/system/nightcrawler_broker.py`
- Create: `tests/test_nightcrawler_broker.py`

- [ ] Write RED tests with fake executors proving the broker preserves the selected executor, entrypoint, and argument vector; it may add evidence context but may not drop upstream arguments/functions.
- [ ] Implement `InvocationRequest`, `InvocationPlan`, and `NightcrawlerBroker.prepare()`.
- [ ] Resolution order: capability identity -> provenance verification -> native/cross-profile authority decision -> exact executor plan.
- [ ] A provenance mismatch denies invocation but leaves the installed/staged artifact untouched.
- [ ] Nightcrawler-native invocation does not require a cross-profile grant.
- [ ] Cross-profile invocation includes the effective grant ID in the plan.
- [ ] Do not encode offensive-tool behavior in the broker. The broker resolves and invokes the admitted upstream executor exactly as cataloged.
- [ ] Preserve pre-existing wrapper controls, including those already in `obliteratus-runner.sh`; Nightcrawler adds no new capability-reduction layer.
- [ ] Verify GREEN and commit.

---

## Task 7: Add immutable execution receipts and recommendations

**Files:**
- Create: `src/system/nightcrawler_receipts.py`
- Create: `tests/test_nightcrawler_receipts.py`

- [ ] Write RED tests for receipt tampering, duplicate receipt IDs, secret-like field rejection/redaction, native-vs-granted authority evidence, and failed execution receipts.
- [ ] Use schema `hermes-nightcrawler-execution-receipt-v1` containing requester, executor profile, capability ID, provenance digest, grant ID or `native`, task/run IDs, timestamps, status, result digest, and bounded/redacted error metadata.
- [ ] Add recommendation records that let an unauthorized agent say another visible capability may help and request owner access. Recommendation records NEVER create grants.
- [ ] Verify GREEN and commit.

---

## Task 8: Wire Nightcrawler into Hermes discovery/dispatch without touching model routing

**Files:**
- Modify: `src/system/hermes-dispatch.sh`
- Modify: `config/tool-registry.json`
- Modify: `tests/test_hermes_dispatch_tool_discovery.sh`
- Modify: `tests/test_tool_discovery.py`

- [ ] Write RED tests showing Nightcrawler catalog tools are discoverable for normal profiles and that dispatch records visible recommendations separately from executable tool authorization.
- [ ] Add `nightcrawler.invoke` as a governed generic execution front door whose broker performs the actual Nightcrawler authorization check.
- [ ] Do not modify `dynamic-router.sh`; `--profile nightcrawler` continues through the existing dispatch/router path while Nightcrawler execution authority is supplied by the broker/catalog layer.
- [ ] Keep model selection completely independent of Nightcrawler capability membership.
- [ ] Verify existing dispatch/tool-discovery regressions and commit.

---

## Task 9: Perform the explicit risky-capability inventory

**Files:**
- Create: `scripts/inventory-nightcrawler-capabilities.py`
- Create: `tests/test_nightcrawler_inventory.py`
- Modify: `config/nightcrawler-capabilities.json`
- Modify: `config/external-skill-sources.json` only to attach Nightcrawler placement metadata; do not silently rewrite upstream/source policies.

- [ ] Write RED tests that the inventory detects known high-risk surfaces already present in Hermes-Ultra, including OBLITERATUS, malware/reverse-engineering skills, security scanners, remote administration/execution surfaces, and high-risk external sources such as Tempest.
- [ ] Inventory logic produces candidates; it does not automatically delete, disable, or rewrite anything.
- [ ] Materialize reviewed candidates into the explicit Nightcrawler catalog with `availability` states such as `installed`, `staged`, or `discovered`.
- [ ] Every high-risk candidate must either have a Nightcrawler catalog entry or an explicit placement record explaining why it remains elsewhere. Placement records are not capability suppression.
- [ ] Preserve OBLITERATUS package version `0.1.2` and its existing runner command surface exactly; add metadata rather than changing the runner.
- [ ] Verify that cataloging a capability does not modify its source digest.
- [ ] Commit the audited inventory.

---

## Task 10: Admit the three requested external sources as Nightcrawler capabilities

**Files:**
- Modify: `config/nightcrawler-capabilities.json`
- Modify: `config/nightcrawler-upstream.json`
- Create: `tests/test_nightcrawler_external_admission.py`

- [ ] Add Robin as a full upstream capability source, preserving its Tor/search/scrape/LLM/UI functionality and current source tree.
- [ ] Add dark-web-osint-tools as a globally visible Nightcrawler discovery/reference catalog with exact provenance; do not claim it is executable software when it is a curated source list.
- [ ] Add HTTP-Reverse-Shell as the exact pinned upstream artifact with both upstream entrypoints represented in catalog metadata. Do not rewrite it into a simulation-only substitute.
- [ ] Keep license values truthful (`MIT` for Robin, `NOASSERTION` where upstream declares none).
- [ ] Tests must compare staged source manifests against pinned source and fail on source changes.
- [ ] Commit external admissions.

---

## Task 11: Add owner-facing Nightcrawler UX

**Files:**
- Modify: `src/system/nightcrawler_cli.py`
- Create: `docs/deployment/nightcrawler.md`
- Create: `tests/test_nightcrawler_cli.py`

Required commands:

```text
catalog
access --requester PROFILE
request --requester PROFILE --capability ID --reason TEXT [--scope ...]
grant --grant FILE --approval-receipt FILE
revoke --grant-id ID --approval-receipt FILE
invoke --requester PROFILE --capability ID --task-id ID -- [upstream args...]
```

- [ ] Write RED tests for readable catalog output, request-only behavior, owner-approved grant issuance, revocation, broad grants, expiry, and secret-free output.
- [ ] A request can recommend broader access but cannot self-approve.
- [ ] Documentation must explain: global visibility, native Nightcrawler authority, owner override grants, non-transitive permissions, provenance, receipts, and how to inspect effective access.
- [ ] Do not document hidden credentials or operational secrets.
- [ ] Verify GREEN and commit.

---

## Task 12: Governed-runtime, CI, release, and router-preservation gates

**Files:**
- Modify: `tests/test_governed_graph_runtime.sh`
- Modify: `.github/workflows/cloud-foundation-validate.yml`
- Modify: `tests/test_release_supply_chain.sh` if Nightcrawler source is included in release artifacts.

- [ ] Capture protected router SHA256 values from the current branch before edits:

```bash
sha256sum src/system/dynamic-router.sh config/cloud-model-catalog.json tests/test_dynamic_router.sh > /tmp/nightcrawler-router-baseline.sha256
```

- [ ] Add Nightcrawler tests to governed-runtime and CI without changing protected router files.
- [ ] Run the full local matrix:

```bash
git diff --check
python3 -m unittest tests.test_nightcrawler_catalog -v
python3 -m unittest tests.test_nightcrawler_visibility -v
python3 -m unittest tests.test_nightcrawler_authority -v
python3 -m unittest tests.test_nightcrawler_grants -v
python3 -m unittest tests.test_nightcrawler_broker -v
python3 -m unittest tests.test_nightcrawler_receipts -v
python3 -m unittest tests.test_nightcrawler_inventory -v
python3 -m unittest tests.test_nightcrawler_external_admission -v
python3 -m unittest tests.test_nightcrawler_cli -v
python3 -m unittest tests.test_consequential_action_gate -v
python3 -m unittest tests.test_tool_discovery -v
bash tests/test_hermes_dispatch_tool_discovery.sh
bash tests/test_obliteratus_runner.sh
bash tests/test_governed_graph_runtime.sh
bash tests/test_dynamic_router.sh
bash tests/test_plugin_intake.py 2>/dev/null || python3 -m unittest tests.test_plugin_intake -v
bash tests/test_secret_scan_production.sh
bash tests/test_release_supply_chain.sh
sha256sum -c /tmp/nightcrawler-router-baseline.sha256
```

- [ ] If a command name differs in the current branch, use the existing repository-native equivalent; do not omit the gate.
- [ ] Add Nightcrawler paths/tests to CI and run the GitHub workflow.
- [ ] Prove no raw credentials, staged `.git` directories, runtime state, or generated caches were committed.
- [ ] Verify `git status`, review the full diff, and commit:

```bash
git add .
git commit -m "feat: add owner-governed Nightcrawler profile"
```

---

## Task 13: Final verification and branch handoff

- [ ] Read and apply `superpowers:verification-before-completion`.
- [ ] Read and apply `superpowers:requesting-code-review`.
- [ ] Re-run the complete Nightcrawler suite and all protected-router checks from a clean working tree.
- [ ] Verify every approved spec acceptance criterion is represented by at least one passing test.
- [ ] Verify the final catalog proves the four seed capabilities plus the audited high-risk inventory are globally visible.
- [ ] Verify Nightcrawler-native authority works without a cross-profile grant.
- [ ] Verify a normal profile cannot execute a Nightcrawler capability without a matching owner grant.
- [ ] Verify an Obliteratus-only grant cannot execute HTTP Reverse Shell, while the grantee can still see and recommend it.
- [ ] Verify full-Nightcrawler and explicitly persistent owner grants behave exactly at the breadth selected by the owner.
- [ ] Verify no adapter/source-staging step changed upstream source content.
- [ ] Publish only `ai/nightcrawler-profile`; do not merge `main` or deploy production.
- [ ] Use `superpowers:finishing-a-development-branch` for the final integration choice.

## Definition of Done

Nightcrawler is implementation-complete when the branch proves all of the following simultaneously:

1. Every Hermes profile can inspect the Nightcrawler catalog.
2. Catalog visibility exposes capability/provenance/access metadata but no secrets.
3. Nightcrawler retains native access to its admitted capability surfaces.
4. Cross-profile execution requires an owner-authorized matching grant.
5. Grants can be exact-tool, category, full-profile, temporary, or explicitly persistent.
6. Access does not chain to unrelated capabilities and cannot be silently widened.
7. Agents may recommend/request visible capabilities they do not have.
8. Provenance mismatch denies invocation without deleting or modifying the underlying tool.
9. Robin, dark-web-osint-tools, HTTP-Reverse-Shell, OBLITERATUS, and the audited high-risk Hermes inventory are represented explicitly.
10. Risk placement does not weaken or replace upstream functionality.
11. Execution/grant decisions are immutable/auditable without raw secrets.
12. Protected model-routing files are byte-for-byte unchanged.
