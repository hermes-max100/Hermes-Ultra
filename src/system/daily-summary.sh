#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_DIR="${HERMES_REPORTS_DIR:-$ROOT_DIR/.hermes/reports}"
LOG_DIR="$ROOT_DIR/.hermes/logs"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-$REPORT_DIR/hermes-daily-summary-$STAMP.md}"

mkdir -p "$REPORT_DIR" "$LOG_DIR"

latest_file() {
  local pattern="$1"
  find "$REPORT_DIR" -maxdepth 1 -name "$pattern" -type f 2>/dev/null | sort | tail -1
}

append_command() {
  local title="$1"
  shift
  {
    printf '## %s\n\n' "$title"
    printf '```text\n'
    "$@" 2>&1 || true
    printf '```\n\n'
  } >> "$OUT"
}

{
  printf '# Hermes Daily Summary\n\n'
  printf 'Generated: %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT"

append_command "Model Receipt" "$ROOT_DIR/src/system/model.sh" receipt
append_command "Provider Keys" "$ROOT_DIR/src/system/model.sh" keys
append_command "Gateway Watchdog Dry Run" "$ROOT_DIR/src/system/gateway-watchdog.sh" --dry-run --required 9router,omniroute
append_command "Skill Dashboard" "$ROOT_DIR/src/system/skill-router-v3.sh" dashboard
append_command "External Source Sweep Status" "$ROOT_DIR/src/system/external-source-sweep.sh" status
append_command "Anchor Evaluator Status" "$ROOT_DIR/src/system/anchor-evaluator.sh" status
append_command "Canary Controller Status" "$ROOT_DIR/src/system/canary-controller.sh" status

{
  printf '## Latest Artifacts\n\n'
  latest_external="$(latest_file 'external-source-sweep-*.md')"
  latest_trending="$(latest_file 'github-trending-30d-*.md')"
  latest_anchor="$(find "$REPORT_DIR/anchor-evaluator" -maxdepth 1 -name '*.md' -type f 2>/dev/null | sort | tail -1)"
  latest_canary="$(find "$ROOT_DIR/.hermes/canary/reports" -maxdepth 1 -name 'rollback-*.json' -type f 2>/dev/null | sort | tail -1)"
  latest_summary="$(latest_file 'hermes-daily-summary-*.md')"
  printf -- '- Latest external source sweep: %s\n' "${latest_external:-none}"
  printf -- '- Latest GitHub trending scan: %s\n' "${latest_trending:-none}"
  printf -- '- Latest anchor evaluation: %s\n' "${latest_anchor:-none}"
  printf -- '- Latest canary rollback: %s\n' "${latest_canary:-none}"
  printf -- '- This summary: %s\n' "${latest_summary:-$OUT}"
  printf '\n'
  printf '## Pending External Proposals\n\n'
  find "$ROOT_DIR/.hermes/external-proposals" -maxdepth 2 -name README.md -type f 2>/dev/null | sort | tail -20 | sed 's/^/- /' || true
  printf '\n'
} >> "$OUT"

echo "daily_summary=$OUT"
