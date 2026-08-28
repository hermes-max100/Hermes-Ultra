#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PICKER="$ROOT_DIR/src/system/cloud-model-picker.sh"

usage() {
  cat <<'EOF'
Hermes Model Quick Picker

Usage:
  src/system/model.sh                 Open numbered picker menu
  src/system/model.sh list            List all models
  src/system/model.sh receipt         Show current model receipt
  src/system/model.sh keys            Show provider key status
  src/system/model.sh sync [provider] Sync provider model list

Quick selects:
  src/system/model.sh onith
  src/system/model.sh glm
  src/system/model.sh nvidia
  src/system/model.sh openrouter
  src/system/model.sh gemini
  src/system/model.sh perplexity
  src/system/model.sh venice
  src/system/model.sh zenmux
  src/system/model.sh omniroute
  src/system/model.sh omni
  src/system/model.sh omni-glm
  src/system/model.sh 9router
  src/system/model.sh nine-glm
  src/system/model.sh kimi3
  src/system/model.sh kimi
  src/system/model.sh kimi-code
  src/system/model.sh kimi3-openrouter
  src/system/model.sh yolo-approver
  src/system/model.sh yolo-env
EOF
}

select_model() {
  local provider="$1"
  local model="$2"
  "$PICKER" select "$provider" "$model"
  "$PICKER" receipt
}

menu() {
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN

  "$PICKER" list | awk '
    /^#/ { provider=$2; next }
    NF >= 3 { n += 1; provider_col=$1; model=$2; label=$3; print n "\t" provider_col "\t" model "\t" substr($0, index($0,$3)) }
  ' > "$tmp"

  if [[ ! -s "$tmp" ]]; then
    echo "no models found" >&2
    return 1
  fi

  echo "Hermes models:"
  awk -F '\t' '{printf "%3d) %-12s %-34s %s\n", $1, $2, $3, $4}' "$tmp"
  printf '\nPick number: '
  read -r choice
  [[ "$choice" =~ ^[0-9]+$ ]] || { echo "invalid choice" >&2; return 2; }

  local row provider model
  row="$(awk -F '\t' -v n="$choice" '$1 == n {print $0}' "$tmp")"
  [[ -n "$row" ]] || { echo "choice not found: $choice" >&2; return 2; }
  provider="$(printf '%s' "$row" | awk -F '\t' '{print $2}')"
  model="$(printf '%s' "$row" | awk -F '\t' '{print $3}')"
  select_model "$provider" "$model"
}

cmd="${1:-menu}"
case "$cmd" in
  onith|onith-1.0)
    select_model onith onith-1.0 ;;
  glm|glm-5.2)
    select_model nvidia glm-5.2 ;;
  nvidia)
    select_model nvidia glm-5.2 ;;
  openrouter)
    select_model openrouter openrouter/auto ;;
  gemini)
    select_model gemini gemini-3.5-pro ;;
  perplexity)
    select_model perplexity sonar-pro ;;
  venice)
    select_model venice venice/auto ;;
  zenmux)
    select_model zenmux auto ;;
  omniroute|omni)
    select_model omniroute auto ;;
  omni-glm|omniroute-glm|glm-omni|glm-omniroute)
    select_model omniroute nvidia/glm-5.2 ;;
  9router|nine|ninerouter)
    select_model 9router auto ;;
  nine-glm|9router-glm|glm-nine|glm-9router)
    select_model 9router nvidia/glm-5.2 ;;
  kimi3|kimi-k3|k3)
    select_model 9router moonshotai/kimi-k3 ;;
  kimi|kimi-latest)
    select_model 9router kimi/kimi-latest ;;
  kimi-code|kimi-coder|kimi3-code|kimi-k3-code)
    select_model 9router moonshotai/kimi-k3 ;;
  kimi27-code|kimi-k2.7-code)
    select_model 9router clinepass/cline-pass/kimi-k2.7-code ;;
  kimi3-openrouter|kimi-k3-openrouter|k3-openrouter)
    select_model openrouter moonshotai/kimi-k3 ;;
  yolo-approver|approver)
    "$ROOT_DIR/src/system/yolo-gate.sh" approver ;;
  yolo-env)
    "$ROOT_DIR/src/system/yolo-gate.sh" env ;;
  list)
    "$PICKER" list ;;
  receipt)
    "$PICKER" receipt ;;
  keys)
    "$PICKER" keys ;;
  sync)
    "$PICKER" sync "${2:-all}" ;;
  menu)
    menu ;;
  help|-h|--help)
    usage ;;
  *)
    echo "unknown model shortcut: $cmd" >&2
    usage >&2
    exit 2 ;;
esac
