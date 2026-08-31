# Hermes Relay SDK Optimization Implementation Plan

> **For Melo:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate the pinned official Hermes-Relay Android, server/plugin, and desktop surfaces into Hermes-Ultra as a private, governed, evidence-backed AWS extension while preserving the existing Hermes Dashboard path and model router.

**Architecture:** AWS Hermes remains the only agent brain. Android uses the upstream Dashboard/Gateway on `:9119`; the pinned Relay server/plugin adds private WSS extensions on tailnet-only `:8767`; `:8642` stays optional fallback. Hermes-Ultra stages exact upstream Relay source and lockfiles into its deterministic cloud release, performs Hermes-native plugin scanning before activation, maps Relay operations through the existing consequential-action gate, and reconciles remote completion through the existing provider-independent background-task machinery.

**Tech Stack:** Python 3.11/3.12, Bash, JSON/YAML, Hermes Agent 0.20.5 plugin APIs, Hermes-Relay server 1.10.0, Android 1.13.2, Hermes-Relay Desktop CLI 0.4.0-beta.5, `uv`, `pip --require-hashes`, systemd, Tailscale, durable JSON state, GitHub Actions.

---

## Baseline invariants

Work only on `ai/hermes-relay-sdk-optimization`. Do not edit `src/system/dynamic-router.sh`, `config/cloud-model-catalog.json`, or `tests/test_dynamic_router.sh`. Do not add public AWS ingress, enable Hermes Reach, grant Relay Full Access automatically, store raw Relay bearer tokens, or fetch unpinned production code during AWS activation.

Pinned upstream facts:

```text
Android tag:       android-v1.13.2
Android commit:    a5cc0104bfbda8542667ab50eb70ab02b02a47e5
APK SHA256:        ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d
Server tag:        server-v1.10.0
Server commit:     08545ed32db07609c14730a7fc02cdd758f12434
Server wheel SHA:  26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663
Desktop tag:       desktop-v0.4.0-beta.5
Desktop commit:    8acba9b3539a1905fc7361efcab97de8199a0ac9
Linux x64 SHA256:  2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110
```

Capture protected routing hashes before implementation:

```bash
sha256sum src/system/dynamic-router.sh config/cloud-model-catalog.json tests/test_dynamic_router.sh
```

Expected:

```text
9c6466e48781f4e417dee147524ad33ca78a1a631feb9785d9be3798888495b7  src/system/dynamic-router.sh
9514640689702d7a5f3eaea80bb92453dc98b40847cc3317e8f77faa444b4629  config/cloud-model-catalog.json
d9db6851108bbf4b65a9800d1b58f1faa9d4a7172426368c0583a78ee3add790  tests/test_dynamic_router.sh
```

---

### Task 1: Lock independent Relay component provenance

**Files:**
- Modify: `config/production-versions.json`
- Create: `config/hermes-relay-upstream.json`
- Create: `tests/test_hermes_relay_provenance.py`
- Modify: `tests/test_production_versions.sh`

**Step 1: Write RED tests**

Use the repository's `unittest` style. The new module must require the exact Android/server/desktop tags, commits, artifact digests, MIT license, and independent component versions.

```python
class RelayProvenanceTests(unittest.TestCase):
    def test_android_pin_is_1_13_2(self):
        versions = load_json("config/production-versions.json")
        self.assertEqual(versions["hermes_relay_android"]["tag"], "android-v1.13.2")
        self.assertEqual(versions["hermes_relay_android"]["version"], "1.13.2")

    def test_components_are_independently_pinned(self):
        manifest = load_json("config/hermes-relay-upstream.json")
        self.assertEqual(manifest["android"]["commit"], "a5cc0104bfbda8542667ab50eb70ab02b02a47e5")
        self.assertEqual(manifest["server"]["commit"], "08545ed32db07609c14730a7fc02cdd758f12434")
        self.assertEqual(manifest["desktop"]["commit"], "8acba9b3539a1905fc7361efcab97de8199a0ac9")
        self.assertNotEqual(manifest["android"]["version"], manifest["server"]["version"])
```

Run:

```bash
python3 -m unittest tests.test_hermes_relay_provenance -v
```

Expected RED: missing manifest and stale Android 1.12.0 pin.

**Step 2: Implement minimum provenance**

