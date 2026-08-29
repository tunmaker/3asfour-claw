#!/usr/bin/env bash
# Run the wake detector on its own, printing a line per trigger and nothing else.
# Stop abbes-loop first: both want the microphone.
set -euo pipefail
CFG="$HOME/.config/voicepi/voicepi.env"
PY=$(sed -n 's/^WAKE_VOSK_PYTHON=//p' "$CFG" | tail -1)
[ -x "${PY:-}" ] || { echo "WAKE_VOSK_PYTHON not set or not executable in $CFG" >&2; exit 1; }
if systemctl --user is-active --quiet abbes-loop; then
    echo "abbes-loop is running and holds the microphone." >&2
    echo "  systemctl --user stop abbes-loop" >&2
    exit 1
fi
exec "$PY" "$(dirname "$0")/abbes_wake.py" --listen "$@"
