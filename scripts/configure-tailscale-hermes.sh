#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'no arguments accepted' >&2; exit 2; }
command -v tailscale >/dev/null 2>&1 || { echo 'tailscale command missing' >&2; exit 1; }
STATUS="$(tailscale status --json)"
python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("BackendState") == "Running" and d.get("Self",{}).get("Online") is True else 1)' <<<"$STATUS" \
  || { echo 'TAILSCALE_AUTH=FAIL' >&2; exit 1; }
echo 'TAILSCALE_AUTH=PASS'
tailscale serve --bg --yes http://127.0.0.1:9119
echo 'TAILSCALE_SERVE=PASS target=http://127.0.0.1:9119'
