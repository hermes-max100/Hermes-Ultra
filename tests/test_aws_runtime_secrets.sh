#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/src/system/load-aws-runtime-secrets.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"; mkdir -p "$BIN"
cat > "$BIN/aws" <<'AWS'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1 $2" == 'ssm get-parameters-by-path' ]] || exit 2
if [[ "${FAKE_UNKNOWN:-0}" == 1 ]]; then
  cat <<'JSON'
{"Parameters":[{"Name":"/hermes-max/runtime/NVIDIA_API_KEY","Value":"nvidia-test-secret"},{"Name":"/hermes-max/runtime/UNEXPECTED_KEY","Value":"must-not-leak"}]}
JSON
else
  cat <<'JSON'
{"Parameters":[{"Name":"/hermes-max/runtime/NVIDIA_API_KEY","Value":"nvidia-test-secret"},{"Name":"/hermes-max/runtime/OPENROUTER_API_KEY","Value":"openrouter-test-secret"},{"Name":"/hermes-max/runtime/VENICE_API_KEY","Value":"venice-test-secret"},{"Name":"/hermes-max/runtime/GOOGLE_API_KEY","Value":"google-test-secret"}]}
JSON
fi
AWS
chmod +x "$BIN/aws"
[[ -x "$SCRIPT" ]] || { echo 'AWS runtime secret loader missing' >&2; exit 1; }
OUTFILE="$TMP/runtime.env"
printf 'OLD=unsafe\n' > "$OUTFILE"; chmod 644 "$OUTFILE"
OUTPUT="$(PATH="$BIN:$PATH" HERMES_RUNTIME_ENV_PATH="$OUTFILE" bash "$SCRIPT" 2>&1)"
[[ "$(stat -c '%a' "$OUTFILE")" == 600 ]] || { echo 'runtime env permissions not 600' >&2; exit 1; }
grep -q '^NVIDIA_API_KEY=nvidia-test-secret$' "$OUTFILE"
grep -q '^OPENROUTER_API_KEY=openrouter-test-secret$' "$OUTFILE"
grep -q '^VENICE_API_KEY=venice-test-secret$' "$OUTFILE"
grep -q '^GOOGLE_API_KEY=google-test-secret$' "$OUTFILE"
! grep -Eq 'nvidia-test-secret|openrouter-test-secret|venice-test-secret|google-test-secret' <<<"$OUTPUT"
grep -q '^AWS_RUNTIME_SECRETS=PASS count=4$' <<<"$OUTPUT"
UNKNOWN="$TMP/unknown.env"
if PATH="$BIN:$PATH" FAKE_UNKNOWN=1 HERMES_RUNTIME_ENV_PATH="$UNKNOWN" bash "$SCRIPT" >"$TMP/unknown.out" 2>&1; then echo 'unknown secret key accepted' >&2; exit 1; fi
[[ ! -e "$UNKNOWN" ]] || { echo 'unknown-key failure wrote destination' >&2; exit 1; }
! grep -q 'must-not-leak' "$TMP/unknown.out"
grep -q 'unknown runtime secret key: UNEXPECTED_KEY' "$TMP/unknown.out"
grep -q 'ssm:GetParameter' "$ROOT_DIR/infra/aws-primary/main.tf"
grep -q 'ssm:GetParametersByPath' "$ROOT_DIR/infra/aws-primary/main.tf"
grep -q 'runtime_ssm_parameter_prefix' "$ROOT_DIR/infra/aws-primary/variables.tf"
! grep -q 'resource "aws_ssm_parameter"' "$ROOT_DIR/infra/aws-primary/main.tf"
echo 'AWS runtime secret tests passed'
