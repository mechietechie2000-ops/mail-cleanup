"""
migrate_ini_to_csv.py

One-time helper: converts an existing senders_*.ini file (the old format,
with [From] / [DisplayName] / [FromSubject] / [DisplayNameDateAgo] /
[DisplayNameDateAgoSubject] sections) into the new senders_*.csv format
used by GmailMgmt.process_sender_rules().

Action defaults match the old hard-coded behavior of each .ini section:
  [From]                      -> rule_type=sender,                    action=delete
  [DisplayName]                -> rule_type=display_name,              action=delete
  [FromSubject]                -> rule_type=from_subject,              action=delete
  [DisplayNameDateAgo]          -> rule_type=display_name_days,         action=list
                                   (the old AppleScript had "delete msg" commented out)
  [DisplayNameDateAgoSubject]   -> rule_type=display_name_days_subject, action=delete

Usage:
    python3 migrate_ini_to_csv.py senders_email1.ini senders_email1.csv
"""

import configparser
import csv
import sys
from datetime import datetime

CSV_FIELDS = ["rule_type", "value1", "value2", "value3", "action", "date_added", "notes"]


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 migrate_ini_to_csv.py <input.ini> <output.csv>")
        return 1

    ini_path, csv_path = sys.argv[1], sys.argv[2]
    today = datetime.now().strftime("%Y-%m-%d")

    config = configparser.ConfigParser(allow_no_value=True)
    config.read(ini_path)

    rows = []

    if 'From' in config:
        for item in config.items('From'):
            rows.append(("sender", item[0].strip(), "", "", "delete", today, "migrated from [From]"))

    if 'DisplayName' in config:
        for item in config.items('DisplayName'):
            rows.append(("display_name", item[0].strip(), "", "", "delete", today, "migrated from [DisplayName]"))

    if 'FromSubject' in config:
        for item in config.items('FromSubject'):
            sender, subject = item[0].split(',', 1)
            rows.append((
                "from_subject", sender.strip(), subject.strip().strip('"'), "",
                "delete", today, "migrated from [FromSubject]"
            ))

    if 'DisplayNameDateAgo' in config:
        for item in config.items('DisplayNameDateAgo'):
            name, days = item[0].split(',', 1)
            rows.append((
                "display_name_days", name.strip(), days.strip(), "",
                "list", today, "migrated from [DisplayNameDateAgo]"
            ))

    if 'DisplayNameDateAgoSubject' in config:
        for item in config.items('DisplayNameDateAgoSubject'):
            name, days, subject = item[0].split(',', 2)
            rows.append((
                "display_name_days_subject", name.strip(), days.strip(), subject.strip().strip('"'),
                "delete", today, "migrated from [DisplayNameDateAgoSubject]"
            ))

    if not rows:
        print(f"No recognized sections found in {ini_path} - nothing migrated.")
        return 1

    with open(csv_path, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for row in rows:
            writer.writerow(row)

    print(f"Migrated {len(rows)} rule(s) from {ini_path} to {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
