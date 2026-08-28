# Hermes Relay SDK Optimization Implementation Plan

> **For Melo:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate the pinned official Hermes-Relay Android/server/desktop surfaces into Hermes-Ultra as a private, governed, evidence-backed AWS extension while preserving the existing Hermes Dashboard path and model router.

**Architecture:** AWS Hermes remains the only agent brain. Android uses the upstream Dashboard/Gateway on `:9119`; the pinned Relay server/plugin adds WSS extensions on tailnet-only `:8767`; `:8642` stays optional fallback. Hermes-Ultra stages exact upstream Relay source and lockfiles into its deterministic cloud release, scans and enables the plugin from local staged content, maps Relay operations through the existing consequential-action gate, and reconciles remote completion through the existing provider-independent background-task machinery.

**Tech Stack:** Python 3.12/3.11, Bash, JSON/YAML, Hermes Agent 0.20.5 plugin APIs, Hermes-Relay server 1.10.0, Android 1.13.2, `uv`, `pip --require-hashes`, systemd, Tailscale, SQLite/JSON durable state, GitHub Actions.

---

## Baseline invariants

Before every task, work only on `ai/hermes-relay-sdk-optimization`. Do not edit `src/system/dynamic-router.sh`, `config/cloud-model-catalog.json`, or `tests/test_dynamic_router.sh`. Do not add public AWS ingress, enable Hermes Reach, grant Relay Full Access automatically, store raw Relay bearer tokens, or fetch unpinned production code during AWS activation.

Pinned upstream facts used by this plan:

```text
Android tag:       android-v1.13.2
Android commit:    a5cc0104bfbda8542667ab50eb70ab02b02a47e5
APK SHA256:        ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d
Server tag:        server-v1.10.0
Server commit:     08545ed32db07609c14730a7fc02cdd758f12434
Server wheel SHA:  26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663
Desktop tag:       desktop-v0.3.0-alpha.18
Desktop commit:    ab1924d44089c06b99afd1d64afc1d7da42fcb28
Linux x64 SHA256:  efa6e9ce27e03d10f057c9ce992b5fc5185dbf8803e7c605267e4fd2ac04b265
```

At the start, capture the protected router hashes:

```bash
sha256sum src/system/dynamic-router.sh config/cloud-model-catalog.json tests/test_dynamic_router.sh
```

Expected values:

```text
ad04816c63dd56d2f8469218e7d40a294ffa3697  src/system/dynamic-router.sh
eb2503bef0c561b6aba839e5ca7d6d37263d5bdd  config/cloud-model-catalog.json
960a9bec716e55f290d14cd9aa3ab454a0c50aa2  tests/test_dynamic_router.sh
```

---

### Task 1: Lock independent Relay component provenance

**Files:**
- Modify: `config/production-versions.json`
- Create: `config/hermes-relay-upstream.json`
- Create: `tests/test_hermes_relay_provenance.py`
- Modify: `tests/test_production_versions.sh`

**Step 1: Write the failing provenance tests**

Create `tests/test_hermes_relay_provenance.py` with tests that require independent Android/server/desktop records and exact immutable identifiers:

```python
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text())


def test_android_pin_is_1_13_2():
    versions = load_json("config/production-versions.json")
    relay = versions["hermes_relay_android"]
    assert relay["tag"] == "android-v1.13.2"
    assert relay["version"] == "1.13.2"


def test_relay_components_are_independently_pinned():
    manifest = load_json("config/hermes-relay-upstream.json")
    assert manifest["schema_version"] == 1
    assert manifest["android"]["commit"] == "a5cc0104bfbda8542667ab50eb70ab02b02a47e5"
    assert manifest["server"]["commit"] == "08545ed32db07609c14730a7fc02cdd758f12434"
    assert manifest["desktop"]["commit"] == "ab1924d44089c06b99afd1d64afc1d7da42fcb28"
    for component in ("android", "server", "desktop"):
        assert manifest[component]["license"] == "MIT"
        assert len(manifest[component]["artifact_sha256"]) == 64


def test_server_pin_does_not_inherit_android_version():
    manifest = load_json("config/hermes-relay-upstream.json")
    assert manifest["server"]["tag"] == "server-v1.10.0"
    assert manifest["server"]["version"] == "1.10.0"
    assert manifest["server"]["version"] != manifest["android"]["version"]
```

Update `tests/test_production_versions.sh` so it also executes this module.

