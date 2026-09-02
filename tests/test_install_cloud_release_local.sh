#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/scripts/install-cloud-release-local.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
make_release() {
  local dir="$1" marker="$2" archive="$3"
  mkdir -p "$dir/hermes-max/scripts" "$dir/hermes-max/vendor/hermes-agent/0.20.5" \
    "$dir/hermes-max/vendor/hermes-relay/server-v1.10.0" \
    "$dir/hermes-max/.agents/skills/design-engineer" "$dir/hermes-max/.agents/skills/web-design-guidelines"
  printf 'relay-fixture\n' > "$dir/hermes-max/vendor/hermes-relay/server-v1.10.0/fixture"
  printf '{"schema_version":1}\n' > "$dir/hermes-max/skills-lock.json"
  printf '{"spdxVersion":"SPDX-2.3"}\n' > "$dir/hermes-max/SBOM.spdx.json"
  printf '{"source_commit":"test-%s"}\n' "$marker" > "$dir/hermes-max/RELEASE_PROVENANCE.json"
  printf '%s\n' "$marker" > "$dir/hermes-max/release-marker.txt"
  cp "$ROOT_DIR/scripts/sync-hermes-ultra-runtime-skills.sh" "$dir/hermes-max/scripts/"
  printf -- '---\nname: design-engineer\ndescription: test %s\n---\n# Design Engineer %s\n' "$marker" "$marker" > "$dir/hermes-max/.agents/skills/design-engineer/SKILL.md"
  printf '{"schema_version":1,"marker":"%s"}\n' "$marker" > "$dir/hermes-max/.agents/skills/design-engineer/acceptance.json"
  printf '{"schema_version":1,"marker":"%s"}\n' "$marker" > "$dir/hermes-max/.agents/skills/design-engineer/sources.json"
  printf -- '---\nname: web-design-guidelines\ndescription: test %s\n---\n# Web Guidelines %s\n' "$marker" "$marker" > "$dir/hermes-max/.agents/skills/web-design-guidelines/SKILL.md"
  printf 'v2026.8.19\n' > "$dir/hermes-max/vendor/hermes-agent/0.20.5/SOURCE_TAG"
  printf '0123456789abcdef0123456789abcdef01234567\n' > "$dir/hermes-max/vendor/hermes-agent/0.20.5/SOURCE_COMMIT"
  printf '{"source_tag":"v2026.8.19","version":"0.20.5"}\n' > "$dir/hermes-max/vendor/hermes-agent/0.20.5/SOURCE_PROVENANCE.json"
  printf 'demo==1.0 --hash=sha256:%064d\n' 0 > "$dir/hermes-max/vendor/hermes-agent/0.20.5/requirements-hermes-all.lock.txt"
  printf 'setuptools==83.0.0 --hash=sha256:%064d\n' 1 > "$dir/hermes-max/vendor/hermes-agent/0.20.5/requirements-hermes-build.lock.txt"
  printf 'version = 1\n' > "$dir/hermes-max/vendor/hermes-agent/0.20.5/uv.lock"
  python3 - "$dir/hermes-max/vendor/hermes-agent/0.20.5" <<'PYDEP'
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
(r/'DEPENDENCY_LOCK_PROVENANCE.json').write_text(json.dumps({
 'mode':'uv-export-locked-no-project', 'uv_version':'uv test',
 'uv_lock_sha256':sha(r/'uv.lock'),
 'runtime_requirements_sha256':sha(r/'requirements-hermes-all.lock.txt'),
 'build_requirements_sha256':sha(r/'requirements-hermes-build.lock.txt')}, sort_keys=True)+'\n')
PYDEP
  (cd "$dir/hermes-max/vendor/hermes-agent/0.20.5" && find . -type f ! -name SOURCE_MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > SOURCE_MANIFEST.sha256)
  (cd "$dir/hermes-max" && find . -type f ! -name CLOUD_RELEASE_MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > CLOUD_RELEASE_MANIFEST.sha256)
  tar -C "$dir" -czf "$archive" hermes-max
}
[[ -x "$INSTALLER" ]] || { echo 'local cloud installer missing' >&2; exit 1; }
INSTALL_ROOT="$TMP/opt/hermes-max"
VAR_ROOT="$TMP/var/lib/hermes"
mkdir -p "$VAR_ROOT/state"
printf 'durable-state\n' > "$VAR_ROOT/state/sentinel"
R1="$TMP/r1"; A1="$TMP/release1.tar.gz"; make_release "$R1" one "$A1"
SHA1="$(sha256sum "$A1" | awk '{print $1}')"
SYSTEMD_DIR="$TMP/systemd"; mkdir -p "$SYSTEMD_DIR/hermes-runtime.service.d"
printf '[Service]\nExecStart=/legacy/hermes\n' > "$SYSTEMD_DIR/hermes-runtime.service.d/0205.conf"
printf '[Service]\nEnvironment=KEEP_ME=1\n' > "$SYSTEMD_DIR/hermes-runtime.service.d/keep.conf"
RELAY_LOG="$TMP/relay-installer.log"; : > "$RELAY_LOG"
FAKE_RELAY_INSTALLER="$TMP/fake-relay-installer.sh"
cat > "$FAKE_RELAY_INSTALLER" <<'RELAY'
#!/usr/bin/env bash
set -euo pipefail
mode="$1"; shift
current=""
if [[ -L "$FAKE_INSTALL_ROOT/current" ]]; then current="$(readlink -f "$FAKE_INSTALL_ROOT/current")"; fi
printf '%s current=%s\n' "$mode" "$current" >> "$FAKE_RELAY_LOG"
RELAY
chmod +x "$FAKE_RELAY_INSTALLER"
HERMES_INSTALL_TEST_MODE=1 HERMES_INSTALL_ROOT="$INSTALL_ROOT" HERMES_VAR_ROOT="$VAR_ROOT" HERMES_SYSTEMD_DIR="$SYSTEMD_DIR" \
  HERMES_RELAY_INSTALLER="$FAKE_RELAY_INSTALLER" FAKE_RELAY_LOG="$RELAY_LOG" FAKE_INSTALL_ROOT="$INSTALL_ROOT" \
  bash "$INSTALLER" "$A1" "$SHA1" | grep -q '^HERMES_LOCAL_INSTALL=PASS release='
