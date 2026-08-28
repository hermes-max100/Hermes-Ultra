# Hermes Relay SDK Optimization — Design

**Date:** 2026-08-28  
**Status:** Approved design target; implementation not started  
**Hermes-Ultra branch:** `ai/hermes-relay-sdk-optimization`  
**Canonical repository:** `hermes-max100/Hermes-Ultra`

## 1. Purpose

Integrate and optimize the official `Codename-11/hermes-relay` SDK/runtime surfaces for Hermes-Ultra without creating a second agent brain, without replacing the existing Hermes model router, and without maintaining an unnecessary independent companion implementation.

The resulting system uses AWS-hosted Hermes as the single authoritative brain. Android and desktop machines are governed clients/tool surfaces. The standard Hermes Dashboard/Gateway remains the primary mobile path; Hermes-Relay adds the capabilities upstream Hermes does not yet own directly: Relay pairing, terminal/TUI, notifications, media, enhanced voice, Relay sessions, desktop tools, and sideload-only Device Control.

## 2. Upstream Authority and Pins

The implementation must preserve upstream provenance and make each independently released Relay surface explicit rather than treating the Android version as the version of every component.

Initial pinned inputs:

- Android: `android-v1.13.2`, upstream commit `a5cc0104bfbda8542667ab50eb70ab02b02a47e5`.
- Android sideload APK SHA-256: `ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d`.
- Relay server/plugin: `server-v1.10.0`; published wheel SHA-256 `26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663`.
- Desktop CLI: do not infer a production pin from the Android tag. The currently documented binary release is prerelease `desktop-v0.3.0-alpha.18`; implementation must verify the newest compatible desktop release or build from the pinned upstream source commit and record its provenance before installation.

Hermes-Ultra will add a machine-readable Relay provenance manifest containing component tag, commit, artifact digest, source URL, license, verification date, and compatibility status. The existing `config/production-versions.json` Android pin will move from `1.12.0` to `1.13.2` only together with this provenance record and regression tests.

## 3. Architecture

### 3.1 Authoritative brain and routes

AWS `hermes-max-primary` remains the only authoritative Hermes runtime. No Relay client, desktop daemon, Android service, or Chromebook process becomes a second reasoning/memory authority.

Primary paths:

1. Android Chat / Manage / sessions / standard voice → Hermes Dashboard/Gateway on port `9119` through the private Tailscale route.
2. Relay extensions → official Hermes-Relay server/plugin, default protocol port `8767`, available only through the private tailnet.
3. Hermes API server on `8642` → optional compatibility/fallback only; it is not required for the standard Android path and is not exposed publicly.
4. Desktop CLI/daemon → official Relay WSS/WS protocol and per-host grants; it is a remote tool surface, not a local Hermes installation.

No public security-group ingress is added. Initial Relay production binding is the AWS Tailscale address only. Plain Relay transport is permitted only when the socket is reachable exclusively through Tailscale; public or non-tailnet exposure requires TLS/Secure Link before activation.

### 3.2 Upstream-first integration, not a permanent fork

Hermes-Ultra will not copy and independently evolve the whole Hermes-Relay repository by default. It will maintain a governed integration layer around a pinned upstream source/artifact set.

The integration layer will contain:

- upstream provenance/pin manifest;
- deterministic staging/install scripts;
- Hermes-Ultra policy mapping for Relay grants and consequential actions;
- health/capability inspection;
- execution evidence adapters;
- compatibility tests against the pinned Relay protocol;
- AWS service wiring and rollback support.

If implementation discovers a real upstream defect that must be patched, Hermes-Ultra may carry the smallest possible patch file against the exact pinned upstream commit. Every patch must have a regression test and a documented upstream issue/PR candidate. Large source divergence is out of scope.

## 4. Protocol and Capability Model

Relay's existing protocol remains authoritative. Hermes-Ultra consumes it rather than inventing a parallel protocol.

The adapter must understand and validate:

- `system/auth` and `auth.ok` session establishment;
- client `supports` capability negotiation including `typed_stream_events` and `event_schema_version`;
- server version and per-channel grant expiries;
- `bridge.status.capabilities` schema, including permanent, timed, and unlimited capabilities;
- request/response correlation using Relay envelope IDs and `request_id`;
- typed chat stream envelopes using `session_id`, `run_id`, `seq`, and event family when Relay chat proxying is used;
- session-token expiry/revocation and reconnect behavior;
- health data from Relay `/health` and Hermes Dashboard health independently.

