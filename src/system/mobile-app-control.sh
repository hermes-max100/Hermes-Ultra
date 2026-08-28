#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$ROOT_DIR/.hermes/logs"
POLICY_DIR="$ROOT_DIR/.hermes/policy"
mkdir -p "$LOG_DIR"
mkdir -p "$POLICY_DIR"
LOG_FILE="$LOG_DIR/mobile-app-control.jsonl"
POLICY_FILE="$POLICY_DIR/mobile-app-control.env"

usage() {
  cat <<'EOF'
Hermes Mobile App Control

Usage:
  src/system/mobile-app-control.sh status
  src/system/mobile-app-control.sh open <telegram|whatsapp-business|discord|instagram|termux|hermes|superfile>
  src/system/mobile-app-control.sh draft <app> <text>
  src/system/mobile-app-control.sh tap <x> <y>
  src/system/mobile-app-control.sh text <text>
  src/system/mobile-app-control.sh key <keycode>
  src/system/mobile-app-control.sh back
  src/system/mobile-app-control.sh recents
  src/system/mobile-app-control.sh screenshot [path]
  src/system/mobile-app-control.sh notify <title> <message>
  src/system/mobile-app-control.sh settings <accessibility|notifications|usage|overlay|battery>

This command prepares and opens app workflows. It does not send, post, invite,
delete, enter credentials, make purchases, or change security settings without
explicit user approval.
EOF
}

