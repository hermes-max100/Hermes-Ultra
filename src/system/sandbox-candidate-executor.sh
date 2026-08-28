#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXECUTOR="$ROOT_DIR/src/system/sandbox-candidate-executor.py"

usage() {
  cat <<'EOF'
Hermes Sandbox Candidate Executor v1

Usage:
  src/system/sandbox-candidate-executor.sh PACKAGE_DIR [options]

Options:
  --base-commit COMMIT             Pin sandbox to a specific Git commit
  --sandbox-dir DIR                Disposable worktree parent
  --result-dir DIR                 Immutable sandbox result parent
  --subsystem-test CMD             Run an affected-subsystem test command
  --governance-test CMD            Run a mandatory governance test command
  --command-timeout SECONDS        Per-command timeout
  --allow-governance-paths         Permit protected governance paths for an explicitly governed candidate
  --keep-worktree                  Do not remove the disposable worktree

The executor verifies the candidate package, runs only in a detached worktree,
strips credential-bearing environment variables, produces a patch/result bundle,
persists sandbox evidence to Memory Fabric, and hands the result package to
Trust Gate. It never commits, promotes, or edits the live checkout.
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
