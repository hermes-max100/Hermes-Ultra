# Hermes Legal Private MCP

Status: implemented boundary, transport adapters, tests, and CI. Provider-specific legal capabilities remain deliberately unbound until an explicit first-party or approved-provider handler is registered.

## Purpose

Hermes Legal is a private first-party capability boundary for legal work. It is not a collection of public MCP servers and it does not inherit trust from the general Hermes tool ecosystem.

Technical isolation can support confidentiality and data minimization, but this software architecture does not itself create attorney-client privilege or work-product protection.

## Architecture

```text
Hermes / authenticated agent host
        |
        |  server-owned matter authorizer
        |  server-owned sensitivity + max egress
        v
   MCP v2 / optional FastAPI
        |
        v
   LegalService
      |-- LegalPolicy
      |-- matter-isolated resource store
      |-- ProvenanceGuard
      |-- HMAC redaction attestations
      |-- payload-free audit records
      `-- explicitly registered legal handlers
```

The legal core has no required third-party dependency. `mcp` and `fastapi` are optional transport extras. Every transport calls `LegalService.execute`; transports never receive direct handler access.

## Legal tools

The private server advertises these governed entrypoints:

- `document_reader`
- `legal_retrieval`
- `citation_validator`
- `guarded_draft`
- `case_record_search`
- `timeline_builder`
- `exhibit_indexer`
- `record_fact_extractor`
- `authority_checker`
- `redact_for_external_model`
- `compare_filings`
- `record_citation_resolver`
- `perseus_remember`
- `perseus_recall`

A tool that has no registered first-party handler fails closed with `tool_handler_unavailable`. This prevents a declared capability from silently falling through to a general broker.

## Trusted transport controls

The MCP model/client and HTTP request body are **not** allowed to select either the sensitivity class or maximum egress mode. Those controls are fixed when the MCP server / FastAPI router is constructed.

Every transport call also runs a deployment-supplied `matter_authorizer(matter_id)` before creating a `LegalContext`. An unauthorized matter fails before service dispatch and produces no service audit event.

For a multi-user deployment, the matter authorizer must be bound to the authenticated principal (for example through a per-principal server instance or an authenticated request context). A function that merely checks whether a matter ID exists is not sufficient authorization.

## Routing policy

Default maximum egress is `external_access=DENY`.

| Route | Default | Additional requirement |
| --- | --- | --- |
| `LOCAL` | allow | tool must permit local route |
| `OFFICIAL_LEGAL_API` | deny | server must enable `ALLOWLIST`; provider must be explicitly configured; tool must permit this route |
| `APPROVED_MODEL` | deny | server must enable `ALLOWLIST`; provider explicitly configured; exact outbound payload must carry a valid matter-bound redaction attestation; tool must permit model route |
| `MONID` | deny | categorical |
| `PUBLIC_MCP` | deny | categorical |
| `UNKNOWN` | deny | categorical |

No provider names are shipped in an allowlist. Deployment must configure each approved provider explicitly. User-supplied endpoint overrides are not part of the route contract; provider handlers must use deployment-owned endpoint configuration.

Current route capability matrix:

- Local only: document reading, case-record search, timeline construction, exhibit indexing, record-fact extraction, external-model redaction, filing comparison, Perseus remember/recall.
- Local or allowlisted official legal API: legal retrieval, citation validation, authority checking, record-citation resolution.
- Local or approved redacted model: guarded drafting.

## Matter isolation

Every request requires a `matter_id`. Stored resources and provenance sources are bound to exactly one matter. A cross-matter read raises `MatterIsolationViolation`; reusing a source/resource identifier from another matter is denied.

Matter isolation is separate from matter authorization: the transport first establishes that the caller is authorized for the requested matter, then the core prevents resources/sources from crossing matter boundaries.

Persistence adapters must retain the same matter key and should use separate encryption/access-control scopes where the deployment supports them.

## Provenance invariants

Hermes Legal enforces:

1. A fact cannot be marked verified without at least one registered matter-bound source.
2. A citation cannot be marked verified without at least one matter-bound source classified as `AUTHORITY`.
3. A success claim cannot be emitted without a non-empty evidence bundle.
4. Source IDs cannot cross matter boundaries.
5. Source redefinition is rejected unless the complete source record is identical.

Evidence sources require a SHA-256 digest and locator.

## External-model redaction and attestation

`redact_for_external_model` recursively replaces explicitly named fields with `[REDACTED]` and then creates an HMAC-SHA256 attestation over:

- the active `matter_id`; and
- the SHA-256 digest of the exact canonical sanitized payload.

The redaction gate fails closed when:

- no redaction keys are supplied;
- none of the supplied targets exist in the payload; or
- the outbound payload is not JSON-safe.

An approved-model route must supply that attestation with the **exact sanitized payload** under `arguments.payload`. Hermes recomputes the digest and HMAC before dispatch. A forged token, modified payload, or reuse under another matter is denied.

The HMAC key is generated per `LegalService` instance by default. Multi-worker/restart-stable deployments must inject the same protected key into every intended legal-service replica; it must not be exposed to MCP/HTTP callers or handlers that do not need it.

Field-level redaction is a minimum boundary, not a substitute for a full DLP classifier. Provider-bound handlers should add document-specific DLP before production externalization.

## Audit

`LegalService.audit_records` is append-only from the caller's perspective and records:

- sequence
- matter ID
- tool name
- route kind
- outcome (`DENY`, `ERROR`, `EXECUTED`)
- stable reason

Arguments, document contents, prompts, credentials, exception details, and retrieved legal text are deliberately excluded.

For async handlers, `EXECUTED` is written only after the awaited handler completes. A raised exception becomes `ERROR`; returning a coroutine is not treated as proof of success.

Durable/HMAC-backed persistence should be attached to Hermes's existing evidence ledger at deployment. The current in-process list is the transport-neutral audit contract, not the final durable ledger.

## MCP

The MCP adapter targets the official MCP Python SDK v2 (`mcp>=2,<3`) and registers every private legal tool on one `MCPServer`.

The server constructor requires a trusted matter authorizer. It fixes sensitivity and maximum external access outside the tool schema, so an agent cannot request `ALLOWLIST` or downgrade `LEGAL_PRIVILEGED` in a tool call. The official SDK's in-process `Client(server)` path is used by CI to test actual protocol registration, tool schema, dispatch, and denials.

## FastAPI

`create_fastapi_router()` is an optional REST facade over `LegalService`. It requires the same trusted matter-authorizer and server-owned sensitivity/egress configuration. The request body cannot override those controls. It returns stable denial reasons and does not echo privileged request payloads into errors.

FastAPI is a transport, not the legal security boundary.

## Deployment requirements

Application policy is necessary but not sufficient. Production deployment should add a separate legal egress control at the network layer:

```text
Legal runtime
  -> explicitly approved court/legal-provider endpoints
  -> explicitly approved model endpoint(s), only when policy permits
  -> deny everything else
