#!/usr/bin/env bash
# Prayer times for today, or the next one due.
#
#   prayer.sh today          all six, one per line
#   prayer.sh next           the next prayer as JSON, for the cron trigger
#   prayer.sh next --minutes N   also report whether it falls within N minutes
#
# Computed locally. No network and no mosque identifier: the location lives in
# PRAYER_LAT / PRAYER_LON in the gateway env file, because this repo is public.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

exec python3 "$HOME/bin/_prayer_cli.py" "$@"
