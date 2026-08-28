#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="$ROOT_DIR/config/hermes-direct-mode-policy.json"
SOUL="$ROOT_DIR/profiles/direct/SOUL.md"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

python3 -m json.tool "$POLICY" >/dev/null

python3 <<PY
import json
from pathlib import Path

policy = json.loads(Path("$POLICY").read_text())
assert policy["id"] == "direct_but_bounded"
assert policy["style"]["answer_directly"] is True
assert policy["style"]["avoid_moralizing"] is True
assert "malware" in policy["blocked_categories"]
assert "credential_theft" in policy["blocked_categories"]
assert "access_control_bypass" in policy["blocked_categories"]
assert "wholesale_safety_removal" in policy["blocked_categories"]
assert "coding" in policy["allowed_domains"]
assert "authorized_defensive_security" in policy["allowed_domains"]
PY

assert_contains "$(cat "$SOUL")" "Hermes Direct Mode"
assert_contains "$(cat "$SOUL")" "Avoid boilerplate"
assert_contains "$(cat "$SOUL")" "Refuse or redirect only"

json_output="$("$ROUTER" --json "ship the local code fix with tests" bounded-direct)"
assert_contains "$json_output" '"profile": "direct"'
assert_contains "$json_output" '"coding-review"'
assert_contains "$json_output" '"policy": "approved_api_connector_local_or_manual_handoff_only"'

report_output="$("$ROUTER" --report direct "local implementation task")"
assert_contains "$report_output" "direct-but-bounded policy"
assert_contains "$report_output" "Cost Controls"

echo "direct-mode policy tests passed"