**Step 2: Run the test to verify RED**

```bash
python3 -m unittest tests.test_hermes_relay_provenance -v
```

Expected: FAIL because `config/hermes-relay-upstream.json` does not exist and the Android production pin is still 1.12.0.

**Step 3: Implement the minimum manifest and pin update**

Update `config/production-versions.json` Android fields to 1.13.2 and set `frozen_at` to `2026-08-28`.

Create `config/hermes-relay-upstream.json` with this shape:

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
    "tag": "desktop-v0.3.0-alpha.18",
    "version": "0.3.0-alpha.18",
    "commit": "ab1924d44089c06b99afd1d64afc1d7da42fcb28",
    "artifact": "hermes-relay-linux-x64",
    "artifact_sha256": "efa6e9ce27e03d10f057c9ce992b5fc5185dbf8803e7c605267e4fd2ac04b265",
    "prerelease": true,
    "source_url": "https://github.com/Codename-11/hermes-relay",
    "license": "MIT"
  },
  "verified_at": "2026-08-28"
}
```

**Step 4: Run GREEN**

```bash
python3 -m unittest tests.test_hermes_relay_provenance -v
bash tests/test_production_versions.sh
```

Expected: all Relay provenance tests PASS; existing Hermes Agent production pin tests remain PASS.

**Step 5: Commit**

```bash
git add config/production-versions.json config/hermes-relay-upstream.json tests/test_hermes_relay_provenance.py tests/test_production_versions.sh
git commit -m "chore: pin Hermes Relay production components"
```

---

### Task 2: Deterministically stage Relay server source and locked dependencies

**Files:**
- Create: `scripts/export-hermes-relay-dependency-lock.sh`
- Create: `scripts/stage-hermes-relay-source.sh`
- Create: `tests/test_export_hermes_relay_dependency_lock.sh`
- Create: `tests/test_stage_hermes_relay_source.sh`
- Modify: `scripts/build-cloud-release.sh`
- Modify: `tests/test_release_supply_chain.sh`

**Step 1: Write RED tests for exact source identity and dependency locking**

`tests/test_stage_hermes_relay_source.sh` must construct a tiny fixture Git checkout tagged `server-v1.10.0` and prove the stager rejects dirty trees, wrong commits/tags/versions, missing `plugin/plugin.yaml`, and wrong wheel digest.

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

The dependency-lock test must reject editable requirements, direct URLs, and any requirement block without `--hash=sha256:`.

**Step 2: Run RED**

```bash
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
```

Expected: both fail because scripts are absent.

**Step 3: Implement the lock exporter**

Mirror `scripts/export-hermes-dependency-locks.sh`, but export the Relay root `uv.lock` with no project emission:

```bash
(
  cd "$SOURCE_DIR"
  "$UV_BIN" export --locked --format requirements-txt --no-dev \
    --no-emit-project --output-file "$TMP" >/dev/null
)
```

Post-process every block exactly like the Hermes lock exporter: no `-e`, `git+`, `http://`, or `https://`; every requirement must carry at least one SHA256 hash. Write `DEPENDENCY_LOCK_PROVENANCE.json` containing `uv_version`, `uv_lock_sha256`, and `runtime_requirements_sha256`.

**Step 4: Implement the source stager**

`stage-hermes-relay-source.sh SOURCE_DIR WHEEL DEST_DIR` must:

1. require a clean Git checkout;
2. require `pyproject.toml` project version `1.10.0`;
3. require HEAD exactly `08545ed32db07609c14730a7fc02cdd758f12434`;
4. require tag `server-v1.10.0` at HEAD;
5. require `plugin/plugin.yaml` manifest version 1 and plugin version 1.10.0;
6. verify the official wheel SHA256 exactly;
7. copy only tracked server/runtime inputs: `pyproject.toml`, `uv.lock`, `LICENSE`, `plugin/**`, `relay_server/**`, `hermes_relay_bootstrap/**`, and `hermes_relay_bootstrap.pth` when present;
8. exclude `.git`, tests, Android, desktop, caches, user state, `.env`, logs, and credentials;
9. export dependency locks;
10. create `SOURCE_MANIFEST.sha256` and `SOURCE_PROVENANCE.json`.

Use `git ls-files -z` as the source-of-truth instead of filesystem globbing.

**Step 5: Wire the cloud build**

When `HERMES_PRODUCTION_BUILD=1`, extend `scripts/build-cloud-release.sh` to require:

