"""
delete_by_id.py

Delete one or more specific messages by Mail.app's OWN internal message id -
the message_id column from export_preview.py's CSV output. This is NOT the
same as a mail server's Message-ID: header, and these ids are NOT stable
enough to store long-term - only use this right after reviewing a message,
not as a saved rule.

Defaults to a dry run (--action list, just logs what it found, doesn't
delete) so you can confirm it found the right message before committing.

Usage:
    # Dry run first - confirms the ID(s) resolve to the message(s) you expect
    python3 delete_by_id.py Email1 90280

    # Actually delete
    python3 delete_by_id.py Email1 90280 --action delete

    # Multiple at once
    python3 delete_by_id.py Email1 90280 90281 90282 --action delete
"""

import argparse
import logging

from GmailMgmt import GmailMgmt


def main():
    parser = argparse.ArgumentParser(
        description="Delete specific messages by Mail.app message_id.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("section", help="config.ini section, e.g. Email1")
    parser.add_argument("message_ids", nargs="+", help="One or more message_id values (from export_preview.py's CSV)")
    parser.add_argument("--action", choices=["list", "delete"], default="list",
                         help="'list' (default) just confirms the message exists and logs it, without deleting. "
                              "'delete' actually deletes it.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    gmailObject = GmailMgmt()
    email_id, _user, _service_provider, _sender_file = gmailObject.get_email_info(args.section)
    if email_id is None:
        print(f"Section '{args.section}' not found in config.ini.")
        return 1

    if args.action == "list":
        print(f"Dry run - checking {len(args.message_ids)} message_id(s) exist, NOT deleting. "
              f"Re-run with --action delete once you've confirmed.")
    else:
        print(f"Deleting {len(args.message_ids)} message_id(s)...")

    ok = gmailObject.delete_messages_by_id(args.section, args.message_ids, action=args.action)

    if ok is False:
        print("Failed - check email_run_hist.log / the per-account log for details.")
        return 1

    print("Done. Check the per-account log (see email_run_hist.log for the exact path) "
          "for which IDs were found vs. not found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())