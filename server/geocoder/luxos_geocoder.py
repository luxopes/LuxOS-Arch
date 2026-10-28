#!/usr/bin/env python3
"""LuxOS geocoder - naseptavani mist pro Mapy LuxOS (typeahead), odpovedi kompatibilni s Photonem.

GET /api?q=...&lat=...&lon=...&limit=...&lang=...  ->  GeoJSON FeatureCollection jako photon.komoot.io/api
GET /health                                         ->  {"ok": true, "built": ..., "features": ...}

Proc Python a ne LSL: LSL 0.10.8 ma httpserver, ale SQLite jen pres program sqlite3 (novy proces
a nove otevreni databaze na kazdy dotaz = desitky ms a zadna sdilena mezipamet stranek), a LSL na
serveru (Debian) neni. Python 3 je na Debianu vzdy a jeho sqlite3 ma FTS5. http.server neni pro
provoz; tady je maly asyncio server HTTP/1.1 (keep-alive, limity hlavicek a casu) za Caddy.

Soukromi: dotazy se nikam nezapisuji (zadny access log, chyby bez textu dotazu); omezeni rychlosti
drzi jen adresu IP a dva citace v pameti procesu.

Databazi stavi scripts/geocoder/build.py (data OSM, Geofabrik). Jen cteni: immutable=1, query_only.
Kdyz se soubor databaze vymeni (symlink current -> nove vydani), dalsi dotazy ji samy znovu otevrou.
"""

import argparse
import asyncio
import concurrent.futures
import json
import math
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.parse

VERSION = "1.0"
MAX_Q = 100                  # znaku dotazu
MAX_LIMIT = 10
DEFAULT_LIMIT = 7
MAX_TOKENS = 8
CANDIDATES = 150             # radku z FTS na jeden dotaz (globalne a v okoli)
QUERY_BUDGET = 0.4           # s na dotaz do SQLite, pak se prerusi (ochrana pred drahymi dotazy)
RATE_BURST = 40              # pozadavku najednou na jednu adresu IP
RATE_PER_S = 10.0            # doplnovani za sekundu (psani s odkladem 150 ms = max. ~7/s)
RATE_MAX_IPS = 50000
KEEPALIVE_S = 30
HEADER_LIMIT = 8192

# delky predpon s vlastnim indexem FTS5. Dotaz "praha"* bez indexu predpony musi FTS5 nejdriv slozit cely
# doclist (vsechny adresy v Praze, ~40 ms), s indexem cte jen prvnich LIMIT radku (~0,5 ms). Delsi slovo
# se proto hleda jako nejdelsi indexovana predpona a cele se overi v Pythonu (Feature.score).
PREFIXES = (2, 3, 4, 6, 8)

# bunky mrizky pro prednost mist v okoli: token "zq<radek>x<sloupec>" v textu FTS (bunka ~22 x 22 km)
CELL_LAT = 0.2
CELL_LON = 0.3

KINDS = ("city", "stop", "street", "poi", "address")
K_CITY, K_STOP, K_STREET, K_POI, K_ADDRESS = range(5)
OSM_TYPES = "NWR"
COUNTRY_NAMES = {
    "CZ": {"default": "Česko", "cs": "Česko", "sk": "Česko", "en": "Czechia", "de": "Tschechien",
           "fr": "Tchéquie", "pl": "Czechy", "uk": "Чехія", "ru": "Чехия", "hu": "Csehország"},
    "SK": {"default": "Slovensko", "cs": "Slovensko", "sk": "Slovensko", "en": "Slovakia", "de": "Slowakei",
           "fr": "Slovaquie", "pl": "Słowacja", "uk": "Словаччина", "ru": "Словакия", "hu": "Szlovákia"},
}
PLACE_TYPES = {"city": "city", "town": "city", "village": "city", "suburb": "district",
               "quarter": "district", "neighbourhood": "district", "borough": "district"}


# ---- text (sdileno se sestavenim databaze) -------------------------------------------------------
_SPECIAL = str.maketrans({"ß": "ss", "ł": "l", "đ": "d", "ø": "o", "æ": "ae", "œ": "oe", "ı": "i",
                          "ŀ": "l", "þ": "th", "ð": "d"})


def fold(text):
    """Mala pismena bez diakritiky (jako tokenizer FTS5 unicode61 remove_diacritics 2)."""
    s = unicodedata.normalize("NFKD", str(text or "").lower().translate(_SPECIAL))
    return "".join(c for c in s if not unicodedata.combining(c))


