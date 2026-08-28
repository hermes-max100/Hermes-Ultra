#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOADER="$ROOT_DIR/src/system/load-hermes-runtime-env.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

cat > "$TMP_DIR/runtime.env" <<'EOF'
export HERMES_SMTP_HOST="smtp.example.com"
export HERMES_SMTP_PORT="587"
export HERMES_SMTP_USER="sender@example.com"
export HERMES_SMTP_PASSWORD="secret"
export HERMES_SMTP_FROM="sender@example.com"
export HERMES_CONTACT_NAME="Jane Doe"
export HERMES_CONTACT_EMAIL="jane@example.com"
export HERMES_PRIMARY_PROVIDER="ninerouter"
export HERMES_FALLBACK_PROVIDER="omniroute"
EOF
chmod 600 "$TMP_DIR/runtime.env"

(
  source "$LOADER" --file "$TMP_DIR/runtime.env" --check smtp
  [[ "$HERMES_SMTP_HOST" == "smtp.example.com" ]]
  [[ "$HERMES_SMTP_PORT" == "587" ]]
  [[ "$HERMES_CONTACT_NAME" == "Jane Doe" ]]
)

(
  source "$LOADER" --file "$TMP_DIR/runtime.env" --check contact-form
  [[ "$HERMES_CONTACT_NAME" == "Jane Doe" ]]
  [[ "$HERMES_CONTACT_EMAIL" == "jane@example.com" ]]
)

cat > "$TMP_DIR/unknown.env" <<'EOF'
export HERMES_SMTP_HOST="smtp.example.com"
export HERMES_UNKNOWN_KEY="nope"
EOF
chmod 600 "$TMP_DIR/unknown.env"

if source "$LOADER" --file "$TMP_DIR/unknown.env" --check smtp >/tmp/hermes-runtime-env.out 2>&1; then
  echo "expected unknown key rejection" >&2
  exit 1
fi
assert_contains "$(cat /tmp/hermes-runtime-env.out)" "unknown env key: HERMES_UNKNOWN_KEY"

cat > "$TMP_DIR/world.env" <<'EOF'
export HERMES_CONTACT_NAME="Jane Doe"
export HERMES_CONTACT_EMAIL="jane@example.com"
EOF
chmod 644 "$TMP_DIR/world.env"

if source "$LOADER" --file "$TMP_DIR/world.env" --check contact-form >/tmp/hermes-runtime-world.out 2>&1; then
  echo "expected world-readable rejection" >&2
  exit 1
fi
assert_contains "$(cat /tmp/hermes-runtime-world.out)" "refusing to load world-readable env file"

echo "hermes runtime env loader tests passed"