Unknown protocol schema versions, unknown high-authority capabilities, malformed grant expiries, or target-device ambiguity fail closed.

## 5. Governance and Authority

Relay must not become a second authority path around Hermes-Ultra governance.

Hermes-Ultra will map remote capabilities into the existing consequential-action gate before dispatching actions that can materially affect a device, filesystem, process, communication, credentials, money, or external system. The Relay server's own grants and the Android/desktop on-device controls remain additional independent gates, not substitutes for Hermes governance.

New desktop hosts default to Relay's `Ask Every Time`/restricted posture rather than Full Access. Full Access is never granted automatically. Android Device Control remains sideload-only and retains upstream phone-side blocklists, destructive-action confirmation, idle auto-disable, and activity logging.

For every consequential remote dispatch, the evidence record binds at minimum:

- Hermes task/execution identifier;
- Relay session/token prefix or stable session identity without storing the raw bearer;
- stable target device ID;
- Relay channel and operation;
- Relay envelope/request ID;
- requested capability class;
- authorization decision/grant reference;
- start/end timestamps;
- terminal status and bounded result digest;
- verification source.

Sensitive request bodies, raw session tokens, API keys, clipboard contents, screen contents, notification bodies, and credential-bearing headers are not written to the general evidence ledger.

## 6. Reliability and Reconciliation

Relay notifications are advisory evidence, not sole proof of completion.

The integration will use bounded reconnect with exponential backoff and jitter, session reauthentication, and explicit terminal-state reconciliation. Remote requests must be idempotent where the upstream operation supports an ID; repeated delivery must not silently create duplicate execution.

For operations with Relay `request_id`, completion requires a matching response for the same target device and request. For long-running or stateful operations, Hermes-Ultra records the provider/Relay handle and independently rechecks the relevant status or health surface before marking success when feasible.

Typed stream events are de-duplicated by `(session_id, run_id, seq)` when present. Out-of-order, duplicate, or missing event sequences may update diagnostics but cannot manufacture success. Disconnects leave work in a reconcilable non-terminal state until a bounded retry policy resolves it or classifies it as stalled/failed.

Concurrency is bounded per target device and per capability family. The design does not allow an unbounded number of desktop shell jobs, phone bridge commands, or reconnect loops.

## 7. AWS Deployment

The Relay server/plugin will be installed through a deterministic, provenance-checked release path that participates in the same `/opt/hermes-max/releases/<digest>` and rollback model already used by Hermes-Ultra.

Preferred deployment path:

1. Stage the exact verified upstream Relay plugin source/artifact into the Hermes-Ultra production release.
2. Install/enable it using the current Hermes plugin contract from local staged content where supported.
3. Create a dedicated `hermes-relay.service` owned by the Hermes runtime identity or an equivalent supervised process tied to the release.
4. Bind Relay only to the Tailscale address on port `8767`; no public EC2 security-group rule.
5. Keep Hermes Dashboard/Gateway on `9119` as the primary Android route.
6. Preserve existing Hermes state, Relay session state, QR signing identity, and user-owned runtime secrets outside immutable release directories.
7. On failed install or failed post-start health, do not advance the active release; restore the previous service/runtime configuration.

The implementation must verify whether the pinned Hermes plugin manager accepts a local plugin path. If not, the fallback must still be deterministic and pinned (verified wheel/source plus explicit plugin metadata wiring); arbitrary live `pip install` or unpinned GitHub install is not an acceptable production fallback.

## 8. Android and Desktop Client Policy

Android v1.13.2 is the reference mobile client. Hermes-Ultra does not rebuild the APK unless an actual client-side defect is demonstrated by tests. The supplied sideload APK digest is recorded so installation can be verified independently.

The expected Android connection profile is:

- Dashboard route: private AWS/Tailscale `:9119`.
- Relay route: private AWS/Tailscale `:8767` after the Relay plugin is enabled and paired.
- API fallback: optional, disabled unless needed.
- Route roaming: use upstream Relay behavior; Hermes-Ultra does not add a competing route manager.

Desktop uses the official Hermes-Relay CLI/daemon. A desktop target is always selected by stable device identity when more than one daemon is connected. Tool execution inherits Relay's per-host access presets and capability ledger. Raw terminal, PowerShell, detached processes, and command jobs stay unavailable under Standard access exactly as upstream defines them.

## 9. Observability and Health

