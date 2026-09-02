#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUTER="$ROOT_DIR/src/system/dynamic-router.sh"
SKILL_ROUTER="$ROOT_DIR/src/system/skill-router.sh"
OTEL_BRIDGE="$ROOT_DIR/src/system/otel-bridge.py"
TOOL_DISCOVERY="$ROOT_DIR/src/system/tool-discovery.py"
TOOL_REGISTRY="${HERMES_TOOL_REGISTRY:-$ROOT_DIR/config/tool-registry.json}"
CLOUD_SELECTION="${HERMES_CLOUD_MODEL_SELECTION_FILE:-$ROOT_DIR/.hermes/cloud-model-selection.env}"
CLOUD_KEYS="${HERMES_CLOUD_KEYS_FILE:-$ROOT_DIR/.env.cloud-models.local}"

PROFILE="direct"
PROJECT="${HERMES_PROJECT:-}"
MODE="report"
QUERY=""
OTEL_START_NS=""

usage() {
  cat <<'EOF'
Hermes Dispatch Front Door

Usage:
  src/system/hermes-dispatch.sh [options] <query>

Options:
  --profile <name>         Profile alias. Default: direct.
  --project <name>         Project overlay for dynamic skill selection.
  --thinking <level>       low|medium|high|critical|1|3|5|7 or explicit text.
  --model-key <key>        Router model key, e.g. nvidia-nim, zenmux-router.
  --model-id <id>          Provider model id, e.g. meta/llama-3.3-70b-instruct.
  --json                   Emit JSON route only.
  --report                 Emit dispatch report plus attribution footnote. Default.
  -h, --help               Show help.

Skills and eligible tool schemas are selected dynamically when their registries are available.
Tool discovery is descriptive only; execution still requires the normal Hermes governance boundary.
Cloud model selection is loaded from .hermes/cloud-model-selection.env when present.
EOF
}

normalize_thinking() {
  case "${1,,}" in
    low|1|"level 1") echo "Level 1 (Low)" ;;
    medium|med|3|"level 3") echo "Level 3 (Medium)" ;;
    high|5|"level 5") echo "Level 5 (High)" ;;
    critical|crit|7|"level 7") echo "Level 7 (Critical)" ;;
    *) echo "$1" ;;
  esac
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
  if [[ -f "$CLOUD_SELECTION" ]]; then
    # shellcheck disable=SC1090
    source "$CLOUD_SELECTION"
  fi
}

select_dynamic_skills() {
  [[ -x "$SKILL_ROUTER" ]] || return 0
  [[ -f "${HERMES_SKILLS_HOME:-$ROOT_DIR/.skills}/skills.txt" ]] || return 0

  local output names
  if [[ -n "$PROJECT" ]]; then
    output="$("$SKILL_ROUTER" project "$PROJECT" --limit "${HERMES_SKILL_LIMIT:-5}" "$QUERY" 2>/dev/null || true)"
  else
    output="$("$SKILL_ROUTER" find --limit "${HERMES_SKILL_LIMIT:-5}" "$QUERY" 2>/dev/null || true)"
  fi
  names="$(printf '%s\n' "$output" | awk '/score=/{print $1}' | paste -sd, -)"
  if [[ -n "$names" ]]; then
    export HERMES_SKILL_SET_OVERRIDE="$names"
    export HERMES_SKILL_SET_SOURCE="dynamic_skill_engine"
  fi
}

select_dynamic_tools() {
  [[ "${HERMES_TOOL_DISCOVERY_DISABLE:-0}" == "1" ]] && return 0
  [[ -f "$TOOL_DISCOVERY" && -f "$TOOL_REGISTRY" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  local args output names capability_csv capability
  args=(python3 "$TOOL_DISCOVERY" search --registry "$TOOL_REGISTRY" --query "$QUERY" --limit "${HERMES_TOOL_LIMIT:-5}" --data-class "${HERMES_SECURITY_CLASSIFICATION:-INTERNAL}")
  if [[ "${HERMES_ALLOW_MUTATING_TOOL_DISCOVERY:-0}" == "1" ]]; then
    args+=(--allow-mutating)
  fi
  capability_csv="${HERMES_AVAILABLE_CAPABILITIES:-}"
  if [[ -n "$capability_csv" ]]; then
    IFS=',' read -r -a _caps <<< "$capability_csv"
    for capability in "${_caps[@]}"; do
      capability="${capability//[[:space:]]/}"
      [[ -n "$capability" ]] && args+=(--capability "$capability")
    done
  fi
  if ! output="$("${args[@]}" 2>/dev/null)"; then
    [[ "${HERMES_TOOL_DISCOVERY_STRICT:-0}" == "1" ]] && return 1
    return 0
  fi
  names="$(python3 - "$output" <<'PY'
import json, sys
rows = json.loads(sys.argv[1])
if not isinstance(rows, list):
    raise SystemExit(2)
print(",".join(str(row["name"]) for row in rows if isinstance(row, dict) and row.get("name")))
PY
)" || {
    [[ "${HERMES_TOOL_DISCOVERY_STRICT:-0}" == "1" ]] && return 1
    return 0
  }
  if [[ -n "$names" ]]; then
    export HERMES_TOOL_SET_OVERRIDE="$names"
    export HERMES_TOOL_SET_SOURCE="progressive_tool_discovery"
  else
    unset HERMES_TOOL_SET_OVERRIDE HERMES_TOOL_SET_SOURCE || true
  fi
}

