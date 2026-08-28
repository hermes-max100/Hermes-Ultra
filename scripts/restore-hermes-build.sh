#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBLITERATUS_DIR="$ROOT_DIR/OBLITERATUS"
INSTALL_DIR="$ROOT_DIR/.hermes/install"
STATE_DIR="$ROOT_DIR/.hermes/state"
LOG_FILE="${HERMES_INSTALL_LOG_FILE:-$INSTALL_DIR/install.log}"
SYSTEM_LOG_FILE="${HERMES_INSTALL_SYSTEM_LOG_FILE:-$INSTALL_DIR/system.log}"
FIRST_RUN_MARKER="$STATE_DIR/first-run-config.done"
SKIP_OBLITERATUS_INSTALL=0
VERIFY_ONLY=0
ENABLE_SYSTEM_LOG_MONITOR=1
SYSTEM_LOG_PID=""

usage() {
  cat <<'EOF'
Usage:
  scripts/restore-hermes-build.sh [options]

Options:
  --verify-only               Run dependency checks and first-run config only.
  --skip-obliteratus-install  Skip Python venv/package installation.
  --no-system-log-monitor     Do not attempt journalctl/dmesg install monitoring.
  -h, --help                  Show help.

Logs:
  .hermes/install/install.log
  .hermes/install/system.log
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

check_python_module() {
  python3 - "$1" <<'PY' >/dev/null 2>&1 || return 1
import importlib.util
import sys
module = sys.argv[1]
raise SystemExit(0 if importlib.util.find_spec(module) else 1)
PY
}

setup_logging() {
  mkdir -p "$INSTALL_DIR" "$STATE_DIR"
  touch "$LOG_FILE" "$SYSTEM_LOG_FILE"
  exec > >(tee -a "$LOG_FILE") 2>&1
  log "install_log=$LOG_FILE"
  log "system_log=$SYSTEM_LOG_FILE"
}

start_system_log_monitor() {
  [[ "$ENABLE_SYSTEM_LOG_MONITOR" == "1" ]] || return 0
  {
    printf '[%s] system log monitor start\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if command -v journalctl >/dev/null 2>&1 && journalctl -n 1 >/dev/null 2>&1; then
      printf '[%s] source=journalctl -f\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      journalctl -f -o short-iso
    elif command -v dmesg >/dev/null 2>&1 && dmesg >/dev/null 2>&1; then
      printf '[%s] source=dmesg snapshot\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      dmesg
    else
      printf '[%s] no readable journalctl/dmesg source available\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf 'uname=%s\n' "$(uname -a 2>/dev/null || true)"
      printf 'pwd=%s\n' "$ROOT_DIR"
    fi
  } >> "$SYSTEM_LOG_FILE" 2>&1 &
  SYSTEM_LOG_PID="$!"
  log "system log monitor pid=$SYSTEM_LOG_PID"
}

stop_system_log_monitor() {
  if [[ -n "${SYSTEM_LOG_PID:-}" ]]; then
    kill "$SYSTEM_LOG_PID" >/dev/null 2>&1 || true
    wait "$SYSTEM_LOG_PID" >/dev/null 2>&1 || true
    log "system log monitor stopped"
  fi
}

check_deps() {
  log "checking required dependencies"
  local deps=(bash chmod date mkdir tee awk uname xargs)
  for dep in "${deps[@]}"; do
    require_cmd "$dep"
  done
  require_cmd python3
  if [[ "$VERIFY_ONLY" != "1" && "$SKIP_OBLITERATUS_INSTALL" != "1" ]]; then
    check_python_module venv || die "python3 venv module is required; install python3-venv"
  fi
  log "required dependencies found"

  local optional=(git curl tar sha256sum journalctl dmesg)
  for dep in "${optional[@]}"; do
    if command -v "$dep" >/dev/null 2>&1; then
      log "optional dependency available: $dep"
    else
      log "optional dependency missing: $dep"
    fi
  done
}

first_run_config() {
  mkdir -p \
    "$ROOT_DIR/.hermes/obliteratus" \
    "$ROOT_DIR/.hermes/refresh" \
    "$ROOT_DIR/.hermes/reports" \
    "$ROOT_DIR/.skills/logs" \
    "$ROOT_DIR/.skills/reports" \
    "$STATE_DIR"

  if [[ -f "$FIRST_RUN_MARKER" ]]; then
    log "first-run skill OS configuration already complete"
    return 0
  fi

  log "running first-run skill OS configuration"
  cat > "$STATE_DIR/router.conf" <<'EOF'
DEFAULT_PROFILE=direct
DEFAULT_SKILL_LIMIT=5
ENABLE_DYNAMIC_SKILL_ENGINE=true
ENABLE_LISTWISE_RERANKER=true
EOF

  cat > "$STATE_DIR/sweep.conf" <<'EOF'
ENABLE_SOURCES=github,awesome,trending,topics,marketplaces,reddit,hackernews,arxiv
SWEEP_INTERVAL=daily
ARXIV_INTERVAL=weekly
NOISE_FILTER_THRESHOLD=0.15
CONSENSUS_MIN_SOURCES=1
QUALITY_THRESHOLD=30
EOF

  cat > "$STATE_DIR/install.env" <<EOF
ROOT_DIR="$ROOT_DIR"
INSTALL_LOG="$LOG_FILE"
SYSTEM_LOG="$SYSTEM_LOG_FILE"
INITIALIZED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EOF

  if [[ -f "$ROOT_DIR/.skills/skills.txt" ]]; then
    sort -u "$ROOT_DIR/.skills/skills.txt" -o "$ROOT_DIR/.skills/skills.txt"
  fi

  date -u +%Y-%m-%dT%H:%M:%SZ > "$FIRST_RUN_MARKER"
  log "first-run skill OS configuration written"
}

verify_layout() {
  log "verifying Hermes layout"
  [[ -f "$ROOT_DIR/src/system/dynamic-router.sh" ]] || die "dynamic-router.sh missing"
  [[ -f "$ROOT_DIR/src/system/hermes-dispatch.sh" ]] || die "hermes-dispatch.sh missing"
  [[ -f "$ROOT_DIR/src/system/skill-router.sh" ]] || die "skill-router.sh missing"
  [[ -f "$ROOT_DIR/src/system/skill-router-v3.sh" ]] || die "skill-router-v3.sh missing"
  [[ -f "$ROOT_DIR/src/system/score-snapshot.sh" ]] || die "score-snapshot.sh missing"
  [[ -f "$ROOT_DIR/.skills/skills.txt" ]] || die ".skills/skills.txt missing"
  chmod +x "$ROOT_DIR"/src/system/*.sh "$ROOT_DIR"/tests/*.sh "$ROOT_DIR"/scripts/*.sh
  log "layout verification complete"
}

install_obliteratus() {
  [[ "$VERIFY_ONLY" != "1" ]] || { log "verify-only mode; skipping OBLITERATUS install"; return 0; }
  [[ "$SKIP_OBLITERATUS_INSTALL" != "1" ]] || { log "skipping OBLITERATUS install by request"; return 0; }

  [[ -d "$OBLITERATUS_DIR" ]] || die "OBLITERATUS directory not found under $ROOT_DIR"

  log "installing OBLITERATUS dependencies"
  cd "$OBLITERATUS_DIR"

  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip setuptools wheel
  .venv/bin/python -m pip install -e '.[dev,spaces]'

  PY_MINOR="$("$OBLITERATUS_DIR/.venv/bin/python" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"

  if [[ "$(uname -m)" == "aarch64" ]]; then
    if [[ "$PY_MINOR" == "3.13" ]]; then
      log "Python 3.13 detected; keeping PyTorch bundled CUDA/NVIDIA wheels because CPU-only aarch64 torch wheels are not available from this index."
    else
      if ! .venv/bin/python -m pip install --force-reinstall 'torch==2.5.1'; then
        log "warning: torch==2.5.1 unavailable for this Python/platform; trying torch==2.6.0"
        if ! .venv/bin/python -m pip install --force-reinstall 'torch==2.6.0'; then
          log "warning: torch fallback reinstall failed; keeping installed torch if it imports"
        fi
      fi
      .venv/bin/python -m pip freeze | awk -F== '/^(nvidia-|cuda-|triton==)/ {print $1}' | xargs -r .venv/bin/python -m pip uninstall -y
    fi
    .venv/bin/python -m pip install 'fsspec[http]==2026.4.0'
  fi

  .venv/bin/python - <<'PY'
import torch
print(f"torch={torch.__version__}")
print(f"cuda_available={torch.cuda.is_available()}")
PY

  .venv/bin/python -m pip check
  cd "$ROOT_DIR"
  log "OBLITERATUS dependency install complete"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only)
      VERIFY_ONLY=1
      shift
      ;;
    --skip-obliteratus-install)
      SKIP_OBLITERATUS_INSTALL=1
      shift
      ;;
    --no-system-log-monitor)
      ENABLE_SYSTEM_LOG_MONITOR=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown flag: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

main() {
  setup_logging
  trap stop_system_log_monitor EXIT
  log "starting Hermes restore/install in: $ROOT_DIR"
  check_deps
  start_system_log_monitor
  first_run_config
  verify_layout
  install_obliteratus
  log "restore complete"
  log "run: src/system/obliteratus-runner.sh doctor"
  log "run: src/system/dynamic-router.sh --json 'fix this failing test' direct"
  log "run: src/system/skill-router-v3.sh dashboard"
}

main "$@"
