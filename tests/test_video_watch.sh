#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVER="$ROOT_DIR/src/system/video-watch.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_VIDEO_REPORT_DIR="$TMP_DIR/reports"
export HERMES_VIDEO_VENV_DIR="$TMP_DIR/venv"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

chmod +x "$DRIVER"
bash -n "$DRIVER"

help_output="$("$DRIVER" --help)"
assert_contains "$help_output" "metadata"
assert_contains "$help_output" "download"
assert_contains "$help_output" "understand"
assert_contains "$help_output" "blueprint"
assert_contains "$help_output" "whisper-model"

doctor_output="$("$DRIVER" doctor)"
assert_contains "$doctor_output" "report_dir=$HERMES_VIDEO_REPORT_DIR"
assert_contains "$doctor_output" "tesseract="

test -f "$ROOT_DIR/.agents/skills/video-watch/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/video-watch/SKILL.md"
test -f "$ROOT_DIR/.skills/skills.d/video-watch/meta.env"
grep -q '^video-watch$' "$ROOT_DIR/.skills/skills.txt"

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  sample="$TMP_DIR/sample.mp4"
  ffmpeg -y -f lavfi -i testsrc=size=320x240:rate=5 -t 1 "$sample" >/dev/null 2>&1
  analysis_output="$("$DRIVER" understand "$sample" --frames 3 --mode interval --no-transcribe)"
  assert_contains "$analysis_output" "analysis="
  analysis="${analysis_output#analysis=}"
  test -f "$analysis"
  python3 -m json.tool "$analysis" >/dev/null
  blueprint_output="$("$DRIVER" blueprint "$sample" --frames 3 --mode interval --no-transcribe)"
  assert_contains "$blueprint_output" "blueprint="
  test -f "${blueprint_output#blueprint=}"
  if command -v tesseract >/dev/null 2>&1; then
    ocr_output="$("$DRIVER" blueprint "$sample" --frames 3 --mode interval --no-transcribe --ocr)"
    assert_contains "$ocr_output" "blueprint="
    grep -q "On-Screen Text OCR" "${ocr_output#blueprint=}"
  fi
fi

echo "video-watch tests passed"