_WORD = re.compile(r"[^\W_]+")


def tokens(text):
    return _WORD.findall(fold(text))


def cell_of(lat, lon):
    return int(math.floor(lat / CELL_LAT)) + 500, int(math.floor(lon / CELL_LON)) + 1000


def cell_token(r, c):
    return f"zq{r}x{c}"


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


# ---- hledani --------------------------------------------------------------------------------------
class Query:
    def __init__(self, q, lat=None, lon=None, limit=DEFAULT_LIMIT, lang="default"):
        self.text = " ".join(str(q or "").split())[:MAX_Q]
        self.toks = tokens(self.text)[:MAX_TOKENS]
        self.lat, self.lon = lat, lon
        self.limit = max(1, min(MAX_LIMIT, int(limit)))
        self.lang = lang if re.fullmatch(r"[a-z]{2}", lang or "") else "default"

    @property
    def center(self):
        return None if self.lat is None or self.lon is None else (self.lat, self.lon)


class Searcher:
    """Hledani nad databazi jen pro cteni; jedno spojeni na vlakno (sqlite3 neni sdileny mezi vlakny)."""

    def __init__(self, path, mmap_mb=0, cache_mb=8):
        self.path = path
        self.mmap_mb = mmap_mb
        self.cache_mb = cache_mb
        self.local = threading.local()
        self.generation = 0
        self.ident = self._ident()
        self.meta = {}
        self.conn()          # otevre a overi hned pri startu

    def _ident(self):
        try:
            st = os.stat(self.path)                      # pres symlink current -> vydani
            return (st.st_dev, st.st_ino, st.st_mtime_ns)
        except OSError:
            return None

    def check_reload(self):
        """Volano obcas z hlavniho vlakna: novy soubor databaze -> vlakna si otevrou novy."""
        ident = self._ident()
        if ident and ident != self.ident:
            self.ident = ident
            self.generation += 1
            return True
        return False

    def conn(self):
        loc = self.local
        if getattr(loc, "db", None) is not None and loc.gen == self.generation:
            return loc.db
        if getattr(loc, "db", None) is not None:
            loc.db.close()
        uri = "file:" + urllib.parse.quote(os.path.realpath(self.path)) + "?mode=ro&immutable=1"
        db = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA query_only=1")
        db.execute(f"PRAGMA cache_size=-{int(self.cache_mb) * 1024}")
        db.execute(f"PRAGMA mmap_size={int(self.mmap_mb) * 1024 * 1024}")
        db.execute("PRAGMA temp_store=MEMORY")
        self.meta = dict(db.execute("SELECT k, v FROM meta"))
        if self.meta.get("schema") != "1":
            raise RuntimeError("unsupported database schema")
        self.prefixes = tuple(sorted(int(p) for p in (self.meta.get("prefix") or "2 3 4").split()))
        loc.db, loc.gen = db, self.generation
        loc.strings = {}
        loc.tags = dict((i, (k, v)) for i, k, v in db.execute("SELECT id, k, v FROM tag"))
        return db

    def _string(self, db, ids):
        cache = self.local.strings
        need = [i for i in ids if i and i not in cache]
        if need:
            if len(cache) > 20000:
                cache.clear()
            for i, v in db.execute(f"SELECT id, v FROM str WHERE id IN ({','.join('?' * len(need))})", need):
                cache[i] = v

    def search(self, query):
        if not any(len(t) >= 2 for t in query.toks):
            return []
        db = self.conn()
        deadline = time.monotonic() + QUERY_BUDGET
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
        try:
            return self._search(db, query)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e):
                return []
            raise
        finally:
            db.set_progress_handler(None, 0)

    def _search(self, db, query):
        prefixes = self.prefixes
        terms = []
        for t in query.toks:
            if len(t) >= prefixes[0]:
                t = t[:max(p for p in prefixes if p <= len(t))]
                if t not in terms:
                    terms.append(t)
        match = " AND ".join(f'"{t}"*' for t in terms)
        ids = [r[0] for r in db.execute("SELECT rowid FROM fts WHERE fts MATCH ? LIMIT ?", (match, CANDIDATES))]
        if query.center:
            r0, c0 = cell_of(*query.center)
            near = " OR ".join(cell_token(r0 + dr, c0 + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
            seen = set(ids)
            ids += [r[0] for r in db.execute("SELECT rowid FROM fts WHERE fts MATCH ? LIMIT ?",
                                             (f"({match}) AND ({near})", CANDIDATES)) if r[0] not in seen]
        if not ids:
            return []
        rows = db.execute("SELECT id, kind, name, names, alt, street, hn, postcode, city, district, region, "
                          "country, lat, lon, osm, tag, imp FROM feat WHERE id IN (%s)" % ",".join(map(str, ids)))
        rows = rows.fetchall()
        self._string(db, [i for r in rows for i in (r[5], r[8], r[9], r[10])])
        strings = self.local.strings
        scored = []
        qtext = " ".join(query.toks)
        for r in rows:
            f = Feature(r, strings, self.local.tags)
            s = f.score(query.toks, qtext, query.center)
            if s is not None:
                scored.append((-s, f.id, f))
        scored.sort(key=lambda t: (t[0], t[1]))
        out = []
        for _s, _i, f in scored:
            if not any(f.same(g) for g in out):
                out.append(f)
                if len(out) >= query.limit:
                    break
        return [f.geojson(query.lang) for f in out]


class Feature:
    __slots__ = ("id", "kind", "name", "names", "alt", "street", "hn", "postcode", "city", "district",
                 "region", "country", "lat", "lon", "osm", "key", "value", "imp", "_fname")

    def __init__(self, r, strings, tags):
        (self.id, self.kind, self.name, names, self.alt, street, self.hn, self.postcode, city, district,
         region, self.country, lat, lon, self.osm, tag, imp) = r
        self.names = json.loads(names) if names else {}
        self.street = strings.get(street, "") if street else ""
        self.city = strings.get(city, "") if city else ""
        self.district = strings.get(district, "") if district else ""
        self.region = strings.get(region, "") if region else ""
        self.lat, self.lon = lat / 1e6, lon / 1e6
        self.key, self.value = tags.get(tag, ("", ""))
        self.imp = imp / 1000.0
        self._fname = None

    def display_name(self, lang="default"):
        if self.kind == K_ADDRESS:
            return " ".join(v for v in (self.street, self.hn) if v)
        return self.names.get(lang) or self.name or ""

    def score(self, toks, qtext, center):
        """Vyssi = lepsi. None = neodpovida (FTS hledalo jen zkracenou predponu nebo jednopismenne slovo)."""
        name = fold(self.display_name())
        variants = [name] + ([v for v in self.alt.split("|") if v] if self.alt else [])
        name_words = set()
        for v in variants:
            name_words.update(_WORD.findall(v))
        ctx_words = set(_WORD.findall(fold(" ".join((self.city, self.district, self.street, self.hn or "",
                                                         self.region)))))
        in_name = 0
        for t in toks:
            if any(w.startswith(t) for w in name_words):
                in_name += 1
            elif not any(w.startswith(t) for w in ctx_words):
                return None              # FTS hledalo jen predponu slova (nebo jednopismenne slovo vubec)
        s = 0.0
        if any(v.startswith(qtext) for v in variants):
            s += 3.0
            if any(v == qtext for v in variants):
                s += 0.5
        elif in_name == len(toks):
            s += 2.0
        elif in_name:
            s += 1.0 * in_name / len(toks)
        # cislo domu: "vodickova 30" -> adresa s cislem 30 (nebo .../30) pred ostatnimi cisly
        if self.kind == K_ADDRESS and self.hn:
            parts = _WORD.findall(fold(self.hn))
            nums = [t for t in toks if t[0].isdigit()]
            if nums and all(any(p == t for p in parts) for t in nums):
                s += 0.8
            elif nums and not all(any(p.startswith(t) for p in parts) for t in nums):
                s -= 0.5
        s += 2.0 * self.imp
        if center:
            d = distance_km(center[0], center[1], self.lat, self.lon)
            s -= 0.6 * math.log10(1.0 + d)
        return s

    def same(self, other):
        if self.kind != other.kind or fold(self.display_name()) != fold(other.display_name()):
            return False
        return distance_km(self.lat, self.lon, other.lat, other.lon) < 0.3

    def geojson(self, lang):
        p = {"osm_type": OSM_TYPES[self.osm & 3], "osm_id": self.osm >> 2,
             "osm_key": self.key, "osm_value": self.value}
        if self.kind == K_ADDRESS:
            p["type"] = "house"
        elif self.kind == K_CITY:
            p["type"] = PLACE_TYPES.get(self.value, "locality")
        elif self.kind == K_STREET:
            p["type"] = "street"
        else:
            p["type"] = "house" if self.kind == K_POI else "other"
        name = self.display_name(lang)
        if self.kind != K_ADDRESS and name:
            p["name"] = name
        if self.kind in (K_ADDRESS, K_POI) and self.street:
            p["street"] = self.street
        if self.hn:
            p["housenumber"] = self.hn
        if self.postcode:
            p["postcode"] = self.postcode
        if self.kind != K_CITY:
            if self.city:
                p["city"] = self.city
            if self.district and self.district != self.city:
                p["district"] = self.district
        if self.region:
            p["state"] = self.region
        if self.country:
            names = COUNTRY_NAMES.get(self.country, {})
            p["country"] = names.get(lang) or names.get("default") or self.country
            p["countrycode"] = self.country
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(self.lon, 7),
                                                                                 round(self.lat, 7)]},
                "properties": p}


