# Hermes Max v2.1 OAuth and Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make official subscription/OAuth authentication the preferred inference path, keep OmniRoute as the metered API fallback, and keep 9Router cold standby without browser-session credential reuse.

**Architecture:** Hermes native provider auth owns OAuth credentials and refresh. A small policy layer classifies providers and exposes redacted status only. OmniRoute handles approved API-only fallbacks; 9Router remains installed but is never selected automatically during normal operation.

**Tech Stack:** Hermes Agent v0.20.4 CLI, Bash/Python, JSON policy, OmniRoute, 9Router, existing Hermes model picker and JARVIS configuration.

**Spec:** `docs/superpowers/specs/2026-08-20-hermes-max-jarvis-ultimate-production-design.md`

## Global Constraints

- Browser cookies, Chrome databases, localStorage/sessionStorage, web bearer tokens, and CSRF tokens are forbidden as provider credentials.
- Provider classes are exactly `OFFICIAL_SUBSCRIPTION_OAUTH`, `OFFICIAL_PROVIDER_OAUTH`, `API_ONLY`, and `NATIVE_APP_ONLY`.
- OpenAI Codex OAuth is the preferred supported subscription-backed lane.
- xAI OAuth is enabled only when official auth succeeds and entitlement is verified.
- Claude Pro, Google AI Pro, and Perplexity Pro remain native-app lanes unless the pinned Hermes version exposes an official supported subscription route that passes tests.
- OmniRoute is the primary metered/API fallback.
- 9Router is cold standby only.
- An OAuth failure must not silently cause metered API spend unless the policy explicitly permits that fallback class.

---
### Task 1: Add a canonical provider-auth policy

**Files:**
- Create: `config/provider-auth-policy.json`
- Create: `tests/test_provider_auth_policy.py`
- Modify: `scripts/verify-cloud-foundation.sh`

**Interfaces:**
- Consumes: provider names used by Hermes/JARVIS/router configuration.
- Produces: one machine-readable auth classification and fallback policy.

- [ ] **Step 1: Write the failing policy test**

Create a Python test that loads `config/provider-auth-policy.json` and asserts the four allowed auth classes, `openai-codex` as `OFFICIAL_SUBSCRIPTION_OAUTH`, `omniroute` as `API_ONLY`, `9router` as `API_ONLY` with `cold_standby: true`, and `browser_session_credentials_allowed: false` globally.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 tests/test_provider_auth_policy.py`
Expected: FAIL because the policy file does not exist.

- [ ] **Step 3: Create the policy file**

Define entries for `openai-codex`, `xai-oauth`, `claude-pro`, `google-ai-pro`, `perplexity-pro`, `omniroute`, and `9router`. Add `fallback_to_metered_api` booleans so subscription OAuth failures do not silently spend unless explicitly enabled.

- [ ] **Step 4: Enforce policy presence**

Make `scripts/verify-cloud-foundation.sh` validate the JSON and reject the strings `next-auth.session-token`, `__Secure-1PSID`, `__client_session_token`, and `auth_token` anywhere under tracked `config/`, `scripts/`, `src/`, `infra/`, or `docs/deployment/` files.

- [ ] **Step 5: Verify and commit**

Run `python3 tests/test_provider_auth_policy.py` and `bash scripts/verify-cloud-foundation.sh`. Commit with `git add config/provider-auth-policy.json tests/test_provider_auth_policy.py scripts/verify-cloud-foundation.sh && git commit -m "feat: add canonical provider auth policy"`.
### Task 2: Add redacted Hermes OAuth management wrappers

**Files:**
- Create: `src/system/hermes-auth.sh`
- Create: `tests/test_hermes_auth.sh`

**Interfaces:**
- Consumes: pinned `hermes` CLI commands `auth add`, `auth list`, and provider IDs.
- Produces: safe `status`, `login-openai`, and `login-xai` commands that never print credential values.

- [ ] **Step 1: Write failing tests with a fake Hermes CLI**

Create a temporary `hermes` shim that records arguments. Assert `hermes-auth.sh login-openai` invokes `hermes auth add openai-codex`, `login-xai --no-browser` invokes the documented xAI OAuth provider without browser-cookie access, and `status` filters any token-shaped fields from output.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_hermes_auth.sh`
Expected: FAIL because `src/system/hermes-auth.sh` does not exist.

