#!/usr/bin/env bash
# Live microphone level meter. Stops nothing: abbes-loop holds the mic, so stop it first.
set -euo pipefail
CFG="$HOME/.config/voicepi/voicepi.env"
PY=$(sed -n 's/^WAKE_VOSK_PYTHON=//p' "$CFG" | tail -1)
[ -x "${PY:-}" ] || PY=$(command -v python3)
if systemctl --user is-active --quiet abbes-loop; then
    echo "abbes-loop is running and holds the microphone." >&2
    echo "  systemctl --user stop abbes-loop && $0 ; systemctl --user start abbes-loop" >&2
    exit 1
fi
exec "$PY" "$(dirname "$0")/mic-level.py"