# ---- omezeni rychlosti ----------------------------------------------------------------------------
class RateLimiter:
    """Token bucket na adresu IP (jen v pameti, bez zapisu). Vola se z vlakna smycky asyncio."""

    def __init__(self, burst=RATE_BURST, per_s=RATE_PER_S, max_ips=RATE_MAX_IPS, clock=time.monotonic):
        self.burst, self.per_s, self.max_ips, self.clock = burst, per_s, max_ips, clock
        self.buckets = {}

    def allow(self, ip):
        now = self.clock()
        tokens, t = self.buckets.get(ip, (self.burst, now))
        tokens = min(self.burst, tokens + (now - t) * self.per_s)
        if len(self.buckets) >= self.max_ips and ip not in self.buckets:
            full = self.burst / self.per_s
            self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < full}
            if len(self.buckets) >= self.max_ips:
                self.buckets.clear()
        if tokens < 1:
            self.buckets[ip] = (tokens, now)
            return False
        self.buckets[ip] = (tokens - 1, now)
        return True


# ---- HTTP -----------------------------------------------------------------------------------------
REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
           408: "Request Timeout", 413: "Payload Too Large", 429: "Too Many Requests",
           431: "Request Header Fields Too Large", 500: "Internal Server Error", 503: "Service Unavailable"}
