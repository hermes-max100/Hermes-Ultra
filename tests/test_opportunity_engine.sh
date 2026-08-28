#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT_DIR/src/system/opportunity-engine.sh"
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

cat > "$TMP_DIR/findings.jsonl" <<'EOF'
{"business_model":"AI service setup","customer_segment":"local service businesses","problem":"missed inbound lead follow-up","offer":"lead capture and follow-up automation setup","channel":"public business discovery","evidence_refs":[{"type":"source","ref":"https://example.com/local-business-directory?utm=test"}],"estimated_demand":0.8,"competition":0.45,"probability_of_conversion":0.08,"expected_revenue":1500,"expected_cost":100,"automation_fit":0.85,"time_to_revenue_days":7,"confidence":0.7,"strategic_fit":0.9,"compliance_risk":0.1,"execution_risk":0.2}
{"business_model":"content monetization","customer_segment":"general audience","problem":"low engagement","offer":"generic content loop","channel":"social","evidence_refs":[],"estimated_demand":0.5,"competition":0.8,"probability_of_conversion":0.01,"expected_revenue":80,"expected_cost":30,"automation_fit":0.4,"time_to_revenue_days":30,"confidence":0.9,"strategic_fit":0.3,"compliance_risk":0.2,"execution_risk":0.4}
{"business_model":"expired trend","customer_segment":"trend audience","problem":"old trend","offer":"stale campaign","channel":"social","evidence_refs":["https://example.com/old-trend"],"probability_of_conversion":0.5,"expected_revenue":1000,"expected_cost":10,"automation_fit":1,"time_to_revenue_days":1,"confidence":1,"strategic_fit":1,"compliance_risk":0,"execution_risk":0,"expires_at":"2000-01-01T00:00:00Z"}
EOF

init_output="$("$ENGINE" init)"
assert_contains "$init_output" "opportunity-queue.jsonl"
test -f "$HERMES_REVENUE_OS_DIR/opportunity-queue.jsonl"

normalize_output="$("$ENGINE" normalize --source-file "$TMP_DIR/findings.jsonl" --write-ledger)"
assert_contains "$normalize_output" '"records_written": 3'
assert_contains "$normalize_output" '"expected_value_score"'
assert_contains "$normalize_output" '"status": "insufficient"'
assert_contains "$normalize_output" '"https://example.com/local-business-directory"'
test -f "$HERMES_REVENUE_OS_DIR/opportunities.jsonl"

python3 - "$HERMES_REVENUE_OS_DIR/opportunity-queue.jsonl" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
assert len(rows) == 3, len(rows)
assert rows[0]["customer_segment"] == "local service businesses"
assert rows[0]["evidence_validation"]["status"] == "source_linked"
assert rows[1]["confidence"] == 0.35, rows[1]["confidence"]
assert rows[2]["status"] == "expired"
for row in rows:
    assert "expires_at" in row
    assert row["local_only_boundary"]["sends_messages"] is False
PY

rank_output="$("$ENGINE" rank --limit 5)"
assert_contains "$rank_output" "lead capture and follow-up automation setup"
if [[ "$rank_output" == *"stale campaign"* ]]; then
  echo "Expired opportunities should be excluded by default" >&2
  exit 1
fi

rank_all_output="$("$ENGINE" rank --include-expired --limit 5)"
assert_contains "$rank_all_output" "stale campaign"

report_output="$("$ENGINE" report)"
report_path="${report_output#report=}"
test -f "$report_path"
assert_contains "$(cat "$report_path")" "Hermes Opportunity Engine Report"
assert_contains "$(cat "$report_path")" "Ranked Queue"

python3 -m json.tool "$ROOT_DIR/config/opportunity-engine.example.json" >/dev/null

echo "opportunity engine tests passed"