```

Do not treat the Python allowlists as proof of network isolation. Network enforcement belongs in the existing Hermes containment/egress layer.

Recommended production controls:

- bind the legal service to a private/authenticated interface;
- bind the matter authorizer to the authenticated principal;
- use the existing containment gateway for an explicit legal egress allowlist;
- keep Monid/general MCP endpoints out of that allowlist;
- use scoped capability-brokered credentials, never standing shared credentials;
- keep the redaction HMAC key in a protected deployment secret and consistent across intended replicas;
- encrypt durable matter storage and evidence at rest;
- disable payload logging in reverse proxies/APM for legal routes;
- attach audit/provenance events to the existing HMAC/evidence ledger;
- rotate provider credentials independently of general Hermes credentials;
- test network denies independently of application-level denies.

## Installation and validation

Core only:

```bash
python -m pip install -e '.[test]'
```

MCP + FastAPI transports:

```bash
python -m pip install -e '.[test,legal]'
```

Targeted validation:

```bash
python -m compileall -q src/hermes_ultra/legal
python -m pytest -q \
  tests/test_legal_private_mcp.py \
  tests/test_legal_private_integration.py \
  tests/test_legal_private_security_regressions.py \
  tests/test_legal_mcp_sdk.py \
  tests/test_bot_mode_governance.py
```

CI runs the legal suite on Python 3.10 and 3.12.

## Handler contract

Provider or feature implementations are registered explicitly:

```python
service.register_handler("document_reader", document_reader_handler)
service.register_handler("legal_retrieval", official_legal_retrieval_handler)
```

A handler receives the already-authorized `LegalContext` plus a copied argument mapping. Routing authorization happens before dispatch. Provider handlers must not create their own fallback to Monid, public MCP, arbitrary URLs, or another general-purpose broker.
