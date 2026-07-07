# Gmail Cleanup for Mail.app

Automates deleting/archiving emails from macOS Mail.app by sender, display
name, subject, or age — with monitoring and iMessage alerts so you find out
about problems (storage full, Mail.app crashed, a stuck dialog, mailbox
offline) instead of discovering a week of silent failures.

## Files

| File                    | Purpose                                                              |
|-------------------------|-----------------------------------------------------------------------|
| `GmailMgmt.py`           | Builds argv lists and calls `mail_action.applescript`                |
| `applescript/mail_action.applescript` | The actual Mail.app automation - one generalized script for every mode |
| `monitor.py`             | Preflight checks + retries + iMessage alerting                       |
| `main.py`                | Entry point — runs each cleanup step, writes `heartbeat.json`        |
| `watchdog.py`            | Independent check: alerts if `main.py` hasn't run in >24h            |
| `config.ini.example`     | Template for accounts, alert target, watchdog threshold              |
| `senders.ini.example`    | Template for who/what to delete per account                          |
| `install.sh`             | One-shot installer (copies files, sets up two launchd jobs)          |

### Why a separate `.applescript` file?

Earlier versions built AppleScript by splicing sender addresses, subjects,
and display names directly into a Python f-string. That's fragile: a stray
double-quote or backslash in a subject line breaks out of the AppleScript
string literal. `mail_action.applescript` instead takes all of that as
plain `argv` - `osascript mail_action.applescript <email_id> <log_file>
<batch_size> <mode> <action> <data>` - so dynamic values never get parsed
as AppleScript source. Lists/pairs/triples inside `<data>` are joined with
non-printable ASCII control characters (record/field separators), not
commas or pipes, so real data can never collide with the delimiter. See
the comment header in that file for the exact format per `mode`.

## Install

```bash
./install.sh ~/gmail-cleanup
```

This copies everything into `~/gmail-cleanup`, creates `config.ini` and
`senders_email1.ini` from the templates, and registers **two** `launchd`
jobs:

- `com.gmailcleanup.main` — runs `main.py` hourly, 7AM–11PM
- `com.gmailcleanup.watchdog` — runs `watchdog.py` hourly, checking that
  `main.py` is actually firing

Both run under your user's `launchd` (LaunchAgents), so they're active
whenever you're logged in — no extra daemon (pm2, node, etc.) required.

> **Note:** LaunchAgents only run while you're logged into the Mac (same
> requirement Mail.app's GUI automation has anyway). If you need it to run
> while logged out too, that requires a root `LaunchDaemon` plus a way for
> Mail.app to have a GUI session, which is a different, more involved setup
> — ask if you need that.

## Configure

1. Edit `config.ini`:
   - `[default]` — log directory and base directory (must exist / end in `/`)
   - `[Alerts]` — your iMessage-reachable phone number or Apple ID
   - `[Watchdog]` — how many hours of silence before you get pinged
   - `[Email1]`, `[Email2]`, ... — one section per mailbox

2. Edit `senders_email1.ini` (or whatever you named it) with your real
   senders/display names/subjects to delete — see the comments in the
   template for the format of each section.

3. Edit `main.py`'s `steps` list to call the methods/sections you actually
   want (it ships with a reasonable default set).

## macOS permissions (required, one-time)

The first run will trigger — or silently fail on — Automation permission
prompts. Grant these under **System Settings > Privacy & Security >
Automation** for whichever app runs the script (Terminal or `python3`,
depending on how `launchd` invokes it):

- Mail
- System Events
- Messages

If a prompt never appeared and it's just failing quietly, run:

```bash
tccutil reset AppleEvents
```

then run the script manually once from Terminal so the prompt has a chance
to appear.

## Managing who gets blocked (senders_*.csv)

Sender/rule lists now live in one CSV per account (`senders_email1.csv`,
pointed to by `sender_email_id_list` in `config.ini`), not scattered across
`.ini` sections. Schema:

```
rule_type,value1,value2,value3,action,date_added,notes
```

`rule_type` is one of `sender`, `display_name`, `from_subject`,
`display_name_days`, `display_name_days_subject` (see `senders.csv.example`
for one of each). `action` is `delete` or `list` (list = log matches only,
don't actually delete — useful while you're still confident-checking a
rule).

**Recommended workflow before blocking a new sender:**

```bash
# 1. See what's actually in the inbox lately (read-only, no deletes)
python3 export_preview.py Email1 --count 100 --words 200
#    -> writes review_Email1_<timestamp>.csv: message_id, sender,
#       date_received, subject, body_preview

# 2. Look through it, decide who's spam, then add them
python3 add_sender.py Email1 sender spammer@example.com \
    --notes "flagged in review_Email1_20260706.csv"

python3 add_sender.py Email1 from_subject deal@shop.com "50% off" --action list
```

`add_sender.py` skips silently if the exact rule already exists, so it's
safe to re-run. `process_sender_rules()` (what `main.py` actually calls)
reads the whole CSV each run, groups rows by `(rule_type, action)`, and
does one AppleScript pass per group — so mixing `delete` and `list` rows
for the same `rule_type` works fine, they just become two separate passes.

**Migrating an existing `senders_*.ini`:**

```bash
python3 migrate_ini_to_csv.py senders_email1.ini senders_email1.csv
```

Then update that account's `sender_email_id_list` in `config.ini` to point
at the `.csv` file instead of the `.ini` file. The old `.ini`-reading
methods (`delete_email_by_display_name`, etc.) are still in `GmailMgmt.py`
and still work unchanged if you'd rather not migrate a given account yet.

## How the alerting works

- Before every AppleScript call, `monitor.py` checks free disk space, that
  Mail.app is running, and that there's no blocking dialog/sheet open. Any
  of those failing sends you an iMessage and skips that step (rather than
  hanging or corrupting state).
- Each AppleScript call gets up to 2 retries (60s apart) if it times out or
  the output contains known failure text ("offline", "not enough disk
  space", etc.).
- **Mail.app is quit and relaunched fresh before every run, and quit again
  after** (controlled by `[Mail]` in `config.ini`). This clears out stuck
  connections, an old dialog, or memory bloat left over from the previous
  hourly run instead of inheriting it. If Mail won't quit gracefully within
  the timeout, it's force-killed (`pkill -x Mail`) rather than left hanging.
  Set `restart_before_run` / `restart_after_run` to `false` if this ever
  causes more friction than it saves.
- `main.py` writes `heartbeat.json` at the start (proof it ran at all) and
  end (pass/fail) of every execution.
- `watchdog.py` runs on its own hourly `launchd` job and alerts if
  `heartbeat.json` hasn't been updated within `max_hours_since_attempt` —
  this catches the case where `main.py`'s own `launchd` job silently stopped
  firing (e.g. it crashed, was unloaded, or the plist got corrupted), since
  a dead scheduler can't log its own absence.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.gmailcleanup.main.plist
launchctl unload ~/Library/LaunchAgents/com.gmailcleanup.watchdog.plist
rm ~/Library/LaunchAgents/com.gmailcleanup.main.plist
rm ~/Library/LaunchAgents/com.gmailcleanup.watchdog.plist
rm -rf ~/gmail-cleanup     # or wherever you installed it
```
