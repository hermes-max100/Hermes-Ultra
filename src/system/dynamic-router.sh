#!/usr/bin/env bash

# Hermes Dynamic Router
#
# Source this file from other scripts, or execute it directly with --evaluate.
# It does not call providers. It only classifies requests, chooses a compliant
# route, and emits routing metadata for Hermes orchestration.

declare -A MODELS
MODELS["gemini-flash"]='{"name":"Gemini Flash","provider":"gemini","api":"GEMINI_API_KEY","speed":"fast","best_for":"quick analysis and drafting","cost":"provider_billed_or_manual","strength":4}'
MODELS["gemini-pro"]='{"name":"Gemini Pro","provider":"gemini","api":"GEMINI_API_KEY","speed":"medium","best_for":"deep analysis and long-context review","cost":"provider_billed_or_manual","strength":6}'
MODELS["openai-fast"]='{"name":"OpenAI Fast","provider":"openai","api":"OPENAI_API_KEY","speed":"fast","best_for":"quick structured outputs and coding assistance","cost":"provider_billed_or_manual","strength":5}'
MODELS["openai-reasoning"]='{"name":"OpenAI Reasoning","provider":"openai","api":"OPENAI_API_KEY","speed":"medium","best_for":"complex reasoning, code, and synthesis","cost":"provider_billed_or_manual","strength":7}'
MODELS["perplexity-research"]='{"name":"Perplexity Research","provider":"perplexity","api":"PERPLEXITY_API_KEY","speed":"medium","best_for":"current research and citations","cost":"provider_billed_or_manual","strength":5}'
MODELS["venice-creative"]='{"name":"Venice Creative","provider":"venice","api":"VENICE_API_KEY","speed":"medium","best_for":"creative variants and alternative model perspectives","cost":"provider_billed_or_manual","strength":5}'
MODELS["zenmux-router"]='{"name":"ZenMux Router","provider":"zenmux","api":"ZENMUX_API_KEY","speed":"medium","best_for":"multi-model cloud routing through an OpenAI-compatible endpoint","cost":"provider_billed_or_subscription","strength":6}'
MODELS["nvidia-nim"]='{"name":"NVIDIA NIM","provider":"nvidia","api":"NVIDIA_API_KEY","speed":"medium","best_for":"NVIDIA-hosted NIM models through an OpenAI-compatible endpoint","cost":"provider_billed_or_free_tier","strength":6}'
MODELS["omniroute-gateway"]='{"name":"OmniRoute Gateway","provider":"omniroute","api":"OMNIROUTE_API_KEY","speed":"variable","best_for":"local OmniRoute gateway fallback, compression, provider pools, and auto-combo routing","cost":"omniroute_backend_policy","strength":6}'
MODELS["ninerouter-gateway"]='{"name":"9Router Gateway","provider":"9router","api":"NINEROUTER_API_KEY","speed":"variable","best_for":"local 9Router gateway fallback, RTK token saving, provider pools, and coding-tool routing","cost":"9router_backend_policy","strength":6}'
MODELS["cyberkimi-quarantine"]='{"name":"CyberKimi Quarantine","provider":"adverserial","api":"ADVERSERIAL_API_KEY","provider_model_id":"lordx64/cyberkimi","speed":"medium","best_for":"quarantined defensive cyber reasoning, detection engineering, incident response, and lab-only exploitability assessment reports","cost":"provider_billed_or_manual","strength":7}'
MODELS["local-private"]='{"name":"Local Private Model","provider":"local","api":"","speed":"variable","best_for":"private data, offline fallback, security-sensitive review","cost":"local_runtime","strength":4}'

