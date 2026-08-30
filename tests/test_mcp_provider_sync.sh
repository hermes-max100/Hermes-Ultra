#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="$ROOT_DIR/config/mcp-provider-registry.json"
REGISTRY_MODULE="$ROOT_DIR/src/system/mcp-provider-registry.py"
SYNC_MODULE="$ROOT_DIR/src/system/mcp-provider-sync.py"
SYNC="$ROOT_DIR/scripts/sync-mcp-provider-registry.sh"

python3 - "$REGISTRY_MODULE" "$SYNC_MODULE" "$REGISTRY" <<'PY'
import importlib.util, json, pathlib, sys

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(module)
    return module
registry=load(pathlib.Path(sys.argv[1]),"mcp_registry")
sync=load(pathlib.Path(sys.argv[2]),"mcp_sync")
data=registry.load_registry(pathlib.Path(sys.argv[3]))
rendered=registry.render_hermes_servers(data,environ={})
managed={row["id"] for row in data["providers"]}
existing={
    "custom_local":{"command":"custom-mcp","enabled":True},
    "exa":{"url":"https://stale.invalid/mcp","enabled":False},
    "old_managed":{"url":"https://old.invalid/mcp","hermes_managed":True},
}
merged=sync.merge_managed_servers(existing,rendered,managed)
assert merged["custom_local"]==existing["custom_local"]
assert merged["exa"]["url"]=="https://mcp.exa.ai/mcp"
assert merged["exa"]["enabled"] is True
assert merged["playwright"]["enabled"] is True
assert "old_managed" not in merged
assert "hermes_managed" not in merged["exa"]
raw=json.dumps(merged,sort_keys=True)
for forbidden in ("sk_live_","ghp_","Bearer ey","password="):
    assert forbidden not in raw
PY

[[ -f "$SYNC" ]] || { echo "sync script missing" >&2; exit 1; }
python3 -m json.tool <(bash "$SYNC" dry-run) >/dev/null
bash "$SYNC" dry-run | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["exa"]["enabled"] is True; assert d["playwright"]["enabled"] is True'
bash -n "$SYNC"
echo "MCP_PROVIDER_SYNC_TEST=PASS"
