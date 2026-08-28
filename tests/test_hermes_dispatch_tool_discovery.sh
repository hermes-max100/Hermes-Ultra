#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/src/system" "$TMP/config" "$TMP/.hermes"
cp "$ROOT_DIR/src/system/hermes-dispatch.sh" "$TMP/src/system/hermes-dispatch.sh"
cp "$ROOT_DIR/src/system/otel-bridge.py" "$TMP/src/system/otel-bridge.py"
cp "$ROOT_DIR/src/system/tool-discovery.py" "$TMP/src/system/tool-discovery.py"
chmod +x "$TMP/src/system/hermes-dispatch.sh"
cat > "$TMP/src/system/dynamic-router.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--json" ]]; then printf '%s\n' '{"model":"test-router","provider_model_id":"test/model","skills":[]}'; else printf '%s\n' 'route ok'; fi
EOF
chmod +x "$TMP/src/system/dynamic-router.sh"
cat > "$TMP/src/system/skill-router.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$TMP/src/system/skill-router.sh"
cat > "$TMP/src/system/memory-fabric.py" <<'EOF'
#!/usr/bin/env python3
import json,pathlib,sys
if sys.argv[1] != "ingest-trajectory": raise SystemExit(2)
value=sys.argv[sys.argv.index("--json")+1]
pathlib.Path(".hermes/captured-trajectory.json").write_text(json.dumps(json.loads(value),sort_keys=True))
EOF
chmod +x "$TMP/src/system/memory-fabric.py"
cat > "$TMP/config/tool-registry.json" <<'EOF'
{"schema_version":"hermes-tool-registry-v1","tools":[{"name":"memory.search","namespace":"memory","description":"Search Memory Fabric facts decisions history and provenance","keywords":["memory","recall","fact","history"],"mutating":false,"data_classes":["PUBLIC","INTERNAL","CONFIDENTIAL","LEGAL_PRIVILEGED","FINANCIAL","SECURITY_SENSITIVE"],"required_capabilities":[],"input_schema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]},"source":"src/system/memory-fabric.py"},{"name":"jarvis.browser","namespace":"jarvis","description":"Open public websites with browser automation","keywords":["browser","website","web"],"mutating":true,"data_classes":["PUBLIC","INTERNAL"],"required_capabilities":["network.public.browser"],"input_schema":{"type":"object","properties":{"url":{"type":"string"}}},"source":"src/system/jarvis-armory.sh"}]}
EOF
(
 cd "$TMP"
 HERMES_OTEL_OUTPUT="$TMP/.hermes/telemetry/spans.jsonl" HERMES_TOOL_REGISTRY="$TMP/config/tool-registry.json" HERMES_MEMORY_DISABLE=0 "$TMP/src/system/hermes-dispatch.sh" --json "recall a prior fact from memory" > "$TMP/result.json"
)
python3 - "$TMP" <<'PY'
import json,pathlib,sys
root=pathlib.Path(sys.argv[1]); rows=[json.loads(x) for x in (root/".hermes/telemetry/spans.jsonl").read_text().splitlines() if x.strip()]
assert len(rows)==1,rows
attrs=rows[0]["attributes"]
assert attrs["hermes.selected_tools"]==["memory.search"],attrs
assert "jarvis.browser" not in json.dumps(attrs),attrs
trajectory=json.loads((root/".hermes/captured-trajectory.json").read_text())
assert trajectory["metadata"]["selected_tools"]==["memory.search"],trajectory
assert trajectory["metadata"]["tool_source"]=="progressive_tool_discovery",trajectory
print("HERMES_DISPATCH_TOOL_DISCOVERY=PASS")
PY
