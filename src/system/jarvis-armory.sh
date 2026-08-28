#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -f "$ROOT_DIR/.env.cloud-models.local" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.cloud-models.local"
fi

JARVIS_DIR="${JARVIS_ARMORY_HOME:-$ROOT_DIR/.hermes/jarvis/JARVIS-OS-v1.2.0-tool-armory}"
ARCHIVE="${JARVIS_ARMORY_ARCHIVE:-/tmp/codex-web-uploads/f-1UdywG/JARVIS-OS-v1.2.0-tool-armory.zip}"
ARCHIVE_SHA="${JARVIS_ARMORY_ARCHIVE_SHA:-/tmp/codex-web-uploads/f-RRVAWL/JARVIS-OS-v1.2.0-tool-armory.zip.sha256}"
WHEEL="${JARVIS_ARMORY_WHEEL:-/tmp/codex-web-uploads/f-Jvr8tX/jarvis_os-1.2.0-py3-none-any.whl}"
WHEEL_SHA="${JARVIS_ARMORY_WHEEL_SHA:-/tmp/codex-web-uploads/f-qBy8xe/jarvis_os-1.2.0-py3-none-any.whl.sha256}"
CONFIG_TEMPLATE="$ROOT_DIR/config/jarvis-armory.config.local.example.json"
CONFIG_FILE="${JARVIS_CONFIG:-$JARVIS_DIR/config.local.json}"
LOG_DIR="$ROOT_DIR/.hermes/jarvis/logs"
PID_FILE="$ROOT_DIR/.hermes/jarvis/jarvis-armory.pid"
PORT="${JARVIS_PORT:-4700}"
HOST="${JARVIS_HOST:-127.0.0.1}"

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"

