#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/src/system" "$TMP/.hermes"
cp "$ROOT_DIR/src/system/hermes-dispatch.sh" "$TMP/src/system/hermes-dispatch.sh"
cp "$ROOT_DIR/src/system/otel-bridge.py" "$TMP/src/system/otel-bridge.py"
chmod +x "$TMP/src/system/hermes-dispatch.sh"

cat > "$TMP/src/system/dynamic-router.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--json" ]]; then
  printf '%s\n' '{"model":"test-router","provider_model_id":"test/model","skills":["skill-a"]}'
else
  printf '%s\n' 'route ok'
fi
EOF
chmod +x "$TMP/src/system/dynamic-router.sh"

cat > "$TMP/src/system/skill-router.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$TMP/src/system/skill-router.sh"

cat > "$TMP/src/system/memory-fabric.py" <<'EOF'
#!/usr/bin/env python3
import json, pathlib, sys
if sys.argv[1] != "ingest-trajectory":
    raise SystemExit(2)
value = sys.argv[sys.argv.index("--json") + 1]
pathlib.Path(".hermes/captured-trajectory.json").write_text(json.dumps(json.loads(value), sort_keys=True))
EOF
chmod +x "$TMP/src/system/memory-fabric.py"

(
  cd "$TMP"
  HERMES_OTEL_OUTPUT="$TMP/.hermes/telemetry/spans.jsonl" \
  HERMES_SKILLS_HOME="$TMP/.skills" \
  "$TMP/src/system/hermes-dispatch.sh" --json "route this test" > "$TMP/result.json"
)

python3 - "$TMP" <<'PY'
import json, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
span_path = root / ".hermes/telemetry/spans.jsonl"
assert span_path.is_file(), span_path
rows = [json.loads(line) for line in span_path.read_text().splitlines() if line.strip()]
assert len(rows) == 1, rows
span = rows[0]
assert span["name"] == "hermes.dispatch", span
assert re.fullmatch(r"[0-9a-f]{32}", span["trace_id"]), span
assert "route this test" not in json.dumps(span), span
trajectory = json.loads((root / ".hermes/captured-trajectory.json").read_text())
meta = trajectory["metadata"]
assert meta["trace_id"] == span["trace_id"], (meta, span)
assert meta["span_id"] == span["span_id"], (meta, span)
assert trajectory["input_hash"] and trajectory["objective"] == "route this test"
print("HERMES_DISPATCH_OTEL=PASS")
PY