declare -A SKILLS
SKILLS["legal-review"]='{"name":"Legal Review","best_for":"contracts, legal issues, attorney-review drafts","default_level":"high","strength":6}'
SKILLS["legal-research"]='{"name":"Legal Research","best_for":"jurisdiction, statutes, cases, regulations, citations","default_level":"high","strength":6}'
SKILLS["citation-validation"]='{"name":"Citation Validation","best_for":"source grounding and current authority checks","default_level":"high","strength":5}'
SKILLS["options-analysis"]='{"name":"Options Analysis","best_for":"options structures, greeks, payoff, volatility","default_level":"medium","strength":4}'
SKILLS["market-research"]='{"name":"Market Research","best_for":"current market context and source-backed research","default_level":"medium","strength":4}'
SKILLS["risk-management"]='{"name":"Risk Management","best_for":"max loss, sizing, margin, liquidity, assignment risk","default_level":"high","strength":5}'
SKILLS["security-review"]='{"name":"Authorized Security Review","best_for":"owned systems, defensive testing, secure design","default_level":"high","strength":6}'
SKILLS["threat-modeling"]='{"name":"Threat Modeling","best_for":"assets, actors, trust boundaries, abuse cases","default_level":"high","strength":6}'
SKILLS["remediation-planning"]='{"name":"Remediation Planning","best_for":"fix plans, detection, monitoring, validation","default_level":"high","strength":5}'
SKILLS["cyberkimi-quarantine"]='{"name":"CyberKimi Quarantine","best_for":"defensive cyber reasoning with strict no-tools/no-autonomy boundaries","default_level":"high","strength":6}'
SKILLS["product-launch"]='{"name":"Product Launch","best_for":"positioning, offer design, campaigns, launch plans","default_level":"medium","strength":4}'
SKILLS["income-generation"]='{"name":"Income Generation","best_for":"solo-founder offers and low-capital business ideas","default_level":"medium","strength":3}'
SKILLS["marketing-analysis"]='{"name":"Marketing Analysis","best_for":"campaigns, personas, content, claims, conversion","default_level":"medium","strength":4}'
SKILLS["web-research"]='{"name":"Web Research","best_for":"current public information and source discovery","default_level":"medium","strength":4}'
SKILLS["agent-reach"]='{"name":"Agent Reach","best_for":"public-source trend discovery, source-linked collection, GitHub/social/forum sweep inputs","default_level":"medium","strength":4}'
SKILLS["video-watch"]='{"name":"Video Watch","best_for":"public/local video ingestion, transcript and frame extraction, reverse-engineering visible workflows","default_level":"medium","strength":5}'
SKILLS["hermes-trust-gate"]='{"name":"Hermes Trust Gate","best_for":"supply-chain review, external skill/MCP/package/model/capability quarantine, signed evidence artifacts","default_level":"high","strength":7}'
SKILLS["hermes-memory-fabric"]='{"name":"Hermes Memory Fabric","best_for":"governed memory graph, trajectories, provenance, failure history, decision records, supersession, and safe retrieval","default_level":"medium","strength":7}'
SKILLS["hermes-anchor-evaluator"]='{"name":"Hermes Anchor Evaluator","best_for":"frozen anchor suites, incumbent-vs-candidate comparison, independent verifier gates, canary readiness, and promotion evidence","default_level":"high","strength":7}'
SKILLS["hermes-canary-controller"]='{"name":"Hermes Canary Controller","best_for":"bounded canary rollout, rollback triggers, candidate freeze, previous-version restore, and promotion safety telemetry","default_level":"high","strength":7}'
SKILLS["memory-retrieval"]='{"name":"Memory Retrieval","best_for":"profile context, prior decisions, persistent facts","default_level":"medium","strength":4}'
SKILLS["provider-routing"]='{"name":"Provider Routing","best_for":"approved model/provider selection","default_level":"medium","strength":4}'
SKILLS["coding-review"]='{"name":"Coding Review","best_for":"implementation, debugging, tests, code critique","default_level":"high","strength":5}'
SKILLS["obliteratus-runner"]='{"name":"OBLITERATUS Runner","best_for":"local OBLITERATUS status, doctor, model listings, presets, strategies, smoke tests, and local UI management","default_level":"medium","strength":4}'
SKILLS["background-check"]='{"name":"Background Check","best_for":"heartbeats, cron checks, status polling, cheap classification","default_level":"low","strength":1}'

