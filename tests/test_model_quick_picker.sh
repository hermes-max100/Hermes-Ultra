#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="$ROOT_DIR/src/system/model.sh"
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

onith_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" "$MODEL" onith)"
assert_contains "$onith_output" "provider=onith"
assert_contains "$onith_output" "model=onith-1.0"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=onith-1.0"

glm_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" "$MODEL" glm)"
assert_contains "$glm_output" "provider=nvidia"
assert_contains "$glm_output" "model=glm-5.2"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=glm-5.2"

omni_glm_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OMNIROUTE_API_KEY=test "$MODEL" omni-glm)"
assert_contains "$omni_glm_output" "provider=omniroute"
assert_contains "$omni_glm_output" "model=nvidia/glm-5.2"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=nvidia/glm-5.2"

nine_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" nine)"
assert_contains "$nine_output" "provider=9router"
assert_contains "$nine_output" "model=auto"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=ninerouter-gateway"

nine_glm_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" nine-glm)"
assert_contains "$nine_glm_output" "provider=9router"
assert_contains "$nine_glm_output" "model=nvidia/glm-5.2"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=nvidia/glm-5.2"

kimi_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" kimi3)"
assert_contains "$kimi_output" "provider=9router"
assert_contains "$kimi_output" "model=moonshotai/kimi-k3"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=ninerouter-gateway"

kimi_openrouter_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" OPENROUTER_API_KEY=test "$MODEL" kimi3-openrouter)"
assert_contains "$kimi_openrouter_output" "provider=openrouter"
assert_contains "$kimi_openrouter_output" "model=moonshotai/kimi-k3"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=openai-reasoning"

kimi_latest_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" kimi)"
assert_contains "$kimi_latest_output" "provider=9router"
assert_contains "$kimi_latest_output" "model=kimi/kimi-latest"

kimi_code_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" kimi-code)"
assert_contains "$kimi_code_output" "provider=9router"
assert_contains "$kimi_code_output" "model=moonshotai/kimi-k3"

kimi27_code_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NINEROUTER_API_KEY=test "$MODEL" kimi27-code)"
assert_contains "$kimi27_code_output" "provider=9router"
assert_contains "$kimi27_code_output" "model=clinepass/cline-pass/kimi-k2.7-code"

list_output="$("$MODEL" list)"
assert_contains "$list_output" "onith-1.0"
assert_contains "$list_output" "glm-5.2"
assert_contains "$list_output" "nvidia/glm-5.2"
assert_contains "$list_output" "9Router Auto"
assert_contains "$list_output" "moonshotai/kimi-k3"
assert_contains "$list_output" "kimi/kimi-latest"
assert_contains "$list_output" "clinepass/cline-pass/kimi-k2.7-code"

keys_output="$("$MODEL" keys)"
assert_contains "$keys_output" "nvidia"
assert_contains "$keys_output" "onith"
assert_contains "$keys_output" "9router"

echo "model quick picker tests passed"
