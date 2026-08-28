#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OMNI="$ROOT_DIR/src/system/omniroute.sh"
MODEL="$ROOT_DIR/src/system/model.sh"
RUNNER="$ROOT_DIR/src/system/hermes-run.sh"
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

selection_file="$TMP_DIR/selection.env"

status_output="$("$OMNI" status)"
assert_contains "$status_output" "provider=omniroute"
assert_contains "$status_output" "base_url=http://127.0.0.1:20128/v1"
assert_contains "$status_output" "dashboard_url=http://127.0.0.1:20128"

doctor_output="$("$OMNI" doctor)"
assert_contains "$doctor_output" "recommended_next:"

models_output="$("$OMNI" models)"
assert_contains "$models_output" "omniroute"
assert_contains "$models_output" "auto/coding"
assert_contains "$models_output" "nvidia/glm-5.2"

mcp_output="$("$OMNI" mcp)"
assert_contains "$mcp_output" "mcp_status=http://127.0.0.1:20128/api/mcp/status"
assert_contains "$mcp_output" "mcp_tools=http://127.0.0.1:20128/api/mcp/tools"
assert_contains "$mcp_output" "mcp_sse=http://127.0.0.1:20128/api/mcp/sse"
assert_contains "$mcp_output" "mcp_stdio_command=omniroute --mcp"
assert_contains "$mcp_output" "a2a_json_rpc=http://127.0.0.1:20128/a2a"
assert_contains "$mcp_output" "a2a_status=http://127.0.0.1:20128/api/a2a/status"
assert_contains "$mcp_output" "a2a_agent_card=http://127.0.0.1:20128/.well-known/agent.json"

select_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$OMNI" select auto/coding)"
assert_contains "$select_output" "provider=omniroute"
assert_contains "$select_output" "model=auto/coding"
assert_contains "$select_output" "api_key_status=loaded"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=omniroute-gateway"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=auto/coding"

shortcut_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$MODEL" omni)"
assert_contains "$shortcut_output" "provider=omniroute"
assert_contains "$shortcut_output" "model=auto"

route_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$RUNNER" --dry-run "route through omniroute")"
assert_contains "$route_output" '"model": "omniroute-gateway"'
assert_contains "$route_output" '"provider": "omniroute"'
assert_contains "$route_output" '"provider_model_id": "auto"'
assert_contains "$route_output" '"access_method": "official_api"'

glm_shortcut_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$MODEL" omni-glm)"
assert_contains "$glm_shortcut_output" "provider=omniroute"
assert_contains "$glm_shortcut_output" "model=nvidia/glm-5.2"

glm_route_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$RUNNER" --dry-run "route glm through omniroute")"
assert_contains "$glm_route_output" '"model": "omniroute-gateway"'
assert_contains "$glm_route_output" '"provider": "omniroute"'
assert_contains "$glm_route_output" '"provider_model_id": "nvidia/glm-5.2"'

echo "omniroute integration tests passed"
