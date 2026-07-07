"""
monitor.py

Lightweight monitoring/alerting helpers for the Mail.app AppleScript automation.

What this catches:
  - Low disk space (Mail storage-full failures usually start here)
  - Mail.app not running (gets killed / crashes / never launched by pm2)
  - A stuck error dialog / sheet sitting on top of Mail.app blocking automation
  - AppleScript calls that hang (via subprocess timeout) or return known
    "offline" / "not connected" / disk-space error text
  - Any AppleScript call that fails outright (non-zero exit code, exception)

On any of the above, an iMessage is sent to the address/number configured in
config.ini under [Alerts] -> imessage_target, and the event is logged to
whatever logger is already configured in the calling module (email_run_hist.log).

Nothing here changes what gets deleted - it only wraps the existing
`subprocess.run(['osascript', '-e', applescript], check=True)` calls with
retries + visibility, and adds a couple of pre-flight sanity checks.
"""

import subprocess
import shutil
import logging
import time


# Substrings (checked case-insensitively) that show up in AppleScript/Mail
# stdout+stderr when something has actually gone wrong, even if osascript
# itself returns exit code 0 (Mail sometimes swallows its own errors).
ERROR_PATTERNS = [
    "not enough disk space",
    "is not connected",
    "connection is offline",
    "offline",
    "can't get mailbox",
    "cannot get mailbox",
    "application isn't running",
    "isn't running",
    "timed out",
    "the operation couldn't be completed",
    "appleevent handler failed",
    "error -600",
    "error -1728",
    "error -10004",
]


class AlertMonitor:
    def __init__(self, config, min_free_gb=5):
        """
        config: a configparser.ConfigParser already loaded with config.ini.
        Expects an optional [Alerts] section:

            [Alerts]
            imessage_target = +15551234567
            # or: imessage_target = you@icloud.com
            min_free_gb = 5
        """
        self.config = config
        self.imessage_target = None
        self.min_free_gb = min_free_gb

        if config.has_section('Alerts'):
            self.imessage_target = config.get('Alerts', 'imessage_target', fallback=None)
            self.min_free_gb = config.getfloat('Alerts', 'min_free_gb', fallback=min_free_gb)

        if not self.imessage_target:
            logging.warning(
                "No [Alerts] imessage_target configured in config.ini — "
                "alerts will only go to the log file, not to your phone."
            )

    # ---------------------------------------------------------------
    # Alerting
    # ---------------------------------------------------------------
    def send_imessage(self, message):
        if not self.imessage_target:
            return False

        # Keep it short and escape double quotes/backslashes for AppleScript.
        safe_message = message.replace("\\", "\\\\").replace('"', '\\"')[:900]

        applescript = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{self.imessage_target}" of targetService
            send "{safe_message}" to targetBuddy
        end tell
        '''
        try:
            subprocess.run(
                ['osascript', '-e', applescript],
                check=True, timeout=30, capture_output=True, text=True
            )
            return True
        except Exception as e:
            logging.error(f"Failed to send iMessage alert ({e}). Message was: {message}")
            return False

    def alert(self, subject, detail=""):
        message = f"[Gmail Cleanup] {subject}"
        if detail:
            message += f" — {detail}"
        logging.error(message)
        self.send_imessage(message)

    # ---------------------------------------------------------------
    # Pre-flight checks (call once at the start of a run, or before
    # each big batch method)
    # ---------------------------------------------------------------
    def check_disk_space(self, path="/"):
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < self.min_free_gb:
                self.alert("Low disk space", f"Only {free_gb:.1f} GB free on {path}")
                return False
            return True
        except Exception as e:
            logging.error(f"Disk space check failed, continuing anyway: {e}")
            return True

    def mail_status(self):
        """
        Returns one of:
          "not_running"      - Mail.app process isn't running
          "dialog:<text>"     - Mail.app has a modal dialog/sheet open
          "clear"             - Mail.app is running with no dialogs
          "check_failed"      - couldn't determine status (System Events issue)
        """
        applescript = '''
        tell application "System Events"
            if not (exists process "Mail") then return "not_running"
            tell process "Mail"
                set dialogCount to 0
                try
                    set dialogCount to (count of windows whose subrole is "AXDialog") + (count of sheets of window 1)
                end try
                if dialogCount > 0 then
                    set dialogText to "unknown dialog"
                    try
                        set dialogText to (value of static text 1 of window 1) as string
                    end try
                    return "dialog:" & dialogText
                else
                    return "clear"
                end if
            end tell
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout.strip() or "check_failed"
        except Exception as e:
            logging.error(f"Mail status check failed: {e}")
            return "check_failed"

    def quit_mail_app(self, timeout=30):
        """
        Gracefully quits Mail.app; force-kills it if it won't quit within
        `timeout` seconds (e.g. a stuck dialog is blocking the quit).
        Returns True once Mail.app is confirmed not running.
        """
        if self.mail_status() == "not_running":
            return True

        try:
            subprocess.run(
                ['osascript', '-e', 'tell application "Mail" to quit'],
                timeout=timeout, capture_output=True, text=True
            )
        except subprocess.TimeoutExpired:
            logging.warning("Mail.app quit request timed out; will force-quit.")
        except Exception as e:
            logging.warning(f"Mail.app quit request raised an error: {e}")

        for _ in range(timeout):
            if self.mail_status() == "not_running":
                logging.info("Mail.app quit cleanly.")
                return True
            time.sleep(1)

        logging.warning("Mail.app did not quit gracefully within timeout; force-quitting.")
        try:
            subprocess.run(['pkill', '-x', 'Mail'], timeout=10)
            time.sleep(2)
        except Exception as e:
            logging.error(f"Force-quit of Mail.app failed: {e}")

        if self.mail_status() == "not_running":
            logging.info("Mail.app force-quit succeeded.")
            return True

        self.alert("Could not quit Mail.app", "Graceful quit and force-quit both failed - check manually.")
        return False

    def launch_mail_app_and_wait(self, max_wait=60):
        """
        Opens Mail.app and waits (polling mail_status) until it's fully up
        with no dialogs, or until max_wait seconds elapse. Returns True/False.
        """
        try:
            subprocess.run(['open', '-a', 'Mail'], timeout=15, check=True)
        except Exception as e:
            logging.error(f"Could not launch Mail.app: {e}")
            self.alert("Could not launch Mail.app", str(e)[:200])
            return False

        waited = 0
        while waited < max_wait:
            status = self.mail_status()
            if status == "clear":
                logging.info(f"Mail.app launched and ready after {waited}s.")
                return True
            if status.startswith("dialog:"):
                self.alert("Mail.app opened with a dialog already showing", status[len("dialog:"):])
                return False
            time.sleep(3)
            waited += 3

        self.alert("Mail.app did not become ready in time after launch", f"Waited {max_wait}s")
        return False

    def preflight_checks(self, auto_launch_mail=True):
        """
        Returns True if it's safe to proceed, False if something needs
        human attention (an alert has already been sent in that case).
        """
        ok = self.check_disk_space()

        status = self.mail_status()
        if status == "not_running":
            self.alert("Mail.app is not running")
            if auto_launch_mail:
                try:
                    subprocess.run(['open', '-a', 'Mail'], timeout=30, check=True)
                    time.sleep(8)
                    status = self.mail_status()
                    if status != "clear":
                        ok = False
                except Exception as e:
                    logging.error(f"Could not auto-launch Mail: {e}")
                    ok = False
            else:
                ok = False
        elif status.startswith("dialog:"):
            self.alert("Mail.app has an open dialog blocking automation", status[len("dialog:"):])
            ok = False
        elif status == "check_failed":
            logging.warning("Could not verify Mail.app dialog state; proceeding cautiously.")

        return ok


