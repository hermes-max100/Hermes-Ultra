#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NINE="$ROOT_DIR/src/system/ninerouter.sh"
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

status_output="$("$NINE" status)"
assert_contains "$status_output" "provider=9router"
assert_contains "$status_output" "base_url=http://127.0.0.1:20127/v1"
assert_contains "$status_output" "dashboard_url=http://127.0.0.1:20127"

doctor_output="$("$NINE" doctor)"
assert_contains "$doctor_output" "recommended_next:"

models_output="$("$NINE" models)"
assert_contains "$models_output" "9router"
assert_contains "$models_output" "auto/coding"
assert_contains "$models_output" "nvidia/glm-5.2"

select_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$NINE" select auto/coding)"
assert_contains "$select_output" "provider=9router"
assert_contains "$select_output" "model=auto/coding"
assert_contains "$select_output" "api_key_status=loaded"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=ninerouter-gateway"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=auto/coding"

shortcut_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" nine)"
assert_contains "$shortcut_output" "provider=9router"
assert_contains "$shortcut_output" "model=auto"

route_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "route through 9router")"
assert_contains "$route_output" '"model": "ninerouter-gateway"'
assert_contains "$route_output" '"provider": "9router"'
assert_contains "$route_output" '"provider_model_id": "auto"'
assert_contains "$route_output" '"access_method": "official_api"'

glm_shortcut_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" nine-glm)"
assert_contains "$glm_shortcut_output" "provider=9router"
assert_contains "$glm_shortcut_output" "model=nvidia/glm-5.2"

glm_route_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "route glm through 9router")"
assert_contains "$glm_route_output" '"model": "ninerouter-gateway"'
assert_contains "$glm_route_output" '"provider": "9router"'
assert_contains "$glm_route_output" '"provider_model_id": "nvidia/glm-5.2"'

echo "9router integration tests passed"
