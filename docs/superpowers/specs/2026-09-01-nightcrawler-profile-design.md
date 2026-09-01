# Nightcrawler Profile Design

Date: 2026-09-01
Status: Approved architecture, pending implementation plan
Branch: `ai/nightcrawler-profile`

## 1. Purpose

Nightcrawler is a first-class Hermes-Ultra profile for powerful, high-risk, dual-use, offensive-security, dark-web, malware-analysis, reverse-engineering, exploit, scanner, remote-shell, and related capabilities.

The profile exists to isolate **execution authority**, not to reduce functionality.

Core rule:

> Preserve capabilities. Make the catalog globally visible. Gate cross-profile execution behind owner authorization. Do not allow privilege inheritance or silent delegation.

Nightcrawler MUST NOT weaken, stub, simulate, remove, or rewrite an admitted tool merely because the tool is risky. When an upstream artifact is admitted, its original capability set remains available to Nightcrawler, subject only to the same platform-wide controls that already apply to Hermes-Ultra as a whole.

## 2. Non-goals

Nightcrawler is not:

- a reduced-function security sandbox;
- a fake or training-only replacement for real tools;
- a second Hermes brain;
- a new memory system;
- a new model router;
- a mechanism for hiding risky capabilities from other agents;
- a mechanism for automatically granting risky tools to every agent;
- a reason to modify protected model-routing files.

This design does not authorize changes to Hermes-Ultra's protected model router.

## 3. Capability ownership model

Nightcrawler owns the execution authority for the capabilities assigned to its profile.

Initial Nightcrawler inventory SHALL include, once provenance is resolved and pinned during implementation:

- Robin dark-web OSINT;
- the `dark-web-osint-tools` catalog as a discovery/reference source;
- Obliterus, as identified by the owner;
- the `apurvsinghgautam/HTTP-Reverse-Shell` artifact;
- authorized pentesting and exploitation tooling;
- Tor and dark-web research tooling;
- scanners and active assessment tooling;
- malware-analysis and reverse-engineering skills;
- exploit-development or exploit-execution frameworks present in Hermes-Ultra;
- credential-analysis or remote-administration tooling that is materially higher risk than ordinary Hermes tools;
- other capabilities classified as high-risk during the implementation inventory.

The implementation inventory MUST resolve each admitted capability to an exact local skill, repository, package, binary, model, MCP server, or service identity. External artifacts MUST be provenance-pinned before activation.

A tool's admission to Nightcrawler changes **where its execution authority lives**, not what the tool can do.

## 4. Global capability visibility

Every Hermes agent/profile MUST be able to inspect the Nightcrawler capability catalog.

Catalog visibility includes, where available:

- capability/tool name;
- description;
- feature/capability summary;
- version, source, commit, digest, or other provenance identity;
- required runtime or service dependencies;
- risk classification and reason;
- whether the requesting profile currently has execution permission;
- the grant scope and expiry when access has been delegated.

Catalog visibility MUST NOT expose raw secrets, private keys, session tokens, API keys, passwords, or other credentials.

This visibility is deliberate. Agents are expected to reason over the catalog and may recommend capabilities they do not currently possess.

Example behavior:

> "I currently have Obliterus access. I can also see Nightcrawler has HTTP Reverse Shell, which could help with the next step. I do not have permission to execute it. Request owner access?"

Such a recommendation is permitted. Execution is not.

## 5. Native Nightcrawler authority

Nightcrawler itself has native access to the capabilities assigned to Nightcrawler.

Nightcrawler MUST NOT require a separate cross-profile override merely to access its own catalog or invoke its own admitted tools.

The purpose of Nightcrawler is to be the profile in which those tools remain fully available.

Existing platform-wide Hermes controls remain unchanged. Nightcrawler neither removes those controls nor introduces a second policy system.

## 6. Cross-profile execution gate

All non-Nightcrawler profiles are denied Nightcrawler execution authority by default.

