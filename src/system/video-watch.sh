#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_DIR="${HERMES_VIDEO_REPORT_DIR:-$ROOT_DIR/.hermes/reports/video-watch}"
VENV_DIR="${HERMES_VIDEO_VENV_DIR:-$ROOT_DIR/.hermes/venvs/video-watch}"
BIN_DIR="$VENV_DIR/bin"
YTDLP="$BIN_DIR/yt-dlp"
UNDERSTAND="$ROOT_DIR/.agents/skills/video-understand/scripts/understand_video.py"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"

usage() {
  cat <<'EOF'
Hermes Video Watch

Usage:
  src/system/video-watch.sh install [--with-whisper] [--with-ocr]
  src/system/video-watch.sh doctor
  src/system/video-watch.sh metadata <url>
  src/system/video-watch.sh download <url>
  src/system/video-watch.sh understand <url-or-file> [--frames N] [--mode scene|keyframe|interval] [--no-transcribe] [--whisper-model tiny|base|small|medium|large] [--ocr]
  src/system/video-watch.sh blueprint <url-or-file> [--frames N] [--mode scene|keyframe|interval] [--no-transcribe] [--whisper-model tiny|base|small|medium|large] [--ocr]

Behavior:
  - Supports public URLs handled by yt-dlp and local video files.
  - Writes local artifacts only under .hermes/reports/video-watch.
  - Does not post, message, upload, delete, reuse cookies, bypass paywalls, or
    use private browser profiles.
  - OCR reads extracted frame text with local tesseract when enabled.
EOF
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

record_memory_trajectory() {
  [[ "${HERMES_MEMORY_DISABLE:-0}" == "1" ]] && return 0
  local memory="$ROOT_DIR/src/system/memory-fabric.py"
  [[ -f "$memory" ]] || return 0
  local objective="$1" status="$2" artifact="$3" observed="$4"
  local envelope
  envelope="$(python3 - "$objective" "$status" "$artifact" "$observed" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

objective, status, artifact, observed = sys.argv[1:5]
path = Path(artifact)
if path.is_file():
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = [{"type": "video-watch-artifact", "path": str(path), "sha256": digest}]
elif path.exists():
    digest = hashlib.sha256(str(path).encode()).hexdigest()
    evidence = [{"type": "video-watch-artifact-dir", "path": str(path)}]
else:
    digest = hashlib.sha256(artifact.encode()).hexdigest()
    evidence = []

print(json.dumps({
    "producer": "video-watch",
    "objective": objective,
    "input_hash": digest,
    "selected_agent": "video-watch",
    "actions": [{"type": objective, "artifact": artifact}],
    "predicted_outcome": "local video artifact generated for review",
    "observed_outcome": observed,
    "status": status,
    "evidence_refs": evidence,
    "security_classification": "internal",
    "metadata": {"artifact": artifact},
}, sort_keys=True))
PY
)"
  python3 "$memory" "ingest-trajectory" "--json" "$envelope" >/dev/null 2>&1 || true
}

is_url() {
  case "$1" in
    http://*|https://*) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_dirs() {
  mkdir -p "$REPORT_DIR" "$VENV_DIR"
}

