#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OBLITERATUS_DIR="${HERMES_OBLITERATUS_DIR:-$ROOT_DIR/OBLITERATUS}"
OBLITERATUS_BIN="${HERMES_OBLITERATUS_BIN:-$OBLITERATUS_DIR/.venv/bin/obliteratus}"
PYTHON_BIN="${HERMES_OBLITERATUS_PYTHON:-$OBLITERATUS_DIR/.venv/bin/python}"
UI_SERVER="$ROOT_DIR/src/system/obliteratus_ui_server.py"
RUN_DIR="${HERMES_OBLITERATUS_RUN_DIR:-$ROOT_DIR/.hermes/obliteratus}"
PID_FILE="$RUN_DIR/ui.pid"
LOG_FILE="$RUN_DIR/ui.log"

ALLOW_MODEL_EDIT=0
ALLOW_DOWNLOAD=0

usage() {
    cat <<'EOF'
Hermes OBLITERATUS Runner

Usage:
  src/system/obliteratus-runner.sh [flags] <command> [args...]

Flags:
  --allow-download      Permit commands that may download model files.
  --allow-model-edit    Permit ablation/model-editing commands.
  -h, --help            Show this help.

Safe commands:
  status                Show configured paths and install status.
  doctor                Import-check Python dependencies and pip consistency.
  help                  Show OBLITERATUS CLI help.
  models [args...]      List curated models.
  presets               List presets.
  strategies            List available strategies.
  gpu-calc [args...]    Estimate GPU requirements.
  test-smoke            Run lightweight import/config tests.
  ui-command [args...]  Print the local-only UI launch command.
  ui-start [args...]    Start local UI in the background on 127.0.0.1.
  ui-stop               Stop the background UI started by this wrapper.

Guarded commands:
  info                  Requires --allow-download.
  run, obliterate, abliterate, self-improve, tourney
                        Require --allow-model-edit.

Notes:
  - The wrapper refuses Gradio --share links.
  - ui-start defaults to --host 127.0.0.1 --port 7860 --no-browser.
  - This wrapper never reuses browser sessions or provider credentials.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

ensure_installed() {
    [[ -d "$OBLITERATUS_DIR" ]] || die "OBLITERATUS_DIR not found: $OBLITERATUS_DIR"
    [[ -x "$OBLITERATUS_BIN" ]] || die "obliteratus CLI not executable: $OBLITERATUS_BIN"
    [[ -x "$PYTHON_BIN" ]] || die "Python venv not executable: $PYTHON_BIN"
    [[ -f "$UI_SERVER" ]] || die "UI server shim not found: $UI_SERVER"
}

is_model_edit_command() {
    case "${1:-}" in
        run|obliterate|abliterate|self-improve|tourney) return 0 ;;
        *) return 1 ;;
    esac
}

refuses_share() {
    local arg
    for arg in "$@"; do
        [[ "$arg" == "--share" ]] && return 0
    done
    return 1
}

status() {
    local installed="false"
    local venv="false"
    local version="unavailable"

    [[ -d "$OBLITERATUS_DIR" ]] && installed="true"
    [[ -x "$OBLITERATUS_BIN" && -x "$PYTHON_BIN" ]] && venv="true"
    if [[ "$venv" == "true" ]]; then
        version="$("$PYTHON_BIN" - <<'PY'
import importlib.metadata
try:
    print(importlib.metadata.version("obliteratus"))
except importlib.metadata.PackageNotFoundError:
    print("unknown")
PY
)"
    fi

    cat <<EOF
obliteratus_dir=$OBLITERATUS_DIR
obliteratus_bin=$OBLITERATUS_BIN
python_bin=$PYTHON_BIN
installed=$installed
venv_ready=$venv
package_version=$version
ui_pid_file=$PID_FILE
ui_log_file=$LOG_FILE
EOF
}

doctor() {
    ensure_installed
    "$PYTHON_BIN" - <<'PY'
import obliteratus
import torch
import transformers
import datasets
import accelerate
import gradio

print("obliteratus import ok")
print(f"torch={torch.__version__}")
print(f"cuda_available={torch.cuda.is_available()}")
print(f"transformers={transformers.__version__}")
print(f"datasets={datasets.__version__}")
print(f"accelerate={accelerate.__version__}")
print(f"gradio={gradio.__version__}")
PY
    "$PYTHON_BIN" -m pip check
}

run_cli() {
    ensure_installed
    export HF_HUB_DISABLE_TELEMETRY="${HF_HUB_DISABLE_TELEMETRY:-1}"
    export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"
    (cd "$OBLITERATUS_DIR" && "$OBLITERATUS_BIN" "$@")
}

