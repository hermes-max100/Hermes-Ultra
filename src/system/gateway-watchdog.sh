#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="${HERMES_GATEWAY_HEALTH_LOG:-$ROOT_DIR/.hermes/logs/gateway-health.jsonl}"
REQUIRED="${HERMES_REQUIRED_GATEWAYS:-9router}"
DRY_RUN=0
RESTART=1

usage() {
  cat <<'EOF'
Hermes Gateway Watchdog

Usage:
  src/system/gateway-watchdog.sh [--dry-run] [--no-restart] [--required 9router,omniroute]

Checks gateway status, restarts unhealthy installed gateways when allowed, and
writes JSONL health events to .hermes/logs/gateway-health.jsonl.
EOF
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

log_event() {
  local gateway="$1"
  local status="$2"
  local action="$3"
  local detail="$4"
  mkdir -p "$(dirname "$LOG_FILE")"
  printf '{"ts":"%s","gateway":"%s","status":"%s","action":"%s","detail":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(json_escape "$gateway")" \
    "$(json_escape "$status")" \
    "$(json_escape "$action")" \
    "$(json_escape "$detail")" >> "$LOG_FILE"
}

script_for() {
  case "$1" in
    9router) echo "$ROOT_DIR/src/system/ninerouter.sh" ;;
    omniroute) echo "$ROOT_DIR/src/system/omniroute.sh" ;;
    *) return 1 ;;
  esac
}

field_from_status() {
  local text="$1"
  local key="$2"
  printf '%s\n' "$text" | awk -F= -v k="$key" '$1 == k {print $2; exit}'
}

check_gateway() {
  local gateway="$1"
  local script
  script="$(script_for "$gateway")" || {
    echo "$gateway status=unknown action=unsupported"
    log_event "$gateway" "unknown" "unsupported" "no script for gateway"
    return 1
  }

  local status_text endpoint installed action detail
  status_text="$("$script" status 2>&1 || true)"
  endpoint="$(field_from_status "$status_text" models_endpoint_status)"
  installed="$(field_from_status "$status_text" installed)"
  action="none"
  detail="$endpoint"

  if [[ "$endpoint" == "http_200" ]]; then
    echo "$gateway status=healthy action=none"
    log_event "$gateway" "healthy" "$action" "$detail"
    return 0
  fi

  if [[ "$installed" != "yes" ]]; then
    echo "$gateway status=unhealthy action=not_installed endpoint=${endpoint:-unknown}"
    log_event "$gateway" "unhealthy" "not_installed" "${endpoint:-unknown}"
    return 1
  fi

  if [[ "$DRY_RUN" == "1" || "$RESTART" != "1" ]]; then
    echo "$gateway status=unhealthy action=restart_skipped endpoint=${endpoint:-unknown}"
    log_event "$gateway" "unhealthy" "restart_skipped" "${endpoint:-unknown}"
    return 1
  fi

  "$script" start-bg >/tmp/hermes-gateway-watchdog-start.out 2>&1 || true
  sleep 2
  status_text="$("$script" status 2>&1 || true)"
  endpoint="$(field_from_status "$status_text" models_endpoint_status)"
  if [[ "$endpoint" == "http_200" ]]; then
    action="restarted"
    echo "$gateway status=healthy action=$action"
    log_event "$gateway" "healthy" "$action" "$endpoint"
    return 0
  fi

  action="restart_failed"
  echo "$gateway status=unhealthy action=$action endpoint=${endpoint:-unknown}"
  log_event "$gateway" "unhealthy" "$action" "${endpoint:-unknown}"
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --no-restart) RESTART=0; shift ;;
    --required) REQUIRED="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
  esac
done

overall=0
IFS=',' read -r -a gateways <<< "$REQUIRED"
for gateway in "${gateways[@]}"; do
  gateway="${gateway//[[:space:]]/}"
  [[ -n "$gateway" ]] || continue
  if ! check_gateway "$gateway"; then
    overall=1
  fi
done

echo "log=$LOG_FILE"
exit "$overall"
