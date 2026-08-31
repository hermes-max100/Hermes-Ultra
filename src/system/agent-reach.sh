#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_DIR="$ROOT_DIR/.skill-sources/Panniantong__Agent-Reach"
VENV_DIR="$ROOT_DIR/.hermes/venvs/agent-reach"
BIN="$VENV_DIR/bin/agent-reach"
PROVENANCE="$VENV_DIR/hermes-provenance.json"
RUNTIME_HOME="$VENV_DIR/hermes-home"
POLICY="$ROOT_DIR/config/agent-reach-source-policy.json"
MCPORTER_CONFIG="$ROOT_DIR/config/agent-reach-mcporter.json"
SAFE_FETCH="$ROOT_DIR/src/system/agent-reach-safe-fetch.py"
QUERY_HELPER="$ROOT_DIR/src/system/agent-reach-query.py"
GITHUB_QUERY_HELPER="$ROOT_DIR/src/system/agent-reach-github-query.py"
ENVELOPE="$ROOT_DIR/src/system/agent-reach-envelope.py"
MCP_DISCOVERY_SOURCES="$ROOT_DIR/config/mcp-discovery-sources.json"
MCP_DISCOVERY_GOVERNANCE="$ROOT_DIR/src/system/mcp-discovery-governance.py"
PROVISIONER="$ROOT_DIR/scripts/provision-agent-reach.sh"
TRUSTED_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/data/data/com.termux/files/usr/bin"
export PATH="$TRUSTED_PATH"

