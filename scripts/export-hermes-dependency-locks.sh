#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="${1:?source directory required}"
DEST_DIR="${2:?destination directory required}"
UV_LOCK="$SOURCE_DIR/uv.lock"
UV_BIN="${HERMES_UV_BIN:-$(command -v uv 2>/dev/null || true)}"
[[ -f "$UV_LOCK" ]] || { echo 'Hermes uv.lock missing' >&2; exit 1; }
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || { echo 'uv is required to export locked Hermes dependencies' >&2; exit 1; }
mkdir -p "$DEST_DIR"
RUNTIME="$DEST_DIR/requirements-hermes-all.lock.txt"
BUILD="$DEST_DIR/requirements-hermes-build.lock.txt"
PROV="$DEST_DIR/DEPENDENCY_LOCK_PROVENANCE.json"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
(
  cd "$SOURCE_DIR"
  "$UV_BIN" export --extra all --locked --format requirements-txt --no-dev \
    --no-emit-project --output-file "$TMP" >/dev/null
)
python3 - "$TMP" "$RUNTIME" <<'PY'
import pathlib, re, sys
src, out = map(pathlib.Path, sys.argv[1:])
text = src.read_text()
if re.search(r'(?m)^\s*-e\s+', text) or re.search(r'(?i)(git\+|https?://)', text):
    raise SystemExit('locked export contains editable or direct URL dependency')
blocks=[]; current=[]
for line in text.splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    if line[:1].isspace():
        if current: current.append(line)
        continue
    if current: blocks.append(current)
    current=[line]
if current: blocks.append(current)
if not blocks:
    raise SystemExit('locked export contains no requirements')
for block in blocks:
    joined='\n'.join(block)
    if '--hash=sha256:' not in joined:
        raise SystemExit('locked export contains unhashed requirement: ' + block[0].split()[0])
out.write_text(text)
PY
python3 - "$UV_LOCK" "$BUILD" <<'PY'
import pathlib, re, sys, tomllib
lock, out = map(pathlib.Path, sys.argv[1:])
data = tomllib.loads(lock.read_text())
matches=[p for p in data.get('package',[]) if p.get('name')=='setuptools' and p.get('version')=='83.0.0']
if len(matches)!=1:
    raise SystemExit('setuptools 83.0.0 missing from Hermes uv.lock')
pkg=matches[0]
hashes=[]
for entry in [pkg.get('sdist'), *pkg.get('wheels',[])]:
    if not entry: continue
    value=entry.get('hash','')
    if re.fullmatch(r'sha256:[0-9a-f]{64}', value): hashes.append(value)
if not hashes:
    raise SystemExit('setuptools hashes missing from Hermes uv.lock')
lines=['setuptools==83.0.0 \\']
for i,value in enumerate(sorted(set(hashes))):
    suffix=' \\' if i < len(set(hashes))-1 else ''
    lines.append(f'    --hash={value}{suffix}')
out.write_text('\n'.join(lines)+'\n')
PY
UV_VERSION="$($UV_BIN --version | head -1)"
python3 - "$UV_LOCK" "$RUNTIME" "$BUILD" "$PROV" "$UV_VERSION" <<'PY'
import hashlib, json, pathlib, sys
lock, runtime, build, prov = map(pathlib.Path, sys.argv[1:5]); uv_version=sys.argv[5]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
prov.write_text(json.dumps({
  'mode':'uv-export-locked-no-project',
  'uv_version':uv_version,
  'uv_lock_sha256':sha(lock),
  'runtime_requirements_sha256':sha(runtime),
  'build_requirements_sha256':sha(build),
}, indent=2, sort_keys=True)+'\n')
PY
printf 'HERMES_DEPENDENCY_LOCK_EXPORT=PASS\n'
