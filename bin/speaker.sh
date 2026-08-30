#!/usr/bin/env bash
# Change the volume of Abbes's own voice, on the satellite that speaks it.
# Volume only: the key this uses is bound to a forced command on that host and
# cannot run anything else there.
set -euo pipefail
ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
TARGET="${ABBES_SPEAKER_SSH:?ABBES_SPEAKER_SSH is not set (see .env.example)}"
KEY="${ABBES_SPEAKER_KEY:-$HOME/.ssh/id_ed25519_speaker}"
[ -r "$KEY" ] || { echo "speaker key not readable at $KEY" >&2; exit 1; }

case "${1:-get}" in
    get|up|down|mute|unmute) ;;
    set) [[ "${2:-}" =~ ^[0-9]{1,3}$ ]] || { echo "usage: speaker.sh set <0-100>" >&2; exit 2; } ;;
    *)   echo "usage: speaker.sh get | up | down | set <0-100> | mute | unmute" >&2; exit 2 ;;
esac

exec ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 "$TARGET" "$@"
