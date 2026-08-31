#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
grep -q 'HERMES_RELAY_SOURCE_DIR is required for production builds' "$ROOT_DIR/scripts/build-cloud-release.sh"
grep -q 'stage-hermes-relay-source.sh' "$ROOT_DIR/scripts/build-cloud-release.sh"
ERR="$TMP/missing-relay.err"
if HERMES_PRODUCTION_BUILD=1 HERMES_AGENT_SOURCE_DIR="$TMP/fake-agent" HERMES_DIST_DIR="$TMP/missing-dist" bash "$ROOT_DIR/scripts/build-cloud-release.sh" >/dev/null 2>"$ERR"; then
  echo 'production build accepted missing Relay inputs' >&2; exit 1
fi
grep -q 'HERMES_RELAY_SOURCE_DIR is required for production builds' "$ERR"
DIST="$TMP/dist"
mkdir -p "$DIST"
HERMES_DIST_DIR="$DIST" SOURCE_DATE_EPOCH=20260821T000000Z bash "$ROOT_DIR/scripts/build-cloud-release.sh" >/dev/null
ARCHIVE="$(find "$DIST" -maxdepth 1 -name 'hermes-max-cloud-*.tar.gz' -print -quit)"
[[ -n "$ARCHIVE" ]] || { echo 'missing release archive' >&2; exit 1; }
SHA_FILE="$ARCHIVE.sha256"
[[ -f "$SHA_FILE" ]] || { echo 'missing outer release checksum' >&2; exit 1; }
[[ "$(awk '{print $2}' "$SHA_FILE")" == "$(basename "$ARCHIVE")" ]] || { echo 'outer release checksum is not portable' >&2; exit 1; }
( cd "$DIST" && sha256sum -c "$(basename "$SHA_FILE")" >/dev/null )
tar -xzf "$ARCHIVE" -C "$TMP"
STAGE="$TMP/hermes-max"
for f in SBOM.spdx.json RELEASE_PROVENANCE.json CLOUD_RELEASE_MANIFEST.sha256; do
  [[ -f "$STAGE/$f" ]] || { echo "missing $f" >&2; exit 1; }
done
python3 - "$STAGE/SBOM.spdx.json" "$STAGE/RELEASE_PROVENANCE.json" <<'PY'
import json, pathlib, sys
sbom = json.loads(pathlib.Path(sys.argv[1]).read_text())
prov = json.loads(pathlib.Path(sys.argv[2]).read_text())
assert sbom.get('spdxVersion') == 'SPDX-2.3'
for key in ('source_commit','source_branch','build_utc','production_pins_sha256','builder_class','archive_format_version'):
    assert key in prov, key
assert prov['builder_class'] == 'local'
PY
find "$STAGE" -type f \( -name '.env*' -o -name 'terraform.tfstate*' -o -name 'prospects.jsonl' \) -print -quit | grep -q . && { echo 'sensitive file leaked' >&2; exit 1; } || true
[[ ! -e "$STAGE/.git" && ! -e "$STAGE/.hermes" ]] || { echo 'runtime/VCS state leaked' >&2; exit 1; }
( cd "$STAGE" && sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null )

# Build-time source checkouts are inputs, not a second runtime tree. A CI checkout
# such as vendor-src/hermes-agent must never be copied into the release archive;
# the production build stages the pinned source separately under vendor/hermes-agent.
FIXTURE_REPO="$TMP/source-fixture"
git clone -q --no-hardlinks "$ROOT_DIR" "$FIXTURE_REPO"
mkdir -p "$FIXTURE_REPO/vendor-src/hermes-agent"
printf 'OPENAI_API_KEY=sk-%040d\n' 0 > "$FIXTURE_REPO/vendor-src/hermes-agent/build-input-only.env"
FIXTURE_DIST="$TMP/fixture-dist"
mkdir -p "$FIXTURE_DIST"
HERMES_DIST_DIR="$FIXTURE_DIST" SOURCE_DATE_EPOCH=20260821T010000Z bash "$FIXTURE_REPO/scripts/build-cloud-release.sh" >/dev/null
FIXTURE_ARCHIVE="$(find "$FIXTURE_DIST" -maxdepth 1 -name 'hermes-max-cloud-*.tar.gz' -print -quit)"
[[ -n "$FIXTURE_ARCHIVE" ]] || { echo 'missing build-input exclusion fixture release' >&2; exit 1; }
FIXTURE_STAGE="$TMP/fixture-stage"
mkdir -p "$FIXTURE_STAGE"
tar -xzf "$FIXTURE_ARCHIVE" -C "$FIXTURE_STAGE"
[[ ! -e "$FIXTURE_STAGE/hermes-max/vendor-src" ]] || { echo 'build-source checkout leaked into release' >&2; exit 1; }

echo 'release supply chain tests passed'
