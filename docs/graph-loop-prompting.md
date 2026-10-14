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
3. **Float math made the verdict depend on dimension order.** The v0 simulator compared a float sum against 9.5. For a scorecard whose exact total is 9.5, the float total can land just below or just above 9.5, and which side it lands on depends on the order the dimensions are added. Example: `[9.2, 9.5, 9.4, 9.5, 9.2, 9.6, 10.0, 9.8, 9.3, 9.9]` comes out at 9.4999… (blocked) in the shipped order and in weight-descending order, but passes in weight-ascending order. Across random orders, about 22% of float sums for this case come out below 9.5. Reordering the `dimensions` array, which looks cosmetic, would therefore silently change verdicts. The hazard also depends on the Python version. From 3.12, the built-in `sum()` over floats uses compensated summation and returns exactly 9.5 for this case. On 3.10 and 3.11, which `requires-python` still allows, `sum()` is naive and returns 9.4999…. Mutation testing showed this directly: a float `sum()` mutant of the gate is caught on 3.11 and survives on 3.13, which is why CI runs on both 3.11 and 3.12. The gate sums integers, so its total is exact, independent of order, and independent of the Python version. A test asserts this across shipped, reversed, weight-sorted and alphabetical orders, and also asserts that float sums of the same case disagree.
4. **Nothing stopped a context from scoring its own draft.** v0's anti-inflation rule relied on the scorer's honesty. A scorecard now must name both `drafter_context_id` and `scorer_context_id`, and they must differ. It must carry the `content_sha256` of the exact text it scored (so a score can't be reused on a different text) and the current `rubric_version` (so a score made under an old rubric is rejected).
5. **Gates G1–G5 are checked mechanically.** G1–G4 check for required headings with non-empty bodies, and G5 checks a list of banned phrases. The gate list is data-driven: adding a gate to `config/prompt-rubric.json` changes behaviour with no code change. `check-rubric` rejects a gate that declares no check, has an unknown key (a typo such as `required_headng` would otherwise always pass), or has an empty check value.

## What the gates do and do not measure

G1–G4 enforce a **heading schema**, not substance. Two pinned tests characterise this:
- A prompt with the same content written under other headings ("Success criteria", "If things go wrong", "Proof required") fails G1–G4 and is vetoed before scoring.
- A prompt with vague bodies ("TBD, use judgment.") under the house headings passes every gate.

Substance is judged only by the independent scorer. Treat a gate pass as "the prompt is parseable in the house format". It is not evidence that the prompt is good.

## Calibration evidence (rubric 0.1.0)

Four blind scorers, each in its own context. Each candidate was scored twice to measure variance.

| Candidate | Scorer | Weighted | Min | Verdict |
|---|---|---|---|---|
| weak: passes all gates, vague bodies | A | 1.565 | 0.5 | BLOCK_FLOOR |
| weak | B | 1.755 | 0.5 | BLOCK_FLOOR |
| strong: `draft.md` node template (frozen copy) | A | 9.331 | 8.8 | BLOCK_FLOOR |
| strong | B | 9.351 | 8.8 | BLOCK_FLOOR |

- The two scorers on the strong candidate differ by at most 0.2 on any dimension. On the weak candidate they differ by at most 1.0, and only on dimensions scored 0.5–6.0.
- Both strong-candidate scorers independently set idempotence to 8.8, for the same reason: the template does not say what happens when it is rerun on the same seed. The floor blocked a high average because of one real weak axis, which is what it was designed to do.
- Limitations: n = 2 per candidate, one model family, and no candidate near the 9.5 bar. This shows that the scorer separates good from bad. It does not yet show that the scorer is precise around the bar.

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

## Mutation coverage

`tests/test_prompt_gate.py` kills 14 of 14 mutants on Python 3.11. They cover the floor, the cap boundary, the rollback pointer, slug validation, stale detection, the parent chain, the bar comparison, self-scoring, sign-off, diagnose, duplicate skip, check-less gates, and float accumulation in both its loop and `sum()` forms. On 3.12+, the `sum()` float mutant survives because compensated summation makes it equivalent in practice. The 3.11 CI leg catches it.

## Open decisions (owner: Carmelo)

1. Sign off on, or amend, the weights, the gates, the 9.0 floor, and the 9.5 bar.
2. Should the library hold specifications or task-execution prompts? If it holds task-execution prompts, add a `reusability` dimension. The weights must still sum to 100, which the gate enforces.
3. Seed source: no prompt library existed before this. Name the first seed objectives, or point to an existing corpus to audit.
4. **Gate vocabulary.** G1–G4 veto a substantive prompt written in other words (S4). The options are (a) keep the heading schema as a deliberate format contract and add a normalisation step in N1 that maps outside headings onto it, or (b) add per-gate synonym lists, which is still lexical, just a larger vocabulary. Recommendation: (a). Parseability is the point of a library, and substance belongs to the scorer.
5. **`signed_off_by` semantics.** A free-text name proves nothing. Recommendation: sign-off is a signed git commit that flips `status`, and `check-rubric` verifies the signature against an allowlisted key fingerprint. This needs your signing key's fingerprint.
6. **Lifecycle.** Neither quarantine (N8) nor a `retired` state exists in code yet. Today the library only versions entries; it has no state field. Recommendation: add `status: active | retired` per entry, with retire as a pointer change like rollback, so nothing is ever deleted.
