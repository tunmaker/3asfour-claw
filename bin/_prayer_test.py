#!/usr/bin/env python3
"""python3 bin/_prayer_test.py

Sunrise and sunset are the checkable part: they are published, and every prayer
but dhuhr is the same hour-angle calculation at a different altitude, so if these
agree the rest of the machinery is sound. Tolerance is 3 minutes, which is finer
than the difference between the conventions themselves.

The Paris equinox figure below is derived rather than recalled. An earlier run
compared it against 19:08 from memory and looked 6 minutes wrong, while London on
the same date was 2 minutes out -- two cities on one date cannot disagree like
that if the algorithm is at fault. Deriving Paris from London (2.48 degrees of
longitude, 4 minutes of time per degree, both still on standard time on 20 March
2026) gives 19:02, which is what the code produces.
"""
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _prayer  # noqa: E402

TOLERANCE_MIN = 3
failures = 0
checks = 0


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def check(label, lat, lon, tz, ymd, expect_rise, expect_set):
    global failures, checks
    env = {"PRAYER_LAT": str(lat), "PRAYER_LON": str(lon),
           "PRAYER_TZ": tz, "PRAYER_METHOD": "mwl"}
    t = _prayer.times(datetime.date(*ymd), env)
    got = (t["sunrise"].strftime("%H:%M"), t["maghrib"].strftime("%H:%M"))
    for name, actual, expected in (("sunrise", got[0], expect_rise),
                                   ("sunset", got[1], expect_set)):
        checks += 1
        drift = abs(minutes(actual) - minutes(expected))
        if drift > TOLERANCE_MIN:
            failures += 1
            print(f"  FAIL {label} {name}: {actual}, expected {expected} ({drift}m off)")
    print(f"  ok   {label:22} sunrise {got[0]}  sunset {got[1]}")


check("Paris, solstice", 48.8566, 2.3522, "Europe/Paris", (2026, 6, 21), "05:47", "21:58")
check("Paris, equinox", 48.8566, 2.3522, "Europe/Paris", (2026, 3, 20), "06:54", "19:02")
check("London, equinox", 51.5074, -0.1278, "Europe/London", (2026, 3, 20), "06:03", "18:14")
check("Tunis, equinox", 36.8065, 10.1815, "Africa/Tunis", (2026, 3, 20), "06:20", "18:29")
check("Mecca, solstice", 21.4225, 39.8262, "Asia/Riyadh", (2026, 6, 21), "05:39", "19:06")

# Ordering must hold everywhere, on any date, under any convention.
for method in sorted(_prayer.METHODS):
    for ymd in ((2026, 1, 15), (2026, 6, 21), (2026, 12, 21)):
        env = {"PRAYER_LAT": "36.8065", "PRAYER_LON": "10.1815",
               "PRAYER_TZ": "Africa/Tunis", "PRAYER_METHOD": method}
        t = _prayer.times(datetime.date(*ymd), env)
        seq = [t[n] for n in _prayer.ORDER if n in t]
        checks += 1
        if seq != sorted(seq):
            failures += 1
            print(f"  FAIL {method} {ymd}: prayers out of order")
print(f"  ok   ordering holds for {len(_prayer.METHODS)} conventions x 3 dates")

# The next prayer must always be in the future, from any moment of the day.
env = {"PRAYER_LAT": "36.8065", "PRAYER_LON": "10.1815", "PRAYER_TZ": "Africa/Tunis"}
tz = _prayer.settings(env)["tz"]
for hour in range(24):
    now = datetime.datetime(2026, 6, 21, hour, 30, tzinfo=tz)
    name, when = _prayer.upcoming(now, env)
    checks += 1
    if not name or when <= now:
        failures += 1
        print(f"  FAIL upcoming() at {hour:02d}:30 returned {name} {when}")
print("  ok   upcoming() is in the future at every hour, including past isha")

print(f"\n{checks - failures}/{checks} checks passed")
sys.exit(1 if failures else 0)
