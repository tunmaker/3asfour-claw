#!/usr/bin/env bash
# Announce appointments starting within CALENDAR_LEAD_MINUTES. Run by the
# abbes-calendar cron job as its payload, after that job's trigger has fired.
#
# As with the prayer announcement, no model: the wording is fixed, and the run
# that went through one came back with an acknowledgement rather than a
# reminder.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

LEAD="${CALENDAR_LEAD_MINUTES:-15}"

# --iso carries the UTC offset. The calendar renders Europe/Paris and this host
# runs on UTC, so anything that compares these against the clock has to be told
# the offset rather than infer it.
line=$("$HOME/bin/calendar.sh" list 1 --iso | LEAD="$LEAD" python3 -c '
import datetime, os, sys

lead = int(os.environ["LEAD"])
now = datetime.datetime.now(datetime.timezone.utc)
due = []
for raw in sys.stdin:
    parts = raw.rstrip("\n").split("\t")
    if len(parts) < 2 or parts[1] == "allday":
        continue                      # a reminder before midnight is not what all-day means
    try:
        when = datetime.datetime.fromisoformat(parts[0])
    except ValueError:
        continue
    minutes = (when - now).total_seconds() / 60
    if 0 <= minutes <= lead:
        due.append((round(minutes), when.strftime("%H:%M"), parts[-1]))
if due:
    mins = due[0][0]
    body = " و ".join(f"{summary} في {hhmm}" for _, hhmm, summary in due)
    print(f"تذكير: {body}، بعد {mins} دقيقة.")
')

if [ -z "$line" ]; then
    echo "NO_REPLY"
    exit 0
fi

"$HOME/bin/abbes-say.sh" "cron:abbes-calendar" "$line"
