#!/usr/bin/env bash

ALLOWED_KEYS=(
  HERMES_SMTP_HOST
  HERMES_SMTP_PORT
  HERMES_SMTP_USER
  HERMES_SMTP_PASSWORD
  HERMES_SMTP_FROM
  HERMES_CONTACT_NAME
  HERMES_CONTACT_EMAIL
  HERMES_PRIMARY_PROVIDER
  HERMES_FALLBACK_PROVIDER
)

usage() {
  cat <<'EOF'
Usage:
  source src/system/load-hermes-runtime-env.sh --file PATH --check smtp|contact-form

The loader exports allowlisted Hermes runtime variables from PATH, rejects
unknown keys, and refuses to load a world-readable file.
EOF
}

die() {
  printf '%s\n' "$*" >&2
  return 1
}

trim() {
  local value="$1"
  value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  printf '%s' "$value"
}

is_allowed_key() {
  local key="$1"
  local candidate
  for candidate in "${ALLOWED_KEYS[@]}"; do
    [[ "$candidate" == "$key" ]] && return 0
  done
  return 1
}

strip_outer_quotes() {
  local value="$1"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

load_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || { die "env file not found: $env_file"; return 1; }

  local mode other_digit
  mode="$(stat -c '%a' "$env_file" 2>/dev/null)" || { die "unable to inspect permissions: $env_file"; return 1; }
  other_digit="${mode: -1}"
  if [[ "$other_digit" =~ [4-7] ]]; then
    die "refusing to load world-readable env file: $env_file"
    return 1
  fi

  local line trimmed key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    trimmed="$(trim "$line")"
    [[ -z "$trimmed" || "${trimmed:0:1}" == "#" ]] && continue
    if [[ "$trimmed" =~ ^export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
    elif [[ "$trimmed" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
    else
      die "invalid env line: $trimmed"
      return 1
    fi
    is_allowed_key "$key" || { die "unknown env key: $key"; return 1; }
    value="$(strip_outer_quotes "$(trim "$value")")"
    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"
}

check_smtp() {
  local required=(HERMES_SMTP_HOST HERMES_SMTP_PORT HERMES_SMTP_USER HERMES_SMTP_PASSWORD HERMES_SMTP_FROM)
  local key value
  for key in "${required[@]}"; do
    value="${!key:-}"
    [[ -n "$value" ]] || { die "missing required SMTP variable: $key"; return 1; }
  done
  [[ "${HERMES_SMTP_PORT:-}" =~ ^[0-9]+$ ]] || { die "HERMES_SMTP_PORT must be numeric"; return 1; }
  (( HERMES_SMTP_PORT >= 1 && HERMES_SMTP_PORT <= 65535 )) || { die "HERMES_SMTP_PORT out of range"; return 1; }
}

check_contact_form() {
  local required=(HERMES_CONTACT_NAME HERMES_CONTACT_EMAIL)
  local key value
  for key in "${required[@]}"; do
    value="${!key:-}"
    [[ -n "$value" ]] || { die "missing required contact-form variable: $key"; return 1; }
  done
}

main() {
  local env_file="" check_target=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --file)
        [[ $# -ge 2 ]] || { die "--file requires a path"; return 1; }
        env_file="$2"
        shift 2
        ;;
      --check)
        [[ $# -ge 2 ]] || { die "--check requires smtp or contact-form"; return 1; }
        check_target="$2"
        shift 2
        ;;
      --help|-h)
        usage
        return 0
        ;;
      *)
        die "unknown argument: $1"
        return 1
        ;;
    esac
  done

  [[ -n "$env_file" ]] || { die "--file is required"; return 1; }
  [[ -n "$check_target" ]] || { die "--check is required"; return 1; }

  load_env_file "$env_file" || return 1

  case "$check_target" in
    smtp)
      check_smtp || return 1
      ;;
    contact-form)
      check_contact_form || return 1
      ;;
    *)
      die "unknown check target: $check_target"
      return 1
      ;;
  esac
}

main "$@"
