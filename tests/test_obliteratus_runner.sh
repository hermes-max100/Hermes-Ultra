#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/src/system/obliteratus-runner.sh"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

status_output="$("$RUNNER" status)"
assert_contains "$status_output" "installed=true"
assert_contains "$status_output" "venv_ready=true"
assert_contains "$status_output" "package_version=0.1.2"

doctor_output="$("$RUNNER" doctor)"
assert_contains "$doctor_output" "obliteratus import ok"
assert_contains "$doctor_output" "No broken requirements found"

help_output="$("$RUNNER" help)"
assert_contains "$help_output" "Master Ablation Suite"

models_output="$("$RUNNER" models --tier tiny)"
assert_contains "$models_output" "Model Library"

ui_command_output="$("$RUNNER" ui-command --port 7861)"
assert_contains "$ui_command_output" "ui"
assert_contains "$ui_command_output" "127.0.0.1"
assert_contains "$ui_command_output" "7861"

if "$RUNNER" ui-command --share >/tmp/obliteratus-share.out 2>&1; then
    echo "Expected --share to be blocked" >&2
    exit 1
fi
assert_contains "$(cat /tmp/obliteratus-share.out)" "share is disabled"

if "$RUNNER" run examples/preset_quick.yaml >/tmp/obliteratus-guard.out 2>&1; then
    echo "Expected model-editing command to be blocked" >&2
    exit 1
fi
assert_contains "$(cat /tmp/obliteratus-guard.out)" "model-editing"

if "$RUNNER" info sshleifer/tiny-gpt2 >/tmp/obliteratus-download.out 2>&1; then
    echo "Expected model-download command to be blocked" >&2
    exit 1
fi
assert_contains "$(cat /tmp/obliteratus-download.out)" "may download model files"

echo "obliteratus-runner tests passed"
