#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${HERMES_MEMORY_DB:-$ROOT_DIR/.hermes/memory/memory-fabric.sqlite3}"

usage() {
  cat <<'EOF'
Hermes Memory Fabric v1

Usage:
  src/system/memory-fabric.sh init
  src/system/memory-fabric.sh status
  src/system/memory-fabric.sh add-node --type FACT --title ... --body ...
  src/system/memory-fabric.sh add-edge --src <node> --dst <node> --type DERIVED_FROM
  src/system/memory-fabric.sh record-trajectory --objective ... --status ...
  src/system/memory-fabric.sh ingest-trajectory --json-file trajectory.json
  src/system/memory-fabric.sh list-trajectories [--producer trust-gate]
  src/system/memory-fabric.sh retrieve <query> [--type FAILURE]

The memory fabric is append-first. Corrections supersede old records; retrieval
excludes deprecated, disputed, and untrusted evidence by default.
EOF
}

cmd="${1:-help}"
case "$cmd" in
  help|-h|--help)
    usage ;;
  *)
    python3 "$ROOT_DIR/src/system/memory-fabric.py" --db "$DB" "$@" ;;
esac
