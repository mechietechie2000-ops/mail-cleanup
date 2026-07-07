from GmailMgmt import GmailMgmt
import logging
import json
import os
from datetime import datetime

HEARTBEAT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.json")


def write_heartbeat(**fields):
    data = {}
    if os.path.exists(HEARTBEAT_PATH):
        try:
            with open(HEARTBEAT_PATH) as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.update(fields)
    tmp_path = HEARTBEAT_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, HEARTBEAT_PATH)


if __name__ == "__main__":
    logging.basicConfig(
        filename='email_run_hist.log',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Record that the script actually started - this is what watchdog.py
    # checks. If launchd stops firing entirely, this timestamp goes stale
    # and watchdog.py will alert, even though nothing inside this script
    # ever ran to log an error.
    write_heartbeat(last_attempt=datetime.now().isoformat())

    gmailObject = GmailMgmt()

    # Optional [Mail] section in config.ini:
    #   restart_before_run = true/false   (default true)
    #   restart_after_run  = true/false   (default true)
    #   launch_wait_seconds = 60
    restart_before = gmailObject.config.getboolean('Mail', 'restart_before_run', fallback=True)
    restart_after = gmailObject.config.getboolean('Mail', 'restart_after_run', fallback=True)
    launch_wait_seconds = gmailObject.config.getint('Mail', 'launch_wait_seconds', fallback=60)

    # Each (label, callable) step runs independently - if one fails/crashes,
    # it's logged + alerted (via GmailMgmt's AlertMonitor / iMessage) and the
    # rest of the run still proceeds instead of the whole script dying.
    #
    # process_sender_rules() reads senders_<account>.csv (one row per rule -
    # see senders.csv.example) and runs every rule type it finds in one
    # step per account, instead of a separate call per rule type. Use
    # batch_size_overrides if you want some rule types to scan more/fewer
    # messages than others in the same run (matches the old per-method
    # batch sizes: sender rules used 200, display_name/from_subject used
    # 2000, display_name_days_subject used 500).
    steps = [
        ("process_sender_rules('Email2', batch_size=200)",
         lambda: gmailObject.process_sender_rules('Email2', batch_size=200)),
        ("process_sender_rules('Email1', batch_size=2000, overrides={'sender': 200, 'display_name_days_subject': 500})",
         lambda: gmailObject.process_sender_rules(
             'Email1', batch_size=2000,
             batch_size_overrides={'sender': 200, 'display_name_days_subject': 500}
         )),
    ]

    logging.info(f"Execution started at {gmailObject.get_time()}")

    results = {}
    try:
        # Start each run from a clean Mail.app process. This clears out
        # whatever accumulated cruft (stuck connections, memory bloat, an
        # old dialog) from the previous run rather than inheriting it.
        if restart_before:
            logging.info("Restarting Mail.app for a clean session before this run.")
            gmailObject.monitor.quit_mail_app()
            if not gmailObject.monitor.launch_mail_app_and_wait(max_wait=launch_wait_seconds):
                logging.error(
                    "Mail.app did not come up cleanly before the run started. "
                    "Proceeding anyway - each step's own preflight check will "
                    "catch anything still wrong."
                )

        for label, step in steps:
            logging.info(f"Executing gmailObject.{label}")
            try:
                ok = step()
                # ok is True  -> succeeded
                # ok is False -> genuinely failed (alerted on)
                # ok is None  -> skipped: the .ini section this step needs
                #                just isn't configured yet - not an error.
                results[label] = ok
            except Exception as e:
                logging.exception(f"Unhandled exception in {label}: {e}")
                gmailObject.monitor.alert(f"{label} crashed with an unhandled exception", str(e)[:200])
                results[label] = False

    finally:
        # Close Mail.app after every run (success or failure) so it isn't
        # sitting open, accumulating memory/connections, between now and
        # the next scheduled run.
        if restart_after:
            logging.info("Closing Mail.app after this run.")
            gmailObject.monitor.quit_mail_app()

    failed = [label for label, ok in results.items() if ok is False]
    skipped = [label for label, ok in results.items() if ok is None]
    logging.info(f"Execution ended at {gmailObject.get_time()}")
    logging.info("===================================")

    if skipped:
        logging.info(f"{len(skipped)} step(s) skipped (not configured): " + "; ".join(skipped))

    if failed:
        summary = f"{len(failed)}/{len(steps)} steps failed: " + "; ".join(failed)
        logging.error(summary)
        gmailObject.monitor.alert("Gmail cleanup run finished with failures", summary[:200])
        write_heartbeat(last_completed=datetime.now().isoformat(), last_result="partial_failure", last_summary=summary)
    else:
        logging.info("All steps completed successfully (or were skipped as unconfigured).")
        write_heartbeat(last_completed=datetime.now().isoformat(), last_result="success", last_summary="all steps ok")

    # To delete emails from ALL MAILBOXES, use a for loop to get the SECTION
    # name from config.ini and iterate over each one.