cmd_install() {
  ensure_dirs
  command -v python3 >/dev/null 2>&1 || die "python3 is required"
  local with_whisper="false" with_ocr="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-whisper) with_whisper="true"; shift ;;
      --with-ocr) with_ocr="true"; shift ;;
      *) die "unknown install option: $1" ;;
    esac
  done
  if [[ ! -d "$VENV_DIR/bin" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  "$BIN_DIR/python" -m pip install --upgrade pip setuptools wheel
  "$BIN_DIR/python" -m pip install --upgrade yt-dlp
  if [[ "$with_whisper" == "true" ]]; then
    "$BIN_DIR/python" -m pip install --upgrade openai-whisper
  fi
  if [[ "$with_ocr" == "true" && ! -x "$(command -v tesseract || true)" ]]; then
    if command -v apt-get >/dev/null 2>&1 && [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      DEBIAN_FRONTEND=noninteractive apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y tesseract-ocr
    else
      log "tesseract not installed; install tesseract-ocr with your OS package manager for --ocr"
    fi
  fi
  log "video-watch Python tools installed in $VENV_DIR"
}

ensure_ytdlp() {
  if [[ ! -x "$YTDLP" ]]; then
    cmd_install
  fi
}

cmd_doctor() {
  ensure_dirs
  printf 'report_dir=%s\n' "$REPORT_DIR"
  printf 'venv=%s\n' "$VENV_DIR"
  if [[ -x "$YTDLP" ]]; then
    printf 'yt_dlp=installed\n'
    "$YTDLP" --version 2>/dev/null | sed 's/^/yt_dlp_version=/'
  elif command -v yt-dlp >/dev/null 2>&1; then
    printf 'yt_dlp=system\n'
    yt-dlp --version 2>/dev/null | sed 's/^/yt_dlp_version=/'
  else
    printf 'yt_dlp=missing\n'
  fi
  command -v ffmpeg >/dev/null 2>&1 && printf 'ffmpeg=installed\n' || printf 'ffmpeg=missing\n'
  command -v ffprobe >/dev/null 2>&1 && printf 'ffprobe=installed\n' || printf 'ffprobe=missing\n'
  if command -v tesseract >/dev/null 2>&1; then
    printf 'tesseract=installed\n'
    tesseract --version 2>/dev/null | head -1 | sed 's/^/tesseract_version=/'
  else
    printf 'tesseract=missing\n'
  fi
  local py="python3"
  [[ -x "$BIN_DIR/python" ]] && py="$BIN_DIR/python"
  "$py" - <<'PY' 2>/dev/null || true
try:
    import whisper
    print("whisper=installed")
except Exception:
    print("whisper=missing")
PY
}

cmd_metadata() {
  [[ $# -eq 1 ]] || die "metadata requires <url>"
  is_url "$1" || die "metadata requires an http(s) URL"
  ensure_ytdlp
  local out
  out="$REPORT_DIR/metadata-$STAMP.json"
  "$YTDLP" --dump-json --no-download --no-playlist "$1" > "$out"
  record_memory_trajectory "video-metadata" "completed" "$out" "metadata written"
  printf 'metadata=%s\n' "$out"
}

cmd_download() {
  [[ $# -eq 1 ]] || die "download requires <url>"
  is_url "$1" || die "download requires an http(s) URL"
  ensure_ytdlp
  local run_dir out_template
  run_dir="$REPORT_DIR/download-$STAMP"
  mkdir -p "$run_dir"
  out_template="$run_dir/%(title).180B-%(id)s.%(ext)s"
  "$YTDLP" \
    --no-playlist \
    --write-subs \
    --write-auto-subs \
    --sub-langs "en.*" \
    --merge-output-format mp4 \
    -f "bestvideo[height<=720]+bestaudio/best[height<=720]/best" \
    -o "$out_template" \
    "$1"
  record_memory_trajectory "video-download" "completed" "$run_dir" "download artifacts written"
  printf 'download_dir=%s\n' "$run_dir"
  find "$run_dir" -maxdepth 1 -type f | sort
}

resolve_video() {
  local input="$1"
  if is_url "$input"; then
    cmd_download "$input" | awk -F= '$1=="download_dir"{print $2}' | tail -1 | {
      read -r run_dir
      find "$run_dir" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.mkv' -o -name '*.webm' -o -name '*.mov' \) | sort | head -1
    }
  else
    [[ -f "$input" ]] || die "video file missing: $input"
    printf '%s\n' "$input"
  fi
}

enrich_analysis_ocr() {
  local analysis="$1"
  command -v tesseract >/dev/null 2>&1 || die "tesseract is required for --ocr"
  python3 - "$analysis" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

analysis_path = Path(sys.argv[1])
data = json.loads(analysis_path.read_text(encoding="utf-8"))
items = []

for frame in data.get("frames", []):
    path = frame.get("path", "")
    if not path or not Path(path).is_file():
        continue
    proc = subprocess.run(
        ["tesseract", path, "stdout", "--psm", "6"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    text = re.sub(r"\s+", " ", proc.stdout or "").strip()
    if not text:
        continue
    item = {
        "timestamp": frame.get("timestamp"),
        "timestamp_formatted": frame.get("timestamp_formatted", ""),
        "path": path,
        "text": text,
    }
    frame["ocr_text"] = text
    items.append(item)

data["frame_ocr"] = items
data["frame_ocr_text"] = "\n".join(
    f"[{item.get('timestamp_formatted', '')}] {item.get('text', '')}"
    for item in items
)
notes = data.get("notes", [])
if not isinstance(notes, list):
    notes = [str(notes)]
notes.append(f"OCR extracted text from {len(items)} frame(s) using local tesseract.")
data["notes"] = notes
analysis_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

cmd_understand() {
  [[ $# -ge 1 ]] || die "understand requires <url-or-file>"
  [[ -f "$UNDERSTAND" ]] || die "video-understand script missing: $UNDERSTAND"
  command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg is required for frame extraction"
  command -v ffprobe >/dev/null 2>&1 || die "ffprobe is required for video metadata"

  local input="$1"; shift
  local frames=30 mode="scene" transcribe="true" ocr="false" whisper_model="base"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --frames) frames="$2"; shift 2 ;;
      --mode) mode="$2"; shift 2 ;;
      --no-transcribe) transcribe="false"; shift ;;
      --whisper-model) whisper_model="$2"; shift 2 ;;
      --ocr) ocr="true"; shift ;;
      *) die "unknown understand option: $1" ;;
    esac
  done

  local video out py args=()
  video="$(resolve_video "$input")"
  out="$REPORT_DIR/understand-$STAMP.json"
  py="python3"
  [[ -x "$BIN_DIR/python" ]] && py="$BIN_DIR/python"
  args=("$py" "$UNDERSTAND" "$video" --max-frames "$frames" --mode "$mode" --whisper-model "$whisper_model" --output "$out" --quiet)
  [[ "$transcribe" == "false" ]] && args+=(--no-transcribe)
  "${args[@]}"
  [[ "$ocr" == "true" ]] && enrich_analysis_ocr "$out"
  record_memory_trajectory "video-understand" "completed" "$out" "analysis artifact written"
  printf 'analysis=%s\n' "$out"
}

cmd_blueprint() {
  [[ $# -ge 1 ]] || die "blueprint requires <url-or-file>"
  local analysis out
  analysis="$(cmd_understand "$@" | awk -F= '$1=="analysis"{print $2}' | tail -1)"
  out="$REPORT_DIR/blueprint-$STAMP.md"
  python3 - "$analysis" "$out" <<'PY'
import json
import sys
from pathlib import Path

analysis_path = Path(sys.argv[1])
out = Path(sys.argv[2])
data = json.loads(analysis_path.read_text(encoding="utf-8"))

title = Path(data.get("video", "video")).name
duration = data.get("duration", 0)
resolution = data.get("resolution", {})
frames = data.get("frames", [])
text = str(data.get("text") or "").strip()
ocr_text = str(data.get("frame_ocr_text") or "").strip()

lines = [
    f"# Video Reverse-Engineering Blueprint",
    "",
    f"Source video: `{title}`",
    f"Duration: {duration} seconds",
    f"Resolution: {resolution.get('width', 0)}x{resolution.get('height', 0)}",
    f"Frames extracted: {len(frames)}",
    "",
    "## Transcript Summary Input",
    "",
    text[:4000] if text else "No transcript available. Use extracted frames for visual review.",
    "",
    "## On-Screen Text OCR",
    "",
    ocr_text[:4000] if ocr_text else "No OCR text available.",
    "",
    "## Frame Review Queue",
    "",
]
for frame in frames:
    lines.append(f"- `{frame.get('timestamp_formatted', '')}`: {frame.get('path', '')}")

lines.extend([
    "",
    "## Implementation Extraction Checklist",
    "",
    "- Identify the promised outcome.",
    "- Identify tools, commands, services, or repositories shown.",
    "- Extract setup order.",
    "- Extract failure points and hidden prerequisites.",
    "- Convert the workflow into a Hermes skill, script, or playbook.",
    "- Keep outputs local until human approval.",
])
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"blueprint={out}")
PY
  record_memory_trajectory "video-blueprint" "completed" "$out" "blueprint artifact written"
}

main() {
  local cmd="${1:-help}"
  [[ $# -gt 0 ]] && shift
  case "$cmd" in
    install) cmd_install "$@" ;;
    doctor) cmd_doctor ;;
    metadata) cmd_metadata "$@" ;;
    download) cmd_download "$@" ;;
    understand) cmd_understand "$@" ;;
    blueprint) cmd_blueprint "$@" ;;
    help|-h|--help) usage ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
