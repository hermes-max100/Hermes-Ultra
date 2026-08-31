#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
ARG2="${2:-}"
ARG3="${3:-}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SKILLS_DIR="$HERMES_HOME/skills"
BASE="$HERMES_HOME/managed-skill-releases/hermes-ultra"
CURRENT="$BASE/current"
LOCK_DIR="$BASE/.sync.lock"
MANAGED_SKILLS=(design-engineer web-design-guidelines)
LOCKED=0
APPLY_PREVIOUS=""
CURRENT_SWAPPED=0
SUCCESS=0
CREATED_LINKS=()

fail() { echo "runtime skill sync: $*" >&2; exit 1; }
valid_release_id() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; }
expected_link() { printf '../managed-skill-releases/hermes-ultra/current/%s' "$1"; }

swap_current() {
  local selector="$1" tmp="$BASE/.current.$$"
  ln -s "$selector" "$tmp"
  mv -Tf "$tmp" "$CURRENT"
}

cleanup() {
  local rc=$?
  if [[ "$rc" -ne 0 && "$ACTION" == "apply" ]]; then
    if [[ "$CURRENT_SWAPPED" == 1 ]]; then
      if [[ -n "$APPLY_PREVIOUS" ]]; then
        swap_current "$APPLY_PREVIOUS" >/dev/null 2>&1 || true
      else
        rm -f "$CURRENT" >/dev/null 2>&1 || true
      fi
    fi
    local link
    for link in "${CREATED_LINKS[@]:-}"; do
      [[ -n "$link" ]] && rm -f "$link" >/dev/null 2>&1 || true
    done
  fi
  [[ "$LOCKED" == 1 ]] && rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  return "$rc"
}
trap cleanup EXIT

acquire_lock() {
  mkdir -p "$BASE"
  mkdir "$LOCK_DIR" 2>/dev/null || fail "another managed skill sync is active"
  LOCKED=1
}

validate_source() {
  local release_root="$1" skill src
  for skill in "${MANAGED_SKILLS[@]}"; do
    src="$release_root/.agents/skills/$skill"
    [[ -d "$src" && -f "$src/SKILL.md" ]] || fail "required skill missing: $skill"
    if find "$src" -type l -print -quit | grep -q .; then
      fail "symlinks are not allowed inside managed runtime skill package: $skill"
    fi
  done
  [[ -f "$release_root/.agents/skills/design-engineer/acceptance.json" ]] || fail 'design-engineer acceptance.json missing'
  [[ -f "$release_root/.agents/skills/design-engineer/sources.json" ]] || fail 'design-engineer sources.json missing'
  python3 - "$release_root/.agents/skills/design-engineer/acceptance.json" "$release_root/.agents/skills/design-engineer/sources.json" <<'PY'
import json, sys
for path in sys.argv[1:]:
    with open(path, encoding='utf-8') as fh:
        data=json.load(fh)
    if data.get('schema_version') != 1:
        raise SystemExit(f'invalid managed design skill schema: {path}')
PY
}

build_target() {
  local release_root="$1" release_id="$2"
  local target="$BASE/$release_id" tmp="$BASE/.${release_id}.tmp.$$" skill
  validate_source "$release_root"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  for skill in "${MANAGED_SKILLS[@]}"; do
    mkdir -p "$tmp/$skill"
    cp -a "$release_root/.agents/skills/$skill/." "$tmp/$skill/"
  done
  (
    cd "$tmp"
    find . -type f ! -name '.manifest.sha256' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > .manifest.sha256
  )
  if [[ -e "$target" ]]; then
    [[ -f "$target/.manifest.sha256" ]] || fail "existing managed skill release lacks manifest: $release_id"
    (cd "$target" && sha256sum -c .manifest.sha256 >/dev/null) || fail "existing managed skill release is corrupt: $release_id"
    cmp -s "$tmp/.manifest.sha256" "$target/.manifest.sha256" || fail "managed skill release id collision: $release_id"
    rm -rf "$tmp"
  else
    mv "$tmp" "$target"
  fi
}

