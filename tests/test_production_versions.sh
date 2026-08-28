#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN="$ROOT_DIR/config/production-versions.json"
[[ -f "$PIN" ]] || { echo "missing production version pin file" >&2; exit 1; }
python3 - "$PIN" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p['hermes_agent']['tag']=='v2026.8.19'
assert p['hermes_agent']['version']=='0.20.5'
assert p['hermes_relay_android']['tag']=='android-v1.12.0'
assert p['hermes_relay_android']['version']=='1.12.0'
assert p['hermes_agent']['url']=='https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.19'
assert p['hermes_relay_android']['url']=='https://github.com/Codename-11/hermes-relay/releases/tag/android-v1.12.0'
PY
echo 'production version pins passed'
