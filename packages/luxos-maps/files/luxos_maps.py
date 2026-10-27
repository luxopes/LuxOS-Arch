"""LuxOS Mapy - data bez GTK: dlazdice OpenStreetMap, hledani (Nominatim), trasy (OSRM), MHD (Transitous),
okoli (Overpass), nahled trasy (PNG), nastaveni.

  TileStore            mezipamet dlazdic na disku + nejvys 2 soubezna stahovani, jen viditelne dlazdice
  search(q, lang)      hledani mist (Nominatim, nejvys 1 pozadavek/s pro vsechna okna, mezipamet 30 dni)
  reverse(lat, lon)    co je na tomto miste (Nominatim, stejny limit)
  route(a, b, mode)    trasa autem/na kole/pesky (routing.openstreetmap.de, FOSSGIS, nejvys 1 pozadavek/s)
  parse_geo_uri(uri)   geo:50.08,14.42?z=15 / geo:0,0?q=Praha
  ip_location()        priblizna poloha podle IP (ipinfo.io) - jen po souhlasu uzivatele
  phone_location()     GPS z telefonu (LuxOS Companion, cz.luxos.Companion1) - jen po souhlasu, cerstva <= 15 s
  transit_plan(a, b)   spojeni MHD (Transitous/MOTIS, mezipamet 3 min, nejvys 1 pozadavek/s)
  timetable(lat, lon)  odjezdy/prijezdy ze zastavky v realnem case (Transitous, mezipamet 45 s)
  nearby(lat, lon, c)  mista v okoli podle kategorie (Overpass, mezipamet 10 min, max. 50 vysledku)
  render_preview(p)    maly obrazek trasy PNG z dlazdic v mezipameti (jen dlazdice toho obrazku)

Pravidla OSM (operations.osmfoundation.org/policies): vlastni User-Agent, mezipamet podle hlavicek
(Cache-Control/Expires/ETag, podmineny pozadavek po vyprseni, bez hlavicek 7 dni), zadne
prednacitani oblasti ani stahovani pro offline; hledani jen po Enter (zadne naseptavani).
Adresy jdou prepsat v nastaveni (tile_url, search_url, reverse_url, route_url) i bez aktualizace.
Mezipamet: $XDG_CACHE_HOME/luxos/maps, nastaveni: $XDG_CONFIG_HOME/luxos/maps.json.
Testy: LUXOS_MAPS_TILES, LUXOS_MAPS_SEARCH, LUXOS_MAPS_REVERSE, LUXOS_MAPS_ROUTE, LUXOS_MAPS_IP,
LUXOS_MAPS_TRANSIT_PLAN, LUXOS_MAPS_STOPTIMES, LUXOS_MAPS_OVERPASS, LUXOS_MAPS_RATE (interval limitu v s).
"""
import collections
import datetime
import email.utils
import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0"
USER_AGENT = f"LuxOS-Maps/{VERSION} (+https://github.com/luxopes/LuxOS-Arch)"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
SEARCH_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
ROUTE_URL = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{coords}"
IP_URL = "https://ipinfo.io/json"
TRANSIT_PLAN_URL = "https://api.transitous.org/api/v6/plan"
STOPTIMES_URL = "https://api.transitous.org/api/v6/stoptimes"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TRANSITOUS_SOURCES_URL = "https://transitous.org/sources/"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
FIXTHEMAP_URL = "https://www.openstreetmap.org/fixthemap"
MAX_ZOOM = 19
TILE = 256
DOWNLOADS = 2                 # soubezna stahovani dlazdic (OSM: rozumny pocet)
MIN_TTL = 7 * 24 * 3600       # dlazdice bez hlavicek mezipameti
TIMEOUT = 15
CACHE_LIMIT = 300 * 1024 * 1024
SEARCH_TTL = 30 * 24 * 3600
MODES = {"car": "car", "bike": "bike", "walk": "foot"}
TRANSIT = "transit"           # MHD (Transitous), v okne vedle car/bike/walk
PLAN_TTL = 180                # s, spojeni MHD (zpozdeni se meni, kratka mezipamet)
STOPTIMES_TTL = 45            # s, odjezdy v realnem case
NEARBY_TTL = 600              # s, mista v okoli (Overpass)
API_CACHE_FILES = 96          # odpovedi Transitous/Overpass na disku
API_CACHE_BYTES = 32 * 1024 * 1024
BACKOFF = 30                  # s, pauza po "pretizeno" (429/502/503/504) od Overpass/Transitous


class MapsError(Exception):
    pass


class BusyError(MapsError):
    """Sluzba je pretizena nebo nas omezila (429/5xx) - chvili ji nezatezovat."""


# ---- cesty a nastaveni -------------------------------------------------------------
def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "luxos", "maps")


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "luxos", "maps.json")


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def valid_place(p):
    return (isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("lat"), (int, float))
            and isinstance(p.get("lon"), (int, float)) and -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180)


def load_config():
    cfg = _read_json(config_path())
    if not isinstance(cfg, dict):
        cfg = {}
    fav = cfg.get("favorites")
    cfg["favorites"] = [p for p in fav if valid_place(p)] if isinstance(fav, list) else []
    view = cfg.get("view")
    if not (isinstance(view, dict) and valid_place(dict(view, name="")) and isinstance(view.get("zoom"), (int, float))):
        cfg["view"] = None
    if cfg.get("appearance") not in ("auto", "light", "dark"):
        cfg["appearance"] = "auto"
    if cfg.get("mode") not in MODES and cfg.get("mode") != TRANSIT:
        cfg["mode"] = "car"
    cfg["location_consent"] = cfg.get("location_consent") is True
    for key in ("tile_url", "search_url", "reverse_url", "route_url", "transit_plan_url", "stoptimes_url",
                "overpass_url"):
        if not isinstance(cfg.get(key), str) or not cfg[key].startswith(("https://", "http://")):
            cfg.pop(key, None)
    return cfg


def save_config(cfg):
    try:
        _write_json(config_path(), cfg)
    except OSError:
        pass


def service_url(cfg, key, env, default):
    """Adresa sluzby: promenna prostredi (testy) > nastaveni > vychozi."""
    return os.environ.get(env) or (cfg or {}).get(key) or default


def same_place(a, b, tol=0.0002):
    return abs(a["lat"] - b["lat"]) < tol and abs(a["lon"] - b["lon"]) < tol


# ---- souradnice --------------------------------------------------------------------
MAX_LAT = 85.0511287798


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def to_world(lat, lon):
    """Zemepisne souradnice -> svet Web Mercator 0..1 (x vychod, y jih)."""
    lat = clamp(lat, -MAX_LAT, MAX_LAT)
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def from_world(x, y):
    lon = x * 360.0 - 180.0
    lon = (lon + 180.0) % 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))
    return lat, lon


def meters_per_pixel(lat, zoom):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def distance_m(a_lat, a_lon, b_lat, b_lon):
    r = 6371008.8
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def zoom_for_bbox(south, north, west, east, width, height, max_zoom=17):
    """Nejvetsi zoom, pri kterem se obdelnik vejde do okna (s okrajem)."""
    x0, y0 = to_world(north, west)
    x1, y1 = to_world(south, east)
    dx, dy = max(abs(x1 - x0), 1e-9), max(abs(y1 - y0), 1e-9)
    z = min(math.log2(max(width - 80, 50) / (dx * TILE)), math.log2(max(height - 80, 50) / (dy * TILE)))
    return clamp(z, 1, max_zoom)


def format_coords(lat, lon):
    return f"{lat:.5f}, {lon:.5f}"


def _num6(v):
    return f"{v:.6f}".rstrip("0").rstrip(".")


def geo_uri(lat, lon, zoom=None, label=None):
    """geo: odkaz (RFC 5870); popis jako u Androidu: ?q=lat,lon(popis)."""
    pos = f"{_num6(lat)},{_num6(lon)}"
    uri = "geo:" + pos
    q = []
    if zoom is not None:
        q.append(f"z={int(round(zoom))}")
    if label:
        q.append("q=" + urllib.parse.quote(f"{pos}({label})", safe=",()"))
    return uri + ("?" + "&".join(q) if q else "")


def osm_url(lat, lon, zoom):
    return f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map={int(round(zoom))}/{lat:.5f}/{lon:.5f}"


_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*(?:\((.*)\))?\s*$")


def parse_coords(text):
    """'50.087, 14.421' -> (lat, lon, popis|None) nebo None."""
    m = _COORD_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon, (m.group(3) or None)


