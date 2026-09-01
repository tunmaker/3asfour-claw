#!/usr/bin/env bash
# Speak a sentence through the orchestrator's announce lane.
#
#   abbes-say.sh <source> <text>
#
# <source> names the caller (cron:abbes-prayer, and so on). It reaches the
# orchestrator so that QUIET_HOURS_EXEMPT can single one caller out, and so a
# log line says which thing decided to interrupt the room.
#
# This does not decide whether to speak. The orchestrator refuses inside quiet
# hours and waits for a live turn to finish, and it is the only thing that can,
# because it is the only thing that can see both.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

source_tag="${1:?usage: abbes-say.sh <source> <text>}"
text="${2:?usage: abbes-say.sh <source> <text>}"

url="${ABBES_ANNOUNCE_URL:-http://127.0.0.1:18790/announce}"

exec curl -sS --max-time 120 \
    "${url}?source=$(printf '%s' "$source_tag" | tr -d '"')" \
    -H "Content-Type: application/json" \
    --data-binary @<(printf '{"text":%s}' "$(printf '%s' "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")
