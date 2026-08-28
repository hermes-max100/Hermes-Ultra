#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/src/system/promptfoo-evals.sh"
CONFIG="$ROOT_DIR/promptfoo/promptfooconfig.yaml"

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
test -f "$CONFIG"

out="$("$SCRIPT" check)"
assert_contains "$out" "promptfoo eval pack check passed"

python3 - <<'PY'
from pathlib import Path
cfg = Path("promptfoo/promptfooconfig.yaml").read_text(encoding="utf-8")
assert "file://evals/prompts.py:create_prompt" in cfg
assert "file://evals/hermes_provider.py:call_api" in cfg
assert "assert_kimi3_route" in cfg
assert "assert_approval_boundary" in cfg
assert "assert_virtual_creator_accepts_disclosed" in cfg
assert "assert_virtual_creator_rejects_hidden_identity" in cfg
assert "assert_virtual_creator_rejects_income_claims" in cfg
assert Path("promptfoo/evals/virtual-creator-policy.yaml").is_file()
PY

echo "promptfoo eval tests passed"
