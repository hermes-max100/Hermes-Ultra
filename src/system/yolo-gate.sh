#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLOUD_KEYS="${HERMES_CLOUD_KEYS_FILE:-$ROOT_DIR/.env.cloud-models.local}"
POLICY_FILE="${HERMES_YOLO_GATE_POLICY:-$ROOT_DIR/config/yolo-gate-policy.json}"

usage() {
  cat <<'EOF'
Hermes YOLO Retrieval Gate

Usage:
  src/system/yolo-gate.sh classify <action text>
  src/system/yolo-gate.sh approver
  src/system/yolo-gate.sh check <action text>
  src/system/yolo-gate.sh env

Meaning:
  HERMES_YOLO_MODE=off       Human approval for all gates. Default.
  HERMES_YOLO_MODE=retrieval Highest-quality configured LLM may approve retrieval/research gates.

Optional approver chain:
  export HERMES_YOLO_APPROVER_CHAIN="9router:openai/sol-5.6,9router:fable/fable-5,9router:moonshotai/kimi-k3,nvidia:glm-5.2"

The chain accepts provider:model-id entries. Custom model IDs are allowed when
your selected gateway exposes them.
EOF
}

load_local_env() {
  if [[ -f "$CLOUD_KEYS" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
      name="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      [[ -n "${!name:-}" ]] && continue
      eval "export ${name}=${value}"
    done < "$CLOUD_KEYS"
  fi
}

provider_key_env() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    gemini) echo "GEMINI_API_KEY" ;;
    perplexity) echo "PERPLEXITY_API_KEY" ;;
    openrouter) echo "OPENROUTER_API_KEY" ;;
    venice) echo "VENICE_API_KEY" ;;
    nvidia) echo "NVIDIA_API_KEY" ;;
    adverserial) echo "ADVERSERIAL_API_KEY" ;;
    zenmux) echo "ZENMUX_API_KEY" ;;
    omniroute) echo "OMNIROUTE_API_KEY" ;;
    9router) echo "NINEROUTER_API_KEY" ;;
    onith|local) echo "" ;;
    *) echo "${1^^}_API_KEY" | tr '-' '_' ;;
  esac
}

provider_router_model() {
  case "$1" in
    openai) echo "openai-reasoning" ;;
    gemini) echo "gemini-pro" ;;
    perplexity) echo "perplexity-research" ;;
    openrouter) echo "openai-reasoning" ;;
    venice) echo "venice-creative" ;;
    nvidia) echo "nvidia-nim" ;;
    adverserial) echo "cyberkimi-quarantine" ;;
    zenmux) echo "zenmux-router" ;;
    omniroute) echo "omniroute-gateway" ;;
    9router) echo "ninerouter-gateway" ;;
    onith|local) echo "local-private" ;;
    *) echo "${HERMES_YOLO_CUSTOM_ROUTER_MODEL:-ninerouter-gateway}" ;;
  esac
}

default_chain() {
  python3 - "$POLICY_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {}
print(",".join(data.get("default_approver_chain", [
    "9router:moonshotai/kimi-k3",
    "9router:kimi/kimi-latest",
    "omniroute:nvidia/glm-5.2",
    "nvidia:glm-5.2",
    "openrouter:moonshotai/kimi-k3",
    "onith:onith-1.0",
])))
PY
}

