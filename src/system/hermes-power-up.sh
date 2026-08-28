#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$ROOT_DIR/.hermes/power-up"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$LOG_DIR"

usage() {
  cat <<'EOF'
Hermes Max Power-Up

Usage:
  src/system/hermes-power-up.sh status
  src/system/hermes-power-up.sh verify
  src/system/hermes-power-up.sh refresh
  src/system/hermes-power-up.sh export [--include-logs]
  src/system/hermes-power-up.sh all [--include-logs]

What it does:
  status   Show model receipt, key status, core manifests, and enabled skills.
  verify   Run the strongest local verification suite.
  refresh  Sync provider model lists when keys are loaded, snapshot skills, run dashboard.
  export   Create a portable Hermes Max archive.
  all      Run status, refresh, verify, and export.
EOF
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

run_step() {
  log "== $* =="
  "$@"
}

status() {
  cd "$ROOT_DIR"
  log "Hermes Max status"
  python3 -m json.tool config/hermes-power-setup.json >/dev/null
  python3 -m json.tool config/cloud-model-catalog.json >/dev/null
  src/system/model.sh receipt || true
  echo
  src/system/model.sh keys || true
  echo
  src/system/jarvis-armory.sh status || true
  echo
  echo "enabled_skills=$(src/system/skills.sh count 2>/dev/null || echo unavailable)"
  echo "profiles=$(python3 - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("profiles/profile_manifest.json").read_text())
print(",".join(p["id"] for p in d.get("profiles", [])))
PY
)"
}

refresh() {
  cd "$ROOT_DIR"
  run_step src/system/model.sh sync all || true
  run_step src/system/gateway-watchdog.sh --required 9router,omniroute || true
  run_step src/system/jarvis-armory.sh status || true
  run_step src/system/continue-config.sh generate || true
  run_step src/system/external-source-sweep.sh run || true
  run_step src/system/trust-gate.sh status || true
  run_step src/system/anchor-evaluator.sh status || true
  run_step src/system/canary-controller.sh status || true
  run_step src/system/promptfoo-evals.sh check || true
  run_step src/system/skill-router-v3.sh snapshot || true
  run_step src/system/skill-router-v3.sh dashboard || true
  run_step src/system/daily-summary.sh || true
}

verify() {
  cd "$ROOT_DIR"
  local tests=(
    tests/test_cloud_model_picker.sh
    tests/test_model_quick_picker.sh
    tests/test_continue_config.sh
    tests/test_gateway_watchdog.sh
    tests/test_external_source_sweep.sh
    tests/test_skill_evolver_validation.sh
    tests/test_dynamic_skill_engine.sh
    tests/test_skill_router_v3.sh
    tests/test_external_skill_sources.sh
    tests/test_dynamic_router.sh
    tests/test_hermes_dispatch.sh
    tests/test_direct_mode_policy.sh
    tests/test_cost_audit.sh
    tests/test_bridge_client.sh
    tests/test_omniroute_integration.sh
    tests/test_ninerouter_integration.sh
    tests/test_jarvis_armory_integration.sh
    tests/test_promptfoo_evals.sh
    tests/test_obliteratus_runner.sh
    tests/test_restore_installer.sh
    tests/test_trust_gate.sh
    tests/test_memory_fabric.sh
    tests/test_memory_classification.sh
    tests/test_trajectory_fabric.sh
    tests/test_anchor_evaluator.sh
    tests/test_governed_graph_runtime.sh
    tests/test_canary_controller.sh
  )

  local test_file
  for test_file in "${tests[@]}"; do
    run_step bash "$test_file"
  done
}

export_build() {
  cd "$ROOT_DIR"
  if [[ "${1:-}" == "--include-logs" ]]; then
    run_step scripts/export-hermes-build.sh --include-logs
  else
    run_step scripts/export-hermes-build.sh
  fi
}

main() {
  local command="${1:-status}"
  shift || true

  local log_file="$LOG_DIR/${command}-${STAMP}.log"
  exec > >(tee -a "$log_file") 2>&1

  case "$command" in
    status) status "$@" ;;
    refresh) refresh "$@" ;;
    verify) verify "$@" ;;
    export) export_build "$@" ;;
    all)
      status
      refresh
      verify
      export_build "$@"
      ;;
    help|-h|--help) usage ;;
    *)
      echo "unknown command: $command" >&2
      usage >&2
      exit 2
      ;;
  esac

  log "log=$log_file"
}

main "$@"
