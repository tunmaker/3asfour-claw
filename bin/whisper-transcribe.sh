#!/usr/bin/env bash
# Transcribe an audio file via the local whisper.cpp server. Prints the transcript to stdout.
set -euo pipefail

set -a; . "$HOME/.openclaw/openclaw.env"; set +a
WHISPER_URL="${WHISPER_URL:?WHISPER_URL must be set in openclaw.env}"
LANGUAGE="${WHISPER_LANGUAGE:-auto}"
AUDIO="${1:?usage: whisper-transcribe.sh <audio-file>}"

[[ -r "$AUDIO" ]] || { echo "whisper-transcribe: cannot read $AUDIO" >&2; exit 1; }

response=$(curl -sS --fail-with-body --max-time "${WHISPER_TIMEOUT:-300}" \
    "$WHISPER_URL" \
    -F "file=@${AUDIO}" \
    -F "language=${LANGUAGE}" \
    -F "response_format=json")

printf '%s' "$response" | python3 -c 'import sys,json
d=json.load(sys.stdin)
if "error" in d:
    sys.stderr.write(str(d["error"])+"\n"); sys.exit(1)
sys.stdout.write((d.get("text") or "").strip())'