def _run_osascript_with_retry(cmd, monitor, step_name, timeout=650, max_retries=2, backoff_seconds=60):
    """
    Shared retry/alert core for both calling styles (inline -e text, or a
    script file + argv). `cmd` is the full argv list to pass to subprocess,
    e.g. ['osascript', '-e', script] or ['osascript', path, arg1, arg2, ...].

    Retries on timeout/failure/known-error-text, alerts via `monitor` if all
    retries are exhausted. Returns True on success, False on failure (never
    raises, so one bad batch doesn't kill the rest of the run).
    """
    attempt = 0
    while attempt <= max_retries:
        attempt += 1
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            combined = (result.stdout or "") + (result.stderr or "")
            lowered = combined.lower()
            hit_pattern = next((p for p in ERROR_PATTERNS if p in lowered), None)

            if result.returncode != 0 or hit_pattern:
                logging.error(
                    f"[{step_name}] attempt {attempt}/{max_retries + 1} failed "
                    f"(rc={result.returncode}, pattern={hit_pattern}): {combined[:500]}"
                )
                if attempt > max_retries:
                    monitor.alert(f"{step_name} failed after {attempt} attempts", combined[:200])
                    return False
                time.sleep(backoff_seconds)
                continue

            summary_text = (result.stdout or "").strip()
            if summary_text:
                logging.info(f"[{step_name}] completed successfully on attempt {attempt}: {summary_text}")
            else:
                logging.info(f"[{step_name}] completed successfully on attempt {attempt}.")
            return True

        except subprocess.TimeoutExpired:
            logging.error(f"[{step_name}] attempt {attempt}/{max_retries + 1} timed out after {timeout}s.")
            if attempt > max_retries:
                monitor.alert(f"{step_name} timed out", f"No response after {timeout}s ({attempt} attempts)")
                return False
            time.sleep(backoff_seconds)

        except Exception as e:
            logging.error(f"[{step_name}] attempt {attempt}/{max_retries + 1} raised: {e}")
            if attempt > max_retries:
                monitor.alert(f"{step_name} crashed", str(e)[:200])
                return False
            time.sleep(backoff_seconds)

    return False


def run_applescript_safe(applescript, monitor, step_name, timeout=650, max_retries=2, backoff_seconds=60):
    """
    Drop-in replacement for:
        subprocess.run(['osascript', '-e', applescript], check=True)

    Only use this for static scripts with NO interpolated user data (e.g.
    listing accounts). Anything with dynamic values (sender lists, subjects,
    display names) should use run_applescript_file_safe instead, which
    passes those values as argv rather than splicing them into script text.
    """
    return _run_osascript_with_retry(
        ['osascript', '-e', applescript], monitor, step_name,
        timeout=timeout, max_retries=max_retries, backoff_seconds=backoff_seconds
    )


def run_applescript_file_safe(script_path, args, monitor, step_name, timeout=650, max_retries=2, backoff_seconds=60):
    """
    Runs a .applescript file with `osascript <path> <args...>`, where each
    item in `args` becomes one element of that script's `argv` (accessed via
    `on run argv`). This is the preferred way to pass sender lists, subjects,
    display names, batch sizes, etc. - they arrive as plain strings instead
    of being spliced into AppleScript source text, so a stray quote or
    backslash in a subject line can't break (or inject into) the script.
    """
    cmd = ['osascript', str(script_path)] + [str(a) for a in args]
    return _run_osascript_with_retry(
        cmd, monitor, step_name,
        timeout=timeout, max_retries=max_retries, backoff_seconds=backoff_seconds
    )
