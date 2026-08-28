#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POWER="$ROOT_DIR/src/system/hermes-power-up.sh"
INVENTORY="$ROOT_DIR/src/system/workspace-inventory.sh"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

python3 -m json.tool "$ROOT_DIR/config/hermes-power-setup.json" >/dev/null

status_output="$("$POWER" status)"
assert_contains "$status_output" "Hermes Max status"
assert_contains "$status_output" "provider="
assert_contains "$status_output" "enabled_skills="

inventory_output="$("$INVENTORY" "$ROOT_DIR")"
assert_contains "$inventory_output" "Hermes Workspace Inventory"
assert_contains "$inventory_output" "Current Hermes Max Components"
assert_contains "$inventory_output" "src/system/hermes-power-up.sh"

echo "hermes power-up tests passed"