```bash
HERMES_RELAY_SOURCE_DIR
HERMES_RELAY_SERVER_WHEEL
```

Then call:

```bash
bash "$ROOT_DIR/scripts/stage-hermes-relay-source.sh" \
  "$HERMES_RELAY_SOURCE_DIR" \
  "$HERMES_RELAY_SERVER_WHEEL" \
  "$STAGE/vendor/hermes-relay/server-v1.10.0"
```

Do not download either input inside the build script.

**Step 6: Run GREEN**

```bash
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
bash tests/test_release_supply_chain.sh
```

Expected: PASS, including negative tamper cases.

**Step 7: Commit**

```bash
git add scripts/export-hermes-relay-dependency-lock.sh scripts/stage-hermes-relay-source.sh scripts/build-cloud-release.sh tests/test_export_hermes_relay_dependency_lock.sh tests/test_stage_hermes_relay_source.sh tests/test_release_supply_chain.sh
git commit -m "feat: stage pinned Hermes Relay supply chain"
```

---

### Task 3: Add a fail-closed Relay capability and authority policy

**Files:**
- Create: `config/hermes-relay-policy.json`
- Create: `src/system/hermes_relay_policy.py`
- Create: `tests/test_hermes_relay_policy.py`

**Step 1: Write RED tests**

Tests must prove:

- every `android_*` and `desktop_*` tool declared by the pinned `plugin/plugin.yaml` is classified;
- unknown operations fail closed;
- ambiguous target device IDs fail closed;
- Full Access is never selected by policy code;
- read-only operations do not manufacture a consequential authorization receipt;
- mutating operations become an exact `hermes-consequential-action-v1` request suitable for `ConsequentialActionGate.authorize()`;
- communication and process-control operations receive higher risk classes;
- raw bearer/session tokens never appear in a policy decision object.

Representative test:

```python
from hermes_relay_policy import RelayPolicy, RelayPolicyError


def test_unknown_operation_fails_closed(policy):
    with pytest.raises(RelayPolicyError, match="unknown relay operation"):
        policy.classify("android_totally_new_power", target_device_id="phone-1")


def test_mutation_maps_to_existing_gate_schema(policy):
    decision = policy.classify("android_tap", target_device_id="phone-1")
    request = decision.to_gate_request(
        action_id="relay-123",
        principal="melo",
        actor="hermes",
        purpose="approved device task",
    )
    assert request["schema_version"] == "hermes-consequential-action-v1"
    assert request["tool"] == "android_tap"
    assert request["destination"] == "device:phone-1"
```

**Step 2: Run RED**

```bash
python3 -m unittest tests.test_hermes_relay_policy -v
```

Expected: import/file failure.

**Step 3: Implement the policy**

`config/hermes-relay-policy.json` must use explicit tool names from `server-v1.10.0` instead of permissive wildcard authority. Group tools by classes such as:

```json
{
  "schema_version": 1,
  "defaults": {"desktop_access": "ask-every-time", "unconfigured_access": "restricted", "full_access_auto": false},
  "classes": {
    "observe": {"consequential": false},
    "device_mutation": {"consequential": true, "action_type": "relay.device_mutation", "risk_class": "medium"},
    "filesystem_mutation": {"consequential": true, "action_type": "relay.filesystem_mutation", "risk_class": "medium"},
    "process_control": {"consequential": true, "action_type": "relay.process_control", "risk_class": "high"},
    "external_communication": {"consequential": true, "action_type": "relay.external_communication", "risk_class": "high"}
  },
  "operations": {}
}
```

Populate `operations` exhaustively from the pinned manifest. Do not silently classify unknown future tools.

`src/system/hermes_relay_policy.py` should expose immutable `RelayPolicyDecision` plus `RelayPolicy.load(path)` and `classify(operation, target_device_id)`.

**Step 4: Run GREEN and regression-test the existing gate**

```bash
python3 -m unittest tests.test_hermes_relay_policy tests.test_consequential_action_gate -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add config/hermes-relay-policy.json src/system/hermes_relay_policy.py tests/test_hermes_relay_policy.py
git commit -m "feat: govern Hermes Relay capabilities"
```

---

### Task 4: Implement protocol parsing, correlation, redaction, and completion receipts

**Files:**
- Create: `src/system/hermes_relay_adapter.py`
- Create: `tests/test_hermes_relay_adapter.py`

**Step 1: Write RED tests for the wire contract**

