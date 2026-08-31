#!/usr/bin/env bash
set -euo pipefail
usage(){ echo 'Usage: install-cloud-release-local.sh RELEASE.tar.gz EXPECTED_SHA256' >&2; }
ARCHIVE="${1:-}"; EXPECTED_SHA="${2:-}"
[[ -n "$ARCHIVE" && -n "$EXPECTED_SHA" ]] || { usage; exit 2; }
[[ -f "$ARCHIVE" ]] || { echo 'release archive not found' >&2; exit 2; }
[[ "$EXPECTED_SHA" =~ ^[0-9A-Fa-f]{64}$ ]] || { echo 'expected SHA256 must be 64 hex characters' >&2; exit 2; }
EXPECTED_SHA="${EXPECTED_SHA,,}"
ACTUAL_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo 'outer release SHA256 mismatch' >&2; exit 1; }

TEST_MODE="${HERMES_INSTALL_TEST_MODE:-0}"
INSTALL_ROOT="${HERMES_INSTALL_ROOT:-/opt/hermes-max}"
VAR_ROOT="${HERMES_VAR_ROOT:-/var/lib/hermes}"
SYSTEMD_DIR="${HERMES_SYSTEMD_DIR:-/etc/systemd/system}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
STATE_ROOT="$VAR_ROOT/state"
LEGACY_RUNTIME_ROOT="$VAR_ROOT/.hermes/hermes-agent"
RUNTIME_RELEASES_DIR="$VAR_ROOT/.hermes/runtime-releases"
RUNTIME_ACTIVE_LINK="$VAR_ROOT/.hermes/hermes-agent-current"
RELEASE_ID="${EXPECTED_SHA:0:16}"
TARGET="$RELEASES_DIR/$RELEASE_ID"
TMP_TARGET="$RELEASES_DIR/.${RELEASE_ID}.tmp.$$"
RUNTIME_TARGET="$RUNTIME_RELEASES_DIR/$RELEASE_ID"
RUNTIME_PREVIOUS="$(readlink -f "$RUNTIME_ACTIVE_LINK" 2>/dev/null || true)"
if [[ -z "$RUNTIME_PREVIOUS" && -d "$LEGACY_RUNTIME_ROOT" ]]; then RUNTIME_PREVIOUS="$LEGACY_RUNTIME_ROOT"; fi
CURRENT_PREVIOUS="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
MANAGED_SKILLS_CURRENT="$VAR_ROOT/.hermes/managed-skill-releases/hermes-ultra/current"
MANAGED_SKILLS_PREVIOUS="$(readlink "$MANAGED_SKILLS_CURRENT" 2>/dev/null || true)"
RUNTIME_SKILL_SYNC_SCRIPT=""
SUCCESS=0; RUNTIME_TARGET_CREATED=0; RUNTIME_ACTIVE_SWAPPED=0; CURRENT_SWAPPED=0; RUNTIME_SERVICE_STARTED=0; RUNTIME_SERVICE_WAS_ACTIVE=0; RUNTIME_SKILLS_SYNCED=0
cleanup(){
  local rc=$?
  if [[ "$SUCCESS" != 1 && "$TEST_MODE" != 1 && "$RUNTIME_SERVICE_STARTED" == 1 ]]; then systemctl stop hermes-runtime.service >/dev/null 2>&1 || true; fi
  rm -rf "$TMP_TARGET" 2>/dev/null || true
  if [[ "$SUCCESS" != 1 && "$CURRENT_SWAPPED" == 1 ]]; then
    if [[ -n "$CURRENT_PREVIOUS" && -d "$CURRENT_PREVIOUS" ]]; then
      ln -sfn "$CURRENT_PREVIOUS" "$CURRENT_LINK.rollback" && mv -Tf "$CURRENT_LINK.rollback" "$CURRENT_LINK"
    else
      rm -f "$CURRENT_LINK"
    fi
  fi
  if [[ "$SUCCESS" != 1 && "$RUNTIME_ACTIVE_SWAPPED" == 1 ]]; then
    if [[ -n "$RUNTIME_PREVIOUS" && -d "$RUNTIME_PREVIOUS" ]]; then
      ln -sfn "$RUNTIME_PREVIOUS" "$RUNTIME_ACTIVE_LINK.rollback" && mv -Tf "$RUNTIME_ACTIVE_LINK.rollback" "$RUNTIME_ACTIVE_LINK"
    else
      rm -f "$RUNTIME_ACTIVE_LINK"
    fi
  fi
  if [[ "$SUCCESS" != 1 && "$RUNTIME_SKILLS_SYNCED" == 1 && -n "$RUNTIME_SKILL_SYNC_SCRIPT" ]]; then
    rollback_release="${MANAGED_SKILLS_PREVIOUS:-NONE}"
    if [[ "$TEST_MODE" == 1 ]]; then
      HERMES_HOME="$VAR_ROOT/.hermes" bash "$RUNTIME_SKILL_SYNC_SCRIPT" rollback "$rollback_release" >/dev/null 2>&1 || true
    else
      HERMES_HOME="$VAR_ROOT/.hermes" bash "$RUNTIME_SKILL_SYNC_SCRIPT" rollback "$rollback_release" >/dev/null 2>&1 || true
    fi
  fi
  if [[ "$SUCCESS" != 1 && "$RUNTIME_TARGET_CREATED" == 1 && "$RUNTIME_TARGET" != "$RUNTIME_PREVIOUS" ]]; then rm -rf "$RUNTIME_TARGET"; fi
  if [[ "$SUCCESS" != 1 && "$TEST_MODE" != 1 && "$RUNTIME_SERVICE_STARTED" == 1 && "$RUNTIME_SERVICE_WAS_ACTIVE" == 1 ]]; then
    systemctl restart hermes-runtime.service >/dev/null 2>&1 || true
  fi
  return "$rc"
}
trap cleanup EXIT

