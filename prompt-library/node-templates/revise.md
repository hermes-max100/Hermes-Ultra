# N5 revise / N6 diagnose — targeted repair

## Objective
Raise a failed candidate to the bar by changing only what the verdict names. Do not rewrite it from scratch.

## Inputs
- `CANDIDATE`: the failed prompt text.
- `VERDICT`: the JSON from `src/system/prompt-gate.sh evaluate`.
- `GUARD`: the JSON from `src/system/prompt-gate.sh guard --history <file>`.

## Procedure
1. Act on `GUARD.action`:
   - `revise`: make a minimal diff against `VERDICT.weakest`, or against the failed gates when the status is `BLOCK_GATE`.
   - `diagnose`: write two lines first. Expected: what the last strategy should have fixed. Observed: what the scorer still flagged. Then choose a strategy that differs from every strategy in the history. A reused strategy escalates.
   - `escalate`: do not edit. Emit the escalation record described under "Failure and stop".
2. Leave every section the verdict did not flag untouched.
3. Record a one-line `strategy` string for the history file.

## Definition of done
A new candidate that differs from `CANDIDATE` only in the flagged areas, with a new history entry that names its strategy.

## Evidence
A unified diff between `CANDIDATE` and the new candidate.

## Failure and stop
On `escalate`, emit the last candidate that passed lint, every verdict in the history, and the single missing item that blocks the bar. Then stop.

## Assumptions
- ASSUMED: the verdict comes from an independent scorer. If `VERDICT.status` is `INVALID`, the scorecard is broken, not the prompt. Route to re-scoring and do not edit.
