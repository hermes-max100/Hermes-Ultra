#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE="$ROOT_DIR/src/system/candidate-generator.py"

usage() {
  cat <<'EOF'
Hermes Candidate Generator v1

Usage:
  src/system/candidate-generator.sh generate <cluster-id>

Creates a governed candidate package from a Failure Intelligence cluster. It
writes local manifests and regression specs only; it does not mutate code,
skills, anchors, routing, runtime config, or promotion state.
EOF
}

cmd="${1:-help}"
[[ $# -gt 0 ]] && shift

case "$cmd" in
  generate)
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
