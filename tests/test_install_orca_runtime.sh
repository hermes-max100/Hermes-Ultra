#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAKE="$TMP/orca-linux.AppImage"
cat > "$FAKE" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "--appimage-extract" ]] || exit 2
mkdir -p squashfs-root/resources/app.asar.unpacked/out/cli
cat > squashfs-root/AppRun <<'APP'
#!/usr/bin/env bash
echo fake-orca "$@"
APP
cat > squashfs-root/orca-ide <<'BIN'
#!/usr/bin/env bash
echo fake-electron "$@"
BIN
printf '%s\n' 'module.exports={main:async()=>{}}' > squashfs-root/resources/app.asar.unpacked/out/cli/index.js
chmod +x squashfs-root/AppRun squashfs-root/orca-ide
SH
chmod +x "$FAKE"
SHA="$(sha256sum "$FAKE" | awk '{print $1}')"

PIN="$TMP/production-versions.json"
python3 - "$PIN" "$SHA" <<'PY'
import json,sys
json.dump({
  "schema_version": 1,
  "orca_runtime": {
    "tag": "v1.4.190",
    "version": "1.4.190",
    "asset": "orca-linux.AppImage",
    "url": "https://example.invalid/orca-linux.AppImage",
    "sha256": sys.argv[2],
  },
}, open(sys.argv[1], "w"))
PY

INSTALL_ROOT="$TMP/opt/orca"
SYSTEMD_DIR="$TMP/systemd"
HOME_DIR="$TMP/home/orca"
HERMES_ORCA_TEST_MODE=1 \
ORCA_PIN_FILE="$PIN" \
ORCA_APPIMAGE_SOURCE="$FAKE" \
ORCA_INSTALL_ROOT="$INSTALL_ROOT" \
ORCA_SYSTEMD_DIR="$SYSTEMD_DIR" \
ORCA_HOME="$HOME_DIR" \
ORCA_RUNTIME_USER="$(id -un)" \
ORCA_PAIRING_ADDRESS="100.64.0.10" \
ORCA_PORT=6768 \
  bash "$ROOT_DIR/scripts/install-orca-runtime.sh"

[[ -L "$INSTALL_ROOT/current" ]]
[[ "$(readlink -f "$INSTALL_ROOT/current")" == "$INSTALL_ROOT/releases/v1.4.190" ]]
[[ -x "$INSTALL_ROOT/current/AppRun" ]]
[[ "$(cat "$INSTALL_ROOT/VERSION")" == "v1.4.190" ]]
UNIT="$SYSTEMD_DIR/orca-serve.service"
[[ -f "$UNIT" ]]
grep -F "ExecStart=$INSTALL_ROOT/current/AppRun serve --port 6768 --pairing-address 100.64.0.10 --json" "$UNIT" >/dev/null
grep -F 'Environment=DO_NOT_TRACK=1' "$UNIT" >/dev/null
grep -F 'Environment=ORCA_TELEMETRY_DISABLED=1' "$UNIT" >/dev/null
grep -F 'NoNewPrivileges=true' "$UNIT" >/dev/null
grep -F 'ProtectSystem=strict' "$UNIT" >/dev/null
grep -F 'RestartPreventExitStatus=3' "$UNIT" >/dev/null
grep -F 'StartLimitBurst=5' "$UNIT" >/dev/null

echo 'orca runtime installer passed'
