#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"
RUNNER="$ROOT_DIR/src/system/hermes-run.sh"
GATE="$ROOT_DIR/src/system/yolo-gate.sh"
AUTO="$ROOT_DIR/src/system/cloud-model-auto.py"
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

python3 -m json.tool "$ROOT_DIR/config/cloud-model-catalog.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/cyberkimi-quarantine-policy.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/yolo-gate-policy.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/gateways/model_providers.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/profiles/profile_manifest.json" >/dev/null
python3 -m py_compile "$AUTO"
bash -n "$ROUTER"
bash -n "$GATE"

providers_output="$("$PICKER" providers)"
assert_contains "$providers_output" "adverserial"

list_output="$("$PICKER" list adverserial)"
assert_contains "$list_output" "lordx64/cyberkimi"
assert_contains "$list_output" "CyberKimi Quarantine"

keys_output="$(ADVERSERIAL_API_KEY=test "$PICKER" keys)"
assert_contains "$keys_output" $'adverserial\tADVERSERIAL_API_KEY\tloaded'

selection_file="$TMP_DIR/cyberkimi-selection.env"
HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" select adverserial lordx64/cyberkimi >/tmp/cyberkimi-select.out
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_OVERRIDE=adverserial"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=cyberkimi-quarantine"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=lordx64/cyberkimi"
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_API_KEY_ENV=ADVERSERIAL_API_KEY"

receipt_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" ADVERSERIAL_API_KEY=test "$PICKER" receipt)"
assert_contains "$receipt_output" "provider=adverserial"
assert_contains "$receipt_output" "model=lordx64/cyberkimi"
assert_contains "$receipt_output" "api_key_status=loaded"

route_output="$(ADVERSERIAL_API_KEY=test "$ROUTER" --json "review this owned service threat model" cyberkimi-quarantine)"
assert_contains "$route_output" '"profile": "cyberkimi-quarantine"'
assert_contains "$route_output" '"model": "cyberkimi-quarantine"'
assert_contains "$route_output" '"provider": "adverserial"'
assert_contains "$route_output" '"provider_model_id": "lordx64/cyberkimi"'
assert_contains "$route_output" '"access_method": "official_api"'
assert_contains "$route_output" '"cyberkimi-quarantine"'

runner_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" ADVERSERIAL_API_KEY=test "$RUNNER" --dry-run "defensive cyber review")"
assert_contains "$runner_output" '"model": "cyberkimi-quarantine"'
assert_contains "$runner_output" '"provider": "adverserial"'
assert_contains "$runner_output" '"provider_model_id": "lordx64/cyberkimi"'

approver_output="$(HERMES_YOLO_APPROVER_CHAIN='adverserial:lordx64/cyberkimi,onith:onith-1.0' ADVERSERIAL_API_KEY=test "$GATE" approver)"
assert_contains "$approver_output" "provider=adverserial"
assert_contains "$approver_output" "model=lordx64/cyberkimi"
assert_contains "$approver_output" "router_model=cyberkimi-quarantine"

blocked_output="$(HERMES_YOLO_MODE=retrieval ADVERSERIAL_API_KEY=test "$GATE" check "execute exploit module against a public target")"
assert_contains "$blocked_output" "decision=blocked"

human_output="$(HERMES_YOLO_MODE=retrieval ADVERSERIAL_API_KEY=test "$GATE" check "send the incident response message")"
assert_contains "$human_output" "decision=human_required"

auto_general="$(ADVERSERIAL_API_KEY=test python3 "$AUTO" --catalog "$ROOT_DIR/config/cloud-model-catalog.json" --query "security review this owned API" --json)"
if [[ "$auto_general" == *'"provider": "adverserial"'* ]]; then
  echo "CyberKimi should not auto-select for generic security text" >&2
  echo "$auto_general" >&2
  exit 1
fi

auto_explicit="$(ADVERSERIAL_API_KEY=test python3 "$AUTO" --catalog "$ROOT_DIR/config/cloud-model-catalog.json" --query "use cyberkimi quarantine for defensive incident response" --json)"
assert_contains "$auto_explicit" '"provider": "adverserial"'
assert_contains "$auto_explicit" '"model_id": "lordx64/cyberkimi"'

test -f "$ROOT_DIR/.agents/skills/cyberkimi-quarantine/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/cyberkimi-quarantine/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/cyberkimi-quarantine/meta.env"

echo "cyberkimi quarantine tests passed"