usage() {
  cat <<'EOF'
Hermes Agent Reach read/collect runtime

Usage:
  src/system/agent-reach.sh status
  src/system/agent-reach.sh doctor
  src/system/agent-reach.sh check-update
  src/system/agent-reach.sh search <query>
  src/system/agent-reach.sh github <query>
  src/system/agent-reach.sh read <public-http(s)-url>
  src/system/agent-reach.sh mcp-sources
  src/system/agent-reach.sh mcp-interface <available-interface>...

Security boundary:
  - Runtime never installs, updates, configures cookies, or accepts raw Agent
    Reach commands.
  - MCP discovery commands expose source policy and interface decisions only;
    they cannot promote, install, or activate providers.
  - Provisioning is separate: scripts/provision-agent-reach.sh install
  - Internet/search results are emitted in an explicit untrusted JSON envelope.
EOF
}

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
  [[ -n "$path" && -x "$path" ]] || return 1
  real="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$real" && -x "$real" ]] || return 1
  case "$real" in
    /usr/*|/bin/*|/sbin/*|/opt/*|/data/data/com.termux/files/usr/*) ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$path"
}

PYTHON_BIN="$(resolve_trusted_tool python3 || true)"
BASH_BIN="$(resolve_trusted_tool bash || true)"
[[ -n "$PYTHON_BIN" ]] || die "trusted python3 interpreter not found"
[[ -n "$BASH_BIN" ]] || die "trusted bash interpreter not found"

reject_symlink() {
  local path="$1"
  [[ ! -L "$path" ]] || die "unsafe symlink path: $path"
}

runtime_path_preflight() {
  reject_symlink "$ROOT_DIR/.hermes"
  reject_symlink "$ROOT_DIR/.hermes/venvs"
  reject_symlink "$VENV_DIR"
  if [[ -e "$BIN" ]]; then
    [[ -f "$BIN" && ! -L "$BIN" ]] || die "unsafe Agent Reach launcher: $BIN"
  fi
  if [[ -e "$PROVENANCE" ]]; then
    [[ -f "$PROVENANCE" && ! -L "$PROVENANCE" ]] || die "unsafe Agent Reach provenance receipt: $PROVENANCE"
  fi
  [[ ! -L "$MCPORTER_CONFIG" ]] || die "unsafe Agent Reach mcporter config: $MCPORTER_CONFIG"
}

validate_mcporter_config() {
  [[ -f "$MCPORTER_CONFIG" ]] || die "Agent Reach mcporter config missing: $MCPORTER_CONFIG"
  "$PYTHON_BIN" - "$MCPORTER_CONFIG" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid Agent Reach mcporter config: {exc}")
expected = {
    "mcpServers": {
        "exa": {
            "baseUrl": "https://mcp.exa.ai/mcp",
            "allowedTools": ["web_search_exa"],
        }
    },
    "imports": [],
}
if payload != expected:
    raise SystemExit("Agent Reach mcporter config differs from the exact read-only Exa policy")
PY
}

validate_provenance() {
  "$PYTHON_BIN" - "$POLICY" "$PROVENANCE" <<'PY'
import json
import pathlib
import sys
policy_path = pathlib.Path(sys.argv[1])
receipt_path = pathlib.Path(sys.argv[2])
try:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Agent Reach provenance validation failed: {exc}")
if receipt.get("schema_version") != "agent-reach-runtime-provenance-v1":
    raise SystemExit("Agent Reach provenance validation failed: schema mismatch")
source = receipt.get("source")
if not isinstance(source, dict):
    raise SystemExit("Agent Reach provenance validation failed: source missing")
if source.get("repository") != policy.get("repository"):
    raise SystemExit("Agent Reach provenance validation failed: repository mismatch")
if source.get("commit") != policy.get("commit"):
    raise SystemExit("Agent Reach provenance validation failed: commit mismatch")
if receipt.get("installed_version") != policy.get("version"):
    raise SystemExit("Agent Reach provenance validation failed: version mismatch")
print(receipt["installed_version"])
PY
}

ensure_installed() {
  runtime_path_preflight
  [[ -x "$BIN" ]] || die "Agent Reach is not provisioned; run: bash $PROVISIONER install"
  [[ -f "$PROVENANCE" ]] || die "Agent Reach runtime provenance is missing; re-provision with: bash $PROVISIONER install"
  validate_provenance >/dev/null
  "$BASH_BIN" "$PROVISIONER" verify-runtime >/dev/null
}

run_agent_reach() {
  ensure_installed
  [[ -d "$RUNTIME_HOME" && ! -L "$RUNTIME_HOME" ]] || die "Agent Reach isolated runtime home missing; re-provision"
  env \
    -u PYTHONPATH -u PYTHONHOME -u PYTHONSTARTUP -u VIRTUAL_ENV \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
    HOME="$RUNTIME_HOME" \
    XDG_CONFIG_HOME="$RUNTIME_HOME/.config" \
    XDG_DATA_HOME="$RUNTIME_HOME/.local/share" \
    XDG_CACHE_HOME="$RUNTIME_HOME/.cache" \
    XDG_STATE_HOME="$RUNTIME_HOME/.local/state" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="$VENV_DIR/bin:$TRUSTED_PATH" \
    "$BIN" "$@"
}

resolve_backend() {
  resolve_trusted_tool "$1"
}

cmd_status() {
  local version verify_status="not-provisioned"
  runtime_path_preflight
  printf 'source=%s\n' "$SOURCE_DIR"
  printf 'venv=%s\n' "$VENV_DIR"
  if [[ -x "$BIN" && -f "$PROVENANCE" ]]; then
    if version="$(validate_provenance)" && "$BASH_BIN" "$PROVISIONER" verify-runtime >/dev/null 2>&1; then
      verify_status="verified"
      printf 'installed=true\n'
      printf 'version=%s\n' "$version"
    else
      die "unsafe or unverifiable Agent Reach runtime"
    fi
  else
    printf 'installed=false\n'
  fi
  printf 'runtime_verification=%s\n' "$verify_status"
  if resolve_backend mcporter >/dev/null 2>&1 && validate_mcporter_config >/dev/null 2>&1; then
    printf 'exa=true\n'
  else
    printf 'exa=false\n'
  fi
  printf 'github=public-api\n'
  printf 'authenticated_social=false\n'
}

cmd_doctor() {
  local verify_json mcporter=false
  ensure_installed
  verify_json="$("$BASH_BIN" "$PROVISIONER" verify-runtime)"
  if resolve_backend mcporter >/dev/null 2>&1 && validate_mcporter_config >/dev/null 2>&1; then
    mcporter=true
  fi
  "$PYTHON_BIN" - "$verify_json" "$mcporter" <<'PY'
import json
import sys
verified = json.loads(sys.argv[1])
print(json.dumps({
    "schema_version": "agent-reach-doctor-v2",
    "runtime_verified": bool(verified.get("verified")),
    "version": verified.get("version"),
    "source_commit": verified.get("commit"),
    "public_web_read": True,
    "exa_search": sys.argv[2].lower() == "true",
    "github_mode": "public-api-no-credential-reuse",
    "authenticated_social": False,
    "raw_upstream_cli": False,
}, indent=2, sort_keys=True))
PY
}

cmd_check_update() {
  run_agent_reach check-update | "$PYTHON_BIN" "$ENVELOPE" --kind update --source "agent-reach-upstream-update-check"
}

cmd_search() {
  [[ $# -gt 0 ]] || die "search requires <query>"
  local query="$*" mcporter expression
  [[ ${#query} -le 2000 ]] || die "search query exceeds 2000 characters"
  validate_mcporter_config
  mcporter="$(resolve_backend mcporter)" || die "trusted mcporter is not provisioned for Exa search"
  expression="$("$PYTHON_BIN" "$QUERY_HELPER" "$query")"
  env \
    -u MCPORTER_CONFIG \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
    HOME="${RUNTIME_HOME:-/nonexistent}" \
    XDG_CONFIG_HOME="${RUNTIME_HOME:-/nonexistent}/.config" \
    XDG_DATA_HOME="${RUNTIME_HOME:-/nonexistent}/.local/share" \
    XDG_CACHE_HOME="${RUNTIME_HOME:-/nonexistent}/.cache" \
    XDG_STATE_HOME="${RUNTIME_HOME:-/nonexistent}/.local/state" \
    MCPORTER_LOG_LEVEL=error \
    PATH="$TRUSTED_PATH" \
    "$mcporter" --config "$MCPORTER_CONFIG" call "$expression" \
    | "$PYTHON_BIN" "$ENVELOPE" --kind search --source "$query"
}

cmd_github() {
  [[ $# -gt 0 ]] || die "github requires <query>"
  local query="$*" url
  url="$("$PYTHON_BIN" "$GITHUB_QUERY_HELPER" "$query")"
  "$PYTHON_BIN" "$SAFE_FETCH" "$url" \
    | "$PYTHON_BIN" "$ENVELOPE" --kind github --source "$query"
}

cmd_read() {
  [[ $# -eq 1 ]] || die "read requires exactly one URL"
  local url="$1"
  "$PYTHON_BIN" "$SAFE_FETCH" "$url" \
    | "$PYTHON_BIN" "$ENVELOPE" --kind web --source "$url"
}

cmd_mcp_sources() {
  [[ $# -eq 0 ]] || die "mcp-sources takes no arguments"
  "$PYTHON_BIN" "$MCP_DISCOVERY_GOVERNANCE" --registry "$MCP_DISCOVERY_SOURCES" sources
}

cmd_mcp_interface() {
  [[ $# -gt 0 ]] || die "mcp-interface requires at least one available interface"
  "$PYTHON_BIN" "$MCP_DISCOVERY_GOVERNANCE" --registry "$MCP_DISCOVERY_SOURCES" choose-interface "$@"
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    status) cmd_status "$@" ;;
    doctor) cmd_doctor "$@" ;;
    check-update) cmd_check_update "$@" ;;
    search) cmd_search "$@" ;;
    github) cmd_github "$@" ;;
    read) cmd_read "$@" ;;
    mcp-sources) cmd_mcp_sources "$@" ;;
    mcp-interface) cmd_mcp_interface "$@" ;;
    help|-h|--help) usage ;;
    install|raw|configure|setup|uninstall|skill|transcribe)
      die "command '$command' is outside the read/collect runtime boundary; use governed provisioning/configuration instead"
      ;;
    *) die "unknown or disallowed command: $command" ;;
  esac
}

main "$@"
