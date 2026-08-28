#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="$ROOT_DIR/src/system/memory-fabric.sh"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hermes-memory-classification.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
FAKE_CREDENTIAL_ONE="sk-$(printf 'E%.0s' {1..32})"
FAKE_CREDENTIAL_TWO="sk-$(printf 'F%.0s' {1..32})"

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

privileged_output="$("$MEMORY" add-node \
  --type FACT \
  --title "Privileged legal strategy" \
  --body "Attorney-client privileged analysis." \
  --security-classification LEGAL_PRIVILEGED \
  --validation-state observed)"
assert_contains "$privileged_output" "node="
privileged_id="${privileged_output#node=}"

if "$MEMORY" add-node \
  --type FACT \
  --title "Downgraded strategy" \
  --body "Attempt to downgrade privileged analysis." \
  --security-classification INTERNAL \
  --validation-state observed \
  --supersedes "$privileged_id" >"$TMP_DIR/memory-downgrade.out" 2>&1; then
  echo "classification downgrade should have failed" >&2
  cat "$TMP_DIR/memory-downgrade.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/memory-downgrade.out")" "flow rejected"

if "$MEMORY" add-node \
  --type FACT \
  --title "Wrong compartment strategy" \
  --body "Attempt to move privileged legal analysis into financial compartment." \
  --security-classification FINANCIAL \
  --validation-state observed \
  --supersedes "$privileged_id" >"$TMP_DIR/memory-compartment.out" 2>&1; then
  echo "cross-compartment supersession should have failed" >&2
  cat "$TMP_DIR/memory-compartment.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/memory-compartment.out")" "LEGAL_PRIVILEGED -> FINANCIAL"

if "$MEMORY" add-node \
  --type FACT \
  --title "Credential fact" \
  --body "api_key=$FAKE_CREDENTIAL_ONE" \
  --security-classification CREDENTIAL \
  --validation-state observed >"$TMP_DIR/memory-credential.out" 2>&1; then
  echo "CREDENTIAL non-provenance node should have failed" >&2
  cat "$TMP_DIR/memory-credential.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/memory-credential.out")" "CREDENTIAL records may only"

credential_output="$("$MEMORY" add-node \
  --type PROVENANCE \
  --title "Credential location only" \
  --body "A credential-like value was present in .env.local: api_key=$FAKE_CREDENTIAL_TWO" \
  --security-classification CREDENTIAL \
  --validation-state observed \
  --metadata '{"note":"token found but not exposed"}')"
assert_contains "$credential_output" "node="

retrieved="$("$MEMORY" retrieve "Credential location" --include-unsafe)"
assert_contains "$retrieved" "CREDENTIAL"
assert_contains "$retrieved" "[REDACTED_SECRET]"
if [[ "$retrieved" == *"$FAKE_CREDENTIAL_ONE"* || "$retrieved" == *"$FAKE_CREDENTIAL_TWO"* ]]; then
  echo "credential value should have been redacted" >&2
  echo "$retrieved" >&2
  exit 1
fi

cat > "$TMP_DIR/downgraded-trajectory.json" <<'JSON'
{
  "producer": "anchor-evaluator",
  "objective": "candidate-anchor-evaluation",
  "status": "validated",
  "security_classification": "INTERNAL",
  "evidence_refs": [
    {"type": "anchor-report", "path": "/tmp/report.json"}
  ],
  "metadata": {
    "validation_claim": true,
    "source_security_classification": "LEGAL_PRIVILEGED"
  }
}
JSON

if "$MEMORY" ingest-trajectory --json-file "$TMP_DIR/downgraded-trajectory.json" >"$TMP_DIR/trajectory-downgrade.out" 2>&1; then
  echo "trajectory classification downgrade should have failed" >&2
  cat "$TMP_DIR/trajectory-downgrade.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/trajectory-downgrade.out")" "flow rejected"

cat > "$TMP_DIR/cross-compartment-trajectory.json" <<'JSON'
{
  "producer": "anchor-evaluator",
  "objective": "candidate-anchor-evaluation",
  "status": "validated",
  "security_classification": "SECURITY_SENSITIVE",
  "evidence_refs": [
    {"type": "anchor-report", "path": "/tmp/report.json"}
  ],
  "metadata": {
    "validation_claim": true,
    "source_security_classification": "FINANCIAL"
  }
}
JSON

if "$MEMORY" ingest-trajectory --json-file "$TMP_DIR/cross-compartment-trajectory.json" >"$TMP_DIR/trajectory-compartment.out" 2>&1; then
  echo "trajectory cross-compartment flow should have failed" >&2
  cat "$TMP_DIR/trajectory-compartment.out" >&2
  exit 1
fi
assert_contains "$(cat "$TMP_DIR/trajectory-compartment.out")" "FINANCIAL -> SECURITY_SENSITIVE"

echo "memory classification tests passed"
