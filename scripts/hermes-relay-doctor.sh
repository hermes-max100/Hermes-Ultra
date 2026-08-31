#!/usr/bin/env bash
set -euo pipefail
DASHBOARD_JSON="${HERMES_RELAY_DOCTOR_DASHBOARD_JSON:-}"
RELAY_JSON="${HERMES_RELAY_DOCTOR_RELAY_JSON:-}"
BIND_HOST="${HERMES_RELAY_DOCTOR_BIND_HOST:-}"
GRANT_STATE="${HERMES_RELAY_DOCTOR_GRANT_STATE:-not_applicable}"
if [[ -z "$BIND_HOST" ]]; then BIND_HOST="$(tailscale ip -4 2>/dev/null | head -1 || true)"; fi
python3 - "$DASHBOARD_JSON" "$RELAY_JSON" "$BIND_HOST" "$GRANT_STATE" <<'PY'
import ipaddress,json,os,sys,urllib.request
raw_dashboard,raw_relay,bind_host,grant_state=sys.argv[1:]
def fetch(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as response:
            return json.load(response)
    except Exception:
        return {'ok':False}
def parse_or_fetch(raw,url):
    if raw:
        try: value=json.loads(raw)
        except json.JSONDecodeError: return {'ok':False}
        return value if isinstance(value,dict) else {'ok':False}
    return fetch(url)
dashboard=parse_or_fetch(raw_dashboard,'http://127.0.0.1:9119/api/health')
relay=parse_or_fetch(raw_relay,f'http://{bind_host}:8767/health' if bind_host else 'http://127.0.0.1:8767/health')
try:
    addr=ipaddress.ip_address(bind_host)
    tailnet_only=addr.version==4 and addr in ipaddress.ip_network('100.64.0.0/10')
except ValueError:
    tailnet_only=False
relay_ok=relay.get('ok') is True or relay.get('status') in ('ok','healthy')
dash_ok=dashboard.get('ok') is True
relay_version=str(relay.get('version') or '')
protocol=relay.get('protocol_schema',relay.get('schema_version',1))
protocol_ok=protocol in (1,'1')
server_ok=relay_version in ('','1.10.0')
unauthorized=grant_state in ('missing','expired','revoked','denied')
stalled=relay.get('stalled') is True or relay.get('status')=='stalled'
if unauthorized: status='unauthorized'
elif not tailnet_only or not protocol_ok or not server_ok: status='incompatible'
elif stalled: status='stalled'
elif dash_ok and relay_ok: status='healthy'
else: status='degraded'
last=None
receipt_path=os.getenv('HERMES_RELAY_LAST_RECEIPT','').strip()
if receipt_path:
    try:
        r=json.load(open(receipt_path,encoding='utf-8'))
        allow=('task_id','target_device_id','channel','operation','request_id','authorization_id','terminal_status','result_digest','verification_source','content_hash')
        last={k:r[k] for k in allow if k in r}
    except Exception:
        last=None
out={
 'status':status,
 'dashboard':{'ok':dash_ok,'version':str(dashboard.get('version') or '')},
 'relay':{'ok':relay_ok,'version':relay_version,'clients':int(relay.get('clients') or 0),'sessions':int(relay.get('sessions') or 0)},
 'bind':{'host':bind_host,'port':8767,'tailnet_only':tailnet_only},
 'compatibility':{'server_pin':'server-v1.10.0','protocol_ok':protocol_ok,'protocol_schema':protocol},
 'grant_state':grant_state,
 'last_receipt':last,
}
print(json.dumps(out,sort_keys=True,separators=(',',':')))
PY
