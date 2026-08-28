# Governed Bot Mode Implementation Plan

Date: 2026-08-19
Branch: `ai/governed-bot-mode`

## Acceptance contract

Bot Mode is complete only when all of the following are true:

1. The roster is an overlay over real Hermes profiles; no parallel Bot database or agent lifecycle exists.
2. Five initial specialist Bots exist: Research, Coding, Legal, Revenue, Creator.
3. Every Bot uses `credential_mode=capability_brokered` and forbids standing shared credentials.
4. Bot configuration inherits the existing profile/router layer and cannot declare a new router or execution authority.
5. Inter-Bot messages have a strict, digest-bound, evidence-linked untrusted envelope.
6. The Hermes Council is bounded to 2-6 members, 3 rounds, and 10 Bot messages and can emit only `PROPOSAL` artifacts.
7. Infrastructure authorities cannot be registered as Bots.
8. Research routes public web collection through the hardened Agent Reach entrypoint rather than direct backend CLIs.
9. Dedicated Bot Mode security tests and immutable-SHA GitHub Actions validation pass in a clean PR merge ref.
10. Existing workflow supply-chain validation remains green.

## TDD sequence

### RED

Add regression tests that fail against the current tree for:

- missing Bot policy and roster
- infrastructure-authority Bot rejection
- shared credential rejection
- missing real profile mappings
- unknown sender/recipient rejection
- message digest tamper rejection
- forced `trust=untrusted` and `authority=none`
- missing evidence parent rejection
- Council authority/status tampering rejection
- Council member/round/message caps
- Council externalization denial
- Research direct-backend prohibition
- router duplication prohibition

Commit RED tests and dedicated CI before implementation.

### GREEN

Add:

- `config/bot-mode-policy.json`
- `src/system/bot-mode-governance.py`
- specialist profile SOUL files for Research, Coding, Revenue, Creator
- profile-manifest entries for the new specialist profiles
- governed inter-Bot message CLI/contracts
- governed Council proposal CLI/contracts
- docs and validation workflow

### REFACTOR / RED TEAM

Run a second adversarial pass for:

- policy unknown fields
- path/profile alias tricks
- classification case/canonicalization
- message/proposal unknown fields
- digest substitution
- forged authority fields
- duplicate/missing Council members
- over-limit rounds/message counts
- caller-provided router/model authority
- direct credential-sharing declarations

## Merge gate

Merge to `hermes-max-setup` only after the current head passes clean merge-ref CI and the PR has no unresolved review threads.
