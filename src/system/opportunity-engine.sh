#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="$ROOT_DIR/src/system/opportunity-engine.py"

usage() {
  cat <<'EOF'
Hermes Opportunity Engine v1

Usage:
  src/system/opportunity-engine.sh init
  src/system/opportunity-engine.sh normalize --source-file findings.jsonl [--write-ledger]
  src/system/opportunity-engine.sh rank [--limit 10] [--include-expired]
  src/system/opportunity-engine.sh report [--limit 10] [--include-expired]

Purpose:
  Local-only opportunity normalization and ranking for Revenue OS. It converts
  public/source findings into evidence-backed opportunity records, validates
  source references, applies expiry/staleness handling, and calculates
  risk-adjusted expected value scores.

Boundary:
  No sending, posting, purchases, account changes, credential entry, permission
  changes, or platform actions. This engine only writes local queue/report
  artifacts and optional Revenue Ledger records.
EOF
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  *)
    python3 "$ENGINE" "$@"
    ;;
esac
