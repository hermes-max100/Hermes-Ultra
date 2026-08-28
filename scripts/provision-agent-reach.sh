#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/.skill-sources/Panniantong__Agent-Reach"
VENV_DIR="$ROOT_DIR/.hermes/venvs/agent-reach"
RUNTIME_HOME="$VENV_DIR/hermes-home"
POLICY="$ROOT_DIR/config/agent-reach-source-policy.json"
VERIFY="$ROOT_DIR/src/system/agent-reach-source-verify.py"
PROVENANCE="$VENV_DIR/hermes-provenance.json"
TRUSTED_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/data/data/com.termux/files/usr/bin"
export PATH="$TRUSTED_PATH"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

resolve_trusted_tool() {
  local name="$1" path real
  path="$(command -v "$name" 2>/dev/null || true)"
  [[ -n "$path" && -x "$path" ]] || die "trusted $name is required"
  real="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$real" && -x "$real" ]] || die "could not resolve trusted $name"
  case "$real" in
    /usr/*|/bin/*|/sbin/*|/opt/*|/data/data/com.termux/files/usr/*) ;;
    *) die "unsafe $name executable path: $real" ;;
  esac
  printf '%s\n' "$path"
}

PYTHON_BIN="$(resolve_trusted_tool python3)"
resolve_trusted_tool git >/dev/null

reject_symlink_path() {
  local path="$1"
  [[ ! -L "$path" ]] || die "unsafe symlink path: $path"
}

validate_venv_python() {
  local path="$VENV_DIR/bin/python" real base
  [[ -e "$path" && -x "$path" ]] || die "missing Agent Reach Python launcher"
  real="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$real" && -x "$real" ]] || die "could not resolve Agent Reach Python launcher"
  base="$(basename -- "$real")"
  case "$base" in
    python|python3|python3.*) ;;
    *) die "unsafe Agent Reach Python target: $real" ;;
  esac
  case "$real" in
    "$VENV_DIR"/*|/usr/*|/bin/*|/opt/*|/data/data/com.termux/files/usr/*) ;;
    *) die "unsafe Agent Reach Python path: $real" ;;
  esac
}

validate_runtime_home() {
  [[ -d "$RUNTIME_HOME" && ! -L "$RUNTIME_HOME" ]] || die "Agent Reach isolated runtime home is missing or unsafe"
  "$PYTHON_BIN" - "$RUNTIME_HOME" <<'PY'
import os
import pathlib
import stat
import sys
path = pathlib.Path(sys.argv[1])
st = path.stat()
if st.st_uid != os.getuid():
    raise SystemExit("Agent Reach runtime home owner mismatch")
if stat.S_IMODE(st.st_mode) & 0o077:
    raise SystemExit("Agent Reach runtime home permissions must be 0700")
PY
}

run_clean_python() {
  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    -u PYTHONINSPECT -u PYTHONWARNINGS \
    PATH="$TRUSTED_PATH" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_BIN" "$@"
}

run_clean_pip() {
  local python="$1"
  shift
  validate_runtime_home
  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    -u PYTHONINSPECT -u PYTHONWARNINGS \
    -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PIP_TRUSTED_HOST \
    -u PIP_FIND_LINKS -u PIP_CERT -u PIP_CLIENT_CERT -u PIP_PROXY \
    -u PIP_CONSTRAINT -u PIP_REQUIREMENT -u PIP_TARGET -u PIP_PREFIX \
    -u PIP_ROOT -u PIP_USER -u PIP_NO_INDEX -u PIP_PRE \
    -u PIP_NO_BINARY -u PIP_ONLY_BINARY -u PIP_REQUIRE_VIRTUALENV \
    -u PIP_CONFIG_FILE \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
    -u SSL_CERT_FILE -u REQUESTS_CA_BUNDLE -u CURL_CA_BUNDLE \
    HOME="$RUNTIME_HOME" \
    XDG_CONFIG_HOME="$RUNTIME_HOME/.config" \
    XDG_DATA_HOME="$RUNTIME_HOME/.local/share" \
    XDG_CACHE_HOME="$RUNTIME_HOME/.cache" \
    XDG_STATE_HOME="$RUNTIME_HOME/.local/state" \
    PATH="$TRUSTED_PATH" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_CONFIG_FILE=/dev/null \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    "$python" -m pip "$@"
}

verify_source() {
  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    -u GIT_CONFIG_GLOBAL -u GIT_CONFIG_SYSTEM \
    HOME=/nonexistent \
    GIT_CONFIG_NOSYSTEM=1 \
    PATH="$TRUSTED_PATH" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    "$PYTHON_BIN" "$VERIFY" --source "$SOURCE_DIR" --policy "$POLICY"
}

verify_runtime() {
  reject_symlink_path "$ROOT_DIR/.hermes"
  reject_symlink_path "$ROOT_DIR/.hermes/venvs"
  reject_symlink_path "$VENV_DIR"
  [[ -d "$VENV_DIR" ]] || die "Agent Reach is not provisioned"
  validate_venv_python
  validate_runtime_home
  [[ -f "$VENV_DIR/bin/agent-reach" && ! -L "$VENV_DIR/bin/agent-reach" ]] || die "unsafe or missing Agent Reach launcher"
  [[ -x "$VENV_DIR/bin/agent-reach" ]] || die "Agent Reach launcher is not executable"
  [[ -f "$PROVENANCE" && ! -L "$PROVENANCE" ]] || die "Agent Reach provenance receipt missing or unsafe"
  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    HOME="$RUNTIME_HOME" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="$VENV_DIR/bin:$TRUSTED_PATH" \
    "$VENV_DIR/bin/python" - "$POLICY" "$PROVENANCE" <<'PY'
import importlib.metadata
import json
import pathlib
import stat
import sys

policy = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
receipt = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
if receipt.get("schema_version") != "agent-reach-runtime-provenance-v1":
    raise SystemExit("invalid Agent Reach runtime provenance schema")
if receipt.get("source", {}).get("commit") != policy.get("commit"):
    raise SystemExit("Agent Reach runtime provenance commit mismatch")
if receipt.get("source", {}).get("repository") != policy.get("repository"):
    raise SystemExit("Agent Reach runtime provenance repository mismatch")
installed = importlib.metadata.version("agent-reach")
if installed != policy.get("version") or receipt.get("installed_version") != installed:
    raise SystemExit(f"Agent Reach version mismatch: expected {policy.get('version')}, got {installed}")
venv = pathlib.Path(sys.prefix)
mode = venv.stat().st_mode
if mode & (stat.S_IWGRP | stat.S_IWOTH):
    raise SystemExit("Agent Reach venv is group/world writable")
print(json.dumps({"verified": True, "version": installed, "commit": policy["commit"]}, sort_keys=True))
PY
  run_clean_pip "$VENV_DIR/bin/python" check >/dev/null
}

install_runtime() {
  local source_receipt backup=""
  source_receipt="$(verify_source)"
  reject_symlink_path "$ROOT_DIR/.hermes"
  reject_symlink_path "$ROOT_DIR/.hermes/venvs"
  reject_symlink_path "$VENV_DIR"
  mkdir -p "$(dirname "$VENV_DIR")"
  reject_symlink_path "$(dirname "$VENV_DIR")"

  if [[ -e "$VENV_DIR" ]]; then
    backup="$VENV_DIR.backup.$(date -u +%Y%m%dT%H%M%SZ).$$"
    mv "$VENV_DIR" "$backup"
  fi

  rollback() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
      rm -rf -- "$VENV_DIR"
      if [[ -n "$backup" && -e "$backup" ]]; then
        mv "$backup" "$VENV_DIR"
      fi
    fi
    return $rc
  }
  trap rollback EXIT

  run_clean_python -m venv "$VENV_DIR"
  validate_venv_python
  mkdir -p "$RUNTIME_HOME/.config" "$RUNTIME_HOME/.local/share" "$RUNTIME_HOME/.cache" "$RUNTIME_HOME/.local/state"
  chmod 0700 "$RUNTIME_HOME"
  validate_runtime_home
  run_clean_pip "$VENV_DIR/bin/python" install --no-input --no-cache-dir "$SOURCE_DIR"
  run_clean_pip "$VENV_DIR/bin/python" check

  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    HOME="$RUNTIME_HOME" \
    PATH="$VENV_DIR/bin:$TRUSTED_PATH" \
    PIP_CONFIG_FILE=/dev/null \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    "$VENV_DIR/bin/python" - "$POLICY" "$PROVENANCE" "$source_receipt" <<'PY'
import importlib.metadata
import json
import pathlib
import platform
import subprocess
import sys

policy = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
provenance_path = pathlib.Path(sys.argv[2])
source = json.loads(sys.argv[3])
installed = importlib.metadata.version("agent-reach")
if installed != policy["version"]:
    raise SystemExit(f"installed Agent Reach version mismatch: {installed}")
freeze_env = {
    "HOME": str(pathlib.Path(sys.executable).parents[1] / "hermes-home"),
    "PATH": str(pathlib.Path(sys.executable).parent) + ":/usr/local/bin:/usr/bin:/bin:/data/data/com.termux/files/usr/bin",
    "PIP_CONFIG_FILE": "/dev/null",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PYTHONNOUSERSITE": "1",
}
freeze = subprocess.run(
    [sys.executable, "-m", "pip", "freeze", "--all"],
    check=True,
    text=True,
    stdout=subprocess.PIPE,
    env=freeze_env,
).stdout.splitlines()
receipt = {
    "schema_version": "agent-reach-runtime-provenance-v1",
    "source": source,
    "installed_version": installed,
    "python": platform.python_version(),
    "packages": freeze,
}
provenance_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  chmod -R go-w "$VENV_DIR"
  chmod 0700 "$RUNTIME_HOME"
  verify_runtime >/dev/null

  if [[ -n "$backup" && -e "$backup" ]]; then
    rm -rf -- "$backup"
  fi
  trap - EXIT
  log "Agent Reach provisioned from pinned source: $VENV_DIR"
}

usage() {
  cat <<'EOF'
Hermes Agent Reach privileged provisioner

Usage:
  scripts/provision-agent-reach.sh verify-source
  scripts/provision-agent-reach.sh verify-runtime
  scripts/provision-agent-reach.sh install

This is a provisioning boundary, not an agent runtime command. The runtime
wrapper never auto-installs or updates Agent Reach.
EOF
}

case "${1:-help}" in
  verify-source) verify_source ;;
  verify-runtime) verify_runtime ;;
  install) install_runtime ;;
  help|-h|--help) usage ;;
  *) die "unknown command: ${1:-}" ;;
esac