A non-Nightcrawler profile MAY execute a Nightcrawler capability only when an owner-authorized override grant matches the request.

The grant MUST be attributable to the owner and MUST bind at least:

- requesting profile/agent;
- Nightcrawler capability or capability set;
- grant identifier;
- issuance time;
- scope;
- expiration or explicit persistence rule;
- delegation rule;
- evidence/audit requirements.

The owner controls grant breadth. The system MUST support narrow and broad grants, including examples such as:

- one capability for one task;
- several capabilities for one investigation;
- one category for a defined period;
- full Nightcrawler access for a defined period;
- persistent access when the owner explicitly chooses it.

Nightcrawler MUST NOT impose a narrower grant than the owner approved.

## 7. No privilege chaining

Cross-profile grants are non-transitive by default.

If Scout is granted Obliterus access, that grant does not automatically confer:

- HTTP Reverse Shell access;
- Robin access;
- scanner access;
- exploit-framework access;
- full Nightcrawler access;
- authority to grant Nightcrawler access to another agent.

A profile receiving a Nightcrawler grant MAY recommend additional tools and request another owner grant.

A grantee MUST NOT mint, widen, transfer, or delegate Nightcrawler authority unless the owner's grant explicitly authorizes delegation.

## 8. Capability recommendations

Every agent may reason over globally visible Nightcrawler metadata and surface recommendations.

Recommendation flow:

1. Agent inspects Nightcrawler catalog metadata.
2. Agent identifies a capability that may improve the current task.
3. Agent checks its own effective grants.
4. If unauthorized, it explains the capability and why it may help.
5. Agent requests owner authorization.
6. Hermes records the owner's decision.
7. On approval, Hermes issues a grant bound to the approved scope.
8. On denial or expiry, execution remains unavailable while catalog visibility remains.

A recommendation MUST NOT be treated as permission.

## 9. Provenance and capability preservation

Each Nightcrawler capability MUST have a provenance record sufficient to distinguish the admitted artifact from a changed artifact.

Where technically available, record:

- upstream repository/package identity;
- exact version/tag;
- commit SHA;
- release asset digest;
- source-tree digest;
- dependency lock or equivalent;
- license metadata;
- local adapter/wrapper version;
- security-scan evidence.

Wrappers and adapters SHOULD normalize invocation, receipts, policy checks, and evidence collection without deleting upstream functions.

If an adapter cannot preserve an upstream capability, the implementation MUST report that incompatibility rather than silently dropping the capability.

Updating a pinned external tool creates a new provenance identity and requires normal Nightcrawler admission review. It does not silently inherit the previous artifact's identity.

## 10. Risk inventory and classification

Nightcrawler uses risk classification to decide **profile placement and cross-profile permission requirements**, not to delete functionality.

A capability SHOULD be placed in Nightcrawler when it materially increases one or more of these powers:

- remote command execution;
- exploitation;
- vulnerability scanning;
- persistence or remote administration;
- credential or secret interaction;
- malware analysis or malware-like execution surfaces;
- reverse engineering;
- device or host control;
- dark-web/Tor investigation;
- active reconnaissance;
- network interception or manipulation;
- evasion-oriented or stealth-oriented execution;
- arbitrary code/plugin execution from external sources.

During implementation, Hermes-Ultra's existing skill/plugin inventory SHALL be audited against these criteria. The resulting inventory becomes an explicit Nightcrawler catalog rather than an implicit blacklist.

## 11. Existing cyber profiles

Existing cyber-specific or quarantine-oriented profiles, including `cyberkimi-quarantine`, are inputs to the Nightcrawler inventory review.

Nightcrawler SHALL reuse compatible Hermes governance primitives where they help with identity, grants, evidence, and auditability, but it SHALL NOT inherit capability-reduction assumptions merely because an older profile used them.

The implementation MUST avoid two competing authorization systems. Nightcrawler cross-profile grants should extend the existing Hermes authority/grant model rather than replace it.

