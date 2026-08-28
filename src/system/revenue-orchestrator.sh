#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORCHESTRATOR="$ROOT_DIR/src/system/revenue-orchestrator.py"
APPROVAL_SECURITY="$ROOT_DIR/src/system/approval-security.py"

usage() {
  cat <<'EOF'
Hermes Revenue Orchestrator v1

Usage:
  src/system/revenue-orchestrator.sh init
  src/system/revenue-orchestrator.sh plan [filters...]
  src/system/revenue-orchestrator.sh list-plans
  src/system/revenue-orchestrator.sh show --experiment-id ID
  src/system/revenue-orchestrator.sh record-approval --approval-id ID --experiment-id ID --action send --scope SCOPE --action-id ACTION --principal PRINCIPAL --actor ACTOR --counterparty PARTY --destination DEST --amount N --approver NAME --policy-hash HASH --expires-at TS

Purpose:
  Select one eligible Revenue OS opportunity and create a bounded, immutable,
  local experiment plan with ledger attribution and approval-required actions
  separated from autonomous local work.

Boundary:
  No sending, posting, purchases, account changes, credential entry, permission
  changes, or platform actions. Approval-required steps must reference an
  authenticated approval receipt before an execution broker may externalize.

Approval security:
  record-approval requires HERMES_APPROVAL_HMAC_SECRET (minimum 32 bytes). Keep
  that secret in the trusted governance boundary; do not expose it to Scout or
  candidate/untrusted agent processes.
EOF
}

arg_value() {
  local wanted="$1"
  shift
  while (($#)); do
    if [[ "$1" == "$wanted" ]]; then
      [[ $# -ge 2 ]] || return 1
      printf '%s\n' "$2"
      return 0
    fi
    shift
  done
  return 1
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  record-approval)
    python3 "$APPROVAL_SECURITY" check-secret
    approval_id="$(arg_value --approval-id "$@")" || {
      echo "record-approval requires --approval-id" >&2
      exit 2
    }
    root="$(arg_value --root "$@" || true)"
    if [[ -z "$root" ]]; then
      root="${HERMES_REVENUE_OS_DIR:-.hermes/revenue-os}"
    fi
    output="$(python3 "$ORCHESTRATOR" "$@")"
    python3 "$APPROVAL_SECURITY" sign --root "$root" --approval-id "$approval_id" >/dev/null
    printf '%s\n' "$output"
    ;;
  *)
    python3 "$ORCHESTRATOR" "$@"
    ;;
esac
