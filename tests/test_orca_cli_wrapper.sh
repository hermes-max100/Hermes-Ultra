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
echo fake-orca-server "$@"
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
json.dump({"schema_version":1,"orca_runtime":{"tag":"v1.4.190","version":"1.4.190","asset":"orca-linux.AppImage","url":"https://example.invalid/orca-linux.AppImage","sha256":sys.argv[2]}}, open(sys.argv[1],"w"))
PY

INSTALL_ROOT="$TMP/opt/orca"
HERMES_ORCA_TEST_MODE=1 ORCA_PIN_FILE="$PIN" ORCA_APPIMAGE_SOURCE="$FAKE" \
ORCA_INSTALL_ROOT="$INSTALL_ROOT" ORCA_SYSTEMD_DIR="$TMP/systemd" ORCA_HOME="$TMP/home/orca" \
ORCA_RUNTIME_USER="$(id -un)" ORCA_PAIRING_ADDRESS="100.64.0.10" ORCA_PORT=6768 \
  bash "$ROOT_DIR/scripts/install-orca-runtime.sh" >/dev/null

CLI="$INSTALL_ROOT/bin/orca-ide"
[[ -x "$CLI" ]] || { echo 'headless Orca CLI wrapper missing' >&2; exit 1; }
grep -F 'ELECTRON_RUN_AS_NODE=1' "$CLI" >/dev/null
grep -F 'resources/app.asar.unpacked' "$CLI" >/dev/null
grep -F 'out/cli/index.js' "$CLI" >/dev/null
grep -F 'ORCA_TELEMETRY_DISABLED=1' "$CLI" >/dev/null
grep -F 'DO_NOT_TRACK=1' "$CLI" >/dev/null
! grep -F 'exec "$APPDIR/AppRun"' "$CLI" >/dev/null

echo 'orca headless cli wrapper passed'
