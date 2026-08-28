#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCES="$ROOT_DIR/config/external-skill-sources.json"
SECURITY_AGENT="$ROOT_DIR/agents/03_hermes_security_research_agent.md"
SECURITY_PROFILE="$ROOT_DIR/profiles/security/SOUL.md"
DIRECT_PROFILE="$ROOT_DIR/profiles/direct/SOUL.md"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

python3 -m json.tool "$SOURCES" >/dev/null

source_ids="$(python3 - <<'PY'
import json
from pathlib import Path
data=json.loads(Path("config/external-skill-sources.json").read_text())
print("\n".join(item["id"] for item in data["sources"]))
PY
)"

assert_contains "$source_ids" "colibri-glm52-runtime"
assert_contains "$source_ids" "openwiki-agent-docs"
assert_contains "$source_ids" "open-connector-saas-gateway"
assert_contains "$source_ids" "aos-agent-os"
assert_contains "$source_ids" "scroll-world-skill"
assert_contains "$source_ids" "tempest-red-team-harness"

security_agent_text="$(cat "$SECURITY_AGENT")"
security_profile_text="$(cat "$SECURITY_PROFILE")"
direct_profile_text="$(cat "$DIRECT_PROFILE")"

assert_contains "$security_agent_text" "T3MP3ST/Tempest"
assert_contains "$security_agent_text" "review-only"
assert_contains "$security_agent_text" "explicit target scope"
assert_contains "$security_profile_text" "T3MP3ST/Tempest"
assert_contains "$security_profile_text" "written authorization"
assert_contains "$direct_profile_text" "T3MP3ST/Tempest"
assert_contains "$direct_profile_text" "review-only"

echo "external skill sources tests passed"