- [ ] **Step 3: Implement the wrapper**

Support exactly `status`, `login-openai`, `login-xai`, and `doctor`. `status` may report provider name, account label if Hermes exposes one, auth state, and expiry state, but must redact values matching `token`, `secret`, `cookie`, `authorization`, or `bearer` keys.

- [ ] **Step 4: Verify against the pinned local Hermes CLI**

Run `PAGER=cat hermes auth --help` and `PAGER=cat hermes auth add --help` to confirm the pinned CLI syntax, then run `bash tests/test_hermes_auth.sh`. Do not start an interactive provider login during automated tests.

- [ ] **Step 5: Commit**

Run: `git add src/system/hermes-auth.sh tests/test_hermes_auth.sh && git commit -m "feat: add safe Hermes OAuth management"`

### Task 3: Make OmniRoute the default API fallback and 9Router cold standby

**Files:**
- Modify: `config/jarvis-armory.config.local.example.json`
- Modify: `src/system/dynamic-router.sh`
- Modify: `src/system/gateway-watchdog.sh`
- Modify: `tests/test_jarvis_armory_integration.sh`
- Modify: `tests/test_gateway_watchdog.sh`
- Modify: `tests/test_dynamic_router.sh`

**Interfaces:**
- Consumes: OmniRoute at `127.0.0.1:20128/v1` and 9Router at `127.0.0.1:20127/v1`.
- Produces: API fallback order `omniroute -> 9router`, with no automatic 9Router preference.
- [ ] **Step 1: Change tests first**

Update the JARVIS test to expect `default_provider == "omniroute"`, keep the 9Router provider entry present, and assert it is marked `cold_standby`. Update watchdog/dynamic-router tests so OmniRoute is the required normal gateway and 9Router is optional unless explicitly requested.

- [ ] **Step 2: Run focused tests and confirm failure**

Run `bash tests/test_jarvis_armory_integration.sh`, `bash tests/test_gateway_watchdog.sh`, and `bash tests/test_dynamic_router.sh`.
Expected: at least the JARVIS default-provider assertion fails against the current 9Router-first configuration.

- [ ] **Step 3: Implement routing-order changes**

Set JARVIS `default_provider` to `omniroute`. Keep named `ninerouter` and `ninerouter_coding` entries for explicit standby activation only. Update dynamic-router metadata to call OmniRoute the normal API fallback and 9Router cold standby. Make the default watchdog requirement OmniRoute-only; permit `--required omniroute,9router` for standby drills.

- [ ] **Step 4: Run focused tests**

Run the three tests from Step 2 and require all to pass.

- [ ] **Step 5: Commit**

Run: `git add config/jarvis-armory.config.local.example.json src/system/dynamic-router.sh src/system/gateway-watchdog.sh tests && git commit -m "feat: make OmniRoute primary API fallback"`

### Task 4: Make API fallback explicit in the Hermes runner

**Files:**
- Modify: `src/system/hermes-run.sh`
- Create: `tests/test_hermes_api_fallback_policy.sh`
- Modify: `docs/cloud-model-picker.md`

**Interfaces:**
- Consumes: provider-auth policy plus existing model selection file.
- Produces: an API-only runner that refuses to masquerade as subscription OAuth and records when a metered fallback is used.

- [ ] **Step 1: Write failing dry-run tests**

