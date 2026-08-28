#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 tests/test_bot_mode_governance.py
python3 tests/test_bot_mode_redteam.py
python3 tests/test_bot_mode_lifecycle.py
python3 -m py_compile src/system/bot-mode-governance.py
python3 src/system/bot-mode-governance.py validate-policy

echo "governed Bot Mode security tests passed"
