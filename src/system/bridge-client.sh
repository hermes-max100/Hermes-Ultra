#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${HERMES_BRIDGE_MANIFEST:-$ROOT_DIR/bridge/hermes_bridge_manifest.json}"
BASE_URL="${HERMES_BRIDGE_BASE_URL:-}"
COOKIE_JAR="${HERMES_BRIDGE_COOKIE_JAR:-$HOME/.hermes-bridge-cookies.txt}"

usage() {
    echo "Usage:"
    echo "  src/system/bridge-client.sh --summary"
    echo "  src/system/bridge-client.sh --list [category]"
    echo "  src/system/bridge-client.sh --find METHOD PATH"
    echo "  src/system/bridge-client.sh --curl METHOD PATH [json_body]"
    echo "  src/system/bridge-client.sh --request METHOD PATH [json_body]"
}

manifest_query() {
    local command="$1"
    local arg1="${2:-}"
    local arg2="${3:-}"
    MANIFEST="$MANIFEST" COMMAND="$command" ARG1="$arg1" ARG2="$arg2" python3 <<'PYEOF'
import json
import os

with open(os.environ["MANIFEST"], "r", encoding="utf-8") as handle:
    manifest = json.load(handle)

command = os.environ["COMMAND"]
arg1 = os.environ.get("ARG1", "")
arg2 = os.environ.get("ARG2", "")

def endpoints():
    for category in manifest["categories"]:
        for endpoint in category["endpoints"]:
            yield category, endpoint

if command == "summary":
    count = sum(1 for _ in endpoints())
    streaming = sum(1 for _, endpoint in endpoints() if endpoint.get("streaming"))
    print(json.dumps({
        "name": manifest["name"],
        "categories": len(manifest["categories"]),
        "endpoints": count,
        "streaming_endpoints": streaming,
        "base_url_env": manifest["base_url_env"],
        "auth_cookie": manifest["auth"]["cookie_name"],
    }, indent=2, sort_keys=True))
elif command == "list":
    rows = []
    for category, endpoint in endpoints():
        if arg1 and category["id"] != arg1:
            continue
        rows.append({
            "category": category["id"],
            "method": endpoint["method"],
            "path": endpoint["path"],
            "purpose": endpoint["purpose"],
            "streaming": endpoint.get("streaming", False),
        })
    print(json.dumps(rows, indent=2, sort_keys=True))
elif command == "find":
    method = arg1.upper()
    path = arg2
    for category, endpoint in endpoints():
        if endpoint["method"] == method and endpoint["path"] == path:
            print(json.dumps({
                "found": True,
                "category": category["id"],
                **endpoint,
            }, indent=2, sort_keys=True))
            break
    else:
        print(json.dumps({"found": False, "method": method, "path": path}, indent=2, sort_keys=True))
        raise SystemExit(3)
else:
    raise SystemExit(f"unknown command: {command}")
PYEOF
}

require_endpoint() {
    local method="$1"
    local path="$2"
    manifest_query find "$method" "$path" >/dev/null
}

curl_args() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local base="${BASE_URL%/}"
    [[ -z "$base" ]] && base='${HERMES_BRIDGE_BASE_URL}'

    printf "curl -sS -X %q" "$method"
    printf " -b %q -c %q" "$COOKIE_JAR" "$COOKIE_JAR"
    printf " -H %q" "Content-Type: application/json"
    if [[ -n "$body" ]]; then
        printf " --data %q" "$body"
    fi
    printf " %q\n" "${base}${path}"
}

request_endpoint() {
    local method="$1"
    local path="$2"
    local body="${3:-}"

    if [[ -z "$BASE_URL" ]]; then
        echo "HERMES_BRIDGE_BASE_URL is required for --request" >&2
        exit 1
    fi

    require_endpoint "$method" "$path"

    local args=(-sS -X "$method" -b "$COOKIE_JAR" -c "$COOKIE_JAR" -H "Content-Type: application/json")
    if [[ -n "$body" ]]; then
        args+=(--data "$body")
    fi
    curl "${args[@]}" "${BASE_URL%/}${path}"
}

case "${1:-}" in
    --summary)
        manifest_query summary ;;
    --list)
        manifest_query list "${2:-}" ;;
    --find)
        require_endpoint "${2:-}" "${3:-}"
        manifest_query find "${2:-}" "${3:-}" ;;
    --curl)
        require_endpoint "${2:-}" "${3:-}"
        curl_args "${2:-}" "${3:-}" "${4:-}" ;;
    --request)
        request_endpoint "${2:-}" "${3:-}" "${4:-}" ;;
    --help|-h|"")
        usage ;;
    *)
        echo "Unknown command: $1" >&2
        usage >&2
        exit 2 ;;
esac
