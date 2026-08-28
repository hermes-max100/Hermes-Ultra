#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POLICY_FILE="${HERMES_COST_POLICY_FILE:-$ROOT_DIR/config/cost-policy.json}"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"

usage() {
    echo "Usage:"
    echo "  src/system/cost-audit.sh [--json]"
    echo "  HERMES_COST_POLICY_FILE=path/to/policy.json src/system/cost-audit.sh"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ ! -f "$POLICY_FILE" ]]; then
    echo "Missing cost policy: $POLICY_FILE" >&2
    exit 1
fi

source "$ROUTER" --source

audit_json() {
    COST_POLICY_FILE="$POLICY_FILE" python3 <<'PYEOF'
import json
import os

path = os.environ["COST_POLICY_FILE"]
with open(path, "r", encoding="utf-8") as handle:
    policy = json.load(handle)

history = policy.get("conversation_history", {})
background = policy.get("background_work", {})
budget = policy.get("tool_schema_budget", {})
provider = policy.get("provider_policy", {})
intervals = background.get("heartbeat_interval_minutes", {})
disallowed = set(provider.get("disallowed", []))

checks = []

def add(name, passed, detail):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})

max_history = history.get("max_history_messages")
add("history_cap", isinstance(max_history, int) and max_history <= 20, f"max_history_messages={max_history}")

model_preference = background.get("model_preference", [])
add("background_model_route", bool(model_preference), f"model_preference={model_preference}")

default_interval = intervals.get("default")
add("heartbeat_interval", isinstance(default_interval, int) and default_interval >= 10, f"default={default_interval}")

max_skills = budget.get("default_max_enabled_skills")
add("skill_schema_budget", isinstance(max_skills, int) and max_skills <= 6, f"default_max_enabled_skills={max_skills}")

required_blocks = {
    "subscription_cookie_automation",
    "session_token_reuse",
    "provider_rate_limit_bypass",
    "paywall_or_captcha_bypass",
}
add("provider_bypass_blocks", required_blocks.issubset(disallowed), f"disallowed={sorted(disallowed)}")

payload = {
    "policy_file": path,
    "passed": all(item["passed"] for item in checks),
    "checks": checks,
}
print(json.dumps(payload, indent=2, sort_keys=True))
PYEOF
}

audit_text() {
    local output
    output="$(audit_json)"
    AUDIT_OUTPUT="$output" python3 <<'PYEOF'
import json
import os

payload = json.loads(os.environ["AUDIT_OUTPUT"])
print("Hermes Cost Audit")
print(f"Policy: {payload['policy_file']}")
print(f"Status: {'PASS' if payload['passed'] else 'FAIL'}")
for check in payload["checks"]:
    marker = "PASS" if check["passed"] else "FAIL"
    print(f"- {marker}: {check['name']} ({check['detail']})")
PYEOF
}

case "${1:-}" in
    --json|-j)
        audit_json ;;
    "")
        audit_text
        echo ""
        "$ROUTER" --json "heartbeat poll anything new" legal ;;
    *)
        echo "Unknown command: $1" >&2
        usage >&2
        exit 2 ;;
esac
