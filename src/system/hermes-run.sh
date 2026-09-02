#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DISPATCH="$ROOT_DIR/src/system/hermes-dispatch.sh"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
SELECTION_FILE_EXPLICIT=0
if [[ -n "${HERMES_CLOUD_MODEL_SELECTION_FILE:-}" ]]; then
  SELECTION_FILE_EXPLICIT=1
fi
CLOUD_SELECTION="${HERMES_CLOUD_MODEL_SELECTION_FILE:-$ROOT_DIR/.hermes/cloud-model-selection.env}"
CLOUD_KEYS="${HERMES_CLOUD_KEYS_FILE:-$ROOT_DIR/.env.cloud-models.local}"

AUTO=0
DRY_RUN=0
PROFILE="direct"
PROJECT=""
SYSTEM_PROMPT="${HERMES_RUN_SYSTEM_PROMPT:-You are Hermes. Answer clearly and directly within the configured task scope.}"
QUERY=""

usage() {
  cat <<'EOF'
Hermes Cloud Runner

Usage:
  src/system/hermes-run.sh [options] <query>

Options:
  --auto                 Auto-pick the best configured cloud model for this query.
  --dry-run              Show route/request metadata without calling the provider.
  --profile <name>       Dispatch profile. Default: direct.
  --project <name>       Project overlay for dynamic skills.
  --system <text>        System prompt for the cloud model call.
  -h, --help             Show help.

Requires provider API keys in .env.cloud-models.local or the environment.
Currently supports OpenAI-compatible providers in the catalog.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) AUTO=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --system) SYSTEM_PROMPT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *) QUERY="${QUERY:+$QUERY }$1"; shift ;;
  esac
done

