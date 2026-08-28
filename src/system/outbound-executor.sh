#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXECUTOR="$ROOT_DIR/src/system/outbound-executor.py"

usage() {
  cat <<'EOF'
Hermes Outbound Executor v1

Usage:
  src/system/outbound-executor.sh init
  src/system/outbound-executor.sh create-campaign-policy --experiment-id ID --offer OFFER [policy flags]
  src/system/outbound-executor.sh validate-handoff --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl
  src/system/outbound-executor.sh send --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl --transport smtp|sendmail

Purpose:
  Execute outbound Revenue OS campaign messages only after a bounded campaign
  policy, approval receipt, source evidence, channel constraints, duplicate
  prevention, and transport success are verified.

Boundary:
  No prospect discovery, no offer mutation, no purchases, no account changes,
  no credential entry, and no platform action outside the configured transport.
  The executor records `sent` only after SMTP/sendmail succeeds. Contact forms
  are handoff-only until a governed browser/contact-form executor exists.
EOF
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  *)
    python3 "$EXECUTOR" "$@"
    ;;
esac
