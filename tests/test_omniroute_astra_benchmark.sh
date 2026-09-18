#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OMNI="$ROOT_DIR/src/system/omniroute.sh"
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

selection_file="$TMP_DIR/selection.env"
printf '%s\n' 'SENTINEL=unchanged' > "$selection_file"

plan_output="$(
    HERMES_CLOUD_MODEL_SELECTION_FILE="$selection_file" \
    "$OMNI" benchmark-astra plan \
      --repo-path "$ROOT_DIR" \
      --base-sha f7a1581c6374217d46db247522cc0551b15c1d91 \
      --task 'inspect the same repository-scale task'
)"

assert_contains "$plan_output" '"gpt-6-astra"'
assert_contains "$plan_output" '"us.openai.gpt-6-astra"'
assert_contains "$plan_output" '"benchmark_only": true'
assert_contains "$plan_output" '"primary_eligible": false'
assert_contains "$plan_output" '"primary_route_change_allowed": false'
assert_contains "$plan_output" '"human_approval_required": true'

if [[ "$(cat "$selection_file")" != 'SENTINEL=unchanged' ]]; then
    echo "Astra benchmark mutated primary model selection state" >&2
    cat "$selection_file" >&2
    exit 1
fi

echo "omniroute Astra benchmark tests passed"
