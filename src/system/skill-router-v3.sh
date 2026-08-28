#!/usr/bin/env bash
set -euo pipefail

# v3 router: TF-IDF first-stage retrieval + local listwise reranking.
# Falls back to the stable dynamic skill router if Python or v3 components are unavailable.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SKILLS_HOME="${HERMES_SKILLS_HOME:-${SKILLS_HOME:-$ROOT_DIR/.skills}}"
RERANKER="${SCRIPT_DIR}/skill-reranker.py"
FALLBACK_ROUTER="${SCRIPT_DIR}/skill-router.sh"
DASHBOARD="${SCRIPT_DIR}/skill-dashboard.py"
SNAPSHOT="${SCRIPT_DIR}/score-snapshot.sh"

has_python() { command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; }
py_bin() { command -v python3 2>/dev/null || command -v python 2>/dev/null; }

usage() {
cat <<'USAGE'
Hermes Skill Router v3

Usage:
  src/system/skill-router-v3.sh find [--limit N] <query>
  src/system/skill-router-v3.sh project <project> [--limit N] <query>
  src/system/skill-router-v3.sh explain <query>
  src/system/skill-router-v3.sh snapshot [--rubric name]
  src/system/skill-router-v3.sh dashboard [--since YYYY-MM-DD] [--csv path]

Commands:
  find       Two-stage: TF-IDF retrieval -> listwise reranking
  project    Two-stage with project context
  explain    Show pointwise and listwise scoring breakdown
  snapshot   Record skill rubric score snapshots for drift tracking
  dashboard  Generate evolution dashboard report from skill-events.jsonl
USAGE
}

parse_limit_and_query() {
  LIMIT=5
  QUERY_PARTS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) LIMIT="$2"; shift 2 ;;
      *) QUERY_PARTS+=("$1"); shift ;;
    esac
  done
  QUERY="${QUERY_PARTS[*]}"
}

cmd_find() {
  parse_limit_and_query "$@"
  [[ -n "$QUERY" ]] || { echo "find requires <query>" >&2; return 2; }
  if has_python && [[ -f "$RERANKER" ]]; then
    "$(py_bin)" "$RERANKER" --skills-home "$SKILLS_HOME" --query "$QUERY" --limit "$LIMIT"
  else
    "$FALLBACK_ROUTER" find --limit "$LIMIT" "$QUERY"
  fi
}

cmd_project() {
  [[ $# -ge 2 ]] || { echo "project requires <project> <query>" >&2; return 2; }
  local project="$1"
  shift
  parse_limit_and_query "$@"
  [[ -n "$QUERY" ]] || { echo "project requires <query>" >&2; return 2; }
  if has_python && [[ -f "$RERANKER" ]]; then
    "$(py_bin)" "$RERANKER" --skills-home "$SKILLS_HOME" --query "$QUERY" --project "$project" --limit "$LIMIT"
  else
    "$FALLBACK_ROUTER" project "$project" --limit "$LIMIT" "$QUERY"
  fi
}

cmd_explain() {
  local query="$*"
  [[ -n "$query" ]] || { echo "explain requires <query>" >&2; return 2; }
  if has_python && [[ -f "$RERANKER" ]]; then
    "$(py_bin)" "$RERANKER" --skills-home "$SKILLS_HOME" --query "$query" --limit 10 --explain
  else
    "$FALLBACK_ROUTER" explain "$query"
  fi
}

cmd_dashboard() {
  local since="" csv=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="$2"; shift 2 ;;
      --csv) csv="$2"; shift 2 ;;
      *) echo "unknown dashboard flag: $1" >&2; return 2 ;;
    esac
  done
  if ! has_python || [[ ! -f "$DASHBOARD" ]]; then
    echo "dashboard requires python3 and $DASHBOARD" >&2
    return 1
  fi
  local args=("$(py_bin)" "$DASHBOARD" --skills-home "$SKILLS_HOME")
  [[ -n "$since" ]] && args+=(--since "$since")
  [[ -n "$csv" ]] && args+=(--csv "$csv")
  "${args[@]}"
}

cmd_snapshot() {
  [[ -x "$SNAPSHOT" ]] || { echo "snapshot recorder not executable: $SNAPSHOT" >&2; return 1; }
  "$SNAPSHOT" "$@"
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    find) cmd_find "$@" ;;
    project) cmd_project "$@" ;;
    explain) cmd_explain "$@" ;;
    snapshot) cmd_snapshot "$@" ;;
    dashboard) cmd_dashboard "$@" ;;
    help|-h|--help) usage ;;
    *) echo "Error: unknown command: $command" >&2; usage >&2; return 2 ;;
  esac
}

main "$@"