Update `config/production-versions.json` to Android `android-v1.13.2` / `1.13.2`, with `frozen_at: 2026-08-28`.

Create `config/hermes-relay-upstream.json`:

```json
{
  "schema_version": 1,
  "android": {
    "tag": "android-v1.13.2",
    "version": "1.13.2",
    "commit": "a5cc0104bfbda8542667ab50eb70ab02b02a47e5",
    "artifact": "hermes-relay-1.13.2-sideload-release.apk",
    "artifact_sha256": "ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d",
    "source_url": "https://github.com/Codename-11/hermes-relay",
    "license": "MIT"
  },
  "server": {
    "tag": "server-v1.10.0",
    "version": "1.10.0",
    "commit": "08545ed32db07609c14730a7fc02cdd758f12434",
    "artifact": "hermes_relay-1.10.0-py3-none-any.whl",
    "artifact_sha256": "26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663",
    "source_url": "https://github.com/Codename-11/hermes-relay",
    "license": "MIT"
  },
  "desktop": {
    "tag": "desktop-v0.4.0-beta.5",
    "version": "0.4.0-beta.5",
    "commit": "8acba9b3539a1905fc7361efcab97de8199a0ac9",
    "artifact": "hermes-relay-linux-x64",
    "artifact_sha256": "2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110",
    "prerelease": true,
    "source_url": "https://github.com/Codename-11/hermes-relay",
    "license": "MIT"
  },
  "verified_at": "2026-08-28"
}
```

Have `tests/test_production_versions.sh` execute the new module.