ui_args() {
    local host="127.0.0.1"
    local port="7860"
    local auth=""
    local passthrough=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --host)
                [[ $# -ge 2 ]] || die "--host requires a value"
                host="$2"
                shift 2
                ;;
            --port)
                [[ $# -ge 2 ]] || die "--port requires a value"
                port="$2"
                shift 2
                ;;
            --auth)
                [[ $# -ge 2 ]] || die "--auth requires a value"
                auth="$2"
                shift 2
                ;;
            --share)
                die "Gradio --share is disabled for Hermes local runs"
                ;;
            --)
                shift
                ;;
            *)
                passthrough+=("$1")
                shift
                ;;
        esac
    done

    UI_HOST="$host"
    UI_PORT="$port"
    UI_AUTH="$auth"
    UI_PASSTHROUGH=("${passthrough[@]}")
}

ui_command() {
    ensure_installed
    ui_args "$@"
    printf '%q ' "$PYTHON_BIN" "$UI_SERVER" --project-root "$OBLITERATUS_DIR" --host "$UI_HOST" --port "$UI_PORT" --quiet
    if [[ -n "$UI_AUTH" ]]; then
        printf '%q ' --auth "$UI_AUTH"
    fi
    if [[ ${#UI_PASSTHROUGH[@]} -gt 0 ]]; then
        printf '%q ' "${UI_PASSTHROUGH[@]}"
    fi
    printf '\n'
}

ui_start() {
    ensure_installed
    ui_args "$@"
    mkdir -p "$RUN_DIR"

    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "ui already running: pid=$(cat "$PID_FILE") url=http://$UI_HOST:$UI_PORT"
        return 0
    fi

    local cmd=("$PYTHON_BIN" "$UI_SERVER" --project-root "$OBLITERATUS_DIR" --host "$UI_HOST" --port "$UI_PORT" --quiet)
    if [[ -n "$UI_AUTH" ]]; then
        cmd+=(--auth "$UI_AUTH")
    fi
    if [[ ${#UI_PASSTHROUGH[@]} -gt 0 ]]; then
        cmd+=("${UI_PASSTHROUGH[@]}")
    fi

    (
        cd "$OBLITERATUS_DIR"
        if command -v setsid >/dev/null 2>&1; then
            PYTHONUNBUFFERED=1 nohup setsid "${cmd[@]}" </dev/null >"$LOG_FILE" 2>&1 &
        else
            PYTHONUNBUFFERED=1 nohup "${cmd[@]}" </dev/null >"$LOG_FILE" 2>&1 &
        fi
        echo "$!" >"$PID_FILE"
    )

    local pid
    pid="$(cat "$PID_FILE")"
    local timeout="${HERMES_OBLITERATUS_UI_START_TIMEOUT:-75}"
    local started=0

    for _ in $(seq 1 "$timeout"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            die "UI failed to start; see $LOG_FILE"
        fi
        if "$PYTHON_BIN" - "$UI_HOST" "$UI_PORT" <<'PY' >/dev/null 2>&1; then
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}", timeout=1) as response:
    raise SystemExit(0 if response.status < 500 else 1)
PY
            started=1
            break
        fi
        sleep 1
    done

    if [[ "$started" != "1" ]]; then
        die "UI process is running but did not answer HTTP within ${timeout}s; see $LOG_FILE"
    fi

    echo "ui started: pid=$pid url=http://$UI_HOST:$UI_PORT log=$LOG_FILE"
}

ui_stop() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "ui not running"
        return 0
    fi

    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "ui stopped: pid=$pid"
    else
        echo "stale pid removed: pid=$pid"
    fi
    rm -f "$PID_FILE"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-model-edit)
            ALLOW_MODEL_EDIT=1
            shift
            ;;
        --allow-download)
            ALLOW_DOWNLOAD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            die "unknown global flag: $1"
            ;;
        *)
            break
            ;;
    esac
done

COMMAND="${1:-}"
[[ -n "$COMMAND" ]] || { usage; exit 0; }
shift || true

case "$COMMAND" in
    status) status ;;
    doctor) doctor ;;
    help) run_cli --help ;;
    models|presets|strategies|gpu-calc) run_cli "$COMMAND" "$@" ;;
    test-smoke)
        ensure_installed
        (cd "$OBLITERATUS_DIR" && "$PYTHON_BIN" -m pytest tests/test_config.py tests/test_module_imports.py -q)
        ;;
    ui-command) ui_command "$@" ;;
    ui-start) ui_start "$@" ;;
    ui-stop) ui_stop ;;
    info)
        [[ "$ALLOW_DOWNLOAD" == "1" ]] || die "info may download model files; rerun with --allow-download"
        run_cli "$COMMAND" "$@"
        ;;
    *)
        if is_model_edit_command "$COMMAND"; then
            [[ "$ALLOW_MODEL_EDIT" == "1" ]] || die "$COMMAND is model-editing; rerun with --allow-model-edit"
            refuses_share "$@" && die "public share links are disabled"
            run_cli "$COMMAND" "$@"
        else
            die "unsupported command: $COMMAND"
        fi
        ;;
esac