def parse_geo_uri(uri):
    """RFC 5870 + bezne rozsireni (Android): vraci {"lat", "lon", "zoom", "label", "query"} nebo None."""
    if not isinstance(uri, str) or not uri.lower().startswith("geo:"):
        return None
    body = uri[4:]
    path, _sep, query = body.partition("?")
    parts = path.split(";")
    coords = parts[0].split(",")
    if len(coords) < 2:
        return None
    try:
        lat, lon = float(coords[0]), float(coords[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    for p in parts[1:]:
        k, _s, v = p.partition("=")
        if k.lower() == "crs" and v.lower() != "wgs84":
            return None
    out = {"lat": lat, "lon": lon, "zoom": None, "label": None, "query": None}
    params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
    try:
        if params.get("z"):
            out["zoom"] = clamp(float(params["z"]), 1, MAX_ZOOM)
    except ValueError:
        pass
    q = (params.get("q") or "").strip()
    if q:
        c = parse_coords(q)
        if c:
            out["lat"], out["lon"], out["label"] = c
        else:
            out["query"] = q
    if lat == 0 and lon == 0 and out["query"]:
        out["lat"] = out["lon"] = None       # jen hledani
    return out


# ---- jednotky a texty --------------------------------------------------------------
IMPERIAL = {"US", "LR", "MM"}


def locale_country(env=None):
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MEASUREMENT", "LANG"):
        v = (env.get(var) or "").split(".")[0].split("@")[0]
        if v:
            return v.split("_")[1].upper() if "_" in v else ""
    return ""


def lang_code(env=None):
    env = os.environ if env is None else env
    v = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or "en"
    return v.split("_")[0].split(".")[0].split("@")[0] or "en"


def decimal(value, digits=1, lang=None):
    s = f"{value:.{digits}f}"
    return s if (lang or lang_code()) == "en" else s.replace(".", ",")


def format_distance(meters, imperial=False, lang=None):
    if imperial:
        miles = meters / 1609.344
        if miles < 0.1:
            return f"{int(round(meters * 3.28084 / 10.0) * 10)} ft"
        if miles >= 10 or abs(miles - round(miles)) < 0.05:
            return f"{round(miles)} mi"
        return f"{decimal(miles, 1, lang)} mi"
    if meters < 1000:
        return f"{int(round(meters / 10.0) * 10)} m" if meters >= 100 else f"{int(round(meters))} m"
    km = meters / 1000
    if km >= 10 or abs(km - round(km)) < 0.05:
        return f"{round(km)} km"
    return f"{decimal(km, 1, lang)} km"


def format_duration(seconds, tr=lambda s: s):
    minutes = max(1, int(round(seconds / 60.0)))
    if minutes < 60:
        return tr("%d min") % minutes
    h, m = divmod(minutes, 60)
    return tr("%d h %d min") % (h, m) if m else tr("%d h") % h


# ---- HTTP (JSON) a limit 1 pozadavek/s -------------------------------------------------
def rate_interval():
    try:
        return float(os.environ.get("LUXOS_MAPS_RATE", "1.05"))
    except ValueError:
        return 1.05


def rate_wait(name):
    """Pocka, aby od posledniho pozadavku na sluzbu (ze vsech oken Map) ubehl interval.
    Cas posledniho pozadavku je v souboru se zamkem (fcntl), takze plati i mezi procesy."""
    path = os.path.join(cache_dir(), f"rate-{name}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                last = float(f.read().strip() or 0)
            except ValueError:
                last = 0.0
            wait = last + rate_interval() - time.time()
            if 0 < wait <= rate_interval():
                time.sleep(wait)
            f.seek(0)
            f.truncate()
            f.write(f"{time.time():.3f}")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def http_json(url, params=None, rate=None, timeout=TIMEOUT, lang=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if lang:
        headers["Accept-Language"] = lang
    if rate:
        rate_wait(rate)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(64 * 1024)
        except OSError:
            pass
        e.close()
        try:
            err = json.loads(body.decode("utf-8"))
            msg = err.get("message") or ""
            code = err.get("code") or ""
        except (ValueError, AttributeError):
            msg = code = ""
        if code in ("NoRoute", "NoSegment"):       # OSRM: mezi misty neni cesta
            raise MapsError("NoRoute") from e
        if e.code in (429, 502, 503, 504):          # sluzba je pretizena (Overpass: "at capacity")
            raise BusyError(f"HTTP {e.code}: service busy, try again later") from e
        raise MapsError(f"HTTP {e.code}" + (f": {msg}" if msg else "")) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MapsError(str(getattr(e, "reason", e))) from e
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise MapsError("invalid response") from e


# ---- hledani (Nominatim) -------------------------------------------------------------
_search_lock = threading.Lock()


def _search_cache_path():
    return os.path.join(cache_dir(), "search.json")


def _cached(key, now):
    with _search_lock:
        cache = _read_json(_search_cache_path())
    if isinstance(cache, dict):
        hit = cache.get(key)
        if isinstance(hit, dict) and now - hit.get("t", 0) < SEARCH_TTL and isinstance(hit.get("r"), list):
            return hit["r"]
    return None


def _store(key, results, now):
    with _search_lock:
        cache = _read_json(_search_cache_path())
        if not isinstance(cache, dict):
            cache = {}
        cache[key] = {"t": now, "r": results}
        if len(cache) > 300:          # nejstarsi pryc
            for k, _v in sorted(cache.items(), key=lambda kv: kv[1].get("t", 0))[:len(cache) - 300]:
                cache.pop(k, None)
        try:
            _write_json(_search_cache_path(), cache)
        except OSError:
            pass


def parse_place(r):
    try:
        lat, lon = float(r["lat"]), float(r["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    display = str(r.get("display_name") or "")
    name = str(r.get("name") or "") or display.split(",")[0].strip()
    addr = r.get("address") if isinstance(r.get("address"), dict) else {}
    if not name:
        name = format_coords(lat, lon)
    place = {"name": name, "lat": lat, "lon": lon, "address": address_line(addr, display, name),
             "type": str(r.get("type") or ""), "category": str(r.get("category") or r.get("class") or "")}
    bb = r.get("boundingbox")
    try:
        if bb and len(bb) == 4:
            place["bbox"] = [float(v) for v in bb]       # jih, sever, zapad, vychod
    except (TypeError, ValueError):
        pass
    if r.get("osm_type") and r.get("osm_id"):
        place["osm"] = f"{r['osm_type']}/{r['osm_id']}"
    return place


def address_line(addr, display, name):
    """Kratka adresa: ulice cislo, mesto, zeme (z address nebo zbytku display_name)."""
    if addr:
        street = addr.get("road") or addr.get("pedestrian") or addr.get("square") or ""
        if street and addr.get("house_number"):
            street = f"{street} {addr['house_number']}"
        town = (addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
                or addr.get("county") or "")
        parts = [p for p in (street, addr.get("suburb") if not town else "", town, addr.get("country"))
                 if p and p != name]
        out = []
        for p in parts:
            if p not in out:
                out.append(p)
        if out:
            return ", ".join(out)
    rest = [p.strip() for p in display.split(",") if p.strip()]
    if rest and rest[0] == name:
        rest = rest[1:]
    return ", ".join(rest[:3] + rest[-1:]) if len(rest) > 4 else ", ".join(rest)


def search(query, lang="en", near=None, cfg=None, limit=8, now=None):
    """Hledani mista (jen na vyzadani - Enter). near=(jih, sever, zapad, vychod) zvyhodni okoli."""
    query = " ".join((query or "").split())
    if len(query) < 2:
        return []
    now = time.time() if now is None else now
    params = {"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 1, "accept-language": lang}
    if near:
        # Na 0,1 stupne (mezipamet pro stejne okoli), ale ven: zaokrouhleni na nejblizsi hodnotu
        # dalo pri velkem priblizeni nulovou plochu (jih == sever) a Nominatim vratil HTTP 400
        s, n, w, e = near
        s, w = (math.floor(v * 10 + 1e-9) / 10 for v in (s, w))
        n, e = (math.ceil(v * 10 - 1e-9) / 10 for v in (n, e))
        n, e = max(n, s + 0.1), max(e, w + 0.1)
        params["viewbox"] = f"{w:.1f},{n:.1f},{e:.1f},{s:.1f}"
    key = "s|" + urllib.parse.urlencode(sorted(params.items()))
    hit = _cached(key, now)
    if hit is not None:
        return hit
    data = http_json(service_url(cfg, "search_url", "LUXOS_MAPS_SEARCH", SEARCH_URL), params,
                     rate="nominatim", lang=lang)
    if not isinstance(data, list):
        raise MapsError("invalid response")
    out = []
    for p in (parse_place(r) for r in data):
        # Nominatim vraci napr. namesti jako plochu i jako ulice: stejny nazev do 300 m jen jednou
        if p and not any(q["name"] == p["name"] and distance_m(q["lat"], q["lon"], p["lat"], p["lon"]) < 300
                         for q in out):
            out.append(p)
    _store(key, out, now)
    return out


def reverse(lat, lon, lang="en", zoom=18, cfg=None, now=None):
    now = time.time() if now is None else now
    params = {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2", "zoom": int(zoom),
              "addressdetails": 1, "accept-language": lang}
    key = "r|" + urllib.parse.urlencode(sorted(params.items()))
    hit = _cached(key, now)
    if hit is not None:
        return hit[0] if hit else None
    data = http_json(service_url(cfg, "reverse_url", "LUXOS_MAPS_REVERSE", REVERSE_URL), params,
                     rate="nominatim", lang=lang)
    place = parse_place(data) if isinstance(data, dict) and "lat" in data else None
    _store(key, [place] if place else [], now)
    return place


# ---- trasy (OSRM) ------------------------------------------------------------------
def decode_polyline(text, precision=5):
    """Google polyline -> [(lat, lon), ...]."""
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10 ** precision
    n = len(text)
    while index < n:
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                if index >= n:
                    raise ValueError("truncated polyline")
                b = ord(text[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lon += vals[1]
        coords.append((lat / factor, lon / factor))
    return coords


# Popis manevru: (typ, smer) -> anglicky text k prekladu; ulice je na druhem radku
TURNS = {
    "left": "Turn left", "right": "Turn right", "slight left": "Turn slightly left",
    "slight right": "Turn slightly right", "sharp left": "Turn sharp left", "sharp right": "Turn sharp right",
    "straight": "Go straight", "uturn": "Make a U-turn",
}


def maneuver_text(step):
    m = step.get("maneuver") or {}
    typ, mod = m.get("type", ""), m.get("modifier", "")
    if typ == "depart":
        return "Depart"
    if typ == "arrive":
        if mod in ("left", "slight left", "sharp left"):
            return "Destination is on the left"
        if mod in ("right", "slight right", "sharp right"):
            return "Destination is on the right"
        return "Arrive at your destination"
    if typ in ("roundabout", "rotary", "roundabout turn"):
        return ("Enter the roundabout and take exit %s", str(m.get("exit") or 1)) if m.get("exit") \
            else "Enter the roundabout"
    if typ == "fork":
        return "Keep left" if "left" in mod else "Keep right" if "right" in mod else "Continue straight"
    if typ == "merge":
        return "Merge"
    if typ == "on ramp":
        return "Take the ramp"
    if typ == "off ramp":
        return "Take the exit"
    if typ in ("new name", "notification") or (typ == "continue" and mod in ("straight", "")):
        return "Continue straight"
    return TURNS.get(mod, "Continue straight")


def parse_route(data, mode):
    if not isinstance(data, dict) or data.get("code") != "Ok" or not data.get("routes"):
        code = (data or {}).get("code") if isinstance(data, dict) else None
        raise MapsError("NoRoute" if code in ("NoRoute", "NoSegment") else (code or "invalid response"))
    r = data["routes"][0]
    geometry = r.get("geometry")
    pts = decode_polyline(geometry) if isinstance(geometry, str) else \
        [(c[1], c[0]) for c in (geometry or {}).get("coordinates", [])]
    steps = []
    for leg in r.get("legs") or []:
        for s in leg.get("steps") or []:
            m = s.get("maneuver") or {}
            typ = m.get("type", "")
            if typ == "exit roundabout" or typ == "exit rotary":
                if steps:      # vyjezd z kruhoveho objezdu patri k vjezdu
                    steps[-1]["distance"] += float(s.get("distance") or 0)
                    steps[-1]["duration"] += float(s.get("duration") or 0)
                    if s.get("name") and not steps[-1]["name"]:
                        steps[-1]["name"] = s["name"]
                continue
            loc = m.get("location") or [0, 0]
            name = s.get("name") or ""
            if s.get("ref") and s["ref"] not in name:
                name = f"{name} ({s['ref']})" if name else s["ref"]
            if typ in ("roundabout", "rotary") and s.get("rotary_name"):
                name = name or s["rotary_name"]
            text = maneuver_text(s)
            text, arg = text if isinstance(text, tuple) else (text, None)
            steps.append({"text": text, "arg": arg, "name": name, "distance": float(s.get("distance") or 0),
                          "duration": float(s.get("duration") or 0), "lat": float(loc[1]), "lon": float(loc[0]),
                          "type": typ, "modifier": m.get("modifier", "")})
    if len(pts) < 2:
        raise MapsError("invalid response")
    return {"mode": mode, "distance": float(r.get("distance") or 0), "duration": float(r.get("duration") or 0),
            "points": pts, "steps": steps}


_route_cache = collections.OrderedDict()


def route(a, b, mode="car", cfg=None):
    """Trasa z a do b ({"lat","lon"}); mode car|bike|walk. Vysledek se pamatuje (stejny dotaz znovu ne)."""
    if mode not in MODES:
        raise MapsError("unknown mode")
    coords = f"{a['lon']:.6f},{a['lat']:.6f};{b['lon']:.6f},{b['lat']:.6f}"
    key = (mode, coords)
    if key in _route_cache:
        _route_cache.move_to_end(key)
        return _route_cache[key]
    url = service_url(cfg, "route_url", "LUXOS_MAPS_ROUTE", ROUTE_URL)
    url = url.replace("{profile}", MODES[mode]).replace("{coords}", coords)
    data = http_json(url, {"overview": "full", "steps": "true", "geometries": "polyline", "alternatives": "false"},
                     rate="routing")
    res = parse_route(data, mode)
    _route_cache[key] = res
    while len(_route_cache) > 20:
        _route_cache.popitem(last=False)
    return res


def encode_polyline(points, precision=5):
    """[(lat, lon), ...] -> Google polyline (opak decode_polyline)."""
    factor = 10 ** precision
    out, plat, plon = [], 0, 0
    for lat, lon in points:
        a, b = int(round(lat * factor)), int(round(lon * factor))
        for v in (a - plat, b - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = a, b
    return "".join(out)


def thin_points(points, maximum=400):
    """Nejvys maximum bodu (rovnomerne, prvni a posledni zustava) - pro nahled staci."""
    n = len(points)
    if n <= maximum:
        return list(points)
    last = n - 1
    return [points[i * last // (maximum - 1)] for i in range(maximum)]


# ---- mezipamet odpovedi API (Transitous, Overpass) ----------------------------------------
_api_lock = threading.Lock()


def _api_dir():
    return os.path.join(cache_dir(), "api")


def _backoff_path(service):
    return os.path.join(cache_dir(), f"backoff-{service}")


def _backoff_left(service):
    try:
        return os.stat(_backoff_path(service)).st_mtime - time.time()
    except OSError:
        return 0


def _set_backoff(service, seconds=BACKOFF):
    p = _backoff_path(service)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w"):
            pass
        os.utime(p, (time.time(), time.time() + seconds))
    except OSError:
        pass


def _prune_api_cache():
    files, total = [], 0
    try:
        names = os.listdir(_api_dir())
    except OSError:
        return
    for n in names:
        p = os.path.join(_api_dir(), n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        files.append((st.st_mtime, st.st_size, p))
        total += st.st_size
    files.sort()
    while files and (len(files) > API_CACHE_FILES or total > API_CACHE_BYTES):
        _mt, size, p = files.pop(0)
        try:
            os.unlink(p)
        except OSError:
            pass
        total -= size


def api_get(service, url, params, ttl, timeout=TIMEOUT, max_age=None):
    """GET JSON s mezipameti na disku (spolecna pro okno i --json), limitem 1 pozadavek/s na sluzbu
    pro vsechny procesy a pauzou BACKOFF s po odpovedi "pretizeno". max_age: kratsi platnost
    (tlacitko Obnovit), nikdy delsi nez ttl."""
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    path = os.path.join(_api_dir(), hashlib.sha256(full.encode()).hexdigest()[:40] + ".json")
    now = time.time()
    limit = ttl if max_age is None else min(ttl, max_age)
    hit = _read_json(path)
    if isinstance(hit, dict) and 0 <= now - float(hit.get("t") or 0) < limit and "body" in hit:
        return hit["body"]
    wait = _backoff_left(service)
    if wait > 0:
        raise BusyError(f"service busy, try again in {int(math.ceil(wait))} s")
    try:
        data = http_json(full, rate=service, timeout=timeout)
    except BusyError:
        _set_backoff(service)
        raise
    with _api_lock:
        try:
            _write_json(path, {"t": time.time(), "url": full, "body": data})
        except OSError:
            pass
        _prune_api_cache()
    return data


# ---- cas (ISO 8601) a casova pasma -----------------------------------------------------------
UTC = datetime.timezone.utc


def local_zone():
    return datetime.datetime.now().astimezone().tzinfo


def zone(name):
    """Casove pasmo zastavky (IANA, napr. Europe/Prague); jinak pasmo pocitace."""
    if name:
        try:
            import zoneinfo
            return zoneinfo.ZoneInfo(name)
        except (ImportError, ValueError, KeyError, OSError):
            pass
    return local_zone()


def parse_iso(text):
    """'2026-08-24T08:04:00Z' -> datetime s pasmem, nebo None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=local_zone())


_HHMM_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_user_time(text, now=None):
    """Cas od uzivatele/LuxAI: ISO 8601 s pasmem (bez pasma = mistni cas) nebo 'HH:MM' (dnes, mistni).
    Vraci datetime s pasmem; neplatny cas -> MapsError."""
    if text is None or not str(text).strip() or str(text).strip().lower() == "now":
        return None
    m = _HHMM_RE.match(str(text))
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise MapsError("invalid time, use HH:MM or ISO 8601, e.g. 2026-08-24T10:00:00+02:00")
        base = now or datetime.datetime.now().astimezone()
        return base.replace(hour=h, minute=mi, second=0, microsecond=0)
    dt = parse_iso(str(text))
    if dt is None:
        raise MapsError("invalid time, use ISO 8601 with a timezone, e.g. 2026-08-24T10:00:00+02:00")
    return dt


def api_time(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(dt, tz):
    return dt.astimezone(tz).isoformat(timespec="seconds") if dt else None


def hhmm(dt, tz):
    return dt.astimezone(tz).strftime("%H:%M") if dt else None


def _minutes(a, b):
    return int(round((a - b).total_seconds() / 60.0)) if a and b else None


# ---- MHD (Transitous / MOTIS) -----------------------------------------------------------------
# druh dopravy MOTIS -> (anglicky nazev k prekladu, barva bez routeColor; barvy jako mobilni LuxAI)
TRANSIT_MODES = {
    "WALK": ("Walk", "#64748B"), "BIKE": ("Bike", "#16A34A"), "BICYCLE": ("Bike", "#16A34A"),
    "RENTAL": ("Shared bike", "#16A34A"), "CAR": ("Car", "#DC2626"),
    "TRAM": ("Tram", "#E11D48"), "SUBWAY": ("Metro", "#7C3AED"), "METRO": ("Metro", "#7C3AED"),
    "BUS": ("Bus", "#EA580C"), "COACH": ("Coach", "#EA580C"), "TROLLEYBUS": ("Trolleybus", "#EA580C"),
    "RAIL": ("Train", "#2563EB"), "HIGHSPEED_RAIL": ("Train", "#2563EB"), "LONG_DISTANCE": ("Train", "#2563EB"),
    "NIGHT_RAIL": ("Train", "#2563EB"), "REGIONAL_FAST_RAIL": ("Train", "#2563EB"),
    "REGIONAL_RAIL": ("Train", "#2563EB"), "SUBURBAN": ("Train", "#2563EB"),
    "FERRY": ("Ferry", "#0891B2"), "AIRPLANE": ("Plane", "#0891B2"), "FUNICULAR": ("Funicular", "#0891B2"),
    "AERIAL_LIFT": ("Cable car", "#0891B2"), "CABLE_CAR": ("Cable car", "#0891B2"),
    "ODM": ("On-demand", "#0891B2"), "FLEX": ("On-demand", "#0891B2"),
}
NOT_TRANSIT = {"WALK", "BIKE", "BICYCLE", "RENTAL", "CAR", "CAR_PARKING", "CAR_DROPOFF"}
TRANSIT_ATTRIBUTION = ("Timetable data by participating open-data providers via Transitous — "
                       + TRANSITOUS_SOURCES_URL)
_HEX6 = re.compile(r"^[0-9A-Fa-f]{6}$")


def mode_name(mode):
    return TRANSIT_MODES.get(mode, ("Public transport", ""))[0]


def leg_color(mode, route_color=""):
    c = (route_color or "").strip().lstrip("#")
    if _HEX6.match(c):
        return "#" + c.upper()
    return TRANSIT_MODES.get(mode, ("", "#0891B2"))[1] or "#0891B2"


def text_color(bg, route_text_color=""):
    """Barva textu na odznaku linky: dodana, jinak bila/cerna podle jasu pozadi."""
    c = (route_text_color or "").strip().lstrip("#")
    if _HEX6.match(c) and c.upper() != bg.lstrip("#").upper():
        return "#" + c.upper()
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 165 else "#FFFFFF"


def hex_rgb(color):
    c = (color or "").lstrip("#")
    if not _HEX6.match(c):
        return (0.15, 0.39, 0.92)
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _stop(p, which, tz_name=None):
    """Misto z odpovedi MOTIS -> zastavka pro --json (cas prijezdu/odjezdu v mistnim case zastavky)."""
    p = p if isinstance(p, dict) else {}
    tz = zone(p.get("tz") or tz_name)
    out = {"name": str(p.get("name") or ""), "lat": round(float(p.get("lat") or 0), 6),
           "lon": round(float(p.get("lon") or 0), 6)}
    if out["name"] in ("START", "END"):         # MOTIS pojmenuje vlastni body START/END
        out["name"] = ""
    if p.get("stopId"):
        out["stop_id"] = str(p["stopId"])
    track, sched = str(p.get("track") or ""), str(p.get("scheduledTrack") or "")
    if track or sched:
        out["platform"] = track or sched
        if sched and track and sched != track:
            out["scheduled_platform"] = sched
            out["platform_changed"] = True
    if p.get("cancelled"):
        out["cancelled"] = True
    for key in (which,):
        actual = parse_iso(p.get(key))
        sched_t = parse_iso(p.get("scheduled" + key[0].upper() + key[1:])) or actual
        if actual or sched_t:
            out[key] = iso_local(actual or sched_t, tz)
            out[key + "_time"] = hhmm(actual or sched_t, tz)
            delay = _minutes(actual, sched_t)
            if delay:
                out[key + "_delay_min"] = delay
    return out


def parse_leg(leg, tz_name=None):
    """Usek spojeni; tz_name = pasmo spojeni, kdyz misto vlastni nema (jako mobilni LuxAI)."""
    mode = str(leg.get("mode") or "TRANSIT")
    frm, to = leg.get("from") or {}, leg.get("to") or {}
    tz_a, tz_b = zone(frm.get("tz") or tz_name), zone(to.get("tz") or frm.get("tz") or tz_name)
    start, end = parse_iso(leg.get("startTime")), parse_iso(leg.get("endTime"))
    s_start = parse_iso(leg.get("scheduledStartTime")) or start
    s_end = parse_iso(leg.get("scheduledEndTime")) or end
    transit = mode not in NOT_TRANSIT
    line = str(leg.get("displayName") or leg.get("routeShortName") or leg.get("tripShortName") or "")
    color = leg_color(mode, leg.get("routeColor") if transit else "")
    out = {
        "mode": mode, "mode_name": mode_name(mode), "transit": transit,
        "line": line if transit else "", "headsign": str(leg.get("headsign") or "") if transit else "",
        "operator": str(leg.get("agencyName") or ""), "color": color,
        "text_color": text_color(color, leg.get("routeTextColor") if transit else ""),
        "from": _stop(frm, "departure", tz_name), "to": _stop(to, "arrival", tz_name),
        "departure": iso_local(start, tz_a), "arrival": iso_local(end, tz_b),
        "departure_time": hhmm(start, tz_a), "arrival_time": hhmm(end, tz_b),
        "scheduled_departure_time": hhmm(s_start, tz_a), "scheduled_arrival_time": hhmm(s_end, tz_b),
        "delay_min": _minutes(start, s_start) or 0, "arrival_delay_min": _minutes(end, s_end) or 0,
        "realtime": bool(leg.get("realTime")),
        "cancelled": bool(leg.get("cancelled") or frm.get("cancelled") or to.get("cancelled")),
        "duration_s": int(leg.get("duration") or ((end - start).total_seconds() if start and end else 0)),
    }
    if leg.get("distance") is not None:
        try:
            out["distance_m"] = int(round(float(leg["distance"])))
        except (TypeError, ValueError):
            pass
    stops = leg.get("intermediateStops")
    if transit and isinstance(stops, list):
        out["stops"] = len(stops) + 1
        out["intermediate_stops"] = [str(s.get("name") or "") for s in stops if isinstance(s, dict)]
    if transit and leg.get("routeLongName"):
        out["route_name"] = str(leg["routeLongName"])
    geom = leg.get("legGeometry")
    if isinstance(geom, dict) and isinstance(geom.get("points"), str) and geom["points"]:
        try:
            prec = int(geom.get("precision") or 6)
        except (TypeError, ValueError):
            prec = 6
        out["geometry"] = {"polyline": geom["points"], "precision": int(clamp(prec, 5, 7))}
    return out


def leg_text(leg):
    """Anglicky popis useku (pro LuxAI; prelozi si ho)."""
    if not leg["transit"]:
        dist = f" {format_distance(leg['distance_m'], lang='en')}" if leg.get("distance_m") else ""
        dest = leg["to"]["name"] or "destination"
        return f"{leg['mode_name']}{dist} to {dest} ({format_duration(leg['duration_s'])})"
    t = f"{leg['mode_name']} {leg['line']}".strip()
    if leg["headsign"]:
        t += f" toward {leg['headsign']}"
    t += f" · {leg['departure_time']}–{leg['arrival_time']} · {leg['from']['name']} → {leg['to']['name']}"
    if leg["from"].get("platform"):
        t += f" · platform {leg['from']['platform']}"
        if leg["from"].get("scheduled_platform"):
            t += f" (scheduled {leg['from']['scheduled_platform']})"
    if leg["delay_min"]:
        t += f" · {'+' if leg['delay_min'] > 0 else ''}{leg['delay_min']} min"
    if leg["realtime"]:
        t += " · realtime"
    if leg["cancelled"]:
        t += " · CANCELLED"
    return t


def parse_itinerary(it):
    first = (it.get("legs") or [{}])[0] or {}
    lastl = (it.get("legs") or [{}])[-1] or {}
    tz_name = (first.get("from") or {}).get("tz")
    legs = [parse_leg(lg, tz_name) for lg in (it.get("legs") or []) if isinstance(lg, dict)]
    tz_a = zone(tz_name)
    tz_b = zone((lastl.get("to") or {}).get("tz") or tz_name)
    start, end = parse_iso(it.get("startTime")), parse_iso(it.get("endTime"))
    duration = int(it.get("duration") or ((end - start).total_seconds() if start and end else 0))
    transfers = int(it.get("transfers") or max(0, sum(1 for lg in legs if lg["transit"]) - 1))
    out = {
        "departure": iso_local(start, tz_a), "arrival": iso_local(end, tz_b),
        "departure_time": hhmm(start, tz_a), "arrival_time": hhmm(end, tz_b),
        "date": start.astimezone(tz_a).strftime("%Y-%m-%d") if start else None,
        "duration_s": duration, "duration": format_duration(duration), "transfers": transfers,
        "walk_m": sum(lg.get("distance_m", 0) for lg in legs if lg["mode"] == "WALK"),
        "realtime": any(lg["realtime"] for lg in legs), "cancelled": any(lg["cancelled"] for lg in legs),
        "legs": legs,
    }
    out["summary"] = (f"{out['departure_time']} → {out['arrival_time']} · {out['duration']} · "
                      f"{transfers} transfer{'s' if transfers != 1 else ''}"
                      + (" · CANCELLED CONNECTION" if out["cancelled"] else "") + ": "
                      + "; ".join(leg_text(lg) for lg in legs))
    return out


def transit_plan(a, b, when=None, arrive_by=False, max_transfers=3, limit=3, cfg=None):
    """Spojeni MHD z a do b (Transitous/MOTIS). when = datetime (None = ted). Vraci
    {"itineraries": [...], "timezone"}; zadne spojeni -> MapsError("NoRoute")."""
    for p in (a, b):
        if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
            raise MapsError("invalid coordinates")
    max_transfers = int(clamp(int(max_transfers), 0, 8))
    limit = int(clamp(int(limit), 1, 5))
    params = {"fromPlace": f"{a['lat']:.6f},{a['lon']:.6f}", "toPlace": f"{b['lat']:.6f},{b['lon']:.6f}"}
    if when is not None:
        params["time"] = api_time(when)
    params.update({"arriveBy": "true" if arrive_by else "false", "transitModes": "TRANSIT", "directModes": "",
                   "detailedLegs": "true", "detailedTransfers": "true", "useRoutedTransfers": "true",
                   "maxTransfers": max_transfers, "numItineraries": limit, "maxItineraries": limit})
    data = api_get("transitous", service_url(cfg, "transit_plan_url", "LUXOS_MAPS_TRANSIT_PLAN",
                                             TRANSIT_PLAN_URL), params, PLAN_TTL, timeout=60)
    if not isinstance(data, dict) or not isinstance(data.get("itineraries"), list):
        raise MapsError("invalid response")
    its = [parse_itinerary(it) for it in data["itineraries"] if isinstance(it, dict)]
    its = [it for it in its if it["legs"]][:limit]
    if not its:
        raise MapsError("NoRoute")
    first_tz = ((data["itineraries"][0].get("legs") or [{}])[0].get("from") or {}).get("tz")
    return {"itineraries": its, "timezone": first_tz or str(local_zone())}


def parse_stoptime(st, arrivals=False):
    place = st.get("place") if isinstance(st.get("place"), dict) else {}
    tz = zone(place.get("tz"))
    field = "arrival" if arrivals else "departure"
    sched_field = "scheduledArrival" if arrivals else "scheduledDeparture"
    actual = parse_iso(place.get(field)) or parse_iso(place.get(sched_field))
    sched = parse_iso(place.get(sched_field)) or actual
    mode = str(st.get("mode") or "TRANSIT")
    line = str(st.get("displayName") or st.get("routeShortName") or st.get("tripShortName") or "") or \
        mode_name(mode)
    color = leg_color(mode, st.get("routeColor"))
    dest = str(st.get("headsign") or (st.get("tripTo") or {}).get("name") or "")
    origin = str((st.get("tripFrom") or {}).get("name") or "")
    track, sched_track = str(place.get("track") or ""), str(place.get("scheduledTrack") or "")
    out = {
        "time": hhmm(actual, tz), "datetime": iso_local(actual, tz),
        "scheduled_time": hhmm(sched, tz), "scheduled_datetime": iso_local(sched, tz),
        "delay_min": _minutes(actual, sched) or 0, "realtime": bool(st.get("realTime")),
        "line": line, "mode": mode, "mode_name": mode_name(mode), "color": color,
        "text_color": text_color(color, st.get("routeTextColor")),
        "headsign": dest, "origin": origin, "stop": str(place.get("name") or ""),
        "stop_id": str(place.get("stopId") or ""),
        "lat": round(float(place.get("lat") or 0), 6), "lon": round(float(place.get("lon") or 0), 6),
        "platform": track or sched_track,
        "cancelled": bool(st.get("cancelled") or st.get("tripCancelled") or place.get("cancelled")),
        "operator": str(st.get("agencyName") or ""),
    }
    if sched_track and track and sched_track != track:
        out["scheduled_platform"] = sched_track
        out["platform_changed"] = True
    t = f"{out['time']} · {line}"
    if arrivals and origin:
        t += f" from {origin}"
    if not arrivals and dest:
        t += f" toward {dest}"
    t += f" · {out['stop']}"
    if out["delay_min"]:
        t += f" · {'+' if out['delay_min'] > 0 else ''}{out['delay_min']} min"
    if out["platform"]:
        t += f" · platform {out['platform']}"
        if out.get("scheduled_platform"):
            t += f" (scheduled {out['scheduled_platform']})"
    if out["realtime"]:
        t += " · realtime"
    if out["cancelled"]:
        t += " · CANCELLED"
    if out["operator"]:
        t += f" · operator {out['operator']}"
    out["summary"] = t
    return out


def timetable(lat=None, lon=None, when=None, arrivals=False, radius=500, limit=8, stop_id=None, lang="en",
              cfg=None, max_age=None):
    """Odjezdy (arrivals=True prijezdy) ze zastavek v okoli bodu nebo ze zastavky stop_id."""
    if not stop_id and (lat is None or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
        raise MapsError("invalid coordinates")
    limit = int(clamp(int(limit), 1, 30))
    params = {}
    if stop_id:
        params["stopId"] = stop_id
    else:
        params.update({"center": f"{lat:.6f},{lon:.6f}", "radius": int(clamp(int(radius), 25, 2000)),
                       "exactRadius": "true"})
    params.update({"n": limit, "arriveBy": "true" if arrivals else "false", "direction": "LATER",
                   "realtimeMode": "REALTIME", "withAlerts": "true", "language": (lang or "en").split(",")[0]})
    if when is not None:
        params["time"] = api_time(when)
    data = api_get("transitous", service_url(cfg, "stoptimes_url", "LUXOS_MAPS_STOPTIMES", STOPTIMES_URL),
                   params, STOPTIMES_TTL, timeout=60, max_age=max_age)
    if not isinstance(data, dict) or not isinstance(data.get("stopTimes"), list):
        raise MapsError("invalid response")
    rows = [parse_stoptime(st, arrivals) for st in data["stopTimes"] if isinstance(st, dict)][:limit]
    names = []
    for r in rows:
        if r["stop"] and r["stop"] not in names:
            names.append(r["stop"])
    return {"stop_times": rows, "stops": names}


# ---- mista v okoli (Overpass) -------------------------------------------------------------------
NEARBY_SELECTORS = collections.OrderedDict((
    ("restaurants", '["amenity"~"^(restaurant|fast_food|food_court)$"]'),
    ("cafes", '["amenity"="cafe"]'),
    ("groceries", '["shop"~"^(supermarket|convenience|greengrocer)$"]'),
    ("fuel", '["amenity"="fuel"]'),
    ("charging", '["amenity"="charging_station"]'),
    ("parking", '["amenity"="parking"]'),
    ("pharmacies", '["amenity"="pharmacy"]'),
    ("hospitals", '["amenity"~"^(hospital|clinic|doctors)$"]'),
    ("hotels", '["tourism"~"^(hotel|hostel|guest_house|motel)$"]'),
    ("attractions", '["tourism"~"^(attraction|museum|viewpoint|gallery)$"]'),
    ("public_transport", '["public_transport"]'),
    ("toilets", '["amenity"="toilets"]'),
    ("playgrounds", '["leisure"="playground"]'),
))
PLACE_KIND_KEYS = ("amenity", "shop", "tourism", "leisure", "railway", "public_transport", "highway")
TRANSIT_TAGS = {("highway", "bus_stop"), ("railway", "tram_stop"), ("railway", "station"), ("railway", "halt"),
                ("railway", "subway_entrance"), ("amenity", "bus_station"), ("amenity", "ferry_terminal")}


def overpass_regex(text):
    return "".join("\\" + c if c in '\\.*+?^${}()|[]"' else c for c in text)


def is_transit_place(place):
    """Zastavka/stanice (vysledek hledani nebo okoli) -> nabidnout Odjezdy."""
    if not isinstance(place, dict):
        return False
    if place.get("transit"):
        return True
    cat, typ = place.get("category") or "", place.get("type") or ""
    return cat == "public_transport" or (cat, typ) in TRANSIT_TAGS or \
        (cat == "railway" and typ in ("station", "halt", "tram_stop", "stop", "platform"))


def nearby(lat, lon, category=None, name=None, radius=1500, limit=20, cfg=None):
    """Mista v okoli bodu podle kategorie (NEARBY_SELECTORS) nebo nazvu; serazena podle vzdalenosti."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise MapsError("invalid coordinates")
    category = (category or "").strip().lower() or None
    name = " ".join((name or "").split()) or None
    if not category and not name:
        raise MapsError("provide --category or --name")
    if category and category not in NEARBY_SELECTORS:
        raise MapsError("unknown category, use one of: " + ", ".join(NEARBY_SELECTORS))
    if name and (len(name) > 80 or any(ord(c) < 32 for c in name)):
        raise MapsError("name is too long")
    radius = int(clamp(int(radius), 50, 10000))
    limit = int(clamp(int(limit), 1, 50))
    selector = NEARBY_SELECTORS[category] if category else ""
    if name:
        selector += f'["name"~"{overpass_regex(name)}",i]'
    # vic prvku nez limit: zastavky maji nastupiste i stop_position se stejnym nazvem (slucuji se)
    fetch_n = min(100, limit * 3) if category == "public_transport" else limit
    # Overpass vraci prvnich N prvku v poradi podle id, ne podle vzdalenosti - v hustem miste (centrum
    # mesta) by "nejblizsi" byly nahodne z celeho okruhu. Jeden dotaz s nekolika okruhy (250 m, 750 m,
    # cely): nejblizsi mista jsou vzdy ve vysledku, pak se seradi a oriznou na limit.
    radii = [r for r in (250, 750) if r < radius] + [radius]
    query = "[out:json][timeout:20];" + "".join(
        f"nwr(around:{r},{lat:.6f},{lon:.6f}){selector};out center {fetch_n};" for r in radii)
    data = api_get("overpass", service_url(cfg, "overpass_url", "LUXOS_MAPS_OVERPASS", OVERPASS_URL),
                   {"data": query}, NEARBY_TTL, timeout=40)
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise MapsError("invalid response")
    out = []
    seen = set()
    for el in data["elements"]:
        if not isinstance(el, dict):
            continue
        key = (el.get("type"), el.get("id"))
        if key[1] is not None:
            if key in seen:
                continue                   # stejny prvek z vic okruhu
            seen.add(key)
        c = el.get("center") if isinstance(el.get("center"), dict) else el
        try:
            plat, plon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        kind = next((f"{k}={tags[k]}" for k in PLACE_KIND_KEYS if tags.get(k)), "")
        transit = bool(tags.get("public_transport")) or any(tags.get(k) == v for k, v in TRANSIT_TAGS)
        pname = str(tags.get("name") or "")
        if not pname and transit:
            continue                       # bezejmenna stop_position nic nerekne
        street = " ".join(x for x in (tags.get("addr:street") or tags.get("addr:place"),
                                      tags.get("addr:housenumber")) if x)
        town = " ".join(x for x in (tags.get("addr:postcode"), tags.get("addr:city")) if x)
        p = {"name": pname, "lat": round(plat, 6), "lon": round(plon, 6),
             "distance_m": int(round(distance_m(lat, lon, plat, plon))), "kind": kind,
             "category": kind.split("=")[0] if kind else "", "type": kind.split("=")[1] if kind else "",
             "address": ", ".join(x for x in (street, town) if x)}
        if transit:
            p["transit"] = True
            ref = tags.get("local_ref") or tags.get("ref")
            if ref:
                p["platform"] = str(ref)
        for k in ("opening_hours", "phone", "website", "wheelchair", "cuisine", "operator"):
            v = tags.get(k) or (tags.get("contact:" + k) if k in ("phone", "website") else None)
            if v:
                p[k] = str(v)
        if el.get("type") in ("node", "way", "relation") and el.get("id") is not None:
            p["osm"] = f"{el['type']}/{el['id']}"
            p["osm_url"] = f"https://www.openstreetmap.org/{el['type']}/{el['id']}"
        out.append(p)
    out.sort(key=lambda p: p["distance_m"])
    merged = []
    for p in out:
        # stejne misto vicekrat (uzel + plocha, zastavka: nastupiste A/B/C + stop_position): jen nejblizsi
        tol = 250 if p.get("transit") else 40
        same = next((q for q in merged if p["name"] and q["name"] == p["name"]
                     and distance_m(q["lat"], q["lon"], p["lat"], p["lon"]) < tol), None)
        if same is None:
            merged.append(p)
        elif p.get("platform") and p["platform"] not in same.get("platforms", []):
            same.setdefault("platforms", [same["platform"]] if same.get("platform") else []).append(p["platform"])
    for p in merged:
        if p.get("platforms"):
            p["platforms"].sort(key=lambda v: (len(v), v))
    return merged[:limit]


# ---- nahled trasy (pro karticku v LuxAI) --------------------------------------------------------
ROUTE_COLORS = {"car": "#DC2626", "bike": "#16A34A", "walk": "#2563EB"}
OSM_ENGINES = {"car": "fossgis_osrm_car", "bike": "fossgis_osrm_bike", "walk": "fossgis_osrm_foot"}


def osm_directions_url(mode, a, b):
    return (f"https://www.openstreetmap.org/directions?engine={OSM_ENGINES.get(mode, 'fossgis_osrm_car')}"
            f"&route={a['lat']:.6f},{a['lon']:.6f};{b['lat']:.6f},{b['lon']:.6f}")


def make_preview(mode, start, end, legs, open_map_url=None):
    """Data pro maly obrazek trasy (stejne pole jako RouteMapData mobilni LuxAI + bbox).
    legs: [{"mode", "label", "color", "points": [(lat, lon)...]}]."""
    out_legs, lats, lons = [], [start["lat"], end["lat"]], [start["lon"], end["lon"]]
    for lg in legs:
        pts = thin_points(lg["points"], 400)
        if len(pts) < 2:
            continue
        lats += [p[0] for p in pts]
        lons += [p[1] for p in pts]
        out_legs.append({"mode": lg["mode"], "label": lg.get("label", ""), "color": lg["color"],
                         "polyline": encode_polyline(pts, 6), "precision": 6})
    return {"version": 1, "mode": mode,
            "start": {"lat": round(start["lat"], 6), "lon": round(start["lon"], 6), "label": start.get("label", "")},
            "end": {"lat": round(end["lat"], 6), "lon": round(end["lon"], 6), "label": end.get("label", "")},
            "bbox": [round(min(lats), 6), round(min(lons), 6), round(max(lats), 6), round(max(lons), 6)],
            "legs": out_legs, "open_map_url": open_map_url,
            "attribution": "© OpenStreetMap contributors"}


def leg_points(leg):
    g = leg.get("geometry")
    if not g:
        return []
    try:
        return decode_polyline(g["polyline"], g.get("precision", 6))
    except (ValueError, KeyError, TypeError):
        return []


def itinerary_preview(it, a, b):
    legs = []
    for lg in it["legs"]:
        pts = leg_points(lg) or [(lg["from"]["lat"], lg["from"]["lon"]), (lg["to"]["lat"], lg["to"]["lon"])]
        legs.append({"mode": lg["mode"], "label": lg["line"] or lg["mode_name"], "color": lg["color"],
                     "points": pts})
    first, last = it["legs"][0], it["legs"][-1]
    return make_preview(TRANSIT, dict(a, label=a.get("name") or first["from"]["name"] or "Start"),
                        dict(b, label=b.get("name") or last["to"]["name"] or "Destination"), legs)


def preview_from_json(data, itinerary=0):
    """Vstup --render-preview: objekt nahledu, nebo cely vystup route/transit-route."""
    if not isinstance(data, dict):
        raise MapsError("invalid preview JSON")
    if isinstance(data.get("legs"), list) and data.get("start") and data.get("end") and \
            all("polyline" in lg for lg in data["legs"]):
        return data
    its = data.get("itineraries")
    if isinstance(its, list) and its and (itinerary or not data.get("preview")):
        if not 0 <= itinerary < len(its):
            raise MapsError("no such itinerary")
        it = its[itinerary]
        if not all(lg.get("geometry") for lg in it.get("legs", [])) and itinerary:
            raise MapsError("itinerary has no geometry (use transit-route --geometry)")
        return itinerary_preview(it, data.get("from") or {"lat": it["legs"][0]["from"]["lat"],
                                                          "lon": it["legs"][0]["from"]["lon"]},
                                 data.get("to") or {"lat": it["legs"][-1]["to"]["lat"],
                                                    "lon": it["legs"][-1]["to"]["lon"]})
    if isinstance(data.get("preview"), dict):
        return data["preview"]
    raise MapsError("no route preview in this JSON")


def fetch_tiles(url, keys, timeout=12.0):
    """Stahne/precte z mezipameti presne tyto dlazdice (TileStore: User-Agent, mezipamet podle hlavicek,
    max. 2 stahovani). Vraci ({key: png}, stats)."""
    got = {}
    lock = threading.Lock()

    def cb(key, data):
        if data is not None:
            with lock:
                got[key] = data
    store = TileStore(url, cb)
    try:
        store.want(list(keys))
        end = time.time() + timeout
        while time.time() < end:
            with store.cond:
                idle = not store.busy and not store.net_queue and not store.disk_queue
                offline = store.offline
            if idle or offline:
                break
            time.sleep(0.03)
    finally:
        store.stop()
    with lock:
        return dict(got), dict(store.stats)


def render_preview(preview, width=480, height=270, out_path=None, cfg=None, tile_url=None):
    """Maly obrazek trasy PNG: dlazdice OSM (jen ty, ktere obrazek pokryva), trasa v barvach linek,
    zacatek/cil, atribuce. Bez site jen dlazdice z mezipameti (chybejici = svetle pozadi)."""
    import cairo
    import io as _io
    width, height = int(width), int(height)
    if not (64 <= width <= 1024 and 64 <= height <= 1024):
        raise MapsError("size must be between 64x64 and 1024x1024")
    legs = []
    for lg in preview.get("legs") or []:
        try:
            pts = decode_polyline(lg["polyline"], int(lg.get("precision", 6)))
        except (ValueError, KeyError, TypeError):
            continue
        if len(pts) >= 2:
            legs.append((pts, hex_rgb(lg.get("color")), str(lg.get("mode") or "").upper() == "WALK"))
    s, n = preview["start"], preview["end"]
    lats = [s["lat"], n["lat"]] + [p[0] for pts, _c, _w in legs for p in pts]
    lons = [s["lon"], n["lon"]] + [p[1] for pts, _c, _w in legs for p in pts]
    pad = 28
    x0, y0 = to_world(max(lats), min(lons))
    x1, y1 = to_world(min(lats), max(lons))
    dx, dy = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    z = int(clamp(math.floor(min(math.log2((width - 2 * pad) / (dx * TILE)),
                                 math.log2((height - 2 * pad) / (dy * TILE)))), 1, 17))
    scale = TILE * 2 ** z
    left = (x0 + x1) / 2 * scale - width / 2
    top = (y0 + y1) / 2 * scale - height / 2
    nt = 2 ** z
    keys = [(z, ix % nt, iy) for iy in range(max(0, int(top // TILE)), min(nt - 1, int((top + height) // TILE)) + 1)
            for ix in range(int(left // TILE), int((left + width) // TILE) + 1)]
    url = tile_url or service_url(cfg, "tile_url", "LUXOS_MAPS_TILES", TILE_URL)
    tiles, stats = fetch_tiles(url, dict.fromkeys(keys))
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0.95, 0.94, 0.91)
    cr.paint()
    missing = 0
    for iy in range(max(0, int(top // TILE)), min(nt - 1, int((top + height) // TILE)) + 1):
        for ix in range(int(left // TILE), int((left + width) // TILE) + 1):
            data = tiles.get((z, ix % nt, iy))
            img = None
            if data:
                try:
                    img = cairo.ImageSurface.create_from_png(_io.BytesIO(data))
                except (cairo.Error, MemoryError, ValueError):
                    img = None
            if img is None:
                missing += 1
                continue
            cr.set_source_surface(img, round(ix * TILE - left), round(iy * TILE - top))
            cr.paint()

    def xy(lat, lon):
        wx, wy = to_world(lat, lon)
        return wx * scale - left, wy * scale - top
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for pts, _c, _w in legs:                 # nejdriv vsechny bile okraje (sousedni useky zustanou ostre)
        cr.new_path()
        for p in pts:
            cr.line_to(*xy(*p))
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(7.5)
        cr.stroke()
    for pts, color, walk in legs:
        cr.new_path()
        for p in pts:
            cr.line_to(*xy(*p))
        cr.set_source_rgb(*color)
        cr.set_line_width(4.5)
        cr.set_dash([0.1, 7] if walk else [])
        if walk:
            cr.set_line_width(5)
        cr.stroke()
    cr.set_dash([])
    for p, color in ((s, (0.086, 0.639, 0.29)), (n, (0.863, 0.149, 0.149))):
        x, y = xy(p["lat"], p["lon"])
        cr.arc(x, y, 7.5, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        cr.arc(x, y, 5.5, 0, 2 * math.pi)
        cr.set_source_rgb(*color)
        cr.fill()
    text = "© OpenStreetMap contributors"
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(10 if width >= 240 else 8)
    ext = cr.text_extents(text)
    bw, bh = ext.x_advance + 8, 14
    cr.rectangle(width - bw, height - bh, bw, bh)
    cr.set_source_rgba(1, 1, 1, 0.82)
    cr.fill()
    cr.move_to(width - bw + 4, height - 4)
    cr.set_source_rgb(0.2, 0.2, 0.2)
    cr.show_text(text)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        surf.write_to_png(out_path)
    return {"zoom": z, "tiles": len(keys), "missing_tiles": missing, "downloaded": stats.get("downloads", 0),
            "width": width, "height": height}


# ---- poloha -----------------------------------------------------------------------
def ip_location():
    """Priblizna poloha podle IP (ipinfo.io). Volat jen po souhlasu uzivatele."""
    data = http_json(os.environ.get("LUXOS_MAPS_IP") or IP_URL)
    try:
        lat, lon = (float(x) for x in str(data["loc"]).split(","))
    except (KeyError, ValueError, TypeError) as e:
        raise MapsError("no location") from e
    return {"lat": lat, "lon": lon, "accuracy": 5000.0, "source": "ip", "name": str(data.get("city") or "")}


def geoclue_location(timeout=8.0):
    """Poloha ze sluzby GeoClue (je-li v systemu a aplikace ji smi pouzit); jinak None."""
    if os.environ.get("LUXOS_MAPS_GEOCLUE", "1") == "0":
        return None
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListActivatableNames", None, None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListNames", None, None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        name = "org.freedesktop.GeoClue2"
        if name not in names and name not in owned:
            return None
        # GetClient ceka, dokud se neprihlasi agent GeoClue v sezeni (na LuxOS geoclue-demo-agent z autostartu);
        # bez nej by cekal donekonecna - kratky limit, pak poloha podle IP
        client = bus.call_sync(name, "/org/freedesktop/GeoClue2/Manager", "org.freedesktop.GeoClue2.Manager",
                               "GetClient", None, None, Gio.DBusCallFlags.NONE, 2500, None).unpack()[0]
        iface = "org.freedesktop.GeoClue2.Client"

        def set_prop(prop, value):
            bus.call_sync(name, client, "org.freedesktop.DBus.Properties", "Set",
                          GLib.Variant("(ssv)", (iface, prop, value)), None, Gio.DBusCallFlags.NONE, 2000, None)

        def get_prop(path, ifc, prop):
            return bus.call_sync(name, path, "org.freedesktop.DBus.Properties", "Get",
                                 GLib.Variant("(ss)", (ifc, prop)), None, Gio.DBusCallFlags.NONE, 2000,
                                 None).unpack()[0]
        set_prop("DesktopId", GLib.Variant("s", "luxos-maps"))
        set_prop("RequestedAccuracyLevel", GLib.Variant("u", 6))      # EXACT; GeoClue da, co ma
        bus.call_sync(name, client, iface, "Start", None, None, Gio.DBusCallFlags.NONE, 5000, None)
        try:
            end = time.time() + timeout
            while time.time() < end:
                loc = get_prop(client, iface, "Location")
                if loc and loc != "/":
                    lif = "org.freedesktop.GeoClue2.Location"
                    return {"lat": get_prop(loc, lif, "Latitude"), "lon": get_prop(loc, lif, "Longitude"),
                            "accuracy": max(5.0, get_prop(loc, lif, "Accuracy")), "source": "geoclue", "name": ""}
                time.sleep(0.4)
        finally:
            try:
                bus.call_sync(name, client, iface, "Stop", None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 - GeoClue chybi, odmitl aplikaci nebo neodpovida
        return None
    return None


# Telefon s aplikaci LuxOS Companion (sluzba luxos-companion, D-Bus relace cz.luxos.Companion1):
# cerstvy GPS fix (nejvys 15 s) jen se souhlasem s polohou v Mapach a se zapnutym sdilenim polohy
# v nastaveni Telefon. Mapy sluzbu nespousti (NO_AUTO_START), bez ni hned pokracuji GeoClue/IP.
COMPANION_NAME = "cz.luxos.Companion1"
COMPANION_PATH = "/cz/luxos/Companion1"
PHONE_FRESH_MS = 15000


def companion_sharing_enabled():
    """Prepinac "Sdilet polohu telefonu s Mapami" (~/.config/luxos/companion.json, vychozi zapnuto)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    data = _read_json(os.path.join(base, "luxos", "companion.json"))
    return not (isinstance(data, dict) and data.get("share_location") is False)


def phone_fix(d):
    """Slovnik z cz.luxos.Companion1 (GetLocation / LocationChanged) -> poloha pro Mapy, nebo None."""
    if not isinstance(d, dict) or d.get("valid") is not True:
        return None
    lat, lon, acc, age = d.get("latitude"), d.get("longitude"), d.get("accuracy"), d.get("age_ms", 0)
    nums = (lat, lon, acc, age)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in nums):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and acc >= 0 and 0 <= age <= PHONE_FRESH_MS):
        return None
    out = {"lat": float(lat), "lon": float(lon), "accuracy": max(1.0, float(acc)), "source": "phone",
           "name": "", "age_ms": int(age)}
    for k in ("speed", "bearing", "altitude"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = float(v)
    return out


_companion_bus = {}


def companion_bus():
    """Sbernice relace (LUXOS_MAPS_COMPANION_BUS: adresa jine sbernice - testy)."""
    from gi.repository import Gio
    addr = os.environ.get("LUXOS_MAPS_COMPANION_BUS")
    if not addr:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if addr not in _companion_bus:
        _companion_bus[addr] = Gio.DBusConnection.new_for_address_sync(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
    return _companion_bus[addr]


def phone_location(timeout_ms=800):
    """Cerstva poloha z telefonu (LuxOS Companion) nebo None. Souhlas Map kontroluje my_location()."""
    if os.environ.get("LUXOS_MAPS_PHONE", "1") == "0" or not companion_sharing_enabled():
        return None
    try:
        from gi.repository import Gio, GLib
        bus = companion_bus()
        r = bus.call_sync(COMPANION_NAME, COMPANION_PATH, COMPANION_NAME, "GetLocation", None,
                          GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NO_AUTO_START, timeout_ms, None)
        return phone_fix(r.unpack()[0])
    except Exception:  # noqa: BLE001 - sluzba nebezi, neni sbernice relace
        return None


def my_location(cfg=None):
    """Telefon (LuxOS Companion, jen se souhlasem v Mapach), GeoClue, kdyz je k dispozici, jinak priblizne
    podle IP. Volajici kontroluje souhlas uzivatele (location_consent) i pro GeoClue a IP."""
    if cfg is None:
        cfg = load_config()
    if cfg.get("location_consent") is True:
        phone = phone_location()
        if phone:
            return phone
    return geoclue_location() or ip_location()


# ---- dlazdice --------------------------------------------------------------------
def parse_cache_headers(headers, now):
    """Do kdy je dlazdice cerstva (podle Cache-Control/Age/Expires; stale-while-revalidate se
    pricita - dlazdice se i potom zobrazuje a jen podminene obnovi). Bez hlavicek 7 dni."""
    cc = (headers.get("Cache-Control") or "").lower()
    if "no-store" in cc or "no-cache" in cc:
        return now
    ttl = None
    m = re.search(r"max-age\s*=\s*(\d+)", cc)
    if m:
        try:
            age = int(headers.get("Age") or 0)
        except ValueError:
            age = 0
        ttl = max(0, int(m.group(1)) - age)
        swr = re.search(r"stale-while-revalidate\s*=\s*(\d+)", cc)
        if swr:
            ttl += int(swr.group(1))
    elif headers.get("Expires"):
        try:
            exp = email.utils.parsedate_to_datetime(headers["Expires"]).timestamp()
            ttl = max(0, exp - now)
        except (TypeError, ValueError, IndexError):
            ttl = None
    if ttl is None:
        ttl = MIN_TTL
    return now + ttl


class TileStore:
    """Dlazdice: pamet nema (to dela okno), disk + sit. Viditelne dlazdice predava okno metodou
    want(); co uz neni videt, se nestahuje (zadne prednacitani). Vysledek: callback(key, png|None)
    z vlakna - okno ho preda do hlavni smycky. Expirace dlazdice = mtime souboru, ETag v xattr."""

    def __init__(self, url, callback, cache_root=None, workers=DOWNLOADS):
        self.url = url
        self.callback = callback
        host = urllib.parse.urlsplit(url).netloc or "local"
        tag = "osm" if url == TILE_URL else re.sub(r"[^A-Za-z0-9.-]", "_", host) + "-" + \
            hashlib.sha1(url.encode()).hexdigest()[:8]
        self.root = os.path.join(cache_root or cache_dir(), "tiles", tag)
        self.cond = threading.Condition()
        self.disk_queue = collections.OrderedDict()   # key -> True (poradi = priorita)
        self.net_queue = collections.OrderedDict()    # key -> (etag, stary obsah)
        self.busy = set()
        self.visible = set()
        self.offline_until = 0.0
        self.offline = False
        self.stopped = False
        self.stats = {"downloads": 0, "revalidated": 0, "disk": 0, "errors": 0, "max_parallel": 0}
        self._active = 0
        threads = [threading.Thread(target=self._disk_worker, daemon=True)]
        threads += [threading.Thread(target=self._net_worker, daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()

    def path(self, key):
        z, x, y = key
        return os.path.join(self.root, str(z), str(x), f"{y}.png")

    def want(self, keys):
        """Seznam viditelnych dlazdic (od stredu). Nahradi frontu - stare pozadavky se zahodi."""
        with self.cond:
            self.visible = set(keys)
            for k in list(self.disk_queue):
                if k not in self.visible:
                    del self.disk_queue[k]
            # sitova fronta v poradi noveho pohledu (od stredu), neviditelne pryc
            old = self.net_queue
            self.net_queue = collections.OrderedDict((k, old[k]) for k in keys if k in old)
            for k in old:
                if k not in self.net_queue:
                    self.busy.discard(k)      # ceka jen ve fronte, nikdo ho nestahuje
            for k in keys:
                if k not in self.busy and k not in self.net_queue:
                    self.disk_queue[k] = True
            self.cond.notify_all()

    def stop(self):
        with self.cond:
            self.stopped = True
            self.cond.notify_all()

    def _disk_worker(self):
        while True:
            with self.cond:
                while not self.disk_queue and not self.stopped:
                    self.cond.wait()
                if self.stopped:
                    return
                key, _v = self.disk_queue.popitem(last=False)
                self.busy.add(key)
            data, fresh, etag = self._read(key)
            if data is not None:
                self.stats["disk"] += 1
                self.callback(key, data)
            with self.cond:
                if fresh or self.stopped:
                    self.busy.discard(key)
                elif key in self.visible:
                    self.net_queue[key] = (etag, data)
                    self.cond.notify_all()
                else:
                    self.busy.discard(key)

    def _read(self, key):
        p = self.path(key)
        try:
            with open(p, "rb") as f:
                data = f.read()
            expires = os.stat(p).st_mtime
        except OSError:
            return None, False, None
        etag = None
        try:
            etag = os.getxattr(p, "user.etag").decode("ascii", "replace")
        except (OSError, AttributeError):
            pass
        return data, expires > time.time(), etag

    def _write(self, key, data, expires, etag):
        p = self.path(key)
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = f"{p}.{threading.get_ident()}.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            if etag:
                try:
                    os.setxattr(tmp, "user.etag", etag.encode("ascii", "replace"))
                except (OSError, AttributeError):
                    pass
            os.utime(tmp, (time.time(), expires))
            os.replace(tmp, p)
        except OSError:
            pass

    def _touch(self, key, expires):
        try:
            os.utime(self.path(key), (time.time(), expires))
        except OSError:
            pass

    def _net_worker(self):
        conn = None
        while True:
            with self.cond:
                while (not self.net_queue or time.time() < self.offline_until) and not self.stopped:
                    if self.net_queue and time.time() < self.offline_until:
                        self.cond.wait(max(0.05, self.offline_until - time.time()))
                    else:
                        self.cond.wait()
                if self.stopped:
                    if conn:
                        conn.close()
                    return
                # poradi aktualniho pohledu: nejdriv stred
                key, (etag, old) = self.net_queue.popitem(last=False)
                self._active += 1
                self.stats["max_parallel"] = max(self.stats["max_parallel"], self._active)
            try:
                conn, data = self._download(conn, key, etag, old)
                ok = True
            except (OSError, http.client.HTTPException, MapsError):
                if conn:
                    conn.close()
                conn, data, ok = None, None, False
            with self.cond:
                self._active -= 1
                self.busy.discard(key)
                if ok:
                    self.offline = False
                else:
                    self.stats["errors"] += 1
                    if not self.offline:
                        self.offline = True
                    self.offline_until = time.time() + 15     # bez site chvili nezkouset
            if ok and data is not None and data is not old:
                self.callback(key, data)
            elif data is None and old is None:      # bez site nebo dlazdice neexistuje (404)
                self.callback(key, None)

    def retry_now(self):
        with self.cond:
            self.offline_until = 0.0
            self.cond.notify_all()

    def _download(self, conn, key, etag, old):
        z, x, y = key
        url = self.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        u = urllib.parse.urlsplit(url)
        if conn is None or getattr(conn, "_luxos_host", None) != (u.scheme, u.netloc):
            if conn:
                conn.close()
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = cls(u.netloc, timeout=TIMEOUT)
            conn._luxos_host = (u.scheme, u.netloc)
        headers = {"User-Agent": USER_AGENT, "Accept": "image/png,image/*"}
        if etag and old is not None:
            headers["If-None-Match"] = etag
        path = u.path + ("?" + u.query if u.query else "")
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read(2 * 1024 * 1024)
        now = time.time()
        expires = parse_cache_headers(resp.headers, now)
        if resp.getheader("Connection", "").lower() == "close":
            conn.close()
            conn = None
        if resp.status == 304 and old is not None:
            self.stats["revalidated"] += 1
            self._touch(key, expires)
            return conn, old
        if resp.status == 404:
            return conn, None
        if resp.status != 200 or not body:
            raise MapsError(f"HTTP {resp.status}")
        self.stats["downloads"] += 1
        self._write(key, body, expires, resp.getheader("ETag"))
        return conn, body


def prune_cache(limit=CACHE_LIMIT, root=None, force=False):
    """Kdyz mezipamet dlazdic presahne limit, smaze nejdrive vyprsene (nejstarsi mtime). Jednou denne."""
    root = os.path.join(root or cache_dir(), "tiles")
    stamp = os.path.join(os.path.dirname(root), "pruned")
    try:
        if not force and time.time() - os.stat(stamp).st_mtime < 24 * 3600:
            return 0
    except OSError:
        pass
    files, total = [], 0
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
    removed = 0
    if total > limit:
        files.sort()
        target = limit * 0.8
        for _mt, size, p in files:
            if total <= target:
                break
            try:
                os.unlink(p)
                total -= size
                removed += 1
            except OSError:
                pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w"):
            pass
    except OSError:
        pass
    return removed


# ---- rozhrani pro LuxAI a skripty: luxos-maps --json PRIKAZ ... ------------------------
CLI_HELP = """usage: luxos-maps --json COMMAND ...
  search QUERY [--near LAT,LON] [--limit N]   places (Nominatim, max 1 request/s, cached 30 days)
  reverse LAT,LON                             address of a point
  route FROM TO [--mode car|bike|walk|transit] [--no-preview]
                                              FROM/TO: "LAT,LON", "here" (my location) or a place name
  transit-route FROM TO [--time T] [--arrive] [--max-transfers N] [--limit N] [--geometry] [--no-preview]
                                              public transport (Transitous; T: ISO 8601 or HH:MM, default now)
  timetable STOP [--type departures|arrivals] [--time T] [--radius M] [--limit N] [--stop-id ID]
                                              departures/arrivals at stops near STOP (realtime, Transitous)
  nearby PLACE --category C | --name TEXT [--radius M] [--limit N]
                                              places around PLACE (Overpass); C: """ + "|".join(NEARBY_SELECTORS) + """
  where-am-i                                  my location - only after the user allowed it in Maps
  open PLACE | open --route FROM TO [--mode]  open the Maps window (PLACE: LAT,LON, geo: URI or name)
Output: one JSON object on stdout ({"ok": true, ...} or {"ok": false, "error": ...}).
Route picture: luxos-maps --render-preview FILE.json --size WxH --out FILE.png [--itinerary N]"""
HERE_WORDS = ("here", "me", "my location", "current location")
OSM = "© OpenStreetMap contributors"


def _pop_opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i]
    return default


def _pop_flag(args, name):
    if name in args:
        args.remove(name)
        return True
    return False


def _int_opt(args, name, default, lo, hi):
    v = _pop_opt(args, name)
    if v is None:
        return default
    try:
        n = int(v)
    except ValueError:
        raise MapsError(f"{name} must be a whole number") from None
    if not lo <= n <= hi:
        raise MapsError(f"{name} must be between {lo} and {hi}")
    return n


def resolve_point(text, cfg, lang):
    """'50.08,14.42' / 'here' / geo: / nazev mista -> misto {"name","lat","lon",...}."""
    text = (text or "").strip()
    if text.lower() in HERE_WORDS:
        if not cfg.get("location_consent"):
            raise MapsError("consent: the user has not allowed Maps to use the location (Maps › My Location)")
        loc = my_location(cfg)
        return {"name": "My Location", "lat": loc["lat"], "lon": loc["lon"], "accuracy": loc["accuracy"]}
    c = parse_coords(text)
    if c:
        return {"name": c[2] or format_coords(c[0], c[1]), "lat": c[0], "lon": c[1]}
    geo = parse_geo_uri(text)
    if geo and geo["lat"] is not None:
        return {"name": geo["label"] or format_coords(geo["lat"], geo["lon"]), "lat": geo["lat"], "lon": geo["lon"]}
    res = search(geo["query"] if geo else text, lang, cfg=cfg, limit=1)
    if not res:
        raise MapsError(f"place not found: {text}")
    return res[0]


def _public(place):
    out = {k: place[k] for k in ("name", "address", "lat", "lon", "type", "category", "accuracy") if k in place}
    out["lat"], out["lon"] = round(out["lat"], 6), round(out["lon"], 6)
    out["geo_uri"] = geo_uri(place["lat"], place["lon"], 16, place.get("name"))
    out["osm_url"] = osm_url(place["lat"], place["lon"], 16)
    return out


def step_instruction(step, tr=lambda s: s):
    text = tr(step["text"])
    return text % step["arg"] if step.get("arg") else text


def _transit_json(a, b, when, arrive, max_tr, limit, geometry, no_preview, cfg):
    plan = transit_plan(a, b, when, arrive, max_tr, limit, cfg=cfg)
    out = {"ok": True, "mode": TRANSIT, "from": _public(a), "to": _public(b),
           "search": {"time": iso_local(when, local_zone()) if when else "now", "arrive_by": bool(arrive)},
           "timezone": plan["timezone"], "itineraries": plan["itineraries"]}
    if not no_preview:
        out["preview"] = itinerary_preview(plan["itineraries"][0], a, b)
    if not geometry:
        out["itineraries"] = [dict(it, legs=[{k: v for k, v in lg.items() if k != "geometry"} for lg in it["legs"]])
                              for it in plan["itineraries"]]
    out["attribution"] = TRANSIT_ATTRIBUTION + "; map data " + OSM
    out["sources_url"] = TRANSITOUS_SOURCES_URL
    return out


def cli(argv, spawn=None):
    """luxos-maps --json ... -> (navratovy kod, slovnik). Stejne mezipameti a limity jako okno."""
    args = list(argv)
    cfg = load_config()
    lang = lang_code()
    imperial = locale_country() in IMPERIAL
    if not args or args[0] in ("-h", "--help", "help"):
        return 0, {"ok": True, "help": CLI_HELP, "nearby_categories": list(NEARBY_SELECTORS)}
    cmd = args.pop(0)
    try:
        if cmd == "search":
            near = _pop_opt(args, "--near")
            limit = int(_pop_opt(args, "--limit", "5"))
            query = " ".join(args)
            bbox = None
            if near:
                c = parse_coords(near)
                if not c:
                    raise MapsError("--near must be LAT,LON")
                bbox = (c[0] - 0.5, c[0] + 0.5, c[1] - 0.8, c[1] + 0.8)
            res = search(query, lang, near=bbox, cfg=cfg, limit=max(1, min(limit, 10)))
            return 0, {"ok": True, "query": query, "results": [_public(p) for p in res],
                       "attribution": OSM + " (Nominatim)"}
        if cmd == "reverse":
            c = parse_coords(" ".join(args))
            if not c:
                raise MapsError("usage: reverse LAT,LON")
            p = reverse(c[0], c[1], lang, cfg=cfg)
            return 0, {"ok": True, "place": _public(p) if p else None, "attribution": OSM + " (Nominatim)"}
        if cmd == "route":
            mode = _pop_opt(args, "--mode", "car")
            if mode == TRANSIT:
                return cli(["transit-route", *args], spawn)
            no_preview = _pop_flag(args, "--no-preview")
            if mode not in MODES or len(args) != 2:
                raise MapsError("usage: route FROM TO [--mode car|bike|walk|transit]")
            a = resolve_point(args[0], cfg, lang)
            b = resolve_point(args[1], cfg, lang)
            r = route(a, b, mode, cfg=cfg)
            steps = [{"instruction": step_instruction(s), "street": s["name"], "distance_m": round(s["distance"]),
                      "lat": round(s["lat"], 6), "lon": round(s["lon"], 6)} for s in r["steps"]]
            out = {"ok": True, "mode": mode, "from": _public(a), "to": _public(b),
                   "distance_m": round(r["distance"]), "duration_s": round(r["duration"]),
                   "distance": format_distance(r["distance"], imperial, "en"),
                   "duration": format_duration(r["duration"]), "steps": steps,
                   "open_map_url": osm_directions_url(mode, a, b)}
            if not no_preview:
                out["preview"] = make_preview(
                    mode, dict(a, label=a.get("name", "")), dict(b, label=b.get("name", "")),
                    [{"mode": mode.upper(), "label": mode.capitalize(), "color": ROUTE_COLORS[mode],
                      "points": r["points"]}], out["open_map_url"])
            out["attribution"] = OSM + " (routing: FOSSGIS OSRM)"
            return 0, out
        if cmd == "transit-route":
            when = parse_user_time(_pop_opt(args, "--time"))
            arrive = _pop_flag(args, "--arrive") or _pop_flag(args, "--arrive-by")
            max_tr = _int_opt(args, "--max-transfers", 3, 0, 8)
            limit = _int_opt(args, "--limit", 3, 1, 5)
            geometry = _pop_flag(args, "--geometry")
            no_preview = _pop_flag(args, "--no-preview")
            if len(args) != 2 or any(x.startswith("--") for x in args):
                raise MapsError("usage: transit-route FROM TO [--time T] [--arrive] [--max-transfers N] "
                                "[--limit N] [--geometry] [--no-preview]")
            a = resolve_point(args[0], cfg, lang)
            b = resolve_point(args[1], cfg, lang)
            return 0, _transit_json(a, b, when, arrive, max_tr, limit, geometry, no_preview, cfg)
        if cmd == "timetable":
            typ = _pop_opt(args, "--type", "departures")
            if typ not in ("departures", "arrivals"):
                raise MapsError("--type must be departures or arrivals")
            when = parse_user_time(_pop_opt(args, "--time"))
            radius = _int_opt(args, "--radius", 500, 25, 2000)
            limit = _int_opt(args, "--limit", 8, 1, 30)
            stop_id = _pop_opt(args, "--stop-id")
            if not args and not stop_id:
                raise MapsError("usage: timetable STOP [--type departures|arrivals] [--time T] [--radius M] "
                                "[--limit N] [--stop-id ID]")
            p = resolve_point(" ".join(args), cfg, lang) if args else None
            tt = timetable(p["lat"] if p else None, p["lon"] if p else None, when, typ == "arrivals", radius,
                           limit, stop_id=stop_id, lang=lang, cfg=cfg)
            if not tt["stop_times"]:
                raise MapsError("no departures found near this place" if typ == "departures"
                                else "no arrivals found near this place")
            out = {"ok": True, "type": typ, "stops": tt["stops"], "time": iso_local(when, local_zone())
                   if when else "now", "radius_m": None if stop_id else radius}
            if p:
                out["near"] = _public(p)
            if stop_id:
                out["stop_id"] = stop_id
            out.update({"connections": tt["stop_times"], "attribution": TRANSIT_ATTRIBUTION,
                        "sources_url": TRANSITOUS_SOURCES_URL})
            return 0, out
        if cmd == "nearby":
            category = _pop_opt(args, "--category")
            name = _pop_opt(args, "--name") or _pop_opt(args, "--query")
            radius = _int_opt(args, "--radius", 1500, 50, 10000)
            limit = _int_opt(args, "--limit", 20, 1, 50)
            if not args or not (category or name):
                raise MapsError("usage: nearby PLACE --category " + "|".join(NEARBY_SELECTORS) +
                                " | --name TEXT [--radius M] [--limit N]")
            p = resolve_point(" ".join(args), cfg, lang)
            res = nearby(p["lat"], p["lon"], category, name, radius, limit, cfg=cfg)
            for r in res:
                r["distance"] = format_distance(r["distance_m"], imperial, "en")
                r["geo_uri"] = geo_uri(r["lat"], r["lon"], 17, r["name"] or None)
            return 0, {"ok": True, "category": category, "name": name, "origin": _public(p), "radius_m": radius,
                       "results": res, "attribution": OSM + " (Overpass API)"}
        if cmd == "where-am-i":
            if not cfg.get("location_consent"):
                raise MapsError("consent: the user has not allowed Maps to use the location (Maps › My Location)")
            loc = my_location(cfg)
            return 0, {"ok": True, "lat": round(loc["lat"], 6), "lon": round(loc["lon"], 6),
                       "accuracy_m": round(loc["accuracy"]), "source": loc["source"],
                       "geo_uri": geo_uri(loc["lat"], loc["lon"])}
        if cmd == "open":
            if not args:
                raise MapsError("usage: open PLACE | open --route FROM TO [--mode car|bike|walk|transit]")
            gui_args = list(args) if args[0] == "--route" else [" ".join(args)]
            (spawn or _spawn_gui)(gui_args)
            return 0, {"ok": True, "opened": gui_args}
    except BusyError as e:
        return 1, {"ok": False, "error": "busy", "message": str(e)}
    except MapsError as e:
        msg = str(e)
        if msg.startswith("consent: "):
            return 1, {"ok": False, "error": "consent", "message": msg.split(": ", 1)[1]}
        return 1, {"ok": False, "error": msg}
    except ValueError as e:
        return 1, {"ok": False, "error": str(e)}
    return 2, {"ok": False, "error": f"unknown command: {cmd}", "help": CLI_HELP}


def render_cli(argv):
    """luxos-maps --render-preview FILE.json|- --size WxH --out FILE.png [--itinerary N]."""
    args = list(argv)
    try:
        size = _pop_opt(args, "--size", "480x270")
        out = _pop_opt(args, "--out")
        itin = _int_opt(args, "--itinerary", 1, 1, 5) - 1
        m = re.match(r"^(\d+)[xX](\d+)$", size or "")
        if not m or not out or len(args) != 1:
            raise MapsError("usage: luxos-maps --render-preview FILE.json|- --size WxH --out FILE.png "
                            "[--itinerary N]")
        if args[0] == "-":
            import sys
            data = json.loads(sys.stdin.read(8 * 1024 * 1024))
        else:
            with open(args[0], encoding="utf-8") as f:
                data = json.loads(f.read(8 * 1024 * 1024))
        preview = preview_from_json(data, itin)
        info = render_preview(preview, int(m.group(1)), int(m.group(2)), out, cfg=load_config())
        return 0, dict({"ok": True, "out": os.path.abspath(out)}, **info,
                       attribution=OSM)
    except (OSError, ValueError) as e:
        return 1, {"ok": False, "error": str(e)}
    except MapsError as e:
        return 1, {"ok": False, "error": str(e)}


def _spawn_gui(args):
    import subprocess
    exe = os.environ.get("LUXOS_MAPS_EXE") or "luxos-maps"
    subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def cli_main(argv, render=False):
    code, data = render_cli(argv) if render else cli(argv)
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return code
