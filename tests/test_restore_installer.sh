#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESTORE="$ROOT_DIR/scripts/restore-hermes-build.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

chmod +x "$RESTORE"

output="$("$RESTORE" --verify-only --no-system-log-monitor)"
assert_contains "$output" "checking required dependencies"
assert_contains "$output" "required dependencies found"
assert_contains "$output" "layout verification complete"
assert_contains "$output" "restore complete"

[[ -f "$ROOT_DIR/.hermes/install/install.log" ]]
[[ -f "$ROOT_DIR/.hermes/install/system.log" ]]
[[ -f "$ROOT_DIR/.hermes/state/router.conf" ]]
[[ -f "$ROOT_DIR/.hermes/state/sweep.conf" ]]
[[ -f "$ROOT_DIR/.hermes/state/install.env" ]]
[[ -f "$ROOT_DIR/.hermes/state/first-run-config.done" ]]

log_content="$(cat "$ROOT_DIR/.hermes/install/install.log")"
assert_contains "$log_content" "install_log="
assert_contains "$log_content" "verify-only mode; skipping OBLITERATUS install"

second_output="$("$RESTORE" --verify-only --no-system-log-monitor)"
assert_contains "$second_output" "first-run skill OS configuration already complete"

echo "restore-installer tests passed"
