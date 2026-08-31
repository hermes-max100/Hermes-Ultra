#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/rollback-cloud-release.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
INSTALL="$TMP/install"
mkdir -p "$INSTALL/releases/release-a" "$INSTALL/releases/release-b" "$INSTALL/state"
printf 'A\n' > "$INSTALL/releases/release-a/VERSION"
printf 'B\n' > "$INSTALL/releases/release-b/VERSION"
for r in release-a release-b; do
  (cd "$INSTALL/releases/$r" && sha256sum VERSION > CLOUD_RELEASE_MANIFEST.sha256)
done
printf 'durable\n' > "$INSTALL/state/keep.txt"
touch -t 202608200100 "$INSTALL/releases/release-a"
touch -t 202608200200 "$INSTALL/releases/release-b"
ln -s "$INSTALL/releases/release-b" "$INSTALL/current"

[[ -x "$SCRIPT" ]] || { echo 'rollback script missing' >&2; exit 1; }
bash "$SCRIPT" --install-root "$INSTALL"
[[ "$(readlink -f "$INSTALL/current")" == "$INSTALL/releases/release-a" ]] || { echo 'default rollback did not select previous release' >&2; exit 1; }
[[ "$(cat "$INSTALL/state/keep.txt")" == durable ]] || { echo 'durable state changed' >&2; exit 1; }
if bash "$SCRIPT" --install-root "$INSTALL" --to does-not-exist >/dev/null 2>&1; then
  echo 'unknown release unexpectedly accepted' >&2
  exit 1
fi
printf 'tampered\n' >> "$INSTALL/releases/release-b/VERSION"
if bash "$SCRIPT" --install-root "$INSTALL" --to release-b >/dev/null 2>&1; then
  echo 'tampered release unexpectedly accepted' >&2
  exit 1
fi
[[ "$(readlink -f "$INSTALL/current")" == "$INSTALL/releases/release-a" ]] || { echo 'failed rollback changed current link' >&2; exit 1; }
echo 'cloud release rollback tests passed'

# Relay rollback reconciliation: target with Relay uses reconcile; pre-Relay target deactivates code only.
TMP2="$(mktemp -d)"
INSTALL2="$TMP2/install"; VAR2="$TMP2/var/lib/hermes"; SYSD2="$TMP2/systemd"
mkdir -p "$INSTALL2/releases/with-relay/scripts" "$INSTALL2/releases/with-relay/vendor/hermes-relay/server-v1.10.0" "$INSTALL2/releases/pre-relay" "$VAR2/.hermes/plugin-data/hermes-relay" "$SYSD2"
printf 'R\n' > "$INSTALL2/releases/with-relay/VERSION"
printf 'P\n' > "$INSTALL2/releases/pre-relay/VERSION"
printf 'payload\n' > "$INSTALL2/releases/with-relay/vendor-marker"
for r in with-relay pre-relay; do (cd "$INSTALL2/releases/$r" && sha256sum VERSION > CLOUD_RELEASE_MANIFEST.sha256); done
printf 'session\n' > "$VAR2/.hermes/hermes-relay-sessions.json"
printf 'plugin-data\n' > "$VAR2/.hermes/plugin-data/hermes-relay/state"
printf 'signing\n' > "$VAR2/.hermes/relay-signing-identity"
FAKE="$TMP2/relay-installer.sh"; LOG="$TMP2/relay.log"
cat > "$FAKE" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_RELAY_LOG"
exit 0
SH
chmod +x "$FAKE"
ln -s "$INSTALL2/releases/pre-relay" "$INSTALL2/current"
HERMES_RELAY_INSTALLER="$FAKE" FAKE_RELAY_LOG="$LOG" HERMES_VAR_ROOT="$VAR2" HERMES_SYSTEMD_DIR="$SYSD2" bash "$SCRIPT" --install-root "$INSTALL2" --to with-relay
grep -q '^reconcile ' "$LOG"
: > "$LOG"
HERMES_RELAY_INSTALLER="$FAKE" FAKE_RELAY_LOG="$LOG" HERMES_VAR_ROOT="$VAR2" HERMES_SYSTEMD_DIR="$SYSD2" bash "$SCRIPT" --install-root "$INSTALL2" --to pre-relay
grep -q '^deactivate-code-only ' "$LOG"
for f in "$VAR2/.hermes/hermes-relay-sessions.json" "$VAR2/.hermes/plugin-data/hermes-relay/state" "$VAR2/.hermes/relay-signing-identity"; do [[ -f "$f" ]]; done
rm -rf "$TMP2"
