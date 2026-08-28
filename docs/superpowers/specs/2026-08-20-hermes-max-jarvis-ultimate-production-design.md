# Hermes Max / JARVIS Ultimate Production Build v2.1

Status: **APPROVED DESIGN — canonical target**
Date: 2026-08-20
Repository: `hermes-max-live`

## 1. Purpose

This document freezes the production architecture for Hermes Max, JARVIS ADVANCED, Hermes Relay, AWS hosting, mobile control, model authentication, and the Chromebook engineering workstation.

The design has one authoritative Hermes backend. JARVIS is the governed orchestration/tool layer over that backend. Hermes Relay is the remote client/control transport. The Samsung phone is the daily user and device-control surface. Chromebook Linux is the engineering and recovery workstation.

## 2. Non-Negotiable Design Rules

1. One authoritative Hermes Max backend; no duplicate production brains.
2. AWS is the primary production runtime.
3. Samsung connects to AWS through Hermes Relay over Tailscale.
4. Chromebook Linux is development/recovery, not a second active production runtime.
5. Official subscription/OAuth authentication is preferred where supported.
6. Browser-session cookie harvesting or replay is forbidden.
7. OmniRoute is the primary metered/API routing layer.
8. 9Router is cold standby, not the normal request path.
9. Mutating phone/tool actions remain approval-gated.
10. Releases are immutable, checksummed, provenance-recorded, and rollback-capable.

## 3. Upstream Production Baseline

Pin production to tested upstream releases rather than tracking moving branches.

- Hermes Agent: **v0.20.4 (`v2026.8.18`)** at this design freeze.
- Hermes Relay Android: **v1.11.0 (`android-v1.11.0`)** at this design freeze.
- Upgrade policy: validate the next release in a canary/staging path, run the full acceptance suite, then promote by immutable artifact. Never auto-upgrade production in place.

Hermes v0.20.4 is the stable downstream-consumer release current at freeze time and includes the recent MCP/Bot Mode/security work needed by this architecture. Relay v1.11.0 adds explicit Bridge capability presets, bounded screen-control grants, stronger session-recovery behavior, and lower idle-power behavior. Those upstream controls should be used before inventing duplicate local control mechanisms.

Upstream references:
- `https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.18`
- `https://github.com/Codename-11/hermes-relay/releases/tag/android-v1.11.0`
- `https://hermes-relay.dev/docs/guide/remote-access`

## 4. Production Topology

```text
Samsung Android
  -> Hermes Relay Android
  -> Tailscale tailnet
  -> Tailscale Serve WSS/HTTPS
  -> AWS Hermes Dashboard/Gateway :9119 (loopback origin)
  -> JARVIS governance/tool layer
  -> Hermes Max authoritative core
```

Port `8642` is optional fallback/headless compatibility only. Neither `9119` nor `8642` is exposed directly to the public Internet.

## 5. AWS Runtime

Primary region: `us-east-1`.

Preferred host profile:
- EC2 instance type: `m7i-flex.large`.
- 2 vCPU, 8 GiB RAM, x86_64.
- Canonical Ubuntu Server 24.04 LTS (Noble) amd64 AMI.
- 30 GiB encrypted gp3 root volume.
- gp3 baseline: 3,000 IOPS and 125 MiB/s throughput.
- IMDSv2 required.
- AWS Systems Manager Session Manager for infrastructure administration.
- No SSH ingress and no key-pair dependency for normal administration.
- No NAT Gateway, RDS/Aurora, EKS/Kubernetes, GPU, ALB/NLB, Reserved Instances, Savings Plans, Marketplace commitments, or support-plan commitments.

The instance may have one ordinary public IPv4 for outbound Internet reachability, but the security group exposes no raw Hermes/JARVIS application port. A permanent Elastic IP is not required for identity because Tailscale provides stable tailnet addressing.

Before apply, automation must query the live AWS account/region and verify that the selected instance type is launchable and that current pricing/credits fit the cost policy. It must never silently substitute a different instance family.

## 6. Cost Guardrails