TRUSTED_PROXIES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def parse_float(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and lo <= x <= hi else None


class App:
    def __init__(self, searcher, limiter=None, workers=2):
        self.searcher = searcher
        self.limiter = limiter or RateLimiter()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="geocode")

    async def route(self, method, target, headers, peer):
        """-> (status, body bytes, extra headers)."""
        if method not in ("GET", "HEAD"):
            return 405, b'{"message":"method not allowed"}', {"Allow": "GET, HEAD"}
        path, _, qs = target.partition("?")
        if path in ("/health", "/geocode/health"):
            m = self.searcher.meta
            body = {"ok": True, "version": VERSION, "built": m.get("built"), "data": m.get("data"),
                    "features": int(m.get("features") or 0), "countries": m.get("countries")}
            return 200, json.dumps(body).encode(), {"Cache-Control": "no-store"}
        if path not in ("/api", "/api/", "/geocode/api", "/geocode/api/"):
            return 404, b'{"message":"not found"}', {}
        ip = client_ip(headers, peer)
        if not self.limiter.allow(ip):
            return 429, b'{"message":"too many requests"}', {"Retry-After": "1"}
        try:
            params = urllib.parse.parse_qs(qs, max_num_fields=20, strict_parsing=False)
        except ValueError:
            return 400, b'{"message":"bad query"}', {}
        q = (params.get("q") or [""])[0]
        if len(q) > MAX_Q:
            return 400, b'{"message":"q too long (max 100 characters)"}', {}
        try:
            limit = int((params.get("limit") or [DEFAULT_LIMIT])[0])
        except ValueError:
            return 400, b'{"message":"bad limit"}', {}
        lat = parse_float((params.get("lat") or [None])[0], -90, 90)
        lon = parse_float((params.get("lon") or [None])[0], -180, 180)
        query = Query(q, lat, lon, limit, (params.get("lang") or ["default"])[0])
        loop = asyncio.get_running_loop()
        try:
            feats = await loop.run_in_executor(self.pool, self.searcher.search, query)
        except Exception as e:                  # bez textu dotazu
            print(f"geocoder: search failed: {type(e).__name__}", file=sys.stderr, flush=True)
            return 500, b'{"message":"internal error"}', {}
        body = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False,
                          separators=(",", ":")).encode()
        return 200, body, {"Cache-Control": "public, max-age=600"}

    async def handle(self, reader, writer):
        peer = (writer.get_extra_info("peername") or ("", 0))[0]
        try:
            while True:
                try:
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), KEEPALIVE_S)
                except asyncio.IncompleteReadError:
                    return
                except asyncio.LimitOverrunError:
                    await self.respond(writer, 431, b'{"message":"headers too large"}', {}, False, "GET")
                    return
                except asyncio.TimeoutError:
                    return
                lines = head.decode("latin-1").split("\r\n")
                parts = lines[0].split(" ")
                if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
                    await self.respond(writer, 400, b'{"message":"bad request"}', {}, False, "GET")
                    return
                method, target, version = parts
                headers = {}
                for ln in lines[1:]:
                    if not ln:
                        continue
                    k, sep, v = ln.partition(":")
                    if not sep or not k or k != k.strip():
                        await self.respond(writer, 400, b'{"message":"bad header"}', {}, False, method)
                        return
                    headers[k.lower()] = v.strip()
                if "transfer-encoding" in headers or int(headers.get("content-length", "0") or 0) > 0:
                    await self.respond(writer, 413, b'{"message":"no request body allowed"}', {}, False, method)
                    return
                conn_hdr = headers.get("connection", "").lower()
                keep = (version == "HTTP/1.1" and "close" not in conn_hdr) or \
                       (version == "HTTP/1.0" and "keep-alive" in conn_hdr)
                status, body, extra = await self.route(method, target, headers, peer)
                await self.respond(writer, status, body, extra, keep, method)
                if not keep:
                    return
        except (ConnectionError, ValueError, OSError):
            return
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def respond(self, writer, status, body, extra, keep, method):
        hdr = [f"HTTP/1.1 {status} {REASONS.get(status, 'Error')}",
               "Content-Type: application/json; charset=utf-8",
               f"Content-Length: {len(body)}",
               "X-Content-Type-Options: nosniff",
               "Connection: " + ("keep-alive" if keep else "close")]
        hdr += [f"{k}: {v}" for k, v in extra.items()]
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode("latin-1") + (b"" if method == "HEAD" else body))
        await writer.drain()


