#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP="$ROOT_DIR/scripts/bootstrap-hermes-orca-client.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAKE_CLI="$TMP/orca-ide"
cat > "$FAKE_CLI" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
STATE="${ORCA_FAKE_STATE:?}"
COUNT="${ORCA_FAKE_ADD_COUNT:?}"
if [[ "${1:-} ${2:-}" == 'environment list' ]]; then
  if [[ -f "$STATE" ]]; then
    printf '%s\n' '{"id":"local","ok":true,"result":{"environments":[{"name":"hermes-runtime","id":"env-1"}]}}'
  else
    printf '%s\n' '{"id":"local","ok":true,"result":{"environments":[]}}'
  fi
  exit 0
fi
if [[ "${1:-} ${2:-}" == 'environment add' ]]; then
  [[ "$*" == *'--name hermes-runtime'* ]]
  [[ "$*" == *'--pairing-code orca://pair?code=FAKE-PAIRING-CAPABILITY'* ]]
  printf '1\n' >> "$COUNT"
  : > "$STATE"
  printf '%s\n' '{"id":"local","ok":true,"result":{"environment":{"name":"hermes-runtime","id":"env-1"}}}'
  exit 0
fi
if [[ "${1:-}" == 'status' ]]; then
  [[ -f "$STATE" ]] || exit 1
  [[ "$*" == *'--environment hermes-runtime'* ]]
  printf '%s\n' '{"id":"1","ok":true,"result":{"runtime":{"state":"ready","reachable":true,"appVersion":"1.4.190"},"graph":{"state":"ready"}}}'
  exit 0
fi
echo "unexpected fake CLI invocation: $*" >&2
exit 2
SH
chmod +x "$FAKE_CLI"
printf '%s\n' 'Pairing URL: orca://pair?code=FAKE-PAIRING-CAPABILITY' > "$TMP/ready.log"

run_bootstrap() {
  HERMES_ORCA_TEST_MODE=1 \
  ORCA_CLI_COMMAND="$FAKE_CLI" \
  ORCA_CLIENT_HOME="$TMP/home" \
  ORCA_USER_DATA_PATH="$TMP/userdata" \
  ORCA_ENVIRONMENT_NAME=hermes-runtime \
  ORCA_READY_LOG_FILE="$TMP/ready.log" \
  ORCA_FAKE_STATE="$TMP/state" \
  ORCA_FAKE_ADD_COUNT="$TMP/add-count" \
    bash "$BOOTSTRAP"
}

OUT1="$(run_bootstrap)"
[[ "$OUT1" == *'HERMES_ORCA_CLIENT=PASS'* ]]
[[ "$OUT1" != *'FAKE-PAIRING-CAPABILITY'* ]]
[[ "$(stat -c '%a' "$TMP/userdata")" == 700 ]]
[[ "$(wc -l < "$TMP/add-count")" -eq 1 ]]
OUT2="$(run_bootstrap)"
[[ "$OUT2" == *'HERMES_ORCA_CLIENT=PASS'* ]]
[[ "$OUT2" != *'FAKE-PAIRING-CAPABILITY'* ]]
[[ "$(wc -l < "$TMP/add-count")" -eq 1 ]]

echo 'hermes Orca client bootstrap passed'
