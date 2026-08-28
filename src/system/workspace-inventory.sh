#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEARCH_ROOT="${1:-/root/Documents/Codex}"

usage() {
  cat <<'EOF'
Hermes Workspace Inventory

Usage:
  src/system/workspace-inventory.sh [search-root]

Scans local Codex workspaces for Hermes, OpenClaw, agent, skill, and SimpleLLMs
artifacts. It prints paths only and does not read or emit secrets.
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

echo "# Hermes Workspace Inventory"
echo "generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "search_root=$SEARCH_ROOT"
echo

echo "## Candidate Workspaces"
find "$SEARCH_ROOT" -maxdepth 6 -type d \
  \( -iname '*Hermes*' -o -iname '*OpenClaw*' -o -iname '*simplellms*' -o -iname '*agent*' -o -iname '*skills*' \) \
  2>/dev/null | sort | sed 's/^/- /'

echo
echo "## Key Files"
find "$SEARCH_ROOT" -maxdepth 7 -type f \
  \( -name 'README.md' -o -name 'AGENTS.md' -o -name 'cloud-model-catalog.json' -o -name 'dynamic-router.sh' -o -name 'hermes-run.sh' -o -name 'model.sh' -o -name 'skill-router-v3.sh' -o -name 'backup.sh' -o -name 'install.sh' \) \
  2>/dev/null | sort | sed 's/^/- /'

echo
echo "## Current Hermes Max Components"
find "$ROOT_DIR" -maxdepth 3 -type f \
  \( -path "$ROOT_DIR/src/system/*" -o -path "$ROOT_DIR/config/*" -o -path "$ROOT_DIR/docs/*" -o -path "$ROOT_DIR/tests/*" -o -path "$ROOT_DIR/packs/*" \) \
  2>/dev/null | sort | sed "s#^$ROOT_DIR/#- #"
