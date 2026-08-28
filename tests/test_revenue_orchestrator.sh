#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT_DIR/src/system/opportunity-engine.sh"
ORCH="$ROOT_DIR/src/system/revenue-orchestrator.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_REVENUE_OS_DIR="$TMP_DIR/revenue-os"
export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_APPROVAL_HMAC_SECRET="${HERMES_APPROVAL_HMAC_SECRET:-revenue-orchestrator-test-secret-32-bytes-minimum-2026}"

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
{"business_model":"expired high score","customer_segment":"old trend buyers","problem":"old trend","offer":"stale trend offer","channel":"social","evidence_refs":[{"type":"source","ref":"https://example.com/expired"}],"probability_of_conversion":0.9,"expected_revenue":5000,"expected_cost":0,"automation_fit":1,"time_to_revenue_days":1,"confidence":1,"strategic_fit":1,"compliance_risk":0,"execution_risk":0,"expires_at":"2000-01-01T00:00:00Z"}
{"business_model":"unsupported high score","customer_segment":"unknown buyers","problem":"unsupported claim","offer":"unsupported offer","channel":"unknown","evidence_refs":[],"probability_of_conversion":0.8,"expected_revenue":5000,"expected_cost":0,"automation_fit":1,"time_to_revenue_days":1,"confidence":1,"strategic_fit":1,"compliance_risk":0,"execution_risk":0}
{"business_model":"AI service setup","customer_segment":"local service businesses","problem":"missed inbound lead follow-up","offer":"lead capture and follow-up automation setup","channel":"public business discovery","evidence_refs":[{"type":"source","ref":"https://example.com/local-business-directory"}],"estimated_demand":0.8,"competition":0.45,"probability_of_conversion":0.08,"expected_revenue":1500,"expected_cost":0,"automation_fit":0.85,"time_to_revenue_days":7,"confidence":0.7,"strategic_fit":0.9,"compliance_risk":0.1,"execution_risk":0.2}
EOF

"$ENGINE" init >/dev/null
"$ORCH" init >/dev/null
"$ENGINE" normalize --source-file "$TMP_DIR/findings.jsonl" --write-ledger >/dev/null

plan_output="$("$ORCH" plan --experiment-id exp_orchestrator_test --timebox-days 5 --plan-ttl-days 8)"
assert_contains "$plan_output" '"experiment_id": "exp_orchestrator_test"'
assert_contains "$plan_output" '"opportunity_id":'

plan_path="$HERMES_REVENUE_OS_DIR/experiments/exp_orchestrator_test/experiment-plan.json"
receipt_path="$HERMES_REVENUE_OS_DIR/experiments/exp_orchestrator_test/experiment-receipt.json"
test -f "$plan_path"
test -f "$receipt_path"

python3 - "$plan_path" "$receipt_path" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
receipt = json.load(open(sys.argv[2], encoding="utf-8"))
assert plan["opportunity_snapshot"]["offer"] == "lead capture and follow-up automation setup"
assert plan["opportunity_snapshot"]["status"] != "expired"
assert plan["approval_policy"]["human_approved_boolean_is_not_authority"] is True
assert plan["approval_required_steps"], "approval steps missing"
assert any(step["action"] == "send" for step in plan["approval_required_steps"])
assert not any(step.get("approval_id") for step in plan["approval_required_steps"])
assert '"human_approved": true' not in json.dumps(plan)
assert receipt["plan_sha256"]
assert receipt["memory_status"] == "persisted", receipt["memory_status"]
PY

list_output="$("$ORCH" list-plans)"
assert_contains "$list_output" "exp_orchestrator_test"

show_output="$("$ORCH" show --experiment-id exp_orchestrator_test)"
assert_contains "$show_output" '"schema_version": "revenue-experiment-plan-v1"'

approval_output="$("$ORCH" record-approval \
  --approval-id appr_test_send \
  --experiment-id exp_orchestrator_test \
  --action send \
  --scope "send one approved outreach draft to one named prospect" \
  --action-id "act_test_send" \
  --principal "owner" \
  --actor "revenue-os" \
  --counterparty "pros_1" \
  --destination "smtp://owner@example.com" \
  --amount 0 \
  --approver "human-test" \
  --policy-hash "policy_hash_test" \
  --expires-at "2099-01-01T00:00:00Z")"
assert_contains "$approval_output" "appr_test_send"
test -f "$HERMES_REVENUE_OS_DIR/approval-receipts/appr_test_send.json"
python3 - "$HERMES_REVENUE_OS_DIR/approval-receipts/appr_test_send.json" <<'PY2'
import json, sys
r=json.load(open(sys.argv[1], encoding="utf-8"))
assert r["action_id"] == "act_test_send"
assert r["principal"] == "owner"
assert r["actor"] == "revenue-os"
assert r["counterparty"] == "pros_1"
assert r["destination"] == "smtp://owner@example.com"
assert r["amount"] == 0.0
assert r["approval_auth"]["algorithm"] == "hmac-sha256"
PY2

if "$ORCH" record-approval \
  --approval-id appr_bad \
  --experiment-id exp_orchestrator_test \
  --action analysis \
  --scope "bad action" \
  --action-id "act_bad" \
  --principal "owner" \
  --actor "revenue-os" \
  --counterparty "pros_1" \
  --destination "smtp://owner@example.com" \
  --amount 0 \
  --approver "human-test" \
  --policy-hash "policy_hash_test" \
  --expires-at "2099-01-01T00:00:00Z" >/tmp/revenue-orchestrator-bad-approval.out 2>&1; then
  echo "analysis should not be accepted as an approval-required action" >&2
  exit 1
fi
assert_contains "$(cat /tmp/revenue-orchestrator-bad-approval.out)" "unsupported approval action"

python3 -m json.tool "$ROOT_DIR/config/revenue-orchestrator.example.json" >/dev/null

echo "revenue orchestrator tests passed"
