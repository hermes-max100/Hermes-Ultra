#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="$ROOT_DIR/src/system/memory-fabric.sh"
FAILURE="$ROOT_DIR/src/system/failure-intelligence.sh"
CANDIDATE="$ROOT_DIR/src/system/candidate-generator.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_FAILURE_INTEL_DIR="$TMP_DIR/failure-intelligence"
export HERMES_CANDIDATE_DIR="$TMP_DIR/candidates"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

"$MEMORY" init >/dev/null

cat > "$TMP_DIR/failure.json" <<'JSON'
{
  "trajectory_id": "traj_candidate_failure_1",
  "producer": "hermes-dispatch",
  "objective": "run candidate generator fixture",
  "input_hash": "sha256:candidate-input",
  "selected_agent": "hermes-router",
  "selected_skills": ["legal-evidence-os"],
  "model": "kimi/kimi-latest",
  "actions": [{"type": "route"}],
  "predicted_outcome": "task succeeds",
  "observed_outcome": "request 84713 timed out after 30004 ms",
  "status": "failed",
  "failure_class": "timeout while routing",
  "evidence_refs": [{"path": "logs/traj_candidate_failure_1.json", "sha256": "sha256:candidate-evidence"}],
  "security_classification": "INTERNAL",
  "metadata": {"profile": "direct", "provider": "kimi", "confidence": 0.8}
}
JSON

"$MEMORY" ingest-trajectory --json-file "$TMP_DIR/failure.json" >/dev/null
"$FAILURE" scan --limit 50 >/dev/null

cluster_id="$(python3 - "$HERMES_FAILURE_INTEL_DIR/clusters.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["clusters"][0]["cluster_id"])
PY
)"

candidate_output="$("$CANDIDATE" generate "$cluster_id")"
assert_contains "$candidate_output" '"candidate_manifest_path"'
assert_contains "$candidate_output" '"regression_test_spec_path"'
package_dir="$(python3 - "$candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["package_dir"])
PY
)"
manifest_path="$(python3 - "$candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["candidate_manifest_path"])
PY
)"
receipt_path="$(python3 - "$candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["receipt"])
PY
)"
regression_path="$(python3 - "$candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["regression_test_spec_path"])
PY
)"

test -f "$manifest_path"
test -f "$receipt_path"
test -f "$regression_path"
[[ "$(basename "$package_dir")" == cand_* ]]

manifest="$(cat "$manifest_path")"
assert_contains "$manifest" '"source_cluster_id"'
assert_contains "$manifest" '"root_signature_hash"'
assert_contains "$manifest" '"source_trajectory_ids"'
assert_contains "$manifest" '"source_evidence_hashes"'
assert_contains "$manifest" '"proposed_diff"'
assert_contains "$manifest" '"status": "not_generated_by_v1"'
assert_contains "$manifest" '"required_anchor_changes": []'
assert_contains "$manifest" '"benchmark_gap_proposal": null'
assert_contains "$manifest" '"candidate_manifest_hash"'
assert_contains "$manifest" '"candidate_manifest_hash_scope"'
assert_contains "$(cat "$regression_path")" '"created_before_candidate_spec": true'

python3 - "$manifest_path" <<'PY'
import hashlib
import json
import sys

path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
expected = data.pop("candidate_manifest_hash")
actual = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
if expected != actual:
    raise SystemExit(f"candidate manifest hash mismatch: {expected} != {actual}")
if data.get("required_anchor_changes") != []:
    raise SystemExit("required_anchor_changes must remain empty")
PY

first_manifest_hash="$(sha256sum "$manifest_path" | awk '{print $1}')"
second_candidate_output="$("$CANDIDATE" generate "$cluster_id")"
second_package_dir="$(python3 - "$second_candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["package_dir"])
PY
)"
if [[ "$package_dir" == "$second_package_dir" ]]; then
  echo "candidate generator reused an immutable package directory" >&2
  exit 1
fi
second_manifest_path="$(python3 - "$second_candidate_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["candidate_manifest_path"])
PY
)"
test -f "$second_manifest_path"
after_regeneration_hash="$(sha256sum "$manifest_path" | awk '{print $1}')"
if [[ "$first_manifest_hash" != "$after_regeneration_hash" ]]; then
  echo "regenerating a candidate changed the first immutable package" >&2
  exit 1
fi

echo "candidate generator tests passed"
