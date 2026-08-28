#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
MODEL="$ROOT_DIR/src/system/model.sh"
LOG_DIR="$ROOT_DIR/.hermes/omniroute"
BASE_URL="${OMNIROUTE_BASE_URL:-http://127.0.0.1:20128/v1}"
DASHBOARD_URL="${OMNIROUTE_DASHBOARD_URL:-${BASE_URL%/v1}}"

mkdir -p "$LOG_DIR"

if [[ -f "$ROOT_DIR/.env.cloud-models.local" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.cloud-models.local"
fi

usage() {
  cat <<'EOF'
Hermes OmniRoute Integration

Usage:
  src/system/omniroute.sh status
  src/system/omniroute.sh doctor
  src/system/omniroute.sh install
  src/system/omniroute.sh start
  src/system/omniroute.sh start-bg
  src/system/omniroute.sh models
  src/system/omniroute.sh sync
  src/system/omniroute.sh select [model-id]
  src/system/omniroute.sh import-nvidia
  src/system/omniroute.sh receipt
  src/system/omniroute.sh env
  src/system/omniroute.sh mcp

Notes:
  - Dashboard: http://127.0.0.1:20128
  - OpenAI-compatible API: http://127.0.0.1:20128/v1
  - API key comes from OmniRoute Dashboard -> Endpoints/API Keys.
EOF
}

key_status() {
  if [[ -n "${OMNIROUTE_API_KEY:-}" ]]; then
    echo "loaded"
  else
    echo "missing"
  fi
}

http_status() {
  local path="${1:-/models}"
  BASE_URL="$BASE_URL" PATH_SUFFIX="$path" python3 <<'PY'
import os
import urllib.error
import urllib.request

base = os.environ["BASE_URL"].rstrip("/")
path = os.environ["PATH_SUFFIX"]
url = base + path
headers = {"Accept": "application/json"}
key = os.environ.get("OMNIROUTE_API_KEY", "")
if key:
    headers["Authorization"] = f"Bearer {key}"
req = urllib.request.Request(url, headers=headers, method="GET")
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(f"http_{resp.status}")
except urllib.error.HTTPError as exc:
    print(f"http_{exc.code}")
except Exception:
    print("unreachable")
PY
}

status() {
  cat <<EOF
provider=omniroute
installed=$(command -v omniroute >/dev/null 2>&1 && echo yes || echo no)
base_url=$BASE_URL
dashboard_url=$DASHBOARD_URL
api_key_env=OMNIROUTE_API_KEY
api_key_status=$(key_status)
models_endpoint_status=$(http_status /models)
log_dir=$LOG_DIR
EOF
}

doctor() {
  status
  echo
  echo "checks:"
  command -v node >/dev/null 2>&1 && echo "node=found" || echo "node=missing"
  command -v npm >/dev/null 2>&1 && echo "npm=found" || echo "npm=missing"
  command -v omniroute >/dev/null 2>&1 && echo "omniroute=found" || echo "omniroute=missing"
  echo
  echo "recommended_next:"
  if ! command -v omniroute >/dev/null 2>&1; then
    echo "run: src/system/omniroute.sh install"
  elif [[ "$(http_status /models)" == "unreachable" ]]; then
    echo "run: src/system/omniroute.sh start-bg"
  elif [[ "$(key_status)" == "missing" ]]; then
    echo "set OMNIROUTE_API_KEY in .env.cloud-models.local"
  else
    echo "run: src/system/omniroute.sh sync && src/system/omniroute.sh select"
  fi
}

install_omniroute() {
  command -v npm >/dev/null 2>&1 || {
    echo "npm is required to install OmniRoute globally" >&2
    return 1
  }
  npm install -g omniroute
}

start_foreground() {
  command -v omniroute >/dev/null 2>&1 || {
    echo "omniroute command not found; run src/system/omniroute.sh install" >&2
    return 1
  }
  PORT="${OMNIROUTE_PORT:-20128}" omniroute serve --no-open --no-tray --no-recovery --log
}

start_background() {
  command -v omniroute >/dev/null 2>&1 || {
    echo "omniroute command not found; run src/system/omniroute.sh install" >&2
    return 1
  }
  local log_file="$LOG_DIR/omniroute-$(date -u +%Y%m%dT%H%M%SZ).log"
  local pid
  if command -v setsid >/dev/null 2>&1; then
    setsid env PORT="${OMNIROUTE_PORT:-20128}" \
      omniroute serve --no-open --no-tray --no-recovery --log \
      >"$log_file" 2>&1 < /dev/null &
  else
    nohup env PORT="${OMNIROUTE_PORT:-20128}" \
      omniroute serve --no-open --no-tray --no-recovery --log \
      >"$log_file" 2>&1 < /dev/null &
  fi
  pid="$!"
  echo "pid=$pid"
  echo "log=$log_file"
  echo "dashboard_url=$DASHBOARD_URL"
  echo "base_url=$BASE_URL"
}

models() {
  "$PICKER" list omniroute
}

sync_models() {
  "$PICKER" sync omniroute
}

select_omniroute() {
  local model_id="${1:-auto}"
  "$PICKER" select omniroute "$model_id"
  "$PICKER" receipt
}

import_nvidia() {
  local nvidia_key="${NVIDIA_API_KEY:-${NVIDIA_NIM_API_KEY:-}}"
  if [[ -z "$nvidia_key" ]]; then
    cat >&2 <<'EOF'
NVIDIA_API_KEY is not set.

Add your NVIDIA/NIM key to .env.cloud-models.local first:
  export NVIDIA_API_KEY="..."

Then run:
  src/system/omniroute.sh import-nvidia
EOF
    return 2
  fi

  command -v omniroute >/dev/null 2>&1 || {
    echo "omniroute command not found; run src/system/omniroute.sh install" >&2
    return 1
  }

  printf '%s' "$nvidia_key" | omniroute keys add nvidia --stdin >/dev/null 2>&1 || true
  omniroute nodes add \
    --provider nvidia \
    --name nvidia-nim \
    --base-url "https://integrate.api.nvidia.com/v1" \
    --auth-header "Authorization=Bearer ${nvidia_key}" >/dev/null

  echo "nvidia_provider=imported"
  echo "nvidia_base_url=https://integrate.api.nvidia.com/v1"
}

env_hint() {
  cat <<EOF
export OMNIROUTE_BASE_URL="$BASE_URL"
# Local OmniRoute accepts OpenAI-compatible /v1 calls without a management key.
# Hermes uses this placeholder to pass local API connector validation.
export OMNIROUTE_API_KEY="local-omniroute-placeholder"

# Optional NVIDIA/NIM upstream for nvidia/glm-5.2 through OmniRoute:
# export NVIDIA_API_KEY="..."
# src/system/omniroute.sh import-nvidia
EOF
}

mcp_info() {
  local root="${DASHBOARD_URL%/}"
  cat <<EOF
mcp_status=$root/api/mcp/status
mcp_tools=$root/api/mcp/tools
mcp_sse=$root/api/mcp/sse
mcp_stream=$root/api/mcp/stream
mcp_stdio_command=omniroute --mcp
a2a_json_rpc=$root/a2a
a2a_status=$root/api/a2a/status
a2a_tasks=$root/api/a2a/tasks
a2a_agent_card=$root/.well-known/agent.json
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status) status ;;
  doctor) doctor ;;
  install) install_omniroute ;;
  start) start_foreground ;;
  start-bg) start_background ;;
  models) models ;;
  sync) sync_models ;;
  select) select_omniroute "${1:-auto}" ;;
  import-nvidia) import_nvidia ;;
  receipt) "$PICKER" receipt ;;
  env) env_hint ;;
  mcp) mcp_info ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