load_policy() {
  if [[ -f "$POLICY_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$POLICY_FILE"
  fi
  ALLOW_TERMUX="${ALLOW_TERMUX:-true}"
  ALLOW_SHIZUKU="${ALLOW_SHIZUKU:-true}"
  REQUIRE_APPROVAL_FOR_SENSITIVE_ACTIONS="${REQUIRE_APPROVAL_FOR_SENSITIVE_ACTIONS:-true}"
  ALLOW_PRIVATE_NETWORK_FILE_TRANSFER="${ALLOW_PRIVATE_NETWORK_FILE_TRANSFER:-false}"
  ALLOW_HOME_NETWORK_FILE_TRANSFER="${ALLOW_HOME_NETWORK_FILE_TRANSFER:-false}"
  HOME_NETWORK_TRANSFER_SCOPE="${HOME_NETWORK_TRANSFER_SCOPE:-local_lan_only}"
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  printf '%s' "$s"
}

log_event() {
  local action="$1"
  local target="${2:-}"
  local note="${3:-}"
  printf '{"ts":"%s","action":"%s","target":"%s","note":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(json_escape "$action")" \
    "$(json_escape "$target")" \
    "$(json_escape "$note")" >> "$LOG_FILE"
}

need_am() {
  command -v am >/dev/null 2>&1 || {
    echo "am Android intent bridge is required" >&2
    exit 1
  }
}

notify() {
  load_policy
  [[ "$ALLOW_TERMUX" == "true" ]] || return 0
  local title="$1"
  local message="$2"
  if command -v termux-notification >/dev/null 2>&1; then
    termux-notification --title "$title" --content "$message" >/dev/null 2>&1 || true
  fi
  if command -v termux-toast >/dev/null 2>&1; then
    termux-toast "$title: $message" >/dev/null 2>&1 || true
  fi
  log_event "notify" "$title" "$message"
}

set_clipboard() {
  load_policy
  local text="$1"
  if [[ "$ALLOW_TERMUX" == "true" ]] && command -v termux-clipboard-set >/dev/null 2>&1; then
    printf '%s' "$text" | termux-clipboard-set >/dev/null 2>&1 || true
  fi
  if command -v bsh >/dev/null 2>&1; then
    TEXT="$text" bsh -e 'clipboard.set(System.getenv("TEXT"))' >/dev/null 2>&1 || true
  fi
}

shell_with_shizuku() {
  load_policy
  [[ "$ALLOW_SHIZUKU" == "true" ]] || return 127
  command -v shizuku >/dev/null 2>&1 || return 127
  shizuku /system/bin/sh -c "$*" 2>/dev/null
}

need_shizuku_input() {
  command -v shizuku >/dev/null 2>&1 || {
    echo "shizuku is required for input control" >&2
    exit 1
  }
  shell_with_shizuku 'command -v input' >/dev/null || {
    echo "Shizuku input is unavailable. Start Shizuku on the phone first." >&2
    exit 1
  }
}

tap_xy() {
  local x="$1"
  local y="$2"
  [[ "$x" =~ ^[0-9]+$ && "$y" =~ ^[0-9]+$ ]] || {
    echo "tap requires numeric x y" >&2
    return 2
  }
  need_shizuku_input
  shell_with_shizuku "input tap $x $y"
  log_event "tap" "$x,$y" "shizuku input"
}

input_text() {
  local text="$*"
  [[ -n "$text" ]] || {
    echo "text is required" >&2
    return 2
  }
  need_shizuku_input
  set_clipboard "$text"
  shell_with_shizuku 'input keyevent 279' || true
  log_event "text" "clipboard_paste" "$text"
}

key_event() {
  local key="$1"
  [[ "$key" =~ ^[0-9]+$ ]] || {
    echo "key requires numeric Android keycode" >&2
    return 2
  }
  need_shizuku_input
  shell_with_shizuku "input keyevent $key"
  log_event "key" "$key" "shizuku input"
}

screen_capture() {
  local path="${1:-$ROOT_DIR/.hermes/screens/mobile-app-control-$(date -u +%Y%m%dT%H%M%SZ).png}"
  mkdir -p "$(dirname "$path")"
  command -v shizuku >/dev/null 2>&1 || {
    echo "shizuku is required for screenshot" >&2
    exit 1
  }
  local bridge_dir="/sdcard/Android/data/gptos.intelligence.assistant/files"
  local remote="$bridge_dir/hermes-mobile-app-control.png"
  shell_with_shizuku "mkdir -p '$bridge_dir' && screencap -p '$remote'"
  if cp "$remote" "$path" 2>/dev/null; then
    echo "screenshot=$path"
    log_event "screenshot" "$path" "captured"
  else
    echo "screenshot capture failed during bridge-dir transfer" >&2
    return 1
  fi
}

visible_packages_bsh() {
  command -v bsh >/dev/null 2>&1 || return 0
  bsh -e 'String[] names={"gptos.intelligence.assistant","com.mobilefork.hermesagent","com.whatsapp.w4b","com.discord","com.instagram.android","org.telegram.messenger","org.telegram.messenger.web","org.telegram.plus","tw.nekomimi.nekogram","nekox.messenger","com.termux"}; String out=""; for(String n:names){try{android.content.pm.PackageInfo p=pm.getPackageInfo(n,0); String label=pm.getApplicationLabel(p.applicationInfo).toString(); out+=n+" | "+label+" | "+p.versionName+" | launch="+(pm.getLaunchIntentForPackage(n)!=null)+"\n";}catch(Exception e){out+=n+" | not_visible_or_not_installed\n";}} out'
}

visible_packages_shizuku() {
  command -v shizuku >/dev/null 2>&1 || return 0
  shell_with_shizuku 'pm list packages -f | grep -Ei "telegram|discord|instagram|whatsapp|termux|hermes|gptos|anyclaw|esuper|file.explorer|superfile" | head -200' || true
}

accessibility_status() {
  command -v bsh >/dev/null 2>&1 || return 0
  bsh -e 'String flag=android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ACCESSIBILITY_ENABLED); String services=android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES); "accessibility_enabled="+flag+"\nservices="+services'
}

open_by_package() {
  local package="$1"
  need_am
  shell_with_shizuku "monkey -p '$package' -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
    || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "$package" 2>/dev/null \
    || am start -a android.intent.action.VIEW -d "package:$package" 2>/dev/null \
    || return 1
}

open_app() {
  local app="$1"
  need_am
  case "$app" in
    telegram)
      shell_with_shizuku "monkey -p org.telegram.messenger -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "org.telegram.messenger/.DefaultIcon" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "tg://resolve?domain=telegram" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "https://t.me" >/dev/null 2>&1
      ;;
    whatsapp-business|whatsapp)
      am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.whatsapp.w4b/com.whatsapp.Main" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "whatsapp://send" >/dev/null 2>&1
      ;;
    discord)
      shell_with_shizuku "monkey -p com.discord -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.discord/.main.MainDefault" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "discord://-/channels/@me" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "https://discord.com/app" >/dev/null 2>&1
      ;;
    instagram|ig)
      shell_with_shizuku "monkey -p com.instagram.android -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.instagram.android/.activity.MainTabActivity" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "instagram://user" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "https://www.instagram.com/" >/dev/null 2>&1
      ;;
    termux)
      shell_with_shizuku "monkey -p com.termux -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.termux/.app.TermuxActivity" >/dev/null 2>&1
      ;;
    hermes)
      shell_with_shizuku "monkey -p com.mobilefork.hermesagent -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || shell_with_shizuku "monkey -p com.hermesagent.android -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.mobilefork.hermesagent/.MainActivity" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.hermesagent.android/com.hermes.android.MainActivity" >/dev/null 2>&1 \
        || am start -a android.intent.action.VIEW -d "hermes://home" >/dev/null 2>&1
      ;;
    superfile|super-file)
      shell_with_shizuku "monkey -p com.esuper.file.explorer -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 \
        || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "com.esuper.file.explorer/com.frames.filemanager.module.activity.FirstActivity" >/dev/null 2>&1
      ;;
    *)
      echo "unknown app: $app" >&2
      return 2
      ;;
  esac
  notify "Hermes opened $app" "Ready. I will wait for approval before send/post/delete/security actions."
  log_event "open" "$app" "intent launched"
}

