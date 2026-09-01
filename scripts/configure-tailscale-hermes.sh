#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'no arguments accepted' >&2; exit 2; }
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCA_INSTALLER="${ORCA_INSTALLER:-$ROOT_DIR/scripts/install-orca-runtime.sh}"
NGINX_CONF="${HERMES_NGINX_CONF_PATH:-/etc/nginx/conf.d/hermes-tailnet.conf}"
NGINX_DEFAULT_SITE="${HERMES_NGINX_DEFAULT_SITE:-/etc/nginx/sites-enabled/default}"
for cmd in tailscale nginx systemctl curl python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "$cmd command missing" >&2; exit 1; }
done
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
mkdir -p "$(dirname "$NGINX_CONF")"
rm -f "$NGINX_DEFAULT_SITE"
cat > "$NGINX_CONF" <<'NGINX'
server {
    listen 127.0.0.1:9120;
    listen [::1]:9120;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:9119;
        proxy_http_version 1.1;
        proxy_set_header Host 127.0.0.1:9119;
        proxy_set_header Origin http://127.0.0.1:9119;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $http_connection;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
NGINX
nginx -t
systemctl enable --now nginx.service
tailscale serve --tcp=9119 off
tailscale serve --bg --yes http://127.0.0.1:9120
curl -fsS -H 'Host: hermes-tailnet-proxy.invalid' http://127.0.0.1:9120/api/health \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("ok") is True else 1)'
echo 'TAILSCALE_SERVE=PASS target=http://127.0.0.1:9120'
