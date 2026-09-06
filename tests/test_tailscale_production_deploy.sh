#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/tailscale-production-deploy.yml"
DEPLOY="$ROOT/scripts/deploy-cloud-release-tailscale.sh"
POLICY="$ROOT/config/tailscale-production-policy.json"
BOOTSTRAP="$ROOT/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"

[[ -x "$DEPLOY" ]] || { echo 'Tailscale deploy script is not executable' >&2; exit 1; }
python3 -m json.tool "$POLICY" >/dev/null
grep -q 'workflow_dispatch:' "$WORKFLOW"
! grep -qE '^  (push|pull_request):' "$WORKFLOW"
grep -q 'environment: production' "$WORKFLOW"
grep -q 'tailscale/github-action@[0-9a-f]\{40\}' "$WORKFLOW"
grep -q 'TS_OAUTH_CLIENT_ID' "$WORKFLOW"
grep -q 'TS_OAUTH_SECRET' "$WORKFLOW"
grep -q 'tag:hermes-ci' "$WORKFLOW"
grep -q 'deploy-cloud-release-tailscale.sh' "$WORKFLOW"
grep -q 'tailscale ping' "$DEPLOY"
grep -q 'sha256sum -c' "$DEPLOY"
grep -q 'install-cloud-release-local.sh' "$DEPLOY"
grep -q 'StrictHostKeyChecking=accept-new' "$DEPLOY"
grep -q 'api/health' "$DEPLOY"
grep -q 'tailscale serve status' "$DEPLOY"
grep -q -- '--advertise-tags=tag:hermes-prod' "$BOOTSTRAP"
grep -q -- '--ssh' "$BOOTSTRAP"
grep -q '"ip": \["tcp:22"\]' "$POLICY"
grep -q '"users": \["ubuntu"\]' "$POLICY"
! grep -qE '0\.0\.0\.0/0|::/0' "$POLICY"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"
mkdir -p "$BIN"
cat >"$BIN/tailscale" <<'TS'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == status ]]; then
  if [[ "${FAKE_TS_OFFLINE:-0}" == 1 ]]; then
    printf '%s\n' '{"BackendState":"NeedsLogin","Self":{"Online":false}}'
  else
    printf '%s\n' '{"BackendState":"Running","Self":{"Online":true}}'
  fi
elif [[ "${1:-}" == ping ]]; then
  printf 'ping %s\n' "${2:-}" >>"$FAKE_TS_LOG"
else
  exit 2
fi
TS
cat >"$BIN/ssh" <<'SSH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_SSH_LOG"
SSH
cat >"$BIN/scp" <<'SCP'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_SCP_LOG"
SCP
chmod +x "$BIN/tailscale" "$BIN/ssh" "$BIN/scp"

ARCHIVE="$TMP/hermes-release.tar.gz"
printf 'verified fixture\n' >"$ARCHIVE"
( cd "$TMP" && sha256sum "$(basename "$ARCHIVE")" >"$(basename "$ARCHIVE").sha256" )
export FAKE_TS_LOG="$TMP/tailscale.log"
export FAKE_SSH_LOG="$TMP/ssh.log"
export FAKE_SCP_LOG="$TMP/scp.log"
PATH="$BIN:$PATH" bash "$DEPLOY" hermes-max "$ARCHIVE" ubuntu >/dev/null
grep -q '^ping hermes-max$' "$FAKE_TS_LOG"
grep -q 'sudo bash' "$FAKE_SSH_LOG"
grep -q 'api/health' "$FAKE_SSH_LOG"
grep -q 'hermes-runtime.service' "$FAKE_SSH_LOG"
grep -q 'hermes-relay.service' "$FAKE_SSH_LOG"
[[ "$(wc -l <"$FAKE_SCP_LOG")" == 2 ]]

if FAKE_TS_OFFLINE=1 PATH="$BIN:$PATH" bash "$DEPLOY" hermes-max "$ARCHIVE" ubuntu >/dev/null 2>&1; then
  echo 'offline tailnet was accepted' >&2
  exit 1
fi
echo 'TAILSCALE_PRODUCTION_DEPLOY_TEST=PASS'
