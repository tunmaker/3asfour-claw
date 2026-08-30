#!/usr/bin/env bash
# Read and write appointments in the local Radicale CalDAV server.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a
# shellcheck source=bin/_dedupe.sh
. "$(dirname "${BASH_SOURCE[0]}")/_dedupe.sh"

# A repeated add is the one that leaves a duplicate appointment behind; list and
# remove are safe to run twice.
if [ "${1:-}" = "add" ] && already_written calendar "$@"; then
    echo "Already added moments ago: ${2:-}"
    exit 0
fi

exec "$HOME/radicale-venv/bin/python" "$HOME/bin/_calendar.py" "$@"
