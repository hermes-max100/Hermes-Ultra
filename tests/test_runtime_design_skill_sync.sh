#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC="$ROOT_DIR/scripts/sync-hermes-ultra-runtime-skills.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[[ -x "$SYNC" ]] || { echo 'runtime design skill sync script missing' >&2; exit 1; }

make_release() {
  local root="$1" marker="$2"
  mkdir -p "$root/.agents/skills/design-engineer" "$root/.agents/skills/web-design-guidelines"
  cat > "$root/.agents/skills/design-engineer/SKILL.md" <<EOF
---
name: design-engineer
description: test design engineer $marker
---
# Design Engineer $marker
EOF
  printf '{"schema_version":1,"marker":"%s"}\n' "$marker" > "$root/.agents/skills/design-engineer/acceptance.json"
  printf '{"schema_version":1,"marker":"%s"}\n' "$marker" > "$root/.agents/skills/design-engineer/sources.json"
  cat > "$root/.agents/skills/web-design-guidelines/SKILL.md" <<EOF
---
name: web-design-guidelines
description: test web guidelines $marker
---
# Web Guidelines $marker
EOF
}

HOME1="$TMP/hermes-home"
mkdir -p "$HOME1/skills/unrelated"
printf '%s\n' keep > "$HOME1/skills/unrelated/SKILL.md"
R1="$TMP/release-one"; R2="$TMP/release-two"
make_release "$R1" one
make_release "$R2" two

HERMES_HOME="$HOME1" bash "$SYNC" apply "$R1" r1 | grep -q '^HERMES_ULTRA_RUNTIME_SKILLS=PASS release=r1 previous=NONE$'
BASE="$HOME1/managed-skill-releases/hermes-ultra"
[[ "$(readlink "$BASE/current")" == "r1" ]]
[[ -L "$HOME1/skills/design-engineer" ]]
[[ -L "$HOME1/skills/web-design-guidelines" ]]
[[ "$(readlink "$HOME1/skills/design-engineer")" == "../managed-skill-releases/hermes-ultra/current/design-engineer" ]]
[[ "$(readlink "$HOME1/skills/web-design-guidelines")" == "../managed-skill-releases/hermes-ultra/current/web-design-guidelines" ]]
grep -q 'Design Engineer one' "$HOME1/skills/design-engineer/SKILL.md"
grep -q 'Web Guidelines one' "$HOME1/skills/web-design-guidelines/SKILL.md"
grep -qx keep "$HOME1/skills/unrelated/SKILL.md"
HERMES_HOME="$HOME1" bash "$SYNC" verify r1 | grep -q '^HERMES_ULTRA_RUNTIME_SKILLS_VERIFY=PASS release=r1$'

HERMES_HOME="$HOME1" bash "$SYNC" apply "$R2" r2 | grep -q '^HERMES_ULTRA_RUNTIME_SKILLS=PASS release=r2 previous=r1$'
[[ "$(readlink "$BASE/current")" == "r2" ]]
grep -q 'Design Engineer two' "$HOME1/skills/design-engineer/SKILL.md"
grep -q 'Web Guidelines two' "$HOME1/skills/web-design-guidelines/SKILL.md"
HERMES_HOME="$HOME1" bash "$SYNC" rollback r1 | grep -q '^HERMES_ULTRA_RUNTIME_SKILLS_ROLLBACK=PASS release=r1$'
grep -q 'Design Engineer one' "$HOME1/skills/design-engineer/SKILL.md"
HERMES_HOME="$HOME1" bash "$SYNC" verify r1 >/dev/null

# Existing user-owned skill names must fail closed rather than be overwritten.
HOME2="$TMP/collision-home"
mkdir -p "$HOME2/skills/design-engineer"
printf '%s\n' user-owned > "$HOME2/skills/design-engineer/SKILL.md"
if HERMES_HOME="$HOME2" bash "$SYNC" apply "$R1" r1 >/dev/null 2>&1; then
  echo 'user-owned skill collision was overwritten' >&2
  exit 1
fi
grep -qx user-owned "$HOME2/skills/design-engineer/SKILL.md"
[[ ! -e "$HOME2/managed-skill-releases/hermes-ultra/current" ]]

# Incomplete releases fail before activation.
HOME3="$TMP/incomplete-home"
mkdir -p "$TMP/incomplete/.agents/skills/design-engineer"
printf '%s\n' broken > "$TMP/incomplete/.agents/skills/design-engineer/SKILL.md"
if HERMES_HOME="$HOME3" bash "$SYNC" apply "$TMP/incomplete" bad >/dev/null 2>&1; then
  echo 'incomplete runtime skill release was accepted' >&2
  exit 1
fi
[[ ! -e "$HOME3/managed-skill-releases/hermes-ultra/current" ]]

echo 'runtime design skill sync tests passed'
