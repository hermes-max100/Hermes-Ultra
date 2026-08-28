#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEDGER="$ROOT_DIR/src/system/revenue-ledger.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_REVENUE_OS_DIR="$TMP_DIR/revenue-os"
export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

init_output="$("$LEDGER" init)"
assert_contains "$init_output" "revenue-events.jsonl"
test -f "$HERMES_REVENUE_OS_DIR/revenue-events.jsonl"
test -f "$HERMES_REVENUE_OS_DIR/opportunities.jsonl"

lead_output="$("$LEDGER" record-event \
  --experiment-id exp_ai_services_001 \
  --workflow-id wf_public_audit \
  --offer-id ai-followup-setup \
  --channel manual \
  --campaign seed-test \
  --asset-id audit-template-v1 \
  --lead-id lead_001 \
  --event-type lead \
  --leads 1 \
  --qualified-leads 1 \
  --notes "manual test lead")"
assert_contains "$lead_output" '"experiment_id": "exp_ai_services_001"'
assert_contains "$lead_output" '"memory_status": "persisted"'

conversion_output="$("$LEDGER" record-event \
  --experiment-id exp_ai_services_001 \
  --workflow-id wf_public_audit \
  --offer-id ai-followup-setup \
  --channel manual \
  --campaign seed-test \
  --lead-id lead_001 \
  --customer-id customer_001 \
  --event-type conversion \
  --conversions 1 \
  --gross-revenue 497 \
  --platform-fees 15 \
  --ai-api-cost 2 \
  --other-cost 20)"
assert_contains "$conversion_output" '"profit": 460.0'

if "$LEDGER" record-event --experiment-id exp_bad --event-type manual_note --action send >/tmp/revenue-ledger-send.out 2>&1; then
  echo "send action should require human approval" >&2
  exit 1
fi
assert_contains "$(cat /tmp/revenue-ledger-send.out)" "action requires human approval"

approved_send_output="$("$LEDGER" record-event --experiment-id exp_draft --event-type outreach_draft --action send --human-approved --notes "approved send handoff")"
assert_contains "$approved_send_output" '"human_approved": true'

opp_a="$("$LEDGER" record-opportunity \
  --business-model "AI service setup" \
  --customer "local service businesses" \
  --problem "missed inbound lead follow-up" \
  --offer "lead capture and follow-up automation setup" \
  --channel "manual/public research" \
  --probability-of-conversion 0.08 \
  --expected-profit 900 \
  --automation-fit 0.8 \
  --time-to-revenue-days 7 \
  --startup-cost 0 \
  --confidence 0.7)"
assert_contains "$opp_a" '"memory_status": "persisted"'

"$LEDGER" record-opportunity \
  --business-model "content monetization" \
  --customer "general audience" \
  --problem "low content engagement" \
  --offer "virtual creator content" \
  --channel "social" \
  --probability-of-conversion 0.01 \
  --expected-profit 50 \
  --automation-fit 0.6 \
  --time-to-revenue-days 30 \
  --startup-cost 20 \
  --confidence 0.4 >/dev/null

summary_output="$("$LEDGER" summary --group-by experiment_id)"
assert_contains "$summary_output" '"profit": 460.0'
assert_contains "$summary_output" '"cac": 37.0'
assert_contains "$summary_output" '"conversion_rate": 1.0'

rank_output="$("$LEDGER" rank-opportunities --limit 1)"
assert_contains "$rank_output" "lead capture and follow-up automation setup"

report_output="$("$LEDGER" report --group-by offer_id)"
report_path="${report_output#report=}"
test -f "$report_path"
assert_contains "$(cat "$report_path")" "Hermes Revenue OS Report"
assert_contains "$(cat "$report_path")" "Profit"

python3 -m json.tool "$ROOT_DIR/config/revenue-os-policy.example.json" >/dev/null

echo "revenue ledger tests passed"
