#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CATALOG="${HERMES_CLOUD_MODEL_CATALOG:-$ROOT_DIR/config/cloud-model-catalog.json}"
OUTPUT_DIR="${HERMES_CONTINUE_OUTPUT_DIR:-$ROOT_DIR/.hermes/continue}"
OUTPUT_FILE="${HERMES_CONTINUE_CONFIG:-$OUTPUT_DIR/config.yaml}"
USER_CONFIG="${CONTINUE_CONFIG_FILE:-$HOME/.continue/config.yaml}"

usage() {
  cat <<'EOF'
Hermes Continue Config Exporter

Usage:
  src/system/continue-config.sh generate [output-file]
  src/system/continue-config.sh install
  src/system/continue-config.sh show
  src/system/continue-config.sh path
  src/system/continue-config.sh doctor

Commands:
  generate  Generate a Continue config.yaml for Hermes model gateways.
  install   Back up ~/.continue/config.yaml and replace it with the generated config.
  show      Print the generated config.
  path      Print the generated config path.
  doctor    Check local Continue/Hermes integration state.

The generated config avoids embedding real provider secrets. It points Continue
at local OpenAI-compatible Hermes gateways such as 9Router, OmniRoute, and Onith.
EOF
}

has_code() {
  command -v code >/dev/null 2>&1
}

yaml_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

generate_config() {
  local output="${1:-$OUTPUT_FILE}"
  mkdir -p "$(dirname "$output")"

  CATALOG="$CATALOG" python3 <<'PY' > "$output"
import json
import os
import re
from pathlib import Path

catalog = json.loads(Path(os.environ["CATALOG"]).read_text(encoding="utf-8"))
providers = catalog.get("providers", {})

preferred = {
    "9router": [
        "auto",
        "auto/coding",
        "moonshotai/kimi-k3",
        "kimi/kimi-latest",
        "nvidia/glm-5.2",
        "glm/glm-5",
    ],
    "omniroute": [
        "auto",
        "auto/coding",
        "nvidia/glm-5.2",
    ],
    "onith": [
        "onith-1.0",
    ],
}

def clean_name(text):
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace('"', "'")

def find_model(provider_key, model_id):
    provider = providers.get(provider_key, {})
    for model in provider.get("models", []):
        if model.get("id") == model_id:
            return provider, model
    return provider, {"id": model_id, "label": model_id, "tier": ""}

print("name: Hermes Max")
print("version: 1.0.0")
print("schema: v1")
print("")
print("models:")

for provider_key, model_ids in preferred.items():
    provider = providers.get(provider_key)
    if not provider:
        continue
    api_base = provider.get("default_base_url", "")
    for model_id in model_ids:
        provider_data, model = find_model(provider_key, model_id)
        if not provider_data:
            continue
        label = clean_name(model.get("label", model_id))
        display_provider = clean_name(provider_data.get("display_name", provider_key))
        name = f"Hermes {display_provider} - {label}"
        print(f'  - name: "{name}"')
        print("    provider: openai")
        print(f'    model: "{model_id}"')
        if api_base:
            print(f'    apiBase: "{api_base}"')
        print('    apiKey: "hermes-local-gateway"')
        print("    useResponsesApi: false")
        print("    roles:")
        print("      - chat")
        print("      - edit")
        print("      - apply")
        if model.get("tier") != "router":
            print("      - summarize")
        print("    capabilities:")
        print("      - tool_use")
        print("    defaultCompletionOptions:")
        print("      temperature: 0.2")
        print("      maxTokens: 4096")
        print("")

print("context:")
print("  - provider: file")
print("  - provider: code")
print("  - provider: diff")
print("  - provider: terminal")
print("")
print("rules:")
print("  - Use the Hermes local model gateways for routing; do not embed real provider keys in this config.")
print("  - Keep destructive terminal actions behind explicit user approval.")
print("  - For security work, require owned target scope and report findings as artifacts.")
print("")
print("docs:")
print("  - name: Continue")
print("    startUrl: https://docs.continue.dev/")
print("  - name: Hermes Cloud Model Picker")
print("    startUrl: file://" + str(Path.cwd() / "docs" / "cloud-model-picker.md"))
PY

  chmod 600 "$output"
  echo "continue_config=$output"
}

install_config() {
  local generated
  generated="$(generate_config "$OUTPUT_FILE" | awk -F= '/^continue_config=/ {print $2}')"
  mkdir -p "$(dirname "$USER_CONFIG")"
  if [[ -f "$USER_CONFIG" ]]; then
    local backup="$USER_CONFIG.hermes-backup-$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$USER_CONFIG" "$backup"
    echo "backup=$backup"
  fi
  cp "$generated" "$USER_CONFIG"
  chmod 600 "$USER_CONFIG"
  echo "installed=$USER_CONFIG"
  echo "reload VS Code or use Continue's config refresh after installing."
}

doctor() {
  echo "continue_extension_id=Continue.continue"
  if has_code; then
    echo "vscode_cli=found"
    if code --list-extensions 2>/dev/null | grep -Fxq "Continue.continue"; then
      echo "continue_extension=installed"
    else
      echo "continue_extension=missing"
      echo "install_command=code --install-extension Continue.continue"
    fi
  else
    echo "vscode_cli=missing"
  fi
  echo "generated_config=$OUTPUT_FILE"
  [[ -f "$OUTPUT_FILE" ]] && echo "generated_config_status=present" || echo "generated_config_status=missing"
  echo "user_config=$USER_CONFIG"
  [[ -f "$USER_CONFIG" ]] && echo "user_config_status=present" || echo "user_config_status=missing"
  echo "9router_endpoint=http://127.0.0.1:20127/v1"
  echo "omniroute_endpoint=http://127.0.0.1:20128/v1"
}

command="${1:-generate}"
shift || true

case "$command" in
  generate) generate_config "${1:-$OUTPUT_FILE}" ;;
  install) install_config ;;
  show)
    if [[ ! -f "$OUTPUT_FILE" ]]; then
      generate_config "$OUTPUT_FILE" >/dev/null
    fi
    cat "$OUTPUT_FILE" ;;
  path) echo "$OUTPUT_FILE" ;;
  doctor) doctor ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