Cover:

- `system/auth.ok` parsing;
- exact server compatibility against the pinned server version;
- grant expiry and `null` never-expire handling;
- `bridge.status.capabilities` schema 1;
- unknown capability schema fail-closed;
- `bridge.response.request_id` correlation;
- target device binding;
- typed `stream.event` schema 1;
- bounded de-duplication on `(session_id, run_id, seq)`;
- duplicate/out-of-order events cannot mark success;
- redaction of `session_token`, API keys, auth headers, clipboard/screen/notification payloads;
- canonical SHA256 completion receipts.

Receipt shape to test:

```python
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
    "verification_source": "relay_response",
}
```

**Step 2: Run RED**

```bash
python3 -m unittest tests.test_hermes_relay_adapter -v
```

Expected: import failure.

**Step 3: Implement focused protocol types**

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class RelaySessionState:
    server_version: str
    expires_at: datetime | None
    grants: Mapping[str, datetime | None]
    transport_hint: str

@dataclass(frozen=True)
class RelayCompletionReceipt:
    task_id: str
    target_device_id: str
    channel: str
    operation: str
    request_id: str
    authorization_id: str
    terminal_status: str
    result_digest: str
    verification_source: str
```

Keep raw bearer tokens out of these dataclasses. The caller may hold a token in process memory for transport, but persisted adapter state stores at most a bounded token prefix or stable session identifier.

Implement an `RelayEventDeduper(max_entries=4096)` using an ordered bounded set; an already-seen key returns `False`, but never returns terminal success.

**Step 4: Run GREEN**

```bash
python3 -m unittest tests.test_hermes_relay_adapter -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/system/hermes_relay_adapter.py tests/test_hermes_relay_adapter.py
git commit -m "feat: validate Hermes Relay protocol evidence"
```

---

### Task 5: Reconcile Relay tasks through the existing provider-independent engine

**Files:**
- Create: `src/system/hermes_relay_reconciler.py`
- Create: `tests/test_hermes_relay_reconciler.py`
- Modify: `tests/test_governed_graph_runtime.sh`
- Modify: `.github/workflows/governed-graph-runtime-validate.yml`

**Step 1: Write RED reconciliation tests**

Use the existing `BackgroundTaskStore` / `BackgroundTaskReconciler` contracts. Do not add a second task ledger.

Required cases:

1. matching Relay completion receipt → `ProviderInspection(status="completed", evidence=(receipt_path,), output_hash=...)`;
2. mismatched device/request → verificationPending or failure, never success;
3. notification without durable receipt → running;
4. revoked session → failed/unauthorized;
5. unchanged progress past stale threshold → stalled;
6. repeated reconciliation after success → idempotent success;
7. output hash tamper → verificationPending;
8. no raw token appears in provider-task JSON.

Representative inspector contract:

```python
inspection = RelayTaskInspector(receipt_store).inspect("relay:req-123")
assert isinstance(inspection, ProviderInspection)
assert inspection.status == "completed"
assert inspection.evidence
assert inspection.output_hash.startswith("sha256:")
```

**Step 2: Run RED**

```bash
python3 -m unittest tests.test_hermes_relay_reconciler -v
```

Expected: import failure.

**Step 3: Implement a sealed receipt store and inspector**

`hermes_relay_reconciler.py` should expose:

- `RelayReceiptStore` under `.hermes/state/relay-receipts` by default;
- atomic fsync + replace writes;
- content-hash verification on load;
- `RelayTaskInspector.inspect(provider_task_id)` returning the existing `ProviderInspection` type;
- `relay_evidence_verifier(...)` which reloads the receipt, checks correlation fields, recomputes the result digest, and never accepts notification-only completion.

Register Relay by passing `inspectors={"relay": inspector.inspect}` into the existing `BackgroundTaskReconciler`. Do **not** modify its success semantics.

**Step 4: Add to governed graph regression suite**

Append `tests.test_hermes_relay_policy`, `tests.test_hermes_relay_adapter`, and `tests.test_hermes_relay_reconciler` to `tests/test_governed_graph_runtime.sh`. Add their source/test paths to both push and pull-request path filters in `.github/workflows/governed-graph-runtime-validate.yml`.

**Step 5: Run GREEN**

```bash
python3 -m unittest tests.test_hermes_relay_reconciler -v
bash tests/test_governed_graph_runtime.sh
```

Expected: all existing governed graph tests plus Relay tests PASS.

**Step 6: Commit**

```bash
git add src/system/hermes_relay_reconciler.py tests/test_hermes_relay_reconciler.py tests/test_governed_graph_runtime.sh .github/workflows/governed-graph-runtime-validate.yml
git commit -m "feat: reconcile Hermes Relay remote tasks"
```

---

### Task 6: Install the staged Relay plugin without a live production fetch

**Files:**
- Create: `scripts/install-hermes-relay.sh`
- Create: `tests/test_install_hermes_relay.sh`
- Modify: `scripts/install-cloud-release-local.sh`
- Modify: `tests/test_install_cloud_release_local.sh`

**Step 1: Write RED installer tests**

The test harness must use temporary install/var/systemd roots and fake `tailscale`, `systemctl`, and Hermes commands. Assert:

- missing Relay evidence fails before mutation;
- source manifest tamper fails;
- dependency-lock tamper fails;
- non-tailnet bind address fails;
- `0.0.0.0` is never written to the production unit;
- plugin security verdict `caution` or `dangerous` fails non-interactively;
- safe scan creates the plugin link and enables without tool override;
- service uses port 8767 and the Hermes runtime identity;
- raw secrets are absent from unit/config output;
- failed activation restores the previous plugin link/service state;
- durable `~/.hermes` Relay session/QR state is never removed.

**Step 2: Run RED**

```bash
bash tests/test_install_hermes_relay.sh
```

Expected: fail because installer is absent.

**Step 3: Implement the installer as a release-bound helper**

Interface:

```text
install-hermes-relay.sh --release-root PATH --runtime-python PATH --hermes-home PATH --systemd-dir PATH [--test-mode]
```

Required sequence:

1. verify `SOURCE_MANIFEST.sha256`, `SOURCE_PROVENANCE.json`, exact server tag/commit/version, `uv.lock`, dependency-lock provenance, and wheel digest;
2. determine the Tailscale IPv4 using `tailscale ip -4` and require membership in `100.64.0.0/10` using Python `ipaddress`;
3. install only the hash-locked Relay dependencies into the **new Hermes runtime venv** with `pip install --require-hashes -r requirements-hermes-relay.lock.txt`;
4. run the pinned Hermes Agent `tools.plugin_guard.scan_plugin()` against the staged `source/plugin` tree and permit only a `safe` noninteractive verdict;
5. create/replace `$HERMES_HOME/plugins/hermes-relay` as a symlink to the staged immutable `source/plugin` path;
6. run `hermes plugins enable hermes-relay --no-allow-tool-override` and `hermes plugins doctor hermes-relay --ci` under the Hermes runtime identity;
7. write a system unit with `User=hermes`, `Group=hermes`, `WorkingDirectory=/opt/hermes-max/current/vendor/hermes-relay/server-v1.10.0/source`, and an `ExecStart` equivalent to:

```text
/var/lib/hermes/.hermes/hermes-agent/venv/bin/python -m plugin.relay --host 100.x.y.z --port 8767 --no-ssl --log-level INFO
```

8. harden the unit with `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict`, `ProtectHome=true`, and only the required Hermes/installation paths writable;
9. start/restart only after all previous checks pass;
10. poll `http://<tailscale-ip>:8767/health` with a bounded timeout;
11. on failure restore previous symlink/unit state and leave Relay durable session state untouched.

