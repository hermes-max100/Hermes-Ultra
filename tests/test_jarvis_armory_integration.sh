#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/src/system/jarvis-armory.sh"
CONFIG="$ROOT_DIR/config/jarvis-armory.config.local.example.json"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

test -x "$SCRIPT"
python3 -m json.tool "$CONFIG" >/dev/null

printf 'test archive\n' > "$TMP_DIR/JARVIS-OS-v1.2.0-tool-armory.zip"
printf 'test wheel\n' > "$TMP_DIR/jarvis_os-1.2.0-py3-none-any.whl"
sha256sum "$TMP_DIR/JARVIS-OS-v1.2.0-tool-armory.zip" > "$TMP_DIR/JARVIS-OS-v1.2.0-tool-armory.zip.sha256"
sha256sum "$TMP_DIR/jarvis_os-1.2.0-py3-none-any.whl" > "$TMP_DIR/jarvis_os-1.2.0-py3-none-any.whl.sha256"

export JARVIS_ARMORY_ARCHIVE="$TMP_DIR/JARVIS-OS-v1.2.0-tool-armory.zip"
export JARVIS_ARMORY_ARCHIVE_SHA="$TMP_DIR/JARVIS-OS-v1.2.0-tool-armory.zip.sha256"
export JARVIS_ARMORY_WHEEL="$TMP_DIR/jarvis_os-1.2.0-py3-none-any.whl"
export JARVIS_ARMORY_WHEEL_SHA="$TMP_DIR/jarvis_os-1.2.0-py3-none-any.whl.sha256"

status_output="$("$SCRIPT" status || true)"
assert_contains "$status_output" "jarvis_dir="
assert_contains "$status_output" "url=http://127.0.0.1:4700"
assert_contains "$status_output" "archive_sha256="

verify_output="$("$SCRIPT" verify-artifacts)"
assert_contains "$verify_output" "archive_sha256=ok"
assert_contains "$verify_output" "wheel_sha256=ok"

python3 - "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["default_provider"] == "ninerouter"
providers = data["providers"]
assert providers["ninerouter"]["base_url"] == "http://127.0.0.1:20127/v1"
assert providers["omniroute"]["base_url"] == "http://127.0.0.1:20128/v1"
assert providers["omniroute_glm"]["model"] == "nvidia/glm-5.2"
assert providers["ninerouter_coding"]["model"] == "moonshotai/kimi-k3"
assert providers["ninerouter"]["api_key_env"] == "NINEROUTER_API_KEY"
assert data["browser_harness"]["allow_private_network"] is False
PY

echo "jarvis armory integration tests passed"
