#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LEDGER="$ROOT_DIR/src/system/revenue-ledger.py"

usage() {
  cat <<'EOF'
Hermes Revenue Ledger v1

Usage:
  src/system/revenue-ledger.sh init
  src/system/revenue-ledger.sh record-event --experiment-id ID --event-type lead [metrics...]
  src/system/revenue-ledger.sh record-opportunity --business-model ... --customer ... --problem ... --offer ... --channel ...
  src/system/revenue-ledger.sh summary [--group-by experiment_id|workflow_id|offer_id|channel|campaign]
  src/system/revenue-ledger.sh rank-opportunities [--limit 10]
  src/system/revenue-ledger.sh report

Purpose:
  Local-only attribution and opportunity ledger for Revenue OS. It records
  experiments, leads, conversions, revenue, refunds, costs, net profit, CAC,
  ROAS, and opportunity expected value.

Boundary:
  No sending, posting, purchases, account changes, credential entry, permission
  changes, or irreversible actions. Those remain human-approved workflows.
EOF
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  *)
    python3 "$LEDGER" "$@"
    ;;
esac
