#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="$ROOT_DIR/src/system/failure-intelligence.py"

usage() {
  cat <<'EOF'
Hermes Failure Intelligence v1

Usage:
  src/system/failure-intelligence.sh scan [--limit N]
  src/system/failure-intelligence.sh clusters [--limit N]
  src/system/failure-intelligence.sh show <cluster-id>
  src/system/failure-intelligence.sh propose <cluster-id>

Reads governed Memory Fabric trajectories, clusters recurring failures, and
writes local proposal artifacts. It does not mutate skills, anchors, routing, or
runtime config.
EOF
}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift

case "$cmd" in
  scan|clusters|show|propose)
    python3 "$ENGINE" "$cmd" "$@"
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
