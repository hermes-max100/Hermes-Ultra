#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'no arguments accepted' >&2; exit 2; }
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCA_INSTALLER="${ORCA_INSTALLER:-$ROOT_DIR/scripts/install-orca-runtime.sh}"
command -v tailscale >/dev/null 2>&1 || { echo 'tailscale command missing' >&2; exit 1; }
STATUS="$(tailscale status --json)"
python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("BackendState") == "Running" and d.get("Self",{}).get("Online") is True else 1)' <<<"$STATUS" \
  || { echo 'TAILSCALE_AUTH=FAIL' >&2; exit 1; }
echo 'TAILSCALE_AUTH=PASS'
TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -n1)"
[[ -n "$TAILSCALE_IP" ]] || { echo 'TAILSCALE_IP=FAIL' >&2; exit 1; }
if [[ "${HERMES_ORCA_DISABLE:-0}" != 1 ]]; then
  [[ -f "$ORCA_INSTALLER" ]] || { echo 'ORCA_INSTALLER=FAIL missing installer' >&2; exit 1; }
  ORCA_PAIRING_ADDRESS="$TAILSCALE_IP" bash "$ORCA_INSTALLER"
  echo 'ORCA_PRIVATE_RUNTIME=PASS'
fi
tailscale serve --bg --yes http://127.0.0.1:9119
echo 'TAILSCALE_SERVE=PASS target=http://127.0.0.1:9119'