Add one Hermes-Ultra Relay diagnostics command/report that summarizes without revealing secrets:

- Hermes Dashboard health/version;
- Relay `/health`, version, client/session counts;
- Relay bind address/port and whether it is tailnet-only;
- Android/desktop capability negotiation status when connected;
- expired/near-expiry grants;
- reconnect/backoff state;
- last verified remote action receipt;
- protocol/version compatibility result.

Health reporting must distinguish `healthy`, `degraded`, `stalled`, `incompatible`, and `unauthorized`; a generic green status is insufficient.

## 10. Testing Strategy

Implementation is test-first. The acceptance suite must cover the integration at four levels.

**Static/provenance:** component pins, artifact digests, MIT license/provenance, secret scanning, no public port rule, no browser-cookie/session harvesting, and unchanged existing model-routing files.

**Protocol/unit:** auth/capability parsing, unknown-version fail-closed behavior, target-device binding, grant expiry, request correlation, event de-duplication, reconnect/backoff bounds, redaction, and evidence receipt validation.

**Integration:** a fake Relay server exercises pair/auth, reconnect, duplicate event delivery, mismatched request IDs, revoked sessions, ambiguous devices, bridge capability changes, and service restart recovery. Existing Hermes execution-state/reconciliation tests remain green.

**Live AWS:** Relay service active, `/health` healthy through the private route, Dashboard `9119` still healthy, no new public ingress, pairing/reconnect succeeds with an authorized client, a harmless remote operation completes with a verified receipt, and rollback to the previous Hermes release is rehearsed or proven by the existing rollback harness without losing Relay/session state.

Android build/repackaging is not an acceptance requirement unless Hermes-Ultra actually changes Android source. If no client patch is needed, use the official v1.13.2 APK unchanged.

## 11. Files Expected in Hermes-Ultra

Implementation should prefer the repository's existing naming/layout, but the expected logical artifacts are:

- `config/production-versions.json` — corrected Android 1.13.2 pin.
- `config/hermes-relay-upstream.json` — independent Android/server/desktop provenance.
- `config/hermes-relay-policy.json` — capability and authority mapping.
- `src/system/hermes-relay-adapter.py` — protocol/capability/evidence integration.
- `scripts/stage-hermes-relay.sh` — deterministic upstream staging and digest verification.
- `scripts/install-hermes-relay.sh` — release-bound plugin/service install.
- `scripts/hermes-relay-doctor.sh` — bounded diagnostics/health.
- `tests/test_hermes_relay_*.py` and/or shell integration tests.
- `docs/deployment/hermes-relay.md` — production and pairing runbook.

Exact filenames may be adjusted during the implementation plan to match existing repository patterns, but no new agent, router, memory system, or duplicate protocol is introduced.

## 12. Non-Goals

This tranche does not replace Hermes Dashboard chat with Relay chat, expose Relay publicly, create a new mobile app, create a second desktop chat client, auto-grant Full Access, redesign the existing model router, move Hermes memory to clients, enable experimental Hermes Reach, or add paid infrastructure.

Secure Link/Reach may be evaluated later, but direct Tailscale is the production baseline for this tranche because it already provides private reachability without another broker or public endpoint.

## 13. Acceptance Criteria

Implementation is complete only when all of the following are true:

1. Hermes-Ultra records verified independent Relay component pins and upgrades Android from 1.12.0 to 1.13.2.
2. The Relay plugin is deterministically staged and installed on AWS without public ingress or unpinned production downloads.
3. Dashboard `9119` remains the primary Android path and remains healthy.
4. Relay `8767` is reachable only through the approved private tailnet path.
5. Capability negotiation and grant expiry are enforced fail-closed.
6. Consequential Relay/desktop/bridge actions pass through Hermes-Ultra authority policy in addition to upstream Relay/device gates.
7. Remote action success requires correlated, target-bound evidence; duplicate/out-of-order notifications cannot fabricate success.
8. Reconnect, session revocation, stale work, ambiguous device selection, and service restart behavior are covered by tests.
9. Existing Hermes model-routing files remain byte-for-byte unchanged unless the user separately requests routing changes.
10. Secret scans, integration tests, cloud release tests, and live AWS health checks pass.
11. A harmless Android or desktop round trip is demonstrated against AWS, or the only remaining blocker is a clearly identified user-held pairing action.
12. The final Hermes-Ultra release is reproducible, provenance-bearing, rollback-capable, and contains no raw Relay bearer tokens or user credentials.
