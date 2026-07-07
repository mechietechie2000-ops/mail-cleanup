"""
add_sender.py

Manually add one rule to a per-account senders_*.csv file - meant to be run
after you've looked at export_preview.py's output and decided a sender is
spam. Thin CLI wrapper around GmailMgmt.add_sender_rule().

Usage:
    python3 add_sender.py Email1 sender spam@example.com
    python3 add_sender.py Email1 display_name "Spammy Sender Name"
    python3 add_sender.py Email1 from_subject spam@example.com "Weekly Deal"
    python3 add_sender.py Email1 display_name_days "Some School" 30
    python3 add_sender.py Email1 display_name_days_subject "Some School" 30 "Digest"

Options:
    --action {delete,list}   default: delete (list for display_name_days)
    --notes "text"           optional note, e.g. which review file flagged it
"""

import argparse
import logging

from GmailMgmt import GmailMgmt

RULE_FIELD_COUNTS = {
    "sender": 1,
    "display_name": 1,
    "from_subject": 2,
    "display_name_days": 2,
    "display_name_days_subject": 3,
}


def main():
    parser = argparse.ArgumentParser(
        description="Add a sender/rule to a senders_*.csv block list.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("section", help="config.ini section, e.g. Email1")
    parser.add_argument("rule_type", choices=list(RULE_FIELD_COUNTS.keys()))
    parser.add_argument("values", nargs="+",
                         help="Rule-specific values, e.g. an email address, or 'name days [subject]'")
    parser.add_argument("--action", choices=["delete", "list"], default=None)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    expected = RULE_FIELD_COUNTS[args.rule_type]
    if len(args.values) != expected:
        parser.error(
            f"rule_type '{args.rule_type}' expects {expected} value(s), "
            f"got {len(args.values)}: {args.values}"
        )

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    gmailObject = GmailMgmt()
    email_id, _user, _service_provider, _sender_file = gmailObject.get_email_info(args.section)
    if email_id is None:
        print(f"Section '{args.section}' not found in config.ini.")
        return 1

    values = args.values[0] if expected == 1 else tuple(args.values)
    added = gmailObject.add_sender_rule(
        args.section, args.rule_type, values, action=args.action, notes=args.notes
    )

    if not added:
        print(f"Already present, not added again: {args.rule_type} {args.values}")
    else:
        print(f"Added: {args.rule_type} {args.values} (action={args.action or 'default'})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
