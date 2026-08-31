#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/config/hermes-relay-upstream.json"
if [[ "${1:-}" == "--manifest" ]]; then
  [[ $# -ge 2 ]] || { echo '--manifest requires a path' >&2; exit 2; }
  MANIFEST="$2"
  shift 2
fi
SOURCE_DIR="${1:?source directory required}"
WHEEL="${2:?server wheel required}"
DEST_DIR="${3:?destination directory required}"
[[ -f "$MANIFEST" ]] || { echo 'Hermes Relay provenance manifest missing' >&2; exit 1; }
[[ -d "$SOURCE_DIR/.git" || -f "$SOURCE_DIR/.git" ]] || { echo 'Hermes Relay source must be a git checkout' >&2; exit 1; }
[[ -z "$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=all)" ]] || { echo 'Hermes Relay source checkout is dirty' >&2; exit 1; }
mapfile -t EXPECT < <(python3 - "$MANIFEST" <<'PY'
import json, pathlib, re, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
if p.get('schema_version') != 1 or not isinstance(p.get('server'), dict):
    raise SystemExit('invalid Hermes Relay provenance manifest')
s=p['server']
for key in ('tag','version','commit','artifact','artifact_sha256'):
    value=str(s.get(key,'')).strip()
    if not value: raise SystemExit('missing server provenance field: '+key)
print(s['tag']); print(s['version']); print(s['commit']); print(s['artifact']); print(s['artifact_sha256'])
PY
)
EXPECTED_TAG="${EXPECT[0]}"
EXPECTED_VERSION="${EXPECT[1]}"
EXPECTED_COMMIT="${EXPECT[2]}"
EXPECTED_ARTIFACT="${EXPECT[3]}"
EXPECTED_WHEEL_SHA="${EXPECT[4]}"
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || { echo 'invalid Hermes Relay commit pin' >&2; exit 1; }
[[ "$EXPECTED_WHEEL_SHA" =~ ^[0-9a-fA-F]{64}$ ]] || { echo 'invalid Hermes Relay wheel digest pin' >&2; exit 1; }
[[ -f "$SOURCE_DIR/pyproject.toml" ]] || { echo 'Hermes Relay pyproject.toml missing' >&2; exit 1; }
[[ -f "$SOURCE_DIR/plugin/plugin.yaml" ]] || { echo 'Hermes Relay plugin manifest missing' >&2; exit 1; }
[[ -f "$SOURCE_DIR/uv.lock" ]] || { echo 'Hermes Relay uv.lock missing' >&2; exit 1; }
[[ -f "$SOURCE_DIR/LICENSE" ]] || { echo 'Hermes Relay LICENSE missing' >&2; exit 1; }
[[ -f "$WHEEL" ]] || { echo 'Hermes Relay server wheel missing' >&2; exit 1; }
[[ "$(basename "$WHEEL")" == "$EXPECTED_ARTIFACT" ]] || { echo 'Hermes Relay wheel filename mismatch' >&2; exit 1; }
VERSION="$(python3 - "$SOURCE_DIR/pyproject.toml" <<'PY'
import pathlib, sys, tomllib
print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())['project']['version'])
PY
)"
[[ "$VERSION" == "$EXPECTED_VERSION" ]] || { echo 'Hermes Relay source version mismatch' >&2; exit 1; }
python3 - "$SOURCE_DIR/plugin/plugin.yaml" "$EXPECTED_VERSION" <<'PY'
import pathlib, re, sys
text=pathlib.Path(sys.argv[1]).read_text()
version=sys.argv[2]
def value(name):
    m=re.search(rf'(?m)^{re.escape(name)}:\s*["\']?([^"\'\s#]+)', text)
    return m.group(1) if m else ''
