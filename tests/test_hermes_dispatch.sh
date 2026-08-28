#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPATCH="$ROOT_DIR/src/system/hermes-dispatch.sh"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
export HERMES_CLOUD_MODEL_SELECTION_FILE="$TMP_DIR/default-selection.env"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

json_output="$("$DISPATCH" --json --thinking high "fix this failing test")"
assert_contains "$json_output" '"profile": "direct"'
assert_contains "$json_output" '"thinking_level": "Level 5 (High)"'
assert_contains "$json_output" '"skill_source": "dynamic_skill_engine"'
assert_contains "$json_output" '"agentic-coding-router"'

legal_skill_output="$("$DISPATCH" --json --project amazon-appeal "red team this appeal filing and build evidence matrix from PDFs")"
assert_contains "$legal_skill_output" '"skill_source": "dynamic_skill_engine"'
assert_contains "$legal_skill_output" '"legal-evidence-os"'
assert_contains "$legal_skill_output" '"appellate-filing-red-team"'

report_output="$("$DISPATCH" --thinking critical "threat model my owned SaaS API auth flow")"
assert_contains "$report_output" "Hermes Dispatch"
assert_contains "$report_output" "**Skill Set**:"
assert_contains "$report_output" "**Skill Source**: dynamic_skill_engine"
assert_contains "$report_output" "**Thinking Level**: Level 7 (Critical)"
assert_contains "$report_output" "_Auto-routed by Hermes Dynamic Router"

selection_file="$TMP_DIR/selection.env"
HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" select nvidia meta/llama-3.3-70b-instruct >/dev/null

selected_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NVIDIA_API_KEY=test "$DISPATCH" --json "use selected model")"
assert_contains "$selected_output" '"model": "nvidia-nim"'
assert_contains "$selected_output" '"provider_model_id": "meta/llama-3.3-70b-instruct"'

inline_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$TMP_DIR/inline-selection.env" NVIDIA_API_KEY=test "$DISPATCH" --json --model-key nvidia-nim --model-id meta/custom "use inline model")"
assert_contains "$inline_output" '"model": "nvidia-nim"'
assert_contains "$inline_output" '"provider_model_id": "meta/custom"'

echo "hermes-dispatch tests passed"