if [[ "$TEST_MODE" != 1 && "$EUID" -ne 0 ]]; then echo 'installer must run as root' >&2; exit 1; fi
for cmd in sha256sum tar find python3; do command -v "$cmd" >/dev/null || { echo "required command missing: $cmd" >&2; exit 1; }; done
if [[ "$TEST_MODE" == 1 ]]; then
  mkdir -p "$RELEASES_DIR" "$STATE_ROOT" "$VAR_ROOT/.hermes" "$RUNTIME_RELEASES_DIR"
else
  command -v runuser >/dev/null 2>&1 || { echo 'runuser is required' >&2; exit 1; }
  command -v systemctl >/dev/null 2>&1 || { echo 'systemctl is required' >&2; exit 1; }
  if systemctl is-active --quiet hermes-runtime.service 2>/dev/null; then RUNTIME_SERVICE_WAS_ACTIVE=1; fi
  if ! id hermes >/dev/null 2>&1; then useradd --system --create-home --home-dir "$VAR_ROOT" --shell /bin/bash hermes; fi
  install -d -o hermes -g hermes -m 0750 "$INSTALL_ROOT" "$RELEASES_DIR" "$VAR_ROOT/.hermes" "$VAR_ROOT/.hermes/skills" "$RUNTIME_RELEASES_DIR" "$VAR_ROOT/.config/hermes" "$STATE_ROOT"
fi

