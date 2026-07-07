"""
watchdog.py

Independent health check for the Gmail cleanup automation.

Run this on its own schedule (via launchd, NOT pm2 - see install.sh) every
hour or so. It does NOT touch Mail.app at all; it only reads heartbeat.json,
which main.py updates every time it starts and finishes. If main.py hasn't
even *started* recently, that means pm2/cron/launchd itself has stopped
firing (Mac asleep, pm2 daemon died, laptop closed, etc.) - the exact
scenario where you'd otherwise have no idea anything stopped.

Configure the threshold in config.ini:

    [Watchdog]
    max_hours_since_attempt = 26
"""

import json
import os
import logging
import configparser
from datetime import datetime, timedelta

from monitor import AlertMonitor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT_PATH = os.path.join(SCRIPT_DIR, "heartbeat.json")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")
WATCHDOG_LOG_PATH = os.path.join(SCRIPT_DIR, "watchdog.log")


def main():
    logging.basicConfig(
        filename=WATCHDOG_LOG_PATH,
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    config = configparser.ConfigParser(allow_no_value=True)
    config.read(CONFIG_PATH)
    max_hours = config.getfloat('Watchdog', 'max_hours_since_attempt', fallback=26.0)

    monitor = AlertMonitor(config)

    if not os.path.exists(HEARTBEAT_PATH):
        logging.error(f"No heartbeat.json found at {HEARTBEAT_PATH} — has main.py ever run?")
        monitor.alert(
            "Gmail cleanup has never run (no heartbeat file)",
            "Check pm2/launchd scheduling."
        )
        return

    try:
        with open(HEARTBEAT_PATH) as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"Could not read/parse heartbeat.json: {e}")
        monitor.alert("Gmail cleanup heartbeat file is unreadable", str(e)[:200])
        return

    last_attempt_str = data.get("last_attempt")
    if not last_attempt_str:
        logging.error("heartbeat.json has no 'last_attempt' field.")
        monitor.alert("Gmail cleanup heartbeat is missing 'last_attempt'")
        return

    last_attempt = datetime.fromisoformat(last_attempt_str)
    age = datetime.now() - last_attempt

    if age > timedelta(hours=max_hours):
        hours = age.total_seconds() / 3600
        logging.error(f"Last run attempt was {hours:.1f}h ago (limit {max_hours}h).")
        monitor.alert(
            "Gmail cleanup hasn't run recently",
            f"Last attempt was {hours:.1f}h ago (expected within {max_hours}h). "
            f"Check pm2/launchd and that the Mac is awake."
        )
    else:
        logging.info(f"OK — last attempt {age.total_seconds()/3600:.1f}h ago, within {max_hours}h limit.")

    last_result = data.get("last_result")
    if last_result == "partial_failure":
        logging.warning(f"Most recent completed run had failures: {data.get('last_summary')}")
        # Not re-alerting here - main.py already sent an alert for this at
        # the time it happened. This just gets logged for visibility.


if __name__ == "__main__":
    main()
