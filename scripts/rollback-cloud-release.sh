#!/usr/bin/env bash
set -euo pipefail
usage(){ echo 'Usage: rollback-cloud-release.sh --install-root PATH [--to RELEASE_ID]' >&2; }
INSTALL_ROOT=''
TO=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root) INSTALL_ROOT="${2:-}"; shift 2 ;;
    --to) TO="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
[[ -n "$INSTALL_ROOT" ]] || { usage; exit 2; }
RELEASES="$INSTALL_ROOT/releases"
CURRENT="$INSTALL_ROOT/current"
[[ -d "$RELEASES" ]] || { echo 'releases directory missing' >&2; exit 1; }
CURRENT_REAL="$(readlink -f "$CURRENT" 2>/dev/null || true)"
CURRENT_ID="${CURRENT_REAL##*/}"
if [[ -n "$TO" ]]; then
  TARGET="$RELEASES/$TO"
else
  TARGET=''
  while IFS= read -r candidate; do
    [[ "$(basename "$candidate")" == "$CURRENT_ID" ]] && continue
    TARGET="$candidate"
    break
  done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
fi
[[ -n "$TARGET" && -d "$TARGET" ]] || { echo 'rollback target not found' >&2; exit 1; }
[[ -f "$TARGET/CLOUD_RELEASE_MANIFEST.sha256" ]] || { echo 'rollback manifest missing' >&2; exit 1; }
( cd "$TARGET" && sha256sum -c CLOUD_RELEASE_MANIFEST.sha256 >/dev/null ) || { echo 'rollback manifest verification failed' >&2; exit 1; }
TMP_LINK="$INSTALL_ROOT/.current.rollback.$$"
trap 'rm -f "$TMP_LINK"' EXIT
ln -s "$TARGET" "$TMP_LINK"
mv -Tf "$TMP_LINK" "$CURRENT"
trap - EXIT
printf 'ROLLBACK=PASS release=%s\n' "$(basename "$TARGET")"
