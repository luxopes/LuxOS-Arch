"""LuxOS Pocasi - data z Open-Meteo (bez klice): predpoved, hledani mest, mezipamet a jednotky.

  forecast(loc, units)          predpoved z mezipameti (30 min) nebo z Open-Meteo; bez site posledni data
  search(name, lang)            hledani mesta (geocoding API Open-Meteo)
  timezone_city()               mesto podle casoveho pasma systemu (vychozi poloha, bez sluzby polohy)
  ip_location()                 priblizna poloha podle IP adresy (ipinfo.io) - jen po souhlasu uzivatele

Mezipamet: $XDG_CACHE_HOME/luxos/weather, nastaveni: $XDG_CONFIG_HOME/luxos/weather.json.
Testy prepisuji adresy sluzeb: LUXOS_WEATHER_API, LUXOS_WEATHER_GEO, LUXOS_WEATHER_IP.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("LUXOS_WEATHER_API") or "https://api.open-meteo.com/v1/forecast"
GEO = os.environ.get("LUXOS_WEATHER_GEO") or "https://geocoding-api.open-meteo.com/v1/search"
IPLOC = os.environ.get("LUXOS_WEATHER_IP") or "https://ipinfo.io/json"
TTL = 30 * 60              # stari dat, po kterem se stahuji znovu
TIMEOUT = 12
USER_AGENT = "LuxOS-Weather/1.0 (+https://github.com/luxopes/LuxOS-Arch)"
# Zeme, kde se bezne pouzivaji stupne Fahrenheita a mile
IMPERIAL = {"US", "LR", "MM", "BS", "BZ", "KY", "PW", "FM", "MH"}

CURRENT = ("temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,"
           "wind_speed_10m,wind_direction_10m,precipitation,pressure_msl")
HOURLY = "temperature_2m,weather_code,precipitation_probability,is_day"
DAILY = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
         "precipitation_sum,sunrise,sunset,uv_index_max")


class WeatherError(Exception):
    pass


# ---- cesty a nastaveni -----------------------------------------------------------
def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "luxos", "weather")


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "luxos", "weather.json")


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_config():
    cfg = _read_json(config_path())
    if not isinstance(cfg, dict):
        cfg = {}
    locs = cfg.get("locations")
    cfg["locations"] = [l for l in locs if valid_location(l)] if isinstance(locs, list) else []
    if cfg.get("units") not in ("auto", "metric", "imperial"):
        cfg["units"] = "auto"
    sel = cfg.get("selected")
    cfg["selected"] = sel if isinstance(sel, int) and 0 <= sel < len(cfg["locations"]) else 0
    return cfg


def save_config(cfg):
    try:
        _write_json(config_path(), cfg)
    except OSError:
        pass


def valid_location(loc):
    return (isinstance(loc, dict) and isinstance(loc.get("name"), str)
            and isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lon"), (int, float)))


def same_place(a, b):
    return abs(a["lat"] - b["lat"]) < 0.02 and abs(a["lon"] - b["lon"]) < 0.02


# ---- jednotky --------------------------------------------------------------------
def locale_country(env=None):
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MEASUREMENT", "LANG"):
        v = env.get(var) or ""
        if v:
            v = v.split(".")[0].split("@")[0]
            return v.split("_")[1].upper() if "_" in v else ""
    return ""


def default_units(env=None):
    return "imperial" if locale_country(env) in IMPERIAL else "metric"


def resolve_units(setting, env=None):
    return setting if setting in ("metric", "imperial") else default_units(env)


def unit_params(units):
    if units == "imperial":
        return {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}
    return {"temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}


def unit_labels(units):
    if units == "imperial":
        return {"temp": "°F", "wind": "mph", "precip": "in"}
    return {"temp": "°C", "wind": "km/h", "precip": "mm"}


# ---- kody pocasi WMO -------------------------------------------------------------
# kod -> (ikona, popis); ikona s "-day" ma i nocni variantu "-night"
CODES = {
    0: ("clear", "Clear Sky"),
    1: ("partly-cloudy", "Mostly Clear"),
    2: ("partly-cloudy", "Partly Cloudy"),
    3: ("cloudy", "Cloudy"),
    45: ("fog", "Fog"),
    48: ("fog", "Freezing Fog"),
    51: ("drizzle", "Light Drizzle"),
    53: ("drizzle", "Drizzle"),
    55: ("drizzle", "Heavy Drizzle"),
    56: ("sleet", "Freezing Drizzle"),
    57: ("sleet", "Freezing Drizzle"),
    61: ("rain", "Light Rain"),
    63: ("rain", "Rain"),
    65: ("heavy-rain", "Heavy Rain"),
    66: ("sleet", "Freezing Rain"),
    67: ("sleet", "Freezing Rain"),
    71: ("snow", "Light Snow"),
    73: ("snow", "Snow"),
    75: ("snow", "Heavy Snow"),
    77: ("snow", "Snow Grains"),
    80: ("showers", "Showers"),
    81: ("showers", "Showers"),
    82: ("heavy-rain", "Heavy Showers"),
    85: ("snow", "Snow Showers"),
    86: ("snow", "Heavy Snow Showers"),
    95: ("storm", "Thunderstorm"),
    96: ("storm", "Thunderstorm with Hail"),
    99: ("storm", "Thunderstorm with Hail"),
}


def condition(code):
    """Anglicky popis (k prekladu) kodu WMO."""
    return CODES.get(code, ("cloudy", "Unknown"))[1]


def icon_name(code, is_day=True):
    """Nazev ikony v /usr/share/luxos/weather/icons (bez .svg)."""
    key = CODES.get(code, ("cloudy", ""))[0]
    if key in ("clear", "partly-cloudy"):
        return f"{key}-{'day' if is_day else 'night'}"
    if key == "showers":
        return "showers-day" if is_day else "rain"
    return key


def sky(code, is_day=True):
    """Skupina pozadi okna: clear, cloudy, rain, storm, snow, fog (+ -night)."""
    key = CODES.get(code, ("cloudy", ""))[0]
    group = {"clear": "clear", "partly-cloudy": "clear", "cloudy": "cloudy", "fog": "fog",
             "drizzle": "rain", "rain": "rain", "heavy-rain": "rain", "showers": "rain",
             "sleet": "snow", "snow": "snow", "storm": "storm"}.get(key, "cloudy")
    return group if is_day else group + "-night"


# ---- HTTP ------------------------------------------------------------------------
def http_json(url, params=None, timeout=TIMEOUT):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        e.close()
        raise WeatherError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise WeatherError(str(getattr(e, "reason", e))) from e
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise WeatherError("invalid response") from e


# ---- hledani a poloha ------------------------------------------------------------
def parse_places(data):
    out = []
    for r in (data or {}).get("results") or []:
        try:
            loc = {"name": str(r["name"]), "lat": float(r["latitude"]), "lon": float(r["longitude"])}
        except (KeyError, TypeError, ValueError):
            continue
        loc["admin"] = str(r.get("admin1") or "")
        loc["country"] = str(r.get("country") or "")
        loc["country_code"] = str(r.get("country_code") or "")
        loc["tz"] = str(r.get("timezone") or "")
        out.append(loc)
    return out


def search(name, lang="en", count=8):
    name = (name or "").strip()
    if len(name) < 2:
        return []
    return parse_places(http_json(GEO, {"name": name, "count": count, "language": lang, "format": "json"}))


def system_timezone():
    tz = os.environ.get("LUXOS_WEATHER_TZ")
    if tz:
        return tz
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        with open("/etc/timezone", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def timezone_city(lang="en", tz=None):
    """Mesto z nazvu casoveho pasma (Europe/Prague -> Praha) - jen hledani mesta, ne poloha."""
    tz = tz if tz is not None else system_timezone()
    if "/" not in tz or tz.startswith("Etc/"):
        return None
    city = tz.rsplit("/", 1)[1].replace("_", " ")
    places = search(city, lang, count=10)
    for p in places:
        if p["tz"] == tz:
            return p
    return None


def ip_location():
    """Priblizna poloha podle IP (ipinfo.io). Volat jen po souhlasu uzivatele."""
    data = http_json(IPLOC)
    try:
        lat, lon = (float(x) for x in str(data["loc"]).split(","))
    except (KeyError, ValueError, TypeError) as e:
        raise WeatherError("no location") from e
    return {"name": str(data.get("city") or "?"), "lat": lat, "lon": lon,
            "admin": str(data.get("region") or ""), "country": "", "country_code": str(data.get("country") or ""),
            "tz": str(data.get("timezone") or "")}


# ---- predpoved -------------------------------------------------------------------
def cache_file(loc, units):
    return os.path.join(cache_dir(), f"forecast-{loc['lat']:.3f}_{loc['lon']:.3f}-{units}.json")


def fetch_raw(loc, units):
    params = {"latitude": f"{loc['lat']:.4f}", "longitude": f"{loc['lon']:.4f}", "current": CURRENT,
              "hourly": HOURLY, "daily": DAILY, "timezone": "auto", "forecast_days": 7,
              "forecast_hours": 48}
    params.update(unit_params(units))
    return http_json(API, params)


def forecast(loc, units, force=False, now=None):
    """Vraci {"data": rozparsovana predpoved, "fetched": cas, "stale": bool, "error": text|None}.
    Data mladsi nez TTL se berou z mezipameti; bez site se vrati posledni ulozena (stale)."""
    now = time.time() if now is None else now
    path = cache_file(loc, units)
    cached = _read_json(path)
    if isinstance(cached, dict) and not force and now - cached.get("fetched", 0) < TTL:
        try:
            return {"data": parse_forecast(cached["raw"]), "fetched": cached["fetched"], "stale": False,
                    "error": None}
        except (KeyError, TypeError, ValueError, IndexError):
            cached = None
    try:
        raw = fetch_raw(loc, units)
        data = parse_forecast(raw)
    except (WeatherError, KeyError, TypeError, ValueError, IndexError) as e:
        err = str(e) or type(e).__name__
        if isinstance(cached, dict) and "raw" in cached:
            try:
                return {"data": parse_forecast(cached["raw"]), "fetched": cached.get("fetched", 0),
                        "stale": True, "error": err}
            except (KeyError, TypeError, ValueError, IndexError):
                pass
        return {"data": None, "fetched": 0, "stale": True, "error": err}
    try:
        _write_json(path, {"fetched": now, "raw": raw})
    except OSError:
        pass
    return {"data": data, "fetched": now, "stale": False, "error": None}


def cached_forecast(loc, units):
    """Jen data z mezipameti (okamzite pri startu, bez site); None kdyz nejsou."""
    cached = _read_json(cache_file(loc, units))
    if not isinstance(cached, dict):
        return None
    try:
        return {"data": parse_forecast(cached["raw"]), "fetched": cached.get("fetched", 0),
                "stale": time.time() - cached.get("fetched", 0) >= TTL, "error": None}
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _num(v):
    return None if v is None else float(v)


def parse_forecast(raw):
    """Odpoved Open-Meteo -> {"current", "hourly" (24 h od aktualni hodiny), "daily" (7 dni), "tz"}."""
    cur = raw["current"]
    current = {
        "time": cur["time"],
        "temp": float(cur["temperature_2m"]),
        "feels": _num(cur.get("apparent_temperature")),
        "humidity": _num(cur.get("relative_humidity_2m")),
        "code": int(cur["weather_code"]),
        "is_day": bool(cur.get("is_day", 1)),
        "wind": _num(cur.get("wind_speed_10m")),
        "wind_dir": _num(cur.get("wind_direction_10m")),
        "precip": _num(cur.get("precipitation")),
        "pressure": _num(cur.get("pressure_msl")),
    }
    h = raw["hourly"]
    times = h["time"]
    hour = current["time"][:13]
    start = next((i for i, t in enumerate(times) if t[:13] >= hour), 0)
    hourly = []
    for i in range(start, min(start + 24, len(times))):
        hourly.append({
            "time": times[i],
            "temp": float(h["temperature_2m"][i]),
            "code": int(h["weather_code"][i]),
            "is_day": bool(h.get("is_day", [1] * len(times))[i]),
            "pop": _num((h.get("precipitation_probability") or [None] * len(times))[i]),
        })
    d = raw["daily"]
    daily = []
    for i, date in enumerate(d["time"][:7]):
        def col(name, default=None):
            values = d.get(name) or []
            return values[i] if i < len(values) else default
        daily.append({
            "date": date,
            "code": int(col("weather_code", 3)),
            "max": float(col("temperature_2m_max")),
            "min": float(col("temperature_2m_min")),
            "pop": _num(col("precipitation_probability_max")),
            "precip": _num(col("precipitation_sum")),
            "sunrise": col("sunrise") or "",
            "sunset": col("sunset") or "",
            "uv": _num(col("uv_index_max")),
        })
    if not daily:
        raise ValueError("no daily forecast")
    return {"current": current, "hourly": hourly, "daily": daily, "tz": raw.get("timezone", ""),
            "utc_offset": int(raw.get("utc_offset_seconds") or 0)}


# ---- souhrn pro Kalendar v horni liste ------------------------------------------------
def summary_path():
    return os.path.join(cache_dir(), "summary.json")


def write_summary(loc, result, units):
    """Kratky souhrn vybraneho mista (Kalendar ho ukaze pod datem, jen kdyz je cerstvy)."""
    data = result.get("data") if result else None
    if not data:
        return
    cur = data["current"]
    today = data["daily"][0]
    try:
        _write_json(summary_path(), {
            "name": loc["name"], "fetched": int(result.get("fetched", 0)), "units": units,
            "temp": round(cur["temp"]), "max": round(today["max"]), "min": round(today["min"]),
            "code": cur["code"], "is_day": cur["is_day"], "condition": condition(cur["code"]),
            "icon": icon_name(cur["code"], cur["is_day"]),
        })
    except OSError:
        pass


WINDS = ("North wind", "Northeast wind", "East wind", "Southeast wind", "South wind", "Southwest wind",
         "West wind", "Northwest wind")


def compass(deg):
    """Smer vetru (odkud fouka) jako anglicky text k prekladu."""
    if deg is None:
        return ""
    return WINDS[int((deg % 360) / 45 + 0.5) % 8]
