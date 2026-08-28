#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTROLLER="$ROOT_DIR/src/system/canary-controller.py"
STATE_DIR="${HERMES_CANARY_STATE_DIR:-$ROOT_DIR/.hermes/canary}"

usage() {
  cat <<'EOF'
Hermes Canary Controller v1

Usage:
  src/system/canary-controller.sh start --policy canary-policy.json
  src/system/canary-controller.sh record --promotion-id <id> --trajectory trajectory.json
  src/system/canary-controller.sh rollback --promotion-id <id> --reason "reason"
  src/system/canary-controller.sh status [--promotion-id <id>]

Promotion is reversible; evidence is not. Rollback is atomic and idempotent.
EOF
}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift

case "$cmd" in
  start|record|rollback|status)
    python3 "$CONTROLLER" --state-dir "$STATE_DIR" "$cmd" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
