#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANARY="$ROOT_DIR/src/system/canary-controller.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_CANARY_STATE_DIR="$TMP_DIR/canary"
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

live="$TMP_DIR/live-meta.env"
backup="$TMP_DIR/backup-meta.env"
live_two="$TMP_DIR/live-routing.env"
backup_two="$TMP_DIR/backup-routing.env"
printf 'VERSION="candidate"\n' > "$live"
printf 'VERSION="previous"\n' > "$backup"
printf 'ROUTE="candidate"\n' > "$live_two"
printf 'ROUTE="previous"\n' > "$backup_two"
backup_hash="$(sha256sum "$backup" | awk '{print $1}')"
backup_two_hash="$(sha256sum "$backup_two" | awk '{print $1}')"

cat > "$TMP_DIR/policy.json" <<JSON
{
  "promotion_id": "promotion-test-1",
  "candidate_version": "candidate",
  "previous_version": "previous",
  "promotion_evidence_id": "trajenv_anchor_pass",
  "anchor_report_hash": "sha256:anchor",
  "rollback_target": "previous",
  "canary_policy": {
    "max_executions": 5,
    "window_seconds": 3600,
    "cost_ceiling": 1.0,
    "latency_ceiling_ms": 30000,
    "error_rate_threshold": 0.5,
    "security_classification_ceiling": "INTERNAL",
    "permitted_profiles": ["direct"],
    "permitted_projects": []
  },
  "rollback_targets": [
    {
      "path": "$live",
      "backup_path": "$backup",
      "sha256": "$backup_hash"
    },
    {
      "path": "$live_two",
      "backup_path": "$backup_two",
      "sha256": "$backup_two_hash"
    }
  ]
}
JSON

start_output="$("$CANARY" start --policy "$TMP_DIR/policy.json")"
assert_contains "$start_output" '"status": "active"'

cat > "$TMP_DIR/trajectory.json" <<'JSON'
{
  "producer": "hermes-dispatch",
  "objective": "low-risk task",
  "status": "completed",
  "security_classification": "SECURITY_SENSITIVE",
  "duration_ms": 100,
  "cost": 0.01,
  "metadata": {
    "profile": "direct"
  }
}
JSON

record_output="$("$CANARY" record --promotion-id promotion-test-1 --trajectory "$TMP_DIR/trajectory.json")"
assert_contains "$record_output" '"status": "rolled_back"'
assert_contains "$record_output" 'classification-ceiling-exceeded'
assert_contains "$record_output" '"rollback_transaction_id"'
assert_contains "$record_output" '"rollback_evidence_id"'
assert_contains "$(cat "$live")" 'VERSION="previous"'
assert_contains "$(cat "$live_two")" 'ROUTE="previous"'
test -f "$HERMES_CANARY_STATE_DIR/reports/rollback-promotion-test-1.json"
test -f "$HERMES_CANARY_STATE_DIR/reports/rollback-result-promotion-test-1.json"
test -f "$HERMES_CANARY_STATE_DIR/reports/rollback-receipt-promotion-test-1.json"
test -f "$HERMES_CANARY_STATE_DIR/journals/promotion-test-1-rollback.json"
assert_contains "$(cat "$HERMES_CANARY_STATE_DIR/journals/promotion-test-1-rollback.json")" '"status": "committed"'
find "$HERMES_CANARY_STATE_DIR/frozen/promotion-test-1" -type f | grep -q 'live-meta.env'
find "$HERMES_CANARY_STATE_DIR/frozen/promotion-test-1" -type f | grep -q 'live-routing.env'
result_hash="$(sha256sum "$HERMES_CANARY_STATE_DIR/reports/rollback-result-promotion-test-1.json" | awk '{print $1}')"
state_result_hash="$(python3 - "$HERMES_CANARY_STATE_DIR/promotion-test-1.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["rollback_result_hash"])
PY
)"
receipt_result_hash="$(python3 - "$HERMES_CANARY_STATE_DIR/reports/rollback-receipt-promotion-test-1.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["rollback_result_hash"])
PY
)"
[[ "$result_hash" == "$state_result_hash" ]]
[[ "$result_hash" == "$receipt_result_hash" ]]

