#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

test -f "$ROOT_DIR/.agents/skills/premortem/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/premortem/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/premortem/meta.env"

grep -q '^name: premortem$' "$ROOT_DIR/.agents/skills/premortem/SKILL.md"
grep -q '^description: Run a premortem' "$ROOT_DIR/.agents/skills/premortem/SKILL.md"
grep -q '^premortem$' "$ROOT_DIR/.skills/skills.txt"
grep -q 'premortem-report-YYYYMMDDTHHMMSSZ.html' "$ROOT_DIR/.agents/skills/premortem/SKILL.md"
grep -q 'premortem-transcript-YYYYMMDDTHHMMSSZ.md' "$ROOT_DIR/.agents/skills/premortem/SKILL.md"

echo "premortem skill tests passed"
