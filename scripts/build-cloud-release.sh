#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${HERMES_DIST_DIR:-$ROOT_DIR/dist}"
STAMP="${SOURCE_DATE_EPOCH:-$(date -u +%Y%m%dT%H%M%SZ)}"
NAME="hermes-max-cloud-${STAMP}.tar.gz"
OUT="$DIST_DIR/$NAME"
SHA="$OUT.sha256"

mkdir -p "$DIST_DIR"
bash "$ROOT_DIR/tests/test_production_versions.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/hermes-max"
mkdir -p "$STAGE"

# Cloud releases intentionally exclude local runtime state, credentials, Terraform state,
# prospect/customer data, generated dist artifacts, caches, Codex conversation history,
# and editor/VCS metadata.
tar -C "$ROOT_DIR" -cf - \
  --exclude='./.git' \
  --exclude='./.codex-project' \
  --exclude='./.superpowers' \
  --exclude='./.hermes' \
  --exclude='./.env*' \
  --exclude='./**/__pycache__' \
  --exclude='./dist' \
  --exclude='./prospects.jsonl' \
  --exclude='./exp_local_service_001-opportunity.json' \
  --exclude='./infra/**/.terraform' \
  --exclude='./infra/**/terraform.tfstate*' \
  --exclude='./infra/**/terraform.tfvars' \
  --exclude='./infra/**/*.auto.tfvars' \
  . | tar -C "$STAGE" -xf -

if [[ "${HERMES_PRODUCTION_BUILD:-0}" == "1" ]]; then
  [[ -n "${HERMES_AGENT_SOURCE_DIR:-}" ]] || { echo 'HERMES_AGENT_SOURCE_DIR is required for production builds' >&2; exit 1; }
  [[ -n "${HERMES_RELAY_SOURCE_DIR:-}" ]] || { echo 'HERMES_RELAY_SOURCE_DIR is required for production builds' >&2; exit 1; }
  [[ -n "${HERMES_RELAY_SERVER_WHEEL:-}" ]] || { echo 'HERMES_RELAY_SERVER_WHEEL is required for production builds' >&2; exit 1; }
  mkdir -p "$STAGE/vendor/hermes-agent" "$STAGE/vendor/hermes-relay"
  HERMES_EXPORT_DEPENDENCY_LOCKS=1 bash "$ROOT_DIR/scripts/stage-hermes-agent-source.sh" "$HERMES_AGENT_SOURCE_DIR" "$STAGE/vendor/hermes-agent/0.20.5"
  bash "$ROOT_DIR/scripts/stage-hermes-relay-source.sh" \
    "$HERMES_RELAY_SOURCE_DIR" \
    "$HERMES_RELAY_SERVER_WHEEL" \
    "$STAGE/vendor/hermes-relay/server-v1.10.0"
fi

chmod +x "$STAGE"/scripts/*.sh "$STAGE"/src/system/*.sh "$STAGE"/tests/*.sh
(
  cd "$STAGE"
  bash scripts/verify-cloud-foundation.sh
  bash tests/test_cloud_foundation.sh
  bash tests/test_load_hermes_runtime_env.sh
)

# Tests must not leak runtime state or generated Python bytecode into the release.
rm -rf "$STAGE/.hermes" "$STAGE/.skills/logs"
find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

# Fail closed before final archive creation if tracked source or staged content
# contains credential-like material. The scanner reports detector classes only.
bash "$ROOT_DIR/scripts/secret-scan-production.sh" --tracked-root "$ROOT_DIR"
bash "$ROOT_DIR/scripts/secret-scan-production.sh" "$STAGE"

bash "$ROOT_DIR/scripts/generate-release-provenance.sh" "$ROOT_DIR" "$STAGE/RELEASE_PROVENANCE.json" "$STAMP"
python3 - "$STAGE" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
prov = json.loads((root / 'RELEASE_PROVENANCE.json').read_text())
files = []
for path in sorted(p for p in root.rglob('*') if p.is_file()):
    rel = path.relative_to(root).as_posix()
    if rel in {'SBOM.spdx.json', 'CLOUD_RELEASE_MANIFEST.sha256'}:
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files.append({
        'SPDXID': 'SPDXRef-File-' + hashlib.sha256(rel.encode()).hexdigest()[:16],
        'fileName': './' + rel,
        'checksums': [{'algorithm': 'SHA256', 'checksumValue': digest}],
    })
sbom = {
    'spdxVersion': 'SPDX-2.3',
    'dataLicense': 'CC0-1.0',
    'SPDXID': 'SPDXRef-DOCUMENT',
    'name': 'hermes-max',
    'documentNamespace': 'https://hermes-max.local/spdx/' + prov['source_commit'],
    'creationInfo': {
        'created': prov['build_utc'],
        'creators': ['Tool: hermes-max-build-cloud-release'],
    },
    'packages': [{
        'name': 'hermes-max',
        'SPDXID': 'SPDXRef-Package-hermes-max',
        'versionInfo': prov['source_commit'],
        'downloadLocation': 'NOASSERTION',
        'filesAnalyzed': True,
    }],
    'files': files,
}
(root / 'SBOM.spdx.json').write_text(json.dumps(sbom, indent=2, sort_keys=True) + '\n')
PY
(
  cd "$STAGE"
  find . -type f ! -name CLOUD_RELEASE_MANIFEST.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > CLOUD_RELEASE_MANIFEST.sha256
  sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null
)

# Normalize permission metadata as well as order/time/ownership so the release
# archive is byte-for-byte reproducible across builders with different umasks.
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner \
  --mode='u+rwX,go+rX,go-w,a-s' \
  -C "$TMP" -czf "$OUT" hermes-max
sha256sum "$OUT" > "$SHA"
printf 'release=%s\nsha256_file=%s\n' "$OUT" "$SHA"
