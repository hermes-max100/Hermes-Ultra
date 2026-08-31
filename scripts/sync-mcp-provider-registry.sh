#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-dry-run}"
REGISTRY="${HERMES_MCP_REGISTRY:-$ROOT_DIR/config/mcp-provider-registry.json}"
REGISTRY_MODULE="$ROOT_DIR/src/system/mcp-provider-registry.py"
SYNC_MODULE="$ROOT_DIR/src/system/mcp-provider-sync.py"

case "$ACTION" in
  dry-run)
    exec python3 "$REGISTRY_MODULE" --registry "$REGISTRY" render
    ;;
  status)
    exec python3 "$REGISTRY_MODULE" --registry "$REGISTRY" status
    ;;
  apply)
    ;;
  *)
    echo "usage: sync-mcp-provider-registry.sh [dry-run|status|apply]" >&2
    exit 2
    ;;
esac

PYTHON="${HERMES_RUNTIME_PYTHON:-${HERMES_AGENT_PYTHON:-}}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x /var/lib/hermes/.hermes/hermes-agent/venv/bin/python ]]; then
    PYTHON=/var/lib/hermes/.hermes/hermes-agent/venv/bin/python
  elif [[ -x /var/lib/hermes/.hermes/hermes-agent-0.20.5/venv/bin/python ]]; then
    PYTHON=/var/lib/hermes/.hermes/hermes-agent-0.20.5/venv/bin/python
  else
    PYTHON=python3
  fi
fi

exec "$PYTHON" - "$REGISTRY_MODULE" "$SYNC_MODULE" "$REGISTRY" <<'PY'
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys


def load(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

registry_module=load(Path(sys.argv[1]),"hermes_mcp_registry_sync")
sync_module=load(Path(sys.argv[2]),"hermes_mcp_sync")
data=registry_module.load_registry(Path(sys.argv[3]))
errors=registry_module.validate_registry(data)
if errors:
    raise SystemExit("registry invalid: " + "; ".join(errors))
rendered=registry_module.render_hermes_servers(data)
managed={row["id"] for row in data["providers"]}

from hermes_cli.mcp_config import _get_mcp_servers, _replace_mcp_servers
existing=_get_mcp_servers()
hermes_home=Path(os.environ.get("HERMES_HOME", Path.home()/".hermes"))
state_path=hermes_home/"mcp-provider-registry-managed.json"
previous=[]
if state_path.exists():
    try:
        value=json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value,list): previous=[x for x in value if isinstance(x,str)]
    except Exception:
        previous=[]
merged=sync_module.merge_managed_servers(existing,rendered,managed,previous_managed=previous)
ok,issues=_replace_mcp_servers(merged)
if not ok:
    raise SystemExit("native Hermes MCP validation failed: " + "; ".join(issues))
state_path.parent.mkdir(parents=True,exist_ok=True)
tmp=state_path.with_suffix(".tmp")
tmp.write_text(json.dumps(sorted(managed),indent=2)+"\n",encoding="utf-8")
tmp.replace(state_path)
print(json.dumps({
    "result":"MCP_PROVIDER_SYNC=PASS",
    "managed_count":len(managed),
    "rendered_count":len(rendered),
    "enabled":sorted(name for name,cfg in rendered.items() if cfg.get("enabled") is True),
    "preserved_unmanaged":sorted(set(existing)-managed),
},sort_keys=True))
PY
