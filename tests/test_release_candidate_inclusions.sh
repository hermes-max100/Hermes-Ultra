#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for path in \
  config/hermes-relay-policy.json \
  config/hermes-relay-upstream.json \
  scripts/stage-hermes-relay-source.sh \
  scripts/export-hermes-relay-dependency-lock.sh \
  scripts/install-hermes-relay.sh \
  scripts/hermes-relay-doctor.sh \
  src/system/hermes_relay_adapter.py \
  src/system/hermes_relay_policy.py \
  src/system/hermes_relay_reconciler.py; do
  test -f "$ROOT/$path" || { echo "missing release inclusion: $path" >&2; exit 1; }
done
python3 - "$ROOT/config/production-versions.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert p['node_runtime']['minimum_major']==22
assert p['hermes_relay_android']['version']=='1.13.2'
PY
grep -q "find .*\\*.pyc" "$ROOT/scripts/build-cloud-release.sh" || { echo 'release does not purge .pyc files' >&2; exit 1; }
grep -q 'install-hermes-relay.sh' "$ROOT/scripts/install-cloud-release-local.sh" || { echo 'cloud installer does not integrate Relay' >&2; exit 1; }
echo RELEASE_CANDIDATE_INCLUSIONS=PASS
