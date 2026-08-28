#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="$ROOT_DIR/src/system/bridge-client.sh"
MANIFEST="$ROOT_DIR/bridge/hermes_bridge_manifest.json"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

python3 -m json.tool "$MANIFEST" >/dev/null

summary="$("$CLIENT" --summary)"
assert_contains "$summary" '"categories": 13'
assert_contains "$summary" '"auth_cookie": "hermes_session"'

chat_list="$("$CLIENT" --list chat_streaming)"
assert_contains "$chat_list" '"/api/chat/start"'
assert_contains "$chat_list" '"streaming": true'

found="$("$CLIENT" --find POST /api/chat/start)"
assert_contains "$found" '"found": true'
assert_contains "$found" '"category": "chat_streaming"'

curl_command="$("$CLIENT" --curl POST /api/profile/switch '{"profile":"legal"}')"
assert_contains "$curl_command" "/api/profile/switch"
assert_contains "$curl_command" "hermes-bridge-cookies"

if "$CLIENT" --find GET /api/not-real >/tmp/bridge-not-real.out 2>/tmp/bridge-not-real.err; then
    echo "Expected unknown endpoint lookup to fail" >&2
    exit 1
fi

echo "bridge-client tests passed"
