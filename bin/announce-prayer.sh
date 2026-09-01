#!/usr/bin/env bash
# Announce the prayer that is due now. Run by the abbes-prayer cron job as its
# payload, after that job's trigger has decided the moment has come.
#
# There is deliberately no model in this path. The sentence is known before the
# work starts, so sending it through a 9B model costs 30-odd seconds and risks
# it being paraphrased -- the first run of this job answered "I will alert you"
# instead of announcing anything. The model earns its place where there is a
# judgement to make; announcing a fixed time is not one.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

# --minutes 1 rather than 0: the trigger fires on the minute the prayer is due,
# and this runs a moment later, by which time "0 minutes away" has become "-1".
next=$("$HOME/bin/prayer.sh" next --minutes 1)

due=$(printf '%s' "$next" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("due") else "0")')
if [ "$due" != "1" ]; then
    echo "NO_REPLY"
    exit 0
fi

name_ar=$(printf '%s' "$next" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name_ar"])')
hhmm=$(printf '%s' "$next" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hhmm"])')

"$HOME/bin/abbes-say.sh" "cron:abbes-prayer" "حان الآن وقت صلاة ${name_ar}، الساعة ${hhmm}."
