# Calibration run — rubric 0.1.0

Blind scorers, each in a separate context. `strong.md` is a frozen snapshot of `node-templates/draft.md` as scored. The live template may change. Each scorecard's `content_sha256` binds it to that exact text.

Re-verify any card with:

    src/system/prompt-gate.sh evaluate --prompt prompt-library/calibration/rubric-0.1.0/weak.md \
      --scorecard prompt-library/calibration/rubric-0.1.0/card-weak-A.json

`outsider.md` is the S4 seed: substantive, in a different vocabulary. It fails G1–G4 at lint, so it was not scored.
