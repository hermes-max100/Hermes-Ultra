#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/hermes-relay-doctor.sh"
[[ -x "$SCRIPT" ]] || { echo 'Hermes Relay doctor missing' >&2; exit 1; }
run_case(){
  local expected="$1" dashboard="$2" relay="$3" bind="$4" grant="$5"
  out="$(HERMES_RELAY_DOCTOR_DASHBOARD_JSON="$dashboard" HERMES_RELAY_DOCTOR_RELAY_JSON="$relay" HERMES_RELAY_DOCTOR_BIND_HOST="$bind" HERMES_RELAY_DOCTOR_GRANT_STATE="$grant" bash "$SCRIPT")"
  python3 - "$expected" "$out" <<'PY'
import json,sys
expected=sys.argv[1]; data=json.loads(sys.argv[2])
assert data['status']==expected,(expected,data)
assert data['compatibility']['server_pin']=='server-v1.10.0'
raw=json.dumps(data).lower()
for bad in ('secret-token-value','authorization: bearer','clipboard-secret','notification-secret'):
    assert bad not in raw,bad
PY
}
GOOD_D='{"ok":true,"version":"0.20.5"}'
GOOD_R='{"ok":true,"version":"1.10.0","protocol_schema":1,"clients":1,"sessions":1}'
run_case healthy "$GOOD_D" "$GOOD_R" 100.64.0.42 valid
run_case degraded "$GOOD_D" '{"ok":false,"version":"1.10.0","protocol_schema":1}' 100.64.0.42 valid
run_case stalled "$GOOD_D" '{"ok":true,"version":"1.10.0","protocol_schema":1,"stalled":true}' 100.64.0.42 valid
run_case incompatible "$GOOD_D" '{"ok":true,"version":"1.10.0","protocol_schema":2}' 100.64.0.42 valid
run_case incompatible "$GOOD_D" "$GOOD_R" 0.0.0.0 valid
run_case unauthorized "$GOOD_D" "$GOOD_R" 100.64.0.42 expired
SENSITIVE='{"ok":true,"version":"1.10.0","protocol_schema":1,"token":"secret-token-value","authorization":"Authorization: Bearer secret-token-value","clipboard":"clipboard-secret","notification_body":"notification-secret"}'
run_case healthy "$GOOD_D" "$SENSITIVE" 100.64.0.42 valid
printf 'Hermes Relay doctor tests passed\n'
