#!/usr/bin/env bash
# Manage the running grocery list in the Obsidian vault.
# List-building only: this script cannot buy anything.
set -euo pipefail
ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
DATA="${ABBES_VAULT_DIR:?ABBES_VAULT_DIR is not set (see .env.example)}"
MOUNT="${ABBES_VAULT_MOUNT:?ABBES_VAULT_MOUNT is not set (see .env.example)}"
mountpoint -q "$MOUNT" || { echo "vault storage is not mounted; list unavailable" >&2; exit 1; }
# shellcheck source=bin/_dedupe.sh
. "$(dirname "${BASH_SOURCE[0]}")/_dedupe.sh"
LIST="$DATA/Groceries/list.md"
mkdir -p "$DATA/Groceries"
[[ -f "$LIST" ]] || printf '# Liste de courses / Grocery list\n\n' > "$LIST"
chmod a+rw "$LIST" 2>/dev/null || true

case "${1:-list}" in
  add)
    shift
    ITEM="${*:?usage: grocery.sh add <item>}"
    if already_written grocery add "$ITEM"; then
      echo "Already added moments ago: $ITEM"
      exit 0
    fi
    printf -- '- [ ] %s\n' "$ITEM" >> "$LIST"
    echo "Added: $ITEM"
    ;;
  done)
    shift
    ITEM="${*:?usage: grocery.sh done <item>}"
    ITEM="$ITEM" awk '
      BEGIN { target = ENVIRON["ITEM"]; hit = 0 }
      {
        if (!hit && match($0, /^- \[ \] /)) {
          text = substr($0, RLENGTH + 1)
          if (tolower(text) == tolower(target)) { print "- [x] " text; hit = 1; next }
        }
        print
      }
      END { exit (hit ? 0 : 1) }
    ' "$LIST" > "$LIST.tmp" && { mv "$LIST.tmp" "$LIST"; echo "Checked off: $ITEM"; } \
      || { rm -f "$LIST.tmp"; echo "Not found: $ITEM"; exit 1; }
    ;;
  remove)
    shift
    ITEM="${*:?usage: grocery.sh remove <item>}"
    ITEM="$ITEM" awk '
      BEGIN { target = ENVIRON["ITEM"]; hit = 0 }
      {
        if (!hit && match($0, /^- \[[ x]\] /)) {
          text = substr($0, RLENGTH + 1)
          if (tolower(text) == tolower(target)) { hit = 1; next }
        }
        print
      }
      END { exit (hit ? 0 : 1) }
    ' "$LIST" > "$LIST.tmp" && { mv "$LIST.tmp" "$LIST"; echo "Removed: $ITEM"; } \
      || { rm -f "$LIST.tmp"; echo "Not found: $ITEM"; exit 1; }
    ;;
  clear)
    grep -v '^- \[x\] ' "$LIST" > "$LIST.tmp" && mv "$LIST.tmp" "$LIST"
    echo "Cleared checked items."
    ;;
  list|*)
    cat "$LIST"
    ;;
esac
