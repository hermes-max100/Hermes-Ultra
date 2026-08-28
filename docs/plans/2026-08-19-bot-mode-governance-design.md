# Governed Bot Mode Design

Date: 2026-08-19
Status: Approved for implementation

## Goal

Expose Hermes specialist profiles as persistent named Bots without creating a new agent runtime, router, memory system, credential pool, or governance authority.

A Bot is a governed view of an existing Hermes profile. Bot Mode may organize profile metadata, conversations, routines, and inter-profile collaboration, but it never grants trust or permission to perform an external side effect.

## Architectural invariants

- Governance / Trust Gate remains the only authority that can move capabilities through `discovered -> vetted -> trusted -> installed -> active`.
- Scout remains discovery/proposal only.
- The Containment Gateway remains the runtime enforcement boundary for network/credential use.
- Existing profile/router configuration remains authoritative; Bot Mode does not add a second model router.
- Existing Memory Fabric remains authoritative; Bot Mode does not add a memory subsystem.
- Inter-Bot messages are untrusted control-flow inputs, even when they originate from another governed profile.
- Council output is advisory `PROPOSAL` evidence only. It cannot authorize execution, promotion, installation, spending, sending, posting, filing, deployment, or credential access.
- Sensitive credentials are capability-brokered. Bots do not share a standing OAuth/token pool.
- External success still requires proof-before-success and an execution receipt.

## Initial governed roster

The Bot roster is an overlay, not a replacement for existing profiles. Initial specialist Bots are:

- `research`: public-research specialist. Agent Reach is available only through the hardened Agent Reach wrapper.
- `coding`: repository/code engineering specialist using existing governed code/tool boundaries.
- `legal`: maps to the existing `legal` profile and retains its legal review/citation constraints.
- `revenue`: Revenue OS analysis and proposal specialist. Externalization remains separately approved and contained.
- `creator`: virtual-creator research/content specialist. Posting, messaging, buying, and account mutation remain outside Bot authority.

Infrastructure identities are forbidden from Bot registration, including Trust Gate, Containment Gateway, Canary Controller, Evidence Ledger, OmniRoute, Scout, and Memory Fabric.

## Inter-Bot message contract

Every inter-Bot message uses `hermes-bot-message-v1` and contains:

- sender Bot/profile
- recipient Bot/profile or governed council
- data classification
- purpose
- body
- body SHA-256
- causal/evidence parent
- UTC creation time
- `trust: untrusted`
- `authority: none`

Validation is fail-closed. Unknown Bots, malformed classifications, digest mismatch, missing evidence ancestry, or any attempt to claim authority are rejected.

The envelope is evidence/provenance; it is not itself an execution capability.

## Hermes Council

`hermes-council` initially contains Research, Legal, Revenue, and Coding Bots.

Hard bounds:

- 2-6 members
- maximum 3 deliberation rounds
- maximum 10 Bot messages per user/request turn
- output status is always `PROPOSAL`
- every proposal records member identities, evidence parents, and a deliberation digest

The Council cannot emit an executable policy decision. Its output must return to governance/human review before any governed side effect.

## Desktop compatibility

NousResearch Bot Mode treats Bots as Hermes profiles. Hermes Max follows the same durable primitive so a future signed Hermes Desktop release can render these profiles without requiring a second Bot database.

This implementation deliberately does not vendor unreleased Hermes Desktop code. It adds the profile/governance contracts that the UI can safely consume later.

## Security model

Bot compromise is assumed possible. A compromised Bot must not be able to:

- turn another Bot's message into trusted policy
- grant itself credentials or network access
- create an infrastructure-authority Bot
- bypass Trust Gate or Containment Gateway
- convert a Council recommendation into an execution decision
- mutate the Bot policy through ordinary runtime messaging
- inherit another Bot's sensitive credentials

Production egress remains independently enforced outside the Bot/runtime process.
