#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INCLUDE_LOGS=0

usage() {
  cat <<'EOF'
Usage:
  scripts/export-hermes-build.sh [--include-logs]

Creates a portable Hermes Max transfer archive under dist/.

By default, logs and runtime state are excluded because they can contain prompts,
local paths, tokens, or command output. Use --include-logs for a debugging
handoff bundle.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --include-logs)
      INCLUDE_LOGS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown flag: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$INCLUDE_LOGS" == "1" ]]; then
  ARCHIVE="$DIST_DIR/hermes-max-build-with-logs-$STAMP.tar.gz"
else
  ARCHIVE="$DIST_DIR/hermes-max-build-$STAMP.tar.gz"
fi
CHECKSUM="$ARCHIVE.sha256"

mkdir -p "$DIST_DIR"

cd "$ROOT_DIR"

EXCLUDES=(
  --exclude='./dist'
  --exclude='./.git'
  --exclude='./.env'
  --exclude='./.env.*'
  --exclude='./secrets'
  --exclude='./.pytest_cache'
  --exclude='./OBLITERATUS/.git'
  --exclude='./OBLITERATUS/.venv'
  --exclude='./OBLITERATUS/.pytest_cache'
  --exclude='./OBLITERATUS/__pycache__'
  --exclude='./OBLITERATUS/**/__pycache__'
  --exclude='./OBLITERATUS/results'
  --exclude='./OBLITERATUS/models'
  --exclude='./OBLITERATUS/checkpoints'
  --exclude='./OBLITERATUS/*.safetensors'
  --exclude='./OBLITERATUS/*.bin'
  --exclude='./OBLITERATUS/*.pt'
  --exclude='./OBLITERATUS/*.pth'
)

if [[ "$INCLUDE_LOGS" != "1" ]]; then
  EXCLUDES+=(--exclude='./.hermes')
fi

tar "${EXCLUDES[@]}" -czf "$ARCHIVE" .

sha256sum "$ARCHIVE" > "$CHECKSUM"

echo "archive=$ARCHIVE"
echo "checksum=$CHECKSUM"
echo "include_logs=$INCLUDE_LOGS"
