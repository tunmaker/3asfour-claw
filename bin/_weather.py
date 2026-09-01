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
    """(lat, lon, label) for the household -- what a missing place means.

    Coordinates come from WEATHER_LAT/LON, else the prayer coordinates, which
    describe the same house. Failing both, WEATHER_PLACE is geocoded, so a
    deployment configured with nothing but a town name still answers. The label
    is WEATHER_LABEL (the spoken, Arabic form) when set, else WEATHER_PLACE.
    """
    place = env.get("WEATHER_PLACE", "")
    label = env.get("WEATHER_LABEL") or place
    lat = env.get("WEATHER_LAT") or env.get("PRAYER_LAT")
    lon = env.get("WEATHER_LON") or env.get("PRAYER_LON")
    if lat and lon:
        return float(lat), float(lon), label
    if place:
        lat, lon, found = find_place(place)
        return lat, lon, label or found
    raise WeatherError(
        "no home configured: set WEATHER_PLACE, or PRAYER_LAT/PRAYER_LON."
    )


def find_place(name):
    """(lat, lon, label) for a named place, or raise."""
    data = _get(GEOCODE_URL, {"name": name, "count": 1, "language": "ar", "format": "json"})
    results = data.get("results") or []
    if not results:
        # `language` selects the language of the labels coming back, not how the
        # query is matched, so retrying the same Arabic string in French buys
        # nothing -- it was tried and it does not rescue a miss.
        #
        # Big cities carry Arabic alternate names in the gazetteer and resolve
        # fine (باريس، تونس، لندن، مرسيليا). Smaller towns do not: <البلدة> is
        # simply absent, and no query language changes that. The caller has to
        # try the Latin spelling.
        #
        # The message says so explicitly because of what happened without it: the
        # model read a bare "not found", decided <البلدة> must be الأرجنتين, and
        # reported the weather in Argentina as though it were the answer. A tool
        # that fails must say what would succeed, or it gets improvised over.
        raise WeatherError(
            f"لم أجد مكاناً باسم {name}. أعد المحاولة بالاسم اللاتيني "
            f"(مثلاً <town> بدل <البلدة>). لا تستعمل مكاناً آخر."
        )
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