Do not run upstream `install.sh` in production and do not run `hermes plugins install` against GitHub during activation.

**Step 4: Wire into `install-cloud-release-local.sh` before final success**

After the new Hermes runtime venv has been populated and before `SUCCESS=1`, call the Relay installer using the staged target release. Extend the cleanup trap so a Relay activation failure prevents the release from becoming current and restores the pre-install Relay service/link state.

The normal Hermes health gate on `127.0.0.1:9119/api/health` must remain unchanged.

**Step 5: Run GREEN**

```bash
bash tests/test_install_hermes_relay.sh
bash tests/test_install_cloud_release_local.sh
```

Expected: PASS, including all tamper/rollback tests.

**Step 6: Commit**

```bash
git add scripts/install-hermes-relay.sh scripts/install-cloud-release-local.sh tests/test_install_hermes_relay.sh tests/test_install_cloud_release_local.sh
git commit -m "feat: install Hermes Relay from verified releases"
```

---

### Task 7: Make cloud rollback reconcile Relay service state without deleting Relay data

**Files:**
- Modify: `scripts/rollback-cloud-release.sh`
- Modify: `tests/test_cloud_release_rollback.sh`

**Step 1: Add RED rollback cases**

Extend the rollback test with two release fixtures:

- Relay-enabled release containing `vendor/hermes-relay/server-v1.10.0`;
- pre-Relay release without it.

