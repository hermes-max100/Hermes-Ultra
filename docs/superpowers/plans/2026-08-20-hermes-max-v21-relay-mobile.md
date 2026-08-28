# Hermes Max v2.1 Relay and Mobile Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes Relay Android v1.11.0 the primary Samsung client, connect it privately to AWS Hermes on `:9119`, and enforce capability-scoped phone control with JARVIS approval gates.

**Architecture:** AWS runs one loopback-bound Hermes backend using `hermes serve --host 127.0.0.1 --port 9119`; Tailscale Serve publishes it only inside the tailnet. Relay v1.11.0 owns the primary Bridge capability UI. Existing Accessibility/Usage/Notification/Termux/Shizuku helpers remain optional extensions and obey one canonical mobile-control policy.

**Tech Stack:** Hermes Agent v0.20.4, Hermes Relay Android v1.11.0, Tailscale Serve, Bash, Android intents, Termux:API, Shizuku.

**Spec:** `docs/superpowers/specs/2026-08-20-hermes-max-jarvis-ultimate-production-design.md`

## Global Constraints

- Relay Android version is pinned to `1.11.0` / `android-v1.11.0`.
- Dashboard/Gateway `:9119` is primary; `:8642` is optional compatibility fallback only.
- Hermes binds `127.0.0.1`; Tailscale Serve is the private remote-access layer.
- Tailscale Funnel is disabled.
- Phone capability scopes are `screen_read`, `screen_control`, `foreground_state`, `notification_read`, `screenshot`, `package_launch`, `clipboard_draft`, and `shell_action`.
- Sends, posts, deletes, purchases, credentials/OTP, privilege changes, security changes, session termination, and destructive shell actions require explicit approval.
- The phone is a client/control surface, not a second Hermes brain.

---
### Task 1: Add a canonical mobile capability policy

**Files:**
- Create: `config/mobile-control-policy.json`
- Create: `tests/test_mobile_control_policy.py`
- Modify: `config/hermes-jarvis-policy.json`

**Interfaces:**
- Consumes: existing JARVIS approval boundaries and Relay Bridge concepts.
- Produces: one policy document mapping each phone capability to default grant mode and approval requirements.

- [ ] **Step 1: Write the failing policy test**

Create a Python test that asserts the eight allowed capability names, Relay as the primary policy surface, `screen_control` defaulting to bounded/read-and-confirm behavior, and all sensitive mutations mapped to `explicit_approval`.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_mobile_control_policy.py`
Expected: FAIL because the policy file does not exist.

- [ ] **Step 3: Implement policy and JARVIS linkage**

Create `config/mobile-control-policy.json` with per-capability keys `default`, `audit`, and `requires_approval_for`. Add `mobile_control_policy: "config/mobile-control-policy.json"` to the JARVIS policy and preserve existing hard blocks.

- [ ] **Step 4: Verify and commit**

Run `python3 tests/test_mobile_control_policy.py` and `python3 -m json.tool config/hermes-jarvis-policy.json`. Commit with `git add config tests/test_mobile_control_policy.py && git commit -m "feat: add scoped mobile control policy"`.

### Task 2: Add the AWS Hermes Relay server wrapper

**Files:**
- Create: `src/system/hermes-relay-server.sh`
- Create: `tests/test_hermes_relay_server.sh`

**Interfaces:**
- Consumes: pinned `hermes` CLI and local port `9119`.
- Produces: `status`, `start`, `stop`, and `doctor` operations for the loopback Hermes backend.
- [ ] **Step 1: Write failing wrapper tests**

Use a fake `hermes` executable in `PATH` and assert `start` invokes `hermes serve --host 127.0.0.1 --port 9119`, `stop` invokes `hermes serve --stop`, and `doctor` refuses a non-loopback configured host.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_hermes_relay_server.sh`
Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement the wrapper**

Support `status`, `start`, `stop`, and `doctor`. `start` uses `--no-open` semantics where applicable and never binds `0.0.0.0`. `doctor` checks `hermes --version`, `hermes serve --status`, local TCP reachability of `9119`, and the pinned production version file.

- [ ] **Step 4: Verify against the local pinned Hermes**

Run `PAGER=cat hermes serve --help`, then `bash tests/test_hermes_relay_server.sh`. Do not start a second production Hermes process on the Chromebook during automated tests.

- [ ] **Step 5: Commit**

Run: `git add src/system/hermes-relay-server.sh tests/test_hermes_relay_server.sh && git commit -m "feat: add private Hermes Relay server wrapper"`

