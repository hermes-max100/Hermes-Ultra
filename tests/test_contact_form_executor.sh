#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTACT="$ROOT_DIR/src/system/contact-form-executor.sh"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hermes-contact-form-test.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

# Production CLI help must not expose historical policy-off switches.
validate_help="$("$CONTACT" validate-handoff --help)"
if [[ "$validate_help" == *"--allow-private-network-for-test"* ]]; then
  echo "private-network bypass unexpectedly exposed" >&2
  exit 1
fi
if [[ "$validate_help" == *"--allow-duplicate"* ]]; then
  echo "duplicate-send bypass unexpectedly exposed" >&2
  exit 1
fi
submit_help="$("$CONTACT" submit --help)"
if [[ "$submit_help" != *"--containment-token-stdin"* ]]; then
  echo "containment token stdin requirement missing" >&2
  exit 1
fi
if [[ "$submit_help" == *"--allow-private-network-for-test"* || "$submit_help" == *"--allow-duplicate"* ]]; then
  echo "submit policy-off switch unexpectedly exposed" >&2
  exit 1
fi

python3 - "$ROOT_DIR/src/system/contact-form-executor.py" <<'PY'
import importlib.util
import sys

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("contact_form_executor_test", path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

assert module.same_site("https://forms.example.co.uk/contact", ["https://www.example.co.uk/"])
assert not module.same_site("https://forms.attacker.co.uk/contact", ["https://www.example.co.uk/"])
assert module.same_site("https://forms.example.com.au/contact", ["https://example.com.au/"])
assert not module.same_site("https://forms.attacker.com.au/contact", ["https://example.com.au/"])

private_errors = module.validate_public_url("http://127.0.0.1/contact")
assert any("blocked" in item for item in private_errors), private_errors
metadata_errors = module.validate_public_url("http://169.254.169.254/latest/meta-data/")
assert any("blocked" in item for item in metadata_errors), metadata_errors
assert not module.request_is_authorized("https://attacker.invalid/pixel", "https://example.com/contact")
assert not module.request_is_authorized("http://127.0.0.1/admin", "http://127.0.0.1/contact")
assert module.request_is_authorized("data:text/plain,ok", "https://example.com/contact")

parser = module.build_parser()
sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
submit = sub.choices["submit"]
opts = {opt for action in submit._actions for opt in action.option_strings}
assert "--containment-token-stdin" in opts
assert "--containment-token" not in opts
assert "--allow-private-network-for-test" not in opts
assert "--allow-duplicate" not in opts
PY

python3 -m py_compile \
  "$ROOT_DIR/src/system/contact-form-executor.py" \
  "$ROOT_DIR/src/system/contact-form-executor-core.py"

echo "contact form executor tests passed"
