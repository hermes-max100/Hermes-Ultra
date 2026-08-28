#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"
RUNNER="$ROOT_DIR/src/system/hermes-run.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
export HERMES_CLOUD_KEYS_FILE="$TMP_DIR/default-empty-cloud-models.env"
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

list_output="$("$PICKER" list nvidia)"
assert_contains "$list_output" "meta/llama-3.3-70b-instruct"
assert_contains "$list_output" "glm-5.2"
assert_contains "$list_output" "NVIDIA NIM"

providers_output="$("$PICKER" providers)"
assert_contains "$providers_output" "onith"
assert_contains "$providers_output" "openai"
assert_contains "$providers_output" "gemini"
assert_contains "$providers_output" "perplexity"
assert_contains "$providers_output" "openrouter"
assert_contains "$providers_output" "venice"
assert_contains "$providers_output" "adverserial"
assert_contains "$providers_output" "9router"

keys_output="$(OPENROUTER_API_KEY=test "$PICKER" keys)"
assert_contains "$keys_output" $'onith\t\tnot_required'
assert_contains "$keys_output" $'openrouter\tOPENROUTER_API_KEY\tloaded'
assert_contains "$keys_output" $'nvidia\tNVIDIA_API_KEY\tmissing'
assert_contains "$keys_output" $'adverserial\tADVERSERIAL_API_KEY\tmissing'
assert_contains "$keys_output" $'9router\tNINEROUTER_API_KEY\tmissing'

cyberkimi_list="$("$PICKER" list adverserial)"
assert_contains "$cyberkimi_list" "lordx64/cyberkimi"
assert_contains "$cyberkimi_list" "CyberKimi Quarantine"

omni_list="$("$PICKER" list omniroute)"
assert_contains "$omni_list" "auto/coding"
assert_contains "$omni_list" "nvidia/glm-5.2"
assert_contains "$omni_list" "OmniRoute"

onith_list="$("$PICKER" list onith)"
assert_contains "$onith_list" "onith-1.0"
assert_contains "$onith_list" "Onith 1.0 Local"

selection_file="$TMP_DIR/selection.env"
keys_file="$TMP_DIR/.env.cloud-models.local"
local_catalog="$TMP_DIR/cloud-model-catalog.local.json"

setup_output="$(HERMES_CLOUD_KEYS_FILE="$keys_file" "$PICKER" setup)"
assert_contains "$setup_output" "created_env_file=$keys_file"
[[ -f "$keys_file" ]]

sync_output="$(HERMES_CLOUD_KEYS_FILE="$keys_file" HERMES_CLOUD_MODEL_LOCAL_CATALOG="$local_catalog" "$PICKER" sync nvidia)"
assert_contains "$sync_output" "nvidia"
assert_contains "$sync_output" "missing_key:NVIDIA_API_KEY"
[[ -f "$local_catalog" ]]

cat > "$local_catalog" <<'JSON'
{
  "version": "1.0.0",
  "providers": {
    "nvidia": {
      "display_name": "NVIDIA NIM",
      "models": [
        {
          "id": "provider-synced-model",
          "label": "Provider Synced Model",
          "tier": "synced",
          "best_for": ["synced", "reasoning"],
          "source": "provider_models_api"
        }
      ]
    }
  }
}
JSON

synced_list="$(HERMES_CLOUD_MODEL_LOCAL_CATALOG="$local_catalog" "$PICKER" list nvidia)"
assert_contains "$synced_list" "provider-synced-model"

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" HERMES_CLOUD_MODEL_LOCAL_CATALOG="$local_catalog" \
  "$PICKER" select nvidia provider-synced-model >/tmp/cloud-picker-synced-select.out
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=provider-synced-model"

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" select onith onith-1.0 >/tmp/cloud-picker-onith.out
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_OVERRIDE=onith"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=local-private"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=onith-1.0"
assert_contains "$(cat "$selection_file")" "ONITH_BASE_URL=http://127.0.0.1:11434/v1"
onith_receipt="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" "$PICKER" receipt)"
assert_contains "$onith_receipt" "provider=onith"
assert_contains "$onith_receipt" "model=onith-1.0"
assert_contains "$onith_receipt" "api_key_status=not_applicable"
onith_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" "$RUNNER" --dry-run "use local onith")"
assert_contains "$onith_route" '"model": "local-private"'
assert_contains "$onith_route" '"provider": "onith"'
assert_contains "$onith_route" '"provider_model_id": "onith-1.0"'
assert_contains "$onith_route" '"access_method": "local_runtime"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" select nvidia meta/llama-3.3-70b-instruct >/tmp/cloud-picker-select.out

assert_contains "$(cat "$selection_file")" "HERMES_MODEL_SELECTION_MODE=manual"
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_OVERRIDE=nvidia"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=nvidia-nim"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=meta/llama-3.3-70b-instruct"

set -a
source "$selection_file"
set +a

