#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVOLVER="$ROOT_DIR/src/system/skill-evolver.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

skills_home="$TMP_DIR/.skills"
skills_dir="$skills_home/skills.d/legal-evidence-os"
mkdir -p "$skills_dir" "$skills_home/logs"
cat > "$skills_home/skills.txt" <<'EOF'
legal-evidence-os
EOF
cat > "$skills_dir/meta.env" <<'EOF'
NAME="legal-evidence-os"
VERSION="0.1.0"
DESCRIPTION="Legal evidence chronology and litigation records review."
TAGS="legal evidence litigation chronology records"
TRIGGERS="legal evidence chronology"
INPUTS="pdf email transcript"
OUTPUTS="chronology evidence-matrix"
RISK_LEVEL="high"
EOF
cat > "$skills_dir/SKILL.md" <<'EOF'
# legal-evidence-os

Use for legal evidence review and chronology work.
EOF
cat > "$skills_dir/changelog.md" <<'EOF'
# changelog
EOF
cat > "$skills_home/logs/skill-events.jsonl" <<'EOF'
{"ts":"2026-07-21T00:00:00Z","project":"amazon-appeal","skill":"legal-evidence-os","outcome":"failure","note":"Missed deadline service record designation terms"}
EOF

env_args=(
  HERMES_SKILLS_HOME="$skills_home"
  LOG_FILE="$skills_home/logs/skill-events.jsonl"
  PROPOSALS_DIR="$TMP_DIR/proposals"
  BACKUPS_DIR="$TMP_DIR/backups"
)

propose_output="$(env "${env_args[@]}" "$EVOLVER" propose amazon-appeal)"
assert_contains "$propose_output" "proposal created:"
proposal_id="$(printf '%s\n' "$propose_output" | awk '/proposal created:/ {print $3; exit}')"

validate_output="$(env "${env_args[@]}" "$EVOLVER" validate-proposal "$proposal_id")"
assert_contains "$validate_output" "validation passed:"

promote_output="$(env "${env_args[@]}" "$EVOLVER" promote "$proposal_id")"
assert_contains "$promote_output" "promoted:"
assert_contains "$(cat "$skills_dir/meta.env")" "deadline"
assert_contains "$(cat "$skills_dir/meta.env")" "VERSION=\"0.1.1\""
assert_contains "$(cat "$TMP_DIR/proposals/$proposal_id/proposal.env")" "STATUS=\"promoted\""

echo "skill evolver validation tests passed"
