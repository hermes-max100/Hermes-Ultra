#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="${1:?source directory required}"
DEST_DIR="${2:?destination directory required}"
UV_LOCK="$SOURCE_DIR/uv.lock"
PYPROJECT="$SOURCE_DIR/pyproject.toml"
UV_BIN="${HERMES_UV_BIN:-$(command -v uv 2>/dev/null || true)}"
[[ -f "$UV_LOCK" ]] || { echo 'Hermes Relay uv.lock missing' >&2; exit 1; }
[[ -f "$PYPROJECT" ]] || { echo 'Hermes Relay pyproject.toml missing' >&2; exit 1; }
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || { echo 'uv is required to export Hermes Relay dependencies' >&2; exit 1; }
mkdir -p "$DEST_DIR"
RUNTIME="$DEST_DIR/requirements-hermes-relay.lock.txt"
PROV="$DEST_DIR/DEPENDENCY_LOCK_PROVENANCE.json"
META="$(mktemp)"
TMP="$(mktemp)"
trap 'rm -f "$META" "$TMP"' EXIT

python3 - "$PYPROJECT" "$UV_LOCK" "$META" <<'PY'
import json, pathlib, re, sys, tomllib
project_path, lock_path, out_path = map(pathlib.Path, sys.argv[1:])
project = tomllib.loads(project_path.read_text())
lock = tomllib.loads(lock_path.read_text())
name = str(project.get('project', {}).get('name', '')).strip()
version = str(project.get('project', {}).get('version', '')).strip()
if name != 'hermes-relay' or not version:
    raise SystemExit('invalid Hermes Relay project metadata')
def norm_req(text):
    text = str(text).strip()
    if '@' in text:
        raise SystemExit('direct URL dependency in project metadata')
    m = re.match(r'^([A-Za-z0-9_.-]+)\s*(.*)$', text)
    if not m:
        raise SystemExit('invalid project dependency: ' + text)
    canon = re.sub(r'[-_.]+', '-', m.group(1)).lower()
    return canon + re.sub(r'\s+', '', m.group(2))

project_deps = sorted(norm_req(x) for x in project['project'].get('dependencies', []))
roots = [p for p in lock.get('package', []) if p.get('name') == 'hermes-relay']
if len(roots) != 1:
    raise SystemExit('Hermes Relay root package missing or ambiguous in uv.lock')
root = roots[0]
locked = []
for item in root.get('metadata', {}).get('requires-dist', []):
    marker = str(item.get('marker', ''))
    if "extra ==" in marker:
        continue
    spec = str(item.get('specifier', ''))
    locked.append(norm_req(str(item.get('name', '')) + spec))
locked = sorted(locked)
if project_deps != locked:
    raise SystemExit('Hermes Relay dependency metadata mismatch between pyproject.toml and uv.lock')
meta = {
    'project_version': version,
    'lock_project_version': str(root.get('version', '')),
    'dependency_metadata_match': True,
    'root_version_mismatch': str(root.get('version', '')) != version,
}
out_path.write_text(json.dumps(meta, sort_keys=True) + '\n')
PY

(
  cd "$SOURCE_DIR"
  "$UV_BIN" export --frozen --format requirements-txt --no-dev \
    --no-emit-project --output-file "$TMP" >/dev/null
)
python3 - "$TMP" "$RUNTIME" <<'PY'
import pathlib, re, sys
src, out = map(pathlib.Path, sys.argv[1:])
text = src.read_text()
lines=[]
for line in text.splitlines():
    if line.startswith('#    uv export ') and ' --output-file ' in line:
        line = line.rsplit(' --output-file ', 1)[0] + ' --output-file <normalized>'
    lines.append(line)
text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')
if re.search(r'(?m)^\s*-e\s+', text) or re.search(r'(?i)(git\+|https?://)', text):
    raise SystemExit('frozen export contains editable or direct URL dependency')
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
    raise SystemExit('frozen export contains no requirements')
for block in blocks:
    if '--hash=sha256:' not in '\n'.join(block):
        raise SystemExit('frozen export contains unhashed requirement: ' + block[0].split()[0])
out.write_text(text)
PY
UV_VERSION="$($UV_BIN --version | head -1)"
python3 - "$UV_LOCK" "$RUNTIME" "$META" "$PROV" "$UV_VERSION" <<'PY'
import hashlib, json, pathlib, sys
lock, runtime, meta, prov = map(pathlib.Path, sys.argv[1:5]); uv_version=sys.argv[5]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
values=json.loads(meta.read_text())
values.update({
  'mode':'uv-export-frozen-validated-no-project',
  'uv_version':uv_version,
  'uv_lock_sha256':sha(lock),
  'runtime_requirements_sha256':sha(runtime),
})
prov.write_text(json.dumps(values, indent=2, sort_keys=True)+'\n')
PY
printf 'HERMES_RELAY_DEPENDENCY_LOCK_EXPORT=PASS\n'
