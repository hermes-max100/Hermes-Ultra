#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="$ROOT_DIR/src/system/skills.sh"
ROUTER_V1="$ROOT_DIR/src/system/skill-router.sh"
ROUTER_V3="$ROOT_DIR/src/system/skill-router-v3.sh"
SNAPSHOT="$ROOT_DIR/src/system/score-snapshot.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_SKILLS_HOME="$TMP_DIR/.skills"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

copy_seed_skill() {
  local skill="$1"
  mkdir -p "$HERMES_SKILLS_HOME/skills.d/$skill"
  cp "$ROOT_DIR/.skills/skills.d/$skill/"* "$HERMES_SKILLS_HOME/skills.d/$skill/"
  "$SKILLS" add "$skill" >/dev/null
}

"$ROUTER_V1" init >/dev/null
for skill in \
  legal-evidence-os \
  document-intelligence \
  appellate-filing-red-team \
  citation-integrity-checker \
  contradiction-ledger \
  agentic-coding-router \
  bash-script-hardener \
  nim-model-router; do
  copy_seed_skill "$skill"
done

mkdir -p "$HERMES_SKILLS_HOME/projects/amazon-appeal"
cp "$ROOT_DIR/.skills/projects/amazon-appeal/profile.md" "$HERMES_SKILLS_HOME/projects/amazon-appeal/profile.md"
cp "$ROOT_DIR/.skills/projects/amazon-appeal/active-skills.txt" "$HERMES_SKILLS_HOME/projects/amazon-appeal/active-skills.txt"

find_output="$("$ROUTER_V3" find "red team this appeal filing and build evidence matrix from PDFs")"
assert_contains "$find_output" "legal-evidence-os"
assert_contains "$find_output" "score="
assert_contains "$find_output" "pointwise="

project_output="$("$ROUTER_V3" project amazon-appeal "find contradictions in the investigation timeline")"
assert_contains "$project_output" "contradiction-ledger"
assert_contains "$project_output" "legal-evidence-os"

explain_output="$("$ROUTER_V3" explain "appeal filing contradiction")"
assert_contains "$explain_output" "LISTWISE"
assert_contains "$explain_output" "POINTWISE"
assert_contains "$explain_output" "PROJECT"

"$ROUTER_V1" log amazon-appeal legal-evidence-os success "Correctly selected." >/dev/null
"$ROUTER_V1" log amazon-appeal legal-evidence-os failure "Missed service trigger." >/dev/null
"$ROUTER_V1" log amazon-appeal contradiction-ledger partial "Needed stronger timeline terms." >/dev/null

"$SNAPSHOT" --rubric structural-v1 >/dev/null
cat >> "$HERMES_SKILLS_HOME/logs/score-snapshots.jsonl" <<'JSONL'
{"ts":"2026-07-06T00:00:00Z","skill":"legal-evidence-os","rubric":"structural-v1","score":70}
{"ts":"2026-07-06T00:00:00Z","skill":"contradiction-ledger","rubric":"structural-v1","score":96}
JSONL

dashboard_output="$("$ROUTER_V3" dashboard)"
assert_contains "$dashboard_output" "Skill Evolution Dashboard"
assert_contains "$dashboard_output" "legal-evidence-os"
assert_contains "$dashboard_output" "Rubric Drift Detection"
assert_contains "$dashboard_output" "Evolution Pressure"
assert_contains "$dashboard_output" "Per-Project Routing Accuracy"

csv_path="$TMP_DIR/dashboard.csv"
"$ROUTER_V3" dashboard --csv "$csv_path" >/dev/null
[[ -f "$csv_path" ]]
assert_contains "$(cat "$csv_path")" "skill,version,risk_level,total,success"
assert_contains "$(cat "$csv_path")" "drift_delta"

snapshot_output="$("$ROUTER_V3" snapshot --rubric test-rubric)"
assert_contains "$snapshot_output" "snapshots="

echo "skill-router-v3 tests passed"
