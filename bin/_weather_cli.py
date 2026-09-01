#!/usr/bin/env python3
"""CLI for _weather.py. See weather.sh for usage.

Prints Arabic prose rather than JSON, because the only caller is a model that
has to say it out loud. Handing it numbers to assemble is a chance for it to
assemble them wrongly.
"""
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _weather  # noqa: E402


def n(v, unit=""):
    if v is None:
        return "غير معروف"
    return f"{round(v)}{unit}" if float(v) == int(float(v)) or abs(v) >= 10 else f"{v}{unit}"


def where(argv):
    """(lat, lon, label) from a place argument, else home.

    Bare digits are the day count for `forecast`, not a place: "forecast 3" was
    otherwise looked up as a town called 3.
    """
    place = " ".join(a for a in argv if not a.startswith("-") and not a.isdigit()).strip()
    if place:
        return _weather.find_place(place)
    lat, lon, label = _weather.home()
    return lat, lon, label


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "now"
    rest = argv[2:]
    if cmd not in ("now", "today", "forecast"):
        # "weather.sh <town>" should work without a subcommand.
        rest = argv[1:]
        cmd = "now"

    try:
        lat, lon, label = where(rest)
        here = f" في {label}" if label else ""

        if cmd in ("now", "today"):
            w = _weather.current(lat, lon)
            parts = [f"الطقس{here} الآن: {w['desc']}، {n(w['temp'], '°')}"]
            if w["feels"] is not None and abs((w["feels"] or 0) - (w["temp"] or 0)) >= 2:
                parts.append(f"محسوسة {n(w['feels'], '°')}")
            if w["high"] is not None and w["low"] is not None:
                parts.append(f"اليوم بين {n(w['low'], '°')} و{n(w['high'], '°')}")
            if w["rain_chance"]:
                parts.append(f"احتمال المطر {n(w['rain_chance'], '%')}")
            if w["wind"] is not None and w["wind"] >= 20:
                parts.append(f"رياح {n(w['wind'])} كم/س")
            print("، ".join(parts) + ".")
            return 0

        days = 3
        for a in rest:
            if a.isdigit():
                days = int(a)
        print(f"توقعات الطقس{here}:")
        for day in _weather.forecast(lat, lon, days):
            d = datetime.date.fromisoformat(day["date"])
            name = _weather.DAYS_AR[d.weekday()]
            line = f"  {name} {d:%d/%m}: {day['desc']}، {n(day['low'], '°')} إلى {n(day['high'], '°')}"
            if day["rain_chance"]:
                line += f"، مطر {n(day['rain_chance'], '%')}"
            print(line)
        return 0

    except _weather.WeatherError as e:
        print(f"{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
