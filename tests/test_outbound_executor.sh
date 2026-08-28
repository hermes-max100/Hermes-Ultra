#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT_DIR/src/system/opportunity-engine.sh"
ORCH="$ROOT_DIR/src/system/revenue-orchestrator.sh"
FUNNEL="$ROOT_DIR/src/system/local-service-funnel.sh"
OUTBOUND="$ROOT_DIR/src/system/outbound-executor.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_REVENUE_OS_DIR="$TMP_DIR/revenue-os"
export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_APPROVAL_HMAC_SECRET="test-approval-secret-that-is-longer-than-thirty-two-bytes"
export HERMES_CONTAINMENT_SECRET="test-containment-secret-that-is-longer-than-thirty-two-bytes"
export HERMES_CONTAINMENT_STATE_DIR="$TMP_DIR/containment"
export HERMES_EXTERNALIZATION_STATE_DIR="$TMP_DIR/externalization"

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
{"business_model":"AI service setup","customer_segment":"local service businesses","problem":"missed inbound lead follow-up","offer":"AI-assisted lead capture and follow-up automation","channel":"human-approved direct outreach","evidence_refs":[{"type":"source","ref":"https://example.com/local-business-directory"}],"estimated_demand":0.8,"competition":0.45,"probability_of_conversion":0.08,"expected_revenue":1500,"expected_cost":0,"automation_fit":0.85,"time_to_revenue_days":7,"confidence":0.7,"strategic_fit":0.9,"compliance_risk":0.1,"execution_risk":0.2}
EOF

cat > "$TMP_DIR/prospects.jsonl" <<'EOF'
{"business_name":"Apex Plumbing","category":"plumbing","city":"Riverside","state":"CA","website":"https://example.com/apex","contact_channel":"email","contact_ref":"hello@example.com","source_url":"https://example.com/apex-profile","signals":["high-ticket-service","manual-follow-up"]}
{"business_name":"Form Only HVAC","category":"hvac","city":"Riverside","state":"CA","website":"https://example.com/form-hvac","contact_channel":"contact_form","contact_ref":"https://example.com/form-hvac/contact","source_url":"https://example.com/form-hvac-profile","signals":["high-ticket-service","manual-follow-up"]}
{"business_name":"Phone Only Doors","category":"garage_door","city":"Riverside","state":"CA","website":"https://example.com/doors","contact_channel":"phone","contact_ref":"555-0100","source_url":"https://example.com/doors-profile","signals":["high-ticket-service","manual-follow-up"]}
EOF

"$ENGINE" init >/dev/null
"$ORCH" init >/dev/null
"$OUTBOUND" init >/dev/null
"$ENGINE" normalize --source-file "$TMP_DIR/findings.jsonl" --write-ledger >/dev/null
"$ORCH" plan --experiment-id exp_outbound_test --timebox-days 5 --plan-ttl-days 8 >/dev/null
"$FUNNEL" generate --experiment-id exp_outbound_test --prospects-file "$TMP_DIR/prospects.jsonl" --record-ledger >/dev/null

policy_output="$("$OUTBOUND" create-campaign-policy \
  --campaign-id camp_outbound_test \
  --experiment-id exp_outbound_test \
  --offer "AI-assisted lead capture and follow-up automation" \
  --max-sends 10 \
  --allowed-industry plumbing \
  --allowed-industry hvac \
  --allowed-autonomous-channel email \
  --handoff-only-channel contact_form \
  --expires-at 2099-01-01T00:00:00Z)"
assert_contains "$policy_output" "campaign_policy_hash"

policy_path="$HERMES_REVENUE_OS_DIR/campaign-policies/camp_outbound_test.json"
policy_hash="$(python3 - "$policy_path" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["campaign_policy_hash"])
PY
)"

"$ORCH" record-approval \
  --approval-id appr_campaign_send \
  --experiment-id exp_outbound_test \
  --action send \
  --scope "campaign camp_outbound_test max 10 allowed email sends" \
  --action-id "act_campaign_send" \
  --principal "owner" \
  --actor "revenue-os" \
  --counterparty "Apex Plumbing" \
  --destination "smtp://hello@example.com" \
  --amount 0 \
  --approver "human-test" \
  --policy-hash "$policy_hash" \
  --expires-at "2099-01-01T00:00:00Z" >/dev/null

approval_path="$HERMES_REVENUE_OS_DIR/approval-receipts/appr_campaign_send.json"
assert_contains "$(cat "$approval_path")" '"approval_auth"'
assert_contains "$(cat "$approval_path")" '"algorithm": "hmac-sha256"'