CURRENT1="$(readlink -f "$INSTALL_ROOT/current")"
RID1="${SHA1:0:16}"
grep -Fxq 'prepare current=' "$RELAY_LOG"
grep -Fxq "activate current=$CURRENT1" "$RELAY_LOG"
[[ -f "$CURRENT1/release-marker.txt" ]] && grep -qx one "$CURRENT1/release-marker.txt"
[[ "$(readlink "$VAR_ROOT/.hermes/managed-skill-releases/hermes-ultra/current")" == "$RID1" ]]
[[ -L "$VAR_ROOT/.hermes/skills/design-engineer" ]]
[[ -L "$VAR_ROOT/.hermes/skills/web-design-guidelines" ]]
grep -q 'Design Engineer one' "$VAR_ROOT/.hermes/skills/design-engineer/SKILL.md"
grep -q 'Web Guidelines one' "$VAR_ROOT/.hermes/skills/web-design-guidelines/SKILL.md"
grep -qx durable-state "$VAR_ROOT/state/sentinel"
UNIT="$SYSTEMD_DIR/hermes-runtime.service"
[[ -f "$UNIT" ]] || { echo 'runtime systemd unit missing' >&2; exit 1; }
[[ ! -e "$SYSTEMD_DIR/hermes-runtime.service.d/0205.conf" ]] || { echo 'legacy 0205 runtime override survived install' >&2; exit 1; }
[[ -f "$SYSTEMD_DIR/hermes-runtime.service.d/keep.conf" ]] || { echo 'unrelated runtime override was removed' >&2; exit 1; }
grep -q 'User=hermes' "$UNIT"
grep -q 'serve --host 127.0.0.1 --port 9119' "$UNIT"
grep -q 'Restart=on-failure' "$UNIT"
grep -q 'Environment=ORCA_CLI_COMMAND=/opt/orca/bin/orca-ide' "$UNIT"
grep -q 'Environment=ORCA_USER_DATA_PATH=/var/lib/hermes/.config/hermes/orca-client/orca' "$UNIT"
grep -q 'Environment=ORCA_ENVIRONMENT=hermes-runtime' "$UNIT"
grep -q 'Environment=ORCA_TELEMETRY_DISABLED=1' "$UNIT"
grep -q "WorkingDirectory=$VAR_ROOT/.hermes/hermes-agent-current" "$UNIT"
grep -q 'runtime-releases' "$INSTALLER" || { echo 'installer does not use final versioned runtime paths' >&2; exit 1; }
grep -q 'hermes-agent-current' "$INSTALLER" || { echo 'installer lacks atomic runtime selector' >&2; exit 1; }
! grep -q 'mv "$RUNTIME_TMP" "$RUNTIME_ROOT"' "$INSTALLER" || { echo 'installer still relocates a built venv' >&2; exit 1; }
grep -q 'RUNTIME_SERVICE_WAS_ACTIVE' "$INSTALLER" || { echo 'installer does not restore prior service after rollback' >&2; exit 1; }
if grep -q 'runuser -u hermes.*RELAY_INSTALLER.*prepare' "$INSTALLER"; then
  echo 'Relay prepare incorrectly runs as hermes against root-owned runtime venv' >&2; exit 1
