#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/stage-hermes-agent-source.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC="$TMP/source"; DEST="$TMP/staged"
mkdir -p "$SRC/hermes_cli" "$SRC/logs" "$SRC/__pycache__" "$SRC/venv/bin" "$SRC/tests" "$SRC/website/docs" "$SRC/.github/workflows" "$SRC/scripts"
cat > "$SRC/pyproject.toml" <<'PYPROJECT'
[project]
name = "hermes-agent"
version = "0.20.5"
PYPROJECT
printf '__version__ = "0.20.5"\n__release_date__ = "2026.8.18"\n' > "$SRC/hermes_cli/__init__.py"
printf '#!/usr/bin/env bash\necho setup\n' > "$SRC/setup-hermes.sh"
printf 'safe\n' > "$SRC/runtime.py"
printf 'secret\n' > "$SRC/auth.json"
printf 'log\n' > "$SRC/logs/runtime.log"
printf 'cache\n' > "$SRC/__pycache__/x.pyc"
printf 'venv\n' > "$SRC/venv/bin/python"
printf 'test-only\n' > "$SRC/tests/test_only.py"
printf 'website-only\n' > "$SRC/website/docs/readme.md"
printf 'ci-only\n' > "$SRC/.github/workflows/test.yml"
printf 'certification-only\n' > "$SRC/scripts/iso-certify.py"
cat > "$SRC/uv.lock" <<'LOCK'
version = 1
revision = 3
[[package]]
name = "setuptools"
version = "83.0.0"
sdist = { url = "https://example.invalid/setuptools.tar.gz", hash = "sha256:025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef", size = 1 }
wheels = [{ url = "https://example.invalid/setuptools.whl", hash = "sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3", size = 1 }]
LOCK
FAKE_UV="$TMP/uv"
cat > "$FAKE_UV" <<'UV'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == '--version' ]] && { echo 'uv 0.11.32 (test)'; exit 0; }
out=''; for ((i=1;i<=$#;i++)); do if [[ "${!i}" == '--output-file' ]]; then j=$((i+1)); out="${!j}"; fi; done
[[ -n "$out" ]]
printf 'demo==1.0 \\\n    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$out"
UV
chmod +x "$SRC/setup-hermes.sh" "$FAKE_UV"
git -C "$SRC" init -q
git -C "$SRC" config user.email test@example.invalid
git -C "$SRC" config user.name test
git -C "$SRC" add .
git -C "$SRC" commit -qm initial
git -C "$SRC" tag v2026.8.19
[[ -x "$SCRIPT" ]] || { echo 'stage script missing' >&2; exit 1; }
HERMES_EXPORT_DEPENDENCY_LOCKS=1 HERMES_UV_BIN="$FAKE_UV" bash "$SCRIPT" "$SRC" "$DEST"
[[ -f "$DEST/runtime.py" && -f "$DEST/setup-hermes.sh" ]] || { echo 'runtime files missing' >&2; exit 1; }
[[ ! -e "$DEST/.git" && ! -e "$DEST/venv" && ! -e "$DEST/auth.json" && ! -e "$DEST/logs" && ! -e "$DEST/__pycache__" && ! -e "$DEST/tests" && ! -e "$DEST/website" && ! -e "$DEST/.github" && ! -e "$DEST/scripts/iso-certify.py" ]] || { echo 'excluded source leaked' >&2; exit 1; }
[[ -f "$DEST/requirements-hermes-all.lock.txt" && -f "$DEST/requirements-hermes-build.lock.txt" && -f "$DEST/DEPENDENCY_LOCK_PROVENANCE.json" ]] || { echo 'dependency lock artifacts missing' >&2; exit 1; }
grep -q 'requirements-hermes-all.lock.txt' "$DEST/SOURCE_MANIFEST.sha256"
grep -q 'requirements-hermes-build.lock.txt' "$DEST/SOURCE_MANIFEST.sha256"
COMMIT="$(git -C "$SRC" rev-parse HEAD)"
grep -qx "$COMMIT" "$DEST/SOURCE_COMMIT"
python3 - "$DEST/SOURCE_PROVENANCE.json" "$COMMIT" <<'PY'
import json, pathlib, sys
p=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert p['source_commit']==sys.argv[2]
assert p['source_tag']=='v2026.8.19'
assert p['version']=='0.20.5'
assert len(p['tree_sha256'])==64
PY
DIST="$TMP/dist"; mkdir -p "$DIST"
HERMES_PRODUCTION_BUILD=1 HERMES_UV_BIN="$FAKE_UV" HERMES_AGENT_SOURCE_DIR="$SRC" HERMES_DIST_DIR="$DIST" SOURCE_DATE_EPOCH=20260821T000000Z bash "$ROOT_DIR/scripts/build-cloud-release.sh" >/dev/null
ARCHIVE="$(find "$DIST" -name 'hermes-max-cloud-*.tar.gz' -print -quit)"
tar -tzf "$ARCHIVE" | grep -q 'hermes-max/vendor/hermes-agent/0.20.5/DEPENDENCY_LOCK_PROVENANCE.json'
grep -q 'vendor/hermes-agent/0.20.5' "$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"
grep -q 'setup-hermes.sh' "$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"
! grep -q 'hermes update' "$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"
printf 'dirty\n' >> "$SRC/runtime.py"
if bash "$SCRIPT" "$SRC" "$TMP/dirty" >/dev/null 2>&1; then echo 'dirty source accepted' >&2; exit 1; fi
git -C "$SRC" reset --hard -q HEAD
sed -i 's/0.20.5/0.20.3/' "$SRC/pyproject.toml" "$SRC/hermes_cli/__init__.py"
git -C "$SRC" add . && git -C "$SRC" commit -qm mismatch
if bash "$SCRIPT" "$SRC" "$TMP/wrong-version" >/dev/null 2>&1; then echo 'wrong version accepted' >&2; exit 1; fi
echo 'Hermes source staging tests passed'
