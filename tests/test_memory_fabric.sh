#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="$ROOT_DIR/src/system/memory-fabric.sh"
TMP_DIR="$(mktemp -d)"
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

init_output="$("$MEMORY" init)"
assert_contains "$init_output" "initialized="

decision_output="$("$MEMORY" add-node \
  --type DECISION \
  --title "Scout cannot promote skills" \
  --body "Scout discovers candidates. Trust Gate evaluates. Governance promotes." \
  --validation-state validated \
  --confidence 0.95)"
assert_contains "$decision_output" "node="
decision_id="${decision_output#node=}"

failure_output="$("$MEMORY" add-node \
  --type FAILURE \
  --title "Router missed deadline trigger" \
  --body "legal-evidence-os failed to rank for service deadline terms" \
  --validation-state observed \
  --confidence 0.8)"
failure_id="${failure_output#node=}"

edge_output="$("$MEMORY" add-edge \
  --src "$failure_id" \
  --dst "$decision_id" \
  --type DERIVED_FROM \
  --confidence 0.7)"
assert_contains "$edge_output" "edge="

trajectory_output="$("$MEMORY" record-trajectory \
  --objective skill-evolution \
  --status promoted \
  --skill legal-evidence-os \
  --proposal-id proposal-1 \
  --prediction "new trigger terms should rank" \
  --observed "validation passed and proposal promoted" \
  --delta "routing improved" \
  --evidence-refs "[\"proposal-1-validation\"]")"
assert_contains "$trajectory_output" "trajectory="

retrieve_output="$("$MEMORY" retrieve "deadline trigger" --type FAILURE)"
assert_contains "$retrieve_output" "Router missed deadline trigger"

replacement_output="$("$MEMORY" add-node \
  --type FAILURE \
  --title "Router deadline trigger resolved" \
  --body "deadline trigger failure was resolved by proposal-1" \
  --validation-state validated \
  --supersedes "$failure_id" \
  --confidence 0.9)"
assert_contains "$replacement_output" "node="

safe_retrieve="$("$MEMORY" retrieve "legal-evidence-os failed" --type FAILURE)"
if [[ "$safe_retrieve" == *"legal-evidence-os failed to rank"* ]]; then
  echo "Deprecated superseded record should not appear in default retrieval" >&2
  echo "$safe_retrieve" >&2
  exit 1
fi

status_output="$("$MEMORY" status)"
assert_contains "$status_output" '"nodes"'
assert_contains "$status_output" '"trajectories"'

echo "memory fabric tests passed"
