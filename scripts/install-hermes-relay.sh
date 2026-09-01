#!/usr/bin/env bash
set -euo pipefail
usage(){ echo 'Usage: install-hermes-relay.sh {prepare|activate|reconcile|deactivate-code-only} --release-root PATH --runtime-python PATH --hermes-home PATH [--systemd-dir PATH] [--test-mode]' >&2; }
MODE="${1:-}"; shift || true
RELEASE_ROOT=''; RUNTIME_PYTHON=''; HERMES_HOME=''; SYSTEMD_DIR='/etc/systemd/system'; TEST_MODE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-root) RELEASE_ROOT="${2:-}"; shift 2 ;;
    --runtime-python) RUNTIME_PYTHON="${2:-}"; shift 2 ;;
    --hermes-home) HERMES_HOME="${2:-}"; shift 2 ;;
    --systemd-dir) SYSTEMD_DIR="${2:-}"; shift 2 ;;
    --test-mode) TEST_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
[[ "$MODE" =~ ^(prepare|activate|reconcile|deactivate-code-only)$ ]] || { usage; exit 2; }
[[ -n "$RELEASE_ROOT" && -n "$RUNTIME_PYTHON" && -n "$HERMES_HOME" ]] || { usage; exit 2; }
VENDOR="$RELEASE_ROOT/vendor/hermes-relay/server-v1.10.0"
PLUGIN="$VENDOR/source/plugin"
UPSTREAM="$RELEASE_ROOT/config/hermes-relay-upstream.json"
SCAN_BASELINE="$RELEASE_ROOT/config/hermes-relay-scan-baseline.json"
SCAN_BASELINE_VERIFIER="$RELEASE_ROOT/scripts/verify-hermes-relay-scan-baseline.py"
UNIT="$SYSTEMD_DIR/hermes-relay.service"
HERMES_BIN="${HERMES_RELAY_HERMES_BIN:-$(dirname "$RUNTIME_PYTHON")/hermes}"
require_relay_evidence(){
  for f in "$UPSTREAM" "$VENDOR/SOURCE_TAG" "$VENDOR/SOURCE_COMMIT" "$VENDOR/SOURCE_PROVENANCE.json" \
    "$VENDOR/SOURCE_MANIFEST.sha256" "$VENDOR/uv.lock" "$VENDOR/requirements-hermes-relay.lock.txt" \
    "$VENDOR/DEPENDENCY_LOCK_PROVENANCE.json" "$VENDOR/hermes_relay-1.10.0-py3-none-any.whl" "$VENDOR/LICENSE" \
    "$PLUGIN/plugin.yaml" "$SCAN_BASELINE" "$SCAN_BASELINE_VERIFIER"; do
    [[ -f "$f" ]] || { echo "required Relay evidence missing: $f" >&2; return 1; }
  done
  (cd "$VENDOR" && sha256sum -c SOURCE_MANIFEST.sha256 >/dev/null) || { echo 'Relay source manifest verification failed' >&2; return 1; }
  python3 - "$UPSTREAM" "$VENDOR" <<'PY'
import hashlib,json,pathlib,re,sys
up=pathlib.Path(sys.argv[1]); root=pathlib.Path(sys.argv[2]); sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
data=json.loads(up.read_text()); server=data.get('server',{})
prov=json.loads((root/'SOURCE_PROVENANCE.json').read_text()); dep=json.loads((root/'DEPENDENCY_LOCK_PROVENANCE.json').read_text())
expect={'tag':'server-v1.10.0','version':'1.10.0','artifact':'hermes_relay-1.10.0-py3-none-any.whl'}
for key,val in expect.items():
    if str(server.get(key,''))!=val: raise SystemExit('Relay upstream '+key+' mismatch')
if (root/'SOURCE_TAG').read_text().strip()!=server.get('tag'): raise SystemExit('Relay source tag mismatch')
if (root/'SOURCE_COMMIT').read_text().strip()!=server.get('commit'): raise SystemExit('Relay source commit mismatch')
if prov.get('source_commit')!=server.get('commit') or prov.get('source_tag')!=server.get('tag') or prov.get('version')!=server.get('version'): raise SystemExit('Relay source provenance mismatch')
if sha(root/server['artifact'])!=server.get('artifact_sha256') or prov.get('artifact_sha256')!=server.get('artifact_sha256'): raise SystemExit('Relay wheel digest mismatch')
if prov.get('tree_sha256')!=sha(root/'SOURCE_MANIFEST.sha256'): raise SystemExit('Relay tree provenance mismatch')
if dep.get('mode')!='uv-export-frozen-validated-no-project' or dep.get('dependency_metadata_match') is not True or dep.get('uv_lock_sha256')!=sha(root/'uv.lock') or dep.get('runtime_requirements_sha256')!=sha(root/'requirements-hermes-relay.lock.txt'): raise SystemExit('Relay dependency provenance mismatch')
PY
}
tailnet_ip(){
  local ip
  ip="$(tailscale ip -4 2>/dev/null | head -1)"
  python3 - "$ip" <<'PY'
import ipaddress,sys
try: ip=ipaddress.ip_address(sys.argv[1])
except ValueError: raise SystemExit('invalid Tailscale IPv4')
if ip.version != 4 or ip not in ipaddress.ip_network('100.64.0.0/10'): raise SystemExit('Relay bind must be Tailscale IPv4')
print(ip)
PY
}
scan_verdict(){
  if [[ "$TEST_MODE" == 1 && -n "${HERMES_RELAY_TEST_SCAN_VERDICT:-}" ]]; then
    printf '%s\n' "$HERMES_RELAY_TEST_SCAN_VERDICT"
    return
  fi
  local scan_json raw
  scan_json="$(mktemp)"
  if ! raw="$("$RUNTIME_PYTHON" - "$PLUGIN" "$scan_json" <<'PYSCAN'
from pathlib import Path
import json,sys
from tools.plugin_guard import PLUGIN_SCANNER_VERSION, scan_plugin
r=scan_plugin(Path(sys.argv[1]), source='Codename-11/hermes-relay@server-v1.10.0')
fields=('severity','pattern_id','category','file','line','match','description')
findings=[{key:getattr(f,key) for key in fields} for f in r.findings]
Path(sys.argv[2]).write_text(json.dumps({
    'scanner_version':PLUGIN_SCANNER_VERSION, 'verdict':r.verdict, 'findings':findings,
}, sort_keys=True, ensure_ascii=False))
print(r.verdict)
PYSCAN
  )"; then
    rm -f "$scan_json"
    return 1
  fi
  if [[ "$raw" == safe ]]; then
    rm -f "$scan_json"
    printf 'safe\n'
    return
  fi
  if python3 "$SCAN_BASELINE_VERIFIER" \
      --scan-result "$scan_json" --baseline "$SCAN_BASELINE" \
      --source-commit-file "$VENDOR/SOURCE_COMMIT" --plugin-root "$PLUGIN" \
      --source 'Codename-11/hermes-relay' --tag 'server-v1.10.0' >&2; then
    rm -f "$scan_json"
    printf 'reviewed-safe\n'
    return
  fi
  rm -f "$scan_json"
  printf '%s\n' "$raw"
}

