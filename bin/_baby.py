"""The baby journal: one append-only JSONL file of events.

This replaced two CSV streams (feed, sleep) that each refused to run without
every argument. A parent holding a baby says "سجّل رضعة" and nothing else, so
every command here works with what it was given and fills the rest in from the
journal or the clock -- and every fill-in is reported, because a default the
model does not repeat is a default nobody can correct.

Append-only on purpose. A sleep is two events, `sleep` then `wake`; the reader
pairs them. Nothing is ever rewritten, so the line printed back after a write is
exactly what is on disk.

The dedupe window shares its file and key format with bin/_dedupe.sh, so a
retried command is refused here for the same reason and in the same way as
everywhere else.
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import time
import zoneinfo

KINDS = ("feed", "sleep", "wake", "diaper", "note")
DIAPER = ("wet", "dirty", "both")
NAMES_AR = {"feed": "رضعة", "sleep": "نوم", "wake": "استيقاظ", "diaper": "حفاض", "note": "ملاحظة"}
DIAPER_AR = {"wet": "مبلل", "dirty": "متسخ", "both": "مبلل ومتسخ"}


class JournalError(Exception):
    pass


def settings(env=os.environ):
    data = pathlib.Path(env.get("ABBES_DATA_DIR", "/var/lib/abbes"))
    return {
        "journal": data / "babylog" / "journal.jsonl",
        "legacy_dir": data / "babylog",
        "dedupe": data / "state" / "writes.log",
        "dedupe_secs": int(env.get("DEDUPE_WINDOW_SECS", "90")),
        "tz": zoneinfo.ZoneInfo(env.get("BABY_TZ") or env.get("PRAYER_TZ") or "Europe/Paris"),
        "feed_ml": int(env.get("BABY_FEED_ML", "120")),
    }


def now(cfg):
    return dt.datetime.now(cfg["tz"]).replace(second=0, microsecond=0)


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M%z")


def parse_stamp(s, cfg):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M%z").astimezone(cfg["tz"])


def at_time(hhmm, cfg, reference=None):
    """Today at HH:MM; yesterday if that would be in the future."""
    ref = reference or now(cfg)
    h, m = hhmm.split(":")
    when = ref.replace(hour=int(h), minute=int(m))
    if when > ref:
        when -= dt.timedelta(days=1)
    return when


def is_hhmm(s):
    parts = s.split(":")
    return len(parts) == 2 and all(p.isdigit() for p in parts) and int(parts[0]) < 24 and int(parts[1]) < 60


def read(cfg):
    path = cfg["journal"]
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def already_written(cfg, args):
    if cfg["dedupe_secs"] <= 0:
        return False
    key = hashlib.sha256(b"".join(a.encode("utf-8") + b"\0" for a in args)).hexdigest()
    ts_now = int(time.time())
    cutoff = ts_now - cfg["dedupe_secs"]
    path = cfg["dedupe"]
    path.parent.mkdir(parents=True, exist_ok=True)
    kept, hit = [], False
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) >= cutoff:
                kept.append(line)
                hit = hit or parts[1] == key
    if not hit:
        kept.append(f"{ts_now} {key}")
    path.write_text("\n".join(kept) + "\n")
    return hit


def append(cfg, event, dedupe_args):
    if already_written(cfg, dedupe_args):
        raise JournalError("ALREADY LOGGED: the same entry was recorded moments ago; nothing added")
    path = cfg["journal"]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(event, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    stored = path.read_text(encoding="utf-8").splitlines()[-1]
    if stored != line:
        raise JournalError("write verification FAILED: stored line does not match")
    return stored


def last_of(events, kind):
    for e in reversed(events):
        if e["kind"] == kind:
            return e
    return None


def open_sleep(events):
    """The sleep with no wake after it, or None."""
    for e in reversed(events):
        if e["kind"] == "wake":
            return None
        if e["kind"] == "sleep":
            return None if e.get("end") else e
    return None


def feed(cfg, ml=None, note="", when=None):
    events = read(cfg)
    assumed = []
    if ml is None:
        prev = last_of(events, "feed")
        ml = prev["ml"] if prev else cfg["feed_ml"]
        assumed.append(f"الكمية {ml} مل مثل المرة السابقة" if prev else f"الكمية {ml} مل (الافتراضية)")
    when = when or now(cfg)
    event = {"ts": stamp(when), "kind": "feed", "ml": int(ml), "note": note}
    stored = append(cfg, event, ["baby", "feed", str(ml), note])
    return stored, assumed


def sleep(cfg, start=None, end=None, note=""):
    events = read(cfg)
    if open_sleep(events) and end is None and start is None:
        raise JournalError("النوم مسجّل بالفعل ولم يُسجَّل استيقاظ بعد. استعمل wake عند الاستيقاظ.")
    assumed = []
    t_now = now(cfg)
    if start is None:
        start_at = t_now
        assumed.append("بدأ النوم الآن")
    else:
        start_at = at_time(start, cfg, t_now)
    event = {"ts": stamp(start_at), "kind": "sleep", "note": note}
    if end is not None:
        end_at = at_time(end, cfg, t_now)
        if end_at < start_at:
            end_at += dt.timedelta(days=1)
        event["end"] = stamp(end_at)
        event["minutes"] = int((end_at - start_at).total_seconds() // 60)
    else:
        assumed.append("ما زال نائماً؛ سجّل wake عند الاستيقاظ")
    stored = append(cfg, event, ["baby", "sleep", start or "", end or "", note])
    return stored, assumed


def wake(cfg, at=None, note=""):
    events = read(cfg)
    started = open_sleep(events)
    if not started:
        raise JournalError("لا يوجد نوم مفتوح لتسجيل الاستيقاظ منه.")
    t_now = now(cfg)
    when = at_time(at, cfg, t_now) if at else t_now
    start_at = parse_stamp(started["ts"], cfg)
    if when < start_at:
        when += dt.timedelta(days=1)
    minutes = int((when - start_at).total_seconds() // 60)
    event = {"ts": stamp(when), "kind": "wake", "minutes": minutes, "note": note}
    stored = append(cfg, event, ["baby", "wake", at or "", note])
    return stored, ([] if at else ["استيقظ الآن"]), minutes


def diaper(cfg, state=None, note=""):
    assumed = []
    if state is None:
        state = "wet"
        assumed.append("حفاض مبلل (الافتراضي)")
    if state not in DIAPER:
        raise JournalError(f"diaper must be one of {', '.join(DIAPER)}")
    event = {"ts": stamp(now(cfg)), "kind": "diaper", "state": state, "note": note}
    stored = append(cfg, event, ["baby", "diaper", state, note])
    return stored, assumed


def note(cfg, text):
    if not text.strip():
        raise JournalError("a note needs text")
    event = {"ts": stamp(now(cfg)), "kind": "note", "note": text}
    return append(cfg, event, ["baby", "note", text]), []


def sleeps(events, cfg):
    """(start, end, minutes) for every sleep, pairing open ones with the next wake."""
    out, pending = [], None
    for e in events:
        if e["kind"] == "sleep":
            if e.get("end"):
                out.append((parse_stamp(e["ts"], cfg), parse_stamp(e["end"], cfg), e["minutes"]))
                pending = None
            else:
                pending = parse_stamp(e["ts"], cfg)
        elif e["kind"] == "wake" and pending:
            end = parse_stamp(e["ts"], cfg)
            out.append((pending, end, int((end - pending).total_seconds() // 60)))
            pending = None
    if pending:
        out.append((pending, None, int((now(cfg) - pending).total_seconds() // 60)))
    return out


def since(when, cfg):
    mins = int((now(cfg) - when).total_seconds() // 60)
    if mins < 60:
        return f"منذ {mins} دقيقة"
    h, m = divmod(mins, 60)
    return f"منذ {h} ساعة و{m} دقيقة" if m else f"منذ {h} ساعة"


def summary(cfg, days=1):
    events = read(cfg)
    if not events:
        return "لا توجد تسجيلات بعد."
    cutoff = now(cfg) - dt.timedelta(days=days)
    recent = [e for e in events if parse_stamp(e["ts"], cfg) >= cutoff]
    feeds = [e for e in recent if e["kind"] == "feed"]
    diapers = [e for e in recent if e["kind"] == "diaper"]
    naps = [s for s in sleeps(events, cfg) if s[0] >= cutoff]
    period = "اليوم" if days == 1 else f"في آخر {days} أيام"
    lines = [f"ملخص {period}:"]
    if feeds:
        lines.append(f"  الرضعات: {len(feeds)}، المجموع {sum(e['ml'] for e in feeds)} مل، "
                     f"آخرها {parse_stamp(feeds[-1]['ts'], cfg):%H:%M} ({since(parse_stamp(feeds[-1]['ts'], cfg), cfg)})")
    else:
        lines.append("  الرضعات: لا شيء مسجّل")
    if naps:
        total = sum(n[2] for n in naps)
        lines.append(f"  النوم: {len(naps)} مرات، المجموع {total // 60} ساعة و{total % 60} دقيقة")
        if naps[-1][1] is None:
            lines.append(f"  نائم الآن منذ {naps[-1][0]:%H:%M}")
    else:
        lines.append("  النوم: لا شيء مسجّل")
    if diapers:
        lines.append(f"  الحفاضات: {len(diapers)}، آخرها {parse_stamp(diapers[-1]['ts'], cfg):%H:%M}")
    return "\n".join(lines)


def last(cfg):
    events = read(cfg)
    if not events:
        return "لا توجد تسجيلات بعد."
    lines = []
    f = last_of(events, "feed")
    if f:
        lines.append(f"آخر رضعة: {parse_stamp(f['ts'], cfg):%H:%M}، {f['ml']} مل، {since(parse_stamp(f['ts'], cfg), cfg)}")
    naps = sleeps(events, cfg)
    if naps:
        s, e, m = naps[-1]
        lines.append(f"نائم الآن منذ {s:%H:%M} ({m} دقيقة)" if e is None
                     else f"آخر نوم: من {s:%H:%M} إلى {e:%H:%M}، {m} دقيقة، استيقظ {since(e, cfg)}")
    d = last_of(events, "diaper")
    if d:
        lines.append(f"آخر حفاض: {parse_stamp(d['ts'], cfg):%H:%M}، {DIAPER_AR[d['state']]}، {since(parse_stamp(d['ts'], cfg), cfg)}")
    return "\n".join(lines) or "لا توجد تسجيلات بعد."


def listing(cfg, days=1):
    events = read(cfg)
    cutoff = now(cfg) - dt.timedelta(days=days)
    out = []
    for e in events:
        when = parse_stamp(e["ts"], cfg)
        if when < cutoff:
            continue
        detail = {"feed": lambda: f"{e['ml']} مل",
                  "sleep": lambda: f"حتى {parse_stamp(e['end'], cfg):%H:%M} ({e['minutes']} د)" if e.get("end") else "بدأ",
                  "wake": lambda: f"بعد {e['minutes']} د",
                  "diaper": lambda: DIAPER_AR[e["state"]],
                  "note": lambda: ""}[e["kind"]]()
        out.append(f"{when:%d/%m %H:%M}  {NAMES_AR[e['kind']]:<8} {detail}  {e.get('note', '')}".rstrip())
    return "\n".join(out) or f"لا شيء مسجّل في آخر {days} يوم."


def import_legacy(cfg):
    """One-time import of the old feed-*.csv / sleep-*.csv streams."""
    if cfg["journal"].exists():
        return 0
    rows = []
    for csv in sorted(cfg["legacy_dir"].glob("*.csv")):
        for line in csv.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split(",")
            if csv.name.startswith("feed") and len(parts) >= 2:
                when = dt.datetime.strptime(parts[0], "%Y-%m-%d %H:%M").replace(tzinfo=cfg["tz"])
                rows.append({"ts": stamp(when), "kind": "feed", "ml": int(parts[1]), "note": ",".join(parts[2:])})
            elif csv.name.startswith("sleep") and len(parts) >= 4:
                day = dt.datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=cfg["tz"])
                start = at_time(parts[1], cfg, day.replace(hour=23, minute=59))
                end = at_time(parts[2], cfg, day.replace(hour=23, minute=59))
                if end < start:
                    end += dt.timedelta(days=1)
                rows.append({"ts": stamp(start), "kind": "sleep", "end": stamp(end),
                             "minutes": int(parts[3]), "note": ",".join(parts[4:])})
        csv.rename(csv.with_suffix(".csv.imported"))
    if not rows:
        return 0
    rows.sort(key=lambda r: r["ts"])
    cfg["journal"].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with cfg["journal"].open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)
