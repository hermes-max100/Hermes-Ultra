#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="$ROOT_DIR/config/mcp-provider-registry.json"
MODULE="$ROOT_DIR/src/system/mcp-provider-registry.py"
SYNC="$ROOT_DIR/scripts/sync-mcp-provider-registry.sh"

python3 - "$MODULE" "$REGISTRY" <<'PY'
import importlib.util, json, pathlib, sys
module_path=pathlib.Path(sys.argv[1]); registry_path=pathlib.Path(sys.argv[2])
spec=importlib.util.spec_from_file_location("mcp_registry",module_path)
module=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(module)
data=module.load_registry(registry_path)
rendered=module.render_hermes_servers(data,environ={})
managed={row["id"] for row in data["providers"]}
existing={
    "custom_local":{"command":"custom-mcp","enabled":True},
    "exa":{"url":"https://stale.invalid/mcp","enabled":False},
    "old_managed":{"url":"https://old.invalid/mcp","hermes_managed":True},
}
merged=module.merge_managed_servers(existing,rendered,managed)
assert merged["custom_local"]==existing["custom_local"]
assert merged["exa"]["url"]=="https://mcp.exa.ai/mcp"
assert merged["exa"]["enabled"] is True
assert merged["playwright"]["enabled"] is True
assert "old_managed" not in merged
raw=json.dumps(merged,sort_keys=True)
for forbidden in ("sk_live_","ghp_","Bearer ey","password="):
    assert forbidden not in raw
PY

[[ -x "$SYNC" ]] || { echo "sync script missing or not executable" >&2; exit 1; }
python3 -m json.tool <("$SYNC" dry-run) >/dev/null
"$SYNC" dry-run | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["exa"]["enabled"] is True; assert d["playwright"]["enabled"] is True'
bash -n "$SYNC"
echo "MCP_PROVIDER_SYNC_TEST=PASS"
