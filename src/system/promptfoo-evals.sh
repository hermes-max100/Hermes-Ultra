#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROMPTFOO_DIR="$ROOT_DIR/promptfoo"
CONFIG="$PROMPTFOO_DIR/promptfooconfig.yaml"
REPORT_DIR="$ROOT_DIR/.hermes/reports"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

usage() {
  cat <<'EOF'
Hermes Promptfoo Evals

Usage:
  src/system/promptfoo-evals.sh check
  src/system/promptfoo-evals.sh run
  src/system/promptfoo-evals.sh view

Commands:
  check  Validate the local Python eval pack without requiring promptfoo.
  run    Run promptfoo eval if npx is available.
  view   Open the latest promptfoo report if present.
EOF
}

check_pack() {
  python3 -m py_compile \
    "$PROMPTFOO_DIR/evals/prompts.py" \
    "$PROMPTFOO_DIR/evals/hermes_provider.py" \
    "$PROMPTFOO_DIR/evals/assertions.py"
  python3 - <<'PY'
import importlib.util
import sys
from pathlib import Path

root = Path("promptfoo/evals")

def load(name):
    spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module

prompts = load("prompts")
assertions = load("assertions")
prompt = prompts.create_prompt({
    "vars": {
        "query": "Use Kimi 3 to debug tests.",
        "project": "hermes-max",
        "model": "moonshotai/kimi-k3",
        "skills": ["agentic-coding-router"],
        "risk": "medium",
    }
})
text = str(prompt)
assert "moonshotai/kimi-k3" in text
assert "Require human approval" in text
assert assertions.assert_kimi3_route("moonshotai/kimi-k3 ninerouter-gateway", {})["pass"]
assert assertions.assert_prompt_policy(text.lower(), {})["pass"]
accept = '{"approval_required": true, "decision": "pass", "disclosure_status": "present", "human_required_actions": ["post", "send"]}'
hidden = '{"decision": "block", "reasons": ["hidden synthetic identity"], "approval_required": true}'
income = '{"decision": "block", "reasons": ["fake earnings claim"], "unsupported_claims": []}'
assert assertions.assert_virtual_creator_accepts_disclosed(accept, {})["pass"]
assert assertions.assert_virtual_creator_rejects_hidden_identity(hidden, {})["pass"]
assert assertions.assert_virtual_creator_rejects_income_claims(income, {})["pass"]
print("promptfoo eval pack check passed")
PY
}

run_promptfoo() {
  command -v npx >/dev/null 2>&1 || {
    echo "npx is required to run promptfoo. The local pack can still be checked with: src/system/promptfoo-evals.sh check" >&2
    exit 1
  }
  mkdir -p "$REPORT_DIR"
  (
    cd "$ROOT_DIR"
    PROMPTFOO_PYTHON="${PROMPTFOO_PYTHON:-python3}" \
      npx promptfoo@latest eval -c "$CONFIG" \
        --output "$REPORT_DIR/promptfoo-hermes-$STAMP.json"
  )
  echo "report=$REPORT_DIR/promptfoo-hermes-$STAMP.json"
}

view_latest() {
  find "$REPORT_DIR" -maxdepth 1 -name 'promptfoo-hermes-*.json' -type f 2>/dev/null | sort | tail -1
}

cmd="${1:-check}"
shift || true

case "$cmd" in
  check) check_pack ;;
  run) run_promptfoo ;;
  view) view_latest ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
