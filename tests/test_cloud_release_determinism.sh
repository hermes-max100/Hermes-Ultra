#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

build_with_umask() {
  local mask="$1" out="$2"
  mkdir -p "$out"
  (
    umask "$mask"
    HERMES_DIST_DIR="$out" SOURCE_DATE_EPOCH=20260815T010000Z \
      bash "$ROOT_DIR/scripts/build-cloud-release.sh" >/dev/null
  )
}

build_with_umask 022 "$TMP/u022"
build_with_umask 077 "$TMP/u077"

A="$TMP/u022/hermes-max-cloud-20260815T010000Z.tar.gz"
B="$TMP/u077/hermes-max-cloud-20260815T010000Z.tar.gz"
for archive in "$A" "$B"; do
  listing="$TMP/$(basename "$(dirname "$archive")").list"
  tar -tzf "$archive" > "$listing"
  if grep -Eq '(^|/)(__pycache__/|[^/]+\.py[co]$)' "$listing"; then
    echo 'generated Python cache leaked into cloud release' >&2
    exit 1
  fi
done
SHA_A="$(sha256sum "$A" | awk '{print $1}')"
SHA_B="$(sha256sum "$B" | awk '{print $1}')"
[[ "$SHA_A" == "$SHA_B" ]] || {
  echo "cloud release is umask-dependent: 022=$SHA_A 077=$SHA_B" >&2
  exit 1
}

MANIFEST_A="$(tar -xOf "$A" hermes-max/CLOUD_RELEASE_MANIFEST.sha256 | sha256sum | awk '{print $1}')"
MANIFEST_B="$(tar -xOf "$B" hermes-max/CLOUD_RELEASE_MANIFEST.sha256 | sha256sum | awk '{print $1}')"
[[ "$MANIFEST_A" == "$MANIFEST_B" ]] || { echo 'release content manifest changed across umasks' >&2; exit 1; }

CHECK="$TMP/check"
mkdir -p "$CHECK"
tar -xzf "$A" -C "$CHECK"
[[ "$(stat -c '%a' "$CHECK/hermes-max")" == 755 ]] || { echo 'release root mode is not 0755' >&2; exit 1; }
[[ "$(stat -c '%a' "$CHECK/hermes-max/scripts/build-cloud-release.sh")" == 755 ]] || { echo 'release script mode is not 0755' >&2; exit 1; }
[[ "$(stat -c '%a' "$CHECK/hermes-max/config/production-versions.json")" == 644 ]] || { echo 'ordinary release file mode is not 0644' >&2; exit 1; }

echo "cloud release determinism passed sha256=$SHA_A"