classify_action() {
  ACTION_TEXT="$*" python3 <<'PY'
import os
import re

text = os.environ.get("ACTION_TEXT", "").lower()

hard_block = [
    r"credential theft", r"stealth", r"exfiltrat", r"unauthorized persistence",
    r"public target scan", r"exploit module", r"bypass access control",
]
human = [
    r"\bsend\b", r"\bpost\b", r"\binvite\b", r"\bdelete\b", r"\bpurchase\b",
    r"\bpay\b", r"credential", r"password", r"one[- ]time code", r"\botp\b",
    r"terminate .*session", r"privacy setting", r"security setting",
    r"grant .*permission", r"install .*app", r"remove .*app",
    r"destructive", r"browser profile", r"private index", r"exploit",
    r"public target", r"change account", r"irreversible",
]
retrieval = [
    r"retriev", r"research", r"search", r"look up", r"source", r"cite",
    r"github", r"reddit", r"\bx\b", r"twitter", r"thread", r"arxiv",
    r"skill hub", r"skills\.sh", r"scan.*repo", r"sweep", r"discover",
    r"candidate skill", r"current", r"latest", r"web", r"docs",
    r"instagram", r"reel", r"youtube", r"youtu\.be", r"video",
    r"tiktok", r"transcript", r"frame extraction", r"yt-dlp",
]
draft = [
    r"draft", r"report", r"summar", r"classif", r"score", r"rank",
    r"package", r"proposal", r"one-pager", r"landing page copy",
]

def any_match(patterns):
    return any(re.search(pattern, text) for pattern in patterns)

if any_match(hard_block):
    print("hard_block")
elif any_match(human):
    print("human_required")
elif any_match(retrieval):
    print("public_retrieval_gate")
elif any_match(draft):
    print("draft_generation_gate")
else:
    print("low_risk_gate")
PY
}

select_approver() {
  load_local_env
  local chain="${HERMES_YOLO_APPROVER_CHAIN:-$(default_chain)}"
  local entry provider model key_env
  IFS=',' read -r -a entries <<< "$chain"
  for entry in "${entries[@]}"; do
    entry="${entry#"${entry%%[![:space:]]*}"}"
    entry="${entry%"${entry##*[![:space:]]}"}"
    [[ "$entry" == *:* ]] || continue
    provider="${entry%%:*}"
    model="${entry#*:}"
    key_env="$(provider_key_env "$provider")"
    if [[ -z "$key_env" || -n "${!key_env:-}" ]]; then
      printf 'provider=%s\n' "$provider"
      printf 'model=%s\n' "$model"
      printf 'router_model=%s\n' "$(provider_router_model "$provider")"
      printf 'api_key_env=%s\n' "${key_env:-none}"
      printf 'api_key_status=%s\n' "$([[ -z "$key_env" ]] && echo not_required || echo loaded)"
      return 0
    fi
  done
  return 1
}

check_gate() {
  local action_text="$*"
  local class mode approver
  class="$(classify_action "$action_text")"
  mode="${HERMES_YOLO_MODE:-off}"

  case "$class" in
    hard_block)
      printf 'decision=blocked\nclass=%s\nreason=hard_block_policy\n' "$class"
      return 0 ;;
    human_required)
      printf 'decision=human_required\nclass=%s\nreason=irreversible_or_sensitive_action\n' "$class"
      return 0 ;;
  esac

  if [[ "$mode" == "retrieval" || "$mode" == "yolo" ]]; then
    if approver="$(select_approver)"; then
      printf 'decision=model_approved\nclass=%s\nmode=%s\n' "$class" "$mode"
      printf '%s\n' "$approver"
      return 0
    fi
    printf 'decision=human_required\nclass=%s\nmode=%s\nreason=no_configured_approver_model\n' "$class" "$mode"
    return 0
  fi

  printf 'decision=human_required\nclass=%s\nmode=%s\nreason=yolo_mode_off\n' "$class" "$mode"
}

emit_env() {
  local approver provider model router_model
  approver="$(select_approver)" || {
    echo "no configured approver model found" >&2
    return 1
  }
  provider="$(printf '%s\n' "$approver" | awk -F= '$1=="provider"{print $2}')"
  model="$(printf '%s\n' "$approver" | awk -F= '$1=="model"{print $2}')"
  router_model="$(printf '%s\n' "$approver" | awk -F= '$1=="router_model"{print $2}')"
  printf 'export HERMES_YOLO_MODE=%q\n' "retrieval"
  printf 'export HERMES_PROVIDER_OVERRIDE=%q\n' "$provider"
  printf 'export HERMES_MODEL_KEY_OVERRIDE=%q\n' "$router_model"
  printf 'export HERMES_MODEL_OVERRIDE=%q\n' "$model"
}

cmd="${1:-}"
shift || true
case "$cmd" in
  classify)
    classify_action "$@" ;;
  approver)
    select_approver ;;
  check)
    check_gate "$@" ;;
  env)
    emit_env ;;
  help|-h|--help|"")
    usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2 ;;
esac