Assert that `hermes-run.sh --dry-run` marks OmniRoute/9Router routes as `auth_class=API_ONLY`, that direct `openai-codex` is not accepted by this OpenAI-compatible API runner, and that a metered route requires `HERMES_ALLOW_METERED_FALLBACK=true` when reached after an OAuth-class failure.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_hermes_api_fallback_policy.sh`
Expected: FAIL because the runner does not yet enforce auth classes.

- [ ] **Step 3: Implement policy checks**

Load `config/provider-auth-policy.json` with Python, add `auth_class` and `metered_fallback` to dry-run metadata, and fail with a clear message instead of attempting a paid API when fallback permission is false.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_hermes_api_fallback_policy.sh`, `bash tests/test_cloud_model_picker.sh`, and `bash tests/test_dynamic_router.sh`. Commit with `git add src/system/hermes-run.sh tests docs/cloud-model-picker.md && git commit -m "feat: enforce explicit metered fallback policy"`.
### Task 5: Use Hermes-native OAuth proxy surfaces where officially supported

**Files:**
- Create: `src/system/hermes-oauth-proxy.sh`
- Create: `tests/test_hermes_oauth_proxy.sh`
- Modify: `config/provider-auth-policy.json`

**Interfaces:**
- Consumes: Hermes v0.20.4 `hermes proxy` support for official OAuth upstreams (`nous`, `xai`).
- Produces: optional loopback-only OpenAI-compatible OAuth proxy endpoints without browser-cookie extraction.

- [ ] **Step 1: Write failing tests with a fake Hermes CLI**

Assert the wrapper first checks `hermes proxy providers`, accepts only providers returned there, binds `127.0.0.1`, rejects `0.0.0.0`, and never accepts token/cookie arguments.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_hermes_oauth_proxy.sh`
Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement official proxy wrapper**

Support `providers`, `status`, and `start PROVIDER PORT`. Require provider membership in live `hermes proxy providers`; invoke `hermes proxy start --provider PROVIDER --host 127.0.0.1 --port PORT`. Mark `nous` and `xai` as `OFFICIAL_PROVIDER_OAUTH` proxy-capable in policy; do not mark OpenAI Codex proxy-capable because the pinned CLI does not expose it through `hermes proxy`.

- [ ] **Step 4: Verify and commit**

Run `PAGER=cat hermes proxy --help`, `PAGER=cat hermes proxy providers`, and `bash tests/test_hermes_oauth_proxy.sh`. Commit with `git add src/system/hermes-oauth-proxy.sh tests/test_hermes_oauth_proxy.sh config/provider-auth-policy.json && git commit -m "feat: add official Hermes OAuth proxy wrapper"`.
### Task 6: Drive fallback through Hermes-native fallback configuration

**Files:**
- Create: `src/system/hermes-fallback-policy.sh`
- Create: `tests/test_hermes_fallback_policy.sh`
- Modify: `docs/cloud-model-picker.md`

**Interfaces:**
- Consumes: Hermes v0.20.4 `fallback_providers` config and local OpenAI-compatible router endpoints.
- Produces: normal fallback chain containing OmniRoute only; explicit standby activation can append 9Router.

- [ ] **Step 1: Write failing isolated-HERMES_HOME tests**

Use a temporary `HERMES_HOME`. Assert `configure` writes one fallback entry with provider `openai`, model `auto`, base URL `http://127.0.0.1:20128/v1`, and `key_env=OMNIROUTE_API_KEY`. Assert `activate-standby` appends `http://127.0.0.1:20127/v1` with `NINEROUTER_API_KEY`, while `deactivate-standby` removes only that entry.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_hermes_fallback_policy.sh`
Expected: FAIL because the policy wrapper does not exist.

- [ ] **Step 3: Implement with supported Hermes config commands**

Use `hermes config set fallback_providers '<json>'` and validate by reading `hermes config get fallback_providers --json`. Never write API key values, only `key_env` names. `configure` must leave 9Router out of the normal chain; standby activation is an explicit command.

- [ ] **Step 4: Verify against the pinned CLI and commit**

Run `bash tests/test_hermes_fallback_policy.sh`, then in a temporary `HERMES_HOME` run `hermes config check`. Commit with `git add src/system/hermes-fallback-policy.sh tests/test_hermes_fallback_policy.sh docs/cloud-model-picker.md && git commit -m "feat: use Hermes native fallback policy"`.
