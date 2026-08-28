import os, sys, datetime as dt, zoneinfo
import caldav
from icalendar import Calendar, Event

TZ = zoneinfo.ZoneInfo(os.environ.get("OPENCLAW_TZ", "Europe/Paris"))
CAL_NAME = os.environ.get("RADICALE_CALENDAR", "perso")

def calendar():
    client = caldav.DAVClient(
        url=os.environ["RADICALE_URL"],
        username=os.environ["RADICALE_USER"],
        password=os.environ["RADICALE_PASSWORD"],
    )
    return client.principal().calendar(name=CAL_NAME)

def parse_when(text):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(text, fmt)
            return d.replace(tzinfo=TZ)
        except ValueError:
            continue
    raise SystemExit(f"unrecognised date/time: {text!r} (use 'YYYY-MM-DD HH:MM')")

def cmd_add(summary, when, minutes="60"):
    start = parse_when(when)
    end = start + dt.timedelta(minutes=int(minutes))
    cal = Calendar(); cal.add("prodid", "-//openclaw//calendar//FR"); cal.add("version", "2.0")
    ev = Event()
    ev.add("summary", summary); ev.add("dtstart", start); ev.add("dtend", end)
    ev.add("dtstamp", dt.datetime.now(TZ))
    ev.add("uid", f"{dt.datetime.now(TZ).timestamp()}-openclaw@llama")
    cal.add_component(ev)
    calendar().save_event(cal.to_ical().decode())
    print(f"Added: {summary} — {start:%Y-%m-%d %H:%M} to {end:%H:%M} ({TZ.key})")

def cmd_list(days="14"):
    start = dt.datetime.now(TZ)
    end = start + dt.timedelta(days=int(days))
    events = calendar().search(start=start, end=end, event=True, expand=True)
    if not events:
        print(f"No appointments in the next {days} days."); return
    rows = []
    for e in events:
        for comp in Calendar.from_ical(e.data).walk("VEVENT"):
            s = comp.get("dtstart").dt
            if isinstance(s, dt.datetime):
                s = s.astimezone(TZ)
                rows.append((s, f"{s:%Y-%m-%d %H:%M}  {comp.get('summary')}"))
            else:
                rows.append((dt.datetime.combine(s, dt.time(0), TZ),
                             f"{s:%Y-%m-%d} (journée)  {comp.get('summary')}"))
    for _, line in sorted(rows):
        print(line)

def cmd_remove(needle):
    hits = 0
    for e in calendar().events():
        for comp in Calendar.from_ical(e.data).walk("VEVENT"):
            if needle.lower() in str(comp.get("summary", "")).lower():
                e.delete(); hits += 1; print(f"Removed: {comp.get('summary')}")
                break
    if not hits:
        print(f"No appointment matches: {needle}")

if __name__ == "__main__":
    args = sys.argv[1:] or ["list"]
    cmd, rest = args[0], args[1:]
    try:
        {"add": cmd_add, "list": cmd_list, "remove": cmd_remove}[cmd](*rest)
    except KeyError:
        raise SystemExit("usage: calendar.sh [list <days> | add <summary> <YYYY-MM-DD HH:MM> [minutes] | remove <summary>]")
