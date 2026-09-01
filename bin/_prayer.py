"""Prayer times, computed here rather than fetched.

No network, no account, no mosque identifier in the tree. The inputs are a
latitude, a longitude and two twilight angles, all of which come from the
environment -- the location is configuration, never source, because the repo is
public and a home's coordinates are not.

The algorithm is the standard one (PrayTimes.org): solar declination and the
equation of time give solar noon, then each prayer is the hour angle at which
the sun reaches a given altitude. Asr is the moment a stick's shadow reaches its
noon length plus a multiple of the stick's height.

Angles are a convention, not a fact, and mosques differ. PRAYER_METHOD picks a
published set; PRAYER_FAJR_ANGLE and PRAYER_ISHA_ANGLE override it. Default is
the Tunisian Ministry of Religious Affairs, 18/18.
"""
import math
import os
from datetime import date as _date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Published twilight conventions. The pair is (fajr depression, isha depression)
# in degrees below the horizon.
METHODS = {
    "tunisia": (18.0, 18.0),      # Ministry of Religious Affairs
    "mwl": (18.0, 17.0),          # Muslim World League
    "isna": (15.0, 15.0),         # Islamic Society of North America
    "egypt": (19.5, 17.5),        # Egyptian General Authority of Survey
    "umm_al_qura": (18.5, 0.0),   # Isha is a fixed 90 min after maghrib
    "karachi": (18.0, 18.0),
}

# The sun's centre is this far below the horizon at apparent sunrise/sunset,
# accounting for refraction and the solar radius.
HORIZON = 0.833

ORDER = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")

NAMES_AR = {
    "fajr": "الفجر",
    "sunrise": "الشروق",
    "dhuhr": "الظهر",
    "asr": "العصر",
    "maghrib": "المغرب",
    "isha": "العشاء",
}


class NotConfigured(Exception):
    pass


def _julian_day(d):
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5


def _sun(jd):
    """(declination, equation of time in hours) for a Julian day."""
    d = jd - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)          # mean anomaly
    q = (280.459 + 0.98564736 * d) % 360                        # mean longitude
    lam = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.00000036 * d)                 # obliquity

    decl = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) / 15.0
    ra %= 24.0
    eqt = q / 15.0 - ra
    # q/15 and ra can straddle the 24h wrap; fold the difference back to +-12h.
    eqt = (eqt + 12) % 24 - 12
    return decl, eqt


def _hour_angle(altitude_deg, lat_rad, decl):
    """Hours from solar noon at which the sun sits at the given altitude.

    `altitude_deg` is signed: negative is below the horizon. Twilight angles are
    published as depressions, so they are passed in negated -- keeping the sign
    convention here rather than in the caller is what stopped asr, which is an
    altitude above the horizon, from being computed as its own mirror image.

    Returns None inside a polar day or night, where the sun never reaches it.
    """
    cos_h = (math.sin(math.radians(altitude_deg)) - math.sin(lat_rad) * math.sin(decl)) / (
        math.cos(lat_rad) * math.cos(decl)
    )
    if cos_h > 1 or cos_h < -1:
        return None
    return math.degrees(math.acos(cos_h)) / 15.0


def _asr_angle(factor, lat_rad, decl):
    """Altitude of the sun when a shadow is noon-length plus `factor` heights."""
    return math.degrees(math.atan(1.0 / (factor + math.tan(abs(lat_rad - decl)))))


def settings(env=os.environ):
    lat = env.get("PRAYER_LAT")
    lon = env.get("PRAYER_LON")
    if not lat or not lon:
        raise NotConfigured(
            "PRAYER_LAT and PRAYER_LON are not set. Prayer times need a location, "
            "and it is configuration rather than source because this repo is public."
        )
    method = env.get("PRAYER_METHOD", "tunisia").strip().lower()
    if method not in METHODS:
        raise NotConfigured(f"PRAYER_METHOD={method!r} is not one of: {', '.join(sorted(METHODS))}")
    fajr_default, isha_default = METHODS[method]
    return {
        "lat": float(lat),
        "lon": float(lon),
        "tz": ZoneInfo(env.get("PRAYER_TZ") or env.get("TZ") or "Europe/Paris"),
        "fajr_angle": float(env.get("PRAYER_FAJR_ANGLE", fajr_default)),
        "isha_angle": float(env.get("PRAYER_ISHA_ANGLE", isha_default)),
        "asr_factor": float(env.get("PRAYER_ASR_FACTOR", 1.0)),
        "method": method,
    }


def times(day=None, env=os.environ):
    """{name: aware datetime} for one local day."""
    cfg = settings(env)
    day = day or datetime.now(cfg["tz"]).date()

    # The UTC offset is taken for local noon so a DST boundary during the night
    # cannot pick the wrong side of the change.
    noon_local = datetime(day.year, day.month, day.day, 12, tzinfo=cfg["tz"])
    utc_offset = noon_local.utcoffset().total_seconds() / 3600.0

    jd = _julian_day(day) - cfg["lon"] / (15.0 * 24.0)
    decl, eqt = _sun(jd)
    lat_rad = math.radians(cfg["lat"])

    dhuhr = 12.0 + utc_offset - cfg["lon"] / 15.0 - eqt

    def at(offset_hours):
        if offset_hours is None:
            return None
        h = dhuhr + offset_hours
        return datetime(day.year, day.month, day.day, tzinfo=cfg["tz"]) + timedelta(hours=h)

    t_horizon = _hour_angle(-HORIZON, lat_rad, decl)
    out = {
        "fajr": at(_neg(_hour_angle(-cfg["fajr_angle"], lat_rad, decl))),
        "sunrise": at(_neg(t_horizon)),
        "dhuhr": at(0.0),
        "asr": at(_hour_angle(_asr_angle(cfg["asr_factor"], lat_rad, decl), lat_rad, decl)),
        "maghrib": at(t_horizon),
    }
    if cfg["method"] == "umm_al_qura" and out["maghrib"]:
        out["isha"] = out["maghrib"] + timedelta(minutes=90)
    else:
        out["isha"] = at(_hour_angle(-cfg["isha_angle"], lat_rad, decl))
    return {k: v for k, v in out.items() if v is not None}


def _neg(x):
    return None if x is None else -x


def most_recent(now=None, env=os.environ, include_sunrise=False):
    """(name, when) for the prayer that has most recently arrived.

    The counterpart to upcoming(), and the one a per-minute job actually needs.
    "Announce at the time itself" cannot be expressed with upcoming() alone: the
    instant a prayer arrives it stops being upcoming, so a check for "is the next
    prayer due now" is false a second before and looking at a different prayer a
    second after.
    """
    cfg = settings(env)
    now = now or datetime.now(cfg["tz"])
    wanted = [p for p in ORDER if include_sunrise or p != "sunrise"]

    best = (None, None)
    for offset in (0, -1):                 # today, then yesterday for after-isha
        day = (now + timedelta(days=offset)).date()
        for name, when in times(day, env).items():
            if name not in wanted or when > now:
                continue
            if best[1] is None or when > best[1]:
                best = (name, when)
        if best[1] is not None:
            break
    return best


def upcoming(now=None, env=os.environ, include_sunrise=False):
    """(name, when) for the next prayer, looking into tomorrow if need be."""
    cfg = settings(env)
    now = now or datetime.now(cfg["tz"])
    wanted = [p for p in ORDER if include_sunrise or p != "sunrise"]

    for offset in (0, 1):
        day = (now + timedelta(days=offset)).date()
        t = times(day, env)
        for name in wanted:
            when = t.get(name)
            if when and when > now:
                return name, when
    return None, None
