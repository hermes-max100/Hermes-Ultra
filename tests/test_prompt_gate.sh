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
python3 -m unittest -v "$ROOT_DIR/tests/test_prompt_gate.py"

# Node templates must pass the gates they enforce.
for template in "$ROOT_DIR"/prompt-library/node-templates/*.md; do
  "$GATE" lint --prompt "$template" >/dev/null || { echo "gate failure: $template" >&2; exit 1; }
done

# The shipped rubric is unsigned, so promotion must be refused end to end.
cp "$ROOT_DIR/prompt-library/node-templates/score.md" "$TMP_DIR/cand.md"
python3 - "$ROOT_DIR/config/prompt-rubric.json" "$TMP_DIR/cand.md" "$TMP_DIR/card.json" <<'PY'
import hashlib, json, sys
rubric = json.load(open(sys.argv[1], encoding="utf-8"))
text = open(sys.argv[2], encoding="utf-8").read()
card = {
    "rubric_version": rubric["version"],
    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "drafter_context_id": "d",
    "scorer_context_id": "s",
    "scores": {d["id"]: {"score": 9.6, "justification": "fixture", "evidence": "fixture"} for d in rubric["dimensions"]},
}
json.dump(card, open(sys.argv[3], "w", encoding="utf-8"))
PY
"$GATE" evaluate --prompt "$TMP_DIR/cand.md" --scorecard "$TMP_DIR/card.json" | grep -q '"status": "PASS"'
if "$GATE" promote --prompt "$TMP_DIR/cand.md" --scorecard "$TMP_DIR/card.json" \
    --slug fixture --library "$TMP_DIR/lib" > "$TMP_DIR/promote.out"; then
  echo "promotion succeeded against an unsigned rubric" >&2
  exit 1
fi
grep -q 'pending_signoff' "$TMP_DIR/promote.out"
test ! -e "$TMP_DIR/lib/index.json"

echo "PROMPT_GATE_TESTS=PASS"
