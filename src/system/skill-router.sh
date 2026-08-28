#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$ROOT_DIR/src/system"
SKILLS_HOME="${HERMES_SKILLS_HOME:-$ROOT_DIR/.skills}"
SKILLS_FILE="${SKILLS_FILE:-$SKILLS_HOME/skills.txt}"
SKILLS_DIR="${SKILLS_DIR:-$SKILLS_HOME/skills.d}"
PROJECTS_DIR="${PROJECTS_DIR:-$SKILLS_HOME/projects}"
LOG_FILE="${LOG_FILE:-$SKILLS_HOME/logs/skill-events.jsonl}"
TFIDF_SCRIPT="$SCRIPT_DIR/skill-tfidf.py"

err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Hermes Dynamic Skill Router

Usage:
  src/system/skill-router.sh init
  src/system/skill-router.sh find [--limit N] <query>
  src/system/skill-router.sh project <project> [--limit N] <query>
  src/system/skill-router.sh bundle <project> [--limit N] <query>
  src/system/skill-router.sh log <project> <skill> <outcome> <note>
  src/system/skill-router.sh show <skill>
  src/system/skill-router.sh scaffold <skill> <description>
  src/system/skill-router.sh explain <query>
  src/system/skill-router.sh compare <query>
EOF
}

normalize() {
  local s="$1"
  s="${s,,}"
  s="${s//[^a-z0-9._ -]/ }"
  printf '%s' "$s"
}

slug_valid() { [[ "$1" =~ ^[a-z0-9._-]+$ ]]; }

init_system() {
  mkdir -p "$SKILLS_HOME" "$SKILLS_DIR" "$PROJECTS_DIR" "$(dirname "$LOG_FILE")"
  [[ -f "$SKILLS_FILE" ]] || : > "$SKILLS_FILE"
  [[ -f "$SKILLS_HOME/EVOLUTION.md" ]] || printf '# Skill Evolution Policy\n\nObserve -> Propose -> Test -> Promote.\n' > "$SKILLS_HOME/EVOLUTION.md"
  printf 'Initialized skill system at: %s\n' "$SKILLS_HOME"
}

load_meta_value() {
  local meta_file="$1" key="$2"
  [[ -f "$meta_file" ]] || return 0
  (
    set +u
    # shellcheck disable=SC1090
    source "$meta_file"
    case "$key" in
      NAME) printf '%s' "${NAME:-}" ;;
      VERSION) printf '%s' "${VERSION:-}" ;;
      DESCRIPTION) printf '%s' "${DESCRIPTION:-}" ;;
      TAGS) printf '%s' "${TAGS:-}" ;;
      TRIGGERS) printf '%s' "${TRIGGERS:-}" ;;
      INPUTS) printf '%s' "${INPUTS:-}" ;;
      OUTPUTS) printf '%s' "${OUTPUTS:-}" ;;
      RISK_LEVEL) printf '%s' "${RISK_LEVEL:-}" ;;
    esac
  )
}

