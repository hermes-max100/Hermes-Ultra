#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_HOME="${HERMES_SKILLS_HOME:-$ROOT_DIR/.skills}"
SKILLS_DIR="${SKILLS_DIR:-$SKILLS_HOME/skills.d}"
LOG_FILE="${LOG_FILE:-$SKILLS_HOME/logs/skill-events.jsonl}"
PROPOSALS_DIR="${PROPOSALS_DIR:-$SKILLS_HOME/proposals}"
BACKUPS_DIR="${BACKUPS_DIR:-$SKILLS_HOME/backups}"
MEMORY_FABRIC="${HERMES_MEMORY_FABRIC:-$ROOT_DIR/src/system/memory-fabric.sh}"

err() { printf '%s\n' "$*" >&2; }

record_memory_trajectory() {
  [[ -x "$MEMORY_FABRIC" ]] || return 0
  "$MEMORY_FABRIC" record-trajectory "$@" >/dev/null 2>&1 || true
}

record_memory_trajectory_required() {
  [[ -x "$MEMORY_FABRIC" ]] || { err "memory fabric unavailable; refusing validated/promotion claim"; return 1; }
  "$MEMORY_FABRIC" record-trajectory "$@" >/dev/null
}

usage() {
  cat <<'EOF'
Hermes Skill Evolver

Usage:
  src/system/skill-evolver.sh status
  src/system/skill-evolver.sh scan [project]
  src/system/skill-evolver.sh propose [project]
  src/system/skill-evolver.sh list-proposals
  src/system/skill-evolver.sh show-proposal <proposal-id>
  src/system/skill-evolver.sh validate-proposal <proposal-id>
  src/system/skill-evolver.sh promote <proposal-id>
  src/system/skill-evolver.sh reject <proposal-id>

The evolver never silently mutates skills. It creates reviewable proposals.
EOF
}

slug_valid() { [[ "$1" =~ ^[a-z0-9._-]+$ ]]; }

load_env() {
  local file="$1"
  [[ -f "$file" ]] || { err "missing file: $file"; return 1; }
  # shellcheck disable=SC1090
  source "$file"
}

status() {
  mkdir -p "$PROPOSALS_DIR" "$BACKUPS_DIR" "$(dirname "$LOG_FILE")"
  printf 'skills_home=%s\n' "$SKILLS_HOME"
  printf 'log_file=%s\n' "$LOG_FILE"
  printf 'proposals_dir=%s\n' "$PROPOSALS_DIR"
  printf 'pending_proposals=%s\n' "$(find "$PROPOSALS_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
}

scan_failures() {
  local project="${1:-}"
  [[ -f "$LOG_FILE" ]] || { printf 'No skill events logged.\n'; return 0; }
  python3 - "$LOG_FILE" "$project" <<'PY'
import json
import sys
from collections import Counter

path, project = sys.argv[1], sys.argv[2]
counts = Counter()
notes = {}
for line in open(path, encoding="utf-8", errors="replace"):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if project and event.get("project") != project:
        continue
    if event.get("outcome") not in {"failure", "partial", "blocked"}:
        continue
    skill = event.get("skill", "")
    if not skill:
        continue
    counts[skill] += 1
    notes.setdefault(skill, []).append(event.get("note", ""))

if not counts:
    print("No repeated failure signals found.")
else:
    for skill, count in counts.most_common():
        sample = "; ".join(notes.get(skill, [])[-3:])
        print(f"{skill} failures={count} notes={sample}")
PY
}

proposal_id() {
  local project="$1" skill="$2"
  printf '%s-%s-%s' "$(date -u +%Y%m%dT%H%M%SZ)" "$project" "$skill" | tr -cs 'a-zA-Z0-9._-' '-'
}

extract_terms() {
  local note="$1"
  NOTE="$note" python3 <<'PY'
import os
import re

stop = {
    "this", "that", "with", "from", "have", "missed", "issue", "terms", "trigger",
    "selected", "failure", "partial", "blocked", "task", "add", "and", "the", "for",
}
words = []
for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]+", os.environ.get("NOTE", "").lower()):
    if len(token) >= 4 and token not in stop and token not in words:
        words.append(token)
print(" ".join(words[:12]))
PY
}