declare -A PROFILE_SKILLS
PROFILE_SKILLS["general"]="provider-routing,hermes-memory-fabric,memory-retrieval,web-research"
PROFILE_SKILLS["legal"]="legal-review,legal-research,citation-validation,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["hermes-legal"]="legal-review,legal-research,citation-validation,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["trading"]="options-analysis,market-research,risk-management,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["options-trader"]="options-analysis,market-research,risk-management,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["security"]="security-review,threat-modeling,remediation-planning,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["security-research"]="hermes-trust-gate,security-review,threat-modeling,remediation-planning,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["hacker"]="hermes-trust-gate,security-review,threat-modeling,remediation-planning,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["cyberkimi-quarantine"]="cyberkimi-quarantine,security-review,threat-modeling,remediation-planning,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["solopreneur"]="income-generation,product-launch,marketing-analysis,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["solo-entrepreneur"]="income-generation,product-launch,marketing-analysis,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["marketing"]="marketing-analysis,product-launch,web-research,hermes-memory-fabric,memory-retrieval,provider-routing"
PROFILE_SKILLS["direct"]="coding-review,web-research,hermes-memory-fabric,memory-retrieval,provider-routing"

json_field() {
    local json="$1"
    local field="$2"
    JSON_INPUT="$json" JSON_FIELD="$field" python3 <<'PYEOF'
import json
import os

try:
    data = json.loads(os.environ.get("JSON_INPUT", "{}"))
except json.JSONDecodeError:
    data = {}

value = data.get(os.environ.get("JSON_FIELD", ""), "")
print(value)
PYEOF
}

normalize_profile() {
    local profile="${1:-general}"
    profile="${profile//_/-}"
    profile="${profile,,}"
    case "$profile" in
        legal|hermes-legal) echo "legal" ;;
        trading|options-trader|options-trading) echo "trading" ;;
        security|security-research|hacker|security-pentest) echo "security-research" ;;
        cyberkimi|cyberkimi-quarantine|adverserial-cyberkimi) echo "cyberkimi-quarantine" ;;
        solopreneur|solo-entrepreneur|zero-capital-income) echo "solopreneur" ;;
        marketing|concept-to-launch) echo "marketing" ;;
        direct|direct-mode|direct-but-bounded|bounded-direct|hermes-direct) echo "direct" ;;
        *) echo "general" ;;
    esac
}

profile_policy_key() {
    local profile
    profile=$(normalize_profile "${1:-general}")
    case "$profile" in
        security-research) echo "security_research" ;;
        cyberkimi-quarantine) echo "security_research" ;;
        *) echo "$profile" ;;
    esac
}

analyze_complexity() {
    local request="$1"
    COMPLEXITY_REQUEST="$request" python3 <<'PYEOF'
import os
import re

request = os.environ.get("COMPLEXITY_REQUEST", "")
lower = request.lower()
word_count = len(request.split())
score = 0.1

signals = [
    (r"(critical|urgent|high[- ]stakes|production|liability|privilege)", 0.2),
    (r"(security|vulnerability|threat|cve|incident|breach)", 0.2),
    (r"(legal|contract|statute|regulation|jurisdiction|case law)", 0.2),
    (r"(options?|volatility|margin|portfolio|risk|market)", 0.15),
    (r"(complex|advanced|deep|thorough|comprehensive|strategic)", 0.15),
    (r"(analyze|research|investigate|evaluate|assess|audit|review)", 0.15),
    (r"(architecture|design|implement|framework|router|orchestrator)", 0.15),
]

for pattern, weight in signals:
    if re.search(pattern, lower):
        score += weight

if word_count > 20:
    score += 0.1
if word_count > 40:
    score += 0.15

print(f"{min(1.0, max(0.1, score)):.2f}")
PYEOF
}

