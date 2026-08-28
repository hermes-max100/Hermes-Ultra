#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="${1:?source directory required}"
DEST_DIR="${2:?destination directory required}"
EXPECTED_VERSION='0.20.5'
EXPECTED_TAG='v2026.8.19'
[[ -d "$SOURCE_DIR/.git" || -f "$SOURCE_DIR/.git" ]] || { echo 'Hermes source must be a git checkout' >&2; exit 1; }
[[ -z "$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=all)" ]] || { echo 'Hermes source checkout is dirty' >&2; exit 1; }
VERSION="$(python3 - "$SOURCE_DIR/pyproject.toml" <<'PY'
import pathlib, sys, tomllib
print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())['project']['version'])
PY
)"
CLI_VERSION="$(python3 - "$SOURCE_DIR/hermes_cli/__init__.py" <<'PY'
import pathlib, re, sys
m=re.search(r'^__version__\s*=\s*["\']([^"\']+)', pathlib.Path(sys.argv[1]).read_text(), re.M)
print(m.group(1) if m else '')
PY
)"
[[ "$VERSION" == "$EXPECTED_VERSION" && "$CLI_VERSION" == "$EXPECTED_VERSION" ]] || { echo 'Hermes source version mismatch' >&2; exit 1; }
git -C "$SOURCE_DIR" tag --points-at HEAD | grep -Fxq "$EXPECTED_TAG" || { echo 'Hermes source tag mismatch' >&2; exit 1; }
COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
python3 - "$SOURCE_DIR" "$DEST_DIR" <<'PY'
import pathlib, shutil, subprocess, sys
src=pathlib.Path(sys.argv[1]); dst=pathlib.Path(sys.argv[2])
blocked_parts={'.git','venv','.venv','__pycache__','.cache','logs','sessions','tests','website','.github'}
blocked_names={'auth.json','.env'}
raw=subprocess.check_output(['git','-C',str(src),'ls-files','-z'])
for item in (x.decode() for x in raw.split(b'\0') if x):
    rel=pathlib.PurePosixPath(item)
    if any(part in blocked_parts for part in rel.parts):
        continue
    if rel.name in blocked_names or rel.name.endswith(('.log','.pyc')) or rel.name.startswith('request_dump_'):
        continue
    if rel.as_posix() == 'scripts/iso-certify.py':
        continue
    source=src / pathlib.Path(*rel.parts)
    target=dst / pathlib.Path(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
PY
if [[ "${HERMES_EXPORT_DEPENDENCY_LOCKS:-0}" == "1" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  bash "$ROOT_DIR/scripts/export-hermes-dependency-locks.sh" "$SOURCE_DIR" "$DEST_DIR"
fi
printf '%s\n' "$COMMIT" > "$DEST_DIR/SOURCE_COMMIT"
printf '%s\n' "$EXPECTED_TAG" > "$DEST_DIR/SOURCE_TAG"
(
  cd "$DEST_DIR"
  find . -type f ! -name SOURCE_MANIFEST.sha256 ! -name SOURCE_PROVENANCE.json -print0 | sort -z | xargs -0 sha256sum > SOURCE_MANIFEST.sha256
  sha256sum -c SOURCE_MANIFEST.sha256 >/dev/null
)
TREE_SHA="$(sha256sum "$DEST_DIR/SOURCE_MANIFEST.sha256" | awk '{print $1}')"
python3 - "$DEST_DIR/SOURCE_PROVENANCE.json" "$COMMIT" "$EXPECTED_TAG" "$EXPECTED_VERSION" "$TREE_SHA" <<'PY'
import json, pathlib, sys
out, commit, tag, version, tree = sys.argv[1:]
pathlib.Path(out).write_text(json.dumps({
  'source_commit': commit,
  'source_tag': tag,
  'version': version,
  'tree_sha256': tree,
}, indent=2, sort_keys=True) + '\n')
PY
printf 'HERMES_SOURCE_STAGE=PASS version=%s commit=%s\n' "$EXPECTED_VERSION" "$COMMIT"
