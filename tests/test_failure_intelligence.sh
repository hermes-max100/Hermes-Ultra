#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="$ROOT_DIR/src/system/memory-fabric.sh"
FAILURE="$ROOT_DIR/src/system/failure-intelligence.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_FAILURE_INTEL_DIR="$TMP_DIR/failure-intelligence"

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

cat > "$TMP_DIR/failure-1.json" <<'JSON'
{
  "trajectory_id": "traj_failure_1",
  "producer": "hermes-dispatch",
  "objective": "route task through legal skill",
  "input_hash": "sha256:input1",
  "selected_agent": "hermes-router",
  "selected_skills": ["document-intelligence"],
  "model": "glm/glm-5.2",
  "actions": [{"type": "route"}],
  "predicted_outcome": "legal skill handles filing task",
  "observed_outcome": "request 84713 timed out after 30004 ms; classification violation blocked routing at /tmp/hermes/run-20260814T220101Z",
  "status": "failed",
  "failure_class": "classification violation",
  "evidence_refs": [{"path": "logs/traj_failure_1.json", "sha256": "sha256:evidence1"}],
  "security_classification": "SECURITY_SENSITIVE",
  "metadata": {"profile": "direct", "confidence": 0.8}
}
JSON

cat > "$TMP_DIR/failure-2.json" <<'JSON'
{
  "trajectory_id": "traj_failure_2",
  "producer": "hermes-dispatch",
  "objective": "route second legal filing task",
  "input_hash": "sha256:input2",
  "selected_agent": "hermes-router",
  "selected_skills": ["legal-evidence-os"],
  "model": "kimi/kimi-latest",
  "actions": [{"type": "route"}],
  "predicted_outcome": "legal skill handles filing task",
  "observed_outcome": "request 91282 timed out after 30011 ms; classification violation blocked routing at /var/tmp/hermes/run-20260814T220533Z",
  "status": "blocked",
  "failure_class": "classification violation",
  "evidence_refs": [{"path": "logs/traj_failure_2.json", "sha256": "sha256:evidence2"}],
  "security_classification": "SECURITY_SENSITIVE",
  "metadata": {"profile": "direct", "provider": "glm", "confidence": 0.8, "recovery_attempt": true}
}
JSON

cat > "$TMP_DIR/success.json" <<'JSON'
{
  "trajectory_id": "traj_success_1",
  "producer": "hermes-dispatch",
  "objective": "safe unrelated task",
  "input_hash": "sha256:input3",
  "selected_agent": "hermes-router",
  "selected_skills": ["document-intelligence"],
  "model": "kimi/kimi-latest",
  "actions": [{"type": "route"}],
  "predicted_outcome": "document skill succeeds",
  "observed_outcome": "completed normally",
  "status": "completed",
  "failure_class": "",
  "evidence_refs": [],
  "security_classification": "INTERNAL",
  "metadata": {"profile": "direct", "confidence": 0.8}
}
JSON

cat > "$TMP_DIR/success-with-history.json" <<'JSON'
{
  "trajectory_id": "traj_success_historical_failure_class",
  "producer": "hermes-dispatch",
  "objective": "safe recovered diagnostic task",
  "input_hash": "sha256:input4",
  "selected_agent": "hermes-router",
  "selected_skills": ["legal-evidence-os"],
  "model": "kimi/kimi-latest",
  "actions": [{"type": "route"}],
  "predicted_outcome": "diagnostic succeeds",
  "observed_outcome": "completed after handling prior classification violation",
  "status": "completed",
  "failure_class": "classification violation",
  "evidence_refs": [],
  "security_classification": "SECURITY_SENSITIVE",
  "metadata": {"profile": "direct", "confidence": 0.8}
}
JSON

"$MEMORY" ingest-trajectory --json-file "$TMP_DIR/failure-1.json" >/dev/null
"$MEMORY" ingest-trajectory --json-file "$TMP_DIR/failure-2.json" >/dev/null
"$MEMORY" ingest-trajectory --json-file "$TMP_DIR/success.json" >/dev/null
"$MEMORY" ingest-trajectory --json-file "$TMP_DIR/success-with-history.json" >/dev/null

export_output="$("$MEMORY" export-trajectories --failures-only --jsonl)"
assert_contains "$export_output" 'traj_failure_1'
assert_contains "$export_output" 'traj_failure_2'
if [[ "$export_output" == *"traj_success_historical_failure_class"* ]]; then
  echo "successful trajectory with historical failure_class should not export as failure" >&2
  echo "$export_output" >&2
  exit 1
fi

scan_output="$("$FAILURE" scan --limit 50)"
assert_contains "$scan_output" '"clusters": 1'
test -f "$HERMES_FAILURE_INTEL_DIR/clusters.json"
test -f "$HERMES_FAILURE_INTEL_DIR/clusters.jsonl"

clusters_output="$("$FAILURE" clusters)"
assert_contains "$clusters_output" '"occurrence_count": 2'
assert_contains "$clusters_output" '"severity": "critical"'
assert_contains "$clusters_output" 'legal-evidence-os'
assert_contains "$clusters_output" 'document-intelligence'
assert_contains "$clusters_output" 'glm/glm-5.2'

cluster_id="$(python3 - "$HERMES_FAILURE_INTEL_DIR/clusters.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["clusters"][0]["cluster_id"])
PY
)"

show_output="$("$FAILURE" show "$cluster_id")"
assert_contains "$show_output" '"representative_trajectory_ids"'
assert_contains "$show_output" '"root_signature"'
assert_contains "$show_output" '"raw_observed_hashes"'
assert_contains "$show_output" '"normalized_observed_fingerprint"'
assert_contains "$show_output" '"context_dimensions"'
assert_contains "$show_output" 'traj_failure_1'
assert_contains "$show_output" 'traj_failure_2'
if [[ "$show_output" == *"traj_success_historical_failure_class"* ]]; then
  echo "successful diagnostic trajectory should not contaminate failure cluster" >&2
  echo "$show_output" >&2
  exit 1
fi

proposal_output="$("$FAILURE" propose "$cluster_id")"
assert_contains "$proposal_output" '"source_cluster_id"'
assert_contains "$proposal_output" "$cluster_id"
assert_contains "$proposal_output" '"root_signature"'
assert_contains "$proposal_output" '"hypothesis_confidence"'
assert_contains "$proposal_output" '"evidence_trajectory_ids"'
assert_contains "$proposal_output" '"no automatic mutation"'
proposal_path="$(python3 - "$proposal_output" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["proposal"])
PY
)"
test -f "$proposal_path"
assert_contains "$(cat "$proposal_path")" '"required_anchor_changes": []'
assert_contains "$(cat "$proposal_path")" '"affected_paths": []'
assert_contains "$(cat "$proposal_path")" '"proposal-only"'

echo "failure intelligence tests passed"
