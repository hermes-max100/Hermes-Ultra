#!/usr/bin/env bash
set -euo pipefail

CLI="${ORCA_CLI_COMMAND:-/opt/orca/bin/orca-ide}"
CLIENT_USER="${ORCA_CLIENT_USER:-hermes}"
CLIENT_HOME="${ORCA_CLIENT_HOME:-/var/lib/hermes}"
USER_DATA="${ORCA_USER_DATA_PATH:-$CLIENT_HOME/.config/hermes/orca-client/orca}"
ENVIRONMENT_NAME="${ORCA_ENVIRONMENT_NAME:-hermes-runtime}"
ORCA_SERVICE_NAME="${ORCA_SERVICE_NAME:-orca-serve.service}"
READY_LOG_FILE="${ORCA_READY_LOG_FILE:-}"
TEST_MODE="${HERMES_ORCA_TEST_MODE:-0}"

[[ -x "$CLI" ]] || { echo 'Hermes Orca CLI is missing or not executable' >&2; exit 1; }
[[ -n "$ENVIRONMENT_NAME" ]] || { echo 'ORCA_ENVIRONMENT_NAME is required' >&2; exit 2; }

if [[ "$TEST_MODE" == 1 ]]; then
  mkdir -p "$USER_DATA"
  chmod 0700 "$USER_DATA"
else
  [[ "$EUID" -eq 0 ]] || { echo 'Hermes Orca client bootstrap must run as root' >&2; exit 1; }
  id "$CLIENT_USER" >/dev/null 2>&1 || { echo 'Hermes client user is missing' >&2; exit 1; }
  CLIENT_GROUP="$(id -gn "$CLIENT_USER")"
  install -d -o "$CLIENT_USER" -g "$CLIENT_GROUP" -m 0700 \
    "$CLIENT_HOME/.config/hermes/orca-client" "$USER_DATA"
fi

run_cli() {
  if [[ "$TEST_MODE" == 1 ]]; then
    env HOME="$CLIENT_HOME" ORCA_USER_DATA_PATH="$USER_DATA" \
      DO_NOT_TRACK=1 ORCA_TELEMETRY_DISABLED=1 "$CLI" "$@"
  else
    runuser -u "$CLIENT_USER" -- env HOME="$CLIENT_HOME" ORCA_USER_DATA_PATH="$USER_DATA" \
      DO_NOT_TRACK=1 ORCA_TELEMETRY_DISABLED=1 "$CLI" "$@"
  fi
}

status_ready() {
  run_cli status --environment "$ENVIRONMENT_NAME" --json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result") or {}; rt=r.get("runtime") or {}; g=r.get("graph") or {}; raise SystemExit(0 if d.get("ok") is True and rt.get("state")=="ready" and rt.get("reachable") is True and g.get("state")=="ready" else 1)'
}

LIST="$(run_cli environment list --json 2>/dev/null)" || { echo 'Unable to read Hermes Orca environment store' >&2; exit 1; }
HAS_ENV="$(printf '%s' "$LIST" | python3 -c 'import json,sys; n=sys.argv[1]; d=json.load(sys.stdin); e=((d.get("result") or {}).get("environments") or []); print("1" if any(x.get("name")==n for x in e if isinstance(x,dict)) else "0")' "$ENVIRONMENT_NAME")"
if [[ "$HAS_ENV" == 1 ]]; then
  status_ready || { echo 'Existing Hermes Orca environment is not reachable; refusing automatic credential replacement' >&2; exit 1; }
  echo "HERMES_ORCA_CLIENT=PASS environment=$ENVIRONMENT_NAME state=existing"
  exit 0
fi

extract_pairing() {
  python3 -c '
import json,sys
value=""
for raw in sys.stdin:
    line=raw.strip()
    if line.startswith("Pairing URL: "):
        value=line.split(": ",1)[1].strip()
    try:
        obj=json.loads(line)
    except Exception:
        continue
    pairing=obj.get("pairing") if isinstance(obj,dict) else None
    if isinstance(pairing,dict) and isinstance(pairing.get("url"),str) and pairing.get("url"):
        value=pairing["url"]
print(value)
'
}

PAIRING=""
for _ in $(seq 1 30); do
  if [[ -n "$READY_LOG_FILE" ]]; then
    READY_TEXT="$(cat "$READY_LOG_FILE" 2>/dev/null || true)"
  else
    STARTED="$(systemctl show -p ActiveEnterTimestamp --value "$ORCA_SERVICE_NAME" 2>/dev/null || true)"
    if [[ -n "$STARTED" && "$STARTED" != n/a ]]; then
      READY_TEXT="$(journalctl -u "$ORCA_SERVICE_NAME" --since "$STARTED" -o cat --no-pager 2>/dev/null || true)"
    else
      READY_TEXT="$(journalctl -u "$ORCA_SERVICE_NAME" -n 300 -o cat --no-pager 2>/dev/null || true)"
    fi
  fi
  PAIRING="$(printf '%s\n' "$READY_TEXT" | extract_pairing)"
  [[ -n "$PAIRING" ]] && break
  [[ "$TEST_MODE" == 1 ]] && break
  sleep 1
done
[[ -n "$PAIRING" ]] || { echo 'Orca pairing capability was not available for Hermes client bootstrap' >&2; exit 1; }

if ! run_cli environment add --name "$ENVIRONMENT_NAME" --pairing-code "$PAIRING" --json >/dev/null 2>&1; then
  PAIRING=''
  echo 'Failed to create Hermes Orca client environment' >&2
  exit 1
fi
PAIRING=''

if ! status_ready; then
  run_cli environment rm --environment "$ENVIRONMENT_NAME" --json >/dev/null 2>&1 || true
  echo 'Hermes Orca client environment failed readiness verification' >&2
  exit 1
fi

echo "HERMES_ORCA_CLIENT=PASS environment=$ENVIRONMENT_NAME state=created"