- Monthly AWS budget alert target: USD 75.
- Actual alerts: 50%, 80%, 100%.
- Forecast alerts: 80%, 100%.
- Budget is an alert/guardrail, not a destructive auto-shutdown mechanism.
- Record promotional-credit balance and expiration before provisioning.
- Prefer one host and one AZ until measured load proves scaling is necessary.
- Do not add paid infrastructure merely for architectural symmetry.

## 7. Authentication and Model Routing

Every provider is classified into one of four states:

1. `OFFICIAL_SUBSCRIPTION_OAUTH` — official subscription login usable by the runtime.
2. `OFFICIAL_PROVIDER_OAUTH` — provider-supported OAuth not necessarily tied to a consumer subscription.
3. `API_ONLY` — metered API credential required.
4. `NATIVE_APP_ONLY` — subscription is consumed only through its supported first-party client/tooling.

Current policy at design freeze:
- OpenAI Codex: official Hermes/Codex OAuth lane; preferred subscription-backed lane when healthy.
- xAI/Grok: enable only through documented official OAuth and only if entitlement verification succeeds.
- Claude Pro: native Claude Code subscription lane on Chromebook unless the pinned Hermes release documents and passes an official supported subscription path.
- Google AI Pro: native Antigravity/Google development lane unless the pinned Hermes release documents and passes an official supported consumer-subscription path.
- Perplexity Pro: native product/research lane unless an official runtime integration exists and passes verification.
- NVIDIA, OpenRouter, Venice, Google AI Studio/Vertex, and other approved endpoints: `API_ONLY` fallback through OmniRoute.

Browser cookies, Chrome profile databases, local/session storage, web-session bearer tokens, and CSRF tokens are never provider credentials for Hermes/JARVIS.

Routing order:
`official OAuth/subscription -> OmniRoute API fallback -> 9Router cold standby`.

OAuth-native providers bypass OmniRoute unless there is a documented technical requirement to route them through a gateway.

## 8. Hermes, JARVIS, and Router Responsibilities

Hermes Max is the single reasoning/state authority. JARVIS does not duplicate Hermes memory, scheduler, bot runtime, model catalog, or MCP transport when the pinned Hermes release already provides those capabilities.

JARVIS owns the governed action boundary:
- approvals and irreversible-action gates;
- HMAC/evidence ledger and proof-before-success checks;
- external tool authorization and policy enforcement;
- failure classification and rollback decisions;
- voice/HUD integration where JARVIS-specific behavior is required.

Hermes owns:
- core agent loop and session state;
- model selection policy and official provider auth;
- stateless MCP compatibility;
- Bot Mode/runtime primitives;
- skill/plugin discovery and upstream security scanning;
- scheduler/self-healing primitives supplied by the pinned release.

OmniRoute owns only metered/API backend routing, fallback pools, and compatible model aliases. 9Router stays installed/configurable as cold standby and must not be inserted into the normal request path.

## 9. Mobile Control

Hermes Relay Android v1.11.0 is the primary mobile client and the first phone-control policy surface. Use its explicit Bridge presets and bounded-duration screen-control grants before custom Android automation.

The existing Termux, Termux:API, Accessibility, Usage Access, Notification Access, and Shizuku bridges remain optional capability extensions for workflows Relay does not natively cover. They are not a second autonomous runtime.

Phone capabilities are scoped independently: `screen_read`, `screen_control`, `foreground_state`, `notification_read`, `screenshot`, `package_launch`, `clipboard_draft`, and `shell_action`.

Routine read/inspect/navigation/draft actions may run within granted capability scope. Sending, posting, deleting, purchasing, credential/OTP entry, privilege grants, security-setting changes, account/session termination, and destructive shell operations require explicit approval and auditable evidence.

Relay remote access uses Tailscale Serve WSS/HTTPS as the preferred path. Tailscale Funnel is disabled. Public reverse proxy exposure is not part of the baseline.

## 10. Chromebook Engineering Workstation

Chromebook Linux is the development, test, recovery, and administration workstation after cutover.

Approved tool lanes include:
- VS Code and Kiro;
- Claude Code using supported Claude subscription authentication;
- Codex CLI using supported ChatGPT/Codex authentication;
- Google Antigravity / `agy` using supported Google authentication;
- OpenCode for supported multi-provider development workflows;
- Git/GitHub CLI, Docker for builds/tests, AWS CLI, Terraform/OpenTofu, and Tailscale.