hermes_cmd(){
  if [[ "$EUID" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u hermes -- env HOME="$(dirname "$HERMES_HOME")" HERMES_HOME="$HERMES_HOME" "$HERMES_BIN" "$@"
  else
    env HOME="$(dirname "$HERMES_HOME")" HERMES_HOME="$HERMES_HOME" "$HERMES_BIN" "$@"
  fi
}
health_ok(){
  local ip="$1"
  [[ "${HERMES_RELAY_TEST_HEALTH:-}" == ok ]] && return 0
  python3 - "$ip" <<'PY'
import json,sys,urllib.request
try:
    with urllib.request.urlopen(f'http://{sys.argv[1]}:8767/health', timeout=2) as r: body=json.load(r)
    raise SystemExit(0 if body.get('ok') is True or body.get('status') in ('ok','healthy') else 1)
except Exception: raise SystemExit(1)
PY
}
prepare(){
  require_relay_evidence
  local ip verdict; ip="$(tailnet_ip)"; verdict="$(scan_verdict)"
  [[ "$verdict" == safe || "$verdict" == reviewed-safe ]] || { echo "Relay plugin scan rejected: $verdict" >&2; return 1; }
  PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 "$RUNTIME_PYTHON" -m pip install --require-hashes -r "$VENDOR/requirements-hermes-relay.lock.txt"
  printf 'HERMES_RELAY_PREPARE=PASS host=%s version=1.10.0\n' "$ip"
}
restore_snapshot(){
  local snap="$1" old_link="$2" old_enabled="$3" old_active="$4"
  rm -f "$HERMES_HOME/plugins/hermes-relay"
  [[ -n "$old_link" ]] && ln -s "$old_link" "$HERMES_HOME/plugins/hermes-relay"
  if [[ -f "$snap/config.yaml" ]]; then cp -a "$snap/config.yaml" "$HERMES_HOME/config.yaml"; else rm -f "$HERMES_HOME/config.yaml"; fi
  if [[ -f "$snap/hermes-relay.service" ]]; then cp -a "$snap/hermes-relay.service" "$UNIT"; else rm -f "$UNIT"; fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  if [[ "$old_enabled" == enabled ]]; then systemctl enable hermes-relay.service >/dev/null 2>&1 || true; else systemctl disable hermes-relay.service >/dev/null 2>&1 || true; fi
  if [[ "$old_active" == active ]]; then systemctl restart hermes-relay.service >/dev/null 2>&1 || true; else systemctl stop hermes-relay.service >/dev/null 2>&1 || true; fi
}
deactivate_code_only(){
  mkdir -p "$HERMES_HOME/plugins" "$SYSTEMD_DIR"
  systemctl stop hermes-relay.service >/dev/null 2>&1 || true
  systemctl disable hermes-relay.service >/dev/null 2>&1 || true
  rm -f "$UNIT"
  systemctl daemon-reload >/dev/null 2>&1 || true
  hermes_cmd plugins disable hermes-relay >/dev/null 2>&1 || true
  rm -f "$HERMES_HOME/plugins/hermes-relay"
  printf 'HERMES_RELAY_DEACTIVATE=PASS
'
}

activate(){
  require_relay_evidence
  local ip; ip="$(tailnet_ip)"
  mkdir -p "$HERMES_HOME/plugins" "$SYSTEMD_DIR"
  local snap old_link old_enabled old_active
  snap="$(mktemp -d)"; old_link="$(readlink "$HERMES_HOME/plugins/hermes-relay" 2>/dev/null || true)"
  [[ -f "$HERMES_HOME/config.yaml" ]] && cp -a "$HERMES_HOME/config.yaml" "$snap/config.yaml"
  [[ -f "$UNIT" ]] && cp -a "$UNIT" "$snap/hermes-relay.service"
  old_enabled="$(systemctl is-enabled hermes-relay.service 2>/dev/null || true)"; old_active="$(systemctl is-active hermes-relay.service 2>/dev/null || true)"
  if ! (
    set -e
    rm -f "$HERMES_HOME/plugins/hermes-relay"
    ln -s "$PLUGIN" "$HERMES_HOME/plugins/hermes-relay"
    hermes_cmd plugins enable hermes-relay --no-allow-tool-override || exit 1
    hermes_cmd plugins doctor hermes-relay --ci || exit 1
    cat > "$UNIT" <<UNIT
[Unit]
Description=Hermes Relay private tailnet extension
After=network-online.target hermes-runtime.service
Wants=network-online.target
[Service]
Type=simple
User=hermes
Group=hermes
WorkingDirectory=$VENDOR/source
Environment=HOME=$(dirname "$HERMES_HOME")
Environment=HERMES_HOME=$HERMES_HOME
ExecStart=$RUNTIME_PYTHON -m plugin.relay --host $ip --port 8767 --no-ssl --log-level INFO
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$HERMES_HOME
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload || exit 1
    systemctl enable --now hermes-relay.service || exit 1
    ready=0
    for _ in $(seq 1 30); do
      if health_ok "$ip"; then ready=1; break; fi
      sleep 1
    done
    [[ "$ready" == 1 ]] || { echo 'Hermes Relay health check failed' >&2; exit 1; }
  ); then
    restore_snapshot "$snap" "$old_link" "$old_enabled" "$old_active"
    rm -rf "$snap"
    return 1
  fi
  rm -rf "$snap"
  printf 'HERMES_RELAY_ACTIVATE=PASS host=%s version=1.10.0\n' "$ip"
}

case "$MODE" in
  prepare) prepare ;;
  activate) activate ;;
  reconcile) activate ;;
  deactivate-code-only) deactivate_code_only ;;
  *) echo "unsupported mode: $MODE" >&2; exit 2 ;;
esac
