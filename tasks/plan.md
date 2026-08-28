# Implementation Plan: Hermes Virtual Creator Revenue System

## Overview

Build a compliant virtual creator revenue workflow for Hermes/JARVIS. The first
version is local/report-first: it creates persona memory, trend scans, content
plans, drafts, compliance checks, and analytics artifacts without posting or
messaging automatically.

## Architecture Decisions

- Use an AI-disclosed virtual creator, not a hidden fake human identity.
- Use Agent Reach for read-only public trend/source collection.
- Use YOLO mode only for retrieval and research gates.
- Keep posting, messaging, deleting, buying, credentials, account settings, and
  permission changes human-only.
- Implement as skills plus a `revenue-ops.sh` driver so it transfers cleanly to
  other Hermes agents.

## Task List

### Phase 1: Foundation

- [x] Task 1: Add virtual creator profile template.
- [x] Task 2: Add trend scanner skill.
- [x] Task 3: Add content planner skill.
- [x] Task 4: Add compliance checker skill.

### Checkpoint: Foundation

- [x] JSON templates validate.
- [x] Skills have `SKILL.md` entrypoints.
- [x] Compliance checker blocks deceptive synthetic identity claims.

### Phase 2: Driver

- [x] Task 5: Add `src/system/revenue-ops.sh`.
- [x] Task 6: Add local report output directories.
- [x] Task 7: Add analytics ledger command.

### Checkpoint: Driver

- [x] `bash -n src/system/revenue-ops.sh` passes.
- [x] `revenue-ops.sh scan --profile virtual-creator` writes a report.
- [x] No command posts, sends, deletes, or changes account settings.

### Phase 3: Evaluation

- [x] Task 8: Add shell boundary tests.
- [x] Task 9: Add promptfoo policy eval.
- [x] Task 10: Add restore/export verification entries.

### Checkpoint: Complete

- [x] Boundary tests pass.
- [x] Promptfoo eval passes.
- [x] Transfer bundle includes profile, skills, driver, tests, docs.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Hidden synthetic identity | High | Mandatory disclosure check and block rules. |
| Unsupported income claims | High | Claims require evidence or are removed. |
| Platform policy drift | Medium | Daily/weekly Agent Reach retrieval gate checks. |
| Over-automation of DMs/posts | High | Human-only approval gate. |
| Low content quality | Medium | Analytics ledger and kill criteria. |

## Open Questions

- Which niche should be first: local service lead follow-up, AI automation
  consulting, legal workflow templates, or another niche?
- Which public platforms are already available for manual posting?
- Should the first monetization target be a service offer or a digital product?

