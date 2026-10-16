#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$ROOT_DIR/src/system/prompt-gate.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 -m py_compile "$ROOT_DIR/src/system/prompt_gate.py"
bash -n "$GATE"
python3 -m json.tool "$ROOT_DIR/config/prompt-rubric.json" >/dev/null
"$GATE" check-rubric >/dev/null
python3 -m unittest -v "$ROOT_DIR/tests/test_prompt_gate.py"  # CI pytest discovers the rest of tests/

json_field() {  # json_field FILE KEY -> prints value; parses JSON instead of grepping its formatting
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

# Node templates must pass the gates they enforce, and a missing template must not shrink the loop silently.
shopt -s nullglob
templates=("$ROOT_DIR"/prompt-library/node-templates/*.md)
shopt -u nullglob
if (( ${#templates[@]} < 3 )); then
  echo "expected at least 3 node templates, found ${#templates[@]}" >&2
  exit 1
fi
for template in "${templates[@]}"; do
  "$GATE" lint --prompt "$template" >/dev/null || { echo "gate failure: $template" >&2; exit 1; }
done

# End-to-end promote against the rubric as shipped. Valid in both sign-off states,
# so the commit that signs the rubric does not turn this gate red.
cp "$ROOT_DIR/prompt-library/node-templates/score.md" "$TMP_DIR/cand.md"
python3 - "$ROOT_DIR/config/prompt-rubric.json" "$TMP_DIR/cand.md" "$TMP_DIR/card.json" <<'PY'
import hashlib, json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    rubric = json.load(fh)
with open(sys.argv[2], encoding="utf-8") as fh:
    text = fh.read()
card = {
    "rubric_version": rubric["version"],
    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "drafter_context_id": "d",
    "scorer_context_id": "s",
    "scores": {d["id"]: {"score": 9.6, "justification": "fixture", "evidence": "fixture"} for d in rubric["dimensions"]},
}
with open(sys.argv[3], "w", encoding="utf-8") as fh:
    json.dump(card, fh)
PY
"$GATE" evaluate --prompt "$TMP_DIR/cand.md" --scorecard "$TMP_DIR/card.json" > "$TMP_DIR/eval.out"
test "$(json_field "$TMP_DIR/eval.out" status)" = PASS

"$GATE" check-rubric > "$TMP_DIR/rubric.out"
signoff="$(json_field "$TMP_DIR/rubric.out" signoff)"
set +e
"$GATE" promote --prompt "$TMP_DIR/cand.md" --scorecard "$TMP_DIR/card.json" \
  --slug fixture --library "$TMP_DIR/lib" > "$TMP_DIR/promote.out"
promote_rc=$?
set -e
promote_status="$(json_field "$TMP_DIR/promote.out" status)"
if [[ "$signoff" == signed_off ]]; then
  # Signed: either the binding holds and it promotes, or the rubric was edited after signing.
  if [[ "$promote_status" == promoted ]]; then
    test "$promote_rc" -eq 0 && test -e "$TMP_DIR/lib/index.json"
  else
    test "$(json_field "$TMP_DIR/promote.out" cause)" = signoff_fingerprint_mismatch
    echo "rubric is signed_off but its fingerprint no longer matches; re-sign before merging" >&2
    exit 1
  fi
else
  test "$promote_rc" -eq 1 && test "$promote_status" = refused
  test "$(json_field "$TMP_DIR/promote.out" cause)" = unsigned
  test ! -e "$TMP_DIR/lib"
fi

echo "PROMPT_GATE_TESTS=PASS"
