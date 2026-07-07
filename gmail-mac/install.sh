#!/bin/bash
#
# install.sh - sets up the Gmail cleanup automation for a new user/machine.
#
# Usage:
#   ./install.sh [install_dir]
#
# Default install_dir: ~/gmail-cleanup

set -e

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${1:-$HOME/mail-cleanup}"
PLIST_LABEL="com.gmailcleanup.watchdog"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

echo "== Gmail Cleanup installer =="
echo "Install directory: $INSTALL_DIR"

# ---------------------------------------------------------------------------
# 1. Sanity checks
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Xcode Command Line Tools first:"
    echo "  xcode-select --install"
    exit 1
fi

if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: this automation drives macOS Mail.app via AppleScript - it only runs on macOS."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Copy files
# ---------------------------------------------------------------------------
mkdir -p "$INSTALL_DIR/logs"
cp "$SRC_DIR/GmailMgmt.py" "$INSTALL_DIR/"
cp "$SRC_DIR/main.py" "$INSTALL_DIR/"
cp "$SRC_DIR/monitor.py" "$INSTALL_DIR/"
cp "$SRC_DIR/watchdog.py" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/applescript"
cp "$SRC_DIR/applescript/mail_action.applescript" "$INSTALL_DIR/applescript/"

if [[ ! -f "$INSTALL_DIR/config.ini" ]]; then
    cp "$SRC_DIR/config.ini.example" "$INSTALL_DIR/config.ini"
    echo "Created $INSTALL_DIR/config.ini from the template — YOU MUST EDIT THIS before running."
else
    echo "config.ini already exists, leaving it alone."
fi

if [[ ! -f "$INSTALL_DIR/senders_email1.ini" ]]; then
    cp "$SRC_DIR/senders.ini.example" "$INSTALL_DIR/senders_email1.ini"
    echo "Created $INSTALL_DIR/senders_email1.ini from the template — edit this with your real senders."
fi

echo "Files copied."

# ---------------------------------------------------------------------------
# 3. Set up the watchdog as its own launchd job, separate from the main job,
#    so it keeps checking even if the main job's plist ever gets corrupted
#    or unloaded.
# ---------------------------------------------------------------------------
PYTHON_BIN="$(command -v python3)"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${INSTALL_DIR}/watchdog.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/logs/watchdog_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/logs/watchdog_stderr.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "Watchdog installed as a launchd job (runs hourly): $PLIST_PATH"

# ---------------------------------------------------------------------------
# 4. Main job scheduling (launchd) — runs hourly, 7AM-11PM.
# ---------------------------------------------------------------------------
MAIN_PLIST_LABEL="com.gmailcleanup.main"
MAIN_PLIST_PATH="$HOME/Library/LaunchAgents/${MAIN_PLIST_LABEL}.plist"

# Build the StartCalendarInterval array: one entry per hour, 7 through 23,
# at minute 0. This is launchd's equivalent of cron's "0 7-23 * * *".
CALENDAR_INTERVALS=""
for hour in $(seq 7 23); do
    CALENDAR_INTERVALS="${CALENDAR_INTERVALS}
        <dict>
            <key>Hour</key>
            <integer>${hour}</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>"
done

cat > "$MAIN_PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MAIN_PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${INSTALL_DIR}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>StartCalendarInterval</key>
    <array>${CALENDAR_INTERVALS}
    </array>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/logs/main_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/logs/main_stderr.log</string>
</dict>
</plist>
EOF

launchctl unload "$MAIN_PLIST_PATH" 2>/dev/null || true
launchctl load "$MAIN_PLIST_PATH"
echo "Main job installed as a launchd job (runs hourly, 7AM-11PM): $MAIN_PLIST_PATH"
echo "  Trigger a test run immediately with:"
echo "    launchctl start ${MAIN_PLIST_LABEL}"

# ---------------------------------------------------------------------------
# 5. Permission reminders (macOS Automation privacy prompts)
# ---------------------------------------------------------------------------
cat <<'EOF'

== IMPORTANT: macOS permissions ==
The first time this runs, macOS will ask (or silently block) for permission
for Terminal/python3 (whichever launchd uses to run the scripts) to control:
  - Mail
  - System Events
  - Messages

Grant all three under:
  System Settings > Privacy & Security > Automation
(look for "Terminal", "python3", or "launchd" in that list, and check
Mail / System Events / Messages under each)

If a permission was silently denied, the fastest fix is usually:
  1. Run any one script manually once (e.g. python3 watchdog.py) from Terminal
  2. Approve the popup when it appears
  3. If no popup appeared and it's still failing, reset with:
       tccutil reset AppleEvents
     then try again

== Next steps ==
1. Edit config.ini and senders_email1.ini with your real details.
2. Test one method manually:
     cd INSTALL_DIR && python3 -c "from GmailMgmt import GmailMgmt; GmailMgmt().list_email_accounts()"
3. Watch /tmp/email_log.txt and INSTALL_DIR/email_run_hist.log for output.
EOF

echo ""
echo "Done. Installed to: $INSTALL_DIR"
