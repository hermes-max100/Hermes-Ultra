# N1 draft — candidate prompt author

## Objective
Write one self-contained candidate prompt from a seed record. If this is a loop iteration, apply a revision diff to the prior candidate instead.

## Inputs
- `SEED`: an objective plus its success criteria. Reject a seed with no stated definition of done (N0 guard).
- `PRIOR` (optional): the previous candidate, plus the verdict JSON that failed it.

## Required sections
The candidate must contain these headings, each with a non-empty body:
- `## Objective`
- `## Definition of done`
- `## Failure and stop` (or a heading that contains that phrase)
- `## Evidence`
- `## Assumptions`: label every assumption `ASSUMED:` so a reader can tell it apart from a stated fact.

## Constraints
- Zero prior context. The candidate must not refer to conversation history or to anything else the executing agent cannot see. The banned phrases are listed under gate G5 in `config/prompt-rubric.json`.
- Write to staging only (`prompt-library/seeds/` or a temp path). You have no library write scope.
- Prefer one precise sentence over three approximate ones. Token economy is scored.

## Definition of done
`src/system/prompt-gate.sh lint --prompt <candidate>` exits 0.

## Evidence
The lint JSON output for the candidate.

## Failure and stop
- Seed has no definition of done: stop and report `seed rejected: no definition of done`.
- Lint fails twice on the same gate: stop and report the gate id and its reason. Do not loop.

## Assumptions
- ASSUMED: the executing agent has tool access equivalent to the seed's stated environment. If the seed names no environment, the candidate must state one under Assumptions.