**Step 3: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_hermes_relay_provenance -v
bash tests/test_production_versions.sh
git add config/production-versions.json config/hermes-relay-upstream.json tests/test_hermes_relay_provenance.py tests/test_production_versions.sh
git commit -m "chore: pin Hermes Relay production components"
```

---

### Task 2: Deterministically stage Relay server source and dependencies

**Files:**
- Create: `scripts/export-hermes-relay-dependency-lock.sh`
- Create: `scripts/stage-hermes-relay-source.sh`
- Create: `tests/test_export_hermes_relay_dependency_lock.sh`
- Create: `tests/test_stage_hermes_relay_source.sh`
- Modify: `scripts/build-cloud-release.sh`
- Modify: `tests/test_release_supply_chain.sh`

**Step 1: Write RED fixture tests**

Make `stage-hermes-relay-source.sh` read its production expectations from `config/hermes-relay-upstream.json` by default and accept `--manifest PATH` for test fixtures. The test can therefore create a tiny clean Git repo, fixture manifest, fake wheel, and fixture `uv.lock` without network access. Test dirty tree, wrong commit/tag/version, missing `plugin/plugin.yaml`, wrong wheel digest, and manifest tampering.

Required staged evidence:

```text
vendor/hermes-relay/server-v1.10.0/source/
vendor/hermes-relay/server-v1.10.0/SOURCE_TAG
vendor/hermes-relay/server-v1.10.0/SOURCE_COMMIT
vendor/hermes-relay/server-v1.10.0/SOURCE_PROVENANCE.json
vendor/hermes-relay/server-v1.10.0/SOURCE_MANIFEST.sha256
vendor/hermes-relay/server-v1.10.0/uv.lock
vendor/hermes-relay/server-v1.10.0/requirements-hermes-relay.lock.txt
vendor/hermes-relay/server-v1.10.0/DEPENDENCY_LOCK_PROVENANCE.json
vendor/hermes-relay/server-v1.10.0/hermes_relay-1.10.0-py3-none-any.whl
vendor/hermes-relay/server-v1.10.0/LICENSE
```

Run RED:

```bash
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
```

**Step 2: Implement the lock exporter**

Mirror `scripts/export-hermes-dependency-locks.sh` but export Relay's committed root `uv.lock`:

```bash
(
  cd "$SOURCE_DIR"
  "$UV_BIN" export --locked --format requirements-txt --no-dev \
    --no-emit-project --output-file "$TMP" >/dev/null
)
```

Reject editable/direct-URL requirements and any requirement block without a SHA256 hash. Emit `DEPENDENCY_LOCK_PROVENANCE.json` with the `uv` version and SHA256 of `uv.lock` and the exported runtime requirements.

**Step 3: Implement the source stager**

`stage-hermes-relay-source.sh [--manifest PATH] SOURCE_DIR WHEEL DEST_DIR` must validate the selected manifest's exact server tag/commit/version/wheel digest. Copy only Git-tracked server/runtime inputs: `pyproject.toml`, `uv.lock`, `LICENSE`, `plugin/**`, `relay_server/**`, `hermes_relay_bootstrap/**`, and `hermes_relay_bootstrap.pth` when present. Exclude `.git`, Android, desktop, tests, caches, `.env`, logs, runtime state, and credentials. Generate `SOURCE_MANIFEST.sha256` and `SOURCE_PROVENANCE.json`.

**Step 4: Wire production build**

When `HERMES_PRODUCTION_BUILD=1`, `scripts/build-cloud-release.sh` must additionally require:

```text
HERMES_RELAY_SOURCE_DIR
HERMES_RELAY_SERVER_WHEEL
```

and call the stager into `vendor/hermes-relay/server-v1.10.0`. Do not download Relay inside the build script.

**Step 5: Verify GREEN and commit**

```bash
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
bash tests/test_release_supply_chain.sh
git add scripts/export-hermes-relay-dependency-lock.sh scripts/stage-hermes-relay-source.sh scripts/build-cloud-release.sh tests/test_export_hermes_relay_dependency_lock.sh tests/test_stage_hermes_relay_source.sh tests/test_release_supply_chain.sh
git commit -m "feat: stage pinned Hermes Relay supply chain"
```

---

### Task 3: Add an exhaustive fail-closed Relay authority policy

**Files:**
- Create: `config/hermes-relay-policy.json`
- Create: `src/system/hermes_relay_policy.py`
- Create: `tests/test_hermes_relay_policy.py`

**Step 1: Write RED tests**

Freeze the pinned `plugin/plugin.yaml` `android_*` and `desktop_*` tool names as the expected operation set in the test. Assert every operation is classified, no wildcard grants exist, unknown operations fail closed, ambiguous/missing target device IDs fail closed, Full Access is never selected automatically, and mutating operations produce a valid `hermes-consequential-action-v1` request for the existing `ConsequentialActionGate`.

```python
class RelayPolicyTests(unittest.TestCase):
    def test_unknown_operation_fails_closed(self):
        with self.assertRaisesRegex(RelayPolicyError, "unknown relay operation"):
            self.policy.classify("android_totally_new_power", target_device_id="phone-1")

    def test_mutation_maps_to_gate_schema(self):
        decision = self.policy.classify("android_tap", target_device_id="phone-1")
        request = decision.to_gate_request(
            action_id="relay-123",
            principal="owner",
            actor="hermes",
            purpose="approved device task",
        )
        self.assertEqual(request["schema_version"], "hermes-consequential-action-v1")
        self.assertEqual(request["tool"], "android_tap")
        self.assertEqual(request["destination"], "device:phone-1")
```

Run RED:

```bash
python3 -m unittest tests.test_hermes_relay_policy -v
```

**Step 2: Implement policy data and loader**

Use explicit operation entries, grouped into classes such as `observe`, `device_mutation`, `filesystem_mutation`, `process_control`, and `external_communication`. Configuration defaults must state:

```json
{
  "desktop_access": "ask-every-time",
  "unconfigured_access": "restricted",
  "full_access_auto": false
}
```

`RelayPolicyDecision.to_gate_request()` builds the existing gate schema; it does not bypass `ConsequentialActionGate.authorize()`. Unknown future tools remain denied until explicitly classified.

**Step 3: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_hermes_relay_policy tests.test_consequential_action_gate -v
git add config/hermes-relay-policy.json src/system/hermes_relay_policy.py tests/test_hermes_relay_policy.py
git commit -m "feat: govern Hermes Relay capabilities"
```

---

### Task 4: Validate Relay protocol, correlation, redaction, and completion receipts

**Files:**
- Create: `src/system/hermes_relay_adapter.py`
- Create: `tests/test_hermes_relay_adapter.py`

**Step 1: Write RED protocol tests**

Cover `system/auth.ok`, pinned server compatibility, grant expiry and `null` never-expire, `bridge.status.capabilities` schema 1, unknown capability schema rejection, target-device binding, `bridge.response.request_id` matching, typed `stream.event` schema 1, bounded `(session_id, run_id, seq)` de-duplication, and sensitive-field redaction.

The persisted receipt shape is:

```json
{
  "schema_version": "hermes-relay-completion-receipt-v1",
  "task_id": "task-1",
  "target_device_id": "phone-1",
  "channel": "bridge",
  "operation": "android_tap",
  "request_id": "req-1",
  "authorization_id": "auth-1",
  "terminal_status": "success",
  "result_digest": "sha256:<64 hex>",
  "verification_source": "relay_response"
}
```

Raw session tokens, API keys, Authorization headers, clipboard bodies, screen bodies, and notification bodies must never enter this receipt.

Run RED:

```bash
python3 -m unittest tests.test_hermes_relay_adapter -v
```

**Step 2: Implement focused immutable types**

Use frozen dataclasses `RelaySessionState`, `RelayBridgeCapabilities`, `RelayCompletionReceipt`, plus a bounded `RelayEventDeduper(max_entries=4096)`. Duplicate or out-of-order stream events may update diagnostics but cannot return terminal success.

**Step 3: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_hermes_relay_adapter -v
git add src/system/hermes_relay_adapter.py tests/test_hermes_relay_adapter.py
git commit -m "feat: validate Hermes Relay protocol evidence"
```

---

### Task 5: Reconcile Relay work through the existing background-task engine

**Files:**
- Create: `src/system/hermes_relay_reconciler.py`
- Create: `tests/test_hermes_relay_reconciler.py`
- Modify: `tests/test_governed_graph_runtime.sh`
- Modify: `.github/workflows/governed-graph-runtime-validate.yml`

**Step 1: Write RED reconciliation tests**

Use `BackgroundTaskStore`, `BackgroundTaskReconciler`, and `ProviderInspection`; do not introduce a second task ledger. Test matching receipt success, mismatched device/request verification failure, notification-only non-success, revoked session failure, stale work → stalled, idempotent repeated success, output-hash tamper, and no raw token in provider-task JSON.

**Step 2: Implement sealed Relay receipt state**

Create `RelayReceiptStore` defaulting to `.hermes/state/relay-receipts`, using atomic temp-write/fsync/replace plus content-hash verification. Create `RelayTaskInspector.inspect(provider_task_id)` returning the existing `ProviderInspection`. `relay_evidence_verifier()` must reload the durable receipt and recompute correlation/hash fields; WSS notifications alone are never completion proof.

Register Relay by supplying `inspectors={"relay": inspector.inspect}` to the existing reconciler. Do not weaken `BackgroundTaskReconciler` success semantics.

**Step 3: Add Relay modules to the governed regression suite**

Add the three Relay Python test modules and their source paths to `tests/test_governed_graph_runtime.sh` and both path filters in `.github/workflows/governed-graph-runtime-validate.yml`.

**Step 4: Verify GREEN and commit**

```bash
python3 -m unittest tests.test_hermes_relay_reconciler -v
bash tests/test_governed_graph_runtime.sh
git add src/system/hermes_relay_reconciler.py tests/test_hermes_relay_reconciler.py tests/test_governed_graph_runtime.sh .github/workflows/governed-graph-runtime-validate.yml
git commit -m "feat: reconcile Hermes Relay remote tasks"
```

---

### Task 6: Add two-phase, release-bound Relay installation

**Files:**
- Create: `scripts/install-hermes-relay.sh`
- Create: `tests/test_install_hermes_relay.sh`
- Modify: `scripts/install-cloud-release-local.sh`
- Modify: `tests/test_install_cloud_release_local.sh`

**Step 1: Write RED installer tests**

Use temporary install/var/systemd roots and fake `tailscale`, `systemctl`, and Hermes commands. Assert missing/tampered evidence fails before mutation; non-tailnet bind and `0.0.0.0` are rejected; plugin scan verdict `caution` or `dangerous` fails noninteractively; safe scan permits activation; the unit runs as `hermes` on 8767; no secrets enter the unit; activation failure restores previous plugin link/config/unit; durable Relay sessions/QR/plugin-data are untouched.

Run RED:

```bash
bash tests/test_install_hermes_relay.sh
```

**Step 2: Implement `prepare` mode before runtime/current swaps**

Interface:

```text
install-hermes-relay.sh prepare --release-root PATH --runtime-python PATH --hermes-home PATH [--test-mode]
```

`prepare` must:

1. verify source manifest/provenance, exact tag/commit/version, `uv.lock`, dependency-lock provenance, and official wheel digest;
2. require the detected Tailscale IPv4 to belong to `100.64.0.0/10` using Python `ipaddress`;
3. install only hash-locked Relay dependencies into the **new runtime venv** with `pip install --require-hashes`;
4. invoke pinned Hermes Agent `tools.plugin_guard.scan_plugin()` against staged `source/plugin` and permit only a `safe` production verdict;
5. make no plugin-link, config, service, or `current` mutations.

`install-cloud-release-local.sh` calls `prepare` while the new runtime still lives at `$RUNTIME_TMP`.

**Step 3: Implement `activate` mode after both atomic swaps**

Interface:

```text
install-hermes-relay.sh activate --release-root PATH --runtime-python PATH --hermes-home PATH --systemd-dir PATH [--test-mode]
```

Call `activate` only **after** the installer has moved `$RUNTIME_TMP` to stable `$RUNTIME_ROOT` and atomically switched `/opt/hermes-max/current` to `$TARGET`, but **before** `SUCCESS=1`. This ordering is required so the unit never points at a temporary Python path or the previous release.

`activate` must:

1. snapshot previous plugin symlink, relevant `config.yaml` state, and Relay unit for rollback;
2. link `$HERMES_HOME/plugins/hermes-relay` to `/opt/hermes-max/current/vendor/hermes-relay/server-v1.10.0/source/plugin`;
3. run stable-runtime `hermes plugins enable hermes-relay --no-allow-tool-override` and `hermes plugins doctor hermes-relay --ci`;
4. write a system unit with `User=hermes`, `Group=hermes`, `WorkingDirectory=/opt/hermes-max/current/vendor/hermes-relay/server-v1.10.0/source`, stable `/var/lib/hermes/.hermes/hermes-agent/venv/bin/python -m plugin.relay`, the exact Tailscale IPv4, port 8767, `--no-ssl`, and `--log-level INFO`;
5. include `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict`, `ProtectHome=true`, and narrowly scoped `ReadWritePaths`;
6. daemon-reload/start/restart and poll `http://<tailscale-ip>:8767/health` with a bounded timeout.

If `activate` fails, return nonzero. The surrounding `install-cloud-release-local.sh` cleanup trap must restore prior `current`, prior runtime, and prior Relay link/config/unit state.

**Step 4: Preserve the existing Dashboard gate**

Do not change the existing `127.0.0.1:9119/api/health` requirement or version check. Both Dashboard and Relay health must pass before `SUCCESS=1`.

**Step 5: Verify GREEN and commit**

```bash
bash tests/test_install_hermes_relay.sh
bash tests/test_install_cloud_release_local.sh
git add scripts/install-hermes-relay.sh scripts/install-cloud-release-local.sh tests/test_install_hermes_relay.sh tests/test_install_cloud_release_local.sh
git commit -m "feat: install Hermes Relay from verified releases"
```

---

### Task 7: Reconcile Relay service/code on cloud rollback without deleting Relay data

**Files:**
- Modify: `scripts/install-hermes-relay.sh`
- Modify: `scripts/rollback-cloud-release.sh`
- Modify: `tests/test_cloud_release_rollback.sh`

**Step 1: Add RED rollback cases**

Create Relay-enabled and pre-Relay release fixtures. Assert rollback to Relay-enabled code re-points the plugin/unit; rollback to pre-Relay code stops/disables Relay and removes only the plugin code link; `hermes-relay-sessions.json`, plugin-data, QR signing identity, and other durable Hermes state remain untouched; tampered release manifests still block rollback.

**Step 2: Add reconciliation modes**

Add to `install-hermes-relay.sh`:

```text
reconcile --release-root PATH --runtime-python PATH ...
deactivate-code-only ...
```

`reconcile` verifies the target Relay evidence before relinking/restarting. If the rollback target has no Relay payload, `rollback-cloud-release.sh` uses `deactivate-code-only`: stop/disable service and remove code link/config enablement only. Never purge Relay credentials or durable data.

**Step 3: Verify GREEN and commit**

```bash
bash tests/test_cloud_release_rollback.sh
bash tests/test_install_hermes_relay.sh
git add scripts/install-hermes-relay.sh scripts/rollback-cloud-release.sh tests/test_cloud_release_rollback.sh tests/test_install_hermes_relay.sh
git commit -m "feat: preserve Relay state across cloud rollback"
```

---

### Task 8: Verify Desktop CLI 0.4.0-beta.5 as the dev-companion surface

**Files:**
- Create: `tests/test_hermes_relay_desktop_pin.py`
- Modify only if a newer release is proven before execution: `config/hermes-relay-upstream.json`
- No Hermes-Ultra desktop fork

**Step 1: Write the pin test**

Require tag `desktop-v0.4.0-beta.5`, commit `8acba9b3539a1905fc7361efcab97de8199a0ac9`, Linux x64 digest `2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110`, and `prerelease: true`. A desktop install is forbidden if any immutable field is absent.

**Step 2: Recheck upstream immediately before install**

If a newer `desktop-v*` release appears before implementation reaches this task, do not auto-upgrade. Verify its tag target, Linux x64 digest, release notes, and compatibility first, update provenance/tests in a separate RED→GREEN commit, then continue. Never substitute Android's commit/version for Desktop.

**Step 3: Verify the selected Desktop CLI before installing on a dev machine**

For the beta.5 release binary, verify SHA256 before installation. For source verification, check out exact commit `8acba9b3539a1905fc7361efcab97de8199a0ac9` and run from `desktop/`:

```bash
npm ci
npm run verify
```

Only then install the verified CLI/daemon on Penguin or another approved dev machine. Default host access is Ask Every Time; unconfigured stays Restricted; Full Access is not automatic.

**Step 4: Run tests and commit**

```bash
python3 -m unittest tests.test_hermes_relay_desktop_pin -v
git add tests/test_hermes_relay_desktop_pin.py config/hermes-relay-upstream.json
git commit -m "test: verify Hermes Relay desktop companion pin"
```

If provenance did not change, add only the test file.

---

### Task 9: Add bounded Relay diagnostics and deployment runbook

**Files:**
- Create: `scripts/hermes-relay-doctor.sh`
- Create: `tests/test_hermes_relay_doctor.sh`
- Create: `docs/deployment/hermes-relay.md`

**Step 1: Write RED doctor tests**

Require distinct `healthy`, `degraded`, `stalled`, `incompatible`, and `unauthorized` states. Cover Dashboard healthy/Relay down, protocol mismatch, tailnet bind violation, missing/expired grants, and redaction.

**Step 2: Implement compact JSON diagnostics**

Example output:

```json
{
  "status": "healthy",
  "dashboard": {"ok": true, "version": "0.20.5"},
  "relay": {"ok": true, "version": "1.10.0", "clients": 0, "sessions": 0},
  "bind": {"host": "100.x.y.z", "port": 8767, "tailnet_only": true},
  "compatibility": {"server_pin": "server-v1.10.0", "protocol_ok": true},
  "last_receipt": null
}
```

Never print raw tokens, headers, clipboard/screen bodies, or notification content.

**Step 3: Write `docs/deployment/hermes-relay.md`**

Document Dashboard `:9119` primary, Relay `:8767` extension-only/tailnet-only, API `:8642` optional, doctor usage, one-time pairing, Android APK digest, Desktop beta status, device revocation, rollback, no Full Access automation, and no public SG rule.

**Step 4: Verify and commit**

```bash
bash tests/test_hermes_relay_doctor.sh
git add scripts/hermes-relay-doctor.sh tests/test_hermes_relay_doctor.sh docs/deployment/hermes-relay.md
git commit -m "docs: add Hermes Relay production diagnostics"
```

---

### Task 10: Add Relay gates to CI and prove routing preservation

**Files:**
- Modify: `.github/workflows/cloud-foundation-validate.yml`
- Modify: `tests/test_governed_graph_runtime.sh` only if Task 5 did not already include every Relay module
- Router files: verify only; do not edit

**Step 1: Extend cloud CI**

Add local-safe Relay tests:

```bash
python3 -m unittest tests.test_hermes_relay_provenance tests.test_hermes_relay_desktop_pin -v
python3 -m unittest tests.test_hermes_relay_policy tests.test_hermes_relay_adapter tests.test_hermes_relay_reconciler -v
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
bash tests/test_install_hermes_relay.sh
bash tests/test_hermes_relay_doctor.sh
```

Do not add ordinary-CI dependencies on downloading production artifacts.

**Step 2: Run full local verification**

```bash
git diff --check
bash tests/test_governed_graph_runtime.sh
bash tests/test_dynamic_router.sh
python3 -m unittest tests.test_plugin_intake tests.test_provenance_envelope -v
bash tests/test_trajectory_fabric.sh
bash tests/test_memory_fabric.sh
bash tests/test_cloud_foundation.sh
bash tests/test_aws_runtime_secrets.sh
bash tests/test_cloud_release_rollback.sh
bash tests/test_export_hermes_dependency_locks.sh
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_install_cloud_release_local.sh
bash tests/test_install_hermes_relay.sh
bash tests/test_production_versions.sh
bash tests/test_release_supply_chain.sh
bash tests/test_secret_scan_production.sh
bash tests/test_stage_hermes_agent_source.sh
bash tests/test_stage_hermes_relay_source.sh
bash tests/test_hermes_relay_doctor.sh
bash scripts/secret-scan-production.sh
```

Run `bash tests/test_aws_production_preflight.sh` separately when AWS identity is available; lack of local AWS auth is not a reason to skip any local gate.

**Step 3: Re-prove router hashes**

```bash
sha256sum src/system/dynamic-router.sh config/cloud-model-catalog.json tests/test_dynamic_router.sh
```

All three outputs must exactly match the baseline hashes at the top of this plan.

**Step 4: Commit**

```bash
git add .github/workflows/cloud-foundation-validate.yml tests/test_governed_graph_runtime.sh
git commit -m "test: gate Hermes Relay production integration"
```

---

### Task 11: Build the production release from immutable inputs

**Files:** no new source files expected; generated `dist/*` is not committed.

**Step 1: Prepare exact build inputs on Penguin**

Use these deterministic locations:

```bash
HERMES_AGENT_SOURCE_DIR="$HOME/.cache/hermes-agent-production-v2026.8.19"
HERMES_RELAY_SOURCE_DIR="$HOME/.cache/hermes-relay-server-v1.10.0"
HERMES_RELAY_ARTIFACT_DIR="$HOME/.cache/hermes-relay-artifacts/server-v1.10.0"
HERMES_RELAY_SERVER_WHEEL="$HERMES_RELAY_ARTIFACT_DIR/hermes_relay-1.10.0-py3-none-any.whl"
```

Create/refresh the Relay checkout directly at exact commit `08545ed32db07609c14730a7fc02cdd758f12434`; require clean status and tag `server-v1.10.0`. Obtain the official wheel before build and verify:

```text
26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663
```

**Step 2: Build**

```bash
HERMES_PRODUCTION_BUILD=1 \
HERMES_AGENT_SOURCE_DIR="$HERMES_AGENT_SOURCE_DIR" \
HERMES_RELAY_SOURCE_DIR="$HERMES_RELAY_SOURCE_DIR" \
HERMES_RELAY_SERVER_WHEEL="$HERMES_RELAY_SERVER_WHEEL" \
  bash scripts/build-cloud-release.sh
```

Expected evidence includes Hermes source stage PASS, Relay source stage PASS, secret scans PASS, release path, and `.sha256` path.

**Step 3: Independently verify extracted release**

```bash
sha256sum -c dist/hermes-max-cloud-*.tar.gz.sha256
TMP="$(mktemp -d)"
tar -xzf "$(ls -t dist/hermes-max-cloud-*.tar.gz | head -1)" -C "$TMP"
cd "$TMP/hermes-max"
sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null
sha256sum vendor/hermes-relay/server-v1.10.0/hermes_relay-1.10.0-py3-none-any.whl
cat vendor/hermes-relay/server-v1.10.0/SOURCE_COMMIT
```

Expected wheel SHA and source commit match the baseline. Run the secret scanner against the extracted tree again.

---

### Task 12: Roll the verified release to AWS and prove an end-to-end round trip

**Files:** no source changes unless a live defect is first reproduced by a failing regression test.

**Step 1: Record read-only pre-deploy evidence**

Over private Tailscale SSH to `ubuntu@hermes-max-primary`, record active release, `hermes-runtime.service`, Dashboard health, a filename-only durable-state fingerprint, listening ports, and whether `hermes-relay.service` already exists. Do not read secret/session contents.

**Step 2: Transfer and verify**

Transfer only over the private Tailscale management channel. Compare local and remote SHA256 before installation.

**Step 3: Install through the existing atomic release installer**

```bash
sudo bash /tmp/install-cloud-release-local.sh \
  /tmp/hermes-max-cloud-<stamp>.tar.gz \
  <exact-release-sha256>
```

Expected: `HERMES_LOCAL_INSTALL=PASS release=<sha-prefix>`. Any Relay prepare/activate/health failure must return nonzero and trigger restoration of prior current/runtime/Relay activation state.

**Step 4: Verify production surfaces**

```bash
sudo systemctl is-active hermes-runtime.service
sudo systemctl is-active hermes-relay.service
curl -fsS http://127.0.0.1:9119/api/health
TSIP="$(tailscale ip -4 | head -1)"
curl -fsS "http://$TSIP:8767/health"
sudo /opt/hermes-max/current/scripts/hermes-relay-doctor.sh
sudo ss -ltnp
```

Require Hermes 0.20.5 on 9119, Relay 1.10.0 on the Tailscale IP:8767 only, and no public EC2 ingress change.

**Step 5: Pair Android v1.13.2 only if needed**

Use the official sideload APK whose SHA is pinned in Task 1. The only user-held action allowed to remain is scanning/accepting the one-time pairing QR. Never request a raw Relay session token.

**Step 6: Prove harmless correlated execution**

Prefer `android_ping` or `desktop_health`. Record stable target device ID, request ID, policy class, matched response, result digest, durable receipt path/hash, and reconciler terminal state. A notification alone is not success.

**Step 7: Rehearse rollback/state preservation**

Use a safe rollback or test-mode rehearsal. Verify Relay session/signing/plugin-data fingerprints survive. A pre-Relay target may deactivate Relay code/service, but must not delete durable Relay state.

---

### Task 13: Final verification and publish without touching `main`

**Files:** update `docs/deployment/evidence-template.md` only if a Relay evidence section is useful.

**Step 1: Run final gates**

```bash
git status --short --branch
git diff --check
bash tests/test_governed_graph_runtime.sh
bash tests/test_dynamic_router.sh
bash tests/test_cloud_foundation.sh
bash tests/test_cloud_release_rollback.sh
bash tests/test_install_cloud_release_local.sh
bash tests/test_install_hermes_relay.sh
bash tests/test_release_supply_chain.sh
bash tests/test_secret_scan_production.sh
bash scripts/secret-scan-production.sh
```

**Step 2: Re-prove protected routing hashes**

They must exactly match the three baseline values in this plan. Any mismatch blocks release.

**Step 3: Inspect history and working tree**

```bash
git log --oneline --decorate -15
git status --porcelain
```

No `.env`, APK, generated release archive, raw bearer token, session file, or user credential may be committed.

**Step 4: Publish only the optimization branch**

Push/update only `ai/hermes-relay-sdk-optimization`. Create a release tag only after AWS and round-trip verification pass. Do not merge, fast-forward, or force-update `main` in this tranche.

**Step 5: Record final evidence**

Include Hermes-Ultra source commit; cloud release SHA256; Android tag/commit/APK SHA; Relay server tag/commit/wheel SHA; Desktop tag/commit/artifact SHA; AWS active release; Dashboard and Relay health/version/bind; router hashes; secret-scan result; harmless round-trip request ID/receipt digest; and rollback/state-preservation result. Exclude all raw credentials and sensitive device content.

---

## Definition of Done

Do not claim completion until Android is pinned to 1.13.2; Relay server/plugin 1.10.0 is staged from immutable verified inputs; Relay dependencies are hash-locked; the plugin passes Hermes-native security scanning; Dashboard `:9119` remains primary and healthy; Relay `:8767` is tailnet-only; Desktop CLI 0.4.0-beta.5 (or a separately verified newer tagged release) is independently verified as the dev-companion surface; authority mapping is exhaustive and fail-closed; remote success is correlated and reconciled through existing Hermes task state; secrets are redacted; rollback preserves Relay durable state; the existing model-router hashes are unchanged; all test/secret/release gates pass; and a harmless AWS round trip is proven or the sole remaining action is the user's one-time mobile pairing approval.