if [[ $# -gt 0 ]]; then
  QUERY="${QUERY:+$QUERY }$*"
fi
[[ -n "$QUERY" ]] || { usage >&2; exit 2; }

if [[ -f "$CLOUD_KEYS" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    name="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    [[ -n "${!name:-}" ]] && continue
    eval "export ${name}=${value}"
  done < "$CLOUD_KEYS"
fi

if [[ "$AUTO" == "1" ]]; then
  if [[ "$DRY_RUN" == "1" && "$SELECTION_FILE_EXPLICIT" != "1" ]]; then
    tmp_selection="$(mktemp)"
    export HERMES_CLOUD_MODEL_SELECTION_FILE="$tmp_selection"
    CLOUD_SELECTION="$tmp_selection"
  fi
  "$PICKER" auto "$QUERY" >/dev/null
fi

if [[ -f "$CLOUD_SELECTION" ]]; then
  # shellcheck disable=SC1090
  source "$CLOUD_SELECTION"
fi

dispatch_args=(--json --profile "$PROFILE")
[[ -n "$PROJECT" ]] && dispatch_args+=(--project "$PROJECT")
route_json="$("$DISPATCH" "${dispatch_args[@]}" "$QUERY")"

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "$route_json"
  exit 0
fi

ROOT_DIR="$ROOT_DIR" ROUTE_JSON="$route_json" SYSTEM_PROMPT="$SYSTEM_PROMPT" USER_PROMPT="$QUERY" python3 <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
sys.path.insert(0, str(root / "src"))
from hermes_ultra.provider_runtime import ProviderRequestPolicy

route = json.loads(os.environ["ROUTE_JSON"])
provider = route.get("provider", "")
model = route.get("provider_model_id", "")

provider_env = {
    "onith": ("", "ONITH_BASE_URL", "http://127.0.0.1:11434/v1"),
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "perplexity": ("PERPLEXITY_API_KEY", "PERPLEXITY_BASE_URL", "https://api.perplexity.ai"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    "venice": ("VENICE_API_KEY", "VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    "zenmux": ("ZENMUX_API_KEY", "ZENMUX_BASE_URL", "https://zenmux.ai/api/v1/"),
    "omniroute": ("OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1"),
    "9router": ("NINEROUTER_API_KEY", "NINEROUTER_BASE_URL", "http://127.0.0.1:20127/v1"),
}

if provider not in provider_env:
    raise SystemExit(f"provider is not supported by hermes-run yet: {provider}")
if not model:
    raise SystemExit("no provider_model_id selected; run cloud-model-picker.sh select or hermes-run.sh --auto")

key_env, base_env, default_base = provider_env[provider]
api_key = os.environ.get(key_env, "") if key_env else ""
if key_env and not api_key:
    raise SystemExit(f"missing API key: {key_env}")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def model_metadata() -> dict:
    merged = {}
    for path in (
        root / "config/cloud-model-catalog.json",
        Path(os.environ.get("HERMES_CLOUD_MODEL_LOCAL_CATALOG", root / ".hermes/cloud-model-catalog.local.json")),
    ):
        catalog = load_json(path)
        provider_row = catalog.get("providers", {}).get(provider, {}) if isinstance(catalog.get("providers"), dict) else {}
        rows = provider_row.get("models", []) if isinstance(provider_row, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("id", "")) == model:
                merged.update(row)
    return merged


policy = ProviderRequestPolicy()
local_settings = {
    "ollama_num_ctx": os.environ.get("HERMES_OLLAMA_NUM_CTX") or os.environ.get("OLLAMA_NUM_CTX"),
    "num_ctx": os.environ.get("HERMES_NUM_CTX"),
    "max_output_tokens": os.environ.get("HERMES_LOCAL_MAX_OUTPUT_TOKENS"),
}
limits = policy.resolve_limits(
    provider=provider,
    model=model,
    model_metadata=model_metadata(),
    local_runtime_settings=local_settings,
)

base_url = os.environ.get(base_env, default_base).rstrip("/")
url = f"{base_url}/chat/completions"
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": os.environ["SYSTEM_PROMPT"]},
        {"role": "user", "content": os.environ["USER_PROMPT"]},
    ],
    "temperature": float(os.environ.get("HERMES_RUN_TEMPERATURE", "0.2")),
}
explicit_cap = os.environ.get("HERMES_RUN_MAX_OUTPUT_TOKENS", "").strip()
if explicit_cap:
    try:
        parsed_cap = int(explicit_cap)
    except ValueError as exc:
        raise SystemExit("HERMES_RUN_MAX_OUTPUT_TOKENS must be a positive integer") from exc
    if parsed_cap <= 0:
        raise SystemExit("HERMES_RUN_MAX_OUTPUT_TOKENS must be a positive integer")
    payload["max_tokens"] = parsed_cap
payload = policy.apply_limits(payload, limits)

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"


def request_once(request_payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=int(os.environ.get("HERMES_RUN_TIMEOUT", "120"))) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


max_limit_retries = int(os.environ.get("HERMES_RUN_LIMIT_RETRIES", "1"))
if max_limit_retries < 0 or max_limit_retries > 2:
    raise SystemExit("HERMES_RUN_LIMIT_RETRIES must be between 0 and 2")
retry_count = 0
while True:
    try:
        data = request_once(payload)
        break
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if retry_count < max_limit_retries and policy.is_limit_error(body):
            try:
                corrected = policy.build_retry_payload(payload, error_text=body, limits=limits)
            except ValueError:
                corrected = None
            if corrected is not None and corrected != payload:
                payload = corrected
                retry_count += 1
                continue
        raise SystemExit(f"provider HTTP error {exc.code}: {body[:1000]}")

choices = data.get("choices", [])
if not choices:
    print(json.dumps(data, indent=2))
    raise SystemExit(0)
message = choices[0].get("message", {})
print(message.get("content", ""))
print()
print("---")
print(
    f"model={route.get('model')} provider={provider} provider_model_id={model} "
    f"skill_source={route.get('skill_source')} limit_source={limits.source} limit_retries={retry_count}"
)
PY
