#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
TRANSFER_DIR="$ROOT_DIR/.hermes/transfer"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$DIST_DIR/hermes-max-vps-transfer-$STAMP.tar.gz"
CHECKSUM="$ARCHIVE.sha256"
MANIFEST="$TRANSFER_DIR/vps-transfer-manifest-$STAMP.txt"
MANIFEST_REL=".hermes/transfer/vps-transfer-manifest-$STAMP.txt"

usage() {
  cat <<'EOF'
Usage:
  scripts/export-vps-transfer.sh

Creates a VPS transfer archive for Hermes Max. The archive includes skills,
driver scripts, routing configs, docs, tests, promptfoo evals, source receipts,
and safe runtime policy/state templates. It excludes secrets, logs, screenshots,
pid files, caches, virtualenvs, git internals, model weights, and bulky binary
artifacts.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    echo "error: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac

mkdir -p "$DIST_DIR" "$TRANSFER_DIR"

cd "$ROOT_DIR"

{
  echo "Hermes Max VPS transfer manifest"
  echo "generated=$STAMP"
  echo "root=$ROOT_DIR"
  echo
  echo "skill_counts:"
  printf '  agents_skills=%s\n' "$(find .agents/skills -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | awk '{print $1}')"
  printf '  runtime_skills=%s\n' "$(find .skills/skills.d -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | awk '{print $1}')"
  echo
  echo "included_roots:"
  printf '  %s\n' \
    ".agents" \
    ".skills" \
    ".skill-sources" \
    ".hermes/bundles" \
    ".hermes/policy" \
    ".hermes/state" \
    "$MANIFEST_REL" \
    "agents" \
    "artifacts" \
    "bridge" \
    "config" \
    "docs" \
    "gateways" \
    "packs" \
    "profiles" \
    "promptfoo" \
    "scripts" \
    "src" \
    "tests" \
    "OBLITERATUS" \
    "README.md" \
    "skills-lock.json"
  echo
  echo "excluded_patterns:"
  printf '  %s\n' \
    ".env*" \
    "logs" \
    "screens" \
    "*.pid" \
    "*.log" \
    "*.b64" \
    "__pycache__" \
    ".pytest_cache" \
    ".venv" \
    "node_modules" \
    ".git" \
    "dist" \
    "*.apk" \
    "*.whl" \
    "*.zip" \
    "*.pdf" \
    "*.safetensors" \
    "*.bin" \
    "*.pt" \
    "*.pth"
} > "$MANIFEST"

EXCLUDES=(
  --exclude-vcs
  --exclude='./dist'
  --exclude='dist'
  --exclude='dist/*'
  --exclude='./.git'
  --exclude='./.git/*'
  --exclude='*/.git'
  --exclude='*/.git/*'
  --exclude='./.env'
  --exclude='./.env.*'
  --exclude='./**/.env'
  --exclude='./**/.env.*'
  --exclude='.env'
  --exclude='.env.*'
  --exclude='*/.env'
  --exclude='*/.env.*'
  --exclude='./secrets'
  --exclude='./**/secrets'
  --exclude='secrets'
  --exclude='secrets/*'
  --exclude='*/secrets'
  --exclude='*/secrets/*'
  --exclude='./**/.venv'
  --exclude='./**/venv'
  --exclude='./**/node_modules'
  --exclude='./**/__pycache__'
  --exclude='./**/.pytest_cache'
  --exclude='./**/*.pyc'
  --exclude='./**/*.pyo'
  --exclude='./**/*.pid'
  --exclude='./**/*.log'
  --exclude='./**/*.b64'
  --exclude='*/.venv'
  --exclude='*/.venv/*'
  --exclude='*/venv'
  --exclude='*/venv/*'
  --exclude='*/node_modules'
  --exclude='*/node_modules/*'
  --exclude='*/__pycache__'
  --exclude='*/__pycache__/*'
  --exclude='*/.pytest_cache'
  --exclude='*/.pytest_cache/*'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='*.pid'
  --exclude='*.log'
  --exclude='*.b64'
  --exclude='*/*.pyc'
  --exclude='*/*.pyo'
  --exclude='*/*.pid'
  --exclude='*/*.log'
  --exclude='*/*.b64'
  --exclude='./.hermes/9router'
  --exclude='.hermes/9router'
  --exclude='.hermes/9router/*'
  --exclude='./.hermes/omniroute'
  --exclude='.hermes/omniroute'
  --exclude='.hermes/omniroute/*'
  --exclude='./.hermes/install'
  --exclude='.hermes/install'
  --exclude='.hermes/install/*'
  --exclude='./.hermes/jarvis/*.pid'
  --exclude='.hermes/jarvis/*.pid'
  --exclude='./.hermes/logs'
  --exclude='.hermes/logs'
  --exclude='.hermes/logs/*'
  --exclude='./.hermes/obliteratus'
  --exclude='.hermes/obliteratus'
  --exclude='.hermes/obliteratus/*'
  --exclude='./.hermes/power-up'
  --exclude='.hermes/power-up'
  --exclude='.hermes/power-up/*'
  --exclude='./.hermes/refresh'
  --exclude='.hermes/refresh'
  --exclude='.hermes/refresh/*'
  --exclude='./.hermes/reports'
  --exclude='.hermes/reports'
  --exclude='.hermes/reports/*'
  --exclude='./.hermes/screens'
  --exclude='.hermes/screens'
  --exclude='.hermes/screens/*'
  --exclude='./.hermes/transfer/hermes-exported-data-*'
  --exclude='./.hermes/transfer/*.tar'
  --exclude='./.hermes/transfer/*.tar.gz'
  --exclude='./.hermes/transfer/*.zip'
  --exclude='.hermes/transfer/hermes-exported-data-*'
  --exclude='.hermes/transfer/*.tar'
  --exclude='.hermes/transfer/*.tar.gz'
  --exclude='.hermes/transfer/*.zip'
  --exclude='.hermes/bundles/*.zip'
  --exclude='.hermes/bundles/**/*.zip'
  --exclude='.hermes/bundles/*.apk'
  --exclude='.hermes/bundles/**/*.apk'
  --exclude='./OBLITERATUS/results'
  --exclude='OBLITERATUS/results'
  --exclude='OBLITERATUS/results/*'
  --exclude='./OBLITERATUS/models'
  --exclude='OBLITERATUS/models'
  --exclude='OBLITERATUS/models/*'
  --exclude='./OBLITERATUS/checkpoints'
  --exclude='OBLITERATUS/checkpoints'
  --exclude='OBLITERATUS/checkpoints/*'
  --exclude='OBLITERATUS/.venv'
  --exclude='OBLITERATUS/.venv/*'
  --exclude='OBLITERATUS/.pytest_cache'
  --exclude='OBLITERATUS/.pytest_cache/*'
  --exclude='OBLITERATUS/__pycache__'
  --exclude='OBLITERATUS/__pycache__/*'
  --exclude='./OBLITERATUS/*.safetensors'
  --exclude='./OBLITERATUS/*.bin'
  --exclude='./OBLITERATUS/*.pt'
  --exclude='./OBLITERATUS/*.pth'
  --exclude='OBLITERATUS/*.safetensors'
  --exclude='OBLITERATUS/*.bin'
  --exclude='OBLITERATUS/*.pt'
  --exclude='OBLITERATUS/*.pth'
  --exclude='./**/*.apk'
  --exclude='./**/*.whl'
  --exclude='./**/*.zip'
  --exclude='./**/*.pdf'
  --exclude='*.apk'
  --exclude='*.whl'
  --exclude='*.zip'
  --exclude='*.pdf'
  --exclude='*/*.apk'
  --exclude='*/*.whl'
  --exclude='*/*.zip'
  --exclude='*/*.pdf'
  --exclude='*/*/*.apk'
  --exclude='*/*/*.whl'
  --exclude='*/*/*.zip'
  --exclude='*/*/*.pdf'
)

tar "${EXCLUDES[@]}" -czf "$ARCHIVE" \
  .agents \
  .skills \
  .skill-sources \
  .hermes/bundles \
  .hermes/policy \
  .hermes/state \
  "$MANIFEST_REL" \
  agents \
  artifacts \
  bridge \
  config \
  docs \
  gateways \
  packs \
  profiles \
  promptfoo \
  scripts \
  src \
  tests \
  OBLITERATUS \
  README.md \
  skills-lock.json

sha256sum "$ARCHIVE" > "$CHECKSUM"

echo "archive=$ARCHIVE"
echo "checksum=$CHECKSUM"
echo "manifest=$MANIFEST"
