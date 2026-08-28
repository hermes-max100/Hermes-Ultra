#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EVALUATOR="$ROOT_DIR/src/system/anchor-evaluator.py"
REPORTS_DIR="${HERMES_ANCHOR_REPORTS_DIR:-$ROOT_DIR/.hermes/reports/anchor-evaluator}"

usage() {
  cat <<'EOF'
Hermes Anchor Evaluator v1

Usage:
  src/system/anchor-evaluator.sh run --suite anchors.json --incumbent-output incumbent.json --candidate-output candidate.json
  src/system/anchor-evaluator.sh status
  src/system/anchor-evaluator.sh help

The evaluator compares incumbent vs candidate against the same anchor suite,
emits local signed evidence artifacts, and cannot promote candidates.
EOF
}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift

case "$cmd" in
  run)
    python3 "$EVALUATOR" --reports-dir "$REPORTS_DIR" "$@"
    ;;
  status)
    printf 'reports_dir=%s\n' "$REPORTS_DIR"
    find "$REPORTS_DIR" -maxdepth 1 -name '*.md' -type f 2>/dev/null | sort | tail -5 | sed 's/^/report=/'
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
