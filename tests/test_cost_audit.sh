#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT="$ROOT_DIR/src/system/cost-audit.sh"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

text_output="$("$AUDIT")"
assert_contains "$text_output" "Hermes Cost Audit"
assert_contains "$text_output" "Status: PASS"
assert_contains "$text_output" "PASS: history_cap"
assert_contains "$text_output" '"mode": "background"'

json_output="$("$AUDIT" --json)"
assert_contains "$json_output" '"passed": true'
assert_contains "$json_output" '"name": "provider_bypass_blocks"'

python3 -m json.tool "$ROOT_DIR/config/hermes-cost-controls.example.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/openclaw-cost-controls.example.json" >/dev/null

echo "cost-audit tests passed"
