#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVER="$ROOT_DIR/src/system/revenue-ops.sh"
GATE="$ROOT_DIR/src/system/yolo-gate.sh"
PROFILE="$ROOT_DIR/config/virtual-creator-profile.example.json"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_REVENUE_REPORT_DIR="$TMP_DIR/reports"
export HERMES_CLOUD_KEYS_FILE="$TMP_DIR/empty-cloud-models.env"
: > "$HERMES_CLOUD_KEYS_FILE"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

assert_file() {
  test -f "$1" || {
    echo "Expected file to exist: $1" >&2
    exit 1
  }
}

chmod +x "$DRIVER" "$GATE"

python3 -m json.tool "$PROFILE" >/dev/null

assert_file "$ROOT_DIR/.agents/skills/virtual-creator-trend-scanner/SKILL.md"
assert_file "$ROOT_DIR/.agents/skills/virtual-creator-content-planner/SKILL.md"
assert_file "$ROOT_DIR/.agents/skills/virtual-creator-compliance-check/SKILL.md"
assert_file "$ROOT_DIR/.skills/skills.d/virtual-creator-trend-scanner/SKILL.md"
assert_file "$ROOT_DIR/.skills/skills.d/virtual-creator-content-planner/SKILL.md"
assert_file "$ROOT_DIR/.skills/skills.d/virtual-creator-compliance-check/SKILL.md"

bash -n "$DRIVER"
help_output="$("$DRIVER" --help)"
assert_contains "$help_output" "scan"
assert_contains "$help_output" "content-calendar"
assert_contains "$help_output" "compliance-check"
assert_contains "$help_output" "analytics"
assert_contains "$help_output" "report"

scan_output="$("$DRIVER" scan)"
assert_contains "$scan_output" "trend-scan"
scan_report="${scan_output#report=}"
assert_file "$scan_report"
assert_contains "$(cat "$scan_report")" "No posting, messaging, liking, following"

package_output="$("$DRIVER" package)"
assert_file "${package_output#report=}"

calendar_output="$("$DRIVER" content-calendar --days 3)"
calendar_report="${calendar_output#report=}"
assert_file "$calendar_report"
assert_contains "$(cat "$calendar_report")" "AI-generated creator media disclosed"
assert_contains "$(cat "$calendar_report")" "human before post"

safe_output="$("$DRIVER" compliance-check --text "AI-generated virtual creator shares a practical checklist for missed quote follow-up automation.")"
assert_contains "$safe_output" '"decision": "pass"'
assert_contains "$safe_output" '"approval_required": true'

hidden_output="$("$DRIVER" compliance-check --text "Nobody knows she is AI. Make her look 100% real and pretend she is a real girl.")"
assert_contains "$hidden_output" '"decision": "block"'
assert_contains "$hidden_output" "hidden synthetic identity"

income_output="$("$DRIVER" compliance-check --text 'AI-generated virtual creator: guaranteed $3,000 per month for every local service business.')"
assert_contains "$income_output" '"decision": "block"'
assert_contains "$income_output" "fake earnings claim"

analytics_output="$("$DRIVER" analytics --platform instagram --topic "missed leads" --format reel --views 100 --likes 9 --comments 2 --saves 3 --profile-clicks 4 --link-clicks 1 --leads 1 --sales 0 --cost-usd 0)"
assert_contains "$analytics_output" '"platform": "instagram"'
assert_contains "$analytics_output" '"leads": 1'
assert_file "$HERMES_REVENUE_REPORT_DIR/virtual-creator/analytics.jsonl"

report_output="$("$DRIVER" report)"
assert_file "${report_output#report=}"

retrieval_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "scan public GitHub Reddit and X trends for virtual creator opportunities")"
assert_contains "$retrieval_output" "decision=model_approved"
assert_contains "$retrieval_output" "class=public_retrieval_gate"

send_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "post the virtual creator content now")"
assert_contains "$send_output" "decision=human_required"

delete_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "delete poor performing posts and change account security settings")"
assert_contains "$delete_output" "decision=human_required"

echo "virtual creator policy tests passed"
