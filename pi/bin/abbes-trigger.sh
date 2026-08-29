#!/usr/bin/env bash
set -euo pipefail
FIFO="${TRIGGER_FIFO:-${XDG_RUNTIME_DIR:-/tmp}/abbes-trigger}"
[ -p "$FIFO" ] || { echo "no trigger fifo at $FIFO — is abbes-loop running?" >&2; exit 1; }
echo go > "$FIFO"
