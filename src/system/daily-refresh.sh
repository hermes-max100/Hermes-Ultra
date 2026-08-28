#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$ROOT_DIR/.hermes/refresh"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ).log"

mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "Hermes daily refresh started: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
cd "$ROOT_DIR"

if [[ -d "$ROOT_DIR/OBLITERATUS/.git" ]]; then
  echo "== updating OBLITERATUS =="
  git -C "$ROOT_DIR/OBLITERATUS" fetch --prune origin || true
  git -C "$ROOT_DIR/OBLITERATUS" pull --ff-only || true
else
  echo "== OBLITERATUS has no .git directory; skipping repo pull =="
fi

if [[ -n "${BESTIARY_CATALOG:-}" ]]; then
  echo "== BESTIARY_CATALOG configured: $BESTIARY_CATALOG =="
else
  echo "== BESTIARY_CATALOG not configured; using local cloud-model-catalog.json =="
fi

echo "== validating catalogs =="
python3 -m json.tool "$ROOT_DIR/config/cloud-model-catalog.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/config/hermes-power-setup.json" >/dev/null
python3 -m json.tool "$ROOT_DIR/gateways/model_providers.json" >/dev/null

echo "== syncing configured provider models =="
"$ROOT_DIR/src/system/model.sh" sync all || true

echo "== checking gateways =="
"$ROOT_DIR/src/system/gateway-watchdog.sh" --required 9router,omniroute || true

echo "== checking JARVIS Tool Armory =="
"$ROOT_DIR/src/system/jarvis-armory.sh" status || true

echo "== generating Continue config =="
"$ROOT_DIR/src/system/continue-config.sh" generate || true

echo "== sweeping external sources =="
"$ROOT_DIR/src/system/external-source-sweep.sh" run || true

echo "== checking Promptfoo eval pack =="
"$ROOT_DIR/src/system/promptfoo-evals.sh" check || true

echo "== checking Trust Gate =="
"$ROOT_DIR/src/system/trust-gate.sh" status || true

echo "== checking Memory Fabric =="
"$ROOT_DIR/src/system/memory-fabric.sh" status || true

echo "== checking Anchor Evaluator =="
"$ROOT_DIR/src/system/anchor-evaluator.sh" status || true

echo "== checking Canary Controller =="
"$ROOT_DIR/src/system/canary-controller.sh" status || true

echo "== writing daily summary =="
"$ROOT_DIR/src/system/daily-summary.sh" || true

echo "== running router tests =="
bash "$ROOT_DIR/tests/test_cloud_model_picker.sh"
bash "$ROOT_DIR/tests/test_model_quick_picker.sh"
bash "$ROOT_DIR/tests/test_continue_config.sh"
bash "$ROOT_DIR/tests/test_gateway_watchdog.sh"
bash "$ROOT_DIR/tests/test_external_source_sweep.sh"
bash "$ROOT_DIR/tests/test_skill_evolver_validation.sh"
bash "$ROOT_DIR/tests/test_dynamic_skill_engine.sh"
bash "$ROOT_DIR/tests/test_skill_router_v3.sh"
bash "$ROOT_DIR/tests/test_external_skill_sources.sh"
bash "$ROOT_DIR/tests/test_restore_installer.sh"
bash "$ROOT_DIR/tests/test_dynamic_router.sh"
bash "$ROOT_DIR/tests/test_hermes_dispatch.sh"
bash "$ROOT_DIR/tests/test_direct_mode_policy.sh"
bash "$ROOT_DIR/tests/test_cost_audit.sh"
bash "$ROOT_DIR/tests/test_bridge_client.sh"
bash "$ROOT_DIR/tests/test_omniroute_integration.sh"
bash "$ROOT_DIR/tests/test_ninerouter_integration.sh"
bash "$ROOT_DIR/tests/test_jarvis_armory_integration.sh"
bash "$ROOT_DIR/tests/test_promptfoo_evals.sh"
bash "$ROOT_DIR/tests/test_obliteratus_runner.sh"
bash "$ROOT_DIR/tests/test_trust_gate.sh"
bash "$ROOT_DIR/tests/test_memory_fabric.sh"
bash "$ROOT_DIR/tests/test_memory_classification.sh"
bash "$ROOT_DIR/tests/test_trajectory_fabric.sh"
bash "$ROOT_DIR/tests/test_anchor_evaluator.sh"
bash "$ROOT_DIR/tests/test_canary_controller.sh"

echo "Hermes daily refresh complete: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
echo "log=$LOG_FILE"
