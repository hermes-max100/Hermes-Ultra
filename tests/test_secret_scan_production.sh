#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCANNER="$ROOT_DIR/scripts/secret-scan-production.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
[[ -x "$SCANNER" ]] || { echo 'production secret scanner missing' >&2; exit 1; }
SAFE="$TMP/safe.md"
cat > "$SAFE" <<'SAFE'
OPENAI_API_KEY=REDACTED
Authorization: Bearer <REDACTED>
Cookie: session=PLACEHOLDER
refresh_token=REDACTED
SAFE
bash "$SCANNER" "$SAFE" | grep -q '^SECRET_SCAN=PASS'
printf "apiKey: 'abc123abc123abc123abc'\napiKey: process.env.COMPOSIO_API_KEY\n" > "$TMP/instructional.md"
bash "$SCANNER" "$TMP/instructional.md" | grep -q '^SECRET_SCAN=PASS'
KEY_NAME='config_api_key'
KEY_FN='find_configured_api_key'
REFRESH_NAME='refresh_token'
printf '%s\n' \
  "$KEY_NAME = $KEY_FN(provider_info, api_key)" \
  "$REFRESH_NAME=request.$REFRESH_NAME," \
  "$REFRESH_NAME = stored_$REFRESH_NAME or \"\"" > "$TMP/source-code.py"
bash "$SCANNER" "$TMP/source-code.py" | grep -q '^SECRET_SCAN=PASS'
printf '%s\n' \
  'OPENAI_API_KEY=sk-test-super-secret' \
  'stderr="OPENAI_API_KEY=sk-test-super-secret client_secret=oauth-secret-value"' \
  > "$TMP/synthetic-redaction-fixture.py"
bash "$SCANNER" "$TMP/synthetic-redaction-fixture.py" | grep -q '^SECRET_SCAN=PASS'
GENERIC="A1b2C3d4E5f6G7h8J9k0LmNoPqRsTuVw"
printf 'service_api_key=%s\n' "$GENERIC" > "$TMP/generic.env"
if bash "$SCANNER" "$TMP/generic.env" >/dev/null 2>&1; then echo 'high-entropy generic API key accepted' >&2; exit 1; fi
SECRET1="sk-$(printf 'A%.0s' {1..40})"
SECRET2="$(printf 'B%.0s' {1..48})"
SECRET3="$(printf 'C%.0s' {1..48})"
SECRET4="$(printf 'D%.0s' {1..48})"
printf 'OPENAI_API_KEY=%s\n' "$SECRET1" > "$TMP/api.env"
printf 'Authorization: Bearer %s\n' "$SECRET2" > "$TMP/bearer.log"
printf 'Cookie: __Secure-1PSID=%s\n' "$SECRET3" > "$TMP/cookie.log"
printf 'refresh_token=%s\n' "$SECRET4" > "$TMP/oauth.json"
set +e
OUTPUT="$(bash "$SCANNER" "$TMP/api.env" "$TMP/bearer.log" "$TMP/cookie.log" "$TMP/oauth.json" 2>&1)"
RC=$?
set -e
[[ $RC -ne 0 ]] || { echo 'real-looking secrets accepted' >&2; exit 1; }
grep -q '^SECRET_SCAN=FAIL$' <<<"$OUTPUT"
grep -q 'detector=API_KEY' <<<"$OUTPUT"
grep -q 'detector=BEARER_TOKEN' <<<"$OUTPUT"
grep -q 'detector=BROWSER_SESSION_COOKIE' <<<"$OUTPUT"
grep -q 'detector=OAUTH_REFRESH_TOKEN' <<<"$OUTPUT"
for secret in "$SECRET1" "$SECRET2" "$SECRET3" "$SECRET4"; do
  ! grep -Fq "$secret" <<<"$OUTPUT" || { echo 'scanner leaked secret value' >&2; exit 1; }
done
REPO="$TMP/repo"; mkdir -p "$REPO"; git -C "$REPO" init -q
git -C "$REPO" config user.email test@example.invalid; git -C "$REPO" config user.name test
printf 'safe tracked file\n' > "$REPO/safe.txt"; git -C "$REPO" add .; git -C "$REPO" commit -qm safe
bash "$SCANNER" --tracked-root "$REPO" | grep -q '^SECRET_SCAN=PASS'
printf 'Authorization: Bearer %s\n' "$SECRET2" > "$REPO/leak.txt"; git -C "$REPO" add .; git -C "$REPO" commit -qm leak
if bash "$SCANNER" --tracked-root "$REPO" >/dev/null 2>&1; then echo 'tracked secret accepted' >&2; exit 1; fi
echo 'production secret scan tests passed'