route_output="$(NVIDIA_API_KEY=test "$ROUTER" --json "use selected model" direct)"
assert_contains "$route_output" '"model": "nvidia-nim"'
assert_contains "$route_output" '"provider": "nvidia"'
assert_contains "$route_output" '"provider_model_id": "meta/llama-3.3-70b-instruct"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" select nvidia glm-5.2 >/tmp/cloud-picker-glm.out
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_OVERRIDE=nvidia"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=nvidia-nim"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=glm-5.2"
assert_contains "$(cat "$selection_file")" "HERMES_PROVIDER_API_KEY_ENV=NVIDIA_API_KEY"

receipt_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" NVIDIA_API_KEY=test "$PICKER" receipt)"
assert_contains "$receipt_output" "provider=nvidia"
assert_contains "$receipt_output" "model=glm-5.2"
assert_contains "$receipt_output" "api_key_status=loaded"

openrouter_file="$TMP_DIR/openrouter-selection.env"
HERMES_CLOUD_MODEL_SELECTION_FILE="$openrouter_file" \
  "$PICKER" select openrouter openrouter/auto >/tmp/cloud-picker-openrouter.out
assert_contains "$(cat "$openrouter_file")" "HERMES_PROVIDER_OVERRIDE=openrouter"
assert_contains "$(cat "$openrouter_file")" "HERMES_MODEL_OVERRIDE=openrouter/auto"
openrouter_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$openrouter_file" OPENROUTER_API_KEY=test "$RUNNER" --dry-run "route through openrouter")"
assert_contains "$openrouter_route" '"provider": "openrouter"'
assert_contains "$openrouter_route" '"provider_model_id": "openrouter/auto"'
assert_contains "$openrouter_route" '"access_method": "official_api"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$openrouter_file" \
  "$PICKER" select openrouter moonshotai/kimi-k3 >/tmp/cloud-picker-openrouter-kimi.out
assert_contains "$(cat "$openrouter_file")" "HERMES_PROVIDER_OVERRIDE=openrouter"
assert_contains "$(cat "$openrouter_file")" "HERMES_MODEL_OVERRIDE=moonshotai/kimi-k3"
openrouter_kimi_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$openrouter_file" OPENROUTER_API_KEY=test "$RUNNER" --dry-run "route kimi k3")"
assert_contains "$openrouter_kimi_route" '"provider": "openrouter"'
assert_contains "$openrouter_kimi_route" '"provider_model_id": "moonshotai/kimi-k3"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
  "$PICKER" custom zenmux provider/custom-model >/tmp/cloud-picker-custom.out
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_KEY_OVERRIDE=zenmux-router"
assert_contains "$(cat "$selection_file")" "HERMES_MODEL_OVERRIDE=provider/custom-model"

HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" "$PICKER" clear >/tmp/cloud-picker-clear.out
[[ ! -f "$selection_file" ]]

omni_file="$TMP_DIR/omniroute-selection.env"
HERMES_CLOUD_MODEL_SELECTION_FILE="$omni_file" \
  "$PICKER" select omniroute auto/coding >/tmp/cloud-picker-omniroute.out
assert_contains "$(cat "$omni_file")" "HERMES_PROVIDER_OVERRIDE=omniroute"
assert_contains "$(cat "$omni_file")" "HERMES_MODEL_KEY_OVERRIDE=omniroute-gateway"
assert_contains "$(cat "$omni_file")" "HERMES_MODEL_OVERRIDE=auto/coding"

omni_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$omni_file" OMNIROUTE_API_KEY=test "$RUNNER" --dry-run "coding task")"
assert_contains "$omni_route" '"model": "omniroute-gateway"'
assert_contains "$omni_route" '"provider": "omniroute"'
assert_contains "$omni_route" '"provider_model_id": "auto/coding"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$omni_file" \
  "$PICKER" select omniroute nvidia/glm-5.2 >/tmp/cloud-picker-omniroute-glm.out
assert_contains "$(cat "$omni_file")" "HERMES_PROVIDER_OVERRIDE=omniroute"
assert_contains "$(cat "$omni_file")" "HERMES_MODEL_OVERRIDE=nvidia/glm-5.2"

omni_glm_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$omni_file" OMNIROUTE_API_KEY=test "$RUNNER" --dry-run "use glm through omniroute")"
assert_contains "$omni_glm_route" '"model": "omniroute-gateway"'
assert_contains "$omni_glm_route" '"provider": "omniroute"'
assert_contains "$omni_glm_route" '"provider_model_id": "nvidia/glm-5.2"'

nine_file="$TMP_DIR/9router-selection.env"
HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" \
  "$PICKER" select 9router auto/coding >/tmp/cloud-picker-9router.out
assert_contains "$(cat "$nine_file")" "HERMES_PROVIDER_OVERRIDE=9router"
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_KEY_OVERRIDE=ninerouter-gateway"
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_OVERRIDE=auto/coding"