Concurrent coding agents must use isolated branches/worktrees rather than writing to one checkout simultaneously. Production credentials are not copied into agent worktrees.

The current local Hermes/JARVIS installation is retained until AWS cutover is proven. After successful migration it becomes stopped cold-recovery material rather than a second live production brain.

## 11. Release and Supply-Chain Model

Production is deployed from a deterministic release bundle, not from an unpinned repository checkout.

Every release must include:
- exact upstream Hermes/Relay compatibility pins;
- SHA-256 release checksum and internal file manifest;
- SBOM in a standard machine-readable format;
- provenance/build metadata including source commit and build timestamp;
- secret-exclusion checks;
- static policy/security checks;
- clean-clone replay instructions and verification evidence.

AWS bootstrap verifies both the outer archive checksum and the internal manifest before switching the active release symlink. A failed release never becomes current.

Upgrade procedure is canary-first:
1. build and verify the new immutable artifact;
2. run local/clean-clone acceptance;
3. deploy to a disposable or isolated canary path;
4. run runtime, auth, Relay, and policy checks;
5. promote atomically only after all mandatory gates pass;
6. preserve the prior known-good release for rollback.

## 12. Secret and Credential Handling

Secrets are excluded from Git, release archives, Terraform variables/state, screenshots, logs, and evidence bundles.

- EC2 uses its IAM instance role instead of static AWS access keys.
- OAuth credentials stay in the provider/runtime-supported auth store with owner-only permissions where supported.
- API keys are delivered out-of-band to an owner-only runtime secret file or an approved AWS secure parameter mechanism.
- Tailscale enrollment credentials are never committed or embedded in Terraform user-data/state.
- No browser profile, cookie database, session token, or token-harvesting script is deployed to AWS.
- Redaction tests scan generated artifacts and logs before release promotion.

If harvested consumer session credentials are ever detected, the build fails closed and reports only the credential type/location, never the secret value.

## 13. Host Hardening

Systemd services run as an unprivileged `hermes` service account where possible, with `NoNewPrivileges`, private temporary directories, bounded writable paths, restart limits, and explicit network/service dependencies.

Application services remain loopback-bound when Tailscale Serve can proxy them. Host firewall rules must not expose `4700`, `8642`, `9119`, `20127`, or `20128` on the public interface.

## 14. State, Backup, and Disaster Recovery

Durable state is separated from immutable application releases. Backups are encrypted and versioned, with bounded retention. Restore validation is part of release acceptance rather than an untested emergency-only procedure.

The deployment must demonstrate recovery from:
- replacement of the EC2 instance;
- failed application upgrade;
- corrupt runtime configuration;
- expired or failed OAuth refresh;
- lost/re-paired mobile client;
- temporary OmniRoute outage;
- failed 9Router standby activation;
- unavailable upstream provider.

Rollback restores the previous known-good release and configuration without deleting unique user state. The legacy production host is not decommissioned until migration, state parity, Relay round-trip, and rollback tests all pass.

## 15. Observability and Evidence

Health/status output must be machine-readable and secret-redacted. Required surfaces include service health, active release ID, provider-auth state (without tokens), router state, Relay reachability, Tailscale state, disk capacity, and last successful backup/restore test.

Operational success is evidence-driven: commands may report `PASS` only after the corresponding check actually runs. JARVIS proof-before-success semantics remain authoritative for governed tool actions.

Logs use bounded retention and must not contain prompts/documents by default when a lower-detail operational event is sufficient. Sensitive document/tool payloads remain outside routine telemetry.

## 16. Failure Behavior

Fail closed when an authorization, approval, provenance, checksum, policy, or secret-redaction gate cannot be verified.

Fail over only across explicitly approved model/provider routes. A subscription/OAuth failure must not silently create metered API spend unless the routing policy explicitly permits that fallback class.

## 17. Mandatory Acceptance Gates

A production promotion requires all applicable checks below to pass:

