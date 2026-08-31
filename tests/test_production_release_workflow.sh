#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WF="$ROOT/.github/workflows/production-release-build.yml"
grep -q 'repository: Codename-11/hermes-relay' "$WF"
grep -q 'ref: 08545ed32db07609c14730a7fc02cdd758f12434' "$WF"
grep -q 'hermes_relay-1.10.0-py3-none-any.whl' "$WF"
grep -q '26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663' "$WF"
grep -q 'HERMES_RELAY_SOURCE_DIR:' "$WF"
grep -q 'HERMES_RELAY_SERVER_WHEEL:' "$WF"
grep -q 'vendor/hermes-relay/server-v1.10.0/SOURCE_PROVENANCE.json' "$WF"
grep -q "find .*'\\*.pyc'" "$WF"
echo PRODUCTION_RELEASE_WORKFLOW=PASS
