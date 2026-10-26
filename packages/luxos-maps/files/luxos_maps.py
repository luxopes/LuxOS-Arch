"""LuxOS Mapy - data bez GTK: dlazdice OpenStreetMap, hledani (Nominatim), trasy (OSRM), nastaveni.

  TileStore            mezipamet dlazdic na disku + nejvys 2 soubezna stahovani, jen viditelne dlazdice
  search(q, lang)      hledani mist (Nominatim, nejvys 1 pozadavek/s pro vsechna okna, mezipamet 30 dni)
  reverse(lat, lon)    co je na tomto miste (Nominatim, stejny limit)
  route(a, b, mode)    trasa autem/na kole/pesky (routing.openstreetmap.de, FOSSGIS, nejvys 1 pozadavek/s)
  parse_geo_uri(uri)   geo:50.08,14.42?z=15 / geo:0,0?q=Praha
  ip_location()        priblizna poloha podle IP (ipinfo.io) - jen po souhlasu uzivatele

Pravidla OSM (operations.osmfoundation.org/policies): vlastni User-Agent, mezipamet podle hlavicek
(Cache-Control/Expires/ETag, podmineny pozadavek po vyprseni, bez hlavicek 7 dni), zadne
prednacitani oblasti ani stahovani pro offline; hledani jen po Enter (zadne naseptavani).
Adresy jdou prepsat v nastaveni (tile_url, search_url, reverse_url, route_url) i bez aktualizace.
Mezipamet: $XDG_CACHE_HOME/luxos/maps, nastaveni: $XDG_CONFIG_HOME/luxos/maps.json.
Testy: LUXOS_MAPS_TILES, LUXOS_MAPS_SEARCH, LUXOS_MAPS_REVERSE, LUXOS_MAPS_ROUTE, LUXOS_MAPS_IP,
LUXOS_MAPS_RATE (interval limitu v s).
"""
import collections
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


class MapsError(Exception):
    pass


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
    if cfg.get("mode") not in MODES:
        cfg["mode"] = "car"
    cfg["location_consent"] = cfg.get("location_consent") is True
    for key in ("tile_url", "search_url", "reverse_url", "route_url"):
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
        s, n, w, e = (round(v, 1) for v in near)
        params["viewbox"] = f"{w},{n},{e},{s}"
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
        client = bus.call_sync(name, "/org/freedesktop/GeoClue2/Manager", "org.freedesktop.GeoClue2.Manager",
                               "GetClient", None, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
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


def my_location():
    """GeoClue, kdyz je k dispozici, jinak priblizne podle IP. Jen po souhlasu uzivatele."""
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
  route FROM TO [--mode car|bike|walk]        FROM/TO: "LAT,LON", "here" (my location) or a place name
  where-am-i                                  my location - only after the user allowed it in Maps
  open PLACE | open --route FROM TO [--mode]  open the Maps window (PLACE: LAT,LON, geo: URI or name)
Output: one JSON object on stdout ({"ok": true, ...} or {"ok": false, "error": ...})."""
HERE_WORDS = ("here", "me", "my location", "current location")


def _pop_opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i]
    return default


def resolve_point(text, cfg, lang):
    """'50.08,14.42' / 'here' / geo: / nazev mista -> misto {"name","lat","lon",...}."""
    text = (text or "").strip()
    if text.lower() in HERE_WORDS:
        if not cfg.get("location_consent"):
            raise MapsError("consent: the user has not allowed Maps to use the location (Maps › My Location)")
        loc = my_location()
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


def cli(argv, spawn=None):
    """luxos-maps --json ... -> (navratovy kod, slovnik). Stejne mezipameti a limity jako okno."""
    args = list(argv)
    cfg = load_config()
    lang = lang_code()
    imperial = locale_country() in IMPERIAL
    if not args or args[0] in ("-h", "--help", "help"):
        return 0, {"ok": True, "help": CLI_HELP}
    cmd = args.pop(0)
    osm = "© OpenStreetMap contributors"
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
                       "attribution": osm + " (Nominatim)"}
        if cmd == "reverse":
            c = parse_coords(" ".join(args))
            if not c:
                raise MapsError("usage: reverse LAT,LON")
            p = reverse(c[0], c[1], lang, cfg=cfg)
            return 0, {"ok": True, "place": _public(p) if p else None, "attribution": osm + " (Nominatim)"}
        if cmd == "route":
            mode = _pop_opt(args, "--mode", "car")
            if mode not in MODES or len(args) != 2:
                raise MapsError("usage: route FROM TO [--mode car|bike|walk]")
            a = resolve_point(args[0], cfg, lang)
            b = resolve_point(args[1], cfg, lang)
            r = route(a, b, mode, cfg=cfg)
            steps = [{"instruction": step_instruction(s), "street": s["name"], "distance_m": round(s["distance"]),
                      "lat": round(s["lat"], 6), "lon": round(s["lon"], 6)} for s in r["steps"]]
            return 0, {"ok": True, "mode": mode, "from": _public(a), "to": _public(b),
                       "distance_m": round(r["distance"]), "duration_s": round(r["duration"]),
                       "distance": format_distance(r["distance"], imperial, "en"),
                       "duration": format_duration(r["duration"]), "steps": steps,
                       "attribution": osm + " (routing: FOSSGIS OSRM)"}
        if cmd == "where-am-i":
            if not cfg.get("location_consent"):
                raise MapsError("consent: the user has not allowed Maps to use the location (Maps › My Location)")
            loc = my_location()
            return 0, {"ok": True, "lat": round(loc["lat"], 6), "lon": round(loc["lon"], 6),
                       "accuracy_m": round(loc["accuracy"]), "source": loc["source"],
                       "geo_uri": geo_uri(loc["lat"], loc["lon"])}
        if cmd == "open":
            if not args:
                raise MapsError("usage: open PLACE | open --route FROM TO [--mode car|bike|walk]")
            gui_args = list(args) if args[0] == "--route" else [" ".join(args)]
            (spawn or _spawn_gui)(gui_args)
            return 0, {"ok": True, "opened": gui_args}
    except MapsError as e:
        msg = str(e)
        if msg.startswith("consent: "):
            return 1, {"ok": False, "error": "consent", "message": msg.split(": ", 1)[1]}
        return 1, {"ok": False, "error": msg}
    except ValueError as e:
        return 1, {"ok": False, "error": str(e)}
    return 2, {"ok": False, "error": f"unknown command: {cmd}", "help": CLI_HELP}


def _spawn_gui(args):
    import subprocess
    exe = os.environ.get("LUXOS_MAPS_EXE") or "luxos-maps"
    subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def cli_main(argv):
    code, data = cli(argv)
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return code
