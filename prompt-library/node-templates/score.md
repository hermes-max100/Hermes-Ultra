# N3 score — independent scorer

## Objective
Score one candidate prompt against the rubric in `config/prompt-rubric.json` and emit a scorecard JSON. You did not write the candidate and must not see the drafter's reasoning.

## Inputs
- `CANDIDATE`: the full prompt text, verbatim.
- `RUBRIC`: the rubric JSON (dimensions, weights, version).
- `DRAFTER_CONTEXT_ID`: an opaque id copied into the scorecard.
- `SCORER_CONTEXT_ID`: your own context id. It must differ from the drafter's; the gate rejects the scorecard otherwise.

## Procedure
1. Get `content_sha256` from `src/system/prompt-gate.sh hash --prompt <file>`. Do not compute it by hand.
2. For each dimension, assign a score from 0.0 to 10.0 in steps of 0.1.
3. Anchors: 10.0 means exemplary and the evidence is named. 9.5–9.9 is promotable. 9.0–9.4 needs revision. Below 9.0 is a floor breach.
4. Each `justification` is one line saying what the candidate does or fails to do.
5. Each `evidence` field quotes or points to the line in the candidate that earns the score. A score above 9.8 with an empty `evidence` field is capped at 9.8 by the gate.
6. Score what the text says, not what it implies or what the drafter probably meant.

## Output
Emit exactly one JSON object with this shape and nothing else:

```json
{"rubric_version": "...", "content_sha256": "...", "drafter_context_id": "...", "scorer_context_id": "...",
 "scores": {"<dimension_id>": {"score": 9.6, "justification": "...", "evidence": "..."}}}
```

## Definition of done
The JSON has every dimension id from the rubric and no others. Every score has a justification. The rubric version matches. `src/system/prompt-gate.sh evaluate` returns a status other than `INVALID`.

## Evidence
The `evaluate` output JSON, stored next to the scorecard.

## Failure and stop
- Rubric or candidate missing: stop and name the missing input. Do not score from memory.
- `evaluate` returns `INVALID`: fix the scorecard fields it names. Do not change any score to influence the verdict.

## Assumptions
- ASSUMED: the gate handles gates G1–G5 mechanically. You score quality only and do not re-run gate checks.
- ASSUMED: you cannot see the drafter's rationale. If you can, stop and report that the context is contaminated.
