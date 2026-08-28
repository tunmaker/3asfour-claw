#!/usr/bin/env bash
set -uo pipefail

ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
DEST_ROOT="${ABBES_BACKUP_DEST:?ABBES_BACKUP_DEST is not set (see .env.example)}"
DATA_DIR="${ABBES_DATA_DIR:-/var/lib/abbes}"
BACKUP_MOUNT="${ABBES_BACKUP_MOUNT:?ABBES_BACKUP_MOUNT is not set (see .env.example)}"
STAMP=$(date +%Y-%m-%d)

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

if ! mountpoint -q "$BACKUP_MOUNT"; then
    log "SKIP: backup storage is not mounted; nothing backed up"
    exit 75
fi

mkdir -p "$DEST_ROOT" || { log "FAIL: cannot create $DEST_ROOT"; exit 1; }

rc=0
run() {
    local label="$1" src="$2" dest="$3"
    [ -e "$src" ] || { log "SKIP $label: $src does not exist"; return 0; }
    mkdir -p "$dest"
    if rsync -a --delete --exclude ".git/" "$src" "$dest"; then
        log "OK   $label -> $dest"
    else
        log "FAIL $label"
        rc=1
    fi
}

run "baby-log"   "$DATA_DIR/babylog/"  "$DEST_ROOT/babylog/"
run "workspace"  /home/openclaw/.openclaw/workspace/         "$DEST_ROOT/workspace/"
run "calendar"   /home/openclaw/.local/share/radicale/       "$DEST_ROOT/radicale/"
run "config"     /home/openclaw/.openclaw/openclaw.json      "$DEST_ROOT/config/"
run "approvals"  /home/openclaw/.openclaw/exec-approvals.json "$DEST_ROOT/config/"

snap="$DEST_ROOT/snapshots/$STAMP"
mkdir -p "$snap"
if tar czf "$snap/babylog.tgz" -C "$DATA_DIR" babylog 2>/dev/null; then
    log "OK   dated snapshot -> $snap/babylog.tgz"
else
    log "FAIL dated snapshot"
    rc=1
fi

find "$DEST_ROOT/snapshots" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null

chmod -R a+rX "$DEST_ROOT" 2>/dev/null || log "note: could not relax permissions on $DEST_ROOT"

log "done rc=$rc"
exit $rc
