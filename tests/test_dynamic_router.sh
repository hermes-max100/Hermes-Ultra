#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        echo "$haystack" >&2
        exit 1
    fi
}

source "$ROUTER" --source

hardwire_route "review this vendor contract for liability and jurisdiction risk" "legal"
[[ "$ROUTER_PROFILE" == "legal" ]]
[[ "$ROUTER_INTENT" == "legal-review" ]]
assert_contains "$ROUTER_SKILLS" "citation-validation"
[[ "$ROUTER_ACCESS_METHOD" != "official_api" || -n "${OPENAI_API_KEY:-}${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]]

hardwire_route "analyze an options spread for volatility and assignment risk" "trading"
[[ "$ROUTER_PROFILE" == "trading" ]]
[[ "$ROUTER_INTENT" == "options-analysis" ]]
assert_contains "$ROUTER_SKILLS" "risk-management"

hardwire_route "threat model my owned SaaS API authentication flow" "hacker"
[[ "$ROUTER_PROFILE" == "security-research" ]]
assert_contains "$ROUTER_SKILLS" "remediation-planning"
[[ "$ROUTER_ACCESS_METHOD" == "local_runtime" ]]
[[ "$ROUTER_HEARTBEAT_INTERVAL_MINUTES" == "15" ]]

hardwire_route "review this owned service incident response plan" "cyberkimi-quarantine"
[[ "$ROUTER_PROFILE" == "cyberkimi-quarantine" ]]
[[ "$ROUTER_MODEL" == "cyberkimi-quarantine" ]]
[[ "$ROUTER_PROVIDER" == "adverserial" ]]
assert_contains "$ROUTER_SKILLS" "cyberkimi-quarantine"
[[ "$ROUTER_ACCESS_METHOD" != "official_api" || -n "${ADVERSERIAL_API_KEY:-}" ]]

cyberkimi_output="$(ADVERSERIAL_API_KEY=test "$ROUTER" --json "review this owned service incident response plan" cyberkimi-quarantine)"
assert_contains "$cyberkimi_output" '"profile": "cyberkimi-quarantine"'
assert_contains "$cyberkimi_output" '"model": "cyberkimi-quarantine"'
assert_contains "$cyberkimi_output" '"provider": "adverserial"'
assert_contains "$cyberkimi_output" '"provider_model_id": "lordx64/cyberkimi"'
assert_contains "$cyberkimi_output" '"access_method": "official_api"'

json_output="$("$ROUTER" --json "build a launch campaign and landing page brief" marketing)"
assert_contains "$json_output" '"profile": "marketing"'
assert_contains "$json_output" '"policy": "approved_api_connector_local_or_manual_handoff_only"'
assert_contains "$json_output" '"cost_controls"'

zenmux_output="$(ZENMUX_API_KEY=test "$ROUTER" --json "fix this failing test" direct)"
assert_contains "$zenmux_output" '"model": "zenmux-router"'
assert_contains "$zenmux_output" '"provider": "zenmux"'
assert_contains "$zenmux_output" '"access_method": "official_api"'

nvidia_output="$(NVIDIA_API_KEY=test "$ROUTER" --json "fix this failing test" direct)"
assert_contains "$nvidia_output" '"model": "nvidia-nim"'
assert_contains "$nvidia_output" '"provider": "nvidia"'
assert_contains "$nvidia_output" '"access_method": "official_api"'

omniroute_output="$(OMNIROUTE_API_KEY=test "$ROUTER" --json "fix this failing test" direct)"
assert_contains "$omniroute_output" '"model": "omniroute-gateway"'
assert_contains "$omniroute_output" '"provider": "omniroute"'
assert_contains "$omniroute_output" '"access_method": "official_api"'

override_output="$(NVIDIA_API_KEY=test HERMES_MODEL_KEY_OVERRIDE=nvidia-nim HERMES_MODEL_OVERRIDE=meta/llama-3.3-70b-instruct "$ROUTER" --json "fix this failing test" direct)"
assert_contains "$override_output" '"provider_model_id": "meta/llama-3.3-70b-instruct"'

thinking_output="$(HERMES_THINKING_LEVEL_OVERRIDE='Level 7 (Critical)' "$ROUTER" --json "fix this failing test" direct)"
assert_contains "$thinking_output" '"thinking_level": "Level 7 (Critical)"'

hardwire_route "heartbeat poll anything new" "legal"
[[ "$ROUTER_INTENT" == "background-check" ]]
[[ "$ROUTER_COST_MODE" == "background" ]]
[[ "$ROUTER_MAX_HISTORY_MESSAGES" == "20" ]]
[[ "$ROUTER_HEARTBEAT_INTERVAL_MINUTES" == "15" ]]

hardwire_route "have my hermes agent run obliteratus status" "security"
[[ "$ROUTER_INTENT" == "obliteratus-runner" ]]
assert_contains "$ROUTER_SKILLS" "obliteratus-runner"
[[ "$ROUTER_ACCESS_METHOD" == "local_runtime" ]]

hardwire_route "reverse engineer this instagram reel video into an exact blueprint" "direct-mode"
[[ "$ROUTER_PROFILE" == "direct" ]]
[[ "$ROUTER_INTENT" == "video-watch" ]]
assert_contains "$ROUTER_SKILLS" "video-watch"
assert_contains "$ROUTER_SKILLS" "agent-reach"
assert_contains "$ROUTER_SKILLS" "web-research"

hardwire_route "show memory fabric trajectories for repeated routing failures" "direct-mode"
[[ "$ROUTER_PROFILE" == "direct" ]]
[[ "$ROUTER_INTENT" == "hermes-memory-fabric" ]]
assert_contains "$ROUTER_SKILLS" "hermes-memory-fabric"
assert_contains "$ROUTER_SKILLS" "memory-retrieval"

hardwire_route "run the anchor evaluator against incumbent and candidate before promotion" "direct-mode"
[[ "$ROUTER_PROFILE" == "direct" ]]
[[ "$ROUTER_INTENT" == "hermes-anchor-evaluator" ]]
assert_contains "$ROUTER_SKILLS" "hermes-anchor-evaluator"
assert_contains "$ROUTER_SKILLS" "hermes-memory-fabric"

hardwire_route "start the canary controller with a bounded canary policy and rollback target" "direct-mode"
[[ "$ROUTER_PROFILE" == "direct" ]]
[[ "$ROUTER_INTENT" == "hermes-canary-controller" ]]
assert_contains "$ROUTER_SKILLS" "hermes-canary-controller"
assert_contains "$ROUTER_SKILLS" "hermes-anchor-evaluator"

hardwire_route "fix this failing test and update the docs" "direct-mode"
[[ "$ROUTER_PROFILE" == "direct" ]]
assert_contains "$ROUTER_SKILLS" "coding-review"
assert_contains "$ROUTER_SKILLS" "provider-routing"
[[ "$ROUTER_HEARTBEAT_INTERVAL_MINUTES" == "10" ]]

eval_output="$("$ROUTER" --evaluate "research current case law citations" legal)"
assert_contains "$eval_output" "Hermes Dynamic Router Evaluation"
assert_contains "$eval_output" "Profile: legal"

python3 -m json.tool "$ROOT_DIR/config/cost-policy.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/hermes-cost-controls.example.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/openclaw-cost-controls.example.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/hermes-direct-mode-policy.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/profiles/profile_manifest.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/gateways/model_providers.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/gateways/hermes_gateways.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/agents/hermes_agents.json" >/dev/null

echo "dynamic-router tests passed"
