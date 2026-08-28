# Hermes Containment Gateway

The Containment Gateway is a deterministic enforcement boundary for network and credential capabilities. It does **not** decide whether an agent is trusted and it does not replace Trust Gate, `can_flow`, the router, or governance. Governance decides whether a capability may be issued; this gateway binds and enforces that decision after agent code is already running.

## Security invariant

A tool connection is denied unless a currently valid capability exactly matches all of:

- principal/agent
- tool or capability name
- destination origin
- resource identifier
- Hermes data classification
- evidence/approval identifier
- expiry window

Capabilities are HMAC-SHA256 authenticated, short-lived, single-use by default, and bound to the evidence ID that justified issuance. Tampering, replay, expiry, revocation, scope substitution, malformed signed schemas, unsafe/path-traversing grant IDs, and the emergency kill switch fail closed.

The verifier independently enforces the signed lifetime. The default maximum lifetime is 300 seconds. Runtime request arguments cannot change the signing-secret source, replay-state directory, maximum TTL, consumption behavior, or single-use policy.

## Trusted startup configuration

The only supported runtime configuration is established before the untrusted request reaches the verifier:

- `HERMES_CONTAINMENT_SECRET` — HMAC secret, minimum 32 bytes.
- `HERMES_CONTAINMENT_STATE_DIR` — replay/revocation/kill-switch state.
- `HERMES_CONTAINMENT_MAX_TTL` — optional verifier TTL ceiling; defaults to 300 seconds and cannot exceed the implementation hard ceiling.

Do not let the agent choose or rewrite these values. In production they belong to the external verifier/credential broker service identity.

## Deployment boundary

For production, run verification **outside the agent/runtime security boundary** (for example, an egress proxy, credential broker, host service, or separate service/network policy that the agent cannot reconfigure). Do not expose `HERMES_CONTAINMENT_SECRET` to the agent process. The agent should receive only the signed capability. Network policy and credential release should happen only after the external verifier returns `ALLOW`.

Recommended flow:

`agent/tool request -> can_flow -> governance/Trust Gate grant -> signed capability -> containment verifier -> scoped credential/egress -> execution -> external-state receipt -> evidence ledger`

The local CLI is the reference implementation and regression harness. Merely invoking it inside an unrestricted agent process is **not** an independent containment plane.

## Operations

Use a random secret of at least 32 bytes supplied through the broker's secret manager, not a committed file:

```bash
export HERMES_CONTAINMENT_SECRET='...'
export HERMES_CONTAINMENT_STATE_DIR='/var/lib/hermes-containment'
```

Issue a short-lived capability only after governance approval:

```bash
bash src/system/containment-gateway.sh issue \
  --principal agent:hermes \
  --tool mcp:github \
  --destination https://api.github.com \
  --resource repo:hurakan100/Hermes-Evolution \
  --data-class INTERNAL \
  --purpose repo-maintenance \
  --evidence-id ev_123 \
  --ttl 60 > /secure/path/capability.json
```

Verify and consume it at the external boundary. The verifier accepts the capability over standard input rather than a caller-selected filesystem path:

```bash
cat /secure/path/capability.json | \
  bash src/system/containment-gateway.sh verify \
    --token-stdin \
    --principal agent:hermes \
    --tool mcp:github \
    --destination https://api.github.com \
    --resource repo:hurakan100/Hermes-Evolution \
    --data-class INTERNAL
```

Emergency containment is independent of capability validity and TTL configuration:

```bash
bash src/system/containment-gateway.sh kill on --reason incident
bash src/system/containment-gateway.sh kill off --reason recovered
```

Revoke one grant with:

```bash
bash src/system/containment-gateway.sh revoke cap_<id> --reason policy-change
```

The state directory defaults to `.hermes/containment`. It records used/revoked grant receipts and the kill switch, but never the HMAC secret. Symlinked or unsafe state paths fail closed.

## Destination rules

Destination matching is exact and origin-only; URL paths are intentionally rejected so authority cannot be broadened through URL normalization. Resource matching is also exact.

Literal loopback, link-local, unspecified, multicast, and known metadata-service IP destinations are rejected. URL user-info credentials are rejected. IPv6 authorities are normalized in bracketed form.

DNS rebinding still requires an independent egress/network enforcement boundary in production. Application-layer destination checks are defense in depth, not a substitute for the external containment plane.

## Token transport and parsing

Verification uses standard input (`--token-stdin`) so a more-privileged verifier cannot be turned into a confused-deputy arbitrary file reader. Token JSON is bounded in size, must be UTF-8, must not contain duplicate object keys, and must match the signed schema exactly.

Single-use capabilities are atomically consumed so replay fails closed across concurrent verifiers sharing the same protected state directory.

## Verification

Run:

```bash
bash tests/test_containment_gateway.sh
```

The regression suite covers exact-scope success; unauthorized destination/resource/principal/tool substitution; expiry; oversized signed lifetime; tampering; replay; revocation; emergency kill; TTL bounds; weak secrets; destination normalization; embedded URL credentials; metadata/link-local target denial; grant-ID path traversal; state-directory symlinks; strict signed-field/type validation; bounded/symlink-safe token loading; and rejection of request-time trusted-configuration bypass flags.
