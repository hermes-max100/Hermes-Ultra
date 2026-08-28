#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE="com.mobilefork.hermesagent"
VERSION="0.13.146"
VERSION_CODE="144690"
APK_URL="${HERMES_AGENT_APK_URL:-https://f-droid.org/repo/${PACKAGE}_${VERSION_CODE}.apk}"
APK_PATH="${HERMES_AGENT_APK_PATH:-/sdcard/Download/HermesAgentFork-${VERSION}.apk}"
REPORT_DIR="$ROOT_DIR/.hermes/reports"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/android-hermes-agent-setup-$STAMP.md"
PHONE_SETUP="/sdcard/Download/HermesAgent-Setup.md"
APP_CONTROL_SETUP="/sdcard/Download/Hermes-App-Control-Setup.md"

usage() {
  cat <<'EOF'
Hermes Agent Android Setup

Usage:
  src/system/android-hermes-agent-setup.sh status
  src/system/android-hermes-agent-setup.sh download
  src/system/android-hermes-agent-setup.sh install
  src/system/android-hermes-agent-setup.sh launch
  src/system/android-hermes-agent-setup.sh setup-file
  src/system/android-hermes-agent-setup.sh app-control-setup
  src/system/android-hermes-agent-setup.sh open-control-settings
  src/system/android-hermes-agent-setup.sh all

This script uses Android's normal installer UI. It does not silently install,
grant permissions, bypass Android security settings, or perform unattended
phone takeover.
EOF
}

need_android_bridge() {
  command -v bsh >/dev/null 2>&1 || { echo "bsh Android bridge is required" >&2; return 1; }
  command -v am >/dev/null 2>&1 || { echo "am Android intent bridge is required" >&2; return 1; }
}

package_status() {
  need_android_bridge
  bsh -c 'String pkg="'"$PACKAGE"'"; try { android.content.pm.PackageInfo info = pm.getPackageInfo(pkg, 0); print("installed=true"); print("package=" + pkg); print("versionName=" + info.versionName); print("versionCode=" + info.getLongVersionCode()); android.content.Intent launch = pm.getLaunchIntentForPackage(pkg); print("launchIntent=" + (launch == null ? "missing" : "present")); } catch(Exception e) { print("installed=false"); print("package=" + pkg); }'
}

download_apk() {
  mkdir -p "$(dirname "$APK_PATH")"
  if [[ -s "$APK_PATH" ]]; then
    echo "apk_exists=$APK_PATH"
  else
    curl -L --fail --show-error "$APK_URL" -o "$APK_PATH"
    echo "downloaded=$APK_PATH"
  fi
  sha256sum "$APK_PATH"
}

scan_apk() {
  bsh -c 'try { final Object lock = new Object(); String path="'"$APK_PATH"'"; android.media.MediaScannerConnection.scanFile(context, new String[]{path}, new String[]{"application/vnd.android.package-archive"}, new android.media.MediaScannerConnection.OnScanCompletedListener(){ public void onScanCompleted(String p, android.net.Uri uri){ print("contentUri=" + uri); synchronized(lock){ lock.notify(); } } }); synchronized(lock){ lock.wait(5000); } } catch(Exception e) { print("scanError=" + e); }'
}

content_uri_for_apk() {
  bsh -c 'try { final String target = new java.io.File("'"$APK_PATH"'").getName(); android.net.Uri base = android.provider.MediaStore.Files.getContentUri("external"); String[] proj = {"_id","_display_name"}; android.database.Cursor c = contentResolver.query(base, proj, "_display_name=?", new String[]{target}, null); if (c != null && c.moveToFirst()) { long id = c.getLong(0); print(android.content.ContentUris.withAppendedId(base, id)); c.close(); } else { if (c != null) c.close(); print(""); } } catch(Exception e) { print(""); }'
}