rm -rf "$TMP_TARGET"; mkdir -p "$TMP_TARGET"
tar -xzf "$ARCHIVE" -C "$TMP_TARGET"
ROOT_COUNT="$(find "$TMP_TARGET" -mindepth 1 -maxdepth 1 | wc -l)"
if [[ "$ROOT_COUNT" == 1 ]]; then
  INNER="$(find "$TMP_TARGET" -mindepth 1 -maxdepth 1 -type d -print -quit)"
  if [[ -n "$INNER" ]]; then shopt -s dotglob; mv "$INNER"/* "$TMP_TARGET"/; shopt -u dotglob; rmdir "$INNER"; fi
fi
for f in skills-lock.json CLOUD_RELEASE_MANIFEST.sha256 SBOM.spdx.json RELEASE_PROVENANCE.json; do
  [[ -f "$TMP_TARGET/$f" ]] || { echo "required release evidence missing: $f" >&2; exit 1; }
done
VENDORED="$TMP_TARGET/vendor/hermes-agent/0.20.5"
for f in SOURCE_TAG SOURCE_COMMIT SOURCE_PROVENANCE.json SOURCE_MANIFEST.sha256 uv.lock requirements-hermes-all.lock.txt requirements-hermes-build.lock.txt DEPENDENCY_LOCK_PROVENANCE.json; do
  [[ -f "$VENDORED/$f" ]] || { echo "required Hermes evidence missing: $f" >&2; exit 1; }
done
( cd "$TMP_TARGET" && sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null ) || { echo 'internal release manifest verification failed' >&2; exit 1; }
python3 - "$TMP_TARGET" <<'PY'
import hashlib,json,pathlib,re,sys
root=pathlib.Path(sys.argv[1]); v=root/'vendor/hermes-agent/0.20.5'
if json.loads((root/'SBOM.spdx.json').read_text()).get('spdxVersion')!='SPDX-2.3': raise SystemExit('invalid SBOM')
json.loads((root/'RELEASE_PROVENANCE.json').read_text())
sp=json.loads((v/'SOURCE_PROVENANCE.json').read_text())
if (v/'SOURCE_TAG').read_text().strip()!='v2026.8.19' or sp.get('source_tag')!='v2026.8.19' or sp.get('version')!='0.20.5': raise SystemExit('Hermes production pin mismatch')
if not re.fullmatch(r'[0-9a-f]{40}', (v/'SOURCE_COMMIT').read_text().strip()): raise SystemExit('invalid Hermes source commit')
dp=json.loads((v/'DEPENDENCY_LOCK_PROVENANCE.json').read_text()); sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
if dp.get('mode')!='uv-export-locked-no-project': raise SystemExit('unexpected dependency lock mode')
checks={'uv_lock_sha256':v/'uv.lock','runtime_requirements_sha256':v/'requirements-hermes-all.lock.txt','build_requirements_sha256':v/'requirements-hermes-build.lock.txt'}
for key,path in checks.items():
    if dp.get(key)!=sha(path): raise SystemExit('dependency lock provenance mismatch: '+key)
runtime=(v/'requirements-hermes-all.lock.txt').read_text(); build=(v/'requirements-hermes-build.lock.txt').read_text()
if '--hash=sha256:' not in runtime or re.search(r'(?m)^\s*-e\s+|(?i:git\+|https?://)', runtime): raise SystemExit('runtime requirements are not hash-only locked')
if 'setuptools==83.0.0' not in build or '--hash=sha256:' not in build: raise SystemExit('build backend lock invalid')
PY

if [[ -d "$TARGET" ]]; then
  ( cd "$TARGET" && sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null ) || { echo 'existing release target is corrupt' >&2; exit 1; }
  rm -rf "$TMP_TARGET"
else
  mv "$TMP_TARGET" "$TARGET"
fi
RUNTIME_SKILL_SYNC_SCRIPT="$TARGET/scripts/sync-hermes-ultra-runtime-skills.sh"
[[ -f "$RUNTIME_SKILL_SYNC_SCRIPT" ]] || { echo 'managed runtime skill sync script missing from release' >&2; exit 1; }
if [[ "$TEST_MODE" == 1 ]]; then
  HERMES_HOME="$VAR_ROOT/.hermes" bash "$RUNTIME_SKILL_SYNC_SCRIPT" apply "$TARGET" "$RELEASE_ID"
else
  HERMES_HOME="$VAR_ROOT/.hermes" bash "$RUNTIME_SKILL_SYNC_SCRIPT" apply "$TARGET" "$RELEASE_ID"
fi
RUNTIME_SKILLS_SYNCED=1
if [[ "$TEST_MODE" == 1 && "${HERMES_INSTALL_TEST_FAIL_AFTER_SKILL_SYNC:-0}" == 1 ]]; then
  echo 'test failure after managed runtime skill sync' >&2
  exit 97
fi
if [[ "$TEST_MODE" != 1 ]]; then chown -R hermes:hermes "$TARGET"; fi

if [[ "$TEST_MODE" != 1 ]]; then
  bash "$TARGET/scripts/ensure-node-runtime.sh"
  VENDORED="$TARGET/vendor/hermes-agent/0.20.5"
  if [[ "$RUNTIME_PREVIOUS" != "$RUNTIME_TARGET" ]]; then
    rm -rf "$RUNTIME_TARGET"
    cp -a "$VENDORED" "$RUNTIME_TARGET"
    RUNTIME_TARGET_CREATED=1
    chown -R hermes:hermes "$RUNTIME_TARGET"
    ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" python3 -m venv "$RUNTIME_TARGET/venv" ) || { echo 'python venv creation failed; install python3-venv first' >&2; exit 1; }
    PY="$RUNTIME_TARGET/venv/bin/python"
    ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 "$PY" -m pip install --require-hashes -r "$RUNTIME_TARGET/requirements-hermes-build.lock.txt" )
    ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 "$PY" -m pip install --require-hashes -r "$RUNTIME_TARGET/requirements-hermes-all.lock.txt" )
    ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 "$PY" -m pip install --no-deps --no-build-isolation -e "$RUNTIME_TARGET" )
    if [[ -f "$RUNTIME_TARGET/tools/skills_sync.py" ]]; then
      ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" HERMES_HOME="$VAR_ROOT/.hermes" "$PY" "$RUNTIME_TARGET/tools/skills_sync.py" )
    fi
  else
    PY="$RUNTIME_TARGET/venv/bin/python"
  fi
  ( cd /tmp && runuser -u hermes -- env HOME="$VAR_ROOT" "$PY" -c 'import hermes_cli, hermes_cli.mcp_config' )
  for entry in hermes pip uvicorn; do
    path="$RUNTIME_TARGET/venv/bin/$entry"
    [[ -f "$path" ]] || continue
    first="$(head -n1 "$path")"
    [[ "$first" == "#!$RUNTIME_TARGET/venv/bin/"* ]] || { echo "runtime entrypoint is not final-path stable: $entry" >&2; exit 1; }
  done
  runuser -u hermes -- "$TARGET/scripts/restore-vps-transfer.sh" --skip-agent-reach --skip-python-deps
  runuser -u hermes -- env HOME="$VAR_ROOT" HERMES_HOME="$VAR_ROOT/.hermes" HERMES_RUNTIME_PYTHON="$RUNTIME_TARGET/venv/bin/python" bash "$TARGET/scripts/sync-mcp-provider-registry.sh" apply
  runuser -u hermes -- "$TARGET/scripts/verify-cloud-foundation.sh"
  tmp_runtime_link="$VAR_ROOT/.hermes/.hermes-agent-current.install.$$"
  ln -s "$RUNTIME_TARGET" "$tmp_runtime_link"
  mv -Tf "$tmp_runtime_link" "$RUNTIME_ACTIVE_LINK"
  RUNTIME_ACTIVE_SWAPPED=1
  install -d -o hermes -g hermes -m 0750 "$VAR_ROOT/.local/bin"
  ln -sfn "$RUNTIME_ACTIVE_LINK/venv/bin/hermes" "$VAR_ROOT/.local/bin/hermes"
  chown -h hermes:hermes "$VAR_ROOT/.local/bin/hermes"
fi

TMP_LINK="$INSTALL_ROOT/.current.install.$$"
ln -s "$TARGET" "$TMP_LINK"; mv -Tf "$TMP_LINK" "$CURRENT_LINK"; CURRENT_SWAPPED=1
mkdir -p "$SYSTEMD_DIR"
LEGACY_RUNTIME_DROPIN="$SYSTEMD_DIR/hermes-runtime.service.d/0205.conf"
rm -f "$LEGACY_RUNTIME_DROPIN"
rmdir "$SYSTEMD_DIR/hermes-runtime.service.d" 2>/dev/null || true
cat >"$SYSTEMD_DIR/hermes-runtime.service" <<UNIT
[Unit]
Description=Hermes Agent headless backend
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=hermes
Group=hermes
WorkingDirectory=$RUNTIME_ACTIVE_LINK
Environment=HOME=$VAR_ROOT
Environment=HERMES_HOME=$VAR_ROOT/.hermes
Environment=PATH=$VAR_ROOT/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=ORCA_CLI_COMMAND=/opt/orca/bin/orca-ide
Environment=ORCA_USER_DATA_PATH=/var/lib/hermes/.config/hermes/orca-client/orca
Environment=ORCA_ENVIRONMENT=hermes-runtime
Environment=DO_NOT_TRACK=1
Environment=ORCA_TELEMETRY_DISABLED=1
ExecStart=$VAR_ROOT/.local/bin/hermes serve --host 127.0.0.1 --port 9119
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_ROOT $VAR_ROOT
[Install]
WantedBy=multi-user.target
UNIT
if [[ "$TEST_MODE" != 1 ]]; then
  cat >"$SYSTEMD_DIR/hermes-foundation-verify.service" <<UNIT
[Unit]
Description=Hermes Max foundation verification
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=hermes
Group=hermes
WorkingDirectory=$CURRENT_LINK
ExecStart=$CURRENT_LINK/scripts/verify-cloud-foundation.sh
RemainAfterExit=yes
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_ROOT $VAR_ROOT
[Install]
WantedBy=multi-user.target
UNIT
  ORCA_BOOTSTRAP="$TARGET/scripts/bootstrap-hermes-orca-client.sh"
  [[ -f "$ORCA_BOOTSTRAP" ]] || { echo 'Hermes Orca client bootstrap is missing from release' >&2; exit 1; }
  [[ -x /opt/orca/bin/orca-ide ]] || { echo 'Orca headless CLI is not installed' >&2; exit 1; }
  systemctl is-active --quiet orca-serve.service || { echo 'Orca runtime service is not active' >&2; exit 1; }
  ORCA_CLI_COMMAND=/opt/orca/bin/orca-ide \
  ORCA_CLIENT_HOME="$VAR_ROOT" \
  ORCA_USER_DATA_PATH="$VAR_ROOT/.config/hermes/orca-client/orca" \
  ORCA_ENVIRONMENT_NAME=hermes-runtime \
    bash "$ORCA_BOOTSTRAP"
  systemctl daemon-reload
  systemctl enable --now hermes-foundation-verify.service
  systemctl enable hermes-runtime.service
  systemctl restart hermes-runtime.service
  RUNTIME_SERVICE_STARTED=1
  ready=0
  for _ in $(seq 1 30); do
    if python3 - <<'PYHEALTH'
import json, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:9119/api/health', timeout=2) as r:
        body=json.load(r)
    raise SystemExit(0 if body.get('ok') is True and body.get('version') == '0.20.5' else 1)
except Exception:
    raise SystemExit(1)
PYHEALTH
    then ready=1; break; fi
    sleep 2
  done
  [[ "$ready" == 1 ]] || { echo 'Hermes runtime health check failed' >&2; exit 1; }
  if command -v tailscale >/dev/null 2>&1; then
    if tailscale status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("BackendState")=="Running" and d.get("Self",{}).get("Online") is True else 1)'; then
      "$TARGET/scripts/configure-tailscale-hermes.sh"
    fi
  fi
fi
SUCCESS=1
printf 'HERMES_LOCAL_INSTALL=PASS release=%s\n' "$RELEASE_ID"
