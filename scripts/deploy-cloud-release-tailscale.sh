#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: deploy-cloud-release-tailscale.sh TARGET_HOST RELEASE.tar.gz [TARGET_USER]' >&2
}

TARGET_HOST="${1:-}"
ARCHIVE="${2:-}"
TARGET_USER="${3:-ubuntu}"
[[ -n "$TARGET_HOST" && -n "$ARCHIVE" ]] || { usage; exit 2; }
[[ "$TARGET_HOST" =~ ^[A-Za-z0-9._:-]+$ ]] || { echo 'invalid target host' >&2; exit 2; }
[[ "$TARGET_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo 'invalid target user' >&2; exit 2; }
[[ -f "$ARCHIVE" ]] || { echo 'release archive not found' >&2; exit 2; }
[[ -f "$ARCHIVE.sha256" ]] || { echo 'release checksum sidecar not found' >&2; exit 2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/scripts/install-cloud-release-local.sh"
[[ -x "$INSTALLER" ]] || { echo 'transactional installer missing' >&2; exit 1; }
for command_name in tailscale ssh scp sha256sum python3; do
  command -v "$command_name" >/dev/null 2>&1 \
    || { echo "required command missing: $command_name" >&2; exit 1; }
done

tailscale status --json | python3 -c '
import json, sys
state = json.load(sys.stdin)
raise SystemExit(0 if state.get("BackendState") == "Running" and state.get("Self", {}).get("Online") is True else 1)
' || { echo 'TAILSCALE_AUTH=FAIL' >&2; exit 1; }
echo 'TAILSCALE_AUTH=PASS'
tailscale ping "$TARGET_HOST"
echo "TAILSCALE_TARGET=PASS host=$TARGET_HOST"

ARCHIVE_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"
ARCHIVE_NAME="$(basename "$ARCHIVE")"
( cd "$ARCHIVE_DIR" && sha256sum -c "$ARCHIVE_NAME.sha256" )
EXPECTED_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo 'invalid release checksum' >&2; exit 1; }

REMOTE_ROOT="/tmp/hermes-deploy-${EXPECTED_SHA:0:16}"
REMOTE_ARCHIVE="$REMOTE_ROOT/hermes-release.tar.gz"
REMOTE_INSTALLER="$REMOTE_ROOT/install-cloud-release-local.sh"
SSH_TARGET="$TARGET_USER@$TARGET_HOST"
SSH_OPTIONS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
REMOTE_CREATED=0
cleanup() {
  if [[ "$REMOTE_CREATED" == 1 ]]; then
    ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "rm -rf '$REMOTE_ROOT'" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "install -d -m 0700 '$REMOTE_ROOT'"
REMOTE_CREATED=1
scp "${SSH_OPTIONS[@]}" "$ARCHIVE" "$SSH_TARGET:$REMOTE_ARCHIVE"
scp "${SSH_OPTIONS[@]}" "$INSTALLER" "$SSH_TARGET:$REMOTE_INSTALLER"

ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
  "echo '$EXPECTED_SHA  $REMOTE_ARCHIVE' | sha256sum -c - && sudo bash '$REMOTE_INSTALLER' '$REMOTE_ARCHIVE' '$EXPECTED_SHA'"

ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:9119/api/health', timeout=5) as response:
    body = json.load(response)
if body.get('ok') is not True or body.get('version') != '0.21.0':
    raise SystemExit('Hermes health verification failed')
PY
systemctl is-active --quiet hermes-runtime.service
systemctl is-active --quiet hermes-relay.service
tailscale serve status >/dev/null
"

echo "HERMES_TAILSCALE_DEPLOY=PASS host=$TARGET_HOST release=${EXPECTED_SHA:0:16}"
