#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$ROOT_DIR/src/system/yolo-gate.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
export HERMES_CLOUD_KEYS_FILE="$TMP_DIR/empty-cloud-models.env"
: > "$HERMES_CLOUD_KEYS_FILE"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

chmod +x "$GATE"

class_output="$("$GATE" classify "look on github reddit x threads and skill hub for latest revenue skills")"
[[ "$class_output" == "public_retrieval_gate" ]]

video_class_output="$("$GATE" classify "analyze this public Instagram reel and extract transcript and frames")"
[[ "$video_class_output" == "public_retrieval_gate" ]]

off_output="$(NINEROUTER_API_KEY=test "$GATE" check "look on github and reddit for current revenue skills")"
assert_contains "$off_output" "decision=human_required"
assert_contains "$off_output" "reason=yolo_mode_off"

retrieval_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "look on github and reddit for current revenue skills")"
assert_contains "$retrieval_output" "decision=model_approved"
assert_contains "$retrieval_output" "class=public_retrieval_gate"
assert_contains "$retrieval_output" "provider=9router"
assert_contains "$retrieval_output" "model=moonshotai/kimi-k3"

video_retrieval_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "analyze this public Instagram reel and extract transcript and frames")"
assert_contains "$video_retrieval_output" "decision=model_approved"
assert_contains "$video_retrieval_output" "class=public_retrieval_gate"

custom_output="$(HERMES_YOLO_MODE=retrieval HERMES_YOLO_APPROVER_CHAIN='9router:openai/sol-5.6,9router:fable/fable-5,nvidia:glm-5.2' NINEROUTER_API_KEY=test "$GATE" check "research source links")"
assert_contains "$custom_output" "decision=model_approved"
assert_contains "$custom_output" "model=openai/sol-5.6"

fallback_output="$(HERMES_YOLO_MODE=retrieval HERMES_YOLO_APPROVER_CHAIN='9router:fable/fable-5,nvidia:glm-5.2' NVIDIA_API_KEY=test "$GATE" check "research source links")"
assert_contains "$fallback_output" "decision=model_approved"
assert_contains "$fallback_output" "provider=nvidia"
assert_contains "$fallback_output" "model=glm-5.2"

send_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "send the approved proposal to the client")"
assert_contains "$send_output" "decision=human_required"
assert_contains "$send_output" "class=human_required"

delete_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "delete old chats and change privacy settings")"
assert_contains "$delete_output" "decision=human_required"

block_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" check "run unauthorized public target scanning")"
assert_contains "$block_output" "decision=blocked"

env_output="$(HERMES_YOLO_MODE=retrieval NINEROUTER_API_KEY=test "$GATE" env)"
assert_contains "$env_output" "HERMES_YOLO_MODE=retrieval"
assert_contains "$env_output" "HERMES_MODEL_OVERRIDE=moonshotai/kimi-k3"

echo "yolo gate tests passed"
