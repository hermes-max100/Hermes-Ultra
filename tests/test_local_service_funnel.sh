#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT_DIR/src/system/opportunity-engine.sh"
ORCH="$ROOT_DIR/src/system/revenue-orchestrator.sh"
FUNNEL="$ROOT_DIR/src/system/local-service-funnel.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_REVENUE_OS_DIR="$TMP_DIR/revenue-os"
export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_APPROVAL_HMAC_SECRET="test-approval-secret-that-is-longer-than-thirty-two-bytes"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

cat > "$TMP_DIR/findings.jsonl" <<'EOF'
{"business_model":"AI service setup","customer_segment":"local service businesses","problem":"missed inbound lead follow-up","offer":"lead capture and follow-up automation setup","channel":"public business discovery","evidence_refs":[{"type":"source","ref":"https://example.com/local-business-directory"}],"estimated_demand":0.8,"competition":0.45,"probability_of_conversion":0.08,"expected_revenue":1500,"expected_cost":0,"automation_fit":0.85,"time_to_revenue_days":7,"confidence":0.7,"strategic_fit":0.9,"compliance_risk":0.1,"execution_risk":0.2}
EOF

cat > "$TMP_DIR/prospects.jsonl" <<'EOF'
{"business_name":"Apex Plumbing","category":"plumbing","city":"Riverside","state":"CA","website":"https://example.com/apex","contact_channel":"email","contact_ref":"hello@example.com","source_url":"https://example.com/apex-profile","signals":["missed-calls","no-online-booking","high-ticket-service"]}
{"business_name":"No Evidence LLC","category":"cleaning","signals":[]}
EOF

"$ENGINE" init >/dev/null
"$ORCH" init >/dev/null
"$ENGINE" normalize --source-file "$TMP_DIR/findings.jsonl" --write-ledger >/dev/null
"$ORCH" plan --experiment-id exp_local_service_test --timebox-days 5 --plan-ttl-days 8 >/dev/null

generate_output="$("$FUNNEL" generate --experiment-id exp_local_service_test --prospects-file "$TMP_DIR/prospects.jsonl" --record-ledger)"
assert_contains "$generate_output" '"qualified_prospects": 1'
assert_contains "$generate_output" '"requires_approval_before_send": true'

summary_path="$HERMES_REVENUE_OS_DIR/funnels/local-service/exp_local_service_test/funnel-summary.json"
test -f "$summary_path"

python3 - "$summary_path" "$HERMES_REVENUE_OS_DIR" <<'PY'
import json, pathlib, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
assert summary["qualified_prospects"] == 1
assert summary["boundary"]["sent_anything"] is False
assert summary["boundary"]["local_only"] is True
artifact = summary["artifacts"][0]
for key in ("audit", "outreach_draft", "send_handoff"):
    assert pathlib.Path(artifact[key]).is_file(), artifact[key]
handoff = json.load(open(artifact["send_handoff"], encoding="utf-8"))
assert handoff["approval_required"] is True
assert handoff["allowed_to_send"] is False
assert "send" in handoff["required_approval_actions"]
premortem = pathlib.Path(summary["premortem_gate"])
assert premortem.is_file()
assert "Premortem Gate" in premortem.read_text(encoding="utf-8")
ledger = root / "revenue-events.jsonl"
assert ledger.is_file()
assert "outreach_draft" in ledger.read_text(encoding="utf-8")
print(artifact["send_handoff"])
PY

handoff_path="$(python3 - "$summary_path" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
print(summary["artifacts"][0]["send_handoff"])
PY
)"

policy_hash="$(python3 - "$HERMES_REVENUE_OS_DIR/experiments/exp_local_service_test/experiment-plan.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
print(plan["policy_hash"])
PY
)"

"$ORCH" record-approval \
  --approval-id appr_local_service_send \
  --experiment-id exp_local_service_test \
  --action send \
  --scope "send one approved outreach draft to Apex Plumbing" \
  --action-id "act_local_service_send" \
  --principal "owner" \
  --actor "revenue-os" \
  --counterparty "Apex Plumbing" \
  --destination "smtp://hello@example.com" \
  --amount 0 \
  --approver "human-test" \
  --policy-hash "$policy_hash" \
  --expires-at "2099-01-01T00:00:00Z" >/dev/null

approved_output="$("$FUNNEL" prepare-approved-handoff --experiment-id exp_local_service_test --handoff "$handoff_path" --approval-id appr_local_service_send)"
assert_contains "$approved_output" '"sent_anything": false'