nine_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "coding task")"
assert_contains "$nine_route" '"model": "ninerouter-gateway"'
assert_contains "$nine_route" '"provider": "9router"'
assert_contains "$nine_route" '"provider_model_id": "auto/coding"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" \
  "$PICKER" select 9router nvidia/glm-5.2 >/tmp/cloud-picker-9router-glm.out
assert_contains "$(cat "$nine_file")" "HERMES_PROVIDER_OVERRIDE=9router"
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_OVERRIDE=nvidia/glm-5.2"

nine_glm_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "use glm through 9router")"
assert_contains "$nine_glm_route" '"model": "ninerouter-gateway"'
assert_contains "$nine_glm_route" '"provider": "9router"'
assert_contains "$nine_glm_route" '"provider_model_id": "nvidia/glm-5.2"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" \
  "$PICKER" select 9router moonshotai/kimi-k3 >/tmp/cloud-picker-9router-kimi.out
assert_contains "$(cat "$nine_file")" "HERMES_PROVIDER_OVERRIDE=9router"
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_OVERRIDE=moonshotai/kimi-k3"

nine_kimi_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "use kimi k3 through 9router")"
assert_contains "$nine_kimi_route" '"model": "ninerouter-gateway"'
assert_contains "$nine_kimi_route" '"provider": "9router"'
assert_contains "$nine_kimi_route" '"provider_model_id": "moonshotai/kimi-k3"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" \
  "$PICKER" select 9router kimi/kimi-latest >/tmp/cloud-picker-9router-kimi-latest.out
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_OVERRIDE=kimi/kimi-latest"

nine_kimi_latest_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "use kimi latest through 9router")"
assert_contains "$nine_kimi_latest_route" '"model": "ninerouter-gateway"'
assert_contains "$nine_kimi_latest_route" '"provider": "9router"'
assert_contains "$nine_kimi_latest_route" '"provider_model_id": "kimi/kimi-latest"'

HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" \
  "$PICKER" select 9router clinepass/cline-pass/kimi-k2.7-code >/tmp/cloud-picker-9router-kimi-code.out
assert_contains "$(cat "$nine_file")" "HERMES_MODEL_OVERRIDE=clinepass/cline-pass/kimi-k2.7-code"

nine_kimi_code_route="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_file" NINEROUTER_API_KEY=test "$RUNNER" --dry-run "use kimi code through 9router")"
assert_contains "$nine_kimi_code_route" '"model": "ninerouter-gateway"'
assert_contains "$nine_kimi_code_route" '"provider": "9router"'
assert_contains "$nine_kimi_code_route" '"provider_model_id": "clinepass/cline-pass/kimi-k2.7-code"'

auto_file="$TMP_DIR/auto-selection.env"
auto_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$auto_file" NVIDIA_API_KEY=test "$PICKER" auto "deep reasoning coding architecture task")"
assert_contains "$auto_output" '"provider"'
assert_contains "$(cat "$auto_file")" "HERMES_MODEL_SELECTION_MODE=auto"
assert_contains "$(cat "$auto_file")" "HERMES_MODEL_OVERRIDE="

dry_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$auto_file" NVIDIA_API_KEY=test "$RUNNER" --dry-run "deep reasoning coding architecture task")"
assert_contains "$dry_output" '"provider_model_id"'
assert_contains "$dry_output" '"access_method": "official_api"'

runner_auto_file="$TMP_DIR/runner-auto.env"
runner_auto_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$runner_auto_file" NVIDIA_API_KEY=test "$RUNNER" --auto --dry-run "fast coding task")"
assert_contains "$runner_auto_output" '"model": "nvidia-nim"'
assert_contains "$(cat "$runner_auto_file")" "HERMES_MODEL_SELECTION_MODE=auto"

omni_auto_file="$TMP_DIR/runner-omni-auto.env"
omni_auto_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$omni_auto_file" OMNIROUTE_API_KEY=test "$RUNNER" --auto --dry-run "cheap fallback coding task")"
assert_contains "$omni_auto_output" '"provider": "omniroute"'
assert_contains "$(cat "$omni_auto_file")" "HERMES_MODEL_SELECTION_MODE=auto"

nine_auto_file="$TMP_DIR/runner-9router-auto.env"
nine_auto_output="$(HERMES_CLOUD_MODEL_SELECTION_FILE="$nine_auto_file" NINEROUTER_API_KEY=test "$RUNNER" --auto --dry-run "cheap fallback coding task")"
assert_contains "$nine_auto_output" '"provider": "9router"'
assert_contains "$(cat "$nine_auto_file")" "HERMES_MODEL_SELECTION_MODE=auto"

python3 -m json.tool "$ROOT_DIR/config/cloud-model-catalog.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/external-skill-sources.json" >/dev/null

echo "cloud-model-picker tests passed"