fi
grep -q '"$RELAY_INSTALLER" prepare --release-root "$TARGET" --runtime-python "$PY"' "$INSTALLER" || { echo 'Relay prepare is not executed by the privileged installer' >&2; exit 1; }
grep -q '/api/health' "$INSTALLER"
if HERMES_INSTALL_TEST_MODE=1 HERMES_INSTALL_ROOT="$INSTALL_ROOT" HERMES_VAR_ROOT="$VAR_ROOT" \
  bash "$INSTALLER" "$A1" "$(printf 'f%.0s' {1..64})" >/dev/null 2>&1; then
  echo 'wrong outer sha accepted' >&2; exit 1
fi
[[ "$(readlink -f "$INSTALL_ROOT/current")" == "$CURRENT1" ]]
R2="$TMP/r2"; A2="$TMP/release2.tar.gz"; make_release "$R2" two "$A2"
SHA2="$(sha256sum "$A2" | awk '{print $1}')"
RID2="${SHA2:0:16}"
if HERMES_INSTALL_TEST_MODE=1 HERMES_INSTALL_TEST_FAIL_AFTER_SKILL_SYNC=1 HERMES_INSTALL_ROOT="$INSTALL_ROOT" HERMES_VAR_ROOT="$VAR_ROOT" \
  bash "$INSTALLER" "$A2" "$SHA2" >/dev/null 2>&1; then
  echo 'post-skill-sync failure hook did not fail install' >&2; exit 1
fi
[[ "$(readlink -f "$INSTALL_ROOT/current")" == "$CURRENT1" ]]
[[ "$(readlink "$VAR_ROOT/.hermes/managed-skill-releases/hermes-ultra/current")" == "$RID1" ]]
grep -q 'Design Engineer one' "$VAR_ROOT/.hermes/skills/design-engineer/SKILL.md"

printf 'tampered\n' >> "$R2/hermes-max/release-marker.txt"
tar -C "$R2" -czf "$A2" hermes-max
SHA2_TAMPERED="$(sha256sum "$A2" | awk '{print $1}')"
if HERMES_INSTALL_TEST_MODE=1 HERMES_INSTALL_ROOT="$INSTALL_ROOT" HERMES_VAR_ROOT="$VAR_ROOT" \
  bash "$INSTALLER" "$A2" "$SHA2_TAMPERED" >/dev/null 2>&1; then
  echo 'tampered internal manifest accepted' >&2; exit 1
fi
[[ "$(readlink -f "$INSTALL_ROOT/current")" == "$CURRENT1" ]]
[[ "$(readlink "$VAR_ROOT/.hermes/managed-skill-releases/hermes-ultra/current")" == "$RID1" ]]
grep -qx durable-state "$VAR_ROOT/state/sentinel"
grep -q -- '--require-hashes' "$INSTALLER"
grep -q -- '--no-build-isolation' "$INSTALLER"
! grep -q 'setup-hermes.sh' "$INSTALLER"
! grep -qE 'pip install.*\|\||Falling back|_try_install' "$INSTALLER"
echo 'local cloud release installer tests passed'
