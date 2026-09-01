#!/usr/bin/env python3
"""CLI for _prayer.py. See prayer.sh for usage.

`next` prints JSON because its only real caller is the cron trigger script,
which needs to compare a stable identifier across evaluations to avoid
announcing the same prayer twice.
"""
import json
import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _prayer  # noqa: E402


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "today"
    try:
        cfg = _prayer.settings()
    except _prayer.NotConfigured as e:
        print(f"prayer: {e}", file=sys.stderr)
        return 2

    now = datetime.now(cfg["tz"])

    if cmd == "today":
        # Only the first future entry is "next" -- marking every one of them,
        # which is what a bare `when > now` does, says nothing at all.
        marked = False
        for name, when in sorted(_prayer.times(now.date()).items(), key=lambda kv: kv[1]):
            mark = ""
            if not marked and when > now:
                mark, marked = "  <- next", True
            print(f"{_prayer.NAMES_AR[name]:<8} {name:<8} {when:%H:%M}{mark}")
        return 0

    if cmd == "next":
        lead = 0
        if "--minutes" in argv:
            lead = int(argv[argv.index("--minutes") + 1])
        name, when = _prayer.upcoming(now)
        if not name:
            print(json.dumps({"error": "no upcoming prayer"}))
            return 1
        in_secs = (when - now).total_seconds()
        print(json.dumps({
            "id": f"{when:%Y-%m-%d}:{name}",
            "name": name,
            "name_ar": _prayer.NAMES_AR[name],
            "at": when.isoformat(timespec="minutes"),
            "hhmm": f"{when:%H:%M}",
            "in_minutes": round(in_secs / 60),
            # A lead of 0 means "not until it arrives", which upcoming() can
            # never satisfy -- it only returns prayers still in the future. Use
            # `due` for that. The earlier `bool(lead and ...)` also made 0 mean
            # "never" rather than "now", so the trigger could not fire at all.
            "due": lead > 0 and 0 <= in_secs <= lead * 60,
        }, ensure_ascii=False))
        return 0

    if cmd == "due":
        # Has a prayer arrived within the last `window` minutes? This is what a
        # once-a-minute job asks, and it announces on time rather than early.
        window = 2
        if "--window" in argv:
            window = int(argv[argv.index("--window") + 1])
        name, when = _prayer.most_recent(now)
        if not name:
            print(json.dumps({"due": False}))
            return 0
        ago = (now - when).total_seconds()
        print(json.dumps({
            # Stable across evaluations, so the trigger fires exactly once.
            "id": f"{when:%Y-%m-%d}:{name}",
            "name": name,
            "name_ar": _prayer.NAMES_AR[name],
            "at": when.isoformat(timespec="minutes"),
            "hhmm": f"{when:%H:%M}",
            "minutes_ago": round(ago / 60),
            "due": 0 <= ago <= window * 60,
        }, ensure_ascii=False))
        return 0

    print(f"prayer: unknown command {cmd!r}; try today, next or due", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