propose() {
  local project="${1:-default}"
  [[ -f "$LOG_FILE" ]] || { err "no events to evolve: $LOG_FILE"; return 1; }
  mkdir -p "$PROPOSALS_DIR"

  local proposal_count=0
  while IFS=$'\t' read -r skill note count; do
    [[ -n "$skill" ]] || continue
    slug_valid "$skill" || continue
    [[ -d "$SKILLS_DIR/$skill" ]] || continue
    local terms id dir
    terms="$(extract_terms "$note")"
    [[ -n "$terms" ]] || continue
    id="$(proposal_id "$project" "$skill")"
    dir="$PROPOSALS_DIR/$id"
    mkdir -p "$dir"
    cat > "$dir/proposal.env" <<EOF
PROPOSAL_ID="$id"
PROJECT="$project"
SKILL="$skill"
OUTCOME_COUNT="$count"
ADD_TRIGGER_TERMS="$terms"
STATUS="pending"
REASON="Failure/partial/blocked notes suggested missing routing terms."
EOF
    cat > "$dir/README.md" <<EOF
# Skill Evolution Proposal: $id

Project: $project
Skill: $skill
Failure count: $count

Suggested trigger terms:

\`\`\`
$terms
\`\`\`

Review with:

\`\`\`bash
src/system/skill-evolver.sh show-proposal $id
src/system/skill-evolver.sh promote $id
\`\`\`
EOF
    record_memory_trajectory \
      --objective "skill-evolution" \
      --status "proposed" \
      --skill "$skill" \
      --proposal-id "$id" \
      --input "$note" \
      --prediction "Adding trigger terms may improve routing for repeated weak outcomes." \
      --observed "proposal created with trigger terms: $terms" \
      --delta "pending validation" \
      --agent "skill-evolver" \
      --evidence-refs "[\"$dir/proposal.env\",\"$dir/README.md\"]" \
      --confidence 0.7 \
      --security-classification "internal"
    printf 'proposal created: %s\n' "$id"
    ((proposal_count += 1))
  done < <(python3 - "$LOG_FILE" "$project" <<'PY'
import json
import sys
from collections import defaultdict

path, project = sys.argv[1], sys.argv[2]
events = defaultdict(list)
for line in open(path, encoding="utf-8", errors="replace"):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if project != "default" and event.get("project") != project:
        continue
    if event.get("outcome") in {"failure", "partial", "blocked"}:
        events[event.get("skill", "")].append(event.get("note", ""))
for skill, notes in sorted(events.items()):
    if skill:
        print(f"{skill}\t{' ; '.join(notes[-5:])}\t{len(notes)}")
PY
  )

  (( proposal_count > 0 )) || { printf 'No proposal-worthy failure signals found.\n'; return 1; }
}

list_proposals() {
  mkdir -p "$PROPOSALS_DIR"
  local proposal
  for proposal in "$PROPOSALS_DIR"/*; do
    [[ -d "$proposal" ]] || continue
    basename "$proposal"
  done
}

show_proposal() {
  [[ $# -eq 1 ]] || { err "show-proposal requires <proposal-id>"; return 2; }
  local id="$1"
  local dir="$PROPOSALS_DIR/$id"
  [[ -d "$dir" ]] || { err "proposal not found: $id"; return 1; }
  [[ -f "$dir/README.md" ]] && cat "$dir/README.md"
  [[ -f "$dir/proposal.env" ]] && { printf '\n--- proposal.env ---\n'; cat "$dir/proposal.env"; }
}

bump_patch_version() {
  local version="$1"
  IFS=. read -r major minor patch <<< "$version"
  major="${major:-0}"
  minor="${minor:-1}"
  patch="${patch:-0}"
  patch=$((patch + 1))
  printf '%s.%s.%s' "$major" "$minor" "$patch"
}

apply_trigger_terms() {
  local meta="$1"
  local terms="$2"
  python3 - "$meta" "$terms" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
terms = sys.argv[2].split()
text = path.read_text(encoding="utf-8")

version_match = re.search(r'^VERSION="([^"]+)"', text, re.M)
version = version_match.group(1) if version_match else "0.1.0"
parts = version.split(".")
while len(parts) < 3:
    parts.append("0")
parts[2] = str(int(parts[2]) + 1)
new_version = ".".join(parts[:3])
text = re.sub(r'^VERSION="[^"]+"', f'VERSION="{new_version}"', text, flags=re.M)

trigger_match = re.search(r'^TRIGGERS="([^"]*)"', text, re.M)
if trigger_match:
    existing = trigger_match.group(1).split()
    for term in terms:
        if term not in existing:
            existing.append(term)
    text = re.sub(r'^TRIGGERS="[^"]*"', f'TRIGGERS="{" ".join(existing)}"', text, flags=re.M)
else:
    text += f'\nTRIGGERS="{" ".join(terms)}"\n'

path.write_text(text, encoding="utf-8")
print(new_version)
PY
}

validate_proposal() {
  [[ $# -eq 1 ]] || { err "validate-proposal requires <proposal-id>"; return 2; }
  local id="$1"
  local dir="$PROPOSALS_DIR/$id"
  local proposal_file="$dir/proposal.env"
  [[ -f "$proposal_file" ]] || { err "proposal not found: $id"; return 1; }
  load_env "$proposal_file"
  : "${SKILL:?missing SKILL}"
  : "${ADD_TRIGGER_TERMS:?missing ADD_TRIGGER_TERMS}"
  [[ -d "$SKILLS_DIR/$SKILL" ]] || { err "skill not found: $SKILL"; return 1; }

  local tmp_home output
  tmp_home="$(mktemp -d)"
  cp -a "$SKILLS_HOME/." "$tmp_home/"
  apply_trigger_terms "$tmp_home/skills.d/$SKILL/meta.env" "$ADD_TRIGGER_TERMS" >/dev/null
  output="$(HERMES_SKILLS_HOME="$tmp_home" "$ROOT_DIR/src/system/skill-router-v3.sh" find --limit 5 "$ADD_TRIGGER_TERMS" 2>/dev/null || true)"
  if [[ "$output" != *"$SKILL"* ]]; then
    rm -rf "$tmp_home"
    err "validation failed: updated skill did not rank for candidate terms"
    err "$output"
    return 1
  fi
  rm -rf "$tmp_home"
  record_memory_trajectory_required \
    --objective "skill-evolution" \
    --status "validated" \
    --skill "$SKILL" \
    --proposal-id "$id" \
    --input "$ADD_TRIGGER_TERMS" \
    --prediction "updated skill should rank for candidate terms" \
    --observed "validation passed" \
    --delta "eligible for promotion" \
    --agent "skill-evolver" \
    --evidence-refs "[\"$proposal_file\"]" \
    --confidence 0.85 \
    --security-classification "internal"
  printf 'validation passed: %s\n' "$id"
}

promote() {
  [[ $# -eq 1 ]] || { err "promote requires <proposal-id>"; return 2; }
  local id="$1"
  local dir="$PROPOSALS_DIR/$id"
  local proposal_file="$dir/proposal.env"
  [[ -f "$proposal_file" ]] || { err "proposal not found: $id"; return 1; }
  load_env "$proposal_file"
  : "${SKILL:?missing SKILL}"
  : "${ADD_TRIGGER_TERMS:?missing ADD_TRIGGER_TERMS}"
  local skill_dir="$SKILLS_DIR/$SKILL"
  local meta="$skill_dir/meta.env"
  [[ -f "$meta" ]] || { err "skill metadata not found: $SKILL"; return 1; }

  if [[ "${HERMES_SKIP_EVOLVE_VALIDATION:-0}" != "1" ]]; then
    validate_proposal "$id" >/dev/null
  fi

  mkdir -p "$BACKUPS_DIR/$id"
  cp "$meta" "$BACKUPS_DIR/$id/meta.env"
  [[ -f "$skill_dir/SKILL.md" ]] && cp "$skill_dir/SKILL.md" "$BACKUPS_DIR/$id/SKILL.md"
  [[ -f "$skill_dir/changelog.md" ]] && cp "$skill_dir/changelog.md" "$BACKUPS_DIR/$id/changelog.md"

  apply_trigger_terms "$meta" "$ADD_TRIGGER_TERMS" >/dev/null

  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  {
    printf '\n## %s\n\n' "$ts"
    printf -- '- Promoted proposal `%s`.\n' "$id"
    printf -- '- Added trigger terms: `%s`.\n' "$ADD_TRIGGER_TERMS"
  } >> "$skill_dir/changelog.md"

  python3 - "$proposal_file" <<'PY'
import re
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(r'^STATUS="[^"]+"', 'STATUS="promoted"', text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
  record_memory_trajectory_required \
    --objective "skill-evolution" \
    --status "promoted" \
    --skill "$SKILL" \
    --proposal-id "$id" \
    --input "$ADD_TRIGGER_TERMS" \
    --prediction "validated trigger terms should improve routing recall" \
    --observed "proposal promoted and skill metadata updated" \
    --delta "skill version bumped and changelog updated" \
    --agent "skill-evolver" \
    --evidence-refs "[\"$proposal_file\",\"$meta\",\"$skill_dir/changelog.md\",\"$BACKUPS_DIR/$id/meta.env\"]" \
    --confidence 0.9 \
    --security-classification "internal"
  printf 'promoted: %s\n' "$id"
}

reject() {
  [[ $# -eq 1 ]] || { err "reject requires <proposal-id>"; return 2; }
  local id="$1" proposal_file="$PROPOSALS_DIR/$id/proposal.env"
  [[ -f "$proposal_file" ]] || { err "proposal not found: $id"; return 1; }
  python3 - "$proposal_file" <<'PY'
import re
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(r'^STATUS="[^"]+"', 'STATUS="rejected"', text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY
  load_env "$proposal_file"
  record_memory_trajectory \
    --objective "skill-evolution" \
    --status "rejected" \
    --skill "${SKILL:-}" \
    --proposal-id "$id" \
    --input "${ADD_TRIGGER_TERMS:-}" \
    --prediction "proposal should not be promoted" \
    --observed "proposal rejected" \
    --delta "no live skill mutation" \
    --agent "skill-evolver" \
    --evidence-refs "[\"$proposal_file\"]" \
    --confidence 0.8 \
    --security-classification "internal"
  printf 'rejected: %s\n' "$id"
}

main() {
  local command="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    status) status "$@" ;;
    scan) scan_failures "$@" ;;
    propose) propose "$@" ;;
    list-proposals) list_proposals "$@" ;;
    show-proposal) show_proposal "$@" ;;
    validate-proposal) validate_proposal "$@" ;;
    promote) promote "$@" ;;
    reject) reject "$@" ;;
    help|-h|--help) usage ;;
    *) err "unknown command: $command"; usage >&2; return 2 ;;
  esac
}

main "$@"
