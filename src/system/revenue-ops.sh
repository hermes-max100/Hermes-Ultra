#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="virtual-creator"
PROFILE_FILE="${HERMES_VIRTUAL_CREATOR_PROFILE:-$ROOT_DIR/config/virtual-creator-profile.example.json}"
REPORT_ROOT="${HERMES_REVENUE_REPORT_DIR:-$ROOT_DIR/.hermes/reports/revenue}"
YOLO_GATE="$ROOT_DIR/src/system/yolo-gate.sh"
AGENT_REACH="$ROOT_DIR/src/system/agent-reach.sh"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"

usage() {
  cat <<'EOF'
Hermes Revenue Ops

Usage:
  src/system/revenue-ops.sh [--profile virtual-creator] <command> [options]

Commands:
  scan                    Create a local trend/source scan report.
  package                 Create a local offer package report.
  content-calendar        Create a 7-day content calendar draft.
  compliance-check        Check a draft or text file for virtual creator risks.
  analytics               Append or summarize local analytics.
  report                  Create a consolidated local status report.

Options:
  --profile <name>        Profile name. Default: virtual-creator.
  --profile-file <path>   Profile JSON. Default: config/virtual-creator-profile.example.json.
  --days <n>              Calendar days. Default: 7.
  --text <text>           Draft text for compliance-check.
  --file <path>           Draft text file for compliance-check.
  --platform <name>       Analytics platform.
  --topic <text>          Analytics topic.
  --format <text>         Analytics content format.
  --views <n>             Analytics views.
  --likes <n>             Analytics likes.
  --comments <n>          Analytics comments.
  --saves <n>             Analytics saves.
  --profile-clicks <n>    Analytics profile clicks.
  --link-clicks <n>       Analytics link clicks.
  --leads <n>             Analytics leads.
  --sales <n>             Analytics sales.
  --cost-usd <n>          Analytics cost.

Safety:
  This driver writes local reports only. It has no send, post, delete, purchase,
  credential, permission, or account-setting commands.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

json_value() {
  local selector="$1"
  python3 - "$PROFILE_FILE" "$selector" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
selector = sys.argv[2].split(".")
data = json.loads(path.read_text(encoding="utf-8"))
value = data
for part in selector:
    if isinstance(value, dict):
        value = value.get(part, "")
    else:
        value = ""
if isinstance(value, (list, dict)):
    print(json.dumps(value))
else:
    print(value)
PY
}

report_dir() {
  printf '%s/%s\n' "$REPORT_ROOT" "$PROFILE"
}

ensure_profile() {
  [[ "$PROFILE" == "virtual-creator" ]] || die "unsupported profile: $PROFILE"
  [[ -f "$PROFILE_FILE" ]] || die "profile file missing: $PROFILE_FILE"
  python3 -m json.tool "$PROFILE_FILE" >/dev/null
  mkdir -p "$(report_dir)"
}

yolo_metadata() {
  if [[ -x "$YOLO_GATE" ]]; then
    HERMES_YOLO_MODE="${HERMES_YOLO_MODE:-retrieval}" "$YOLO_GATE" check "$1" 2>/dev/null || true
  else
    printf 'decision=unavailable\nreason=yolo_gate_missing\n'
  fi
}

agent_reach_status() {
  if [[ -x "$AGENT_REACH" ]]; then
    "$AGENT_REACH" status 2>/dev/null || true
  else
    printf 'agent_reach=missing\n'
  fi
}

cmd_scan() {
  ensure_profile
  local out niche
  niche="$(json_value niche)"
  out="$(report_dir)/trend-scan-$STAMP.md"
  {
    printf '# Virtual Creator Trend Scan - %s\n\n' "$STAMP"
    printf 'Profile: `%s`\n\n' "$PROFILE"
    printf 'Niche: %s\n\n' "$niche"
    printf '## Gate\n\n```text\n'
    yolo_metadata "scan public sources for virtual creator content trends and revenue opportunities"
    printf '```\n\n'
    printf '## Agent Reach Status\n\n```text\n'
    agent_reach_status
    printf '```\n\n'
    printf '## Seed Trend Queue\n\n'
    printf '| Trend | Platform | Evidence | Fit | Risk | Next Angle |\n'
    printf '|---|---|---|---:|---|---|\n'
    printf '| Missed lead follow-up automation | Reddit/X-indexed/public web | Small businesses discuss outcomes, not AI tooling | 9 | low | Show how many inquiries never get a second touch |\n'
    printf '| Simple CRM plus Gmail/SMS workflow | GitHub/creator economy/public web | Automation service offers are easy to explain and deliver | 8 | low | Break down a 3-step pipeline |\n'
    printf '| AI-disclosed virtual founder/operator | X/Instagram/public web | Synthetic creators are a content wrapper, not proof of revenue | 6 | medium | Be transparent: AI character, real service |\n'
    printf '\n## Boundaries\n\n'
    printf '%s\n' '- Read-only collection.'
    printf '%s\n' '- No private session scraping.'
    printf '%s\n' '- No posting, messaging, liking, following, or account changes.'
    printf '%s\n' '- Treat income screenshots and viral revenue claims as unverified.'
  } > "$out"
  printf 'report=%s\n' "$out"
}

cmd_package() {
  ensure_profile
  local out offer
  offer="$(json_value monetization.primary_offer)"
  out="$(report_dir)/offer-package-$STAMP.md"
  {
    printf '# Virtual Creator Offer Package - %s\n\n' "$STAMP"
    printf 'Primary offer: %s\n\n' "$offer"
    printf '## Positioning\n\n'
    printf 'I build simple AI-assisted lead capture and follow-up systems that help local service businesses recover missed inquiries, follow up with quotes, and get more booked calls without adding admin work.\n\n'
    printf '## Offer Ladder\n\n'
    printf '| Tier | Price | Deliverable |\n'
    printf '|---|---:|---|\n'
    printf '| Audit | 97 | Current lead follow-up review and missed inquiry map |\n'
    printf '| Setup Lite | 497 | One lead form, one inbox rule, one follow-up sequence, one dashboard |\n'
    printf '| Setup Pro | 1500 | CRM pipeline, Gmail/SMS draft flow, quote follow-up, analytics report |\n'
    printf '| Retainer | 500/month | Weekly optimization and reporting |\n\n'
    printf '## Claims Gate\n\n'
    printf '%s\n' '- Do not claim revenue, clients, or results without evidence.'
    printf '%s\n' '- The virtual creator can market the offer, but the creator must be disclosed as AI-generated where required or potentially misleading.'
  } > "$out"
  printf 'report=%s\n' "$out"
}

cmd_content_calendar() {
  ensure_profile
  local days="$1" out disclosure
  disclosure="$(json_value disclosure)"
  out="$(report_dir)/content-calendar-$STAMP.md"
  {
    printf '# Virtual Creator Content Calendar - %s\n\n' "$STAMP"
    printf 'Disclosure: %s\n\n' "$disclosure"
    printf '| Day | Format | Pillar | Hook | CTA | Disclosure Note | Approval |\n'
    printf '|---:|---|---|---|---|---|---|\n'
    local i
    for ((i=1; i<=days; i++)); do
      case $(((i - 1) % 7)) in
        0) printf '| %s | Reel/short | Problem awareness | How many quote requests never get a follow-up? | Comment "audit" | AI-generated creator media disclosed | human before post |\n' "$i" ;;
        1) printf '| %s | Carousel/thread | Tool breakdown | A simple CRM plus Gmail follow-up stack | Save/share | AI-generated creator media disclosed | human before post |\n' "$i" ;;
        2) printf '| %s | Short video | Process proof | A 3-step missed-lead recovery flow | Ask for audit | AI-generated creator media disclosed | human before post |\n' "$i" ;;
        3) printf '| %s | Text post | Operator POV | What I would automate first in a cleaning business | Reply with niche | AI disclosure if avatar shown | human before post |\n' "$i" ;;
        4) printf '| %s | Reel/short | Offer | I set this up for service businesses | Book call/manual DM | AI-generated creator media disclosed | human before post |\n' "$i" ;;
        5) printf '| %s | Story/post | Behind the scenes | Building the follow-up dashboard | Poll | AI disclosure if avatar shown | human before post |\n' "$i" ;;
        6) printf '| %s | Report post | Lessons learned | What the analytics showed this week | Join list | AI disclosure if avatar shown | human before post |\n' "$i" ;;
      esac
    done
  } > "$out"
  printf 'report=%s\n' "$out"
}