def client_ip(headers, peer):
    """Za Caddy (spojeni z localhostu) je klient posledni polozka X-Forwarded-For (tu doplni Caddy)."""
    if peer in TRUSTED_PROXIES:
        xff = headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[-1].strip()[:64]
    return peer


async def serve(app, host, port, ready=None, stop=None):
    server = await asyncio.start_server(app.handle, host, port, limit=HEADER_LIMIT, backlog=256,
                                        reuse_address=True)
    if ready:
        ready(server.sockets[0].getsockname()[1])
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    async with server:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), 30)
            except asyncio.TimeoutError:
                if app.searcher.check_reload():
                    print("geocoder: database file changed, reopening", file=sys.stderr, flush=True)
    app.pool.shutdown(wait=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="LuxOS geocoder (typeahead place search)")
    ap.add_argument("--db", default=os.environ.get("GEOCODER_DB", "/var/lib/luxos-geocoder/current/geocoder.sqlite"))
    ap.add_argument("--bind", default=os.environ.get("GEOCODER_BIND", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("GEOCODER_PORT", "8765")))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("GEOCODER_WORKERS", "2")))
    ap.add_argument("--mmap-mb", type=int, default=int(os.environ.get("GEOCODER_MMAP_MB", "0")))
    ap.add_argument("--cache-mb", type=int, default=int(os.environ.get("GEOCODER_CACHE_MB", "8")))
    ap.add_argument("--query", help="one search on the command line (prints GeoJSON) and exit")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    a = ap.parse_args(argv)
    searcher = Searcher(a.db, a.mmap_mb, a.cache_mb)
    if a.query is not None:
        res = searcher.search(Query(a.query, a.lat, a.lon))
        print(json.dumps({"type": "FeatureCollection", "features": res}, ensure_ascii=False, indent=1))
        return 0
    m = searcher.meta
    print(f"geocoder: {m.get('features')} features, data {m.get('data')}, listening on {a.bind}:{a.port}",
          file=sys.stderr, flush=True)
    asyncio.run(serve(App(searcher, workers=max(1, min(8, a.workers))), a.bind, a.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
