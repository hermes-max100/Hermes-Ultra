#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTINUE="$ROOT_DIR/src/system/continue-config.sh"
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

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "Expected output not to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

output_file="$TMP_DIR/config.yaml"
generate_output="$("$CONTINUE" generate "$output_file")"
assert_contains "$generate_output" "continue_config=$output_file"

config="$(cat "$output_file")"
assert_contains "$config" "name: Hermes Max"
assert_contains "$config" "schema: v1"
assert_contains "$config" "provider: openai"
assert_contains "$config" "apiBase: \"http://127.0.0.1:20127/v1\""
assert_contains "$config" "apiBase: \"http://127.0.0.1:20128/v1\""
assert_contains "$config" "apiBase: \"http://127.0.0.1:11434/v1\""
assert_contains "$config" "model: \"kimi/kimi-latest\""
assert_contains "$config" "model: \"moonshotai/kimi-k3\""
assert_contains "$config" "model: \"nvidia/glm-5.2\""
assert_contains "$config" "model: \"onith-1.0\""
assert_contains "$config" "apiKey: \"hermes-local-gateway\""
assert_not_contains "$config" "am_us_"
assert_not_contains "$config" "sk-"

doctor_output="$(HERMES_CONTINUE_CONFIG="$output_file" "$CONTINUE" doctor)"
assert_contains "$doctor_output" "continue_extension_id=Continue.continue"
assert_contains "$doctor_output" "generated_config_status=present"
assert_contains "$doctor_output" "9router_endpoint=http://127.0.0.1:20127/v1"

show_output="$(HERMES_CONTINUE_CONFIG="$output_file" "$CONTINUE" show)"
assert_contains "$show_output" "Hermes 9Router"

python3 -m json.tool "$ROOT_DIR/config/hermes-power-setup.json" >/dev/null

echo "continue config tests passed"
