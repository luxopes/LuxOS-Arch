"""LuxOS Pocasi - data z Open-Meteo (bez klice): predpoved, hledani mest, mezipamet a jednotky.

  forecast(loc, units)          predpoved z mezipameti (30 min) nebo z Open-Meteo; bez site posledni data
  search(name, lang)            hledani mesta (geocoding API Open-Meteo)
  timezone_city()               mesto podle casoveho pasma systemu (vychozi poloha, bez sluzby polohy)
  ip_location()                 priblizna poloha podle IP adresy (ipinfo.io) - jen po souhlasu uzivatele
  detect_units(env, tz, places) vychozi jednotky: uzemi z LC_ALL/LC_MEASUREMENT/LANG, jinak zeme mista
  scene_for(data)               scena pozadi okna (druh oblohy + denni doba) z predpovedi

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
# Zeme a uzemi, kde se teplota bezne udava ve stupnich Fahrenheita: USA a jejich uzemi (Portoriko,
# Guam, Americke Panenske ostrovy, Americka Samoa, Severni Mariany, mensi odlehle ostrovy), pridruzene
# staty v Tichomori (Palau, Mikronesie, Marshallovy ostrovy), Bahamy, Belize, Kajmanske ostrovy a
# Liberie. Myanmar (MM) ne: tamni meteorologicka sluzba i zpravy udavaji °C.
FAHRENHEIT = {"US", "PR", "GU", "VI", "AS", "MP", "UM", "PW", "FM", "MH", "BS", "BZ", "KY", "LR"}
IMPERIAL = FAHRENHEIT           # starsi nazev (1.0.0-1)
CONFIG_VERSION = 2              # 2: jednotky "auto" podle uzemi/mista, jednorazovy dotaz na jednotky
ZONETAB = os.environ.get("LUXOS_WEATHER_ZONETAB") or "/usr/share/zoneinfo/zone.tab"

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
    cfg["animate"] = cfg.get("animate") is not False
    return migrate_config(cfg)


def migrate_config(cfg):
    """Jednorazovy prechod starsiho nastaveni (bez "version") na verzi 2.

    1.0.0-1 ukladalo "units": "auto", dokud uzivatel v nabidce nic nevybral; "metric"/"imperial"
    vznikly jen vyslovnou volbou. °F u "auto" byla chyba vychozich jednotek (LANG=en_US.UTF-8 je
    v LuxOS bezna anglictina i v Evrope), ne volba: "auto" zustava, nove se vyhodnoti podle uzemi
    a mista (detect_units) a aplikace se jednou zepta. Vyslovna volba se zachova a uz se neptame.
    Idempotentni; na disk se zapise az s dalsim save_config."""
    if not isinstance(cfg.get("version"), int) or cfg["version"] < CONFIG_VERSION:
        cfg["units_asked"] = cfg["units"] != "auto"
        cfg["version"] = CONFIG_VERSION
    cfg["units_asked"] = bool(cfg.get("units_asked"))
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


def json_cli(argv):
    """Rozhrani luxos-weather --json search|locations|forecast pro LuxAI, bez GTK.

    Nikdy nezjistuje polohu z IP. Bez souradnic pouzije jen ulozene vybrane misto.
    Nastaveni aplikace nemeni; ctou se i jeji jednotky a sdili se cache predpovedi.
    """
    import argparse
    import copy
    import math

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise WeatherError(message)

    parser = Parser(prog="luxos-weather --json", add_help=False)
    sub = parser.add_subparsers(dest="action", required=True, parser_class=Parser)
    search_parser = sub.add_parser("search", add_help=False)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=5)
    sub.add_parser("locations", add_help=False)
    forecast_parser = sub.add_parser("forecast", add_help=False)
    forecast_parser.add_argument("--latitude", type=float)
    forecast_parser.add_argument("--longitude", type=float)
    forecast_parser.add_argument("--name", default="")
    forecast_parser.add_argument("--units", choices=("auto", "metric", "imperial"), default="auto")
    forecast_parser.add_argument("--days", type=int, choices=range(1, 8), default=7)
    forecast_parser.add_argument("--hours", type=int, choices=range(0, 25), default=24)
    try:
        args = parser.parse_args(argv)
        if args.action == "search":
            if not 2 <= len(args.query.strip()) <= 200 or not 1 <= args.limit <= 10:
                raise WeatherError("Give a place name (2-200 characters) and a limit from 1 to 10")
            language = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or
                        os.environ.get("LANG") or "en").split("_")[0].split(".")[0]
            result = {"ok": True, "places": search(args.query, language, args.limit),
                      "source": "Open-Meteo", "source_url": "https://open-meteo.com/"}
        else:
            cfg = load_config()
            if args.action == "locations":
                result = {"ok": True, "locations": cfg["locations"], "selected": cfg["selected"],
                          "units": cfg["units"]}
            else:
                if (args.latitude is None) != (args.longitude is None):
                    raise WeatherError("Give both latitude and longitude")
                if args.latitude is None and args.name:
                    raise WeatherError("name is only a display label; search the city and give its coordinates")
                if args.latitude is not None:
                    if not (math.isfinite(args.latitude) and math.isfinite(args.longitude) and
                            -90 <= args.latitude <= 90 and -180 <= args.longitude <= 180):
                        raise WeatherError("Coordinates are outside their valid range")
                    loc = {"name": args.name[:200] or f"{args.latitude}, {args.longitude}",
                           "lat": args.latitude, "lon": args.longitude}
                elif cfg["locations"]:
                    loc = cfg["locations"][cfg["selected"]]
                else:
                    print(json.dumps({"ok": False, "needs_location": True,
                                      "error": "No saved weather location. Ask which city, then search for its coordinates."}))
                    return 1
                units = resolve_units(cfg["units"] if args.units == "auto" else args.units, places=[loc])
                prediction = forecast(loc, units)
                if prediction["data"] is None:
                    raise WeatherError(prediction["error"] or "Weather is unavailable")
                data = copy.deepcopy(prediction["data"])
                data["daily"] = data["daily"][:args.days]
                data["hourly"] = data["hourly"][:args.hours]
                for entry in [data["current"], *data["hourly"], *data["daily"]]:
                    entry["condition"] = condition(entry["code"])
                result = {"ok": True, "location": loc, "units": unit_labels(units),
                          "unit_system": units, "data": data, "fetched": prediction["fetched"],
                          "stale": prediction["stale"], "error": prediction["error"],
                          "source": "Open-Meteo", "source_url": "https://open-meteo.com/"}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (WeatherError, ValueError, TypeError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


# ---- jednotky --------------------------------------------------------------------
def _territory(value):
    """'cs_CZ.UTF-8' -> 'CZ', 'es_419' -> '419'; C, POSIX, C.UTF-8, 'en' (bez uzemi) -> ''."""
    v = (value or "").split(".")[0].split("@")[0]
    if "_" not in v:
        return ""
    t = v.split("_", 1)[1].upper()
    return t if t.isalnum() and 2 <= len(t) <= 3 else ""


def _locale_conf_measurement():
    """LC_ALL/LC_MEASUREMENT z ~/.config/locale.conf a /etc/locale.conf: zmena formatu (`lux system`,
    Nastaveni) plati hned, bez noveho prihlaseni - prostredi bezici relace ji jeste nema."""
    paths = os.environ.get("LUXOS_WEATHER_LOCALE_CONF")
    if paths is None:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        paths = [os.path.join(base, "locale.conf"), "/etc/locale.conf"]
    else:
        paths = [p for p in paths.split(":") if p]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                kv = {}
                for line in f:
                    if "=" in line and not line.lstrip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        kv[k.strip()] = v.strip().strip("\"'")
        except (OSError, UnicodeDecodeError):
            continue
        for var in ("LC_ALL", "LC_MEASUREMENT"):
            if kv.get(var):
                return var, kv[var]
    return "", ""


def locale_territory(env=None):
    """(uzemi, promenna) pro jednotky mereni v poradi POSIX/glibc: LC_ALL > LC_MEASUREMENT > LANG.
    Bez env (skutecny proces) se LC_ALL/LC_MEASUREMENT hleda i v locale.conf (zmena bez prihlaseni)."""
    real = env is None
    env = os.environ if real else env
    for var in ("LC_ALL", "LC_MEASUREMENT"):
        if env.get(var):
            return _territory(env[var]), var
    if real:
        var, value = _locale_conf_measurement()
        if value:
            return _territory(value), var
    if env.get("LANG"):
        return _territory(env["LANG"]), "LANG"
    return "", ""


def locale_country(env=None):
    return locale_territory(env)[0]


def zone_country(tz, zonetab=None):
    """Zeme casoveho pasma ('Europe/Prague' -> 'CZ') podle tzdata zone.tab; nezname -> ''."""
    if not tz or "/" not in tz:
        return ""
    if tz.startswith("US/"):
        return "US"
    path = zonetab or ZONETAB
    for p in (path, os.path.join(os.path.dirname(path), "zone1970.tab")):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 3 and not line.startswith("#") and parts[2] == tz:
                        return parts[0].split(",")[0].upper()
        except OSError:
            continue
    return ""


def units_for_country(country):
    return "imperial" if (country or "").upper() in FAHRENHEIT else "metric"


def detect_units(env=None, tz=None, places=None, zonetab=None):
    """Vychozi jednotky a duvod: ("metric"|"imperial", "locale"|"place"|"timezone"|"default").

    1. Uzemi z LC_ALL, LC_MEASUREMENT, LANG (prvni nastavena promenna, jako glibc): °F jen pro
       FAHRENHEIT, jinak °C, km/h a mm (en_GB, cs_CZ, de_DE, es_419 ...).
    2. Vyjimka: uzemi US jen z LANG (bez LC_MEASUREMENT/LC_ALL) - en_US.UTF-8 je bezna vychozi
       anglictina LuxOS i Archu, i u lidi v Evrope. Rozhodne zeme prvniho ulozeneho mista, pak
       casoveho pasma systemu; kdyz ani jedna neni znama, °F.
    3. Bez uzemi (C, POSIX, C.UTF-8, nic): zeme prvniho mista, casoveho pasma, jinak °C.
    tz=None: casove pasmo systemu; "" = nezname."""
    territory, var = locale_territory(env)
    if territory and not (var == "LANG" and territory == "US"):
        return units_for_country(territory), "locale"
    first = next((p for p in (places or []) if isinstance(p, dict)), None)
    place_cc = str((first or {}).get("country_code") or "").upper()
    tz_cc = zone_country(system_timezone() if tz is None else tz, zonetab)
    for cc, why in ((place_cc, "place"), (tz_cc, "timezone")):
        if cc:
            return units_for_country(cc), why
    return ("imperial", "locale") if territory == "US" else ("metric", "default")


def default_units(env=None, tz=None, places=None):
    """Vychozi jednotky. S vyslovnym env (testy, cista funkce) bez tz se casove pasmo nepouzije."""
    if env is not None and tz is None:
        tz = ""
    return detect_units(env, tz, places)[0]


def resolve_units(setting, env=None, places=None, tz=None):
    return setting if setting in ("metric", "imperial") else default_units(env, tz, places)


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


# ---- scena pozadi okna -------------------------------------------------------------
# kod WMO -> (druh oblohy, intenzita 0..1: hustota mraku, deste, snehu)
SCENES = {
    0: ("clear", 0.0), 1: ("partly", 0.3), 2: ("partly", 0.6), 3: ("cloudy", 1.0),
    45: ("fog", 0.8), 48: ("fog", 1.0),
    51: ("drizzle", 0.35), 53: ("drizzle", 0.6), 55: ("drizzle", 0.9), 56: ("drizzle", 0.5),
    57: ("drizzle", 0.9),
    61: ("rain", 0.4), 63: ("rain", 0.65), 65: ("rain", 1.0), 66: ("rain", 0.5), 67: ("rain", 0.9),
    80: ("rain", 0.5), 81: ("rain", 0.75), 82: ("rain", 1.0),
    71: ("snow", 0.35), 73: ("snow", 0.6), 75: ("snow", 1.0), 77: ("snow", 0.3), 85: ("snow", 0.5),
    86: ("snow", 0.9),
    95: ("storm", 0.8), 96: ("storm", 1.0), 99: ("storm", 1.0),
}
SCENE_KINDS = ("clear", "partly", "cloudy", "fog", "drizzle", "rain", "snow", "storm")
SCENE_TIMES = ("day", "night", "dawn", "dusk")
TWILIGHT = 45                   # minut kolem vychodu/zapadu slunce = barvy usvitu/soumraku


def _minutes(text):
    """'2026-10-26T06:41' -> minuty od pocatku letopoctu (mistni cas mista); spatny text -> None."""
    try:
        date, _sep, clock = str(text).partition("T")
        y, m, d = (int(x) for x in date.split("-"))
        hh, mm = (int(x) for x in clock.split(":")[:2])
        import datetime
        return datetime.date(y, m, d).toordinal() * 1440 + hh * 60 + mm
    except (ValueError, TypeError):
        return None


def time_of_day(now, is_day=True, sunrise="", sunset=""):
    """'dawn'/'dusk' do TWILIGHT minut od vychodu/zapadu slunce, jinak 'day'/'night' podle slunce
    (kdyz jsou casy toho dne znamy), jinak podle priznaku is_day z Open-Meteo."""
    n, rise, sset = _minutes(now), _minutes(sunrise), _minutes(sunset)
    if n is not None and rise is not None and abs(n - rise) <= TWILIGHT:
        return "dawn"
    if n is not None and sset is not None and abs(n - sset) <= TWILIGHT:
        return "dusk"
    if None not in (n, rise, sset) and rise < sset and n // 1440 == rise // 1440:
        return "day" if rise <= n < sset else "night"
    return "day" if is_day else "night"


def scene(code, is_day=True, now="", sunrise="", sunset=""):
    """Scena pozadi: {"kind", "time", "intensity", "name"} (name napr. "rain-night")."""
    kind, intensity = SCENES.get(code, ("cloudy", 0.8))
    tod = time_of_day(now, is_day, sunrise, sunset)
    return {"kind": kind, "time": tod, "intensity": intensity, "name": f"{kind}-{tod}"}


def local_now(utc_offset, now=None):
    """Aktualni mistni cas mista ('YYYY-MM-DDTHH:MM') podle posunu UTC z predpovedi."""
    t = time.gmtime((time.time() if now is None else now) + int(utc_offset or 0))
    return time.strftime("%Y-%m-%dT%H:%M", t)


def scene_for(data, now=None):
    """Scena z rozparsovane predpovedi: pocasi ted a denni doba podle skutecneho mistniho casu
    (okno muze byt otevrene hodiny) a vychodu/zapadu slunce toho dne."""
    cur = data["current"]
    t = local_now(data.get("utc_offset", 0), now)
    day = next((d for d in data["daily"] if d["date"] == t[:10]), None)
    if day is None:                 # stara data z mezipameti: priznak is_day z Open-Meteo
        return scene(cur["code"], cur["is_day"])
    return scene(cur["code"], cur["is_day"], t, day.get("sunrise", ""), day.get("sunset", ""))


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
