#!/usr/bin/env bash
# Summarise recorded trigger times. Timestamps only -- there is no audio and no
# transcript in this file, by design.
set -euo pipefail
CFG="$HOME/.config/voicepi/voicepi.env"
LOG="${1:-$(sed -n 's/^WAKE_TALLY=//p' "$CFG" | tail -1)}"
[ -r "${LOG:-}" ] || { echo "no tally at ${LOG:-<unset>}" >&2; exit 1; }
echo "triggers: $(wc -l < "$LOG")   since: $(head -1 "$LOG")   latest: $(tail -1 "$LOG")"
echo
echo "per hour:"
cut -dT -f1,2 "$LOG" | cut -d: -f1 | sort | uniq -c | awk '{printf "  %s  %s\n", $2, $1}'