init_otel_trace() {
  [[ "${HERMES_OTEL_DISABLE:-0}" == "1" ]] && return 0
  [[ -f "$OTEL_BRIDGE" ]] || return 0
  local parent_trace parent_span context ids
  parent_trace="${HERMES_TRACE_ID:-}"
  parent_span="${HERMES_TRACE_SPAN_ID:-}"
  if ! context="$(python3 "$OTEL_BRIDGE" new --parent-trace-id "$parent_trace" 2>/dev/null)"; then
    return 1
  fi
  ids="$(python3 - "$context" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
print(value["trace_id"], value["span_id"])
PY
)" || return 1
  read -r HERMES_TRACE_ID HERMES_TRACE_SPAN_ID <<< "$ids"
  export HERMES_TRACE_ID HERMES_TRACE_SPAN_ID
  export HERMES_PARENT_SPAN_ID="$parent_span"
  OTEL_START_NS="$(python3 - <<'PY'
import time
print(time.time_ns())
PY
)"
}

emit_otel_dispatch() {
  local rc="$1"
  [[ "${HERMES_OTEL_DISABLE:-0}" == "1" ]] && return 0
  [[ -n "${HERMES_TRACE_ID:-}" && -n "${HERMES_TRACE_SPAN_ID:-}" && -n "$OTEL_START_NS" ]] || return 0
  [[ -f "$OTEL_BRIDGE" ]] || return 0
  local end_ns status attrs output_path
  end_ns="$(python3 - <<'PY'
import time
print(time.time_ns())
PY
)"
  if [[ "$rc" -eq 0 ]]; then status="OK"; else status="ERROR"; fi
  attrs="$(python3 - "$PROFILE" "$MODE" "$PROJECT" "${HERMES_SKILL_SET_OVERRIDE:-}" "${HERMES_TOOL_SET_OVERRIDE:-}" "${HERMES_MODEL_KEY_OVERRIDE:-${HERMES_SELECTED_MODEL_KEY:-}}" "${HERMES_MODEL_OVERRIDE:-${HERMES_SELECTED_MODEL_ID:-}}" "$rc" <<'PY'
import json, sys
profile, mode, project, skills, tools, model_key, model_id, rc = sys.argv[1:9]
print(json.dumps({
    "gen_ai.operation.name": "dispatch",
    "gen_ai.agent.name": profile,
    "hermes.dispatch.mode": mode,
    "hermes.project": project,
    "hermes.selected_skills": [item for item in skills.split(",") if item],
    "hermes.selected_tools": [item for item in tools.split(",") if item],
    "gen_ai.request.model": "/".join(part for part in (model_key, model_id) if part),
    "hermes.exit_code": int(rc),
}, sort_keys=True))
PY
)" || return 1
  output_path="${HERMES_OTEL_OUTPUT:-$ROOT_DIR/.hermes/telemetry/spans.jsonl}"
  python3 "$OTEL_BRIDGE" emit \
    --name "hermes.dispatch" --kind "agent" \
    --trace-id "$HERMES_TRACE_ID" --span-id "$HERMES_TRACE_SPAN_ID" \
    --parent-span-id "${HERMES_PARENT_SPAN_ID:-}" \
    --start-ns "$OTEL_START_NS" --end-ns "$end_ns" --status "$status" \
    --classification "${HERMES_SECURITY_CLASSIFICATION:-INTERNAL}" \
    --attributes-json "$attrs" --output "$output_path" >/dev/null
}

otel_on_exit() {
  local rc=$?
  trap - EXIT
  if ! emit_otel_dispatch "$rc"; then
    if [[ "${HERMES_OTEL_EXPORT_STRICT:-0}" == "1" ]]; then rc=1; fi
  fi
  exit "$rc"
}

