#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCHDOG="$ROOT_DIR/src/system/gateway-watchdog.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

log_file="$TMP_DIR/gateway-health.jsonl"
output="$(HERMES_GATEWAY_HEALTH_LOG="$log_file" "$WATCHDOG" --dry-run --required 9router || true)"
assert_contains "$output" "9router status="
assert_contains "$output" "log=$log_file"

test -f "$log_file"
log_content="$(cat "$log_file")"
assert_contains "$log_content" "\"gateway\":\"9router\""
assert_contains "$log_content" "\"action\":"

unsupported_output="$(HERMES_GATEWAY_HEALTH_LOG="$log_file" "$WATCHDOG" --dry-run --required not-a-gateway || true)"
assert_contains "$unsupported_output" "not-a-gateway status=unknown action=unsupported"

echo "gateway watchdog tests passed"
