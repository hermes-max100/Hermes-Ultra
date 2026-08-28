#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_HOME="${HERMES_SKILLS_HOME:-$ROOT_DIR/.skills}"
SKILLS_FILE="${SKILLS_FILE:-$SKILLS_HOME/skills.txt}"
SKILLS_DIR="${SKILLS_DIR:-$SKILLS_HOME/skills.d}"

err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Hermes Skill Registry

Usage:
  src/system/skills.sh init
  src/system/skills.sh add <skill>
  src/system/skills.sh remove <skill>
  src/system/skills.sh list
  src/system/skills.sh count
  src/system/skills.sh validate
  src/system/skills.sh help
EOF
}

slug_valid() {
  [[ "$1" =~ ^[a-z0-9._-]+$ ]]
}

init_system() {
  mkdir -p "$SKILLS_HOME" "$SKILLS_DIR" "$SKILLS_HOME/projects" "$SKILLS_HOME/logs"
  [[ -f "$SKILLS_FILE" ]] || : > "$SKILLS_FILE"
  printf 'Initialized skill registry at: %s\n' "$SKILLS_HOME"
}

cmd_add() {
  [[ $# -eq 1 ]] || { err "add requires <skill>"; return 2; }
  local skill="$1"
  slug_valid "$skill" || { err "invalid skill slug: $skill"; return 2; }
  init_system >/dev/null
  if ! grep -Fxq "$skill" "$SKILLS_FILE"; then
    printf '%s\n' "$skill" >> "$SKILLS_FILE"
    sort -u "$SKILLS_FILE" -o "$SKILLS_FILE"
  fi
  printf 'enabled: %s\n' "$skill"
}

cmd_remove() {
  [[ $# -eq 1 ]] || { err "remove requires <skill>"; return 2; }
  local skill="$1"
  slug_valid "$skill" || { err "invalid skill slug: $skill"; return 2; }
  [[ -f "$SKILLS_FILE" ]] || return 0
  grep -Fxv "$skill" "$SKILLS_FILE" > "$SKILLS_FILE.tmp" || true
  mv "$SKILLS_FILE.tmp" "$SKILLS_FILE"
  printf 'disabled: %s\n' "$skill"
}

cmd_list() {
  [[ -f "$SKILLS_FILE" ]] || return 0
  sed '/^[[:space:]]*$/d' "$SKILLS_FILE"
}

cmd_count() {
  [[ -f "$SKILLS_FILE" ]] || { echo 0; return 0; }
  sed '/^[[:space:]]*$/d' "$SKILLS_FILE" | wc -l | tr -d ' '
}

cmd_validate() {
  [[ -f "$SKILLS_FILE" ]] || { err "missing skills file: $SKILLS_FILE"; return 1; }
  local failed=0 skill
  while IFS= read -r skill || [[ -n "$skill" ]]; do
    [[ -n "$skill" ]] || continue
    if ! slug_valid "$skill"; then
      err "invalid slug: $skill"
      failed=1
      continue
    fi
    if [[ ! -d "$SKILLS_DIR/$skill" ]]; then
      err "missing skill directory: $skill"
      failed=1
      continue
    fi
    [[ -f "$SKILLS_DIR/$skill/meta.env" ]] || { err "missing meta.env: $skill"; failed=1; }
    [[ -f "$SKILLS_DIR/$skill/SKILL.md" ]] || { err "missing SKILL.md: $skill"; failed=1; }
  done < "$SKILLS_FILE"
  (( failed == 0 )) && printf 'skill registry valid: %s\n' "$SKILLS_HOME"
  return "$failed"
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    init) init_system "$@" ;;
    add) cmd_add "$@" ;;
    remove|rm|disable) cmd_remove "$@" ;;
    list|ls) cmd_list "$@" ;;
    count) cmd_count "$@" ;;
    validate) cmd_validate "$@" ;;
    help|-h|--help) usage ;;
    *) err "unknown command: $command"; usage >&2; return 2 ;;
  esac
}

main "$@"
