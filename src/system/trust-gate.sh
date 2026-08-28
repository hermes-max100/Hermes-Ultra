#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$ROOT_DIR/src/system/trust-gate.py"
REPORTS_DIR="${HERMES_TRUST_GATE_REPORTS_DIR:-$ROOT_DIR/.hermes/reports/trust-gate}"
CACHE_DIR="${HERMES_TRUST_GATE_CACHE_DIR:-$ROOT_DIR/.hermes/trust-gate-cache}"

usage() {
  cat <<'EOF'
Hermes Trust Gate

Usage:
  src/system/trust-gate.sh scan <path-or-git-url> [--type skill|mcp|package|model|capability] [--state candidate|quarantined|trusted|installed|active]
  src/system/trust-gate.sh status

The gate is read-only. It never executes candidate code. Reports are written
under .hermes/reports/trust-gate.

Optional:
  HERMES_TRUST_GATE_SECRET=... signs evidence artifacts with HMAC-SHA256.
EOF
}

status() {
  printf 'reports_dir=%s\n' "$REPORTS_DIR"
  printf 'cache_dir=%s\n' "$CACHE_DIR"
  printf 'secret_status=%s\n' "$([[ -n "${HERMES_TRUST_GATE_SECRET:-}" ]] && echo loaded || echo not_loaded)"
  find "$REPORTS_DIR" -maxdepth 1 -name '*.md' -type f 2>/dev/null | sort | tail -5 | sed 's/^/report=/'
}

cmd="${1:-help}"
shift || true
case "$cmd" in
  scan)
    [[ $# -ge 1 ]] || { echo "scan requires <path-or-git-url>" >&2; exit 2; }
    python3 "$GATE" "$@" --reports-dir "$REPORTS_DIR" --cache-dir "$CACHE_DIR" ;;
  status)
    status ;;
  help|-h|--help)
    usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2 ;;
esac
