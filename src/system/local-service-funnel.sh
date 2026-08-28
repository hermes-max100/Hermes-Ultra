#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FUNNEL="$ROOT_DIR/src/system/local-service-funnel.py"

usage() {
  cat <<'EOF'
Hermes Local Service Funnel v1

Usage:
  src/system/local-service-funnel.sh generate --experiment-id ID --prospects-file prospects.jsonl [--record-ledger]
  src/system/local-service-funnel.sh prepare-approved-handoff --experiment-id ID --handoff PATH --approval-id ID
  src/system/local-service-funnel.sh record-stage --experiment-id ID --prospect-id ID --business-name NAME --stage STAGE
  src/system/local-service-funnel.sh pilot-report --experiment-id ID [--prospects-file prospects.jsonl]

Purpose:
  Create the first concrete Revenue OS funnel for local service businesses:
  source-linked prospect qualification, tailored audit drafts, outreach drafts,
  approval-gated send handoff packets, premortem gate artifacts, and optional
  Revenue Ledger draft events. The pilot tracker is a thin reporting layer over
  Revenue Ledger stage events and generated funnel artifacts.

Boundary:
  Local artifacts only. No sending, posting, purchases, account changes,
  credential entry, permission changes, or platform actions. Even approved
  handoff packets keep allowed_to_send=false so a downstream connector must
  verify the approval receipt and enforce its own send boundary.
EOF
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  *)
    python3 "$FUNNEL" "$@"
    ;;
esac
