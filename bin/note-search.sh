#!/usr/bin/env bash
# Search notes in the Obsidian vault. Prints matching lines with file and line number.
set -euo pipefail
ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
VAULT="${ABBES_VAULT_DIR:?ABBES_VAULT_DIR is not set (see .env.example)}"
MOUNT="${ABBES_VAULT_MOUNT:?ABBES_VAULT_MOUNT is not set (see .env.example)}"
mountpoint -q "$MOUNT" || { echo "vault storage is not mounted; cannot search" >&2; exit 1; }
QUERY="${*:?usage: note-search.sh <query>}"
cd "$VAULT/Notes" 2>/dev/null || { echo "no notes yet"; exit 0; }
if ! grep -rin --include='*.md' -- "$QUERY" . | head -50; then
    echo "no notes match: $QUERY"
fi
