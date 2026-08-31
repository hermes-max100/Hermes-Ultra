#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/ensure-node-runtime.sh"
INSTALLER="$ROOT_DIR/scripts/install-cloud-release-local.sh"
BOOT="$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"

[[ -f "$SCRIPT" ]] || { echo 'ensure-node-runtime.sh missing' >&2; exit 1; }
bash -n "$SCRIPT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat >"$TMP/bin/node" <<'EOF'
#!/usr/bin/env bash
echo v22.23.2
EOF
for cmd in npm npx; do printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/bin/$cmd"; done
chmod +x "$TMP/bin/node" "$TMP/bin/npm" "$TMP/bin/npx"
PATH="$TMP/bin:/usr/bin:/bin" HERMES_NODE_ALLOW_INSTALL=0 bash "$SCRIPT" | grep -q 'NODE_RUNTIME=PASS'
cat >"$TMP/bin/node" <<'EOF'
#!/usr/bin/env bash
echo v18.20.8
EOF
chmod +x "$TMP/bin/node"
if PATH="$TMP/bin:/usr/bin:/bin" HERMES_NODE_ALLOW_INSTALL=0 bash "$SCRIPT" >/dev/null 2>&1; then
  echo 'Node 18 runtime was incorrectly accepted' >&2; exit 1
fi

grep -q 'NODE_VERSION="${HERMES_NODE_VERSION:-22.23.2}"' "$SCRIPT" || { echo 'Node runtime is not pinned to 22.23.2' >&2; exit 1; }
grep -q 'd60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307' "$SCRIPT" || { echo 'Node x64 checksum pin missing' >&2; exit 1; }
grep -q 'sha256sum -c' "$SCRIPT" || { echo 'Node runtime download is not checksum verified' >&2; exit 1; }
grep -q '/usr/local/bin' "$SCRIPT" || { echo 'Node runtime is not exposed through stable path' >&2; exit 1; }

grep -q 'ensure-node-runtime.sh' "$INSTALLER" || { echo 'installer does not own Node runtime prerequisite' >&2; exit 1; }
grep -q 'sync-mcp-provider-registry.sh' "$INSTALLER" || { echo 'installer does not apply MCP provider registry' >&2; exit 1; }
grep -Eq 'nodejs.*npm|npm.*nodejs' "$BOOT" || { echo 'fresh-host bootstrap does not provision Node/npm' >&2; exit 1; }
echo 'NODE_RUNTIME_PREREQUISITE_TEST=PASS'