## 12. Data and evidence flow

A Nightcrawler execution produces an evidence envelope containing, at minimum:

- requesting profile;
- executing profile (`nightcrawler`);
- capability identity;
- provenance identity;
- effective owner grant when cross-profile;
- task/run correlation identifiers;
- start and completion state;
- result/receipt metadata appropriate to the tool;
- redacted failure information when execution fails.

Raw credentials and sensitive authentication material MUST NOT be written into the evidence ledger.

Nightcrawler-native execution records that no cross-profile grant was required because the executing profile was Nightcrawler.

## 13. Failure behavior

Fail closed when:

- a non-Nightcrawler profile has no matching owner grant;
- a grant is expired;
- a grant does not cover the requested capability;
- the artifact provenance does not match the admitted Nightcrawler identity;
- an agent attempts unauthorized delegation or grant widening;
- the requested capability is ambiguous and cannot be resolved to one catalog identity.

Failing closed means denying that invocation. It MUST NOT remove the capability from Nightcrawler or rewrite the upstream artifact.

## 14. User experience

Agents should expose enough information for the owner to make a useful decision.

A cross-profile request should state:

- requesting profile;
- requested Nightcrawler capability;
- why it is relevant;
- current authorization state;
- requested scope/duration;
- whether broader Nightcrawler access would materially help.

The owner may approve, deny, narrow, or broaden the requested grant.

The system should make it easy for the owner to ask:

- "What is in Nightcrawler?"
- "What can Trading use from Nightcrawler right now?"
- "Give Scout Robin for this task."
- "Give this agent full Nightcrawler access for two hours."
- "Revoke Nightcrawler access from Revenue OS."

## 15. Security boundary

Nightcrawler's primary security boundary is authorization isolation:

- capability metadata is globally readable;
- credentials remain secret;
- Nightcrawler retains native execution authority;
- other profiles require owner grants;
- grants do not propagate automatically;
- provenance changes invalidate artifact identity;
- all cross-profile uses are attributable and auditable.

This design intentionally avoids capability suppression as a security mechanism.

## 16. Testing requirements

Implementation MUST include tests proving:

1. All profiles can enumerate Nightcrawler catalog metadata.
2. Catalog enumeration does not reveal stored secrets.
3. Nightcrawler can invoke its admitted capabilities without a cross-profile grant.
4. A normal profile cannot invoke a Nightcrawler capability without an owner grant.
5. A valid owner grant enables exactly the approved access.
6. A one-tool grant does not imply access to other Nightcrawler tools.
7. A grantee cannot delegate access unless delegation was explicitly authorized.
8. Expired and revoked grants fail closed.
9. Broad owner grants are honored at the breadth the owner selected.
10. Provenance mismatch blocks invocation without deleting or modifying the Nightcrawler capability.
11. Agents can recommend visible Nightcrawler capabilities they are not authorized to execute.
12. Risk inventory placement does not rewrite or reduce admitted upstream functionality.
13. Protected model-routing files remain byte-for-byte unchanged.

## 17. Acceptance criteria

Nightcrawler is accepted when:

- `nightcrawler` exists as a first-class Hermes-Ultra profile;
- the initial risky capability inventory is explicit and provenance-backed;
- all Hermes profiles can inspect the Nightcrawler catalog;
- Nightcrawler retains the admitted tools' original capability surfaces;
- non-Nightcrawler execution requires owner-authorized grants;
- owner grants can be narrow, broad, temporary, or explicitly persistent;
- no privilege chaining occurs unless explicitly owner-authorized;
- agents can request additional Nightcrawler capabilities based on catalog awareness;
- execution and authorization decisions are auditable without exposing secrets;
- no protected model-router change is required;
- regression tests prove the above behavior.

## 18. Architectural invariant

The implementation SHALL preserve this invariant:

> **Global capability awareness + full Nightcrawler capability preservation + owner-controlled cross-profile execution + no automatic privilege inheritance.**
