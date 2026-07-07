"""
export_preview.py

Manual, read-only review tool - pulls the most recent N messages from an
account's INBOX and writes them to a CSV: message_id, sender, date_received,
subject, body_preview (truncated to a fixed word count). Never deletes
anything. Meant to be run by hand before adding a new sender to a
senders_*.ini delete list, so you can see what you're about to block.

Usage:
    python3 export_preview.py Email1
    python3 export_preview.py Email1 --count 200 --words 100
    python3 export_preview.py Email1 --out my_review.csv

Reads the same config.ini as the rest of the automation, so "Email1" here
is a section name from config.ini, same as you pass to GmailMgmt methods.
"""

import argparse
import csv
import logging
import os
import subprocess
import sys
from datetime import datetime

from GmailMgmt import GmailMgmt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APPLESCRIPT_PATH = os.path.join(SCRIPT_DIR, "applescript", "export_recent_messages.applescript")

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


def fetch_recent_messages(email_id, count, max_chars, timeout=180):
    """
    Runs export_recent_messages.applescript directly (not through the
    retry/alert machinery in monitor.py - this is a one-off manual command,
    not a scheduled step). Returns a list of dicts, or raises RuntimeError.
    """
    cmd = ['osascript', APPLESCRIPT_PATH, email_id or "", str(count), str(max_chars)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed (rc={result.returncode}): {result.stderr.strip()[:500]}")

    raw = result.stdout.strip()
    if not raw:
        return []

    records = []
    for rec in raw.split(RECORD_SEP):
        fields = rec.split(FIELD_SEP)
        if len(fields) != 5:
            logging.warning(f"Skipping malformed record (expected 5 fields, got {len(fields)}): {rec[:100]}")
            continue
        msg_id, sender, date_received, subject, body = fields
        records.append({
            "message_id": msg_id,
            "sender": sender,
            "date_received": date_received,
            "subject": subject,
            "body": body,
        })
    return records


def truncate_words(text, max_words):
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [...]"


def main():
    parser = argparse.ArgumentParser(description="Export recent inbox messages to a CSV for manual review.")
    parser.add_argument("section", help="config.ini section name, e.g. Email1")
    parser.add_argument("--count", type=int, default=100, help="How many recent messages to pull (default 100)")
    parser.add_argument("--words", type=int, default=200, help="Max words of body to keep per message (default 200)")
    parser.add_argument("--max-chars", type=int, default=4000,
                         help="Approx. raw character cap fetched from Mail before word-truncation (default 4000)")
    parser.add_argument("--out", default=None, help="Output CSV path (default: review_<section>_<timestamp>.csv)")
    args = parser.parse_args()

    gmailObject = GmailMgmt()
    email_id, user, service_provider, _ = gmailObject.get_email_info(args.section)
    if email_id is None:
        print(f"Section '{args.section}' not found in config.ini.")
        sys.exit(1)

    print(f"Fetching last {args.count} messages for {email_id} ...")
    try:
        records = fetch_recent_messages(email_id, args.count, args.max_chars)
    except Exception as e:
        print(f"Failed to fetch messages: {e}")
        sys.exit(1)

    out_path = args.out or os.path.join(
        SCRIPT_DIR, f"review_{args.section}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["message_id", "sender", "date_received", "subject", "body_preview"])
        for rec in records:
            writer.writerow([
                rec["message_id"],
                rec["sender"],
                rec["date_received"],
                rec["subject"],
                truncate_words(rec["body"], args.words),
            ])

    print(f"Wrote {len(records)} messages to {out_path}")


if __name__ == "__main__":
    main()
