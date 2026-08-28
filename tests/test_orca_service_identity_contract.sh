#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/scripts/install-cloud-release-local.sh"
ORCA_INSTALLER="$ROOT_DIR/scripts/install-orca-runtime.sh"
BOOTSTRAP="$ROOT_DIR/scripts/bootstrap-hermes-orca-client.sh"

[[ -f "$BOOTSTRAP" ]] || { echo 'Hermes Orca client bootstrap missing' >&2; exit 1; }
grep -F 'Environment=ORCA_CLI_COMMAND=/opt/orca/bin/orca-ide' "$INSTALLER" >/dev/null
grep -F 'Environment=ORCA_USER_DATA_PATH=/var/lib/hermes/.config/hermes/orca-client/orca' "$INSTALLER" >/dev/null
grep -F 'Environment=ORCA_ENVIRONMENT=hermes-runtime' "$INSTALLER" >/dev/null
grep -F 'ProtectHome=true' "$INSTALLER" >/dev/null
! grep -F 'Environment=ORCA_CLI_COMMAND=/opt/orca/current/AppRun' "$INSTALLER" >/dev/null

grep -F 'bootstrap-hermes-orca-client.sh' "$ORCA_INSTALLER" >/dev/null
grep -F 'ORCA_ENVIRONMENT_NAME' "$BOOTSTRAP" >/dev/null
grep -F 'ORCA_USER_DATA_PATH' "$BOOTSTRAP" >/dev/null
grep -F 'environment add' "$BOOTSTRAP" >/dev/null
grep -F 'status --environment' "$BOOTSTRAP" >/dev/null
! grep -F 'Pairing URL: $PAIRING' "$BOOTSTRAP" >/dev/null

echo 'orca service identity contract passed'