rollback_again="$("$CANARY" rollback --promotion-id promotion-test-1 --reason "repeat")"
assert_contains "$rollback_again" '"status": "rolled_back"'
assert_contains "$(cat "$live")" 'VERSION="previous"'
assert_contains "$(cat "$live_two")" 'ROUTE="previous"'

memory_output="$("$ROOT_DIR/src/system/memory-fabric.sh" list-trajectories --producer canary-controller)"
assert_contains "$memory_output" '"producer": "canary-controller"'
assert_contains "$memory_output" '"status": "rolled_back"'
assert_contains "$memory_output" "$result_hash"
if [[ "$memory_output" == *"rollback-promotion-test-1.json"* ]]; then
  echo "rollback Memory Fabric evidence must not reference mutable compatibility report" >&2
  echo "$memory_output" >&2
  exit 1
fi

pass_live="$TMP_DIR/pass-live.env"
pass_backup="$TMP_DIR/pass-backup.env"
printf 'VERSION="candidate-pass"\n' > "$pass_live"
printf 'VERSION="previous-pass"\n' > "$pass_backup"
pass_hash="$(sha256sum "$pass_backup" | awk '{print $1}')"

cat > "$TMP_DIR/pass-policy.json" <<JSON
{
  "promotion_id": "promotion-test-pass",
  "candidate_version": "candidate-pass",
  "previous_version": "previous-pass",
  "promotion_evidence_id": "trajenv_anchor_pass_2",
  "anchor_report_hash": "sha256:anchor-pass",
  "rollback_target": "previous-pass",
  "canary_policy": {
    "max_executions": 1,
    "window_seconds": 3600,
    "cost_ceiling": 1.0,
    "latency_ceiling_ms": 30000,
    "error_rate_threshold": 1.0,
    "security_classification_ceiling": "INTERNAL"
  },
  "rollback_targets": [
    {
      "path": "$pass_live",
      "backup_path": "$pass_backup",
      "sha256": "$pass_hash"
    }
  ]
}
JSON

"$CANARY" start --policy "$TMP_DIR/pass-policy.json" >/dev/null
cat > "$TMP_DIR/pass-trajectory.json" <<'JSON'
{
  "producer": "hermes-dispatch",
  "objective": "safe canary task",
  "status": "completed",
  "security_classification": "INTERNAL",
  "duration_ms": 100,
  "cost": 0.01,
  "metadata": {}
}
JSON
pass_output="$("$CANARY" record --promotion-id promotion-test-pass --trajectory "$TMP_DIR/pass-trajectory.json")"
assert_contains "$pass_output" '"status": "canary_passed"'
if [[ "$pass_output" == *'"status": "promoted"'* ]]; then
  echo "canary pass must not become global promotion" >&2
  exit 1
fi

immut_live="$TMP_DIR/immut-live.env"
immut_backup="$TMP_DIR/immut-backup.env"
printf 'VERSION="candidate-immut"\n' > "$immut_live"
printf 'VERSION="previous-immut"\n' > "$immut_backup"
immut_hash="$(sha256sum "$immut_backup" | awk '{print $1}')"

cat > "$TMP_DIR/immut-policy.json" <<JSON
{
  "promotion_id": "promotion-test-immut",
  "candidate_version": "candidate-immut",
  "previous_version": "previous-immut",
  "promotion_evidence_id": "trajenv_anchor_pass_3",
  "anchor_report_hash": "sha256:anchor-immut",
  "rollback_target": "previous-immut",
  "canary_policy": {
    "max_executions": 5,
    "window_seconds": 3600,
    "cost_ceiling": 1.0,
    "latency_ceiling_ms": 30000,
    "error_rate_threshold": 1.0,
    "security_classification_ceiling": "INTERNAL"
  },
  "rollback_targets": [
    {
      "path": "$immut_live",
      "backup_path": "$immut_backup",
      "sha256": "$immut_hash"
    }
  ]
}
JSON

"$CANARY" start --policy "$TMP_DIR/immut-policy.json" >/dev/null
python3 - "$HERMES_CANARY_STATE_DIR/promotion-test-immut.json" <<'PY'
import json
import sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
data["canary_policy"]["max_executions"] = 99
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
if "$CANARY" record --promotion-id promotion-test-immut --trajectory "$TMP_DIR/pass-trajectory.json" >"$TMP_DIR/immut.out" 2>&1; then
  echo "expected immutable policy mutation to fail" >&2
  cat "$TMP_DIR/immut.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/immut.out")" "canary policy changed after start"

