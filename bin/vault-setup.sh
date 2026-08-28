#!/usr/bin/env bash
set -uo pipefail

ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
VAULT_ROOT="${ABBES_VAULT_ROOT:?ABBES_VAULT_ROOT is not set (see .env.example)}"
WS_NAME="${VAULT_WORKSPACE_NAME:-Abbes}"
WS="$VAULT_ROOT/$WS_NAME"
WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
REQUIRE_MOUNT="${VAULT_REQUIRE_MOUNT:-1}"

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "ABORT: $*"; exit 1; }

[ -d "$VAULT_ROOT" ] || die "vault not found at $VAULT_ROOT"
if [ "$REQUIRE_MOUNT" = "1" ] && ! mountpoint -q "$(dirname "$VAULT_ROOT")"; then
    die "$(dirname "$VAULT_ROOT") is not a mountpoint; refusing to write to a local placeholder"
fi

mkdir -p "$WS/Notes" "$WS/Groceries" || die "cannot create $WS (check ownership on the share)"

probe="$WS/.write-probe"
if ! (echo ok > "$probe" && rm -f "$probe"); then
    die "no write permission in $WS — fix ownership or the export mapall user"
fi
log "write access to $WS confirmed"

moved=0
if [ -d "$WORKSPACE/notes" ]; then
    for f in "$WORKSPACE"/notes/*.md; do
        [ -e "$f" ] || continue
        b=$(basename "$f")
        if [ -e "$WS/Notes/$b" ]; then
            log "keep existing $b (not overwritten)"
        else
            cp -p "$f" "$WS/Notes/$b" && moved=$((moved+1))
        fi
    done
fi
if [ -f "$WORKSPACE/groceries/list.md" ] && [ ! -e "$WS/Groceries/list.md" ]; then
    cp -p "$WORKSPACE/groceries/list.md" "$WS/Groceries/list.md" && moved=$((moved+1))
fi
log "copied $moved file(s) into the vault"

if [ ! -d "$VAULT_ROOT/.git" ]; then
    git -C "$VAULT_ROOT" init -q -b main || die "git init failed"
    git -C "$VAULT_ROOT" config user.name "abbes-assistant"
    git -C "$VAULT_ROOT" config user.email "abbes@localhost"
    log "initialised local git in the vault (no remote)"
else
    log "vault git already present"
    if git -C "$VAULT_ROOT" remote | grep -q .; then
        log "WARNING: vault git has a remote configured; D-13 says it must stay local"
    fi
fi

log "vault workspace ready at $WS"
