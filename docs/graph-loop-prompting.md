# Graph Loop Prompting

A graph loop that drafts prompts, has an independent context score them, and admits a prompt to the library only through a deterministic gate. Model workers draft and score. `src/system/prompt_gate.py` alone decides promotion and re-derives every verdict from the prompt text and scorecard.

## Status

Rubric `0.1.0` is **pending sign-off** (`config/prompt-rubric.json` → `"status": "pending_signoff"`). `promote` refuses every entry until the status is set to `signed_off`. That sign-off gate is enforced in code, not just stated in a doc.

## Loop

```text
N0 seed ─▶ N1 draft ─▶ N2 audit (lint G1–G5) ─▶ N3 score (independent context) ─▶ N4 gate (evaluate)
                ▲                                                               │
                │                         PASS ─▶ N7 promote (sole library writer)
                │                         REVISE / BLOCK_* ─▶ guard
                └── N5 revise ◀── revise ─────────────────────────────────────┤
                    N6 diagnose ◀── diagnose (strategy must change) ───────────┤
                    escalate to human ◀── escalate ────────────────────────────┘
INVALID scorecard ─▶ rescore (never edit the prompt for a broken scorecard)
N9 regression: `stale` lists entries scored under an older rubric version
```

## Promotion rule

All gates green **and** min(dimension) ≥ 9.0 **and** weighted ≥ 9.5. All arithmetic is integer: tenths × weight-hundredths = thousandths. The floor and bar comparisons are exact.

## Guard (one node)

| History | Action |
|---|---|
| initial draft failed | revise (1) |
| 1 failed revision | revise (2) |
| 2 failed revisions | diagnose → revision 3 must use a strategy not used before |
| 3 failed revisions, or a post-diagnose revision that reused a strategy | escalate with last good state + all verdicts |

## Changes from rubric v0 (and why)

1. **The escalation rule was unreachable.** v0 said "2nd forced strategy change → escalate" with a cap of 3 revisions. A 2nd strategy change needs a 4th failed revision, so the cap always fired first. v1 escalates at the cap and adds one more escalation trigger: a post-diagnose revision that reuses an earlier strategy.
2. **Two nodes claimed to be the only library writer.** v0 named N4 in one place and N7 in another. Now N4 only emits a verdict and N7 is the only writer.
3. **Float math wrongly blocked prompts that met the bar.** The v0 simulator compared `weighted >= 9.5` in floating point. Of 7,476 sampled scorecards that land exactly on 9.5, 1,566 (21%) evaluate to 9.4999… and were wrongly blocked. Example: `[9.2, 9.5, 9.4, 9.5, 9.2, 9.6, 10.0, 9.8, 9.3, 9.9]`. A regression test now covers it.
4. **Nothing stopped a context from scoring its own draft.** v0's anti-inflation rule relied on the scorer's honesty. A scorecard now must name both `drafter_context_id` and `scorer_context_id`, and they must differ. It must carry the `content_sha256` of the exact text it scored (so a score can't be reused on a different text) and the current `rubric_version` (so a score made under an old rubric is rejected).
5. **Gates G1–G5 are checked mechanically.** Required headings with non-empty bodies cover G1–G4, and a banned-phrase list covers G5. The scorer judges quality only. A mechanical gate is necessary but not sufficient, which is why scoring still exists.

## Files

- `config/prompt-rubric.json`: gates, weights, floor, bar, cap, guard limits, sign-off status.
- `src/system/prompt_gate.py`: lint, evaluate, guard, promote, rollback, stale.
- `src/system/prompt-gate.sh`: CLI wrapper.
- `prompt-library/node-templates/`: draft, score, and revise/diagnose node prompts. Each passes its own gates, and the tests enforce that.
- `prompt-library/index.json`, `entries/<slug>/v<N>.md`, `evidence/<slug>/v<N>.scorecard.json`: created by `promote`.
- `tests/test_prompt_gate.py`, `tests/test_prompt_gate.sh`.

## Commands

```bash
src/system/prompt-gate.sh check-rubric
src/system/prompt-gate.sh lint     --prompt cand.md
src/system/prompt-gate.sh hash     --prompt cand.md
src/system/prompt-gate.sh evaluate --prompt cand.md --scorecard card.json
src/system/prompt-gate.sh guard    --history history.json
src/system/prompt-gate.sh promote  --prompt cand.md --scorecard card.json --slug my-prompt
src/system/prompt-gate.sh rollback --slug my-prompt
src/system/prompt-gate.sh stale
```

Exit codes: 0 means pass or success, 1 means a non-passing verdict, a refusal, or an escalation, and 2 means invalid input.

## Rollback and idempotence

`promote` skips the write when the current version already has the same content hash. Every promote writes a new `v<N>` file with a `parent` pointer, and nothing is ever overwritten. `rollback` repoints `current` to the parent version and deletes nothing.

## Open decisions (owner: Carmelo)

1. Sign off on, or amend, the weights, the gates, the 9.0 floor, and the 9.5 bar.
2. Should the library hold specifications or task-execution prompts? If it holds task-execution prompts, add a `reusability` dimension. The weights must still sum to 100, which the gate enforces.
3. Seed source: no prompt library existed before this. Name the first seed objectives, or point to an existing corpus to audit.