draft_app() {
  local app="$1"
  shift
  local text="$*"
  [[ -n "$text" ]] || {
    echo "draft text is required" >&2
    return 2
  }
  set_clipboard "$text"
  notify "Hermes draft ready" "Clipboard prepared for $app. Review before sending."
  open_app "$app"
  log_event "draft" "$app" "$text"
}

open_settings() {
  local which="$1"
  need_am
  case "$which" in
    accessibility) am start -a android.settings.ACCESSIBILITY_SETTINGS ;;
    notifications) am start -a android.settings.NOTIFICATION_SETTINGS ;;
    usage) am start -a android.settings.USAGE_ACCESS_SETTINGS ;;
    overlay) am start -a android.settings.MANAGE_OVERLAY_PERMISSION ;;
    battery) am start -a android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS ;;
    *)
      echo "unknown settings page: $which" >&2
      return 2
      ;;
  esac
  log_event "settings" "$which" "opened"
}

status() {
  echo "== Accessibility =="
  accessibility_status || true
  echo
  echo "== Visible packages from bsh =="
  visible_packages_bsh || true
  echo
  echo "== Visible packages from shizuku =="
  visible_packages_shizuku || true
  echo
  echo "== Termux API tools =="
  load_policy
  echo "allow_termux=$ALLOW_TERMUX"
  echo "allow_shizuku=$ALLOW_SHIZUKU"
  echo "allow_private_network_file_transfer=$ALLOW_PRIVATE_NETWORK_FILE_TRANSFER"
  echo "allow_home_network_file_transfer=$ALLOW_HOME_NETWORK_FILE_TRANSFER"
  echo "home_network_transfer_scope=$HOME_NETWORK_TRANSFER_SCOPE"
  echo "require_sensitive_action_approval=$REQUIRE_APPROVAL_FOR_SENSITIVE_ACTIONS"
  for tool in termux-clipboard-set termux-notification termux-toast; do
    if command -v "$tool" >/dev/null 2>&1; then
      echo "$tool=present"
    else
      echo "$tool=missing"
    fi
  done
  echo
  echo "== Shizuku shell =="
  if shell_with_shizuku 'id; command -v input; command -v uiautomator; command -v screencap' >/tmp/hermes-shizuku-status.$$ 2>/dev/null; then
    cat /tmp/hermes-shizuku-status.$$
    rm -f /tmp/hermes-shizuku-status.$$
  else
    rm -f /tmp/hermes-shizuku-status.$$
    echo "unavailable_or_not_started"
  fi
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  status) status ;;
  open) open_app "${1:-}" ;;
  draft) app="${1:-}"; shift || true; draft_app "$app" "$@" ;;
  tap) tap_xy "${1:-}" "${2:-}" ;;
  text) input_text "$@" ;;
  key) key_event "${1:-}" ;;
  back) key_event 4 ;;
  recents) key_event 187 ;;
  screenshot) screen_capture "${1:-}" ;;
  notify) title="${1:-Hermes}"; shift || true; notify "$title" "$*" ;;
  settings) open_settings "${1:-}" ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
