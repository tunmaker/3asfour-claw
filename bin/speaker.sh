#!/usr/bin/env bash
# Change the volume of Abbes's own voice, on the satellite that speaks it.
# Volume only: the key this uses is bound to a forced command on that host and
# cannot run anything else there.
#
# ssh is run as a child, not exec'd, and that is load-bearing. OpenClaw's exec
# supervisor hands every command an inherited "lineage" pipe fd and, when that
# fd closes while the command is still running, kills the whole process group
# 100ms later (service-child-group-anchor: lineage-lost -> SIGTERM). OpenSSH
# closes every inherited fd above stderr the moment it starts. With exec, ssh
# *was* the command, the fd vanished, and the agent's volume calls died with
# "Command aborted by signal SIGTERM" ~150ms in. The shell staying alive keeps
# the fd open until ssh is done. Measured A/B in one window: 3/3 vs 0/2.
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

ssh -n -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 "$TARGET" "$@"
