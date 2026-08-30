#!/usr/bin/env bash
set -euo pipefail
MIN_MAJOR="${HERMES_NODE_MIN_MAJOR:-18}"
ALLOW_INSTALL="${HERMES_NODE_ALLOW_INSTALL:-1}"

node_ready() {
  command -v node >/dev/null 2>&1 || return 1
  command -v npm >/dev/null 2>&1 || return 1
  command -v npx >/dev/null 2>&1 || return 1
  local raw major
  raw="$(node --version 2>/dev/null || true)"
  raw="${raw#v}"
  major="${raw%%.*}"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  (( major >= MIN_MAJOR ))
}

if node_ready; then
  printf 'NODE_RUNTIME=PASS version=%s npm=%s npx=%s\n' "$(node --version)" "$(npm --version 2>/dev/null || echo unknown)" "$(npx --version 2>/dev/null || echo unknown)"
  exit 0
fi

[[ "$ALLOW_INSTALL" == 1 ]] || { echo "Node.js >= $MIN_MAJOR with npm/npx is required" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || { echo 'Node runtime installation requires root' >&2; exit 1; }
command -v apt-get >/dev/null 2>&1 || { echo 'apt-get is required to install the Node runtime' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends nodejs npm
node_ready || { echo "installed Node runtime does not satisfy Node.js >= $MIN_MAJOR with npm/npx" >&2; exit 1; }
printf 'NODE_RUNTIME=PASS version=%s npm=%s npx=%s\n' "$(node --version)" "$(npm --version)" "$(npx --version)"