### Task 3: Reconcile legacy Android helpers with Relay v1.11.0

**Files:**
- Modify: `src/system/android-hermes-agent-setup.sh`
- Modify: `src/system/mobile-app-control.sh`
- Create: `tests/test_mobile_app_control.sh`
- Modify: `docs/hermes-android-max-control-playbook.md`

**Interfaces:**
- Consumes: `config/mobile-control-policy.json` and optional Termux/Shizuku commands.
- Produces: legacy helper behavior that augments Relay instead of pretending to be the primary mobile runtime.

- [ ] **Step 1: Write failing mobile-helper tests**

Test with command shims for `am`, `bsh`, `shizuku`, and Termux API tools. Assert status names Relay as primary, draft actions do not send, `tap/text/key/screenshot` require the corresponding capability to be allowed, and no command exists for send/post/delete/purchase/OTP/security mutation.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_mobile_app_control.sh`
Expected: FAIL because the existing helper does not load the canonical capability policy.

- [ ] **Step 3: Implement capability checks**

Load the JSON policy through a small Python query helper inside `mobile-app-control.sh`. Gate `tap`, `text`, `key`, `screenshot`, and app launch by the correct capability; preserve draft-only messaging behavior. Update the Android setup document generated by `android-hermes-agent-setup.sh` to identify Hermes Relay v1.11.0 as primary and the legacy fork/Termux bridge as optional extension only.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_mobile_app_control.sh`, `bash -n src/system/mobile-app-control.sh`, and `bash -n src/system/android-hermes-agent-setup.sh`. Commit with `git add src/system tests/test_mobile_app_control.sh docs/hermes-android-max-control-playbook.md && git commit -m "feat: align mobile helpers with Hermes Relay"`.
### Task 4: Install hardened Hermes backend systemd service

**Files:**
- Create: `infra/aws-primary/templates/hermes-backend.service.tftpl`
- Modify: `infra/aws-primary/templates/bootstrap-hermes.sh.tftpl`
- Modify: `tests/test_cloud_foundation.sh`

**Interfaces:**
- Consumes: `/opt/hermes-max/current/src/system/hermes-relay-server.sh`.
- Produces: a boot-persistent loopback Hermes backend managed by systemd.

- [ ] **Step 1: Add failing service assertions**

Assert the unit uses `User=hermes`, `WorkingDirectory=/opt/hermes-max/current`, `ExecStart=/opt/hermes-max/current/src/system/hermes-relay-server.sh start`, `Restart=on-failure`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, and no `0.0.0.0` bind.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_cloud_foundation.sh`
Expected: FAIL because the backend unit template does not exist.

- [ ] **Step 3: Add and install the unit**

Render the unit during bootstrap, set writable paths only for `/var/lib/hermes` and `/opt/hermes-max`, run `systemctl daemon-reload`, and enable the service after the release manifest and foundation verification pass.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_cloud_foundation.sh` and `bash scripts/verify-cloud-foundation.sh`. Commit with `git add infra/aws-primary tests/test_cloud_foundation.sh && git commit -m "feat: run Hermes backend as hardened service"`.

### Task 5: Add Relay/Tailscale round-trip acceptance

**Files:**
- Create: `scripts/verify-relay-path.sh`
- Create: `tests/test_verify_relay_path.sh`
- Modify: `docs/deployment/aws.md`

**Interfaces:**
- Consumes: local Hermes health, `tailscale status --json`, and optional private Relay URL.
- Produces: redacted gates `HERMES_GATEWAY_9119`, `TAILSCALE_SERVE_PRIVATE`, and `RELAY_ANDROID_TO_AWS`.

- [ ] **Step 1: Write fixture-based tests**

Test local-only mode, private-Tailscale mode, and failure when a supplied endpoint resolves to a public/non-tailnet route. Never require a real phone in unit tests.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_verify_relay_path.sh`
Expected: FAIL because the verifier does not exist.

- [ ] **Step 3: Implement verifier**

Check `127.0.0.1:9119`, confirm Tailscale node/login state and Serve configuration, and optionally probe the private HTTPS/WSS endpoint. A real Android round-trip remains an explicit deployment acceptance action and is reported `N/A` until performed, never `PASS` by inference.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_verify_relay_path.sh` and `git diff --check`. Commit with `git add scripts/verify-relay-path.sh tests/test_verify_relay_path.sh docs/deployment/aws.md && git commit -m "feat: add Relay path acceptance checks"`.
