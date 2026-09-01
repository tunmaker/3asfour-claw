#!/usr/bin/env bash
# The baby journal. Every command works with whatever it was given and reports
# what it assumed.
#
#   baby.sh feed [ml] [note]          no amount: same as last time
#   baby.sh sleep [HH:MM] [HH:MM]     no times: asleep from now; one time: since then
#   baby.sh wake [HH:MM]              closes the open sleep
#   baby.sh diaper [wet|dirty|both]   default wet
#   baby.sh note "<text>"
#   baby.sh today | last | list [days] | summary [days]
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

exec python3 "$HOME/bin/_baby_cli.py" "$@"
