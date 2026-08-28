#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPDIR="$(readlink -f "$INSTALL_ROOT/current")"
ELECTRON="$APPDIR/orca-ide"
CLI_ENTRY="$APPDIR/resources/app.asar.unpacked/out/cli/index.js"

[[ -x "$ELECTRON" ]] || { echo 'Orca Electron runtime is missing' >&2; exit 1; }
[[ -f "$CLI_ENTRY" ]] || { echo 'Orca CLI entrypoint is missing' >&2; exit 1; }

export DO_NOT_TRACK=1
export ORCA_TELEMETRY_DISABLED=1
export ORCA_NODE_OPTIONS="${NODE_OPTIONS-}"
export ORCA_NODE_REPL_EXTERNAL_MODULE="${NODE_REPL_EXTERNAL_MODULE-}"
unset NODE_OPTIONS
unset NODE_REPL_EXTERNAL_MODULE
export ORCA_CLI_ENTRY="$CLI_ENTRY"

CLI_SCRIPT='(async()=>{try{const cli=process.env.ORCA_CLI_ENTRY;await Promise.resolve(require(cli).main(process.argv.slice(1)));}catch(error){console.error(error&&error.stack?error.stack:String(error));process.exit(1);}})();'
ELECTRON_RUN_AS_NODE=1 exec "$ELECTRON" -e "$CLI_SCRIPT" -- "$@"