```text
AWS_REGION_US_EAST_1=PASS
INSTANCE_TYPE_M7I_FLEX_LARGE=PASS
VCPU_2=PASS
RAM_8_GIB=PASS
UBUNTU_24_04_AMD64=PASS
EBS_GP3_30_GIB=PASS
EBS_ENCRYPTED=PASS
GP3_3000_IOPS=PASS
GP3_125_MIBPS=PASS
IMDSV2_REQUIRED=PASS
SSM_MANAGEMENT=PASS
PUBLIC_SSH=NONE
PUBLIC_HERMES_PORTS=NONE
HERMES_AGENT_PIN=PASS
HERMES_RELAY_PIN=PASS
RELEASE_SHA256=PASS
INTERNAL_MANIFEST=PASS
SBOM=PASS
PROVENANCE=PASS
SECRET_SCAN=PASS
CLEAN_CLONE_REPLAY=PASS
```

Runtime gates continue in the next block.

```text
HERMES_CORE=PASS
JARVIS_GOVERNANCE=PASS
JARVIS_APPROVAL_LEDGER=PASS
PROOF_BEFORE_SUCCESS=PASS
STATE_MIGRATION=PASS
ROLLBACK=PASS
BACKUP_RESTORE=PASS
OFFICIAL_OAUTH_FIRST=PASS
OPENAI_CODEX_OAUTH=PASS
OMNIROUTE_API_FALLBACK=PASS
9ROUTER_COLD_STANDBY=PASS
BROWSER_COOKIE_HARVESTING=DISABLED
TOKENS_IN_GIT=NONE
TOKENS_IN_RELEASE=NONE
TOKENS_IN_LOGS=NONE
TAILSCALE=PASS
TAILSCALE_SERVE_PRIVATE=PASS
HERMES_GATEWAY_9119=PASS
HERMES_API_8642_OPTIONAL=PASS
RELAY_ANDROID_TO_AWS=PASS
RELAY_BRIDGE_SCOPES=PASS
MOBILE_SENSITIVE_ACTION_GATE=PASS
SINGLE_BACKEND_AUTHORITY=PASS
FINAL_VERIFICATION=PASS
```

Any non-applicable optional gate is recorded as `N/A` with a reason; it is never mislabeled `PASS`.
## 18. Cutover Sequence

1. Preserve and inventory the existing local and legacy cloud runtime; make no destructive change.
2. Build the pinned, secret-free immutable release and run clean-clone verification.
3. Authenticate AWS through the supported CLI/SSO path and run a read-only account/region/cost preflight.
4. Provision or update the AWS foundation only after the plan matches this specification.
5. Bootstrap Hermes/JARVIS, then deliver runtime secrets out-of-band.
6. Enroll the host into Tailscale without placing enrollment credentials in Terraform state.
7. Configure tailnet-only Tailscale Serve to the local Hermes Dashboard/Gateway.
8. Pair Hermes Relay Android and verify chat/session/voice/control round trips.
9. Migrate durable state, then run backup/restore and rollback rehearsals.
10. Promote AWS as authoritative only after `FINAL_VERIFICATION=PASS`.
11. Stop, but do not delete, the previous active runtime until a stable observation period completes.

## 19. Explicit Non-Goals

This release does not introduce Kubernetes, a second Hermes brain, a second memory authority, a new custom model router, a public unauthenticated gateway, browser-cookie credential harvesting, autonomous financial/purchase actions, or automatic destructive account/device actions.

Google Cloud remains secondary/support-only and must not host an independent Hermes authority. Additional clouds, databases, GPUs, and horizontal scaling are deferred until measured production need justifies them.

## 20. Definition of Done

The build is complete only when the repository implements this specification, all static/local tests pass, the immutable release can be reproduced from a clean checkout, live AWS preflight succeeds, the AWS host passes runtime checks, Relay works from the phone over the private tailnet path, OAuth/provider routing behaves according to policy, disaster recovery is rehearsed, and the final evidence report records `FINAL_VERIFICATION=PASS` without secret leakage.
## 21. Source-Control Authority During Build

The local `hermes-max-live` checkout is the implementation source of truth until a reachable GitHub remote is restored. The configured remote currently cannot be resolved through the connected GitHub account, so this build must not depend on remote fetch/push for correctness.

Local commits remain mandatory for atomic checkpoints and rollback. Restoring or replacing the GitHub remote is a separate, non-destructive handoff step; implementation must not silently repoint `origin` or discard local history.