usage() {
  cat <<'EOF'
Hermes JARVIS Tool Armory

Usage:
  src/system/jarvis-armory.sh status
  src/system/jarvis-armory.sh verify-artifacts
  src/system/jarvis-armory.sh unpack
  src/system/jarvis-armory.sh configure [--force]
  src/system/jarvis-armory.sh install
  src/system/jarvis-armory.sh start
  src/system/jarvis-armory.sh stop
  src/system/jarvis-armory.sh restart
  src/system/jarvis-armory.sh doctor
  src/system/jarvis-armory.sh logs
  src/system/jarvis-armory.sh url

Secrets stay in environment variables. This script does not write API keys,
OAuth client secrets, or service tokens into config files.
EOF
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

hash_matches() {
  local file="$1"
  local sha_file="$2"
  [[ -f "$file" && -f "$sha_file" ]] || return 1
  local expected actual
  expected="$(awk '{print $1; exit}' "$sha_file")"
  actual="$(sha256sum "$file" | awk '{print $1; exit}')"
  [[ "$expected" == "$actual" ]]
}

verify_artifacts() {
  require_cmd sha256sum
  hash_matches "$ARCHIVE" "$ARCHIVE_SHA" || die "JARVIS archive SHA256 mismatch or missing file: $ARCHIVE"
  log "archive_sha256=ok"
  hash_matches "$WHEEL" "$WHEEL_SHA" || die "JARVIS wheel SHA256 mismatch or missing file: $WHEEL"
  log "wheel_sha256=ok"
}

unpack_armory() {
  require_cmd unzip
  verify_artifacts
  if [[ -d "$JARVIS_DIR" && -f "$JARVIS_DIR/pyproject.toml" ]]; then
    log "jarvis_dir_exists=$JARVIS_DIR"
    return 0
  fi
  mkdir -p "$(dirname "$JARVIS_DIR")"
  unzip -q "$ARCHIVE" -d "$(dirname "$JARVIS_DIR")"
  [[ -f "$JARVIS_DIR/pyproject.toml" ]] || die "unpack did not create expected JARVIS directory: $JARVIS_DIR"
  log "unpacked=$JARVIS_DIR"
}

configure_armory() {
  local force=0
  if [[ "${1:-}" == "--force" ]]; then
    force=1
  fi
  [[ -f "$CONFIG_TEMPLATE" ]] || die "missing config template: $CONFIG_TEMPLATE"
  unpack_armory
  if [[ -f "$CONFIG_FILE" && "$force" != "1" ]]; then
    log "config_exists=$CONFIG_FILE"
    return 0
  fi
  cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"
  mkdir -p "$JARVIS_DIR/notes" "$JARVIS_DIR/data/browser_artifacts"
  log "configured=$CONFIG_FILE"
}

install_armory() {
  require_cmd python3
  require_cmd bash
  configure_armory
  (
    cd "$JARVIS_DIR"
    JARVIS_SKIP_BROWSER_INSTALL="${JARVIS_SKIP_BROWSER_INSTALL:-1}" bash install.sh
  )
  configure_armory
  log "installed=$JARVIS_DIR"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

health() {
  curl -fsS "http://$HOST:$PORT/api/health" 2>/dev/null || return 1
}

api_status() {
  if [[ -n "${JARVIS_API_TOKEN:-}" ]]; then
    curl -fsS -H "Authorization: Bearer $JARVIS_API_TOKEN" "http://$HOST:$PORT/api/status" 2>/dev/null
  else
    curl -fsS "http://$HOST:$PORT/api/status" 2>/dev/null
  fi
}

start_armory() {
  require_cmd curl
  configure_armory
  if is_running && health >/dev/null; then
    log "already_running=http://$HOST:$PORT"
    return 0
  fi
  [[ -x "$JARVIS_DIR/.venv/bin/python" ]] || install_armory
  local log_file="$LOG_DIR/jarvis-armory-$(date -u +%Y%m%dT%H%M%SZ).log"
  (
    cd "$JARVIS_DIR"
    export JARVIS_CONFIG="$CONFIG_FILE"
    export PORT="$PORT"
    if command -v setsid >/dev/null 2>&1; then
      setsid bash scripts/run.sh > "$log_file" 2>&1 < /dev/null &
    else
      nohup bash scripts/run.sh > "$log_file" 2>&1 < /dev/null &
    fi
    echo "$!" > "$PID_FILE"
  )
  local attempt
  for attempt in {1..20}; do
    health >/dev/null && break
    sleep 0.5
  done
  health >/dev/null || die "JARVIS did not become healthy; see $log_file"
  log "started=http://$HOST:$PORT"
  log "pid_file=$PID_FILE"
  log "log=$log_file"
}

stop_armory() {
  if ! is_running; then
    log "not_running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
  log "stopped"
}

status_armory() {
  echo "jarvis_dir=$JARVIS_DIR"
  echo "config=$CONFIG_FILE"
  echo "url=http://$HOST:$PORT"
  echo "archive_present=$([[ -f "$ARCHIVE" ]] && echo yes || echo no)"
  echo "archive_sha256=$([[ -f "$ARCHIVE" && -f "$ARCHIVE_SHA" ]] && hash_matches "$ARCHIVE" "$ARCHIVE_SHA" && echo ok || echo unavailable)"
  echo "wheel_present=$([[ -f "$WHEEL" ]] && echo yes || echo no)"
  echo "wheel_sha256=$([[ -f "$WHEEL" && -f "$WHEEL_SHA" ]] && hash_matches "$WHEEL" "$WHEEL_SHA" && echo ok || echo unavailable)"
  echo "unpacked=$([[ -f "$JARVIS_DIR/pyproject.toml" ]] && echo yes || echo no)"
  echo "venv=$([[ -x "$JARVIS_DIR/.venv/bin/python" ]] && echo yes || echo no)"
  echo "running=$(is_running && echo yes || echo no)"
  if health >/dev/null; then
    echo "health=ok"
  else
    echo "health=unavailable"
  fi
}

doctor() {
  status_armory
  echo
  verify_artifacts
  python3 -m json.tool "$CONFIG_TEMPLATE" >/dev/null
  log "config_template_json=ok"
  if [[ -f "$CONFIG_FILE" ]]; then
    python3 -m json.tool "$CONFIG_FILE" >/dev/null
    log "config_json=ok"
  fi
  if health >/dev/null; then
    api_status | python3 -m json.tool || true
  fi
}

tail_logs() {
  find "$LOG_DIR" -maxdepth 1 -name 'jarvis-armory-*.log' -type f 2>/dev/null | sort | tail -1 | while read -r file; do
    echo "log=$file"
    tail -80 "$file"
  done
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status) status_armory ;;
  verify-artifacts) verify_artifacts ;;
  unpack) unpack_armory ;;
  configure) configure_armory "$@" ;;
  install) install_armory ;;
  start) start_armory ;;
  stop) stop_armory ;;
  restart) stop_armory; start_armory ;;
  doctor) doctor ;;
  logs) tail_logs ;;
  url) echo "http://$HOST:$PORT" ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
