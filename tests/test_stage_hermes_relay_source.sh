#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/stage-hermes-relay-source.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC="$TMP/source"; DEST="$TMP/staged"; WHEEL="$TMP/hermes_relay-1.10.0-py3-none-any.whl"
mkdir -p "$SRC/plugin/relay" "$SRC/relay_server" "$SRC/hermes_relay_bootstrap" "$SRC/tests" "$SRC/app" "$SRC/desktop"
cat > "$SRC/pyproject.toml" <<'TOML'
[project]
name = "hermes-relay"
version = "1.10.0"
dependencies = ["aiohttp>=3.14.1,<4"]
TOML
cat > "$SRC/plugin/plugin.yaml" <<'YAML'
name: hermes-relay
manifest_version: 1
version: 1.10.0
provides_tools:
  - android_ping
  - desktop_health
YAML
printf 'MIT test license\n' > "$SRC/LICENSE"
printf 'print("relay")\n' > "$SRC/plugin/relay/server.py"
printf 'shim\n' > "$SRC/relay_server/__init__.py"
printf 'bootstrap\n' > "$SRC/hermes_relay_bootstrap/__init__.py"
printf 'bootstrap-pth\n' > "$SRC/hermes_relay_bootstrap.pth"
printf 'excluded-test\n' > "$SRC/tests/test_x.py"
printf 'excluded-app\n' > "$SRC/app/mobile.txt"
printf 'excluded-desktop\n' > "$SRC/desktop/client.txt"
cat > "$SRC/uv.lock" <<'LOCK'
version = 1
revision = 3
[[package]]
name = "aiohttp"
version = "3.14.3"
[[package]]
name = "hermes-relay"
version = "1.6.4"
source = { editable = "." }
dependencies = [{ name = "aiohttp" }]
[package.metadata]
requires-dist = [{ name = "aiohttp", specifier = ">=3.14.1,<4" }]
LOCK
printf 'wheel fixture\n' > "$WHEEL"
FAKE_UV="$TMP/uv"
cat > "$FAKE_UV" <<'UV'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == '--version' ]] && { echo 'uv 0.11.32 (test)'; exit 0; }
out=''
for ((i=1;i<=$#;i++)); do
  if [[ "${!i}" == '--output-file' ]]; then j=$((i+1)); out="${!j}"; fi
done
printf 'aiohttp==3.14.3 \\\n    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$out"
UV
chmod +x "$FAKE_UV"
git -C "$SRC" init -q
git -C "$SRC" config user.email test@example.invalid
git -C "$SRC" config user.name test
git -C "$SRC" add .
git -C "$SRC" commit -qm initial
git -C "$SRC" tag server-v1.10.0
COMMIT="$(git -C "$SRC" rev-parse HEAD)"
WHEEL_SHA="$(sha256sum "$WHEEL" | awk '{print $1}')"
MANIFEST="$TMP/manifest.json"
python3 - "$MANIFEST" "$COMMIT" "$WHEEL_SHA" <<'PY'
import json, pathlib, sys
out, commit, wheel_sha = sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({
  'schema_version': 1,
  'server': {
    'tag': 'server-v1.10.0',
    'version': '1.10.0',
    'commit': commit,
    'artifact': 'hermes_relay-1.10.0-py3-none-any.whl',
    'artifact_sha256': wheel_sha,
    'license': 'MIT',
  },
}, indent=2) + '\n')
PY
[[ -x "$SCRIPT" ]] || { echo 'Relay source stager missing' >&2; exit 1; }
HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$MANIFEST" "$SRC" "$WHEEL" "$DEST"
for f in SOURCE_TAG SOURCE_COMMIT SOURCE_PROVENANCE.json SOURCE_MANIFEST.sha256 uv.lock requirements-hermes-relay.lock.txt DEPENDENCY_LOCK_PROVENANCE.json hermes_relay-1.10.0-py3-none-any.whl LICENSE; do
  [[ -f "$DEST/$f" ]] || { echo "missing $f" >&2; exit 1; }
done
[[ -f "$DEST/source/plugin/plugin.yaml" && -f "$DEST/source/plugin/relay/server.py" ]] || { echo 'runtime source missing' >&2; exit 1; }
[[ ! -e "$DEST/source/tests" && ! -e "$DEST/source/app" && ! -e "$DEST/source/desktop" && ! -e "$DEST/source/.git" ]] || { echo 'excluded Relay source leaked' >&2; exit 1; }
grep -qx "$COMMIT" "$DEST/SOURCE_COMMIT"
grep -qx 'server-v1.10.0' "$DEST/SOURCE_TAG"
( cd "$DEST" && sha256sum -c SOURCE_MANIFEST.sha256 >/dev/null )
printf 'dirty\n' >> "$SRC/plugin/relay/server.py"
if HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$MANIFEST" "$SRC" "$WHEEL" "$TMP/dirty" >/dev/null 2>&1; then
  echo 'dirty Relay source accepted' >&2; exit 1
fi
git -C "$SRC" reset --hard -q HEAD
BAD="$TMP/bad.json"
python3 - "$MANIFEST" "$BAD" <<'PY'
import json, pathlib, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
p['server']['commit']='0'*40
pathlib.Path(sys.argv[2]).write_text(json.dumps(p))
PY
if HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$BAD" "$SRC" "$WHEEL" "$TMP/wrong-commit" >/dev/null 2>&1; then
  echo 'wrong Relay commit accepted' >&2; exit 1
fi
python3 - "$MANIFEST" "$BAD" <<'PY'
import json, pathlib, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
p['server']['artifact_sha256']='f'*64
pathlib.Path(sys.argv[2]).write_text(json.dumps(p))
PY
if HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$BAD" "$SRC" "$WHEEL" "$TMP/wrong-wheel" >/dev/null 2>&1; then
  echo 'wrong Relay wheel accepted' >&2; exit 1
fi
git -C "$SRC" mv plugin/plugin.yaml plugin/plugin.yaml.missing
git -C "$SRC" commit -qm missing-manifest
git -C "$SRC" tag -f server-v1.10.0 >/dev/null
COMMIT2="$(git -C "$SRC" rev-parse HEAD)"
python3 - "$MANIFEST" "$BAD" "$COMMIT2" <<'PY'
import json, pathlib, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
p['server']['commit']=sys.argv[3]
pathlib.Path(sys.argv[2]).write_text(json.dumps(p))
PY
if HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$BAD" "$SRC" "$WHEEL" "$TMP/missing-manifest" >/dev/null 2>&1; then
  echo 'missing Relay plugin manifest accepted' >&2; exit 1
fi

git -C "$SRC" reset --hard -q HEAD~1
git -C "$SRC" tag -f server-v1.10.0 >/dev/null
sed -i 's/version: 1.10.0/version: 9.9.9/' "$SRC/plugin/plugin.yaml"
git -C "$SRC" add plugin/plugin.yaml && git -C "$SRC" commit -qm wrong-version
git -C "$SRC" tag -f server-v1.10.0 >/dev/null
COMMIT3="$(git -C "$SRC" rev-parse HEAD)"
python3 - "$MANIFEST" "$BAD" "$COMMIT3" <<'PY'
import json, pathlib, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
p['server']['commit']=sys.argv[3]
pathlib.Path(sys.argv[2]).write_text(json.dumps(p))
PY
if HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" --manifest "$BAD" "$SRC" "$WHEEL" "$TMP/wrong-version" >/dev/null 2>&1; then
  echo 'wrong Relay plugin version accepted' >&2; exit 1
fi
echo 'Hermes Relay source staging tests passed'
