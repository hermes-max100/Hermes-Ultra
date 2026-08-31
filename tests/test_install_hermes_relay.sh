#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/install-hermes-relay.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"; mkdir -p "$BIN"
LOG="$TMP/commands.log"; : > "$LOG"

cat > "$BIN/tailscale" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == ip && "${2:-}" == -4 ]] || exit 2
printf '%s\n' "${FAKE_TS_IP:-100.64.0.42}"
EOF
cat > "$BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >> "$FAKE_COMMAND_LOG"
case "${1:-}" in
  is-enabled) echo disabled; exit 1 ;;
  is-active) echo inactive; exit 3 ;;
esac
exit 0
EOF
cat > "$BIN/hermes" <<'EOF'
#!/usr/bin/env bash
printf 'hermes %s\n' "$*" >> "$FAKE_COMMAND_LOG"
if [[ "${FAKE_HERMES_FAIL:-}" == doctor && "$*" == *'plugins doctor'* ]]; then exit 9; fi
exit 0
EOF
cat > "$BIN/python-runtime" <<'EOF'
#!/usr/bin/env bash
printf 'runtime-python %s\n' "$*" >> "$FAKE_COMMAND_LOG"
exit 0
EOF
chmod +x "$BIN"/*

make_release() {
  local root="$1"
  local vendor="$root/vendor/hermes-relay/server-v1.10.0"
  mkdir -p "$root/config" "$vendor/source/plugin" "$vendor/source/plugin/relay"
  printf 'name: hermes-relay\nmanifest_version: 1\nversion: 1.10.0\n' > "$vendor/source/plugin/plugin.yaml"
  printf 'runtime\n' > "$vendor/source/plugin/relay/server.py"
  printf 'version = 1\n' > "$vendor/uv.lock"
  printf 'demo==1.0 --hash=sha256:%064d\n' 0 > "$vendor/requirements-hermes-relay.lock.txt"
  printf 'wheel-fixture\n' > "$vendor/hermes_relay-1.10.0-py3-none-any.whl"
  printf 'MIT\n' > "$vendor/LICENSE"
  local commit='0123456789abcdef0123456789abcdef01234567'
  local wheel_sha; wheel_sha="$(sha256sum "$vendor/hermes_relay-1.10.0-py3-none-any.whl" | awk '{print $1}')"
  printf '%s\n' "$commit" > "$vendor/SOURCE_COMMIT"
  printf 'server-v1.10.0\n' > "$vendor/SOURCE_TAG"
  python3 - "$vendor" <<'PY'
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
(r/'DEPENDENCY_LOCK_PROVENANCE.json').write_text(json.dumps({
 'mode':'uv-export-frozen-validated-no-project','project_version':'1.10.0','lock_project_version':'1.6.4','root_version_mismatch':True,'dependency_metadata_match':True,'uv_version':'uv test',
 'uv_lock_sha256':sha(r/'uv.lock'),
 'runtime_requirements_sha256':sha(r/'requirements-hermes-relay.lock.txt')},sort_keys=True)+'\n')
PY
  (cd "$vendor" && find . -type f ! -name SOURCE_MANIFEST.sha256 ! -name SOURCE_PROVENANCE.json -print0 | sort -z | xargs -0 sha256sum > SOURCE_MANIFEST.sha256)
  local tree_sha; tree_sha="$(sha256sum "$vendor/SOURCE_MANIFEST.sha256" | awk '{print $1}')"
  python3 - "$vendor/SOURCE_PROVENANCE.json" "$commit" "$tree_sha" "$wheel_sha" <<'PY'
import json,pathlib,sys
out,commit,tree,wheel=sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({'source_commit':commit,'source_tag':'server-v1.10.0','version':'1.10.0','artifact':'hermes_relay-1.10.0-py3-none-any.whl','artifact_sha256':wheel,'tree_sha256':tree},sort_keys=True)+'\n')
PY
  python3 - "$root/config/hermes-relay-upstream.json" "$commit" "$wheel_sha" <<'PY'
import json,pathlib,sys
out,commit,wheel=sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({'schema_version':1,'server':{'tag':'server-v1.10.0','version':'1.10.0','commit':commit,'artifact':'hermes_relay-1.10.0-py3-none-any.whl','artifact_sha256':wheel,'license':'MIT'}},sort_keys=True)+'\n')
PY
}

[[ -x "$SCRIPT" ]] || { echo 'Relay installer missing' >&2; exit 1; }
RELEASE="$TMP/release"; make_release "$RELEASE"
HERMES_HOME="$TMP/home/.hermes"; SYSTEMD_DIR="$TMP/systemd"; mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/plugin-data/hermes-relay" "$SYSTEMD_DIR"
printf 'durable-session\n' > "$HERMES_HOME/hermes-relay-sessions.json"
printf 'durable-plugin-data\n' > "$HERMES_HOME/plugin-data/hermes-relay/state"
printf 'signing-id\n' > "$HERMES_HOME/relay-signing-identity"
printf 'old-config\n' > "$HERMES_HOME/config.yaml"
printf 'old-unit\n' > "$SYSTEMD_DIR/hermes-relay.service"
OLD_PLUGIN="$TMP/old-plugin"; mkdir -p "$OLD_PLUGIN"; ln -s "$OLD_PLUGIN" "$HERMES_HOME/plugins/hermes-relay"

COMMON=(--release-root "$RELEASE" --runtime-python "$BIN/python-runtime" --hermes-home "$HERMES_HOME" --systemd-dir "$SYSTEMD_DIR" --test-mode)
PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" HERMES_RELAY_HERMES_BIN="$BIN/hermes" HERMES_RELAY_TEST_SCAN_VERDICT=safe bash "$SCRIPT" prepare "${COMMON[@]}" | grep -q 'HERMES_RELAY_PREPARE=PASS'
grep -q 'runtime-python -m pip install --require-hashes' "$LOG"
[[ "$(readlink "$HERMES_HOME/plugins/hermes-relay")" == "$OLD_PLUGIN" ]]
grep -qx old-config "$HERMES_HOME/config.yaml"
grep -qx old-unit "$SYSTEMD_DIR/hermes-relay.service"

if PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" FAKE_TS_IP=10.0.0.7 HERMES_RELAY_TEST_SCAN_VERDICT=safe bash "$SCRIPT" prepare "${COMMON[@]}" >/dev/null 2>&1; then
  echo 'non-tailnet bind accepted' >&2; exit 1
fi
for verdict in caution dangerous; do
  if PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" HERMES_RELAY_TEST_SCAN_VERDICT="$verdict" bash "$SCRIPT" prepare "${COMMON[@]}" >/dev/null 2>&1; then
    echo "$verdict plugin scan accepted" >&2; exit 1
  fi
done

: > "$LOG"
PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" HERMES_RELAY_HERMES_BIN="$BIN/hermes" HERMES_RELAY_TEST_HEALTH=ok bash "$SCRIPT" activate "${COMMON[@]}" | grep -q 'HERMES_RELAY_ACTIVATE=PASS'
[[ "$(readlink "$HERMES_HOME/plugins/hermes-relay")" == "$RELEASE/vendor/hermes-relay/server-v1.10.0/source/plugin" ]]
UNIT="$SYSTEMD_DIR/hermes-relay.service"
grep -q '^User=hermes$' "$UNIT"
grep -q '^Group=hermes$' "$UNIT"
grep -q -- '--host 100.64.0.42 --port 8767 --no-ssl --log-level INFO' "$UNIT"
grep -q '^NoNewPrivileges=yes$' "$UNIT"
grep -q '^PrivateTmp=yes$' "$UNIT"
grep -q '^ProtectSystem=strict$' "$UNIT"
grep -q '^ProtectHome=true$' "$UNIT"
! grep -qiE 'api[_-]?key|bearer|token=' "$UNIT"
grep -q 'hermes plugins enable hermes-relay --no-allow-tool-override' "$LOG"
grep -q 'hermes plugins doctor hermes-relay --ci' "$LOG"
for f in "$HERMES_HOME/hermes-relay-sessions.json" "$HERMES_HOME/plugin-data/hermes-relay/state" "$HERMES_HOME/relay-signing-identity"; do [[ -f "$f" ]]; done

# A failed activation must restore the prior code link/config/unit and leave durable state alone.
rm -f "$HERMES_HOME/plugins/hermes-relay"; ln -s "$OLD_PLUGIN" "$HERMES_HOME/plugins/hermes-relay"
printf 'old-config\n' > "$HERMES_HOME/config.yaml"; printf 'old-unit\n' > "$UNIT"
if PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" HERMES_RELAY_HERMES_BIN="$BIN/hermes" FAKE_HERMES_FAIL=doctor HERMES_RELAY_TEST_HEALTH=ok bash "$SCRIPT" activate "${COMMON[@]}" >/dev/null 2>&1; then
  echo 'failed Relay activation reported success' >&2; exit 1
fi
[[ "$(readlink "$HERMES_HOME/plugins/hermes-relay")" == "$OLD_PLUGIN" ]]
grep -qx old-config "$HERMES_HOME/config.yaml"
grep -qx old-unit "$UNIT"
grep -qx durable-session "$HERMES_HOME/hermes-relay-sessions.json"
grep -qx durable-plugin-data "$HERMES_HOME/plugin-data/hermes-relay/state"
grep -qx signing-id "$HERMES_HOME/relay-signing-identity"

# Tampered evidence must fail before any activation mutation.
printf 'tamper\n' >> "$RELEASE/vendor/hermes-relay/server-v1.10.0/source/plugin/relay/server.py"
if PATH="$BIN:$PATH" FAKE_COMMAND_LOG="$LOG" HERMES_RELAY_TEST_SCAN_VERDICT=safe bash "$SCRIPT" prepare "${COMMON[@]}" >/dev/null 2>&1; then
  echo 'tampered Relay evidence accepted' >&2; exit 1
fi

echo 'Hermes Relay installer tests passed'
