import os
from datetime import datetime
import logging
import configparser
from pathlib import Path

from monitor import AlertMonitor, run_applescript_safe, run_applescript_file_safe


class GmailMgmt:
    config = configparser.ConfigParser(allow_no_value=True)

    # Get the absolute path of the directory containing the script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Construct the full path to the config file
    config_file_name = os.path.join(script_dir, "config.ini")
    config.read(config_file_name)

    log_dir_name = config['default']['logDirName']
    today_date = datetime.now().strftime("%Y%m%d")
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = config['default']['base_dir']

    # The single generalized AppleScript used by every delete/list method.
    # Dynamic values (sender lists, subjects, display names, batch size) are
    # passed to it as argv, not spliced into script text - see
    # applescript/mail_action.applescript for the format.
    APPLESCRIPT_PATH = os.path.join(script_dir, "applescript", "mail_action.applescript")

    # Separators used to encode lists/tuples into a single argv string.
    # These are non-printable ASCII control characters (unit/record
    # separator) so they can never collide with a real sender address,
    # display name, or subject line - unlike using "," or "|" as delimiters.
    FIELD_SEP = "\x1f"
    RECORD_SEP = "\x1e"

    def __init__(self):
        print('Process initiated')

        logging.basicConfig(
            filename='/tmp/email_log.txt',
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(message)s'
        )

        # Monitoring / alerting. Reads [Alerts] imessage_target and min_free_gb
        # from config.ini if present; falls back to log-only alerts otherwise.
        self.monitor = AlertMonitor(self.config)

    def get_time(self):
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        return current_time

    # -------------------------------------------------------------------
    # AppleScript execution helpers
    # -------------------------------------------------------------------
    def _run_applescript(self, applescript, step_name, timeout=650, max_retries=2):
        """
        Safe replacement for subprocess.run(['osascript','-e',applescript], check=True).

        Only appropriate for STATIC scripts with no interpolated user data
        (e.g. list_email_accounts). Anything with dynamic values should use
        _run_applescript_file instead.
        """
        if not self.monitor.preflight_checks():
            logging.error(f"[{step_name}] Preflight checks failed — skipping this step.")
            return False

        return run_applescript_safe(
            applescript, self.monitor, step_name,
            timeout=timeout, max_retries=max_retries
        )

    @classmethod
    def _encode_records(cls, records):
        """
        Encodes a list of strings, or a list of tuples/lists of strings,
        into a single argv-safe string using control-character separators.
        """
        parts = []
        for rec in records:
            if isinstance(rec, (list, tuple)):
                parts.append(cls.FIELD_SEP.join(str(x).strip() for x in rec))
            else:
                parts.append(str(rec).strip())
        return cls.RECORD_SEP.join(parts)

    def _run_applescript_file(self, step_name, mode, action, batch_size, records,
                               email_id="", log_file="", timeout=650, max_retries=2):
        """
        Runs applescript/mail_action.applescript with the given mode/action/
        batch_size/records, passed as argv - see that file's header comment
        for the exact argv contract. Returns True/False.
        """
        data_arg = self._encode_records(records)
        args = [email_id, log_file, str(batch_size), mode, action, data_arg]

        if not self.monitor.preflight_checks():
            logging.error(f"[{step_name}] Preflight checks failed — skipping this step.")
            return False

        return run_applescript_file_safe(
            self.APPLESCRIPT_PATH, args, self.monitor, step_name,
            timeout=timeout, max_retries=max_retries
        )

    def _resolve_email_file(self, sender_email_id_list, use_base_dir_fallback):
        if use_base_dir_fallback:
            email_file = Path(self.base_dir) / sender_email_id_list
            if not email_file.exists():
                email_file = os.path.join(self.script_dir, sender_email_id_list)
        else:
            email_file = os.path.join(self.script_dir, sender_email_id_list)
        return email_file

    # -------------------------------------------------------------------
    # Config helpers
    # -------------------------------------------------------------------
    def get_log_file(self, service_provider, user):
        log_file_name = self.log_dir_name + service_provider + '_' + user + "_" + self.today_date + ".log"
        return log_file_name

    def get_email_info(self, section_name):
        if section_name in self.config:
            email_id = self.config.get(section_name, 'email_id', fallback=None)
            user = self.config.get(section_name, 'user', fallback=None)
            service_provider = self.config.get(section_name, 'service_provider', fallback=None)
            sender_email_id_list = self.config.get(section_name, 'sender_email_id_list', fallback=None)
            return email_id, user, service_provider, sender_email_id_list
        else:
            print(f"Section '{section_name}' not found.")
            return None, None

    def get_message(self, config_file_name):
        try:
            if 'FromSubject' in self.config:
                for item in self.config.items('FromSubject'):
                    sender, subject = item[0].split(',', 1)
                    sender = sender.strip()
                    subject = subject.strip().strip('"')
                    print(sender)
                    print(subject)
            else:
                print("Section 'FromSubject' not found in the config file.")

            if 'From' in self.config:
                for item in self.config.items('From'):
                    print(item[0])
            else:
                print("Section 'FromSubject' not found in the config file.")

        except configparser.ParsingError as e:
            print(f"Error parsing the config file: {e}")

    # -------------------------------------------------------------------
    # Listing (read-only, diagnostic) methods
    # -------------------------------------------------------------------
    def list_email_accounts(self):
        applescript = '''
            tell application "Mail"
                set accountList to ""
                repeat with theAccount in accounts
                    set accountList to accountList & name of theAccount & " (" & email addresses of theAccount & ")" & return
                end repeat
                log accountList
            end tell
        '''
        self._run_applescript(applescript, "list_email_accounts", timeout=60)

    def list_email_by_sender_id(self, logFileName, batch_size=100):
        with open("senderList.txt", "r") as file:
            sender_list = [line.strip() for line in file.readlines() if line.strip()]

        return self._run_applescript_file(
            step_name="list_email_by_sender_id", mode="sender", action="list",
            batch_size=batch_size, records=sender_list, email_id="", log_file=logFileName
        )

    # -------------------------------------------------------------------
    # Sender-based delete/list.
    #
    # delete_email_by_sender_id / _id2 / _id2_old / _id3 were four separate
    # copies of essentially the same AppleScript-building code, differing
    # only in (a) delete vs. list-only, and (b) how the sender-list file
    # path was resolved. Now that the AppleScript text itself lives in one
    # external file, that duplication is gone - all four are thin wrappers
    # around one shared implementation. Kept as separate methods so nothing
    # that calls them by name needs to change.
    # -------------------------------------------------------------------
    def _delete_by_sender_from_config(self, section_name, batch_size, action, use_base_dir_fallback, step_name):
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        logging.info(f"[{step_name}] email_id={email_id} user={user} sender_file={sender_email_id_list}")

        log_file_name = self.get_log_file(service_provider, user)
        email_file = self._resolve_email_file(sender_email_id_list, use_base_dir_fallback)
        self.config.read(email_file)

        if 'From' not in self.config:
            logging.info(f"[{step_name}] Section 'From' not found in {email_file} — skipping (not configured).")
            return None

        sender_list = [item[0] for item in self.config.items('From')]
        return self._run_applescript_file(
            step_name=step_name, mode="sender", action=action, batch_size=batch_size,
            records=sender_list, email_id=email_id, log_file=log_file_name
        )

    def delete_email_by_sender_id(self, section_name, batch_size=1500):
        return self._delete_by_sender_from_config(
            section_name, batch_size, "delete", use_base_dir_fallback=False,
            step_name="delete_email_by_sender_id"
        )

    def delete_email_by_sender_id2(self, section_name, batch_size=500):
        return self._delete_by_sender_from_config(
            section_name, batch_size, "list", use_base_dir_fallback=False,
            step_name="delete_email_by_sender_id2"
        )

    def delete_email_by_sender_id2_old(self, section_name, batch_size=500):
        return self._delete_by_sender_from_config(
            section_name, batch_size, "delete", use_base_dir_fallback=False,
            step_name="delete_email_by_sender_id2_old"
        )

    def delete_email_by_sender_id3(self, section_name, batch_size=500):
        return self._delete_by_sender_from_config(
            section_name, batch_size, "delete", use_base_dir_fallback=True,
            step_name="delete_email_by_sender_id3"
        )

    # -------------------------------------------------------------------
    # Display-name-based delete
    # -------------------------------------------------------------------
    def delete_email_by_display_name(self, section_name, batch_size=1500):
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.get_log_file(service_provider, user)
        self.config.read(sender_email_id_list)

        if 'DisplayName' not in self.config:
            logging.info("[delete_email_by_display_name] Section 'DisplayName' not found — skipping (not configured).")
            return None

        display_names = [item[0] for item in self.config.items('DisplayName')]
        return self._run_applescript_file(
            step_name="delete_email_by_display_name", mode="display_name", action="delete",
            batch_size=batch_size, records=display_names, email_id=email_id, log_file=log_file_name
        )

    # -------------------------------------------------------------------
    # Sender + subject delete
    # -------------------------------------------------------------------
    def delete_email_by_from_and_subject(self, section_name, batch_size=500):
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.get_log_file(service_provider, user)
        self.config.read(sender_email_id_list)

        if 'FromSubject' not in self.config:
            logging.info("[delete_email_by_from_and_subject] Section 'FromSubject' not found — skipping (not configured).")
            return None

        pairs = []
        for item in self.config.items('FromSubject'):
            # split(',', 1) so a subject that itself contains a comma
            # doesn't get truncated (previous version used plain split(',')).
            sender, subject = item[0].split(',', 1)
            pairs.append((sender.strip(), subject.strip().strip('"')))

        return self._run_applescript_file(
            step_name="delete_email_by_from_and_subject", mode="from_subject", action="delete",
            batch_size=batch_size, records=pairs, email_id=email_id, log_file=log_file_name
        )

    # -------------------------------------------------------------------
    # Bulk per-sender processing
    # -------------------------------------------------------------------
    def bulk_delete_email_by_sender_id(self, section_name):
        """
        NOTE: despite the name, this only LOGS matches (delete msg was
        commented out in the original AppleScript) - preserved as-is.

        Also: the original version looped over each sender and called
        exit() after the FIRST one, which silently killed the entire
        Python process (including any later steps queued in main.py).
        That's fixed here by doing a single combined pass over all
        senders instead of one osascript call per sender.
        """
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.log_dir_name + service_provider + '_' + user + "_bulk_delete_" + self.today_date + ".log"
        email_file = os.path.join(self.script_dir, sender_email_id_list)
        self.config.read(email_file)

        if 'From' not in self.config:
            logging.info("[bulk_delete_email_by_sender_id] Section 'From' not found — skipping (not configured).")
            return None

        sender_list = [item[0] for item in self.config.items('From')]
        return self._run_applescript_file(
            step_name="bulk_delete_email_by_sender_id", mode="sender", action="list",
            batch_size=10000, records=sender_list, email_id=email_id, log_file=log_file_name
        )

    def bulk_process_emails_by_sender_id(self, section_name, batch_size=500, action=None):
        """
        NOTE: the original version made one osascript call PER sender, each
        re-scanning up to batch_size messages of the mailbox from scratch -
        with N senders, that's N full scans. Consolidated to a single call
        that checks all senders in one pass over batch_size messages, which
        is both faster and matches how every other method here works.
        """
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.get_log_file(service_provider, user)
        print(f"You may find the logfile for this run at {log_file_name}")

        email_file = os.path.join(self.script_dir, sender_email_id_list)
        self.config.read(email_file)

        if 'From' not in self.config:
            logging.info("[bulk_process_emails_by_sender_id] Section 'From' not found — skipping (not configured).")
            return None

        sender_list = [item[0] for item in self.config.items('From')]
        effective_action = "delete" if action == "delete" else "list"
        return self._run_applescript_file(
            step_name="bulk_process_emails_by_sender_id", mode="sender", action=effective_action,
            batch_size=batch_size, records=sender_list, email_id=email_id, log_file=log_file_name
        )

    def bulk_delete_emails_by_sender_id(self, section_name, batch_size=50):
        return self.bulk_process_emails_by_sender_id(section_name, batch_size, action="delete")

    def bulk_list_emails_by_sender_id(self, section_name, batch_size=1000):
        return self.bulk_process_emails_by_sender_id(section_name, batch_size, action="list")

    # -------------------------------------------------------------------
    # Display-name + age (+ subject) delete
    # -------------------------------------------------------------------
    def delete_email_by_display_name_days_ago(self, section_name, batch_size=1000):
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.get_log_file(service_provider, user)
        self.config.read(sender_email_id_list)

        if 'DisplayNameDateAgo' not in self.config:
            logging.info("[delete_email_by_display_name_days_ago] Section 'DisplayNameDateAgo' not found — skipping (not configured).")
            return None

        records = []
        for item in self.config.items('DisplayNameDateAgo'):
            name, days = item[0].split(',', 1)
            records.append((name.strip(), days.strip()))

        # action="list" preserves the original behavior (delete msg was
        # commented out in the source AppleScript for this method).
        return self._run_applescript_file(
            step_name="delete_email_by_display_name_days_ago", mode="display_name_days", action="list",
            batch_size=batch_size, records=records, email_id=email_id, log_file=log_file_name
        )

    def delete_email_by_display_name_days_ago_subject(self, section_name, batch_size=1000):
        email_id, user, service_provider, sender_email_id_list = self.get_email_info(section_name)
        log_file_name = self.get_log_file(service_provider, user)
        self.config.read(sender_email_id_list)

        if 'DisplayNameDateAgoSubject' not in self.config:
            logging.info("[delete_email_by_display_name_days_ago_subject] Section 'DisplayNameDateAgoSubject' not found — skipping (not configured).")
            return None

        records = []
        for item in self.config.items('DisplayNameDateAgoSubject'):
            # split(',', 2) so the subject (the last field) can safely
            # contain commas of its own.
            name, days, subject = item[0].split(',', 2)
            records.append((name.strip(), days.strip(), subject.strip().strip('"')))

        return self._run_applescript_file(
            step_name="delete_email_by_display_name_days_ago_subject", mode="display_name_days_subject", action="delete",
            batch_size=batch_size, records=records, email_id=email_id, log_file=log_file_name
        )
