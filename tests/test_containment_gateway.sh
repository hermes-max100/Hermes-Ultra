#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT_DIR/tests/test_containment_gateway.py"
python3 -m py_compile "$ROOT_DIR/src/system/containment-gateway.py"
bash -n "$ROOT_DIR/src/system/containment-gateway.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
export HERMES_CONTAINMENT_SECRET="cli-test-secret-that-is-longer-than-thirty-two-bytes"
export HERMES_CONTAINMENT_STATE_DIR="$TMP_DIR/state"
TOKEN="$TMP_DIR/token.json"

bash "$ROOT_DIR/src/system/containment-gateway.sh" issue \
  --principal agent:hermes --tool mcp:github --destination https://api.github.com \
  --resource repo:hurakan100/Hermes-Evolution --data-class INTERNAL \
  --purpose repo-maintenance --evidence-id ev_cli --ttl 60 > "$TOKEN"

verify_output="$(cat "$TOKEN" | bash "$ROOT_DIR/src/system/containment-gateway.sh" verify \
  --token-stdin --principal agent:hermes --tool mcp:github \
  --destination https://api.github.com --resource repo:hurakan100/Hermes-Evolution \
  --data-class INTERNAL)"
grep -q '"decision": "ALLOW"' <<<"$verify_output"

if cat "$TOKEN" | bash "$ROOT_DIR/src/system/containment-gateway.sh" verify \
  --token-stdin --principal agent:hermes --tool mcp:github \
  --destination https://api.github.com --resource repo:hurakan100/Hermes-Evolution \
  --data-class INTERNAL >/dev/null 2>&1; then
  echo "expected replay to be denied" >&2
  exit 1
fi

# Trusted startup configuration must not be replaceable by request arguments.
if bash "$ROOT_DIR/src/system/containment-gateway.sh" --secret-env PATH status >/dev/null 2>&1; then
  echo "expected --secret-env to be rejected" >&2
  exit 1
fi
if bash "$ROOT_DIR/src/system/containment-gateway.sh" --state-dir "$TMP_DIR/fresh-state" status >/dev/null 2>&1; then
  echo "expected --state-dir to be rejected" >&2
  exit 1
fi
if bash "$ROOT_DIR/src/system/containment-gateway.sh" verify \
  --token /etc/passwd --principal agent:hermes --tool mcp:github \
  --destination https://api.github.com --resource repo:hurakan100/Hermes-Evolution \
  --data-class INTERNAL >/dev/null 2>&1; then
  echo "expected caller-selected token file path to be rejected" >&2
  exit 1
fi

echo "containment gateway tests passed"
