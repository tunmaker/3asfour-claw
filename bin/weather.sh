#!/usr/bin/env bash
# Weather from Open-Meteo. No key, no account.
#
#   weather.sh                     here, now
#   weather.sh <البلدة>             anywhere, now
#   weather.sh forecast            here, three days
#   weather.sh forecast 5 Tunis    anywhere, up to seven days
#
# Home coordinates fall back to the ones prayer times already use, so nothing
# extra needs configuring. A named place is looked up on demand.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

exec python3 "$HOME/bin/_weather_cli.py" "$@"
