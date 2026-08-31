#!/usr/bin/env bash
set -euo pipefail
NODE_VERSION="${HERMES_NODE_VERSION:-22.23.2}"
MIN_MAJOR="${HERMES_NODE_MIN_MAJOR:-22}"
ALLOW_INSTALL="${HERMES_NODE_ALLOW_INSTALL:-1}"
INSTALL_BASE="${HERMES_NODE_INSTALL_BASE:-/opt/hermes-node}"

node_ready() {
  command -v node >/dev/null 2>&1 || return 1
  command -v npm >/dev/null 2>&1 || return 1
  command -v npx >/dev/null 2>&1 || return 1
  local raw major
  raw="$(node --version 2>/dev/null || true)"; raw="${raw#v}"; major="${raw%%.*}"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  (( major >= MIN_MAJOR ))
}

if node_ready; then
  printf 'NODE_RUNTIME=PASS version=%s npm=%s npx=%s\n' "$(node --version)" "$(npm --version 2>/dev/null || echo unknown)" "$(npx --version 2>/dev/null || echo unknown)"
  exit 0
fi

[[ "$ALLOW_INSTALL" == 1 ]] || { echo "Node.js >= $MIN_MAJOR with npm/npx is required" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || { echo 'Node runtime installation requires root' >&2; exit 1; }
for cmd in curl sha256sum tar uname; do command -v "$cmd" >/dev/null 2>&1 || { echo "required Node installer command missing: $cmd" >&2; exit 1; }; done

case "$(uname -m)" in
  x86_64|amd64) ARCH=x64; SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307 ;;
  aarch64|arm64) ARCH=arm64; SHA256=fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8 ;;
  *) echo "unsupported Node runtime architecture: $(uname -m)" >&2; exit 1 ;;
esac
NAME="node-v${NODE_VERSION}-linux-${ARCH}"
URL="https://nodejs.org/dist/v${NODE_VERSION}/${NAME}.tar.xz"
TARGET="$INSTALL_BASE/v${NODE_VERSION}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 "$URL" -o "$TMP/node.tar.xz"
echo "$SHA256  $TMP/node.tar.xz" | sha256sum -c - >/dev/null
rm -rf "$TARGET"; mkdir -p "$TARGET"
tar -xJf "$TMP/node.tar.xz" --strip-components=1 -C "$TARGET"
for cmd in node npm npx corepack; do [[ -e "$TARGET/bin/$cmd" ]] && ln -sfn "$TARGET/bin/$cmd" "/usr/local/bin/$cmd"; done
node_ready || { echo "installed Node runtime does not satisfy Node.js >= $MIN_MAJOR with npm/npx" >&2; exit 1; }
printf 'NODE_RUNTIME=PASS version=%s npm=%s npx=%s\n' "$(node --version)" "$(npm --version)" "$(npx --version)"
