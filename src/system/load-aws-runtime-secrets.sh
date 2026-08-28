#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
PREFIX="${HERMES_RUNTIME_SECRET_PREFIX:-/hermes-max/runtime/}"
DEST="${HERMES_RUNTIME_ENV_PATH:-/var/lib/hermes/.config/hermes/runtime.env}"
[[ "$PREFIX" == /hermes-max/runtime/* && "$PREFIX" == */ ]] || { echo 'invalid runtime secret prefix' >&2; exit 1; }
DEST_DIR="$(dirname "$DEST")"
mkdir -p "$DEST_DIR"
chmod 700 "$DEST_DIR" 2>/dev/null || true
RAW="$(mktemp "$DEST_DIR/.runtime-ssm.XXXXXX")"
TMP="$(mktemp "$DEST_DIR/.runtime-env.XXXXXX")"
chmod 600 "$RAW" "$TMP"
trap 'rm -f "$RAW" "$TMP"' EXIT
aws ssm get-parameters-by-path --path "$PREFIX" --with-decryption --recursive --region "$REGION" --output json > "$RAW"
python3 - "$RAW" "$PREFIX" "$TMP" <<'PY'
import json, pathlib, shlex, sys
raw = pathlib.Path(sys.argv[1])
prefix = sys.argv[2]
out = pathlib.Path(sys.argv[3])
allowed = {
    'NVIDIA_API_KEY',
    'OPENROUTER_API_KEY',
    'VENICE_API_KEY',
    'GOOGLE_API_KEY',
    'GEMINI_API_KEY',
}
data = json.loads(raw.read_text())
rows = []
for param in data.get('Parameters', []):
    name = str(param.get('Name', ''))
    if not name.startswith(prefix):
        print('runtime secret outside configured prefix', file=sys.stderr)
        raise SystemExit(1)
    key = name[len(prefix):]
    if key not in allowed:
        print(f'unknown runtime secret key: {key}', file=sys.stderr)
        raise SystemExit(1)
    value = str(param.get('Value', ''))
    if '\n' in value or '\r' in value or '\x00' in value:
        print(f'invalid runtime secret value for key: {key}', file=sys.stderr)
        raise SystemExit(1)
    rows.append((key, value))
rows.sort()
out.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key, value in rows))
PY
chmod 600 "$TMP"
mv -f "$TMP" "$DEST"
chmod 600 "$DEST"
COUNT="$(grep -c '^[A-Z0-9_][A-Z0-9_]*=' "$DEST" 2>/dev/null || true)"
rm -f "$RAW"
trap - EXIT
printf 'AWS_RUNTIME_SECRETS=PASS count=%s\n' "$COUNT"