classify_intent() {
    local request="$1"
    INTENT_REQUEST="$request" python3 <<'PYEOF'
import os
import re

request = os.environ.get("INTENT_REQUEST", "").lower()
scores = {
    "legal-review": 0.0,
    "legal-research": 0.0,
    "options-analysis": 0.0,
    "market-research": 0.0,
    "security-review": 0.0,
    "threat-modeling": 0.0,
    "product-launch": 0.0,
    "income-generation": 0.0,
    "marketing-analysis": 0.0,
    "coding-review": 0.0,
    "obliteratus-runner": 0.0,
    "background-check": 0.0,
    "video-watch": 0.0,
    "hermes-trust-gate": 0.0,
    "hermes-memory-fabric": 0.0,
    "hermes-anchor-evaluator": 0.0,
    "hermes-canary-controller": 0.0,
    "web-research": 0.1,
}

patterns = {
    "legal-review": r"(contract|clause|agreement|legal review|nda|msa|liability|privilege)",
    "legal-research": r"(case law|statute|regulation|jurisdiction|precedent|citation|court)",
    "options-analysis": r"(option|spread|straddle|strangle|covered call|put|call|greeks|volatility)",
    "market-research": r"(stock|market|ticker|earnings|macro|price|portfolio|sector)",
    "security-review": r"(security|vulnerability|cve|auth|hardening|defensive|owned system|scope|incident response|detection engineering|patch diff)",
    "threat-modeling": r"(threat model|trust boundary|abuse case|attack surface|risk model)",
    "product-launch": r"(launch|go to market|mvp|offer|positioning|campaign)",
    "income-generation": r"(income|revenue|monetize|solo|solopreneur|business idea)",
    "marketing-analysis": r"(marketing|persona|copy|landing page|email sequence|ads|funnel)",
    "coding-review": r"(code|bug|test|implementation|script|router|cli|refactor)",
    "obliteratus-runner": r"(obliteratus|obliterate|abliterate|ablation suite|model ablation|refusal direction|refusal removal)",
    "background-check": r"(heartbeat|cron|poll|status check|anything new|new message|background|classify)",
    "video-watch": r"(instagram reel|reel|youtube|youtu\.be|video|tiktok|shorts|transcript|frame extraction|yt-dlp|reverse engineer.*video|watch this|analyze.*video|extract.*frames)",
    "hermes-trust-gate": r"(trust gate|supply chain|supply-chain|external skill|mcp server|candidate skill|quarantine|promote.*skill|install.*skill|activate.*skill|package review|model artifact|capability bundle|signed evidence)",
    "hermes-memory-fabric": r"(memory fabric|knowledge graph|experience graph|trajectory|trajectories|provenance|supersedes|supersession|failure history|decision record|durable memory|repeated failure|validated memory|disputed evidence)",
    "hermes-anchor-evaluator": r"(anchor evaluator|anchor suite|frozen anchor|incumbent|candidate.*score|candidate.*incumbent|independent verifier|promotion evidence|regression suite|critical regression)",
    "hermes-canary-controller": r"(canary controller|canary policy|canary rollout|rollback controller|rollback target|rollback condition|freeze candidate|previous known-good|previous version|bounded canary|atomic rollback|idempotent rollback)",
    "web-research": r"(research|search|source|current|latest|docs|web)",
}

for intent, pattern in patterns.items():
    matches = re.findall(pattern, request)
    scores[intent] += len(matches) * 0.25

best = max(scores, key=scores.get)
print(f"{best}:{scores[best]:.2f}")
PYEOF
}

append_unique_csv() {
    local base="$1"
    local item="$2"
    [[ -z "$item" ]] && echo "$base" && return 0
    case ",$base," in
        *",$item,"*) echo "$base" ;;
        *) [[ -z "$base" ]] && echo "$item" || echo "$base,$item" ;;
    esac
}

select_skills() {
    local intent="$1"
    local profile
    profile=$(normalize_profile "${2:-general}")
    local skills="${PROFILE_SKILLS[$profile]:-${PROFILE_SKILLS[general]}}"
    skills=$(append_unique_csv "$skills" "$intent")

    case "$intent" in
        legal-review|legal-research)
            skills=$(append_unique_csv "$skills" "citation-validation") ;;
        options-analysis|market-research)
            skills=$(append_unique_csv "$skills" "risk-management") ;;
        security-review|threat-modeling)
            skills=$(append_unique_csv "$skills" "remediation-planning") ;;
        cyberkimi-quarantine)
            skills=$(append_unique_csv "$skills" "security-review")
            skills=$(append_unique_csv "$skills" "threat-modeling")
            skills=$(append_unique_csv "$skills" "remediation-planning") ;;
        product-launch|marketing-analysis)
            skills=$(append_unique_csv "$skills" "web-research") ;;
        obliteratus-runner)
            skills=$(append_unique_csv "$skills" "coding-review") ;;
        video-watch)
            skills=$(append_unique_csv "$skills" "agent-reach")
            skills=$(append_unique_csv "$skills" "web-research") ;;
        hermes-trust-gate)
            skills=$(append_unique_csv "$skills" "security-review")
            skills=$(append_unique_csv "$skills" "threat-modeling") ;;
        hermes-memory-fabric)
            skills=$(append_unique_csv "$skills" "memory-retrieval")
            skills=$(append_unique_csv "$skills" "provider-routing") ;;
        hermes-anchor-evaluator)
            skills=$(append_unique_csv "$skills" "hermes-memory-fabric")
            skills=$(append_unique_csv "$skills" "hermes-trust-gate") ;;
        hermes-canary-controller)
            skills=$(append_unique_csv "$skills" "hermes-anchor-evaluator")
            skills=$(append_unique_csv "$skills" "hermes-memory-fabric") ;;
        background-check)
            skills="background-check,provider-routing" ;;
    esac

    echo "$skills"
}