ensure_links() {
  mkdir -p "$SKILLS_DIR"
  local skill link expected
  for skill in "${MANAGED_SKILLS[@]}"; do
    link="$SKILLS_DIR/$skill"
    expected="$(expected_link "$skill")"
    if [[ -e "$link" || -L "$link" ]]; then
      [[ -L "$link" && "$(readlink "$link")" == "$expected" ]] || fail "refusing to overwrite user-owned skill path: $link"
    else
      ln -s "$expected" "$link"
      CREATED_LINKS+=("$link")
    fi
  done
}

verify_target() {
  local release_id="$1"
  local target="$BASE/$release_id" skill link expected
  valid_release_id "$release_id" || fail 'invalid release id'
  [[ -d "$target" && -f "$target/.manifest.sha256" ]] || fail "managed skill release missing: $release_id"
  (cd "$target" && sha256sum -c .manifest.sha256 >/dev/null) || fail "managed skill release manifest failed: $release_id"
  [[ -L "$CURRENT" && "$(readlink "$CURRENT")" == "$release_id" ]] || fail "managed skill selector is not active: $release_id"
  for skill in "${MANAGED_SKILLS[@]}"; do
    link="$SKILLS_DIR/$skill"
    expected="$(expected_link "$skill")"
    [[ -L "$link" && "$(readlink "$link")" == "$expected" ]] || fail "managed skill link invalid: $skill"
    [[ -f "$link/SKILL.md" ]] || fail "managed skill does not resolve: $skill"
  done
}

case "$ACTION" in
  apply)
    RELEASE_ROOT="$ARG2"; RELEASE_ID="$ARG3"
    [[ -d "$RELEASE_ROOT" ]] || fail 'release root not found'
    valid_release_id "$RELEASE_ID" || fail 'invalid release id'
    acquire_lock
    if [[ -e "$CURRENT" || -L "$CURRENT" ]]; then
      [[ -L "$CURRENT" ]] || fail "managed skill selector is not a symlink: $CURRENT"
      APPLY_PREVIOUS="$(readlink "$CURRENT")"
      valid_release_id "$APPLY_PREVIOUS" || fail "managed skill selector is invalid: $APPLY_PREVIOUS"
      [[ -d "$BASE/$APPLY_PREVIOUS" ]] || fail "managed skill selector target is missing: $APPLY_PREVIOUS"
    else
      APPLY_PREVIOUS=""
    fi
    build_target "$RELEASE_ROOT" "$RELEASE_ID"
    ensure_links
    swap_current "$RELEASE_ID"
    CURRENT_SWAPPED=1
    verify_target "$RELEASE_ID"
    SUCCESS=1
    printf 'HERMES_ULTRA_RUNTIME_SKILLS=PASS release=%s previous=%s\n' "$RELEASE_ID" "${APPLY_PREVIOUS:-NONE}"
    ;;
  verify)
    RELEASE_ID="$ARG2"
    verify_target "$RELEASE_ID"
    SUCCESS=1
    printf 'HERMES_ULTRA_RUNTIME_SKILLS_VERIFY=PASS release=%s\n' "$RELEASE_ID"
    ;;
  rollback)
    PREVIOUS="$ARG2"
    acquire_lock
    if [[ "$PREVIOUS" == "NONE" || -z "$PREVIOUS" ]]; then
      rm -f "$CURRENT"
      for skill in "${MANAGED_SKILLS[@]}"; do
        link="$SKILLS_DIR/$skill"
        expected="$(expected_link "$skill")"
        if [[ -L "$link" && "$(readlink "$link")" == "$expected" ]]; then rm -f "$link"; fi
      done
      SUCCESS=1
      printf 'HERMES_ULTRA_RUNTIME_SKILLS_ROLLBACK=PASS release=NONE\n'
    else
      valid_release_id "$PREVIOUS" || fail 'invalid rollback release id'
      [[ -d "$BASE/$PREVIOUS" ]] || fail "rollback target missing: $PREVIOUS"
      ensure_links
      swap_current "$PREVIOUS"
      verify_target "$PREVIOUS"
      SUCCESS=1
      printf 'HERMES_ULTRA_RUNTIME_SKILLS_ROLLBACK=PASS release=%s\n' "$PREVIOUS"
    fi
    ;;
  *)
    echo 'Usage: sync-hermes-ultra-runtime-skills.sh apply RELEASE_ROOT RELEASE_ID | verify RELEASE_ID | rollback RELEASE_ID|NONE' >&2
    exit 2
    ;;
esac