Assert:

- rollback to Relay-enabled release re-points plugin code/service configuration to that release;
- rollback to pre-Relay release stops/disables the Relay service and removes only the code symlink;
- `hermes-relay-sessions.json`, plugin-data, QR signing identity, and other durable Hermes state remain untouched;
- a tampered target manifest still prevents rollback.

**Step 2: Run RED**

```bash
bash tests/test_cloud_release_rollback.sh
```

Expected: new Relay reconciliation assertions fail.

**Step 3: Add an activation-only mode to `install-hermes-relay.sh`**

Add:

```text
--activate-existing PATH
--deactivate-code-only
```

`--activate-existing` must verify the existing release manifest/evidence before rewriting the symlink/unit. `--deactivate-code-only` stops Relay and removes the code link but never deletes session/token/signing/plugin-data files.

Call the appropriate mode from `rollback-cloud-release.sh` after the atomic `current` symlink switch.

**Step 4: Run GREEN**

```bash
bash tests/test_cloud_release_rollback.sh
bash tests/test_install_hermes_relay.sh
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/install-hermes-relay.sh scripts/rollback-cloud-release.sh tests/test_cloud_release_rollback.sh tests/test_install_hermes_relay.sh
git commit -m "feat: preserve Relay state across cloud rollback"
```

---

### Task 8: Add bounded Relay diagnostics and deployment runbook

**Files:**
- Create: `scripts/hermes-relay-doctor.sh`
- Create: `tests/test_hermes_relay_doctor.sh`
- Create: `docs/deployment/hermes-relay.md`

**Step 1: Write RED doctor tests**

The doctor must distinguish these top-level results:

```text
healthy
degraded
stalled
incompatible
unauthorized
```

Fixture cases:

- Dashboard healthy + Relay healthy + tailnet bind + compatible version → healthy;
- Dashboard healthy, Relay down → degraded;
- Relay present but no progress/reconnect exhausted → stalled;
- Relay version/protocol unsupported → incompatible;
- pairing/session/grant failure → unauthorized;
- bind outside `100.64.0.0/10` → incompatible/fail;
- output contains no bearer token or API key.

**Step 2: Run RED**

```bash
bash tests/test_hermes_relay_doctor.sh
```

Expected: fail because doctor is absent.

**Step 3: Implement doctor**

Emit compact JSON by default containing:

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

Read only bounded metadata; never print raw tokens, headers, clipboard/screen bodies, or notification content.

**Step 4: Write the production runbook**

`docs/deployment/hermes-relay.md` must document:

- Dashboard `:9119` is primary;
- Relay `:8767` is extension-only and tailnet-only;
- API `:8642` remains optional;
- how to run doctor;
- how to mint a one-time pair QR from the Relay-enabled host;
- Android v1.13.2 APK digest verification;
- desktop CLI prerelease status;
- how to revoke a device;
- rollback behavior;
- no Full Access automation;
- no public security-group rule.

**Step 5: Run GREEN**

```bash
bash tests/test_hermes_relay_doctor.sh
```

Expected: PASS.

**Step 6: Commit**

```bash
git add scripts/hermes-relay-doctor.sh tests/test_hermes_relay_doctor.sh docs/deployment/hermes-relay.md
git commit -m "docs: add Hermes Relay production diagnostics"
```

---

### Task 9: Put Relay supply-chain/install tests into cloud CI and preserve routing

**Files:**
- Modify: `.github/workflows/cloud-foundation-validate.yml`
- Modify: `tests/test_governed_graph_runtime.sh` if Task 5 did not already include every Relay module
- No changes permitted to router files

**Step 1: Extend CI commands**

Add these local-safe tests to `cloud-foundation-validate.yml`:

```bash
python3 -m unittest tests.test_hermes_relay_provenance -v
python3 -m unittest tests.test_hermes_relay_policy tests.test_hermes_relay_adapter tests.test_hermes_relay_reconciler -v
bash tests/test_export_hermes_relay_dependency_lock.sh
bash tests/test_stage_hermes_relay_source.sh
bash tests/test_install_hermes_relay.sh
bash tests/test_hermes_relay_doctor.sh
```

