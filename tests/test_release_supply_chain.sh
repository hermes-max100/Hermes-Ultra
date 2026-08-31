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
echo 'release supply chain tests passed'
