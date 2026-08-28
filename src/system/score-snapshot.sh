#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_HOME="${HERMES_SKILLS_HOME:-$ROOT_DIR/.skills}"
SKILLS_FILE="$SKILLS_HOME/skills.txt"
SKILLS_DIR="$SKILLS_HOME/skills.d"
SNAPSHOTS_FILE="$SKILLS_HOME/logs/score-snapshots.jsonl"

usage() {
  cat <<'EOF'
Hermes Skill Score Snapshot

Usage:
  src/system/score-snapshot.sh [--rubric structural-v1]

Records local rubric scores for each enabled skill into:
  .skills/logs/score-snapshots.jsonl
EOF
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

RUBRIC="structural-v1"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rubric)
      [[ $# -ge 2 ]] || { echo "missing value for --rubric" >&2; exit 2; }
      RUBRIC="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown flag: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -f "$SKILLS_FILE" ]] || { echo "missing skills file: $SKILLS_FILE" >&2; exit 1; }
mkdir -p "$(dirname "$SNAPSHOTS_FILE")"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

while IFS= read -r skill || [[ -n "$skill" ]]; do
  [[ -n "$skill" ]] || continue
  skill_dir="$SKILLS_DIR/$skill"
  [[ -d "$skill_dir" ]] || continue

  score="$(python3 - "$skill_dir" <<'PY'
from pathlib import Path
import re
import sys

skill_dir = Path(sys.argv[1])
score = 0
meta = skill_dir / "meta.env"
skill = skill_dir / "SKILL.md"
tests = skill_dir / "tests.md"
changelog = skill_dir / "changelog.md"

if meta.is_file():
    text = meta.read_text(encoding="utf-8", errors="replace")
    for key in ("NAME", "VERSION", "DESCRIPTION", "TAGS", "TRIGGERS", "INPUTS", "OUTPUTS", "RISK_LEVEL"):
        if re.search(rf"^{key}=\"[^\"]+\"", text, re.M):
            score += 7
if skill.is_file():
    text = skill.read_text(encoding="utf-8", errors="replace")
    score += 12
    if "## Rules" in text:
        score += 10
    if "## Outputs" in text:
        score += 10
    if len(text.split()) >= 60:
        score += 6
if tests.is_file() and "Expected:" in tests.read_text(encoding="utf-8", errors="replace"):
    score += 6
if changelog.is_file():
    score += 4
print(min(score, 100))
PY
)"

  printf '{"ts":"%s","skill":"%s","rubric":"%s","score":%s}\n' \
    "$(json_escape "$TS")" "$(json_escape "$skill")" "$(json_escape "$RUBRIC")" "$score" >> "$SNAPSHOTS_FILE"
  printf '%s score=%s rubric=%s\n' "$skill" "$score" "$RUBRIC"
done < "$SKILLS_FILE"

printf 'snapshots=%s\n' "$SNAPSHOTS_FILE"
