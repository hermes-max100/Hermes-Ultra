#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SWEEP="$ROOT_DIR/src/system/external-source-sweep.py"
CONFIG="${HERMES_EXTERNAL_SOURCES_CONFIG:-$ROOT_DIR/config/external-skill-sources.json}"
CACHE_DIR="${HERMES_EXTERNAL_CACHE_DIR:-$ROOT_DIR/.hermes/external-cache}"
REPORTS_DIR="${HERMES_REPORTS_DIR:-$ROOT_DIR/.hermes/reports}"
PROPOSALS_DIR="${HERMES_EXTERNAL_PROPOSALS_DIR:-$ROOT_DIR/.hermes/external-proposals}"

usage() {
  cat <<'EOF'
Hermes External Source Sweep

Usage:
  src/system/external-source-sweep.sh run [--offline] [--max-sources N]
  src/system/external-source-sweep.sh status

Commands:
  run     Clone/update configured external sources and create review artifacts.
  status  Show configured paths and latest reports.

The sweep never executes external repository code.
EOF
}

status() {
  echo "config=$CONFIG"
  echo "cache_dir=$CACHE_DIR"
  echo "reports_dir=$REPORTS_DIR"
  echo "proposals_dir=$PROPOSALS_DIR"
  echo "sources=$(CONFIG="$CONFIG" python3 - <<'PY'
import json
import os
from pathlib import Path
p=Path(os.environ["CONFIG"])
if p.is_file():
    print(len(json.loads(p.read_text()).get("sources", [])))
else:
    print("unavailable")
PY
)"
  find "$REPORTS_DIR" -maxdepth 1 -name 'external-source-sweep-*.md' -type f 2>/dev/null | sort | tail -3 | sed 's/^/report=/'
}

run_sweep() {
  python3 "$SWEEP" \
    --config "$CONFIG" \
    --cache-dir "$CACHE_DIR" \
    --reports-dir "$REPORTS_DIR" \
    --proposals-dir "$PROPOSALS_DIR" \
    "$@"
}

cmd="${1:-run}"
shift || true

case "$cmd" in
  run) run_sweep "$@" ;;
  status) status ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
