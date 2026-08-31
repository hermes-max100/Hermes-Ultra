#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$ROOT_DIR/src/system/governed-graph-runtime.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 -m py_compile "$ROOT_DIR/src/system/governed_graph_runtime.py"
python3 -m py_compile "$ROOT_DIR/src/system/execution_state.py"
python3 -m py_compile "$ROOT_DIR/src/system/native_execution_backends.py"
python3 -m py_compile "$ROOT_DIR/src/system/codex_app_server.py"
python3 -m py_compile "$ROOT_DIR/src/system/background_task_reconciler.py"
python3 -m py_compile "$ROOT_DIR/src/system/hermes_relay_policy.py"
python3 -m py_compile "$ROOT_DIR/src/system/hermes_relay_adapter.py"
python3 -m py_compile "$ROOT_DIR/src/system/hermes_relay_reconciler.py"
bash -n "$RUNTIME"
python3 -m json.tool "$ROOT_DIR/config/governed-graph-runtime.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/governed-graph-plan.schema.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/governed-graph-plan.example.json" >/dev/null
python3 -m unittest -v \
  "$ROOT_DIR/tests/test_execution_state.py" \
  "$ROOT_DIR/tests/test_governed_graph_runtime.py" \
  "$ROOT_DIR/tests/test_codex_app_server.py" \
  "$ROOT_DIR/tests/test_background_task_reconciler.py" \
  "$ROOT_DIR/tests/test_hermes_relay_policy.py" \
  "$ROOT_DIR/tests/test_hermes_relay_adapter.py" \
  "$ROOT_DIR/tests/test_hermes_relay_reconciler.py"

analysis_json="$TMP_DIR/analysis.json"
"$RUNTIME" analyze \
  --plan "$ROOT_DIR/config/governed-graph-plan.example.json" \
  --resource-policy "$ROOT_DIR/config/governed-graph-runtime.json" > "$analysis_json"
python3 - "$analysis_json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["status"] == "valid", data
assert data["pruned_edge_ids"] == ["fake-a-b"], data
layers = data["layers"]
assert ["research_a", "research_b"] in layers, layers
assert data["estimated_cost"] <= 5.0, data
assert data["estimated_tokens"] <= 250000, data
PY

cat > "$TMP_DIR/cycle.json" <<'JSON'
{
  "version": "1",
  "nodes": [
    {"id": "a", "handler": "a"},
    {"id": "b", "handler": "b"}
  ],
  "edges": [
    {"id": "a-b", "source": "a", "target": "b", "kind": "order", "required": true},
    {"id": "b-a", "source": "b", "target": "a", "kind": "authority", "required": true}
  ]
}
JSON
if "$RUNTIME" validate --plan "$TMP_DIR/cycle.json" > "$TMP_DIR/cycle.out" 2>&1; then
  echo "cycle plan unexpectedly validated" >&2
  exit 1
fi
grep -q '"status": "invalid"' "$TMP_DIR/cycle.out"
grep -q 'cycle' "$TMP_DIR/cycle.out"

echo "GOVERNED_GRAPH_RUNTIME_TESTS=PASS"