if value('name') != 'hermes-relay': raise SystemExit('Hermes Relay plugin name mismatch')
if value('manifest_version') != '1': raise SystemExit('Hermes Relay plugin manifest version mismatch')
if value('version') != version: raise SystemExit('Hermes Relay plugin version mismatch')
PY
COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
[[ "$COMMIT" == "$EXPECTED_COMMIT" ]] || { echo 'Hermes Relay source commit mismatch' >&2; exit 1; }
git -C "$SOURCE_DIR" tag --points-at HEAD | grep -Fxq "$EXPECTED_TAG" || { echo 'Hermes Relay source tag mismatch' >&2; exit 1; }
ACTUAL_WHEEL_SHA="$(sha256sum "$WHEEL" | awk '{print $1}')"
[[ "$ACTUAL_WHEEL_SHA" == "$EXPECTED_WHEEL_SHA" ]] || { echo 'Hermes Relay server wheel digest mismatch' >&2; exit 1; }
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR/source"
python3 - "$SOURCE_DIR" "$DEST_DIR/source" <<'PY'
import pathlib, shutil, subprocess, sys
src=pathlib.Path(sys.argv[1]); dst=pathlib.Path(sys.argv[2])
allowed_exact={'pyproject.toml','uv.lock','LICENSE','hermes_relay_bootstrap.pth'}
allowed_prefixes=('plugin/','relay_server/','hermes_relay_bootstrap/')
blocked_parts={'.git','.github','tests','test','app','desktop','android','__pycache__','.cache','logs','sessions'}
blocked_names={'.env','auth.json'}
raw=subprocess.check_output(['git','-C',str(src),'ls-files','-z'])
for item in (x.decode() for x in raw.split(b'\0') if x):
    rel=pathlib.PurePosixPath(item)
    name=rel.as_posix()
    if name not in allowed_exact and not name.startswith(allowed_prefixes):
        continue
    if any(part in blocked_parts for part in rel.parts):
        continue
    if rel.name in blocked_names or rel.name.startswith('.env') or rel.name.endswith(('.log','.pyc')):
        continue
    source=src / pathlib.Path(*rel.parts)
    if not source.is_file():
        continue
    target=dst / pathlib.Path(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
PY
cp "$SOURCE_DIR/uv.lock" "$DEST_DIR/uv.lock"
cp "$SOURCE_DIR/LICENSE" "$DEST_DIR/LICENSE"
cp "$WHEEL" "$DEST_DIR/$EXPECTED_ARTIFACT"
bash "$ROOT_DIR/scripts/export-hermes-relay-dependency-lock.sh" "$SOURCE_DIR" "$DEST_DIR"
printf '%s\n' "$COMMIT" > "$DEST_DIR/SOURCE_COMMIT"
printf '%s\n' "$EXPECTED_TAG" > "$DEST_DIR/SOURCE_TAG"
(
  cd "$DEST_DIR"
  find . -type f ! -name SOURCE_MANIFEST.sha256 ! -name SOURCE_PROVENANCE.json -print0 \
    | sort -z | xargs -0 sha256sum > SOURCE_MANIFEST.sha256
  sha256sum -c SOURCE_MANIFEST.sha256 >/dev/null
)
TREE_SHA="$(sha256sum "$DEST_DIR/SOURCE_MANIFEST.sha256" | awk '{print $1}')"
python3 - "$DEST_DIR/SOURCE_PROVENANCE.json" "$COMMIT" "$EXPECTED_TAG" "$EXPECTED_VERSION" "$EXPECTED_ARTIFACT" "$ACTUAL_WHEEL_SHA" "$TREE_SHA" <<'PY'
import json, pathlib, sys
out, commit, tag, version, artifact, artifact_sha, tree = sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({
  'source_commit': commit,
  'source_tag': tag,
  'version': version,
  'artifact': artifact,
  'artifact_sha256': artifact_sha,
  'tree_sha256': tree,
}, indent=2, sort_keys=True) + '\n')
PY
printf 'HERMES_RELAY_SOURCE_STAGE=PASS version=%s commit=%s\n' "$EXPECTED_VERSION" "$COMMIT"
