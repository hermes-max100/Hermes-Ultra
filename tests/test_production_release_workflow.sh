#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WF="$ROOT/.github/workflows/production-release-build.yml"
grep -q 'repository: Codename-11/hermes-relay' "$WF"
grep -q 'ref: f4b366389ba8081136e81ca1b76deb31ef844cce' "$WF"
grep -q 'hermes_relay-1.11.1-py3-none-any.whl' "$WF"
grep -q '251342d4ddd9d0e55563f9185850764cf5f43200d54c120c6719329f311e76a0' "$WF"
grep -q 'HERMES_RELAY_SOURCE_DIR:' "$WF"
grep -q 'HERMES_RELAY_SERVER_WHEEL:' "$WF"
grep -q 'vendor/hermes-relay/server-v1.11.1/SOURCE_PROVENANCE.json' "$WF"
grep -q "find .*'\\*.pyc'" "$WF"
echo PRODUCTION_RELEASE_WORKFLOW=PASS
