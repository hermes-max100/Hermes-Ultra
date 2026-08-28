#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"; mkdir -p "$BIN"
cat > "$BIN/aws" <<'AWS'
#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  'sts get-caller-identity')
    [[ "${FAKE_AWS_AUTH:-ok}" == ok ]] || exit 253
    echo '{"Account":"123456789012","Arn":"arn:aws:iam::123456789012:user/test"}' ;;
  'ec2 describe-instance-types')
    printf '{"InstanceTypes":[{"InstanceType":"%s","VCpuInfo":{"DefaultVCpus":%s},"MemoryInfo":{"SizeInMiB":%s}}]}\n' "${FAKE_TYPE:-m7i-flex.large}" "${FAKE_VCPU:-2}" "${FAKE_RAM:-8192}" ;;
  'pricing get-products') echo '{"PriceList":[]}' ;;
  'budgets describe-budgets') echo '{"Budgets":[]}' ;;
  *) echo "unexpected aws call: $*" >&2; exit 2 ;;
esac
AWS
chmod +x "$BIN/aws"
cat > "$BIN/tailscale" <<'TS'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == 'status --json' ]]; then
  [[ "${FAKE_TS_STATE:-Running}" == Running ]] && echo '{"BackendState":"Running","Self":{"Online":true}}' || echo '{"BackendState":"NeedsLogin","Self":{"Online":false}}'
elif [[ "$1 $2" == 'ip -4' ]]; then
  echo '100.64.0.10'
elif [[ "$1" == serve ]]; then
  printf '%s\n' "$*" > "${FAKE_TS_LOG:?}"
else
  exit 2
fi
TS
chmod +x "$BIN/tailscale"
cat > "$BIN/orca-installer" <<'ORCA'
#!/usr/bin/env bash
set -euo pipefail
printf 'address=%s\n' "${ORCA_PAIRING_ADDRESS:?}" > "${FAKE_ORCA_LOG:?}"
ORCA
chmod +x "$BIN/orca-installer"

OUT="$(PATH="$BIN:$PATH" bash "$ROOT_DIR/scripts/aws-production-preflight.sh")"
grep -q '^AWS_AUTH=PASS$' <<<"$OUT"
grep -q '^INSTANCE_LAUNCHABLE=PASS$' <<<"$OUT"
grep -q '^VCPU=2$' <<<"$OUT"
grep -q '^RAM_MIB=8192$' <<<"$OUT"
grep -q '^REGION=us-east-1$' <<<"$OUT"
if PATH="$BIN:$PATH" FAKE_TYPE=t3.small bash "$ROOT_DIR/scripts/aws-production-preflight.sh" >/dev/null 2>&1; then echo 'wrong instance type accepted' >&2; exit 1; fi
if PATH="$BIN:$PATH" FAKE_AWS_AUTH=bad bash "$ROOT_DIR/scripts/aws-production-preflight.sh" >"$TMP/auth.out" 2>&1; then echo 'missing AWS credentials accepted' >&2; exit 1; fi
grep -q '^AWS_AUTH=FAIL$' "$TMP/auth.out"
if PATH="$BIN:$PATH" FAKE_TS_STATE=NeedsLogin FAKE_TS_LOG="$TMP/ts.log" ORCA_INSTALLER="$BIN/orca-installer" FAKE_ORCA_LOG="$TMP/orca.log" bash "$ROOT_DIR/scripts/configure-tailscale-hermes.sh" >/dev/null 2>&1; then echo 'logged-out Tailscale accepted' >&2; exit 1; fi
[[ ! -f "$TMP/orca.log" ]]
PATH="$BIN:$PATH" FAKE_TS_LOG="$TMP/ts.log" ORCA_INSTALLER="$BIN/orca-installer" FAKE_ORCA_LOG="$TMP/orca.log" bash "$ROOT_DIR/scripts/configure-tailscale-hermes.sh" >/dev/null
grep -q '^serve --bg --yes http://127.0.0.1:9119$' "$TMP/ts.log"
grep -q '^address=100.64.0.10$' "$TMP/orca.log"
! grep -qi funnel "$ROOT_DIR/scripts/configure-tailscale-hermes.sh"
echo 'AWS production preflight tests passed'