compliance_decision() {
  local text="$1"
  DRAFT_TEXT="$text" python3 <<'PY'
import json
import os
import re

text = os.environ.get("DRAFT_TEXT", "")
lower = text.lower()
required_changes = []
unsupported = []
decision = "pass"

block_patterns = [
    ("hidden synthetic identity", r"nobody knows|can't tell.*ai|pretend.*real|looks 100% real|indistinguishable from a real person"),
    ("stolen or real-person likeness", r"look like (taylor swift|selena gomez|kim kardashian|a real person|this person)|celebrity lookalike"),
    ("fake earnings claim", r"\$\s?[0-9][0-9,]*(k|\+)?\s?(per month|/month|monthly)|guaranteed.*(income|revenue|sales)"),
    ("fake relationship claim", r"your girlfriend|real girl|she is real|romantic relationship|intimate relationship"),
    ("auto public action", r"\b(auto[- ]?post|send automatically|dm automatically|delete automatically)\b"),
]
revise_patterns = [
    ("missing disclosure", r"\b(ai-generated|virtual creator|synthetic creator|ai disclosed)\b"),
]

reasons = []
for label, pattern in block_patterns:
    if re.search(pattern, lower):
        reasons.append(label)
        decision = "block"

if not re.search(revise_patterns[0][1], lower):
    required_changes.append("Add clear AI-generated / virtual creator disclosure.")
    if decision != "block":
        decision = "revise"

unsupported_patterns = [
    r"\b(best|#1)\b.*\b(system|tool|service|offer|automation)\b",
    r"\bproven to\b|\bproven results\b",
    r"\b(always|never)\b.*\b(fails?|works?|guarantees?|wins?|converts?)\b",
    r"\b[0-9]+%\s*(increase|lift|growth|conversion|roi|return)\b",
    r"\b(results?|revenue|sales|clients?)\b.*\b(guaranteed|proven|expected|assured)\b",
]
if any(re.search(pattern, lower) for pattern in unsupported_patterns):
    unsupported.append("Potentially unsupported performance claim; verify or soften.")
    if decision == "pass":
        decision = "revise"

payload = {
    "decision": decision,
    "reasons": reasons,
    "required_changes": required_changes,
    "disclosure_status": "present" if not required_changes else "missing_or_insufficient",
    "unsupported_claims": unsupported,
    "likeness_or_deception_risk": "high" if reasons else ("medium" if required_changes else "low"),
    "approval_required": True,
    "human_required_actions": ["post", "send", "delete", "account_change", "purchase", "credentials", "permissions"],
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

cmd_compliance_check() {
  ensure_profile
  local text="$1" out
  out="$(report_dir)/compliance-check-$STAMP.json"
  compliance_decision "$text" > "$out"
  printf 'report=%s\n' "$out"
  cat "$out"
}

cmd_analytics() {
  ensure_profile
  shift || true
  local platform="${ANALYTICS_PLATFORM:-manual}"
  local topic="${ANALYTICS_TOPIC:-unspecified}"
  local format="${ANALYTICS_FORMAT:-post}"
  local views="${ANALYTICS_VIEWS:-0}"
  local likes="${ANALYTICS_LIKES:-0}"
  local comments="${ANALYTICS_COMMENTS:-0}"
  local saves="${ANALYTICS_SAVES:-0}"
  local profile_clicks="${ANALYTICS_PROFILE_CLICKS:-0}"
  local link_clicks="${ANALYTICS_LINK_CLICKS:-0}"
  local leads="${ANALYTICS_LEADS:-0}"
  local sales="${ANALYTICS_SALES:-0}"
  local cost_usd="${ANALYTICS_COST_USD:-0}"
  local ledger
  ledger="$(report_dir)/analytics.jsonl"
  python3 - "$ledger" "$platform" "$topic" "$format" "$views" "$likes" "$comments" "$saves" "$profile_clicks" "$link_clicks" "$leads" "$sales" "$cost_usd" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ledger = Path(sys.argv[1])
payload = {
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "platform": sys.argv[2],
    "topic": sys.argv[3],
    "format": sys.argv[4],
    "views": int(sys.argv[5]),
    "likes": int(sys.argv[6]),
    "comments": int(sys.argv[7]),
    "saves": int(sys.argv[8]),
    "profile_clicks": int(sys.argv[9]),
    "link_clicks": int(sys.argv[10]),
    "leads": int(sys.argv[11]),
    "sales": int(sys.argv[12]),
    "cost_usd": float(sys.argv[13]),
}
ledger.parent.mkdir(parents=True, exist_ok=True)
with ledger.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
print(f"ledger={ledger}")
print(json.dumps(payload, indent=2, sort_keys=True))
PY
}

cmd_report() {
  ensure_profile
  local out
  out="$(report_dir)/status-report-$STAMP.md"
  {
    printf '# Virtual Creator Revenue Status - %s\n\n' "$STAMP"
    printf 'Profile file: `%s`\n\n' "$PROFILE_FILE"
    printf '## Available Local Artifacts\n\n'
    find "$(report_dir)" -maxdepth 1 -type f | sort | sed 's#^#- #'
    printf '\n## Safety Summary\n\n'
    printf '%s\n' '- Retrieval/research gates may use YOLO when `HERMES_YOLO_MODE=retrieval`.'
    printf '%s\n' '- Drafts and reports are local-only.'
    printf '%s\n' '- Posting, sending, deleting, purchases, credentials, permissions, and account settings require human approval.'
  } > "$out"
  printf 'report=%s\n' "$out"
}

DAYS=7
TEXT=""
FILE=""
COMMAND=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --profile-file) PROFILE_FILE="$2"; shift 2 ;;
    --days) DAYS="$2"; shift 2 ;;
    --text) TEXT="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --platform) export ANALYTICS_PLATFORM="$2"; shift 2 ;;
    --topic) export ANALYTICS_TOPIC="$2"; shift 2 ;;
    --format) export ANALYTICS_FORMAT="$2"; shift 2 ;;
    --views) export ANALYTICS_VIEWS="$2"; shift 2 ;;
    --likes) export ANALYTICS_LIKES="$2"; shift 2 ;;
    --comments) export ANALYTICS_COMMENTS="$2"; shift 2 ;;
    --saves) export ANALYTICS_SAVES="$2"; shift 2 ;;
    --profile-clicks) export ANALYTICS_PROFILE_CLICKS="$2"; shift 2 ;;
    --link-clicks) export ANALYTICS_LINK_CLICKS="$2"; shift 2 ;;
    --leads) export ANALYTICS_LEADS="$2"; shift 2 ;;
    --sales) export ANALYTICS_SALES="$2"; shift 2 ;;
    --cost-usd) export ANALYTICS_COST_USD="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*)
      die "unknown flag: $1" ;;
    *)
      if [[ -z "$COMMAND" ]]; then
        COMMAND="$1"
      else
        TEXT="${TEXT:+$TEXT }$1"
      fi
      shift ;;
  esac
done

case "${COMMAND:-help}" in
  scan) cmd_scan ;;
  package) cmd_package ;;
  content-calendar) cmd_content_calendar "$DAYS" ;;
  compliance-check)
    if [[ -n "$FILE" ]]; then
      [[ -f "$FILE" ]] || die "draft file missing: $FILE"
      TEXT="$(<"$FILE")"
    fi
    [[ -n "$TEXT" ]] || die "compliance-check requires --text or --file"
    cmd_compliance_check "$TEXT" ;;
  analytics) cmd_analytics ;;
  report) cmd_report ;;
  help|-h|--help) usage ;;
  *)
    die "unknown command: $COMMAND" ;;
esac