open_installer() {
  need_android_bridge
  [[ -s "$APK_PATH" ]] || download_apk >/dev/null
  bsh -c 'try { final Object lock = new Object(); final String path="'"$APK_PATH"'"; android.media.MediaScannerConnection.scanFile(context, new String[]{path}, new String[]{"application/vnd.android.package-archive"}, new android.media.MediaScannerConnection.OnScanCompletedListener(){ public void onScanCompleted(String p, android.net.Uri uri){ try { if (uri != null) { android.content.Intent i = new android.content.Intent(android.content.Intent.ACTION_VIEW); i.setDataAndType(uri, "application/vnd.android.package-archive"); i.setFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK); i.addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION); context.startActivity(i); print("installer_started=" + uri); } else { print("installer_error=no_content_uri"); } } catch(Exception e) { print("installer_error=" + e); } synchronized(lock){ lock.notify(); } } }); synchronized(lock){ lock.wait(5000); } } catch(Exception e) { print("installer_error=" + e); }'
}

launch_app() {
  need_android_bridge
  bsh -c 'String pkg="'"$PACKAGE"'"; try { android.content.Intent launch = pm.getLaunchIntentForPackage(pkg); if (launch == null) { print("launch_failed=no_launch_intent"); } else { launch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK); context.startActivity(launch); print("launched=" + pkg); } } catch(Exception e) { print("launch_failed=" + e); }'
}

open_app_settings() {
  am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d "package:$PACKAGE"
}

open_accessibility_settings() {
  am start -a android.settings.ACCESSIBILITY_SETTINGS
}

open_usage_access_settings() {
  am start -a android.settings.USAGE_ACCESS_SETTINGS
}

open_notification_listener_settings() {
  am start -a android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS
}

open_overlay_settings() {
  am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION -d "package:gptos.intelligence.assistant" 2>/dev/null \
    || am start -a android.settings.MANAGE_OVERLAY_PERMISSION
}

open_battery_optimization_settings() {
  am start -a android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS
}

open_control_settings() {
  echo "opening=accessibility"
  open_accessibility_settings || true
  echo "next=enable AnyClaw/Hermes Agent, then run notification-listener-settings, usage-access-settings, overlay-settings, and battery-settings as needed"
}

write_app_control_setup() {
  mkdir -p "$REPORT_DIR" "$(dirname "$APP_CONTROL_SETUP")"
  cat > "$APP_CONTROL_SETUP" <<'EOF'
# Hermes App Control Setup

This setup gives Hermes controlled access to prepare and operate user-approved workflows in:

- Telegram / Telegram M3
- Discord
- Instagram
- WhatsApp Business

## Hard Boundary

Hermes may open apps, prepare drafts, paste approved text, extract visible state, and create reports.

Hermes must ask before:

- sending messages
- posting stories/reels/statuses
- inviting contacts
- changing privacy/security settings
- deleting chats/files
- making purchases
- entering credentials or one-time codes
- terminating sessions

## Enable These Android Settings

Open Android Settings and enable these for the bridge app shown as `AnyClaw`:

1. Accessibility
   - Settings > Accessibility > Installed apps
   - Enable `AnyClaw` or `Hermes Agent` if shown
   - Allow screen reading and gesture control only if you want UI automation

2. Notifications
   - Settings > Apps > AnyClaw > Notifications > Allow

3. Notification Access
   - Settings > Notifications > Advanced settings > Notification access
   - Enable `AnyClaw` only if you want Hermes to read incoming app notifications

4. Appear on top
   - Settings > Apps > AnyClaw > Appear on top > Allow
   - Needed only for overlay controls

5. Usage access
   - Settings > Security and privacy > More privacy settings > Usage data access
   - Enable `AnyClaw` if you want Hermes to detect the foreground app

6. Battery unrestricted
   - Settings > Apps > AnyClaw > Battery
   - Select `Unrestricted`

7. Files and media
   - Settings > Apps > AnyClaw > Permissions
   - Allow files/media only for folders you want Hermes to use

8. Optional Shizuku
   - Install and start Shizuku only if you want stronger local automation
   - Pairing must be done by you from Android developer options or wireless debugging
   - Do not grant broad shell access to unknown apps

## App-Specific Setup

Telegram:
- Keep `t.me`, `telegram.me`, and `telegram.dog` supported links enabled
- Keep the channel private unless you explicitly approve public posting
- Hermes can prepare channel text; you approve final send/post

WhatsApp Business:
- Use Business tools for quick replies, greeting messages, and away messages
- Hermes can draft replies; you approve send

Instagram:
- Hermes can draft captions, hashtags, DMs, and posting checklists
- You approve actual post/story/reel publication

Discord:
- Hermes can draft channel messages, moderation notes, and summaries
- You approve sends, invites, deletes, bans, and role changes

## Verification

After enabling the settings, send a screenshot of:

- Accessibility page showing AnyClaw/Hermes enabled
- App info page for AnyClaw showing Notifications allowed
- The app you want Hermes to control first

Then Hermes can test: open app -> read visible screen -> prepare draft -> wait for approval.
EOF
  cp "$APP_CONTROL_SETUP" "$REPORT_DIR/hermes-app-control-setup-$STAMP.md"
  bsh -e 'clipboard.set("Hermes app-control policy: prepare drafts and navigate only; ask before sending, posting, inviting, deleting, credentials, purchases, or security changes.")' >/dev/null 2>&1 || true
  echo "app_control_setup=$APP_CONTROL_SETUP"
  echo "report=$REPORT_DIR/hermes-app-control-setup-$STAMP.md"
}

