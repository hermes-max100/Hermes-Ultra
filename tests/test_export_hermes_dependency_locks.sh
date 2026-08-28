#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/export-hermes-dependency-locks.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC="$TMP/source"; DEST="$TMP/dest"; mkdir -p "$SRC" "$DEST"
cat > "$SRC/uv.lock" <<'LOCK'
version = 1
revision = 3
requires-python = ">=3.11, <3.14"
[[package]]
name = "setuptools"
version = "83.0.0"
sdist = { url = "https://example.invalid/setuptools.tar.gz", hash = "sha256:025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef", size = 1 }
wheels = [
  { url = "https://example.invalid/setuptools.whl", hash = "sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3", size = 1 },
]
LOCK
FAKE_UV="$TMP/uv"
cat > "$FAKE_UV" <<'UV'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "--version" ]] && { echo 'uv 0.11.32 (test)'; exit 0; }
[[ "$1" == "export" ]]
printf '%s\n' "$*" | grep -q -- '--extra all'
printf '%s\n' "$*" | grep -q -- '--locked'
printf '%s\n' "$*" | grep -q -- '--no-emit-project'
out=''
for ((i=1;i<=$#;i++)); do
  if [[ "${!i}" == '--output-file' ]]; then j=$((i+1)); out="${!j}"; fi
done
[[ -n "$out" ]]
cat > "$out" <<'REQ'
demo==1.0 \
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
REQ
UV
chmod +x "$FAKE_UV"
[[ -x "$SCRIPT" ]] || { echo 'dependency lock exporter missing' >&2; exit 1; }
HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" "$SRC" "$DEST"
RUNTIME="$DEST/requirements-hermes-all.lock.txt"
BUILD="$DEST/requirements-hermes-build.lock.txt"
PROV="$DEST/DEPENDENCY_LOCK_PROVENANCE.json"
grep -q '^demo==1.0' "$RUNTIME"
grep -q -- '--hash=sha256:aaaaaaaa' "$RUNTIME"
! grep -qE '^-e |git\+|https?://' "$RUNTIME"
grep -q '^setuptools==83.0.0' "$BUILD"
grep -q '025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef' "$BUILD"
grep -q '29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3' "$BUILD"
python3 - "$PROV" "$SRC/uv.lock" <<'PY'
import hashlib,json,pathlib,sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert p['uv_version'].startswith('uv 0.11.32')
assert p['uv_lock_sha256']==hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest()
assert p['mode']=='uv-export-locked-no-project'
PY
echo 'Hermes dependency lock export tests passed'
