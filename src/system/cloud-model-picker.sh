#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CATALOG="${HERMES_CLOUD_MODEL_CATALOG:-$ROOT_DIR/config/cloud-model-catalog.json}"
LOCAL_CATALOG="${HERMES_CLOUD_MODEL_LOCAL_CATALOG:-$ROOT_DIR/.hermes/cloud-model-catalog.local.json}"
SELECTION_FILE="${HERMES_CLOUD_MODEL_SELECTION_FILE:-$ROOT_DIR/.hermes/cloud-model-selection.env}"
AUTO_SELECTOR="$ROOT_DIR/src/system/cloud-model-auto.py"
SYNCER="$ROOT_DIR/src/system/cloud-model-sync.py"
CLOUD_KEYS="${HERMES_CLOUD_KEYS_FILE:-$ROOT_DIR/.env.cloud-models.local}"
KEYS_TEMPLATE="$ROOT_DIR/config/cloud-models.env.example"

if [[ -f "$CLOUD_KEYS" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    name="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    [[ -n "${!name:-}" ]] && continue
    eval "export ${name}=${value}"
  done < "$CLOUD_KEYS"
fi

usage() {
  cat <<'EOF'
Hermes Cloud Model Picker

Usage:
  src/system/cloud-model-picker.sh list [provider]
  src/system/cloud-model-picker.sh providers
  src/system/cloud-model-picker.sh keys
  src/system/cloud-model-picker.sh setup
  src/system/cloud-model-picker.sh sync [provider|all]
  src/system/cloud-model-picker.sh auto <query>
  src/system/cloud-model-picker.sh select <provider> <model-id>
  src/system/cloud-model-picker.sh custom <provider> <model-id>
  src/system/cloud-model-picker.sh receipt
  src/system/cloud-model-picker.sh show
  src/system/cloud-model-picker.sh clear
  src/system/cloud-model-picker.sh env

Examples:
  src/system/cloud-model-picker.sh list nvidia
  src/system/cloud-model-picker.sh setup
  src/system/cloud-model-picker.sh sync all
  src/system/cloud-model-picker.sh auto "fix this failing test"
  src/system/cloud-model-picker.sh select nvidia meta/llama-3.3-70b-instruct
  src/system/cloud-model-picker.sh custom nvidia nvidia/custom-model-id
  src/system/cloud-model-picker.sh receipt
  source "$(src/system/cloud-model-picker.sh env)"
  src/system/dynamic-router.sh --json "use selected cloud model" direct
EOF
}

json_query() {
  local mode="$1"
  local provider="${2:-}"
  local model="${3:-}"
  CATALOG="$CATALOG" LOCAL_CATALOG="$LOCAL_CATALOG" MODE="$mode" PROVIDER="$provider" MODEL="$model" python3 <<'PY'
import json
import os
import sys
from pathlib import Path

def load_json(path, default):
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default

def merge_catalogs(base, local):
    merged = json.loads(json.dumps(base))
    providers = merged.setdefault("providers", {})
    for provider_key, local_provider in local.get("providers", {}).items():
        if provider_key not in providers:
            continue
        existing = {item["id"]: item for item in providers[provider_key].get("models", [])}
        for item in local_provider.get("models", []):
            model_id = item.get("id")
            if not model_id:
                continue
            existing[model_id] = item
        providers[provider_key]["models"] = list(existing.values())
    return merged

catalog = merge_catalogs(
    load_json(os.environ["CATALOG"], {"providers": {}}),
    load_json(os.environ["LOCAL_CATALOG"], {"providers": {}}),
)
mode = os.environ["MODE"]
provider = os.environ.get("PROVIDER", "")
model = os.environ.get("MODEL", "")
providers = catalog.get("providers", {})

if mode == "providers":
    for key, data in providers.items():
        print(f"{key}\t{data.get('display_name', key)}")
elif mode == "list":
    selected = providers.items() if not provider else [(provider, providers.get(provider))]
    for key, data in selected:
        if data is None:
            raise SystemExit(f"unknown provider: {key}")
        print(f"# {key} - {data.get('display_name', key)}")
        for item in data.get("models", []):
            best_for = ",".join(item.get("best_for", []))
            print(f"{key}\t{item['id']}\t{item.get('label', item['id'])}\t{item.get('tier', '')}\t{best_for}")
elif mode == "validate":
    data = providers.get(provider)
    if data is None:
        raise SystemExit(f"unknown provider: {provider}")
    ids = {item["id"] for item in data.get("models", [])}
    if model not in ids:
        raise SystemExit(f"model not in catalog for {provider}: {model}")
    print(json.dumps(data))
elif mode == "provider":
    data = providers.get(provider)
    if data is None:
        raise SystemExit(f"unknown provider: {provider}")
    print(json.dumps(data))
elif mode == "keys":
    for key, data in providers.items():
        credential = data.get("credential_env_var", "")
        base_env = data.get("base_url_env_var", "")
        status = "not_required" if not credential else ("loaded" if os.environ.get(credential) else "missing")
        base_url = os.environ.get(base_env, data.get("default_base_url", ""))
        print(f"{key}\t{credential}\t{status}\t{base_url}")
elif mode == "catalog-json":
    print(json.dumps(catalog))
else:
    raise SystemExit(f"unknown mode: {mode}")
PY
}

write_selection() {
  local provider="$1"
  local model="$2"
  local provider_json="$3"
  local mode="${4:-manual}"

  mkdir -p "$(dirname "$SELECTION_FILE")"
PROVIDER="$provider" MODEL="$model" PROVIDER_JSON="$provider_json" MODE="$mode" python3 <<'PY' > "$SELECTION_FILE"
import json
import os
import shlex

provider = os.environ["PROVIDER"]
model = os.environ["MODEL"]
mode = os.environ["MODE"]
data = json.loads(os.environ["PROVIDER_JSON"])

router_model = data["router_model"]
base_url = data.get("default_base_url", "")
base_url_env = data.get("base_url_env_var", "")
credential_env = data.get("credential_env_var", "")

print("# Generated by src/system/cloud-model-picker.sh")
print(f"export HERMES_MODEL_SELECTION_MODE={shlex.quote(mode)}")
print(f"export HERMES_PROVIDER_OVERRIDE={shlex.quote(provider)}")
print(f"export HERMES_MODEL_KEY_OVERRIDE={shlex.quote(router_model)}")
print(f"export HERMES_MODEL_OVERRIDE={shlex.quote(model)}")
if credential_env:
    print(f"export HERMES_PROVIDER_API_KEY_ENV={shlex.quote(credential_env)}")
if base_url and base_url_env:
    print(f"export {base_url_env}={shlex.quote(base_url)}")
    print(f"export HERMES_PROVIDER_BASE_URL_ENV={shlex.quote(base_url_env)}")
PY
  chmod 600 "$SELECTION_FILE"
  echo "selected provider=$provider model=$model"
  echo "env_file=$SELECTION_FILE"
}

setup_env() {
  if [[ -f "$CLOUD_KEYS" ]]; then
    chmod 600 "$CLOUD_KEYS"
    echo "env_file_exists=$CLOUD_KEYS"
    return 0
  fi
  mkdir -p "$(dirname "$CLOUD_KEYS")"
  cp "$KEYS_TEMPLATE" "$CLOUD_KEYS"
  chmod 600 "$CLOUD_KEYS"
  echo "created_env_file=$CLOUD_KEYS"
  echo "edit this file and add only the provider keys you use"
}

sync_models() {
  local provider="${1:-all}"
  python3 "$SYNCER" --catalog "$CATALOG" --local-catalog "$LOCAL_CATALOG" --provider "$provider"
}

receipt() {
  if [[ ! -f "$SELECTION_FILE" ]]; then
    echo "no cloud model selected"
    return 1
  fi

  (
    # shellcheck disable=SC1090
    source "$SELECTION_FILE"
    provider="${HERMES_PROVIDER_OVERRIDE:-unknown}"
    model="${HERMES_MODEL_OVERRIDE:-unknown}"
    router_model="${HERMES_MODEL_KEY_OVERRIDE:-unknown}"
    mode="${HERMES_MODEL_SELECTION_MODE:-unknown}"
    key_env="${HERMES_PROVIDER_API_KEY_ENV:-}"
    base_env="${HERMES_PROVIDER_BASE_URL_ENV:-}"
    key_status="not_applicable"
    if [[ -n "$key_env" ]]; then
      if [[ -n "${!key_env:-}" ]]; then
        key_status="loaded"
      else
        key_status="missing"
      fi
    fi
    base_url=""
    if [[ -n "$base_env" ]]; then
      base_url="${!base_env:-}"
    fi
    cat <<EOF
provider=$provider
model=$model
router_model=$router_model
selection_mode=$mode
api_key_env=${key_env:-none}
api_key_status=$key_status
base_url=${base_url:-default_or_unset}
selection_file=$SELECTION_FILE
EOF
  )
}

cmd="${1:-}"
case "$cmd" in
  list)
    json_query list "${2:-}" ;;
  providers)
    json_query providers ;;
  keys)
    json_query keys ;;
  setup)
    setup_env ;;
  sync)
    sync_models "${2:-all}" ;;
  select)
    [[ $# -eq 3 ]] || { usage >&2; exit 2; }
    provider_json="$(json_query validate "$2" "$3")"
    write_selection "$2" "$3" "$provider_json" manual ;;
  auto)
    [[ $# -ge 2 ]] || { usage >&2; exit 2; }
    query="${*:2}"
    tmp_catalog="$(mktemp)"
    trap 'rm -f "$tmp_catalog"' EXIT
    json_query catalog-json > "$tmp_catalog"
    selected_json="$(python3 "$AUTO_SELECTOR" --catalog "$tmp_catalog" --query "$query" --json)"
    provider="$(SELECTED_JSON="$selected_json" python3 - <<'PY'
import json, os
print(json.loads(os.environ["SELECTED_JSON"])["provider"])
PY
)"
    model="$(SELECTED_JSON="$selected_json" python3 - <<'PY'
import json, os
print(json.loads(os.environ["SELECTED_JSON"])["model_id"])
PY
)"
    provider_json="$(json_query provider "$provider")"
    write_selection "$provider" "$model" "$provider_json" auto
    echo "$selected_json" ;;
  custom)
    [[ $# -eq 3 ]] || { usage >&2; exit 2; }
    provider_json="$(json_query provider "$2")"
    write_selection "$2" "$3" "$provider_json" manual ;;
  show)
    if [[ -f "$SELECTION_FILE" ]]; then
      cat "$SELECTION_FILE"
    else
      echo "no cloud model selected"
    fi ;;
  receipt)
    receipt ;;
  clear)
    rm -f "$SELECTION_FILE"
    echo "cloud model selection cleared" ;;
  env)
    echo "$SELECTION_FILE" ;;
  -h|--help|help|"")
    usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2 ;;
esac