The workflow build step may continue to use a non-production release unless CI explicitly constructs pinned fixture inputs. Do not add network-dependent production artifact downloads to ordinary regression tests.

**Step 2: Run the entire local verification matrix**

```bash
git diff --check
bash tests/test_governed_graph_runtime.sh
bash tests/test_dynamic_router.sh
python3 -m unittest tests.test_plugin_intake tests.test_provenance_envelope -v
bash tests/test_trajectory_fabric.sh
bash tests/test_memory_fabric.sh
bash tests/test_cloud_foundation.sh
bash tests/test_aws_production_preflight.sh || true
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

`test_aws_production_preflight.sh` may report auth unavailable on a development machine; all purely local tests must pass.

**Step 3: Prove routing is untouched**

```bash
sha256sum src/system/dynamic-router.sh config/cloud-model-catalog.json tests/test_dynamic_router.sh
```

Expected exactly:

```text
ad04816c63dd56d2f8469218e7d40a294ffa3697
 eb2503bef0c561b6aba839e5ca7d6d37263d5bdd
960a9bec716e55f290d14cd9aa3ab454a0c50aa2
```

Normalize the display formatting when recording evidence, but compare the actual three 64-character hashes byte-for-byte to the baseline values at the top of this plan.

**Step 4: Commit**

```bash
git add .github/workflows/cloud-foundation-validate.yml tests
git commit -m "test: gate Hermes Relay production integration"
```

---

### Task 10: Build a production release with exact Relay inputs

**Files:**
- No new source files expected; this is verification/evidence work
- Generated: `dist/hermes-max-cloud-*.tar.gz` and `.sha256` (not committed)

**Step 1: Obtain immutable build inputs outside the production installer**

Use a clean checkout of `Codename-11/hermes-relay` exactly at `08545ed32db07609c14730a7fc02cdd758f12434` / `server-v1.10.0`. Download the official server wheel once to the build machine and verify:

```bash
sha256sum hermes_relay-1.10.0-py3-none-any.whl
```

Expected:

```text
26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663
```

The checkout must be clean and `git tag --points-at HEAD` must contain `server-v1.10.0`.

**Step 2: Build production artifact**

```bash
HERMES_PRODUCTION_BUILD=1 \
HERMES_AGENT_SOURCE_DIR=/path/to/hermes-agent-v2026.8.19 \
HERMES_RELAY_SOURCE_DIR=/path/to/hermes-relay-server-v1.10.0 \
HERMES_RELAY_SERVER_WHEEL=/path/to/hermes_relay-1.10.0-py3-none-any.whl \
  bash scripts/build-cloud-release.sh
```

Expected output includes:

```text
HERMES_SOURCE_STAGE=PASS version=0.20.5
HERMES_RELAY_SOURCE_STAGE=PASS version=1.10.0
SECRET_SCAN=PASS
release=...tar.gz
sha256_file=...tar.gz.sha256
```

**Step 3: Verify the artifact independently**

```bash
sha256sum -c dist/hermes-max-cloud-*.tar.gz.sha256
TMP="$(mktemp -d)"
tar -xzf dist/hermes-max-cloud-*.tar.gz -C "$TMP"
cd "$TMP/hermes-max"
sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null
sha256sum vendor/hermes-relay/server-v1.10.0/hermes_relay-1.10.0-py3-none-any.whl
cat vendor/hermes-relay/server-v1.10.0/SOURCE_COMMIT
```

Expected wheel SHA and source commit match the pinned values above.

**Step 4: Re-run secret scan on extracted release**

```bash
bash scripts/secret-scan-production.sh "$TMP/hermes-max"
```

Expected: `SECRET_SCAN=PASS`.

---

### Task 11: Roll the Relay-enabled release to AWS through private Tailscale management

**Files:**
- No source changes unless a live defect is reproduced and first captured by a failing regression test

**Step 1: Capture the live pre-deploy baseline**

Over private Tailscale SSH to `ubuntu@hermes-max-primary`, record:

```bash
sudo readlink -f /opt/hermes-max/current
sudo systemctl is-active hermes-runtime.service
curl -fsS http://127.0.0.1:9119/api/health
sudo find /var/lib/hermes -maxdepth 3 -type f -printf '%P\n' | sort | sha256sum
sudo ss -ltnp
```

Also record whether `hermes-relay.service` already exists. Never print secrets or session-file contents.

**Step 2: Transfer the release only over the private management channel**

Copy the production tarball to `/tmp` on AWS using Tailscale SSH transport, then compare SHA256 locally and remotely before installation.

**Step 3: Run the existing atomic installer**

```bash
sudo bash /tmp/install-cloud-release-local.sh \
  /tmp/hermes-max-cloud-<stamp>.tar.gz \
  <exact-64-char-sha256>
