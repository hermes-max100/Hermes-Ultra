#!/usr/bin/env bash
set -euo pipefail
SOURCE_ROOT="${1:?source root required}"
OUTPUT="${2:?output path required}"
BUILD_UTC="${3:?build UTC required}"
PINS="$SOURCE_ROOT/config/production-versions.json"
[[ -f "$PINS" ]] || { echo 'production version pins missing' >&2; exit 1; }
COMMIT="$(git -C "$SOURCE_ROOT" rev-parse HEAD)"
BRANCH="$(git -C "$SOURCE_ROOT" branch --show-current)"
PINS_SHA="$(sha256sum "$PINS" | awk '{print $1}')"
python3 - "$OUTPUT" "$COMMIT" "$BRANCH" "$BUILD_UTC" "$PINS_SHA" <<'PY'
import json, pathlib, sys
out, commit, branch, build_utc, pins_sha = sys.argv[1:]
data = {
    "schema_version": 1,
    "source_commit": commit,
    "source_branch": branch,
    "build_utc": build_utc,
    "production_pins_sha256": pins_sha,
    "builder_class": "local",
    "archive_format_version": 1,
}
pathlib.Path(out).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
