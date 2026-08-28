#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 tests/test_agent_reach_security.py
python3 -m py_compile \
  src/system/agent-reach-safe-fetch.py \
  src/system/agent-reach-source-verify.py \
  src/system/agent-reach-query.py \
  src/system/agent-reach-github-query.py \
  src/system/agent-reach-envelope.py
bash -n src/system/agent-reach.sh
bash -n scripts/provision-agent-reach.sh

echo "agent reach security tests passed"