record_memory_trajectory() {
  [[ "${HERMES_MEMORY_DISABLE:-0}" == "1" ]] && return 0
  local memory="$ROOT_DIR/src/system/memory-fabric.py"
  [[ -f "$memory" ]] || return 0
  local mode="$1" router_output="$2" envelope
  envelope="$(python3 - "$ROOT_DIR" "$QUERY" "$PROFILE" "$PROJECT" "$mode" "$router_output" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
root, query, profile, project, mode, router_output = sys.argv[1:7]
sys.path.insert(0, str(Path(root) / "src"))
from hermes_ultra.trajectory_metrics import TrajectoryEvaluator

skill_override = os.environ.get("HERMES_SKILL_SET_OVERRIDE", "")
tool_override = os.environ.get("HERMES_TOOL_SET_OVERRIDE", "")
selected_skills = [item for item in skill_override.split(",") if item]
selected_tools = [item for item in tool_override.split(",") if item]
model_key = os.environ.get("HERMES_MODEL_KEY_OVERRIDE") or os.environ.get("HERMES_SELECTED_MODEL_KEY") or ""
model_id = os.environ.get("HERMES_MODEL_OVERRIDE") or os.environ.get("HERMES_SELECTED_MODEL_ID") or ""
try:
    parsed = json.loads(router_output)
    model_key = model_key or str(parsed.get("model", ""))
    model_id = model_id or str(parsed.get("provider_model_id", ""))
    if not selected_skills:
        selected_skills = parsed.get("skills", []) if isinstance(parsed.get("skills"), list) else []
except Exception:
    parsed = {}

route_action = {"type": "route", "status": "success", "mode": mode, "project": project, "profile": profile, "selected_tools": selected_tools}
actions = [route_action]
raw_actions = os.environ.get("HERMES_TRAJECTORY_ACTIONS_JSON", "").strip()
if raw_actions:
    try:
        supplied = json.loads(raw_actions)
        if isinstance(supplied, list) and supplied:
            actions = supplied
    except json.JSONDecodeError:
        pass
trajectory_metrics = TrajectoryEvaluator().evaluate(actions).to_dict()

print(json.dumps({
    "producer": "hermes-dispatch",
    "objective": query,
    "input_hash": hashlib.sha256(query.encode()).hexdigest(),
    "selected_agent": profile,
    "selected_skills": selected_skills,
    "model": "/".join(part for part in [model_key, model_id] if part),
    "actions": actions,
    "predicted_outcome": "query routed to dynamic profile, selected skills, and eligible tool schemas",
    "observed_outcome": "dispatch output emitted",
    "status": "completed",
    "security_classification": "internal",
    "metadata": {
        "mode": mode,
        "project": project,
        "skill_source": os.environ.get("HERMES_SKILL_SET_SOURCE", ""),
        "selected_tools": selected_tools,
        "tool_source": os.environ.get("HERMES_TOOL_SET_SOURCE", ""),
        "router_output_hash": hashlib.sha256(router_output.encode()).hexdigest(),
        "parsed_router_output": parsed,
        "trace_id": os.environ.get("HERMES_TRACE_ID", ""),
        "span_id": os.environ.get("HERMES_TRACE_SPAN_ID", ""),
        "trajectory_metrics": trajectory_metrics,
        "adaptation_signal": trajectory_metrics["adaptation"],
    },
}, sort_keys=True))
PY
)"
  python3 "$memory" "ingest-trajectory" "--json" "$envelope" >/dev/null 2>&1 || true
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) [[ $# -ge 2 ]] || { echo "missing value for --profile" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    --project) [[ $# -ge 2 ]] || { echo "missing value for --project" >&2; exit 2; }; PROJECT="$2"; shift 2 ;;
    --thinking) [[ $# -ge 2 ]] || { echo "missing value for --thinking" >&2; exit 2; }; export HERMES_THINKING_LEVEL_OVERRIDE; HERMES_THINKING_LEVEL_OVERRIDE="$(normalize_thinking "$2")"; shift 2 ;;
    --model-key) [[ $# -ge 2 ]] || { echo "missing value for --model-key" >&2; exit 2; }; export HERMES_MODEL_KEY_OVERRIDE="$2"; shift 2 ;;
    --model-id) [[ $# -ge 2 ]] || { echo "missing value for --model-id" >&2; exit 2; }; export HERMES_MODEL_OVERRIDE="$2"; shift 2 ;;
    --json) MODE="json"; shift ;;
    --report) MODE="report"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *) QUERY="${QUERY:+$QUERY }$1"; shift ;;
  esac
done
if [[ $# -gt 0 ]]; then QUERY="${QUERY:+$QUERY }$*"; fi
[[ -n "$QUERY" ]] || { usage >&2; exit 2; }

load_local_env
if ! init_otel_trace; then
  if [[ "${HERMES_OTEL_EXPORT_STRICT:-0}" == "1" ]]; then echo "failed to initialize Hermes trace context" >&2; exit 2; fi
fi
if [[ -n "${HERMES_TRACE_ID:-}" ]]; then trap otel_on_exit EXIT; fi
select_dynamic_skills
if ! select_dynamic_tools; then
  echo "Hermes tool discovery failed under strict policy" >&2
  exit 2
fi

case "$MODE" in
  json)
    output="$("$ROUTER" --json "$QUERY" "$PROFILE")"
    record_memory_trajectory "json" "$output"
    printf '%s\n' "$output"
    ;;
  report)
    echo "Hermes Dispatch"
    echo "Query: $QUERY"
    echo "Profile: $PROFILE"
    output="$("$ROUTER" --attribution "$QUERY" "$PROFILE" "dynamic_skill_router, progressive_tool_discovery, cloud_model_picker, thinking_override")"
    record_memory_trajectory "report" "$output"
    printf '%s\n' "$output"
    ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
