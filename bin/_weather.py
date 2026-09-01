"""Weather from Open-Meteo. No API key, no account, no tracking.

Home coordinates come from the environment, like the prayer times and for the
same reason: this repo is public and a home's location is not source. A named
place is looked up on demand, so "الطقس في <البلدة>" works without anything
being configured for it.

Output is Arabic, because the assistant answers in Arabic and a translation step
is a chance to get the numbers wrong.
"""
import json
import os
import urllib.parse
import urllib.request

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 15

# WMO 4677. Given in Arabic so nothing downstream has to translate a code.
CODES = {
    0: "صحو",
    1: "صحو غالباً",
    2: "غائم جزئياً",
    3: "غائم",
    45: "ضباب",
    48: "ضباب متجمد",
    51: "رذاذ خفيف",
    53: "رذاذ",
    55: "رذاذ كثيف",
    56: "رذاذ متجمد خفيف",
    57: "رذاذ متجمد",
    61: "مطر خفيف",
    63: "مطر",
    65: "مطر غزير",
    66: "مطر متجمد خفيف",
    67: "مطر متجمد",
    71: "ثلج خفيف",
    73: "ثلج",
    75: "ثلج كثيف",
    77: "حبيبات ثلجية",
    80: "زخات مطر خفيفة",
    81: "زخات مطر",
    82: "زخات مطر غزيرة",
    85: "زخات ثلج خفيفة",
    86: "زخات ثلج",
    95: "عاصفة رعدية",
    96: "عاصفة رعدية مع برد خفيف",
    99: "عاصفة رعدية مع برد",
}

DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


class WeatherError(Exception):
    pass


def _get(url, params):
    query = urllib.parse.urlencode(params, doseq=True)
    try:
        with urllib.request.urlopen(f"{url}?{query}", timeout=TIMEOUT) as r:
            return json.load(r)
    except Exception as e:
        raise WeatherError(f"could not reach the weather service: {e}") from e


def describe(code):
    return CODES.get(int(code), f"رمز {code}")


def home(env=os.environ):
    """(lat, lon, label) for the household.

    Falls back to the prayer coordinates, which are already configured and
    describe the same house. Setting WEATHER_LAT/WEATHER_LON separately is only
    needed if the two should differ, which they should not.
    """
    lat = env.get("WEATHER_LAT") or env.get("PRAYER_LAT")
    lon = env.get("WEATHER_LON") or env.get("PRAYER_LON")
    if not lat or not lon:
        raise WeatherError(
            "no coordinates set. WEATHER_LAT/WEATHER_LON, or the PRAYER_LAT/PRAYER_LON "
            "already used for prayer times."
        )
    return float(lat), float(lon), env.get("WEATHER_PLACE", "")


def find_place(name):
    """(lat, lon, label) for a named place, or raise."""
    data = _get(GEOCODE_URL, {"name": name, "count": 1, "language": "ar", "format": "json"})
    results = data.get("results") or []
    if not results:
        # Arabic names are patchier in the gazetteer than Latin ones, so a miss
        # is retried in French before giving up -- this household's places are
        # mostly French.
        data = _get(GEOCODE_URL, {"name": name, "count": 1, "language": "fr", "format": "json"})
        results = data.get("results") or []
    if not results:
        raise WeatherError(f"لم أجد مكاناً باسم {name}")
    r = results[0]
    # Name and country only. The region comes back in whichever language the
    # gazetteer has it, so including it gives labels that mix scripts mid-phrase.
    label = ", ".join(x for x in (r.get("name"), r.get("country")) if x)
    return float(r["latitude"]), float(r["longitude"]), label


def current(lat, lon):
    data = _get(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "current": ["temperature_2m", "apparent_temperature", "relative_humidity_2m",
                    "precipitation", "weather_code", "wind_speed_10m"],
        "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"],
        "forecast_days": 1,
    })
    c = data.get("current", {})
    d = data.get("daily", {})
    return {
        "temp": c.get("temperature_2m"),
        "feels": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"),
        "precip": c.get("precipitation"),
        "wind": c.get("wind_speed_10m"),
        "code": c.get("weather_code"),
        "desc": describe(c.get("weather_code", -1)),
        "high": (d.get("temperature_2m_max") or [None])[0],
        "low": (d.get("temperature_2m_min") or [None])[0],
        "rain_chance": (d.get("precipitation_probability_max") or [None])[0],
    }


def forecast(lat, lon, days=3):
    days = max(1, min(7, int(days)))
    data = _get(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min",
                  "precipitation_probability_max"],
        "forecast_days": days,
    })
    d = data.get("daily", {})
    out = []
    for i, date in enumerate(d.get("time", [])):
        out.append({
            "date": date,
            "desc": describe((d.get("weather_code") or [])[i]),
            "high": (d.get("temperature_2m_max") or [])[i],
            "low": (d.get("temperature_2m_min") or [])[i],
            "rain_chance": (d.get("precipitation_probability_max") or [])[i],
        })
    return out