python3 - "${handoff_path%/*}/approved-send-handoff.json" <<'PY'
import json, sys
handoff = json.load(open(sys.argv[1], encoding="utf-8"))
assert handoff["connector_handoff_ready"] is True
assert handoff["connector_must_verify_receipt"] is True
assert handoff["allowed_to_send"] is False
assert handoff["approval_id"] == "appr_local_service_send"
PY

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage approved \
  --approval-id appr_local_service_send \
  --notes "Outreach approved by human-test" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage sent \
  --approval-id appr_local_service_send \
  --notes "Manual send completed after approval" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage replied \
  --reply-status positive \
  --notes "Positive reply received" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage call_booked \
  --notes "Call booked" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage proposal_sent \
  --proposal-value 1500 \
  --notes "Proposal sent" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage won \
  --proposal-value 1500 \
  --notes "Won pilot customer" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_260aaa4f3866605a \
  --business-name "Apex Plumbing" \
  --stage revenue_received \
  --gross-revenue 1500 \
  --direct-cost 100 \
  --notes "Revenue received" >/dev/null

report_output="$("$FUNNEL" pilot-report --experiment-id exp_local_service_test --prospects-file "$TMP_DIR/prospects.jsonl")"
assert_contains "$report_output" '"prospects_reviewed": 2'
assert_contains "$report_output" '"outreach_sent": 1'
assert_contains "$report_output" '"positive_replies": 1'
assert_contains "$report_output" '"profit": 1400.0'

tracker_json="$HERMES_REVENUE_OS_DIR/funnels/local-service/exp_local_service_test/pilot-tracker.json"
tracker_md="$HERMES_REVENUE_OS_DIR/funnels/local-service/exp_local_service_test/pilot-tracker.md"
test -f "$tracker_json"
test -f "$tracker_md"

python3 - "$tracker_json" "$tracker_md" <<'PY'
import json, pathlib, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
report = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
metrics = payload["metrics"]
assert metrics["prospects_reviewed"] == 2
assert metrics["qualified"] == 1
assert metrics["outreach_sent"] == 1
assert metrics["positive_reply_rate"] == 1.0
assert metrics["calls_booked"] == 1
assert metrics["proposals_sent"] == 1
assert metrics["wins"] == 1
assert metrics["gross_revenue"] == 1500.0
assert metrics["total_direct_cost"] == 100.0
assert metrics["profit"] == 1400.0
assert metrics["cost_per_qualified_lead"] == 100.0
assert metrics["profit_per_contacted_prospect"] == 1400.0
apex = next(row for row in payload["rows"] if row["business_name"] == "Apex Plumbing")
assert apex["current_stage"] == "revenue_received"
assert apex["reply_status"] == "positive"
assert "Pilot Metrics" in report
assert "Profit per contacted prospect" in report
PY

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_duplicate_qual \
  --business-name "Branch Test HVAC" \
  --stage qualified \
  --qualification-score 0.8 \
  --qualification-signal "missed-calls" \
  --notes "Qualified once" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_duplicate_qual \
  --business-name "Branch Test HVAC" \
  --stage lead_qualified \
  --notes "Lead qualification deepened without double-counting qualified lead" >/dev/null

python3 - "$HERMES_REVENUE_OS_DIR/revenue-events.jsonl" <<'PY'
import json, sys
events = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
qualified = sum(
    int(event.get("metrics", {}).get("qualified_leads", 0))
    for event in events
    if event.get("lead_id") == "pros_duplicate_qual"
)
assert qualified == 1, qualified
PY

duplicate_report="$("$FUNNEL" pilot-report --experiment-id exp_local_service_test --prospects-file "$TMP_DIR/prospects.jsonl")"
assert_contains "$duplicate_report" '"qualified": 2'

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_lost_branch \
  --business-name "Lost Branch Roofing" \
  --stage proposal_sent \
  --proposal-value 1200 \
  --notes "Proposal sent before loss" >/dev/null

"$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_lost_branch \
  --business-name "Lost Branch Roofing" \
  --stage lost \
  --notes "Prospect lost" >/dev/null

if "$FUNNEL" record-stage \
  --experiment-id exp_local_service_test \
  --prospect-id pros_lost_branch \
  --business-name "Lost Branch Roofing" \
  --stage revenue_received \
  --gross-revenue 1200 \
  >/tmp/local-service-lost-revenue.out 2>&1; then
  echo "lost prospect should not advance to revenue_received" >&2
  exit 1
fi
assert_contains "$(cat /tmp/local-service-lost-revenue.out)" "cannot record revenue_received after lost"

if "$FUNNEL" prepare-approved-handoff --experiment-id exp_local_service_test --handoff "$handoff_path" --approval-id missing >/tmp/local-service-bad-handoff.out 2>&1; then
  echo "missing approval receipt should fail" >&2
  exit 1
fi
assert_contains "$(cat /tmp/local-service-bad-handoff.out)" "approval receipt not found"

python3 -m json.tool "$summary_path" >/dev/null

echo "local service funnel tests passed"
