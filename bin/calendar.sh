#!/usr/bin/env bash
# Read and write appointments in the local Radicale CalDAV server.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a
exec "$HOME/radicale-venv/bin/python" "$HOME/bin/_calendar.py" "$@"
