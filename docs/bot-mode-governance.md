# Governed Bot Mode

Hermes Max Bot Mode is a governance/profile layer inspired by upstream Hermes Desktop Bot Mode. It intentionally uses the existing Hermes profile primitive rather than adding another agent runtime, model router, credential store, memory system, or trust authority.

## Roster

The governed roster is defined in `config/bot-mode-policy.json`:

- Research -> `profiles/research/`
- Coding -> `profiles/coding/`
- Legal -> `profiles/legal/`
- Revenue -> `profiles/revenue/`
- Creator -> `profiles/creator/`

All Bots use capability-brokered credentials, have no externalization authority, and inherit the existing profile/router layer.

## Data-flow restrictions

Bot-to-Bot payloads are classified and fail closed at both sender and recipient.

- Research: `PUBLIC`, `INTERNAL`
- Coding: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SECURITY_SENSITIVE`
- Legal: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `LEGAL_PRIVILEGED`
- Revenue: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `FINANCIAL`
- Creator: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`
- Hermes Council: `PUBLIC`, `INTERNAL` only, equal to the safe intersection of its members

`CREDENTIAL` never flows through inter-Bot messages. Credentials must remain behind the existing capability/Containment boundary.

An inactive Bot cannot send or receive messages. A Bot cannot remain a Council member while inactive.

## Message envelopes

`src/system/bot-mode-governance.py` emits `hermes-bot-message-v1` envelopes with:

- sender and recipient profile IDs
- canonical data classification
- purpose
- body and SHA-256 digest
- evidence-parent reference
- UTC timestamp
- `trust=untrusted`
- `authority=none`
- `externalization_authorized=false`

The digest detects body alteration; it is not an authorization signature. The sender/evidence fields are provenance assertions that must be reconciled against the HMAC evidence/transport layer before being used as proof. Because every message remains untrusted and authority-free, a forged message cannot become an execution grant through this contract.

The runtime CLI always loads the repo-owned policy. There is no caller-facing `--policy` override.

Example:

```bash
printf '%s\n' 'Compare these public sources.' > /tmp/bot-message.txt
python3 src/system/bot-mode-governance.py message-create \
  --sender research \
  --recipient legal \
  --classification PUBLIC \
  --purpose research_handoff \
  --body-file /tmp/bot-message.txt \
  --evidence-parent ev_example_001
```

A receiving path should run `message-verify` before admitting the envelope as untrusted data.

## Hermes Council

`hermes-council` contains Research, Legal, Revenue, and Coding.

Hard bounds:

- 2-6 members
- maximum 3 deliberation rounds
- maximum 10 Bot messages per request/turn
- classified proposals only
- `status=PROPOSAL`
- `trust=untrusted`
- `authority=none`
- `externalization_authorized=false`
- `requires_governance_review=true`

Example:

```bash
printf '%s\n' 'Recommend a bounded canary evaluation.' > /tmp/council-proposal.txt
python3 src/system/bot-mode-governance.py council-create \
  --council hermes-council \
  --classification INTERNAL \
  --rounds 2 \
  --message-count 6 \
  --proposal-file /tmp/council-proposal.txt \
  --evidence-parent ev_research_001 \
  --evidence-parent ev_coding_001
```

Council output returns to governance/human review. It never goes directly to an executor.

## Production side effects

Bot collaboration does not change the existing side-effect path:

```text
Bot/profile proposal
  -> Trust Gate / data-flow policy
  -> signed short-lived capability
  -> external Containment Gateway / credential broker
  -> governed execution
  -> external-state receipt
  -> immutable evidence ledger
```

Scout remains discovery/proposal only. Infrastructure identities such as Trust Gate, Containment Gateway, Canary Controller, Evidence Ledger, OmniRoute, Scout, and Memory Fabric are forbidden Bot IDs.

## Desktop compatibility

This repository does not vendor unreleased Hermes Desktop code. The Bot registry deliberately maps to real Hermes profiles so a future signed upstream Desktop release can render the same profile primitive without a parallel Bot database.

Until that signed Desktop integration is adopted, the repo-level profile/governance contracts are the source of truth. Do not create a second credential pool, router, or Bot-specific memory store merely to mimic the UI.
