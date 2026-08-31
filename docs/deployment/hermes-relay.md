# Hermes Relay Production Deployment

Hermes Relay is an optional private extension to the Hermes-Ultra AWS runtime. The Hermes Dashboard/Gateway on `127.0.0.1:9119` remains the primary Hermes service. Relay adds device and desktop capabilities on TCP 8767 and must bind only to the host's Tailscale IPv4 address.

## Production pins

- Hermes Agent: `v2026.8.19` / `0.20.5`
- Relay server/plugin: `server-v1.10.0`
- Android client: `android-v1.13.2`
- Desktop CLI: `desktop-v0.4.0-beta.5` (prerelease)
- Android sideload APK SHA256: `ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d`
- Desktop Linux x64 SHA256: `2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110`

All production Relay source, artifacts, and dependency locks are staged into the cloud release before deployment. AWS activation must not fetch unpinned code.

## Network contract

- `:9119` — Hermes Dashboard/Gateway, loopback on the AWS host and exposed only through the existing private Tailscale path.
- `:8767` — Hermes Relay extension, bound directly to the host Tailscale IPv4 in `100.64.0.0/10`.
- `:8642` — optional Hermes API fallback; it is not the primary Relay path.
- Do not add a public EC2 security-group rule for 8767, 9119, or 8642.
- Hermes Reach and Secure Link are not required for this deployment.
## Installation and activation

`build-cloud-release.sh` stages the exact Relay source tree, wheel, `uv.lock`, exported hash-locked runtime requirements, source provenance, and manifests. `install-cloud-release-local.sh` then performs two Relay phases:

1. `prepare` verifies all Relay evidence, requires a Tailscale bind, installs only hash-locked dependencies into the new runtime, and requires a `safe` Hermes plugin-security verdict. It makes no live plugin/service/config mutation.
2. `activate` runs only after the new runtime and `/opt/hermes-max/current` are stable. It links the verified plugin, enables and diagnoses it with Hermes-native commands, writes the hardened systemd unit, starts Relay, and requires Relay health before the release installer can report success.

A Relay activation failure remains inside the existing cloud installer rollback boundary.

## Access and grants

Relay authority is explicit and fail closed. Unknown future `android_*` or `desktop_*` operations are denied until classified. Desktop hosts default to **Ask Every Time** after configuration; unconfigured hosts remain **Restricted**. Full Access is never selected automatically.

Mutating device, filesystem, process-control, and external-communication operations are mapped into Hermes' existing consequential-action gate. Observational operations are still target-device bound and evidence tracked.

Do not store or request raw Relay session tokens for routine operations. Pairing and session credentials remain in Hermes' durable private state.

## Android pairing

Use the official sideload APK only after verifying its SHA256 against the production pin. Standard Hermes chat/sessions can work without the Relay plugin; Relay pairing is needed for the enhanced device-control surfaces.
The sole user-held step should be scanning or accepting the one-time pairing request when a new mobile device must be paired.

## Diagnostics

Run:

```bash
sudo /opt/hermes-max/current/scripts/hermes-relay-doctor.sh
```

The doctor emits compact JSON and classifies the installation as `healthy`, `degraded`, `stalled`, `incompatible`, or `unauthorized`. It checks Dashboard health, Relay health/version, protocol schema, Tailscale-only binding, and grant state. It never prints raw bearer tokens, Authorization headers, clipboard/screen bodies, or notification bodies.

## Completion evidence

Relay notifications are advisory. Remote work reaches Hermes success only after target-device and request correlation, durable receipt verification, result-digest verification, and the existing background-task reconciler admit the evidence. A notification by itself cannot complete a Hermes task.

## Revocation and rollback

Revoke device access using Relay's authenticated management surface rather than deleting state files manually. Cloud rollback reconciles Relay code/service to the target release. Rolling back to a pre-Relay release may stop and disable the Relay service and remove the plugin code link, but it must preserve durable sessions, QR/signing identity, plugin data, and other Hermes state.

After rollback, run both Dashboard health and the Relay doctor. If Relay is intentionally absent in the target release, verify it is inactive while durable Relay state remains present.
