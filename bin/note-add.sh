#!/usr/bin/env bash
# Append a timestamped note to today's note in the Obsidian vault.
set -euo pipefail
ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
VAULT="${ABBES_VAULT_DIR:?ABBES_VAULT_DIR is not set (see .env.example)}"
MOUNT="${ABBES_VAULT_MOUNT:?ABBES_VAULT_MOUNT is not set (see .env.example)}"
mountpoint -q "$MOUNT" || { echo "vault storage is not mounted; nothing was written" >&2; exit 1; }
TEXT="${*:?usage: note-add.sh <text>}"
DAY=$(date +%F)
FILE="$VAULT/Notes/$DAY.md"
mkdir -p "$VAULT/Notes"
[[ -f "$FILE" ]] || printf '# Notes — %s\n\n' "$DAY" > "$FILE"
printf -- '- %s — %s\n' "$(date +%H:%M)" "$TEXT" >> "$FILE"
chmod a+rw "$FILE" 2>/dev/null || true
grep -qF -- "$TEXT" "$FILE" || { echo "write verification failed" >&2; exit 1; }
echo "Noted in Notes/$DAY.md: $TEXT"
