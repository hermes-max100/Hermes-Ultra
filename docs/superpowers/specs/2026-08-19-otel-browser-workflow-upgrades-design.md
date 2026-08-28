# Hermes OTel + Deterministic Browser Workflow Upgrades — Design

## Scope

This design implements the two previously approved upgrades that are still absent from `hermes-max-setup` after the 2026-08-19 containment hardening:

1. A vendor-neutral OpenTelemetry GenAI bridge that makes Hermes runs traceable without replacing Memory/Trajectory Fabric.
2. A deterministic browser workflow compiler/cache that replays only prevalidated same-site workflows and requires Hermes containment authorization for live execution.

The existing containment gateway, approval HMACs, Landlock/seccomp candidate sandbox, Trust Gate, Memory Fabric, and browser same-site/public-routing rules remain authoritative.

## 1. OpenTelemetry bridge

`src/system/otel-bridge.py` emits a local append-only JSONL span record for every instrumented operation and can optionally export standards-shaped OTLP/HTTP JSON when explicitly enabled. Prompt/completion/tool payload contents are omitted by default; secret-like keys are always redacted. `LEGAL_PRIVILEGED`, `FINANCIAL`, `SECURITY_SENSITIVE`, and `CREDENTIAL` traces remain metadata-only even if content export is requested.

`src/system/hermes-dispatch.sh` becomes the first instrumented root operation. It creates/propagates `HERMES_TRACE_ID` and `HERMES_TRACE_SPAN_ID`, records only query hashes and routing metadata, and writes the trace IDs into the existing trajectory envelope so Memory Fabric evidence can be correlated with live telemetry.

Telemetry is fail-open for availability by default: a collector outage must not break Hermes execution. Setting `HERMES_OTEL_EXPORT_STRICT=1` makes exporter failures fatal for environments that require it. Local span storage remains available unless `HERMES_OTEL_DISABLE=1`.

## 2. Deterministic browser workflow cache

`src/system/browser-workflow-cache.py` accepts only successful, evidence-backed browser traces and compiles them into immutable workflow specifications under `.hermes/browser-workflows/`.

Allowed v1 actions are deliberately small: `navigate`, `fill`, `click`, `assert_url`, and `assert_text`. Every network navigation must stay on the workflow's registrable domain and pass public-address validation. Sensitive parameter names and selectors/labels suggesting passwords, OTPs, CAPTCHAs, payment data, credentials, or uploads are rejected.

Compilation does not execute browser actions. `replay --dry-run` validates and parameterizes without opening a browser. Live `replay --execute` requires a single-use Hermes containment capability scoped to:

- principal supplied by the caller;
- tool `browser:workflow`;
- destination equal to the workflow origin;
- resource `workflow:<workflow_id>`;
- requested Hermes data classification.

The capability is verified through the existing `containment-gateway.sh` before Playwright starts. A successful replay produces an immutable receipt with workflow hash, rendered-step hashes, final URL, assertions, duration, and status; field values are never written to the receipt.

## Security invariants

- No prompt/completion/body content in telemetry by default.
- No credential-class content is exported.
- No cross-site browser workflow navigation.
- No CAPTCHA, login, payment, credential, upload, or sensitive-field automation.
- No live replay without an exact containment capability.
- No workflow overwrite: a workflow ID is create-once; identical recompilation is idempotent, conflicting content fails closed.
- No silent self-healing. A broken workflow fails and must return to the governed candidate/Trust Gate path for revision.

## Verification

Tests must prove redaction/content omission, sensitive-class metadata-only telemetry, stable trace/span IDs, workflow immutability, cross-site rejection, sensitive-parameter rejection, evidence requirement, dry-run parameterization, and live-replay capability enforcement. GitHub Actions runs the new tests plus shell syntax checks on every PR touching these components.