summary_path="$HERMES_REVENUE_OS_DIR/funnels/local-service/exp_outbound_test/funnel-summary.json"
handoff_path="$(python3 - "$summary_path" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
for artifact in summary["artifacts"]:
    if artifact["business_name"] == "Apex Plumbing":
        print(artifact["send_handoff"])
PY
)"

"$FUNNEL" prepare-approved-handoff --experiment-id exp_outbound_test --handoff "$handoff_path" --approval-id appr_campaign_send >/dev/null
approved_handoff="${handoff_path%/*}/approved-send-handoff.json"

python3 - "${handoff_path%/*}/outreach-draft.md" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("Quick idea to reduce missed leads for Apex Plumbing", "Quick idea for lead follow-up at Apex Plumbing")
text = text.replace("noticed a few places where\ninbound leads may be hard to capture or follow up quickly.", "saw that your public profile lists plumbing service availability and a business email contact path.")
text = text.replace("track missed leads in one simple report.", "track open follow-ups in one simple report.")
path.write_text(text, encoding="utf-8")
PY

validate_output="$("$OUTBOUND" validate-handoff \
  --campaign-policy "$policy_path" \
  --handoff "$approved_handoff" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl")"
assert_contains "$validate_output" '"valid": true'

# Removed legacy transport and policy-off switches must fail at the parser.
if "$OUTBOUND" send \
  --campaign-policy "$policy_path" \
  --handoff "$approved_handoff" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl" \
  --transport sendmail \
  --containment-token-stdin </dev/null >/tmp/outbound-sendmail.out 2>&1; then
  echo "sendmail transport should be rejected" >&2
  exit 1
fi
assert_contains "$(cat /tmp/outbound-sendmail.out)" "invalid choice"

if "$OUTBOUND" validate-handoff \
  --campaign-policy "$policy_path" \
  --handoff "$approved_handoff" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl" \
  --allow-duplicate >/tmp/outbound-bypass.out 2>&1; then
  echo "--allow-duplicate should be rejected" >&2
  exit 1
fi
assert_contains "$(cat /tmp/outbound-bypass.out)" "unrecognized arguments"

# Existing sent evidence must deny the same prospect before any network action.
prospect_id="$(python3 - "$approved_handoff" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["prospect_id"])
PY
)"
printf '%s\n' "{\"campaign_id\":\"camp_outbound_test\",\"prospect_id\":\"$prospect_id\",\"send_status\":\"sent\"}" >> "$HERMES_REVENUE_OS_DIR/outbound/send-receipts.jsonl"
if "$OUTBOUND" validate-handoff \
  --campaign-policy "$policy_path" \
  --handoff "$approved_handoff" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl" >/tmp/outbound-duplicate.out 2>&1; then
  echo "duplicate prospect validation should fail" >&2
  exit 1
fi
assert_contains "$(cat /tmp/outbound-duplicate.out)" "duplicate prospect send attempt"

form_handoff="$(python3 - "$summary_path" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
for artifact in summary["artifacts"]:
    if artifact["business_name"] == "Form Only HVAC":
        print(artifact["send_handoff"])
PY
)"
"$FUNNEL" prepare-approved-handoff --experiment-id exp_outbound_test --handoff "$form_handoff" --approval-id appr_campaign_send >/dev/null
if "$OUTBOUND" validate-handoff \
  --campaign-policy "$policy_path" \
  --handoff "${form_handoff%/*}/approved-send-handoff.json" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl" >/tmp/outbound-form.out 2>&1; then
  echo "contact_form channel should be handoff-only, not autonomous" >&2
  exit 1
fi
assert_contains "$(cat /tmp/outbound-form.out)" "contact channel is handoff-only"

phone_handoff="$(python3 - "$summary_path" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
for artifact in summary["artifacts"]:
    if artifact["business_name"] == "Phone Only Doors":
        print(artifact["send_handoff"])
PY
)"
"$FUNNEL" prepare-approved-handoff --experiment-id exp_outbound_test --handoff "$phone_handoff" --approval-id appr_campaign_send >/dev/null
if "$OUTBOUND" validate-handoff \
  --campaign-policy "$policy_path" \
  --handoff "${phone_handoff%/*}/approved-send-handoff.json" \
  --approval-id appr_campaign_send \
  --prospects-file "$TMP_DIR/prospects.jsonl" >/tmp/outbound-phone.out 2>&1; then
  echo "phone channel should not validate under email-only campaign policy" >&2
  exit 1
fi
assert_contains "$(cat /tmp/outbound-phone.out)" "contact channel not allowed"

python3 -m json.tool "$ROOT_DIR/config/revenue-campaign-policy.example.json" >/dev/null

echo "outbound executor tests passed"
