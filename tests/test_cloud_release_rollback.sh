#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/rollback-cloud-release.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
INSTALL="$TMP/install"
mkdir -p "$INSTALL/releases/release-a" "$INSTALL/releases/release-b" "$INSTALL/state"
printf 'A\n' > "$INSTALL/releases/release-a/VERSION"
printf 'B\n' > "$INSTALL/releases/release-b/VERSION"
for r in release-a release-b; do
  (cd "$INSTALL/releases/$r" && sha256sum VERSION > CLOUD_RELEASE_MANIFEST.sha256)
done
printf 'durable\n' > "$INSTALL/state/keep.txt"
touch -t 202608200100 "$INSTALL/releases/release-a"
touch -t 202608200200 "$INSTALL/releases/release-b"
ln -s "$INSTALL/releases/release-b" "$INSTALL/current"

[[ -x "$SCRIPT" ]] || { echo 'rollback script missing' >&2; exit 1; }
bash "$SCRIPT" --install-root "$INSTALL"
[[ "$(readlink -f "$INSTALL/current")" == "$INSTALL/releases/release-a" ]] || { echo 'default rollback did not select previous release' >&2; exit 1; }
[[ "$(cat "$INSTALL/state/keep.txt")" == durable ]] || { echo 'durable state changed' >&2; exit 1; }
if bash "$SCRIPT" --install-root "$INSTALL" --to does-not-exist >/dev/null 2>&1; then
  echo 'unknown release unexpectedly accepted' >&2
  exit 1
fi
printf 'tampered\n' >> "$INSTALL/releases/release-b/VERSION"
if bash "$SCRIPT" --install-root "$INSTALL" --to release-b >/dev/null 2>&1; then
  echo 'tampered release unexpectedly accepted' >&2
  exit 1
fi
[[ "$(readlink -f "$INSTALL/current")" == "$INSTALL/releases/release-a" ]] || { echo 'failed rollback changed current link' >&2; exit 1; }
echo 'cloud release rollback tests passed'