score_skill_deterministic() {
  local skill="$1" query="$2" project="${3:-}"
  local meta_file="$SKILLS_DIR/$skill/meta.env"
  local skill_file="$SKILLS_DIR/$skill/SKILL.md"
  local test_file="$SKILLS_DIR/$skill/tests.md"
  local q meta_text triggers outputs token score=0

  q="$(normalize "$query")"
  meta_text="$skill "
  meta_text+="$(load_meta_value "$meta_file" DESCRIPTION) "
  meta_text+="$(load_meta_value "$meta_file" TAGS) "
  meta_text+="$(load_meta_value "$meta_file" TRIGGERS) "
  meta_text+="$(load_meta_value "$meta_file" INPUTS) "
  meta_text+="$(load_meta_value "$meta_file" OUTPUTS) "
  [[ -f "$skill_file" ]] && meta_text+="$(cat "$skill_file") "
  [[ -f "$test_file" ]] && meta_text+="$(cat "$test_file") "

  if [[ -n "$project" && -f "$PROJECTS_DIR/$project/profile.md" ]]; then
    q+=" $(normalize "$(cat "$PROJECTS_DIR/$project/profile.md")")"
  fi

  meta_text="$(normalize "$meta_text")"
  triggers="$(normalize "$(load_meta_value "$meta_file" TRIGGERS)")"
  outputs="$(normalize "$(load_meta_value "$meta_file" OUTPUTS)")"

  [[ "$q" == *"$skill"* ]] && ((score += 100))

  for token in $q; do
    [[ ${#token} -lt 3 ]] && continue
    [[ "$meta_text" == *"$token"* ]] && ((score += 10))
    [[ "$triggers" == *"$token"* ]] && ((score += 15))
    [[ "$outputs" == *"$token"* ]] && ((score += 15))
  done

  if [[ -n "$project" && -f "$PROJECTS_DIR/$project/active-skills.txt" ]]; then
    grep -Fxq "$skill" "$PROJECTS_DIR/$project/active-skills.txt" && ((score += 25))
  fi

  printf '%d' "$score"
}

find_deterministic() {
  local query="$1" project="${2:-}" limit="${3:-5}"
  local skill score rows=()
  [[ -f "$SKILLS_FILE" ]] || { err "missing skills file: $SKILLS_FILE"; return 4; }

  while IFS= read -r skill || [[ -n "$skill" ]]; do
    [[ -n "$skill" ]] || continue
    slug_valid "$skill" || continue
    [[ -d "$SKILLS_DIR/$skill" ]] || continue
    score="$(score_skill_deterministic "$skill" "$query" "$project")"
    (( score > 0 )) && rows+=("$score $skill")
  done < "$SKILLS_FILE"

  [[ ${#rows[@]} -gt 0 ]] || { printf 'No matching skills found.\n'; return 1; }
  printf '%s\n' "${rows[@]}" | sort -rn | head -n "$limit" | awk '{print $2 " score=" $1}'
}

find_tfidf() {
  local query="$1" project="${2:-}" limit="${3:-5}"
  command -v python3 >/dev/null 2>&1 || return 127
  [[ -f "$TFIDF_SCRIPT" ]] || return 127
  local args=(python3 "$TFIDF_SCRIPT" --skills-home "$SKILLS_HOME" --query "$query" --limit "$limit")
  [[ -n "$project" ]] && args+=(--project "$project")
  "${args[@]}"
}

cmd_find() {
  local limit=5 query=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) query+=("$1"); shift ;;
    esac
  done
  [[ ${#query[@]} -gt 0 ]] || { err "find requires <query>"; return 2; }
  local q="${query[*]}"
  find_tfidf "$q" "" "$limit" 2>/dev/null || find_deterministic "$q" "" "$limit"
}

cmd_project() {
  [[ $# -ge 2 ]] || { err "project requires <project> <query>"; return 2; }
  local project="$1" limit=5 query=()
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) query+=("$1"); shift ;;
    esac
  done
  [[ ${#query[@]} -gt 0 ]] || { err "project requires <query>"; return 2; }
  mkdir -p "$PROJECTS_DIR/$project"
  local q="${query[*]}"
  find_tfidf "$q" "$project" "$limit" 2>/dev/null || find_deterministic "$q" "$project" "$limit"
}

selected_skills() {
  local project="$1" limit="$2" query="$3"
  if [[ -n "$project" ]]; then
    cmd_project "$project" --limit "$limit" "$query" | awk '{print $1}'
  else
    cmd_find --limit "$limit" "$query" | awk '{print $1}'
  fi
}

cmd_bundle() {
  [[ $# -ge 2 ]] || { err "bundle requires <project> <query>"; return 2; }
  local project="$1" limit=3 query=()
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) query+=("$1"); shift ;;
    esac
  done
  [[ ${#query[@]} -gt 0 ]] || { err "bundle requires <query>"; return 2; }
  local q="${query[*]}"
  local selected
  selected="$(selected_skills "$project" "$limit" "$q" || true)"

  printf '# Skill Context Bundle\n\n'
  printf '## Query\n\n%s\n\n' "$q"
  printf '## Project\n\n%s\n\n' "$project"
  if [[ -f "$PROJECTS_DIR/$project/profile.md" ]]; then
    printf '## Project Profile\n\n'
    cat "$PROJECTS_DIR/$project/profile.md"
    printf '\n\n'
  fi
  printf '## Selected Skills\n\n'
  [[ -n "$selected" ]] || { printf 'No skills matched.\n'; return 1; }
  local rank=1 skill
  while IFS= read -r skill; do
    [[ -n "$skill" ]] || continue
    printf '### %d. %s\n\n' "$rank" "$skill"
    if [[ -f "$SKILLS_DIR/$skill/meta.env" ]]; then
      printf '#### Metadata\n\n```env\n'
      cat "$SKILLS_DIR/$skill/meta.env"
      printf '\n```\n\n'
    fi
    if [[ -f "$SKILLS_DIR/$skill/SKILL.md" ]]; then
      printf '#### SKILL.md\n\n'
      cat "$SKILLS_DIR/$skill/SKILL.md"
      printf '\n\n'
    fi
    ((rank++))
  done <<< "$selected"

  printf '## Execution Instructions\n\n'
  printf '1. Select the smallest sufficient skill set from above.\n'
  printf '2. Explain why each skill was selected when producing a report.\n'
  printf '3. Execute the task using selected skills.\n'
  printf '4. Log whether the skill selection was sufficient.\n'
  printf '5. Propose versioned updates for weak skill behavior; do not silently mutate skills.\n'
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

cmd_log() {
  [[ $# -ge 4 ]] || { err "log requires <project> <skill> <outcome> <note>"; return 2; }
  local project="$1" skill="$2" outcome="$3"
  shift 3
  slug_valid "$skill" || { err "invalid skill slug: $skill"; return 2; }
  mkdir -p "$(dirname "$LOG_FILE")"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '{"ts":"%s","project":"%s","skill":"%s","outcome":"%s","note":"%s"}\n' \
    "$(json_escape "$ts")" "$(json_escape "$project")" "$(json_escape "$skill")" \
    "$(json_escape "$outcome")" "$(json_escape "$*")" >> "$LOG_FILE"
  printf 'Logged: %s / %s / %s\n' "$project" "$skill" "$outcome"
}

cmd_show() {
  [[ $# -eq 1 ]] || { err "show requires <skill>"; return 2; }
  local skill="$1"
  slug_valid "$skill" || { err "invalid skill slug: $skill"; return 2; }
  [[ -d "$SKILLS_DIR/$skill" ]] || { err "skill not found: $skill"; return 1; }
  printf 'Skill: %s\n' "$skill"
  [[ -f "$SKILLS_DIR/$skill/meta.env" ]] && { printf '\n--- meta.env ---\n'; cat "$SKILLS_DIR/$skill/meta.env"; }
  [[ -f "$SKILLS_DIR/$skill/SKILL.md" ]] && { printf '\n--- SKILL.md ---\n'; cat "$SKILLS_DIR/$skill/SKILL.md"; }
}

cmd_scaffold() {
  [[ $# -ge 2 ]] || { err "scaffold requires <skill> <description>"; return 2; }
  local skill="$1"
  shift
  slug_valid "$skill" || { err "invalid skill slug: $skill"; return 2; }
  init_system >/dev/null
  mkdir -p "$SKILLS_DIR/$skill"
  [[ -f "$SKILLS_DIR/$skill/meta.env" ]] || cat > "$SKILLS_DIR/$skill/meta.env" <<EOF
NAME="$skill"
VERSION="0.1.0"
DESCRIPTION="$*"
TAGS="$skill"
TRIGGERS="$skill"
INPUTS="task-description"
OUTPUTS="structured-response"
RISK_LEVEL="medium"
EOF
  [[ -f "$SKILLS_DIR/$skill/SKILL.md" ]] || printf '# %s\n\n%s\n' "$skill" "$*" > "$SKILLS_DIR/$skill/SKILL.md"
  [[ -f "$SKILLS_DIR/$skill/tests.md" ]] || printf '# %s Tests\n\n- Query: `%s`\n  - Expected: selected.\n' "$skill" "$*" > "$SKILLS_DIR/$skill/tests.md"
  [[ -f "$SKILLS_DIR/$skill/changelog.md" ]] || printf '# Changelog\n\n## 0.1.0\n\n- Initial scaffold.\n' > "$SKILLS_DIR/$skill/changelog.md"
  "$SCRIPT_DIR/skills.sh" add "$skill" >/dev/null
  printf 'scaffolded: %s\n' "$skill"
}

cmd_explain() {
  [[ $# -ge 1 ]] || { err "explain requires <query>"; return 2; }
  local query="$*"
  printf 'Query: %s\n\n' "$query"
  printf '%-36s %12s %12s\n' "SKILL" "DETERMINIST" "TFIDF"
  printf '%-36s %12s %12s\n' "------------------------------------" "------------" "------------"
  local tfidf_output skill det line tfidf_score
  tfidf_output="$(find_tfidf "$query" "" 999 2>/dev/null || true)"
  while IFS= read -r skill || [[ -n "$skill" ]]; do
    [[ -n "$skill" ]] || continue
    [[ -d "$SKILLS_DIR/$skill" ]] || continue
    det="$(score_skill_deterministic "$skill" "$query")"
    tfidf_score="n/a"
    if [[ -n "$tfidf_output" ]]; then
      line="$(printf '%s\n' "$tfidf_output" | grep "^${skill} " || true)"
      [[ -n "$line" ]] && tfidf_score="${line##*score=}"
    fi
    printf '%-36s %12s %12s\n' "$skill" "$det" "$tfidf_score"
  done < "$SKILLS_FILE"
}

cmd_compare() {
  [[ $# -ge 1 ]] || { err "compare requires <query>"; return 2; }
  local query="$*"
  printf '=== TF-IDF Results ===\n'
  find_tfidf "$query" "" 5 2>/dev/null || printf '(TF-IDF unavailable)\n'
  printf '\n=== Deterministic Results ===\n'
  find_deterministic "$query" "" 5
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    init) init_system "$@" ;;
    find) cmd_find "$@" ;;
    project) cmd_project "$@" ;;
    bundle) cmd_bundle "$@" ;;
    log) cmd_log "$@" ;;
    show) cmd_show "$@" ;;
    scaffold) cmd_scaffold "$@" ;;
    explain) cmd_explain "$@" ;;
    compare) cmd_compare "$@" ;;
    help|-h|--help) usage ;;
    *) err "unknown command: $command"; usage >&2; return 2 ;;
  esac
}

main "$@"
