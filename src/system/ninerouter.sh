#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"
LOG_DIR="$ROOT_DIR/.hermes/9router"
PORT="${NINEROUTER_PORT:-20127}"
BASE_URL="${NINEROUTER_BASE_URL:-http://127.0.0.1:${PORT}/v1}"
DASHBOARD_URL="${NINEROUTER_DASHBOARD_URL:-${BASE_URL%/v1}}"

mkdir -p "$LOG_DIR"

if [[ -f "$ROOT_DIR/.env.cloud-models.local" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.cloud-models.local"
fi

usage() {
  cat <<'EOF'
Hermes 9Router Integration

Usage:
  src/system/ninerouter.sh status
  src/system/ninerouter.sh doctor
  src/system/ninerouter.sh install
  src/system/ninerouter.sh start
  src/system/ninerouter.sh start-bg
  src/system/ninerouter.sh models
  src/system/ninerouter.sh sync
  src/system/ninerouter.sh select [model-id]
  src/system/ninerouter.sh receipt
  src/system/ninerouter.sh env

Notes:
  - Hermes defaults 9Router to port 20127 to avoid OmniRoute's common 20128.
  - Override with NINEROUTER_PORT or NINEROUTER_BASE_URL if needed.
EOF
}

key_status() {
  if [[ -n "${NINEROUTER_API_KEY:-}" ]]; then
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
key = os.environ.get("NINEROUTER_API_KEY", "")
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
provider=9router
installed=$(command -v 9router >/dev/null 2>&1 && echo yes || echo no)
base_url=$BASE_URL
dashboard_url=$DASHBOARD_URL
api_key_env=NINEROUTER_API_KEY
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
  command -v 9router >/dev/null 2>&1 && echo "9router=found" || echo "9router=missing"
  echo
  echo "recommended_next:"
  if ! command -v 9router >/dev/null 2>&1; then
    echo "run: src/system/ninerouter.sh install"
  elif [[ "$(http_status /models)" == "unreachable" ]]; then
    echo "run: src/system/ninerouter.sh start-bg"
  elif [[ "$(key_status)" == "missing" ]]; then
    echo "set NINEROUTER_API_KEY in .env.cloud-models.local"
  else
    echo "run: src/system/ninerouter.sh sync && src/system/ninerouter.sh select"
  fi
}

install_ninerouter() {
  command -v npm >/dev/null 2>&1 || {
    echo "npm is required to install 9Router globally" >&2
    return 1
  }
  npm install -g 9router
}

start_foreground() {
  command -v 9router >/dev/null 2>&1 || {
    echo "9router command not found; run src/system/ninerouter.sh install" >&2
    return 1
  }
  9router --port "$PORT" --host "${NINEROUTER_HOST:-127.0.0.1}" --no-browser --log --skip-update
}

start_background() {
  command -v 9router >/dev/null 2>&1 || {
    echo "9router command not found; run src/system/ninerouter.sh install" >&2
    return 1
  }
  local log_file="$LOG_DIR/9router-$(date -u +%Y%m%dT%H%M%SZ).log"
  local -a router_cmd=(
    9router
    --port "$PORT"
    --host "${NINEROUTER_HOST:-127.0.0.1}"
    --no-browser
    --log
    --skip-update
  )
  if command -v setsid >/dev/null 2>&1 && command -v script >/dev/null 2>&1; then
    local command_text
    printf -v command_text '%q ' "${router_cmd[@]}"
    setsid script -qec "$command_text" /dev/null >"$log_file" 2>&1 < /dev/null &
  elif command -v setsid >/dev/null 2>&1; then
    setsid "${router_cmd[@]}" >"$log_file" 2>&1 < /dev/null &
  else
    nohup "${router_cmd[@]}" >"$log_file" 2>&1 < /dev/null &
  fi
  echo "pid=$!"
  echo "log=$log_file"
  echo "dashboard_url=$DASHBOARD_URL"
  echo "base_url=$BASE_URL"
}

models() {
  "$PICKER" list 9router
}

sync_models() {
  "$PICKER" sync 9router
}

select_ninerouter() {
  local model_id="${1:-auto}"
  "$PICKER" select 9router "$model_id"
  "$PICKER" receipt
}

env_hint() {
  cat <<EOF
export NINEROUTER_BASE_URL="$BASE_URL"
# Set this to the API key copied from the 9Router dashboard.
# If your local 9Router accepts client calls without auth, use a local placeholder.
# export NINEROUTER_API_KEY="local-9router-placeholder"
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status) status ;;
  doctor) doctor ;;
  install) install_ninerouter ;;
  start) start_foreground ;;
  start-bg) start_background ;;
  models) models ;;
  sync) sync_models ;;
  select) select_ninerouter "${1:-auto}" ;;
  receipt) "$PICKER" receipt ;;
  env) env_hint ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