```

Expected:

```text
HERMES_LOCAL_INSTALL=PASS release=<sha-prefix>
```

Any Relay scan/install/health failure must cause a nonzero exit and preserve the previous active release/runtime according to the installer trap.

**Step 4: Verify both production surfaces**

```bash
sudo systemctl is-active hermes-runtime.service
sudo systemctl is-active hermes-relay.service
curl -fsS http://127.0.0.1:9119/api/health
TSIP="$(tailscale ip -4 | head -1)"
curl -fsS "http://$TSIP:8767/health"
sudo /opt/hermes-max/current/scripts/hermes-relay-doctor.sh
```

Expected:

- Dashboard health `ok=true`, Hermes `0.20.5`;
- Relay health reports version `1.10.0`;
- doctor status `healthy` or `unauthorized` only if no device has yet been paired;
- `ss -ltn` shows Relay bound to the Tailscale IP, not `0.0.0.0:8767`;
- no new public EC2 security-group ingress is created.

**Step 5: Pair the Android reference client only if needed**

Use the official Hermes-Relay Android v1.13.2 sideload build whose SHA256 is already pinned. The only user-held step permitted here is scanning/accepting the one-time pairing QR if Android requires it.

Do not request or expose a raw session token in chat or logs.

**Step 6: Execute one harmless proof round trip**

Prefer a read-only operation such as `android_ping` or `desktop_health`. Record:

- stable target device ID;
- Relay request ID;
- policy class;
- authorization decision if consequential (read-only ping should not create one);
- matched response;
- result digest;
- Relay receipt path/hash;
- background reconciler terminal state.

Success requires correlated target-bound evidence, not merely a WSS notification.

**Step 7: Exercise rollback state preservation**

Use the existing rollback harness against a safe previous release or test-mode rehearsal. Verify Relay session/signing/plugin-data state fingerprints are unchanged. If rolling to a pre-Relay release, Relay service should deactivate while durable Relay state remains on disk.

---

### Task 12: Final verification, publish, and release evidence

**Files:**
- Update: `docs/deployment/evidence-template.md` only if a Relay section is needed
- No router changes

**Step 1: Run final clean-tree verification**

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

Expected: all local gates PASS and working tree clean after committing intended changes.

**Step 2: Re-prove protected router hashes**

Compare all three hashes to the exact baseline at the top of this plan. Any mismatch is a release blocker.

**Step 3: Verify GitHub branch before publish**

```bash
git log --oneline --decorate -12
git status --porcelain
```

Expected: only intentional Relay commits; no secrets, generated tarballs, `.env`, session files, APK, or bearer tokens committed.

**Step 4: Publish without touching `main`**

Push/update only:

```text
ai/hermes-relay-sdk-optimization
```

Create a release tag only after AWS and end-to-end verification pass. Do not fast-forward, merge, or force-update `main` as part of this tranche.

**Step 5: Record completion evidence**

Final evidence must include:

```text
Hermes-Ultra source commit
cloud release SHA256
Relay Android tag/commit/APK SHA256
Relay server tag/commit/wheel SHA256
AWS active release ID
Dashboard health/version
Relay health/version/bind address
router hash proof
secret-scan result
harmless round-trip request ID + receipt digest
rollback/state-preservation result
```

No raw credentials, tokens, device screen contents, clipboard contents, or notification bodies belong in the evidence bundle.

---

## Definition of Done

Do not claim this plan complete until: Android is pinned to 1.13.2; server/plugin 1.10.0 is staged from immutable verified inputs; Relay dependencies are hash-locked; the plugin passes Hermes-native security scanning; `:9119` remains primary and healthy; Relay `:8767` is tailnet-only; authority mapping is exhaustive/fail-closed; remote success is correlated and reconciled through existing Hermes task state; secrets are redacted; rollback preserves Relay durable state; the existing model router hashes are unchanged; all test/secret/release gates pass; and a harmless AWS round trip is proven or the sole remaining step is the user's one-time mobile pairing action.
