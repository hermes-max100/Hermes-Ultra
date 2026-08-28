#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$ROOT_DIR/.hermes/install"
STATE_DIR="$ROOT_DIR/.hermes/state"
LOG_FILE="${HERMES_INSTALL_LOG_FILE:-$INSTALL_DIR/vps-restore.log}"
VERIFY_ONLY=0
INSTALL_PYTHON_DEPS=1
INSTALL_AGENT_REACH=1

usage() {
  cat <<'EOF'
Usage:
  scripts/restore-vps-transfer.sh [options]

Options:
  --verify-only          Check dependencies, layout, and config without installs.
  --skip-python-deps     Do not install Python package dependencies.
  --skip-agent-reach     Do not install the Agent Reach local driver venv.
  -h, --help             Show help.

Required VPS packages:
  bash coreutils tar gzip findutils python3 python3-venv python3-pip git curl jq ripgrep tmux
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

check_deps() {
  log "checking VPS dependencies"
  local required=(bash chmod date find mkdir python3 sed sort tar tee xargs)
  for cmd in "${required[@]}"; do
    require_cmd "$cmd"
  done

  local recommended=(git curl jq rg tmux sha256sum)
  for cmd in "${recommended[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      log "recommended dependency available: $cmd"
    else
      log "recommended dependency missing: $cmd"
    fi
  done

  python3 - <<'PY' >/dev/null 2>&1 || die "python3 venv module missing; install python3-venv"
import venv
PY
}

verify_layout() {
  log "verifying transferred layout"
  [[ -f "$ROOT_DIR/skills-lock.json" ]] || die "skills-lock.json missing"
  [[ -d "$ROOT_DIR/.agents/skills" ]] || die ".agents/skills missing"
  [[ -d "$ROOT_DIR/.skills/skills.d" ]] || die ".skills/skills.d missing"
  [[ -f "$ROOT_DIR/src/system/dynamic-router.sh" ]] || die "dynamic-router.sh missing"
  [[ -f "$ROOT_DIR/src/system/hermes-dispatch.sh" ]] || die "hermes-dispatch.sh missing"
  [[ -f "$ROOT_DIR/src/system/jarvis-armory.sh" ]] || die "jarvis-armory.sh missing"
  [[ -f "$ROOT_DIR/config/hermes-jarvis-policy.json" ]] || die "Hermes JARVIS policy missing"
  [[ -f "$ROOT_DIR/config/cloud-models.env.example" ]] || die "cloud model env template missing"

  chmod +x "$ROOT_DIR"/scripts/*.sh "$ROOT_DIR"/src/system/*.sh "$ROOT_DIR"/tests/*.sh

  if command -v jq >/dev/null 2>&1; then
    jq empty "$ROOT_DIR/skills-lock.json"
    jq empty "$ROOT_DIR/config/hermes-jarvis-policy.json"
  fi

  log "layout verification complete"
}

write_first_run_state() {
  mkdir -p "$INSTALL_DIR" "$STATE_DIR" "$ROOT_DIR/.hermes/reports" "$ROOT_DIR/.skills/logs"

  if [[ ! -f "$STATE_DIR/router.conf" ]]; then
    cat > "$STATE_DIR/router.conf" <<'EOF'
DEFAULT_PROFILE=direct
DEFAULT_SKILL_LIMIT=5
ENABLE_DYNAMIC_SKILL_ENGINE=true
ENABLE_LISTWISE_RERANKER=true
EOF
  fi

  if [[ ! -f "$STATE_DIR/sweep.conf" ]]; then
    cat > "$STATE_DIR/sweep.conf" <<'EOF'
ENABLE_SOURCES=github,awesome,trending,topics,marketplaces,reddit,hackernews,arxiv
SWEEP_INTERVAL=daily
ARXIV_INTERVAL=weekly
NOISE_FILTER_THRESHOLD=0.15
CONSENSUS_MIN_SOURCES=1
QUALITY_THRESHOLD=30
EOF
  fi

  cat > "$STATE_DIR/vps-transfer.env" <<EOF
ROOT_DIR="$ROOT_DIR"
RESTORED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ENV_TEMPLATE="$ROOT_DIR/config/cloud-models.env.example"
LOCAL_ENV_FILE="$ROOT_DIR/.env.cloud-models.local"
EOF
}

install_python_deps() {
  [[ "$VERIFY_ONLY" != "1" ]] || { log "verify-only mode; skipping Python deps"; return 0; }
  [[ "$INSTALL_PYTHON_DEPS" == "1" ]] || { log "Python dependency install skipped"; return 0; }

  if [[ -d "$ROOT_DIR/OBLITERATUS" && -f "$ROOT_DIR/OBLITERATUS/pyproject.toml" ]]; then
    log "installing OBLITERATUS into local venv"
    python3 -m venv "$ROOT_DIR/OBLITERATUS/.venv"
    "$ROOT_DIR/OBLITERATUS/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
    "$ROOT_DIR/OBLITERATUS/.venv/bin/python" -m pip install -e "$ROOT_DIR/OBLITERATUS"
  else
    log "OBLITERATUS pyproject not present; skipping"
  fi
}

install_agent_reach() {
  [[ "$VERIFY_ONLY" != "1" ]] || { log "verify-only mode; skipping Agent Reach install"; return 0; }
  [[ "$INSTALL_AGENT_REACH" == "1" ]] || { log "Agent Reach install skipped"; return 0; }

  if [[ -f "$ROOT_DIR/src/system/agent-reach.sh" && -f "$ROOT_DIR/.skill-sources/Panniantong__Agent-Reach/pyproject.toml" ]]; then
    log "installing Agent Reach driver"
    "$ROOT_DIR/src/system/agent-reach.sh" install
  else
    log "Agent Reach source or driver missing; skipping"
  fi
}

print_next_steps() {
  cat <<EOF

VPS restore complete.

Next steps:
  1. cp config/cloud-models.env.example .env.cloud-models.local
  2. chmod 600 .env.cloud-models.local
  3. edit .env.cloud-models.local with provider keys on the VPS
  4. source .env.cloud-models.local
  5. src/system/promptfoo-evals.sh check
  6. src/system/agent-reach.sh status
  7. src/system/agent-reach.sh doctor
  8. src/system/hermes-power-up.sh status
  9. src/system/jarvis-armory.sh verify-artifacts
  10. src/system/jarvis-armory.sh install
  11. src/system/jarvis-armory.sh start
  12. src/system/jarvis-armory.sh doctor

Phone-only Android control still needs the phone bridge:
  - Accessibility
  - Shizuku
  - Notification Access
  - Usage Access
  - bridge-client/mobile-app-control endpoint from the phone side
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only)
      VERIFY_ONLY=1
      shift
      ;;
    --skip-python-deps)
      INSTALL_PYTHON_DEPS=0
      shift
      ;;
    --skip-agent-reach)
      INSTALL_AGENT_REACH=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

main() {
  mkdir -p "$INSTALL_DIR"
  exec > >(tee -a "$LOG_FILE") 2>&1
  log "starting VPS restore in: $ROOT_DIR"
  check_deps
  verify_layout
  write_first_run_state
  install_agent_reach
  install_python_deps
  print_next_steps
}

main "$@"
