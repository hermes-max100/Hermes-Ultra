#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEEP="$ROOT_DIR/src/system/external-source-sweep.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

repo="$TMP_DIR/source-repo"
mkdir -p "$repo"
cat > "$repo/README.md" <<'EOF'
# Test Skill Source

Defensive skill examples for routing and review.
EOF
cat > "$repo/package.json" <<'EOF'
{
  "name": "test-skill-source",
  "version": "0.1.0",
  "scripts": {
    "postinstall": "node setup.js"
  }
}
EOF
cat > "$repo/setup.js" <<'EOF'
console.log("setup placeholder");
EOF
cat > "$repo/LICENSE" <<'EOF'
MIT
EOF

git -C "$repo" init -q
git -C "$repo" add .
git -C "$repo" -c user.name=Hermes -c user.email=hermes@example.invalid commit -q -m init

config="$TMP_DIR/sources.json"
cat > "$config" <<EOF
{
  "version": "1.0.0",
  "sources": [
    {
      "id": "local-test-source",
      "type": "github_repo",
      "url": "$repo",
      "homepage": "$repo",
      "import_policy": "review_before_install",
      "risk_level": "medium"
    }
  ]
}
EOF

cache="$TMP_DIR/cache"
reports="$TMP_DIR/reports"
proposals="$TMP_DIR/proposals"
output="$(HERMES_EXTERNAL_SOURCES_CONFIG="$config" HERMES_EXTERNAL_CACHE_DIR="$cache" HERMES_REPORTS_DIR="$reports" HERMES_EXTERNAL_PROPOSALS_DIR="$proposals" "$SWEEP" run)"
assert_contains "$output" "report="
assert_contains "$output" "jsonl="
assert_contains "$output" "proposals=1"

report_file="$(printf '%s\n' "$output" | awk -F= '/^report=/ {print $2}')"
jsonl_file="$(printf '%s\n' "$output" | awk -F= '/^jsonl=/ {print $2}')"

test -f "$report_file"
test -f "$jsonl_file"
test -d "$cache/local-test-source/.git"
test -f "$proposals"/local-test-source-*/README.md

jsonl="$(cat "$jsonl_file")"
assert_contains "$jsonl" "\"id\": \"local-test-source\""
assert_contains "$jsonl" "\"package.json\""
assert_contains "$jsonl" "npm_postinstall_script"

status_output="$(HERMES_EXTERNAL_SOURCES_CONFIG="$config" HERMES_EXTERNAL_CACHE_DIR="$cache" HERMES_REPORTS_DIR="$reports" HERMES_EXTERNAL_PROPOSALS_DIR="$proposals" "$SWEEP" status)"
assert_contains "$status_output" "sources=1"
assert_contains "$status_output" "report="

echo "external source sweep tests passed"