unverified_live="$TMP_DIR/unverified-live.env"
unverified_backup="$TMP_DIR/unverified-backup.env"
printf 'VERSION="candidate-unverified"\n' > "$unverified_live"
printf 'VERSION="previous-unverified"\n' > "$unverified_backup"
unverified_hash="$(sha256sum "$unverified_backup" | awk '{print $1}')"

cat > "$TMP_DIR/unverified-policy.json" <<JSON
{
  "promotion_id": "promotion-test-unverified",
  "candidate_version": "candidate-unverified",
  "previous_version": "previous-unverified",
  "promotion_evidence_id": "trajenv_anchor_pass_4",
  "anchor_report_hash": "sha256:anchor-unverified",
  "rollback_target": "previous-unverified",
  "canary_policy": {
    "max_executions": 5,
    "window_seconds": 3600,
    "cost_ceiling": 1.0,
    "latency_ceiling_ms": 30000,
    "error_rate_threshold": 0.5,
    "security_classification_ceiling": "INTERNAL"
  },
  "rollback_targets": [
    {
      "path": "$unverified_live",
      "backup_path": "$unverified_backup",
      "sha256": "$unverified_hash"
    }
  ]
}
JSON

"$CANARY" start --policy "$TMP_DIR/unverified-policy.json" >/dev/null
unverified_output="$(HERMES_MEMORY_DISABLE=1 "$CANARY" record --promotion-id promotion-test-unverified --trajectory "$TMP_DIR/trajectory.json")"
assert_contains "$unverified_output" '"status": "rollback_unverified"'
assert_contains "$(cat "$unverified_live")" 'VERSION="previous-unverified"'
test -f "$HERMES_CANARY_STATE_DIR/journals/promotion-test-unverified-rollback.json"
assert_contains "$(cat "$HERMES_CANARY_STATE_DIR/journals/promotion-test-unverified-rollback.json")" '"status": "committed"'
test -f "$HERMES_CANARY_STATE_DIR/reports/rollback-result-promotion-test-unverified.json"
test ! -f "$HERMES_CANARY_STATE_DIR/reports/rollback-receipt-promotion-test-unverified.json"

release_root="$TMP_DIR/releases"
previous_release="$release_root/previous"
candidate_release="$release_root/candidate"
active_release="$release_root/active"
mkdir -p "$previous_release" "$candidate_release"
printf 'VERSION="previous-release"\n' > "$previous_release/meta.env"
printf 'VERSION="candidate-release"\n' > "$candidate_release/meta.env"
ln -s "$candidate_release" "$active_release"

cat > "$TMP_DIR/release-policy.json" <<JSON
{
  "promotion_id": "promotion-test-release",
  "candidate_version": "candidate-release",
  "previous_version": "previous-release",
  "promotion_evidence_id": "trajenv_anchor_pass_5",
  "anchor_report_hash": "sha256:anchor-release",
  "rollback_target": "previous-release",
  "canary_policy": {
    "max_executions": 5,
    "window_seconds": 3600,
    "cost_ceiling": 1.0,
    "latency_ceiling_ms": 30000,
    "error_rate_threshold": 0.5,
    "security_classification_ceiling": "INTERNAL"
  },
  "release_unit": {
    "active_path": "$active_release",
    "previous_release_path": "$previous_release",
    "candidate_release_path": "$candidate_release"
  }
}
JSON

"$CANARY" start --policy "$TMP_DIR/release-policy.json" >/dev/null
release_output="$("$CANARY" record --promotion-id promotion-test-release --trajectory "$TMP_DIR/trajectory.json")"
assert_contains "$release_output" '"status": "rolled_back"'
[[ "$(readlink -f "$active_release")" == "$(readlink -f "$previous_release")" ]]
assert_contains "$(cat "$HERMES_CANARY_STATE_DIR/journals/promotion-test-release-rollback.json")" '"mode": "release_unit"'
assert_contains "$(cat "$HERMES_CANARY_STATE_DIR/reports/rollback-result-promotion-test-release.json")" '"release_unit"'
assert_contains "$(cat "$active_release/meta.env")" 'VERSION="previous-release"'

echo "canary controller tests passed"