select_background_model() {
    [[ -n "${HERMES_BACKGROUND_MODEL:-}" && -n "${MODELS[$HERMES_BACKGROUND_MODEL]:-}" ]] && echo "$HERMES_BACKGROUND_MODEL" && return 0
    [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-flash" && return 0
    [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-fast" && return 0
    echo "local-private"
}

select_model() {
    local intent="$1"
    local complexity="$2"
    local profile
    profile=$(normalize_profile "${3:-general}")

    if [[ -n "${HERMES_MODEL_KEY_OVERRIDE:-}" && -n "${MODELS[$HERMES_MODEL_KEY_OVERRIDE]:-}" ]]; then
        echo "$HERMES_MODEL_KEY_OVERRIDE"
        return 0
    fi

    if [[ "$intent" == "background-check" ]]; then
        select_background_model
        return 0
    fi

    if [[ "$intent" == "obliteratus-runner" ]]; then
        echo "local-private"
        return 0
    fi

    case "$intent" in
        legal-research|market-research|web-research)
            [[ -n "${PERPLEXITY_API_KEY:-}" ]] && echo "perplexity-research" && return 0 ;;
    esac

    case "$profile" in
        legal)
            if python3 -c "raise SystemExit(0 if float('$complexity') >= 0.65 else 1)"; then
                [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-reasoning" && return 0
                [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-pro" && return 0
            fi
            [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-pro" && return 0
            echo "local-private" ;;
        trading)
            [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-flash" && return 0
            [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-fast" && return 0
            echo "local-private" ;;
        cyberkimi-quarantine)
            echo "cyberkimi-quarantine" ;;
        security-research)
            echo "local-private" ;;
        solopreneur|marketing)
            [[ -n "${NVIDIA_API_KEY:-}" ]] && echo "nvidia-nim" && return 0
            [[ -n "${OMNIROUTE_API_KEY:-}" ]] && echo "omniroute-gateway" && return 0
            [[ -n "${NINEROUTER_API_KEY:-}" ]] && echo "ninerouter-gateway" && return 0
            [[ -n "${ZENMUX_API_KEY:-}" ]] && echo "zenmux-router" && return 0
            [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-fast" && return 0
            [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-flash" && return 0
            [[ -n "${VENICE_API_KEY:-}" ]] && echo "venice-creative" && return 0
            echo "local-private" ;;
        direct)
            [[ -n "${NVIDIA_API_KEY:-}" ]] && echo "nvidia-nim" && return 0
            [[ -n "${OMNIROUTE_API_KEY:-}" ]] && echo "omniroute-gateway" && return 0
            [[ -n "${NINEROUTER_API_KEY:-}" ]] && echo "ninerouter-gateway" && return 0
            [[ -n "${ZENMUX_API_KEY:-}" ]] && echo "zenmux-router" && return 0
            [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-fast" && return 0
            [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-flash" && return 0
            echo "local-private" ;;
        *)
            [[ -n "${NVIDIA_API_KEY:-}" ]] && echo "nvidia-nim" && return 0
            [[ -n "${OMNIROUTE_API_KEY:-}" ]] && echo "omniroute-gateway" && return 0
            [[ -n "${NINEROUTER_API_KEY:-}" ]] && echo "ninerouter-gateway" && return 0
            [[ -n "${ZENMUX_API_KEY:-}" ]] && echo "zenmux-router" && return 0
            [[ -n "${OPENAI_API_KEY:-}" ]] && echo "openai-fast" && return 0
            [[ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]] && echo "gemini-flash" && return 0
            echo "local-private" ;;
    esac
}

cost_policy_value() {
    local selector="$1"
    local default="$2"
    local policy_file="${HERMES_COST_POLICY_FILE:-config/cost-policy.json}"

    if [[ ! -f "$policy_file" ]]; then
        echo "$default"
        return 0
    fi

    COST_POLICY_FILE="$policy_file" COST_SELECTOR="$selector" COST_DEFAULT="$default" python3 <<'PYEOF'
import json
import os

path = os.environ["COST_POLICY_FILE"]
selector = os.environ["COST_SELECTOR"].split(".")
default = os.environ["COST_DEFAULT"]

try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, json.JSONDecodeError):
    print(default)
    raise SystemExit

value = data
for part in selector:
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        print(default)
        raise SystemExit

if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PYEOF
}

count_csv_items() {
    local csv="$1"
    CSV_INPUT="$csv" python3 <<'PYEOF'
import os
items = [item for item in os.environ.get("CSV_INPUT", "").split(",") if item]
print(len(items))
PYEOF
}

select_heartbeat_interval() {
    local profile_key
    profile_key=$(profile_policy_key "${1:-general}")
    local value
    value=$(cost_policy_value "background_work.heartbeat_interval_minutes.$profile_key" "")
    [[ -n "$value" ]] && echo "$value" && return 0
    cost_policy_value "background_work.heartbeat_interval_minutes.default" "10"
}

select_thinking_level() {
    local intent="$1"
    local complexity="$2"
    local level="Level 3"
    local level_name="Medium"

    if python3 -c "raise SystemExit(0 if float('$complexity') >= 0.8 else 1)"; then
        level="Level 7"
        level_name="Critical"
    elif python3 -c "raise SystemExit(0 if float('$complexity') >= 0.6 else 1)"; then
        level="Level 5"
        level_name="High"
    elif python3 -c "raise SystemExit(0 if float('$complexity') < 0.3 else 1)"; then
        level="Level 1"
        level_name="Low"
    fi

    case "$intent" in
        legal-review|legal-research|security-review|threat-modeling)
            if [[ "$level" == "Level 1" || "$level" == "Level 3" ]]; then
                level="Level 5"
                level_name="High"
            fi ;;
    esac

    echo "$level ($level_name)"
}

select_access_method() {
    local model_key="$1"
    local model_json="${MODELS[$model_key]:-${MODELS[local-private]}}"
    local provider
    local api
    provider=$(json_field "$model_json" "provider")
    api=$(json_field "$model_json" "api")

    if [[ "$provider" == "local" ]]; then
        echo "local_runtime"
    elif [[ -n "$api" && -n "${!api:-}" ]]; then
        echo "official_api"
    else
        echo "manual_handoff_or_configure_api"
    fi
}

hardwire_route() {
    local request="$1"
    local profile
    profile=$(normalize_profile "${2:-general}")

    local intent_score
    intent_score=$(classify_intent "$request")
    ROUTER_INTENT="${intent_score%%:*}"
    ROUTER_INTENT_SCORE="${intent_score##*:}"
    ROUTER_COMPLEXITY=$(analyze_complexity "$request")
    ROUTER_THINKING_LEVEL=$(select_thinking_level "$ROUTER_INTENT" "$ROUTER_COMPLEXITY")
    if [[ -n "${HERMES_THINKING_LEVEL_OVERRIDE:-}" ]]; then
        ROUTER_THINKING_LEVEL="$HERMES_THINKING_LEVEL_OVERRIDE"
    fi
    ROUTER_MODEL=$(select_model "$ROUTER_INTENT" "$ROUTER_COMPLEXITY" "$profile")

    local model_json="${MODELS[$ROUTER_MODEL]:-${MODELS[local-private]}}"
    ROUTER_MODEL_NAME=$(json_field "$model_json" "name")
    ROUTER_PROVIDER=$(json_field "$model_json" "provider")
    ROUTER_ACCESS_METHOD=$(select_access_method "$ROUTER_MODEL")
    if [[ -n "${HERMES_PROVIDER_OVERRIDE:-}" ]]; then
        ROUTER_PROVIDER="$HERMES_PROVIDER_OVERRIDE"
    fi
    if [[ -n "${HERMES_PROVIDER_API_KEY_ENV:-}" ]]; then
        if [[ -n "${!HERMES_PROVIDER_API_KEY_ENV:-}" ]]; then
            ROUTER_ACCESS_METHOD="official_api"
        else
            ROUTER_ACCESS_METHOD="manual_handoff_or_configure_api"
        fi
    fi
    ROUTER_SKILLS=$(select_skills "$ROUTER_INTENT" "$profile")
    ROUTER_SKILL_SOURCE="profile_router"
    if [[ -n "${HERMES_SKILL_SET_OVERRIDE:-}" ]]; then
        ROUTER_SKILLS="$HERMES_SKILL_SET_OVERRIDE"
        ROUTER_SKILL_SOURCE="${HERMES_SKILL_SET_SOURCE:-dynamic_skill_engine}"
    fi
    ROUTER_PROFILE="$profile"
    ROUTER_PROVIDER_MODEL_ID="${HERMES_MODEL_OVERRIDE:-$(json_field "$model_json" "provider_model_id")}"
    ROUTER_POLICY="approved_api_connector_local_or_manual_handoff_only"
    ROUTER_MAX_HISTORY_MESSAGES=$(cost_policy_value "conversation_history.max_history_messages" "20")
    ROUTER_HEARTBEAT_INTERVAL_MINUTES=$(select_heartbeat_interval "$profile")
    ROUTER_ENABLED_SKILL_COUNT=$(count_csv_items "$ROUTER_SKILLS")
    ROUTER_SKILL_BUDGET=$(cost_policy_value "tool_schema_budget.default_max_enabled_skills" "6")
    ROUTER_COST_MODE=$([[ "$ROUTER_INTENT" == "background-check" ]] && echo "background" || echo "interactive")

    export ROUTER_INTENT ROUTER_INTENT_SCORE ROUTER_COMPLEXITY ROUTER_THINKING_LEVEL
    export ROUTER_MODEL ROUTER_MODEL_NAME ROUTER_PROVIDER ROUTER_ACCESS_METHOD
    export ROUTER_SKILLS ROUTER_SKILL_SOURCE ROUTER_PROFILE ROUTER_PROVIDER_MODEL_ID ROUTER_POLICY
    export ROUTER_MAX_HISTORY_MESSAGES ROUTER_HEARTBEAT_INTERVAL_MINUTES
    export ROUTER_ENABLED_SKILL_COUNT ROUTER_SKILL_BUDGET ROUTER_COST_MODE
}

print_json_route() {
    local task="$1"
    local profile="${2:-general}"
    hardwire_route "$task" "$profile"
    python3 <<'PYEOF'
import json
import os

payload = {
    "profile": os.environ.get("ROUTER_PROFILE", "general"),
    "intent": os.environ.get("ROUTER_INTENT", "web-research"),
    "intent_score": os.environ.get("ROUTER_INTENT_SCORE", "0.00"),
    "complexity": os.environ.get("ROUTER_COMPLEXITY", "0.10"),
    "thinking_level": os.environ.get("ROUTER_THINKING_LEVEL", "Level 3 (Medium)"),
    "model": os.environ.get("ROUTER_MODEL", "local-private"),
    "model_name": os.environ.get("ROUTER_MODEL_NAME", "Local Private Model"),
    "provider": os.environ.get("ROUTER_PROVIDER", "local"),
    "provider_model_id": os.environ.get("ROUTER_PROVIDER_MODEL_ID", ""),
    "access_method": os.environ.get("ROUTER_ACCESS_METHOD", "local_runtime"),
    "skills": [item for item in os.environ.get("ROUTER_SKILLS", "").split(",") if item],
    "skill_source": os.environ.get("ROUTER_SKILL_SOURCE", "profile_router"),
    "policy": os.environ.get("ROUTER_POLICY", ""),
    "cost_controls": {
        "mode": os.environ.get("ROUTER_COST_MODE", "interactive"),
        "max_history_messages": int(os.environ.get("ROUTER_MAX_HISTORY_MESSAGES", "20")),
        "heartbeat_interval_minutes": int(os.environ.get("ROUTER_HEARTBEAT_INTERVAL_MINUTES", "10")),
        "enabled_skill_count": int(os.environ.get("ROUTER_ENABLED_SKILL_COUNT", "0")),
        "skill_budget": int(os.environ.get("ROUTER_SKILL_BUDGET", "6")),
    },
}
print(json.dumps(payload, indent=2, sort_keys=True))
PYEOF
}

print_attribution() {
    local task="$1"
    local profile="${2:-general}"
    local extra="${3:-}"

    hardwire_route "$task" "$profile"

    echo ""
    echo "---"
    echo ""
    local provider_model=""
    if [[ -n "${ROUTER_PROVIDER_MODEL_ID:-}" ]]; then
        provider_model=" | **Provider Model**: ${ROUTER_PROVIDER_MODEL_ID}"
    fi
    echo "> **Model**: ${ROUTER_MODEL_NAME:-Unknown} | **Provider**: ${ROUTER_PROVIDER:-unknown}${provider_model} | **Access**: ${ROUTER_ACCESS_METHOD:-unknown} | **Profile**: ${ROUTER_PROFILE:-general} | **Skill Set**: ${ROUTER_SKILLS:-general} | **Skill Source**: ${ROUTER_SKILL_SOURCE:-profile_router} | **Thinking Level**: ${ROUTER_THINKING_LEVEL:-Level 3 (Medium)} | **Intent**: ${ROUTER_INTENT:-web-research} | **Complexity**: ${ROUTER_COMPLEXITY:-0.10}"
    if [[ -n "$extra" ]]; then
        echo "> **Integrations**: $extra"
    fi
    echo "> **Policy**: approved APIs, approved connectors, local runtimes, or manual handoff only"
    echo "> **Cost Controls**: history=${ROUTER_MAX_HISTORY_MESSAGES:-20} messages | heartbeat=${ROUTER_HEARTBEAT_INTERVAL_MINUTES:-10} min | skills=${ROUTER_ENABLED_SKILL_COUNT:-0}/${ROUTER_SKILL_BUDGET:-6} | mode=${ROUTER_COST_MODE:-interactive}"
    echo ""
    echo "_Auto-routed by Hermes Dynamic Router at $(date -u +'%Y-%m-%d %H:%M:%S UTC')_"
}

profile_attribution() {
    local profile
    profile=$(normalize_profile "${1:-general}")
    local task="${2:-daily profile sweep}"
    local extra=""

    case "$profile" in
        legal) extra="Perplexity research, legal council, Claude aggregator" ;;
        trading) extra="market research, options council, risk aggregator" ;;
        security-research) extra="authorized security research, threat modeling, remediation" ;;
        cyberkimi-quarantine) extra="CyberKimi quarantine, defensive reports only, no autonomous tools" ;;
        solopreneur) extra="offer design, income generation, product launch" ;;
        marketing) extra="campaign strategy, claims review, web research" ;;
        direct) extra="direct-but-bounded policy, local execution, narrow safety boundaries" ;;
    esac

    print_attribution "$task" "$profile" "$extra"
}