write_setup_file() {
  mkdir -p "$REPORT_DIR" "$(dirname "$PHONE_SETUP")"
  local receipt keys watchdog
  receipt="$("$ROOT_DIR/src/system/model.sh" receipt 2>&1 || true)"
  keys="$("$ROOT_DIR/src/system/model.sh" keys 2>&1 || true)"
  watchdog="$("$ROOT_DIR/src/system/gateway-watchdog.sh" --dry-run --required 9router,omniroute 2>&1 || true)"
  cat > "$PHONE_SETUP" <<EOF
# Hermes Agent Phone Setup

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Recommended Remote Provider

- Provider type: OpenAI-compatible
- Base URL: http://127.0.0.1:20127/v1
- Preferred model: kimi/kimi-latest
- Coding model: moonshotai/kimi-k3
- Router model: auto/coding
- GLM route: nvidia/glm-5.2

Do not store real provider API keys in shared storage. If Hermes Agent asks for
an API key, use the local 9Router key from the 9Router dashboard or a local
placeholder only if your local gateway accepts it.

## Safe Permission Profile

Enable first:
- Notifications
- Files/media only for folders you want Hermes to use
- Microphone if you want voice

Enable later, only when needed:
- Camera
- Location
- Calendar
- Usage access
- Accessibility
- Shizuku
- Draw over other apps

Keep human approval for:
- Sending messages/email
- Payments/purchases
- Deleting files
- Installing/removing apps
- Credential entry
- Security settings changes

## Current Hermes Max Route

\`\`\`text
$receipt
\`\`\`

## Provider Key Status

\`\`\`text
$keys
\`\`\`

## Gateway Health

\`\`\`text
$watchdog
\`\`\`
EOF
  cp "$PHONE_SETUP" "$REPORT"
  echo "phone_setup=$PHONE_SETUP"
  echo "report=$REPORT"
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status) package_status ;;
  download) download_apk ;;
  install) download_apk; open_installer ;;
  launch) launch_app ;;
  app-settings) open_app_settings ;;
  accessibility-settings) open_accessibility_settings ;;
  usage-access-settings) open_usage_access_settings ;;
  notification-listener-settings) open_notification_listener_settings ;;
  overlay-settings) open_overlay_settings ;;
  battery-settings) open_battery_optimization_settings ;;
  open-control-settings) open_control_settings ;;
  setup-file) write_setup_file ;;
  app-control-setup) write_app_control_setup; open_control_settings ;;
  all)
    package_status || true
    download_apk
    write_setup_file
    open_installer
    ;;
  help|-h|--help) usage ;;
  *)
    echo "unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
