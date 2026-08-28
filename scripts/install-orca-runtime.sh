#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN_FILE="${ORCA_PIN_FILE:-$ROOT_DIR/config/production-versions.json}"
INSTALL_ROOT="${ORCA_INSTALL_ROOT:-/opt/orca}"
SYSTEMD_DIR="${ORCA_SYSTEMD_DIR:-/etc/systemd/system}"
RUNTIME_USER="${ORCA_RUNTIME_USER:-orca}"
RUNTIME_GROUP="${ORCA_RUNTIME_GROUP:-$RUNTIME_USER}"
ORCA_HOME="${ORCA_HOME:-/home/$RUNTIME_USER}"
PORT="${ORCA_PORT:-6768}"
TEST_MODE="${HERMES_ORCA_TEST_MODE:-0}"
INSTALL_DEPS="${ORCA_INSTALL_DEPS:-1}"
CLI_WRAPPER_SOURCE="$ROOT_DIR/scripts/orca-ide-cli-wrapper.sh"
BOOTSTRAP="$ROOT_DIR/scripts/bootstrap-hermes-orca-client.sh"

[[ -f "$PIN_FILE" ]] || { echo "missing Orca production pin: $PIN_FILE" >&2; exit 2; }
[[ -f "$CLI_WRAPPER_SOURCE" ]] || { echo "missing Orca CLI wrapper source: $CLI_WRAPPER_SOURCE" >&2; exit 2; }
[[ -f "$BOOTSTRAP" ]] || { echo "missing Hermes Orca bootstrap: $BOOTSTRAP" >&2; exit 2; }
read -r TAG VERSION ASSET URL EXPECTED_SHA < <(
  python3 - "$PIN_FILE" <<'PY'
import json,re,sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
o=p.get('orca_runtime') or {}
values=[o.get('tag',''),o.get('version',''),o.get('asset',''),o.get('url',''),o.get('sha256','')]
if not all(isinstance(v,str) and v for v in values): raise SystemExit('invalid orca_runtime production pin')
if not re.fullmatch(r'[0-9a-f]{64}', values[4]): raise SystemExit('invalid Orca SHA256 pin')
print(*values)
PY
)
[[ "$TAG" == "v$VERSION" ]] || { echo "Orca tag/version mismatch" >&2; exit 2; }
[[ "$ASSET" == "orca-linux.AppImage" ]] || { echo "unsupported Orca production asset" >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || { echo "invalid Orca port" >&2; exit 2; }

PAIRING_ADDRESS="${ORCA_PAIRING_ADDRESS:-}"
if [[ -z "$PAIRING_ADDRESS" ]]; then
  command -v tailscale >/dev/null 2>&1 || { echo "ORCA_PAIRING_ADDRESS or tailscale is required" >&2; exit 2; }
  PAIRING_ADDRESS="$(tailscale ip -4 2>/dev/null | head -n1)"
fi
[[ -n "$PAIRING_ADDRESS" ]] || { echo "unable to determine Orca pairing address" >&2; exit 2; }

if [[ "$TEST_MODE" != 1 ]]; then
  [[ "$EUID" -eq 0 ]] || { echo "Orca installer must run as root" >&2; exit 1; }
  if [[ "$INSTALL_DEPS" == 1 ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
      curl file jq xvfb zlib1g-dev ca-certificates git \
      libgtk-3-0t64 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 \
      libgbm1 libasound2t64 libxtst6 libcups2t64 libdrm2 libxkbcommon0 \
      libpango-1.0-0 libcairo2 libatspi2.0-0t64 libxcomposite1 \
      libxdamage1 libxfixes3 libxrandr2 libxrender1 libx11-xcb1 \
      libxcb-dri3-0 libxss1 >/dev/null
  fi
  if ! id "$RUNTIME_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$ORCA_HOME" --shell /usr/sbin/nologin "$RUNTIME_USER"
  fi
  RUNTIME_GROUP="$(id -gn "$RUNTIME_USER")"
  install -d -o root -g root -m 0755 "$INSTALL_ROOT" "$INSTALL_ROOT/releases" "$INSTALL_ROOT/bin"
  install -d -o "$RUNTIME_USER" -g "$RUNTIME_GROUP" -m 0750 "$ORCA_HOME"
  install -d -o root -g root -m 0755 "$SYSTEMD_DIR"
else
  mkdir -p "$INSTALL_ROOT/releases" "$INSTALL_ROOT/bin" "$SYSTEMD_DIR" "$ORCA_HOME"
fi

TMP="$(mktemp -d)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT
IMAGE="$TMP/$ASSET"
SOURCE="${ORCA_APPIMAGE_SOURCE:-$URL}"
if [[ -f "$SOURCE" ]]; then
  cp "$SOURCE" "$IMAGE"
else
  command -v curl >/dev/null 2>&1 || { echo "curl is required to download Orca" >&2; exit 1; }
  curl -fsSL --retry 3 --retry-delay 2 "$SOURCE" -o "$IMAGE"
fi
ACTUAL_SHA="$(sha256sum "$IMAGE" | awk '{print $1}')"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo "Orca AppImage SHA256 mismatch" >&2; exit 1; }
chmod 0755 "$IMAGE"

EXTRACT="$TMP/extract"
mkdir -p "$EXTRACT"
(
  cd "$EXTRACT"
  "$IMAGE" --appimage-extract >/dev/null
)
STAGED="$EXTRACT/squashfs-root"
[[ -x "$STAGED/AppRun" ]] || { echo "Orca AppImage extraction did not produce AppRun" >&2; exit 1; }
chmod -R a+rX "$STAGED"
printf '%s\n' "$EXPECTED_SHA" > "$STAGED/ORCA_SOURCE_SHA256"
printf '%s\n' "$TAG" > "$STAGED/ORCA_VERSION"

TARGET="$INSTALL_ROOT/releases/$TAG"
if [[ -d "$TARGET" ]]; then
  [[ -x "$TARGET/AppRun" ]] || { echo "existing Orca release is incomplete: $TARGET" >&2; exit 1; }
  [[ "$(cat "$TARGET/ORCA_SOURCE_SHA256" 2>/dev/null || true)" == "$EXPECTED_SHA" ]] || { echo "existing Orca release provenance mismatch" >&2; exit 1; }
else
  mv "$STAGED" "$TARGET"
fi
[[ -x "$TARGET/orca-ide" ]] || { echo "Orca release is missing the Electron runtime: $TARGET/orca-ide" >&2; exit 1; }
[[ -f "$TARGET/resources/app.asar.unpacked/out/cli/index.js" ]] || { echo "Orca release is missing the CLI entrypoint" >&2; exit 1; }
if [[ "$TEST_MODE" != 1 ]]; then
  chown -R root:root "$TARGET"
fi
TMP_LINK="$INSTALL_ROOT/.current.$$"
ln -s "$TARGET" "$TMP_LINK"
mv -Tf "$TMP_LINK" "$INSTALL_ROOT/current"
printf '%s\n' "$TAG" > "$INSTALL_ROOT/VERSION"
install -m 0755 "$CLI_WRAPPER_SOURCE" "$INSTALL_ROOT/bin/orca-ide"
if [[ "$TEST_MODE" != 1 ]]; then
  chown root:root "$INSTALL_ROOT/VERSION" "$INSTALL_ROOT/bin/orca-ide"
  chmod 0644 "$INSTALL_ROOT/VERSION"
fi

UNIT="$SYSTEMD_DIR/orca-serve.service"
cat > "$UNIT" <<EOF
[Unit]
Description=Orca development execution runtime
After=network-online.target tailscaled.service
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=$RUNTIME_USER
Group=$RUNTIME_GROUP
WorkingDirectory=$ORCA_HOME
Environment=HOME=$ORCA_HOME
Environment=LIBGL_ALWAYS_SOFTWARE=1
Environment=DO_NOT_TRACK=1
Environment=ORCA_TELEMETRY_DISABLED=1
ExecStart=$INSTALL_ROOT/current/AppRun serve --port $PORT --pairing-address $PAIRING_ADDRESS --json
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=3
KillMode=mixed
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$ORCA_HOME
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT"

if [[ "$TEST_MODE" != 1 ]]; then
  systemctl daemon-reload
  systemctl enable --now orca-serve.service
  ready=0
  for _ in $(seq 1 30); do
    if systemctl is-active --quiet orca-serve.service && ss -lnt | grep -q ":$PORT "; then ready=1; break; fi
    sleep 1
  done
  [[ "$ready" == 1 ]] || {
    systemctl status orca-serve.service --no-pager >&2 || true
    echo "Orca service health check failed" >&2
    exit 1
  }
  if id hermes >/dev/null 2>&1; then
    ORCA_CLI_COMMAND="$INSTALL_ROOT/bin/orca-ide" bash "$BOOTSTRAP"
  else
    echo "HERMES_ORCA_CLIENT=DEFERRED reason=hermes_user_missing"
  fi
fi

printf 'ORCA_RUNTIME_INSTALL=PASS tag=%s sha256=%s address=%s port=%s\n' "$TAG" "$EXPECTED_SHA" "$PAIRING_ADDRESS" "$PORT"