print_usage() {
    echo "Usage:"
    echo "  source src/system/dynamic-router.sh --source"
    echo "  src/system/dynamic-router.sh --evaluate <query> [profile]"
    echo "  src/system/dynamic-router.sh --json <query> [profile]"
    echo "  src/system/dynamic-router.sh --attribution <query> [profile] [extra]"
    echo "  src/system/dynamic-router.sh --report [profile] [task]"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -euo pipefail
    case "${1:-}" in
        --evaluate|-e)
            hardwire_route "${2:-}" "${3:-general}"
            echo "Hermes Dynamic Router Evaluation"
            echo "Query: ${2:-}"
            echo "Profile: ${ROUTER_PROFILE}"
            echo "Intent: ${ROUTER_INTENT} (${ROUTER_INTENT_SCORE})"
            echo "Complexity: ${ROUTER_COMPLEXITY}"
            echo "Model: ${ROUTER_MODEL_NAME} (${ROUTER_MODEL})"
            echo "Provider: ${ROUTER_PROVIDER}"
            echo "Access: ${ROUTER_ACCESS_METHOD}"
            echo "Skills: ${ROUTER_SKILLS}"
            echo "Thinking: ${ROUTER_THINKING_LEVEL}" ;;
        --json|-j)
            print_json_route "${2:-}" "${3:-general}" ;;
        --attribution|-a)
            print_attribution "${2:-}" "${3:-general}" "${4:-}" ;;
        --report|-r)
            profile_attribution "${2:-general}" "${3:-daily profile sweep}" ;;
        --source)
            return 0 2>/dev/null || exit 0 ;;
        help|--help|-h|"")
            print_usage ;;
        *)
            echo "Unknown command: ${1}" >&2
            print_usage >&2
            exit 2 ;;
    esac
fi
