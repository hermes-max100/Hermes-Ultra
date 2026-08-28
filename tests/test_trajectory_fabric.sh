#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="$ROOT_DIR/src/system/memory-fabric.sh"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hermes-trajectory-test.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

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

"$MEMORY" init >/dev/null

cat > "$TMP_DIR/envelope.json" <<'JSON'
{
  "producer": "trust-gate",
  "objective": "candidate-trust-scan",
  "selected_agent": "trust-gate",
  "actions": [
    {
      "type": "static_scan",
      "candidate": "example-skill",
      "authorization": "Bearer sk-thisshouldberedacted123456789"
    }
  ],
  "predicted_outcome": "trusted_candidate",
  "observed_outcome": "verdict=allow",
  "status": "allow",
  "evidence_refs": [
    {"type": "trust-gate-json", "path": "/tmp/report.json", "sha256": "abc123"}
  ],
  "security_classification": "internal",
  "metadata": {
    "safety_claim": true,
    "api_key": "am_us_should_not_survive_1234567890"
  }
}
JSON

ingest_output="$("$MEMORY" ingest-trajectory --json-file "$TMP_DIR/envelope.json")"
assert_contains "$ingest_output" "trajectory="

status_output="$("$MEMORY" status)"
assert_contains "$status_output" '"trajectory_envelopes": 1'

listed="$("$MEMORY" list-trajectories --producer trust-gate)"
assert_contains "$listed" '"producer": "trust-gate"'
assert_contains "$listed" "[REDACTED_SECRET]"
if [[ "$listed" == *"sk-thisshouldberedacted"* || "$listed" == *"am_us_should_not_survive"* ]]; then
  echo "trajectory ingestion leaked a secret-like value" >&2
  echo "$listed" >&2
  exit 1
fi

cat > "$TMP_DIR/no-evidence.json" <<'JSON'
{
  "producer": "skill-evolver",
  "objective": "skill-evolution",
  "status": "validated",
  "selected_agent": "skill-evolver",
  "security_classification": "internal"
}
JSON

if "$MEMORY" ingest-trajectory --json-file "$TMP_DIR/no-evidence.json" >"$TMP_DIR/trajectory-no-evidence.out" 2>&1; then
  echo "validated trajectory without evidence should have failed" >&2
  cat "$TMP_DIR/trajectory-no-evidence.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/trajectory-no-evidence.out")" "requires evidence_refs"

cat > "$TMP_DIR/bad-producer.json" <<'JSON'
{
  "producer": "unknown-agent",
  "objective": "route task",
  "status": "completed",
  "security_classification": "internal"
}
JSON

if "$MEMORY" ingest-trajectory --json-file "$TMP_DIR/bad-producer.json" >"$TMP_DIR/trajectory-bad-producer.out" 2>&1; then
  echo "unsupported producer should have failed" >&2
  cat "$TMP_DIR/trajectory-bad-producer.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/trajectory-bad-producer.out")" "unsupported producer"

echo "trajectory fabric tests passed"
