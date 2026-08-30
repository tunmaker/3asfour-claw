#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${OPENCLAW_ENV:-$HOME/.openclaw/openclaw.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
# shellcheck source=bin/_dedupe.sh
. "$(dirname "${BASH_SOURCE[0]}")/_dedupe.sh"
DATA_DIR="${ABBES_DATA_DIR:-/var/lib/abbes}/babylog"
TZ_NAME="Europe/Paris"

usage() {
    cat <<'EOF'
Usage:
  baby-log.sh feed <amount_ml> [note]
  baby-log.sh sleep <start HH:MM> <end HH:MM> [note]
  baby-log.sh list [feed|sleep] [days]

Times are 24-hour Europe/Paris. Amounts are millilitres.
Every write prints the exact row that was stored.
EOF
}

stream_file() {
    local stream="$1"
    printf '%s/%s-%s.csv' "$DATA_DIR" "$stream" "$(TZ=$TZ_NAME date +%Y-%m)"
}

ensure_header() {
    local f="$1" header="$2"
    [ -f "$f" ] || printf '%s\n' "$header" > "$f"
}

append_row() {
    local f="$1" row="$2"
    exec 9>>"$f"
    flock -w 10 9 || { echo "could not lock $f" >&2; exit 1; }
    printf '%s\n' "$row" >&9
    exec 9>&-
    local stored
    stored=$(tail -n 1 "$f")
    if [ "$stored" != "$row" ]; then
        echo "write verification FAILED: stored row does not match" >&2
        exit 1
    fi
    echo "$stored"
}

mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

case "${1:-}" in
feed)
    [ $# -ge 2 ] || { usage; exit 2; }
    amount="$2"
    [[ "$amount" =~ ^[0-9]+$ ]] || { echo "amount_ml must be an integer" >&2; exit 2; }
    note="${3:-}"
    if already_written baby-log feed "$amount" "$note"; then
        echo "ALREADY LOGGED: the same feed was recorded moments ago; nothing added"
        exit 0
    fi
    f=$(stream_file feed)
    ensure_header "$f" "timestamp,amount_ml,note"
    row="$(TZ=$TZ_NAME date '+%Y-%m-%d %H:%M'),${amount},$(printf '%s' "$note" | tr ',\n' '; ')"
    echo "STORED ROW: $(append_row "$f" "$row")"
    echo "FILE: $f"
    ;;
sleep)
    [ $# -ge 3 ] || { usage; exit 2; }
    start="$2"; end="$3"; note="${4:-}"
    for t in "$start" "$end"; do
        [[ "$t" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "times must be HH:MM (24-hour)" >&2; exit 2; }
    done
    if already_written baby-log sleep "$start" "$end" "$note"; then
        echo "ALREADY LOGGED: the same sleep was recorded moments ago; nothing added"
        exit 0
    fi
    f=$(stream_file sleep)
    ensure_header "$f" "date,start,end,minutes,note"
    s=$(( 10#${start%%:*} * 60 + 10#${start##*:} ))
    e=$(( 10#${end%%:*} * 60 + 10#${end##*:} ))
    [ "$e" -lt "$s" ] && e=$(( e + 1440 ))
    row="$(TZ=$TZ_NAME date +%Y-%m-%d),${start},${end},$(( e - s )),$(printf '%s' "$note" | tr ',\n' '; ')"
    echo "STORED ROW: $(append_row "$f" "$row")"
    echo "FILE: $f"
    ;;
list)
    stream="${2:-feed}"
    days="${3:-7}"
    f=$(stream_file "$stream")
    [ -f "$f" ] || { echo "no entries for $stream this month"; exit 0; }
    cutoff=$(TZ=$TZ_NAME date -d "-${days} days" +%Y-%m-%d)
    head -n 1 "$f"
    awk -F, -v c="$cutoff" 'NR>1 && substr($1,1,10) >= c' "$f"
    ;;
*)
    usage
    exit 2
    ;;
esac
