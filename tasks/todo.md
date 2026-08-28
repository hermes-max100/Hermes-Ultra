# Hermes Virtual Creator Revenue System Todo

## Task 1: Add Virtual Creator Profile Template

**Description:** Add a JSON profile template for persona, disclosure, audience,
platforms, monetization, and approval policy.

**Acceptance criteria:**
- [x] `config/virtual-creator-profile.example.json` exists.
- [x] JSON validates with `python3 -m json.tool`.
- [x] Includes disclosure and prohibited behavior fields.

**Verification:**
- [x] `python3 -m json.tool config/virtual-creator-profile.example.json`

**Dependencies:** None

**Files likely touched:**
- `config/virtual-creator-profile.example.json`

**Estimated scope:** Small

## Task 2: Add Trend Scanner Skill

**Description:** Add a read-only skill that uses Agent Reach/public sources to
collect trend opportunities and source-linked findings.

**Acceptance criteria:**
- [x] `.agents/skills/virtual-creator-trend-scanner/SKILL.md` exists.
- [x] Skill requires source URLs and confidence labels.
- [x] Skill forbids posting, messaging, liking, following, or private scraping.

**Verification:**
- [x] `test -f .agents/skills/virtual-creator-trend-scanner/SKILL.md`

**Dependencies:** Task 1

**Files likely touched:**
- `.agents/skills/virtual-creator-trend-scanner/SKILL.md`

**Estimated scope:** Small

## Task 3: Add Content Planner Skill

**Description:** Add a skill that turns trend findings and persona state into a
7-day content calendar.

**Acceptance criteria:**
- [x] `.agents/skills/virtual-creator-content-planner/SKILL.md` exists.
- [x] Skill uses 70/20/10 useful/proof/offer mix.
- [x] Skill requires AI disclosure notes for synthetic media.

**Verification:**
- [x] `test -f .agents/skills/virtual-creator-content-planner/SKILL.md`

**Dependencies:** Tasks 1-2

**Files likely touched:**
- `.agents/skills/virtual-creator-content-planner/SKILL.md`

**Estimated scope:** Small

## Task 4: Add Compliance Checker Skill

**Description:** Add a policy gate skill that returns pass, revise, or block for
virtual creator drafts.

**Acceptance criteria:**
- [x] `.agents/skills/virtual-creator-compliance-check/SKILL.md` exists.
- [x] Blocks undisclosed AI creator claims.
- [x] Blocks stolen likeness, celebrity lookalike, fake earnings, and fake
      human relationship claims.
- [x] Always marks posting/sending as human approval required.

**Verification:**
- [x] Policy test added in Task 8.

**Dependencies:** Task 1

**Files likely touched:**
- `.agents/skills/virtual-creator-compliance-check/SKILL.md`

**Estimated scope:** Small

## Task 5: Add Revenue Ops Driver

**Description:** Add `src/system/revenue-ops.sh` as the CLI front door.

**Acceptance criteria:**
- [x] Supports `scan`, `content-calendar`, `compliance-check`, `analytics`,
      and `report`.
- [x] Writes local reports only.
- [x] Has no send/post/delete/account actions.

**Verification:**
- [x] `bash -n src/system/revenue-ops.sh`
- [x] `src/system/revenue-ops.sh --help`

**Dependencies:** Tasks 1-4

**Files likely touched:**
- `src/system/revenue-ops.sh`

**Estimated scope:** Medium

## Task 6: Add Analytics Ledger

**Description:** Store manual/API-imported metrics in JSONL.

**Acceptance criteria:**
- [x] Creates `.hermes/reports/revenue/virtual-creator/`.
- [x] Writes analytics JSONL with post metrics fields.
- [x] Does not require platform credentials.

**Verification:**
- [x] Run analytics command with sample input.

**Dependencies:** Task 5

**Files likely touched:**
- `src/system/revenue-ops.sh`

**Estimated scope:** Medium

## Task 7: Add Boundary Tests

**Description:** Add shell tests proving unsafe actions remain human-only.

**Acceptance criteria:**
- [x] `tests/test_virtual_creator_policy.sh` exists.
- [x] Tests validate YOLO retrieval approval.
- [x] Tests validate send/post/delete/security actions remain blocked or
      human-required.

**Verification:**
- [x] `bash tests/test_virtual_creator_policy.sh`

**Dependencies:** Tasks 4-5

**Files likely touched:**
- `tests/test_virtual_creator_policy.sh`

**Estimated scope:** Small

## Task 8: Add Promptfoo Eval

**Description:** Add a promptfoo eval for virtual creator compliance and content
quality.

**Acceptance criteria:**
- [x] Eval rejects hidden AI identity.
- [x] Eval rejects unsupported income claims.
- [x] Eval accepts compliant disclosed virtual brand content.

**Verification:**
- [x] `src/system/promptfoo-evals.sh check`

**Dependencies:** Task 4

**Files likely touched:**
- `promptfoo/evals/virtual-creator-policy.yaml`

**Estimated scope:** Medium

