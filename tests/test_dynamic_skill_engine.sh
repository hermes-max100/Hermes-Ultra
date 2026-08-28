#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="$ROOT_DIR/src/system/skills.sh"
ROUTER="$ROOT_DIR/src/system/skill-router.sh"
EVOLVER="$ROOT_DIR/src/system/skill-evolver.sh"
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

"$ROUTER" init >/dev/null
copy_seed_skill legal-evidence-os
copy_seed_skill document-intelligence
copy_seed_skill appellate-filing-red-team
copy_seed_skill contradiction-ledger
copy_seed_skill agentic-coding-router
copy_seed_skill bash-script-hardener
copy_seed_skill nim-model-router

mkdir -p "$HERMES_SKILLS_HOME/projects/amazon-appeal"
cp "$ROOT_DIR/.skills/projects/amazon-appeal/profile.md" "$HERMES_SKILLS_HOME/projects/amazon-appeal/profile.md"
cp "$ROOT_DIR/.skills/projects/amazon-appeal/active-skills.txt" "$HERMES_SKILLS_HOME/projects/amazon-appeal/active-skills.txt"

"$SKILLS" validate >/dev/null

legal_output="$("$ROUTER" find "red team this appeal filing and build evidence matrix from PDFs")"
assert_contains "$legal_output" "legal-evidence-os"
assert_contains "$legal_output" "document-intelligence"

project_output="$("$ROUTER" project amazon-appeal "find contradictions in the investigation timeline")"
assert_contains "$project_output" "contradiction-ledger"
assert_contains "$project_output" "legal-evidence-os"

bundle_output="$("$ROUTER" bundle amazon-appeal --limit 3 "find contradictions in the investigation timeline")"
assert_contains "$bundle_output" "Skill Context Bundle"
assert_contains "$bundle_output" "Selected Skills"
assert_contains "$bundle_output" "Execution Instructions"

code_output="$("$ROUTER" find "harden this bash script and fix the failing test")"
assert_contains "$code_output" "bash-script-hardener"
assert_contains "$code_output" "agentic-coding-router"

"$ROUTER" log amazon-appeal legal-evidence-os failure "Missed service deadline and record designation trigger terms." >/dev/null
scan_output="$("$EVOLVER" scan amazon-appeal)"
assert_contains "$scan_output" "legal-evidence-os"

proposal_output="$("$EVOLVER" propose amazon-appeal)"
assert_contains "$proposal_output" "proposal created"
proposal_id="$("$EVOLVER" list-proposals | head -n 1)"
show_output="$("$EVOLVER" show-proposal "$proposal_id")"
assert_contains "$show_output" "Skill Evolution Proposal"
promote_output="$("$EVOLVER" promote "$proposal_id")"
assert_contains "$promote_output" "promoted"
assert_contains "$(cat "$HERMES_SKILLS_HOME/skills.d/legal-evidence-os/meta.env")" "service"
assert_contains "$(cat "$HERMES_SKILLS_HOME/skills.d/legal-evidence-os/changelog.md")" "$proposal_id"

v3_output="$("$ROUTER_V3" find "red team this appeal filing and build evidence matrix from PDFs")"
assert_contains "$v3_output" "legal-evidence-os"
assert_contains "$v3_output" "pointwise="

snapshot_output="$("$SNAPSHOT")"
assert_contains "$snapshot_output" "legal-evidence-os"
assert_contains "$snapshot_output" "snapshots="

echo "dynamic-skill-engine tests passed"
