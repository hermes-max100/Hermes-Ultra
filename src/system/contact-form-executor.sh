#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXECUTOR="$ROOT_DIR/src/system/contact-form-executor.py"
JARVIS_PY="$ROOT_DIR/.hermes/jarvis/JARVIS-OS-v1.2.0-tool-armory/.venv/bin/python"

if [[ -n "${HERMES_CONTACT_FORM_PYTHON:-}" ]]; then
  PYTHON="$HERMES_CONTACT_FORM_PYTHON"
elif [[ -x "$JARVIS_PY" ]]; then
  PYTHON="$JARVIS_PY"
else
  PYTHON="python3"
fi

usage() {
  cat <<'EOF'
Hermes Contact Form Executor v1

Usage:
  src/system/contact-form-executor.sh init
  src/system/contact-form-executor.sh validate-handoff --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl
  src/system/contact-form-executor.sh submit --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl --operator-name NAME --operator-email EMAIL
  src/system/contact-form-executor.sh doctor

Purpose:
  Execute approved official public contact-form handoffs after campaign policy,
  approval receipt, source evidence, URL/domain, duplicate-prevention, form-field,
  and browser evidence checks pass.

Boundary:
  No prospect discovery, no offer mutation, no account/login flows, no CAPTCHA
  bypass, no payment/credential/upload fields, no private targets, and no sent
  stage until positive form-submission evidence is sealed.
EOF
}

case "${1:-}" in
  help|-h|--help|"")
    usage
    ;;
  *)
    "$PYTHON" "$EXECUTOR" "$@"
    ;;
esac
