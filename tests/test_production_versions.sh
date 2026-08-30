#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN="$ROOT_DIR/config/production-versions.json"
[[ -f "$PIN" ]] || { echo "missing production version pin file" >&2; exit 1; }
python3 - "$PIN" <<'PY'
import json, re, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p['hermes_agent']['tag']=='v2026.8.19'
assert p['hermes_agent']['version']=='0.20.5'
assert p['hermes_relay_android']['tag']=='android-v1.12.0'
assert p['hermes_relay_android']['version']=='1.12.0'
assert p['hermes_agent']['url']=='https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.19'
assert p['hermes_relay_android']['url']=='https://github.com/Codename-11/hermes-relay/releases/tag/android-v1.12.0'
assert p['orca_runtime']['tag']=='v1.4.190'
assert p['orca_runtime']['version']=='1.4.190'
assert p['orca_runtime']['asset']=='orca-linux.AppImage'
assert p['orca_runtime']['url']=='https://github.com/stablyai/orca/releases/download/v1.4.190/orca-linux.AppImage'
assert p['orca_runtime']['sha256']=='f5b321576d9c909f9e6987aa3bd20e8ff9f214d881b43c7109281cbc87878cde'
assert re.fullmatch(r'[0-9a-f]{64}', p['orca_runtime']['sha256'])
assert p['node_runtime']['minimum_major']==18
assert p['node_runtime']['packages']==['nodejs','npm']
PY
echo 'production version pins passed'
