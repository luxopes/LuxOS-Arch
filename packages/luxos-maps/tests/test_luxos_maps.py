#!/usr/bin/env python3
"""LuxOS Mapy - testy dlazdic, mezipameti, hledani, tras, MHD, okoli, nahledu trasy, odkazu geo:,
rozhrani --json a okna.

    python3 -m unittest packages/luxos-maps/tests/test_luxos_maps.py -v
    (okno jen pod xvfb-run s vlastnim XDG_RUNTIME_DIR, viz scripts/check-titlebars.sh)

Zadny skutecny pozadavek: dlazdice OSM, Nominatim, routing.openstreetmap.de, ipinfo.io, Transitous
a Overpass nahrazuje mistni falesny server HTTP. Fixtures (tests/fixtures) jsou ulozene odpovedi skutecnych
sluzeb z 2026-10-26: dlazdice 0/0/0 (© OpenStreetMap contributors, CC BY-SA), hledani "Karlovo namesti
Praha" a trasa Staromestske namesti -> Thunovska autem a pesky (© OpenStreetMap contributors, ODbL),
spojeni MHD Karlovo namesti -> Prazsky hrad (transitous-plan.json) a odjezdy z Karlova namesti
(transitous-stoptimes.json; Transitous, data PID). transitous-*-sample.json a overpass-cafes.json jsou
vzorky z testu mobilni LuxAI (OpenStreetMapClientTest; plan doplneny o spojeni s prestupem a zrusenym
spojem). overpass-public-transport.json je umely (Overpass byl pri tvorbe fixtures pretizeny, 502):
schema odpovedi Overpass, nazvy, souradnice a nastupiste zastavek ze skutecne odpovedi Transitous.
photon-*.json jsou odpovedi Photonu (photon.komoot.io, 2026-10-28, © OpenStreetMap contributors, ODbL)
na "karlovo nam", "vodickova 30" a "mustek" u Prahy. transitous-plan-long.json je umele dlouhe spojeni
(Ex1 (IC 547) > M1 (Os 3751) > tramvaj 5, schema MOTIS) pro rozlozeni panelu, nav-tracks.json umele stopy
telefonu (fix po 1-5 s, presnost 5-50 m, korelovana chyba GPS) podel route-foot/route-car s odbockami.
Ostatni dlazdice kresli server sam (svetla mrizka s cislem dlazdice). Snimky okna do LUXOS_TEST_SHOTS.
"""
import http.server
import importlib.machinery
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
FIXTURES = os.path.join(HERE, "fixtures")
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, FILES)
sys.path.insert(1, os.path.join(ROOT, "luxos-i18n", "files"))

UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
LANGS = ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")


def fixture(name, binary=False):
    with open(os.path.join(FIXTURES, name), "rb" if binary else "r") as f:
        return f.read() if binary else json.load(f)


def synthetic_tile(z, x, y):
    import cairo
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 256, 256)
    cr = cairo.Context(s)
    cr.set_source_rgb(0.95, 0.94, 0.91)
    cr.paint()
    cr.set_source_rgb(0.67, 0.83, 0.87) if (x + y) % 7 == 0 else cr.set_source_rgb(0.8, 0.9, 0.75)
    cr.rectangle(40, 40, 90, 70)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.set_line_width(8)
    for v in (64, 192):
        cr.move_to(v, 0)
        cr.line_to(v, 256)
        cr.move_to(0, v)
        cr.line_to(256, v)
    cr.stroke()
    cr.set_source_rgb(0.85, 0.83, 0.8)
    cr.set_line_width(1)
    cr.rectangle(0.5, 0.5, 255, 255)
    cr.stroke()
    cr.set_source_rgb(0.5, 0.5, 0.5)
    cr.select_font_face("Sans")
    cr.set_font_size(13)
    cr.move_to(80, 140)
    cr.show_text(f"{z}/{x}/{y}")
    buf = io.BytesIO()
    s.write_to_png(buf)
    return buf.getvalue()


class FakeServer:
    """Falesne dlazdice (/tiles), Nominatim (/search, /reverse), OSRM (/routed-*), ipinfo (/ip),
    Transitous (/transitous/plan, /transitous/stoptimes), Overpass (/overpass), Photon (/photon/api/)
    a geocoder LuxOS (/geocode/api; geocode = "ok", "slow", "fail", "empty", "one")."""

    def __init__(self):
        self.requests = []
        self.raw = []
        self.headers = []
        self.ports = []                   # klientsky port kazdeho pozadavku (trvala spojeni)
        self.busy = False
        self.fail = False
        self.delay = 0.0
        self.geocode = "ok"
        self.drop_idle = False            # po odpovedi zavrit spojeni bez ohlaseni (stare keep-alive)
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.tiles = {}
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def send(self, code, body=b"", ctype="application/json", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                with server.lock:
                    server.requests.append((url.path, q))
                    server.raw.append(url.query)
                    server.headers.append(dict(self.headers))
                    server.ports.append(self.client_address[1])
                    server.active += 1
                    server.max_active = max(server.max_active, server.active)
                try:
                    if server.delay:
                        time.sleep(server.delay)
                    self.route(url, q)
                finally:
                    with server.lock:
                        server.active -= 1

            def route(self, url, q):
                if server.fail:
                    self.send(503, b"{}")
                    return
                m = re.match(r"^/tiles/(\d+)/(\d+)/(\d+)\.png$", url.path)
                if m:
                    z, x, y = (int(v) for v in m.groups())
                    etag = f'"t{z}-{x}-{y}"'
                    if self.headers.get("If-None-Match") == etag:
                        self.send(304, extra={"ETag": etag, "Cache-Control": "max-age=86400"})
                        return
                    if z > 19 or x >= 2 ** z or y >= 2 ** z:
                        self.send(404, b"")
                        return
                    if (z, x, y) == (0, 0, 0):
                        body = fixture("tile-0-0-0.png", True)
                    else:
                        body = server.tiles.get((z, x, y)) or synthetic_tile(z, x, y)
                        server.tiles[(z, x, y)] = body
                    self.send(200, body, "image/png", {"ETag": etag, "Cache-Control":
                                                       "max-age=86400, stale-while-revalidate=604800"})
                    return
                if url.path == "/search":
                    text = q.get("q", "").lower()
                    body = fixture("search-karlovo.json") if "karlovo" in text else []
                    if text.startswith("náměstí"):      # vic ruznych mist (odvozeno z fixture)
                        base = fixture("search-karlovo.json")[0]
                        body = []
                        for name, lat, lon in (("Staroměstské náměstí", "50.0875", "14.4208"),
                                               ("Václavské náměstí", "50.0815", "14.4280"),
                                               ("Karlovo náměstí", "50.0757", "14.4199")):
                            body.append(dict(base, name=name, lat=lat, lon=lon,
                                             address=dict(base["address"], square=name),
                                             boundingbox=None, osm_id=hash(name) % 100000))
                    self.send(200, json.dumps(body).encode())
                    return
                if url.path == "/geocode/api":
                    mode = server.geocode
                    if mode == "slow":
                        time.sleep(2.0)
                    if mode == "fail":
                        self.send(503, b"{}")
                        return
                    text = lm.fold(q.get("q", ""))
                    name = next((f for k, f in (("karl", "photon-karlovo.json"), ("vodi", "photon-vodickova-30.json"),
                                                ("must", "photon-mustek.json")) if k in text), None)
                    body = fixture(name) if name and mode != "empty" else {"type": "FeatureCollection",
                                                                            "features": []}
                    body["features"] = body["features"][:1 if mode == "one" else int(q.get("limit", 10))]
                    self.send(200, json.dumps(body).encode())
                    if server.drop_idle:
                        self.close_connection = True
                    return
                if url.path == "/photon/api/":
                    text = lm.fold(q.get("q", ""))
                    name = next((f for k, f in (("karl", "photon-karlovo.json"), ("vodi", "photon-vodickova-30.json"),
                                                ("must", "photon-mustek.json")) if k in text), None)
                    body = fixture(name) if name else {"type": "FeatureCollection", "features": []}
                    body["features"] = body["features"][:int(q.get("limit", 10))]
                    self.send(200, json.dumps(body).encode())
                    return
                if url.path == "/reverse":
                    item = dict(fixture("search-karlovo.json")[0])
                    item.update(lat=q.get("lat"), lon=q.get("lon"))
                    self.send(200, json.dumps(item).encode())
                    return
                m = re.match(r"^/routed-(car|bike|foot)/route/v1/driving/([-\d.,;]+)$", url.path)
                if m:
                    if m.group(2).startswith("0.000000,0.000000"):
                        self.send(400, json.dumps({"code": "NoRoute", "message": "Impossible route"}).encode())
                        return
                    name = "route-foot.json" if m.group(1) == "foot" else "route-car.json"
                    self.send(200, json.dumps(fixture(name)).encode())
                    return
                if url.path == "/ip":
                    self.send(200, json.dumps({"city": "Praha", "loc": "50.0880,14.4208",
                                               "country": "CZ"}).encode())
                    return
                if url.path.startswith(("/transitous/", "/overpass")) and server.busy:
                    self.send(502, b"# 502 Gateway Timeout\n\nThis Overpass API server is currently at capacity.",
                              "text/plain")
                    return
                if url.path == "/transitous/plan":
                    frm = q.get("fromPlace", "")
                    if frm.startswith("0.000000"):
                        body = {"itineraries": [], "direct": []}
                    elif frm.startswith("50.087500"):
                        body = fixture("transitous-plan-sample.json")
                    elif frm.startswith("50.083500"):
                        body = fixture("transitous-plan-long.json")
                    else:
                        body = fixture("transitous-plan.json")
                    body["itineraries"] = body["itineraries"][:int(q.get("numItineraries", 5))]
                    self.send(200, json.dumps(body).encode())
                    return
                if url.path == "/transitous/stoptimes":
                    if q.get("center", "").startswith("50.087600"):
                        body = fixture("transitous-stoptimes-sample.json")
                    else:
                        body = fixture("transitous-stoptimes.json")
                        if q.get("stopId"):
                            body["stopTimes"] = [st for st in body["stopTimes"]
                                                 if st["place"].get("stopId") == q["stopId"]]
                    body["stopTimes"] = body["stopTimes"][:int(q.get("n", 20))]
                    self.send(200, json.dumps(body).encode())
                    return
                if url.path == "/overpass":
                    data = q.get("data", "")
                    if '["public_transport"]' in data:
                        body = fixture("overpass-public-transport.json")
                    elif '"cafe"' in data or '["name"~' in data:
                        body = fixture("overpass-cafes.json")
                    else:
                        body = {"elements": []}
                    self.send(200, json.dumps(body).encode())
                    return
                self.send(404, b"{}")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        httpd = self.httpd

        def handle_error(request, client_address):
            # naseptavac zavre spojeni zruseneho dotazu: to neni chyba testu
            if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                http.server.ThreadingHTTPServer.handle_error(httpd, request, client_address)
        self.httpd.handle_error = handle_error
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def last_raw(self, prefix):
        """Dotaz (query) posledniho pozadavku na cestu prefix (okno mezitim stahuje dlazdice)."""
        with self.lock:
            return next((r for (p, _q), r in zip(reversed(self.requests), reversed(self.raw))
                         if p.startswith(prefix)), "")

    def last_q(self, prefix):
        with self.lock:
            return next((q for p, q in reversed(self.requests) if p.startswith(prefix)), {})

    def count(self, prefix):
        with self.lock:
            return sum(1 for p, _q in self.requests if p.startswith(prefix))

    def reset(self):
        with self.lock:
            self.requests.clear()
            self.raw.clear()
            self.headers.clear()
            self.ports.clear()
            self.max_active = 0
        self.geocode = "ok"
        self.drop_idle = False
        self.fail = False
        self.busy = False
        self.delay = 0.0

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SERVER = FakeServer()
TMP = tempfile.mkdtemp(prefix="luxos-maps-test-")
os.environ.update({
    "LUXOS_MAPS_TILES": SERVER.base + "/tiles/{z}/{x}/{y}.png",
    "LUXOS_MAPS_SEARCH": SERVER.base + "/search",
    "LUXOS_MAPS_REVERSE": SERVER.base + "/reverse",
    "LUXOS_MAPS_ROUTE": SERVER.base + "/routed-{profile}/route/v1/driving/{coords}",
    "LUXOS_MAPS_IP": SERVER.base + "/ip",
    "LUXOS_MAPS_TRANSIT_PLAN": SERVER.base + "/transitous/plan",
    "LUXOS_MAPS_STOPTIMES": SERVER.base + "/transitous/stoptimes",
    "LUXOS_MAPS_OVERPASS": SERVER.base + "/overpass",
    "LUXOS_MAPS_SUGGEST": SERVER.base + "/photon/api/",
    "LUXOS_MAPS_GEOCLUE": "0",
    "LUXOS_MAPS_PHONE": "0",          # poloha z telefonu jen v TestPhoneLocation (soukroma sbernice)
    "LUXOS_MAPS_RATE": "0.05",
    "LUXOS_I18N_DIR": os.path.join(ROOT, "luxos-i18n", "files"),
    "XDG_CACHE_HOME": os.path.join(TMP, "cache"),
    "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
    "LANG": os.environ.get("LUXOS_TEST_LANG") or "en_GB.UTF-8",
})
for _var in ("LC_ALL", "LC_MESSAGES", "LC_MEASUREMENT"):
    os.environ.pop(_var, None)

import luxos_maps as lm  # noqa: E402


def tearDownModule():
    SERVER.close()
    shutil.rmtree(TMP, ignore_errors=True)


def clean_state():
    shutil.rmtree(os.path.join(TMP, "cache"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP, "config"), ignore_errors=True)
    lm._route_cache.clear()
    SERVER.reset()


class TestGeo(unittest.TestCase):
    def test_world_roundtrip(self):
        for lat, lon in ((50.0875, 14.4208), (-33.86, 151.2), (0, 0), (85, -179.9)):
            x, y = lm.to_world(lat, lon)
            la, lo = lm.from_world(x, y)
            self.assertAlmostEqual(la, lat, places=6)
            self.assertAlmostEqual(lo, lon, places=6)
        self.assertEqual(lm.to_world(0, 0), (0.5, 0.5))
        self.assertAlmostEqual(lm.meters_per_pixel(0, 0), 156543.03, places=1)

    def test_zoom_for_bbox(self):
        z = lm.zoom_for_bbox(50.07, 50.10, 14.39, 14.43, 1000, 700)
        self.assertTrue(12 < z < 16, z)
        self.assertEqual(lm.zoom_for_bbox(50.0, 50.0, 14.0, 14.0, 1000, 700), 17)

    def test_geo_uri(self):
        p = lm.parse_geo_uri("geo:50.0875,14.4208")
        self.assertEqual((p["lat"], p["lon"], p["zoom"], p["query"]), (50.0875, 14.4208, None, None))
        p = lm.parse_geo_uri("geo:50.0875,14.4208,250;u=30?z=17")
        self.assertEqual(p["zoom"], 17)
        p = lm.parse_geo_uri("GEO:50.0875,14.4208;crs=wgs84?z=40")
        self.assertEqual(p["zoom"], lm.MAX_ZOOM)
        self.assertIsNone(lm.parse_geo_uri("geo:50,14;crs=epsg:3857"))
        self.assertIsNone(lm.parse_geo_uri("geo:95,14"))
        self.assertIsNone(lm.parse_geo_uri("geo:abc"))
        self.assertIsNone(lm.parse_geo_uri("https://example.com"))
        p = lm.parse_geo_uri("geo:0,0?q=Karlovo%20n%C3%A1m%C4%9Bst%C3%AD")
        self.assertEqual((p["lat"], p["query"]), (None, "Karlovo náměstí"))
        p = lm.parse_geo_uri("geo:0,0?q=50.1,14.2(Doma)")
        self.assertEqual((p["lat"], p["lon"], p["label"]), (50.1, 14.2, "Doma"))
        uri = lm.geo_uri(50.0875, 14.4208, 16, "Staroměstské náměstí")
        self.assertTrue(uri.startswith("geo:50.0875,14.4208?z=16&q="))
        back = lm.parse_geo_uri(uri)
        self.assertEqual((back["lat"], back["lon"], back["zoom"], back["label"]),
                         (50.0875, 14.4208, 16, "Staroměstské náměstí"))

    def test_coords(self):
        self.assertEqual(lm.parse_coords("50.0875, 14.4208"), (50.0875, 14.4208, None))
        self.assertEqual(lm.parse_coords("-33.8 151.2"), (-33.8, 151.2, None))
        self.assertIsNone(lm.parse_coords("Praha"))
        self.assertIsNone(lm.parse_coords("120, 14"))
        self.assertEqual(lm.format_coords(50.0875, 14.4208), "50.08750, 14.42080")

    def test_format(self):
        self.assertEqual(lm.format_distance(42, lang="en"), "42 m")
        self.assertEqual(lm.format_distance(844, lang="en"), "840 m")
        self.assertEqual(lm.format_distance(2415.3, lang="en"), "2.4 km")
        self.assertEqual(lm.format_distance(2415.3, lang="cs"), "2,4 km")
        self.assertEqual(lm.format_distance(123456, lang="cs"), "123 km")
        self.assertEqual(lm.format_distance(2415.3, imperial=True, lang="en"), "1.5 mi")
        self.assertEqual(lm.format_distance(30, imperial=True, lang="en"), "100 ft")
        self.assertEqual(lm.format_duration(20), "1 min")
        self.assertEqual(lm.format_duration(384.4), "6 min")
        self.assertEqual(lm.format_duration(3600), "1 h")
        self.assertEqual(lm.format_duration(3725), "1 h 2 min")
        self.assertEqual(lm.locale_country({"LANG": "en_US.UTF-8"}), "US")
        self.assertEqual(lm.lang_code({"LANG": "cs_CZ.UTF-8"}), "cs")


class TestConfig(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_defaults_and_invalid(self):
        cfg = lm.load_config()
        self.assertEqual((cfg["favorites"], cfg["view"], cfg["appearance"], cfg["mode"], cfg["location_consent"]),
                         ([], None, "auto", "car", False))
        os.makedirs(os.path.dirname(lm.config_path()), exist_ok=True)
        with open(lm.config_path(), "w") as f:
            json.dump({"favorites": [{"name": "A", "lat": 50, "lon": 14}, {"name": "B", "lat": 99, "lon": 1}, 5],
                       "view": {"lat": 50, "lon": 14, "zoom": 12}, "appearance": "neon", "mode": "plane",
                       "location_consent": "yes", "tile_url": "file:///etc/passwd",
                       "search_url": "https://nominatim.example.org/search"}, f)
        cfg = lm.load_config()
        self.assertEqual([f["name"] for f in cfg["favorites"]], ["A"])
        self.assertEqual(cfg["view"]["zoom"], 12)
        self.assertEqual((cfg["appearance"], cfg["mode"], cfg["location_consent"]), ("auto", "car", False))
        self.assertNotIn("tile_url", cfg)
        self.assertEqual(lm.service_url(cfg, "search_url", "LUXOS_MAPS_NONE", lm.SEARCH_URL),
                         "https://nominatim.example.org/search")
        with open(lm.config_path(), "w") as f:
            f.write("{broken")
        self.assertEqual(lm.load_config()["favorites"], [])


class TestSearchAndRoute(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_search_parse_cache_and_headers(self):
        res = lm.search("Karlovo náměstí Praha", "cs", near=(50.0, 50.2, 14.3, 14.6))
        self.assertEqual(res[0]["name"], "Karlovo náměstí")
        self.assertIn("Praha", res[0]["address"])
        self.assertEqual(len(res), 1)       # namesti jako plocha i 4 ulice = jedno misto
        self.assertEqual(len(res[0]["bbox"]), 4)
        path, q = SERVER.requests[-1]
        self.assertEqual((path, q["format"], q["accept-language"]), ("/search", "jsonv2", "cs"))
        self.assertEqual(q["viewbox"], "14.3,50.2,14.6,50.0")
        self.assertTrue(SERVER.headers[-1]["User-Agent"].startswith("LuxOS-Maps/"))
        # stejny dotaz znovu: z mezipameti, bez pozadavku
        lm.search("Karlovo  náměstí Praha", "cs", near=(50.0, 50.2, 14.3, 14.6))
        self.assertEqual(SERVER.count("/search"), 1)
        self.assertEqual(lm.search("x", "cs"), [])
        self.assertEqual(SERVER.count("/search"), 1)
        self.assertEqual(lm.search("nic takoveho", "cs"), [])

    def test_rate_limit(self):
        os.environ["LUXOS_MAPS_RATE"] = "0.4"
        try:
            t0 = time.time()
            lm.search("karlovo 1", "cs")
            lm.search("karlovo 2", "cs")
            lm.reverse(50.0757, 14.4199, "cs")
            self.assertGreaterEqual(time.time() - t0, 0.75)    # 3 pozadavky = aspon 2 intervaly
        finally:
            os.environ["LUXOS_MAPS_RATE"] = "0.05"

    def test_reverse(self):
        p = lm.reverse(50.0757, 14.4199, "cs")
        self.assertEqual(p["name"], "Karlovo náměstí")
        self.assertEqual(SERVER.requests[-1][1]["zoom"], "18")
        lm.reverse(50.0757, 14.4199, "cs")
        self.assertEqual(SERVER.count("/reverse"), 1)

    def test_polyline(self):
        self.assertEqual(lm.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@"),
                         [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])
        with self.assertRaises(ValueError):
            lm.decode_polyline("_p~iF~ps|U_")

    def test_parse_route(self):
        r = lm.parse_route(fixture("route-car.json"), "car")
        self.assertAlmostEqual(r["distance"], 2415.3)
        self.assertGreater(len(r["points"]), 100)
        texts = [s["text"] for s in r["steps"]]
        self.assertEqual(texts[0], "Depart")
        self.assertEqual(texts[-1], "Destination is on the right")
        self.assertIn("Enter the roundabout and take exit %s", texts)
        self.assertNotIn("exit roundabout", [s["type"] for s in r["steps"]])
        rb = r["steps"][texts.index("Enter the roundabout and take exit %s")]
        self.assertEqual(lm.step_instruction(rb), "Enter the roundabout and take exit 1")
        self.assertAlmostEqual(rb["distance"], 38.9 + 245.9, places=1)
        with self.assertRaises(lm.MapsError):
            lm.parse_route({"code": "NoRoute"}, "car")

    def test_route_modes_and_cache(self):
        a, b = {"lat": 50.0875, "lon": 14.4208}, {"lat": 50.0903, "lon": 14.4005}
        r = lm.route(a, b, "car")
        self.assertEqual(r["mode"], "car")
        path, q = SERVER.requests[-1]
        self.assertTrue(path.startswith("/routed-car/route/v1/driving/14.420800,50.087500;14.400500,50.090300"))
        self.assertEqual((q["steps"], q["overview"], q["geometries"]), ("true", "full", "polyline"))
        lm.route(a, b, "car")
        self.assertEqual(SERVER.count("/routed-"), 1)
        w = lm.route(a, b, "walk")
        self.assertTrue(SERVER.requests[-1][0].startswith("/routed-foot/"))
        self.assertGreater(w["duration"], r["duration"])
        lm.route(a, b, "bike")
        self.assertTrue(SERVER.requests[-1][0].startswith("/routed-bike/"))
        with self.assertRaises(lm.MapsError) as cm:
            lm.route({"lat": 0, "lon": 0}, b, "car")
        self.assertIn("NoRoute", str(cm.exception))
        with self.assertRaises(lm.MapsError):
            lm.route(a, b, "plane")


def age_api_cache(seconds):
    """Odpovedi Transitous/Overpass v mezipameti o tolik sekund starsi."""
    d = os.path.join(TMP, "cache", "luxos", "maps", "api")
    for n in os.listdir(d):
        with open(os.path.join(d, n)) as f:
            data = json.load(f)
        data["t"] -= seconds
        with open(os.path.join(d, n), "w") as f:
            json.dump(data, f)


class TestTransit(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_plan_request_and_parse(self):
        a, b = {"lat": 50.0757, "lon": 14.4199}, {"lat": 50.0905, "lon": 14.3995}
        res = lm.transit_plan(a, b)
        raw = SERVER.raw[-1]
        self.assertIn("fromPlace=50.075700%2C14.419900", raw)
        self.assertIn("transitModes=TRANSIT&directModes=&detailedLegs=true", raw)
        self.assertIn("maxTransfers=3", raw)
        self.assertNotIn("time=", raw)
        self.assertTrue(SERVER.headers[-1]["User-Agent"].startswith("LuxOS-Maps/"))
        self.assertEqual(res["timezone"], "Europe/Prague")
        its = res["itineraries"]
        self.assertEqual(len(its), 3)
        it = its[0]
        # 18:10Z = 19:10 v Praze (zimni cas), ne v pasmu pocitace
        self.assertEqual((it["departure_time"], it["arrival_time"], it["duration"], it["transfers"]),
                         ("19:10", "19:33", "23 min", 0))
        self.assertEqual(it["departure"], "2026-10-26T19:10:00+01:00")
        tram = it["legs"][1]
        self.assertEqual((tram["mode"], tram["mode_name"], tram["line"], tram["headsign"]),
                         ("TRAM", "Tram", "22", "Vypich"))
        self.assertEqual((tram["color"], tram["text_color"]), ("#7A0603", "#FFFFFF"))
        self.assertEqual((tram["delay_min"], tram["scheduled_departure_time"], tram["departure_time"]),
                         (1, "19:10", "19:11"))
        self.assertEqual((tram["from"]["platform"], tram["from"]["stop_id"]), ("C", "cz-PID_U237Z3P"))
        self.assertTrue(tram["realtime"])
        self.assertEqual(tram["operator"], "Pražská integrovaná doprava")
        self.assertGreater(tram["stops"], 2)
        self.assertEqual(it["legs"][0]["mode"], "WALK")
        self.assertFalse(it["legs"][0]["transit"])
        self.assertIn("Tram 22 toward Vypich", it["summary"])
        pts = lm.leg_points(tram)
        self.assertGreater(len(pts), 50)
        self.assertAlmostEqual(pts[0][0], 50.0759, places=3)
        # mezipamet: stejny dotaz bez dalsiho pozadavku, po PLAN_TTL znovu
        lm.transit_plan(a, b)
        self.assertEqual(SERVER.count("/transitous/plan"), 1)
        age_api_cache(lm.PLAN_TTL + 1)
        lm.transit_plan(a, b)
        self.assertEqual(SERVER.count("/transitous/plan"), 2)
        with self.assertRaises(lm.MapsError) as cm:
            lm.transit_plan({"lat": 0, "lon": 0}, b)
        self.assertEqual(str(cm.exception), "NoRoute")

    def test_mobile_sample_plan(self):
        # stejny vstup a ocekavani jako OpenStreetMapClientTest (mobilni LuxAI)
        when = lm.parse_user_time("2026-08-24T10:00:00+02:00")
        res = lm.transit_plan({"lat": 50.0875, "lon": 14.4213}, {"lat": 50.0755, "lon": 14.4378}, when,
                              max_transfers=2, limit=2)
        raw = SERVER.raw[-1]
        self.assertIn("time=2026-08-24T08%3A00%3A00Z", raw)
        self.assertIn("maxTransfers=2", raw)
        self.assertIn("arriveBy=false", raw)
        it = res["itineraries"][0]
        self.assertEqual(it["departure_time"], "10:01")
        self.assertEqual((it["legs"][1]["mode_name"], it["legs"][1]["line"], it["legs"][1]["headsign"]),
                         ("Metro", "A", "Skalka"))
        self.assertEqual(it["legs"][1]["departure_time"], "10:10")       # pasmo ze spojeni
        self.assertTrue(it["legs"][1]["realtime"])
        self.assertEqual(it["legs"][1]["color"], "#00A562")
        self.assertIn("Metro A toward Skalka", it["summary"])
        it2 = res["itineraries"][1]
        self.assertEqual(it2["transfers"], 1)
        self.assertTrue(it2["cancelled"])
        tram = it2["legs"][2]
        self.assertTrue(tram["cancelled"])
        self.assertEqual((tram["from"]["platform"], tram["from"]["scheduled_platform"]), ("B", "A"))
        self.assertTrue(tram["from"]["platform_changed"])
        self.assertIn("CANCELLED", it2["summary"])
        lm.transit_plan({"lat": 50.0875, "lon": 14.4213}, {"lat": 50.0755, "lon": 14.4378}, when, arrive_by=True)
        self.assertIn("arriveBy=true", SERVER.raw[-1])

    def test_times(self):
        dt = lm.parse_user_time("2026-08-24T10:00:00+02:00")
        self.assertEqual(lm.api_time(dt), "2026-08-24T08:00:00Z")
        self.assertEqual(lm.api_time(lm.parse_iso("2026-08-24T08:00:00Z")), "2026-08-24T08:00:00Z")
        self.assertIsNone(lm.parse_user_time(None))
        self.assertIsNone(lm.parse_user_time("now"))
        t = lm.parse_user_time("17:30")
        self.assertEqual((t.hour, t.minute), (17, 30))
        self.assertIsNotNone(t.tzinfo)
        for bad in ("25:00", "tomorrow", "2026-13-01T10:00"):
            with self.assertRaises(lm.MapsError):
                lm.parse_user_time(bad)
        self.assertEqual(lm.hhmm(lm.parse_iso("2026-01-10T12:00:00Z"), lm.zone("Europe/Prague")), "13:00")
        self.assertEqual(lm.hhmm(lm.parse_iso("2026-07-10T12:00:00Z"), lm.zone("Europe/Prague")), "14:00")
        self.assertEqual(lm.hhmm(lm.parse_iso("2026-07-10T12:00:00Z"), lm.zone("America/New_York")), "08:00")
        self.assertIsNotNone(lm.zone("Not/AZone"))

    def test_timetable_realtime(self):
        tt = lm.timetable(50.0759, 14.419612, radius=200, limit=20)
        raw = SERVER.raw[-1]
        for part in ("center=50.075900%2C14.419612", "radius=200", "exactRadius=true", "n=20",
                     "direction=LATER", "realtimeMode=REALTIME", "arriveBy=false"):
            self.assertIn(part, raw)
        rows = tt["stop_times"]
        self.assertEqual(len(rows), 20)
        self.assertEqual(tt["stops"], ["Karlovo náměstí", "Novoměstská radnice"])
        r = rows[6]
        self.assertEqual((r["time"], r["scheduled_time"], r["delay_min"], r["line"], r["headsign"], r["platform"]),
                         ("19:11", "19:10", 1, "22", "Vypich", "C"))
        self.assertEqual((r["mode_name"], r["color"], r["stop_id"]), ("Tram", "#7A0603", "cz-PID_U237Z3P"))
        self.assertTrue(r["realtime"])
        self.assertEqual(rows[2]["mode"], "BUS")
        self.assertEqual(rows[2]["color"], "#007DA8")
        # zastavka podle stopId
        tt = lm.timetable(stop_id="cz-PID_U237Z3P", limit=5)
        self.assertIn("stopId=cz-PID_U237Z3P", SERVER.raw[-1])
        self.assertNotIn("center=", SERVER.raw[-1])
        self.assertTrue(all(r["platform"] == "C" for r in tt["stop_times"]))
        # mezipamet 45 s; Obnovit (max_age=15) po 20 s stahne znovu
        n = SERVER.count("/transitous/stoptimes")
        lm.timetable(50.0759, 14.419612, radius=200, limit=20)
        self.assertEqual(SERVER.count("/transitous/stoptimes"), n)
        age_api_cache(20)
        lm.timetable(50.0759, 14.419612, radius=200, limit=20)
        self.assertEqual(SERVER.count("/transitous/stoptimes"), n)
        lm.timetable(50.0759, 14.419612, radius=200, limit=20, max_age=15)
        self.assertEqual(SERVER.count("/transitous/stoptimes"), n + 1)

    def test_mobile_sample_timetable(self):
        when = lm.parse_user_time("2026-08-24T10:00:00+02:00")
        tt = lm.timetable(50.0876, 14.4212, when, radius=200, limit=2)
        self.assertIn("time=2026-08-24T08%3A00%3A00Z", SERVER.raw[-1])
        a, b = tt["stop_times"]
        self.assertTrue(a["summary"].startswith("10:04 · 194 toward Florenc · Masná · +2 min"))
        self.assertIn("platform B (scheduled A)", a["summary"])
        self.assertEqual((a["delay_min"], a["platform_changed"], a["operator"]),
                         (2, True, "Pražská integrovaná doprava"))
        self.assertIn("17 toward Libuš · Staroměstská", b["summary"])
        self.assertTrue(b["cancelled"])
        self.assertIn("CANCELLED", b["summary"])
        self.assertIn("https://transitous.org/sources/", lm.TRANSIT_ATTRIBUTION)

    def test_busy_backoff(self):
        SERVER.busy = True
        with self.assertRaises(lm.BusyError):
            lm.timetable(50.0759, 14.419612)
        self.assertEqual(SERVER.count("/transitous/"), 1)
        SERVER.busy = False
        with self.assertRaises(lm.BusyError):          # pauza: pozadavek vubec neodejde
            lm.transit_plan({"lat": 50.0757, "lon": 14.4199}, {"lat": 50.0905, "lon": 14.3995})
        self.assertEqual(SERVER.count("/transitous/"), 1)
        os.utime(lm._backoff_path("transitous"), (time.time(), time.time() - 1))
        self.assertTrue(lm.transit_plan({"lat": 50.0757, "lon": 14.4199}, {"lat": 50.0905, "lon": 14.3995}))

    def test_rate_limit_shared(self):
        os.environ["LUXOS_MAPS_RATE"] = "0.4"
        try:
            t0 = time.time()
            lm.timetable(50.07, 14.41)
            lm.timetable(50.06, 14.41)
            lm.transit_plan({"lat": 50.0757, "lon": 14.4199}, {"lat": 50.0905, "lon": 14.3995})
            self.assertGreaterEqual(time.time() - t0, 0.75)
        finally:
            os.environ["LUXOS_MAPS_RATE"] = "0.05"

    def test_colors(self):
        self.assertEqual(lm.leg_color("TRAM", ""), "#E11D48")
        self.assertEqual(lm.leg_color("BUS", "00a562"), "#00A562")
        self.assertEqual(lm.leg_color("WALK", ""), "#64748B")
        self.assertEqual(lm.leg_color("XYZ", "bad"), "#0891B2")
        self.assertEqual(lm.text_color("#FFE000"), "#000000")
        self.assertEqual(lm.text_color("#7A0603"), "#FFFFFF")


class TestSearchViewbox(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_zoomed_in_viewbox_has_area(self):
        # QA: velke priblizeni (Karlstejn, ~1 km) - zaokrouhleny viewbox mel nulovou plochu
        # (jih == sever, zapad == vychod) a Nominatim vratil HTTP 400
        lm.search("Beroun", "cs", near=(49.925, 49.94, 14.17, 14.20))
        self.assertEqual(SERVER.requests[-1][1]["viewbox"], "14.1,50.0,14.2,49.9")
        lm.search("Beroun", "cs", near=(49.96, 49.97, 14.10, 14.10))
        self.assertEqual(SERVER.requests[-1][1]["viewbox"], "14.1,50.0,14.2,49.9")


class TestNearby(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_public_transport_merged(self):
        res = lm.nearby(50.0757, 14.4199, "public_transport", radius=300, limit=20)
        q = SERVER.requests[-1][1]["data"]
        self.assertEqual(q, '[out:json][timeout:20];'
                            'nwr(around:250,50.075700,14.419900)["public_transport"];out center 60;'
                            'nwr(around:300,50.075700,14.419900)["public_transport"];out center 60;')
        names = [p["name"] for p in res]
        self.assertEqual(names, ["Karlovo náměstí", "Novoměstská radnice"])     # nastupiste sloucena
        self.assertTrue(all(p["transit"] for p in res))
        self.assertTrue(lm.is_transit_place(res[0]))
        self.assertGreaterEqual(len(res[0]["platforms"]), 3)
        self.assertLess(res[0]["distance_m"], res[1]["distance_m"])
        self.assertTrue(res[0]["osm_url"].startswith("https://www.openstreetmap.org/node/"))
        lm.nearby(50.0757, 14.4199, "public_transport", radius=300, limit=20)
        self.assertEqual(SERVER.count("/overpass"), 1)

    def test_mobile_sample_name_query(self):
        # stejne jako mobilni test: razeni podle vzdalenosti, escapovany regularni vyraz
        res = lm.nearby(50.0875, 14.4213, name='Cafe "A.*"', radius=800)
        q = SERVER.requests[-1][1]["data"]
        self.assertIn('["name"~"Cafe \\"A\\.\\*\\"",i]', q)
        self.assertIn("around:800,", q)
        self.assertEqual([p["name"] for p in res], ["Near Café", "Far Café"])
        self.assertEqual(res[0]["opening_hours"], "Mo-Fr 08:00-18:00")
        self.assertEqual(res[0]["osm_url"], "https://www.openstreetmap.org/node/1")
        self.assertEqual(res[0]["kind"], "amenity=cafe")

    def test_nearest_rings_and_duplicates(self):
        # Overpass vraci prvni N prvku podle id, ne podle vzdalenosti: dotaz s okruhy 250 m, 750 m
        # a celym polomerem, prvek z vic okruhu jen jednou
        res = lm.nearby(50.0875, 14.4213, name="Cafe", radius=1500)
        q = SERVER.requests[-1][1]["data"]
        self.assertEqual([q.count(f"around:{r},") for r in (250, 750, 1500)], [1, 1, 1])
        self.assertEqual(q.count("out center 20;"), 3)
        self.assertEqual(len({p["osm"] for p in res}), len(res))
        q2 = (lm.nearby(50.0875, 14.4213, name="Cafe", radius=100), SERVER.requests[-1][1]["data"])[1]
        self.assertEqual(q2.count("around:"), 1)
        self.assertIn("around:100,", q2)

    def test_validation_and_busy(self):
        for kw in ({"category": "spaceports"}, {}, {"name": "x" * 81}):
            with self.assertRaises(lm.MapsError):
                lm.nearby(50.0, 14.0, **kw)
        with self.assertRaises(lm.MapsError):
            lm.nearby(95.0, 14.0, "cafes")
        self.assertEqual(SERVER.count("/overpass"), 0)
        self.assertEqual(lm.nearby(50.0, 14.0, "toilets", radius=99999, limit=999), [])
        self.assertIn("around:10000,", SERVER.requests[-1][1]["data"])
        self.assertIn("out center 50;", SERVER.requests[-1][1]["data"])
        SERVER.busy = True
        with self.assertRaises(lm.BusyError):
            lm.nearby(50.0, 14.0, "pharmacies")
        n = SERVER.count("/overpass")
        with self.assertRaises(lm.BusyError):
            lm.nearby(50.0, 14.0, "hotels")
        self.assertEqual(SERVER.count("/overpass"), n)          # po 502 chvili nic


class TestPreview(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_polyline_roundtrip_and_preview(self):
        pts = [(50.0876, 14.4213), (50.0901, 14.4011), (49.9, 14.0)]
        for prec in (5, 6):
            back = lm.decode_polyline(lm.encode_polyline(pts, prec), prec)
            for (a, b), (c, d) in zip(pts, back):
                self.assertAlmostEqual(a, c, places=prec - 1)
                self.assertAlmostEqual(b, d, places=prec - 1)
        self.assertEqual(lm.decode_polyline("mjbp~AwleoZ", 6)[0], (50.087607, 14.421212))   # mobilni test
        self.assertEqual(len(lm.thin_points(list(range(1000)), 400)), 400)
        pv = lm.make_preview("walk", {"lat": 50.0876, "lon": 14.4213, "label": "A"},
                             {"lat": 49.9, "lon": 14.0, "label": "B"},
                             [{"mode": "WALK", "label": "Walk", "color": "#2563EB", "points": pts}])
        self.assertEqual(pv["version"], 1)
        self.assertEqual(pv["bbox"], [49.9, 14.0, 50.0901, 14.4213])
        self.assertEqual(pv["legs"][0]["precision"], 6)
        self.assertIs(lm.preview_from_json({"ok": True, "preview": pv}), pv)
        self.assertIs(lm.preview_from_json(pv), pv)
        with self.assertRaises(lm.MapsError):
            lm.preview_from_json({"ok": True})

    def test_render_only_visible_tiles(self):
        import cairo
        code, out = lm.cli(["route", "50.0875,14.4208", "50.0903,14.4005", "--mode", "car"])
        self.assertEqual(code, 0, out)
        src = os.path.join(TMP, "route.json")
        with open(src, "w") as f:
            json.dump(out, f)
        png = os.path.join(TMP, "shots", "preview.png")
        code, info = lm.render_cli([src, "--size", "400x240", "--out", png])
        self.assertEqual(code, 0, info)
        img = cairo.ImageSurface.create_from_png(png)
        self.assertEqual((img.get_width(), img.get_height()), (400, 240))
        tiles = [p for p, _q in SERVER.requests if p.startswith("/tiles/")]
        self.assertEqual(len(tiles), info["tiles"])
        self.assertLessEqual(len(tiles), (400 // 256 + 2) * (240 // 256 + 2))
        self.assertTrue(all(t.startswith(f"/tiles/{info['zoom']}/") for t in tiles))
        self.assertEqual(info["missing_tiles"], 0)
        self.assertTrue(SERVER.headers[-1]["User-Agent"].startswith("LuxOS-Maps/"))
        # znovu: dlazdice z mezipameti, zadne stahovani
        SERVER.reset()
        code, info = lm.render_cli([src, "--size", "400x240", "--out", png])
        self.assertEqual((code, info["downloaded"], SERVER.count("/tiles/")), (0, 0, 0))
        # bez site: obrazek se vytvori i tak (chybejici dlazdice = pozadi)
        SERVER.fail = True
        code, info = lm.render_cli([src, "--size", "900x500", "--out", png])
        self.assertEqual(code, 0, info)
        self.assertGreater(info["missing_tiles"], 0)
        shots = os.environ.get("LUXOS_TEST_SHOTS")
        SERVER.fail = False
        # MHD: nahled prvniho spojeni; jine spojeni jen s --geometry
        code, tr = lm.cli(["transit-route", "50.0757,14.4199", "50.0905,14.3995"])
        with open(src, "w") as f:
            json.dump(tr, f)
        code, info = lm.render_cli([src, "--size", "480x270", "--out", png])
        self.assertEqual(code, 0, info)
        if shots:
            shutil.copy(png, os.path.join(shots, "maps-preview-transit.png"))
        code, info = lm.render_cli([src, "--size", "480x270", "--out", png, "--itinerary", "2"])
        self.assertEqual(code, 1)
        code, tr = lm.cli(["transit-route", "50.0757,14.4199", "50.0905,14.3995", "--geometry"])
        with open(src, "w") as f:
            json.dump(tr, f)
        code, info = lm.render_cli([src, "--size", "480x270", "--out", png, "--itinerary", "2"])
        self.assertEqual(code, 0, info)
        for bad in (["--size", "5000x10"], ["--size", "abc"], []):
            self.assertEqual(lm.render_cli([src, "--out", png, *bad])[0] if bad else
                             lm.render_cli([src, "--size", "100x100"])[0], 1)


class TestTiles(unittest.TestCase):
    def setUp(self):
        clean_state()
        self.got = {}
        self.event = threading.Event()

    def cb(self, key, data):
        self.got.setdefault(key, []).append(data)
        self.event.set()

    def wait(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def store(self):
        s = lm.TileStore(os.environ["LUXOS_MAPS_TILES"], self.cb)
        self.addCleanup(s.stop)
        return s

    def test_cache_headers(self):
        now = 1000000.0
        real = {"Cache-Control": "max-age=90856, stale-while-revalidate=604800, stale-if-error=604800",
                "Age": "90859"}
        self.assertAlmostEqual(lm.parse_cache_headers(real, now) - now, 604800)
        self.assertEqual(lm.parse_cache_headers({"Cache-Control": "max-age=3600"}, now), now + 3600)
        self.assertEqual(lm.parse_cache_headers({}, now), now + lm.MIN_TTL)
        self.assertEqual(lm.parse_cache_headers({"Cache-Control": "no-cache"}, now), now)
        exp = {"Expires": "Thu, 01 Jan 1970 12:00:00 GMT"}
        self.assertEqual(lm.parse_cache_headers(exp, 0.0), 12 * 3600)

    def test_download_two_parallel_and_disk_cache(self):
        SERVER.delay = 0.15
        s = self.store()
        keys = [(3, x, y) for x in range(3) for y in range(3)]
        s.want(keys)
        self.assertTrue(self.wait(lambda: len(self.got) == len(keys)))
        self.assertLessEqual(SERVER.max_active, 2)
        self.assertLessEqual(s.stats["max_parallel"], 2)
        self.assertEqual(SERVER.count("/tiles/"), len(keys))
        h = SERVER.headers[-1]
        self.assertTrue(h["User-Agent"].startswith("LuxOS-Maps/"))
        self.assertNotIn("Cache-Control", h)
        self.assertNotIn("Pragma", h)
        p = s.path((3, 1, 1))
        self.assertGreater(os.stat(p).st_mtime, time.time() + 86400 + 604800 - 60)   # expirace = mtime
        # nove okno: cerstve dlazdice z disku, zadne pozadavky
        SERVER.reset()
        self.got.clear()
        s2 = self.store()
        s2.want(keys)
        self.assertTrue(self.wait(lambda: len(self.got) == len(keys)))
        time.sleep(0.2)
        self.assertEqual(SERVER.count("/tiles/"), 0)

    def test_revalidate_expired(self):
        s = self.store()
        key = (2, 1, 1)
        s.want([key])
        self.assertTrue(self.wait(lambda: key in self.got))
        p = s.path(key)
        os.utime(p, (time.time(), time.time() - 10))      # vyprsela
        SERVER.reset()
        self.got.clear()
        s.want([])
        s.want([key])
        self.assertTrue(self.wait(lambda: SERVER.count("/tiles/") == 1 and s.stats["revalidated"] == 1))
        self.assertEqual(SERVER.headers[-1].get("If-None-Match"), '"t2-1-1"')
        self.assertEqual(len(self.got[key]), 1)          # stara dlazdice z disku, 304 nic noveho neposle
        self.assertGreater(os.stat(p).st_mtime, time.time() + 3600)

    def test_no_prefetch_and_queue_replaced(self):
        SERVER.delay = 0.3
        s = self.store()
        s.want([(10, x, 300) for x in range(30)])
        time.sleep(0.1)
        s.want([(10, 500, 300)])        # uzivatel se posunul jinam: stara fronta pryc
        self.assertTrue(self.wait(lambda: (10, 500, 300) in self.got))
        time.sleep(0.5)
        self.assertLessEqual(SERVER.count("/tiles/"), 3)   # 2 rozpracovane + nova

    def test_offline(self):
        s = self.store()
        s.want([(1, 0, 0)])
        self.assertTrue(self.wait(lambda: (1, 0, 0) in self.got))
        os.utime(s.path((1, 0, 0)), (time.time(), time.time() - 10))
        SERVER.fail = True
        self.got.clear()
        s.want([(1, 0, 0), (1, 1, 0)])
        self.assertTrue(self.wait(lambda: (1, 1, 0) in self.got and s.offline))
        self.assertEqual(self.got[(1, 1, 0)], [None])            # neni nikde
        self.assertIsNotNone(self.got[(1, 0, 0)][0])             # stara z disku zustava
        SERVER.fail = False
        s.retry_now()
        s.want([(1, 1, 0)])
        self.assertTrue(self.wait(lambda: any(self.got.get((1, 1, 0), [None]))))
        self.assertFalse(s.offline)

    def test_prune(self):
        root = os.path.join(TMP, "cache", "luxos", "maps")
        d = os.path.join(root, "tiles", "osm", "5", "1")
        os.makedirs(d)
        for i in range(10):
            p = os.path.join(d, f"{i}.png")
            with open(p, "wb") as f:
                f.write(b"x" * 1000)
            os.utime(p, (0, 1000 + i))
        self.assertEqual(lm.prune_cache(limit=5000, force=True), 6)
        self.assertEqual(sorted(os.listdir(d)), ["6.png", "7.png", "8.png", "9.png"])
        self.assertEqual(lm.prune_cache(limit=10), 0)      # jednou denne


class TestCli(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_search_route_open(self):
        code, out = lm.cli(["search", "Karlovo", "náměstí", "--limit", "2", "--near", "50.08,14.42"])
        self.assertEqual(code, 0)
        self.assertEqual(out["results"][0]["name"], "Karlovo náměstí")
        self.assertTrue(out["results"][0]["geo_uri"].startswith("geo:50.075744,14.41991"))
        self.assertIn("OpenStreetMap", out["attribution"])
        code, out = lm.cli(["route", "50.0875,14.4208", "Karlovo náměstí", "--mode", "walk"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out["mode"], "walk")
        self.assertEqual(out["to"]["name"], "Karlovo náměstí")
        self.assertEqual(out["steps"][0]["instruction"], "Depart")
        self.assertGreater(out["distance_m"], 1000)
        self.assertTrue(SERVER.requests[-1][0].startswith("/routed-foot/"))
        code, out = lm.cli(["route", "a"])
        self.assertEqual((code, out["ok"]), (1, False))
        code, out = lm.cli(["reverse", "50.0757,14.4199"])
        self.assertEqual(out["place"]["name"], "Karlovo náměstí")
        opened = []
        code, out = lm.cli(["open", "geo:50.08,14.42?z=15"], spawn=opened.append)
        self.assertEqual(opened, [["geo:50.08,14.42?z=15"]])
        lm.cli(["open", "--route", "here", "Praha", "--mode", "bike"], spawn=opened.append)
        self.assertEqual(opened[-1], ["--route", "here", "Praha", "--mode", "bike"])
        self.assertEqual(lm.cli(["fly"])[0], 2)
        self.assertIn("usage", lm.cli([])[1]["help"])

    def test_transit_timetable_nearby_json(self):
        code, out = lm.cli(["transit-route", "50.0757,14.4199", "50.0905,14.3995", "--limit", "2",
                            "--max-transfers", "1"])
        self.assertEqual(code, 0, out)
        self.assertIn("maxTransfers=1", SERVER.raw[-1])
        self.assertEqual(len(out["itineraries"]), 2)
        self.assertEqual(out["search"], {"time": "now", "arrive_by": False})
        self.assertNotIn("geometry", out["itineraries"][0]["legs"][1])       # jen s --geometry
        pv = out["preview"]
        self.assertEqual((pv["mode"], pv["version"], len(pv["legs"])), ("transit", 1, 3))
        self.assertEqual(pv["legs"][1]["color"], "#7A0603")
        self.assertIn("transitous.org/sources", out["attribution"])
        self.assertIn("OpenStreetMap", out["attribution"])
        code, out2 = lm.cli(["route", "50.0757,14.4199", "50.0905,14.3995", "--mode", "transit", "--no-preview"])
        self.assertEqual(code, 0, out2)
        self.assertNotIn("preview", out2)
        code, out = lm.cli(["transit-route", "50.0875,14.4213", "50.0755,14.4378", "--time",
                            "2026-08-24T10:00:00+02:00", "--arrive"])
        self.assertEqual(code, 0, out)
        self.assertIn("arriveBy=true", SERVER.raw[-1])
        self.assertEqual(out["search"]["arrive_by"], True)
        self.assertEqual(lm.cli(["transit-route", "a", "b", "--time", "soon"])[1]["error"][:12], "invalid time")
        code, out = lm.cli(["transit-route", "0,0", "50.0905,14.3995"])
        self.assertEqual((code, out["error"]), (1, "NoRoute"))
        # odjezdy
        code, out = lm.cli(["timetable", "50.0759,14.419612", "--radius", "200", "--limit", "5"])
        self.assertEqual(code, 0, out)
        self.assertEqual((out["type"], len(out["connections"]), out["radius_m"]), ("departures", 5, 200))
        self.assertIn("transitous.org/sources", out["attribution"])
        c = out["connections"][0]
        for key in ("time", "datetime", "scheduled_time", "delay_min", "realtime", "line", "mode", "headsign",
                    "stop", "platform", "cancelled", "operator", "color", "summary"):
            self.assertIn(key, c)
        code, out = lm.cli(["timetable", "--stop-id", "cz-PID_U237Z3P", "--type", "arrivals"])
        self.assertEqual(code, 0, out)
        self.assertIn("arriveBy=true", SERVER.raw[-1])
        self.assertEqual(lm.cli(["timetable", "50.07,14.41", "--type", "x"])[0], 1)
        self.assertEqual(lm.cli(["timetable", "50.07,14.41", "--radius", "5"])[0], 1)
        code, out = lm.cli(["timetable", "Karlovo náměstí"])        # nazev -> Nominatim -> odjezdy
        self.assertEqual(code, 0, out)
        self.assertEqual(out["near"]["name"], "Karlovo náměstí")
        # okoli
        code, out = lm.cli(["nearby", "50.0757,14.4199", "--category", "public_transport", "--radius", "300"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out["results"][0]["name"], "Karlovo náměstí")
        self.assertTrue(out["results"][0]["geo_uri"].startswith("geo:"))
        self.assertIn("distance", out["results"][0])
        self.assertIn("Overpass", out["attribution"])
        code, out = lm.cli(["nearby", "50.0875,14.4213", "--name", "Cafe"])
        self.assertEqual([r["name"] for r in out["results"]], ["Near Café", "Far Café"])
        code, out = lm.cli(["nearby", "50.0875,14.4213", "--category", "bars"])
        self.assertEqual(code, 1)
        self.assertIn("pharmacies", out["error"])
        self.assertEqual(lm.cli(["nearby", "50.0875,14.4213"])[0], 1)
        self.assertIn("public_transport", lm.cli([])[1]["nearby_categories"])
        SERVER.busy = True
        code, out = lm.cli(["nearby", "50.0, 14.0", "--category", "fuel"])
        self.assertEqual((code, out["error"]), (1, "busy"))

    def test_route_preview_json(self):
        code, out = lm.cli(["route", "50.0875,14.4208", "50.0903,14.4005", "--mode", "walk"])
        self.assertEqual(code, 0, out)
        pv = out["preview"]
        self.assertEqual((pv["mode"], pv["legs"][0]["mode"], pv["legs"][0]["color"]), ("walk", "WALK", "#2563EB"))
        self.assertIn("engine=fossgis_osrm_foot", out["open_map_url"])
        self.assertEqual(pv["open_map_url"], out["open_map_url"])
        s, w, n, e = pv["bbox"]
        self.assertTrue(s <= 50.0875 <= n and w <= 14.4208 <= e)
        self.assertGreater(len(lm.decode_polyline(pv["legs"][0]["polyline"], 6)), 10)

    def test_render_entry_point(self):
        import subprocess
        code, out = lm.cli(["route", "50.0875,14.4208", "50.0903,14.4005"])
        src = os.path.join(TMP, "r.json")
        with open(src, "w") as f:
            json.dump(out, f)
        png = os.path.join(TMP, "r.png")
        res = subprocess.run([sys.executable, os.path.join(FILES, "luxos-maps"), "--render-preview", src,
                              "--size", "320x200", "--out", png], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PYTHONPATH=FILES + os.pathsep + os.path.join(
                                 ROOT, "luxos-i18n", "files"), DISPLAY=""))
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual((data["ok"], data["width"], data["height"]), (True, 320, 200))
        self.assertTrue(os.path.getsize(png) > 1000)
        self.assertNotIn("Gtk", res.stderr)

    def test_location_needs_consent(self):
        code, out = lm.cli(["where-am-i"])
        self.assertEqual((code, out["error"]), (1, "consent"))
        code, out = lm.cli(["route", "here", "50.09,14.40"])
        self.assertEqual(out["error"], "consent")
        self.assertEqual(SERVER.count("/ip"), 0)
        cfg = lm.load_config()
        cfg["location_consent"] = True
        lm.save_config(cfg)
        code, out = lm.cli(["where-am-i"])
        self.assertEqual((code, out["lat"], out["source"], out["accuracy_m"]), (0, 50.088, "ip", 5000))

    def test_json_entry_point(self):
        import subprocess
        out = subprocess.run([sys.executable, os.path.join(FILES, "luxos-maps"), "--json", "search", "Karlovo"],
                             capture_output=True, text=True, timeout=30,
                             env=dict(os.environ, PYTHONPATH=FILES + os.pathsep + os.path.join(
                                 ROOT, "luxos-i18n", "files"), DISPLAY=""))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["results"][0]["name"], "Karlovo náměstí")
        self.assertNotIn("Gtk", out.stderr)


class FakeCompanion:
    """cz.luxos.Companion1 (GetLocation, signal LocationChanged) na soukrome sbernici D-Bus
    (vlastni dbus-daemon, nikdy sbernice skutecne relace); obsluha ve vlastnim vlakne.
    Navic org.freedesktop.ScreenSaver a org.freedesktop.PowerManagement.Inhibit (navigace: obrazovka
    nezhasne) - zaznamenava Inhibit/UnInhibit."""
    XML = """<node><interface name="cz.luxos.Companion1">
      <method name="GetLocation"><arg type="a{sv}" direction="out"/></method>
      <signal name="LocationChanged"><arg type="a{sv}"/></signal></interface></node>"""
    INHIBIT_XML = """<node><interface name="%s">
      <method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/>
        <arg type="u" direction="out"/></method>
      <method name="UnInhibit"><arg type="u" direction="in"/></method></interface></node>"""
    INHIBITORS = (("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver"),
                  ("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit",
                   "org.freedesktop.PowerManagement.Inhibit"))

    def __init__(self):
        import subprocess
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        # vlastni konfigurace bez aktivace sluzeb (zadne sluzby skutecne relace)
        conf = os.path.join(TMP, "companion-bus.conf")
        with open(conf, "w") as f:
            f.write("<busconfig><type>session</type><listen>unix:path=%s</listen><auth>EXTERNAL</auth>"
                    "<policy context='default'><allow send_destination='*' eavesdrop='true'/>"
                    "<allow eavesdrop='true'/><allow own='*'/></policy></busconfig>"
                    % os.path.join(TMP, "companion-bus-%d" % time.monotonic_ns()))
        self.daemon = subprocess.Popen(["dbus-daemon", "--config-file=" + conf, "--nofork", "--nopidfile",
                                        "--print-address=1"], stdout=subprocess.PIPE, text=True)
        self.address = self.daemon.stdout.readline().strip()
        self.loc = {"valid": False}
        self.calls = 0
        self.inhibits = {}           # cookie -> (rozhrani, aplikace, duvod), jen aktivni
        self.inhibit_log = []
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,))
        self.thread.start()
        ready.wait(5)

    def variant(self, loc):
        types = {"valid": "b", "latitude": "d", "longitude": "d", "accuracy": "d", "timestamp_ms": "x",
                 "age_ms": "x", "mock": "b", "device": "s", "speed": "d", "bearing": "d", "altitude": "d"}
        return {k: self.GLib.Variant(types[k], v) for k, v in loc.items()}

    def _run(self, ready):
        Gio, GLib = self.Gio, self.GLib
        self.ctx = GLib.MainContext.new()
        self.ctx.push_thread_default()
        self.loop = GLib.MainLoop.new(self.ctx, False)
        self.bus = Gio.DBusConnection.new_for_address_sync(
            self.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        info = Gio.DBusNodeInfo.new_for_xml(self.XML)

        def call(_b, _s, _p, _i, method, _params, inv):
            self.calls += 1
            inv.return_value(GLib.Variant("(a{sv})", (self.variant(self.loc),)))
        self.bus.register_object("/cz/luxos/Companion1", info.interfaces[0], call, None, None)
        self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                           GLib.Variant("(su)", ("cz.luxos.Companion1", 4)), None, 0, 2000, None)

        def inhibit(_b, _s, _p, iface, method, params, inv):
            if method == "Inhibit":
                cookie = len(self.inhibit_log) + 1
                self.inhibits[cookie] = (iface,) + tuple(params.unpack())
                self.inhibit_log.append(("Inhibit", iface, cookie))
                inv.return_value(GLib.Variant("(u)", (cookie,)))
            else:
                cookie = params.unpack()[0]
                self.inhibits.pop(cookie, None)
                self.inhibit_log.append(("UnInhibit", iface, cookie))
                inv.return_value(None)
        for name, path, iface in self.INHIBITORS:
            node = Gio.DBusNodeInfo.new_for_xml(self.INHIBIT_XML % iface)
            self.bus.register_object(path, node.interfaces[0], inhibit, None, None)
            self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "RequestName", GLib.Variant("(su)", (name, 4)), None, 0, 2000, None)
        ready.set()
        self.loop.run()

    def emit(self, loc):
        self.loc = loc

        def do():
            self.bus.emit_signal(None, "/cz/luxos/Companion1", "cz.luxos.Companion1", "LocationChanged",
                                 self.GLib.Variant("(a{sv})", (self.variant(loc),)))
            return False
        self.ctx.invoke_full(self.GLib.PRIORITY_DEFAULT, do)

    def close(self):
        self.ctx.invoke_full(self.GLib.PRIORITY_DEFAULT, lambda: self.loop.quit() or False)
        self.thread.join(5)
        self.daemon.terminate()
        self.daemon.wait(5)


PHONE_FIX = {"valid": True, "latitude": 50.0755, "longitude": 14.4378, "accuracy": 6.5,
             "timestamp_ms": 1793098800000, "age_ms": 1200, "mock": False, "device": "Pixel", "speed": 1.3}


class TestPhoneLocation(unittest.TestCase):
    """my_location() bere cerstvou polohu telefonu (LuxOS Companion) jen se souhlasem v Mapach a se
    zapnutym sdilenim v nastaveni Telefon; jinak GeoClue/IP jako dosud."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon missing")
        cls.fake = FakeCompanion()
        os.environ["LUXOS_MAPS_COMPANION_BUS"] = cls.fake.address

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("LUXOS_MAPS_COMPANION_BUS", None)
        cls.fake.close()

    def setUp(self):
        clean_state()
        os.environ["LUXOS_MAPS_PHONE"] = "1"
        self.addCleanup(os.environ.__setitem__, "LUXOS_MAPS_PHONE", "0")
        self.fake.loc = dict(PHONE_FIX)

    def consent(self, value=True):
        cfg = lm.load_config()
        cfg["location_consent"] = value
        lm.save_config(cfg)
        return lm.load_config()

    def companion_cfg(self, share):
        path = os.path.join(TMP, "config", "luxos", "companion.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"share_location": share}, f)

    def test_phone_fix_validation(self):
        self.assertEqual(lm.phone_fix(PHONE_FIX)["source"], "phone")
        self.assertEqual(lm.phone_fix(PHONE_FIX)["speed"], 1.3)
        for bad in ({"valid": False}, dict(PHONE_FIX, latitude=91.0), dict(PHONE_FIX, age_ms=15001),
                    dict(PHONE_FIX, accuracy=float("nan")), dict(PHONE_FIX, valid=1), None, []):
            self.assertIsNone(lm.phone_fix(bad), bad)

    def test_prefers_fresh_phone_fix_with_consent(self):
        loc = lm.my_location(self.consent(True))
        self.assertEqual((loc["source"], loc["lat"], loc["lon"], loc["accuracy"]), ("phone", 50.0755, 14.4378, 6.5))
        self.assertEqual(SERVER.count("/ip"), 0)
        code, out = lm.cli(["where-am-i"])
        self.assertEqual((code, out["source"]), (0, "phone"))

    def test_no_consent_no_phone(self):
        calls = self.fake.calls
        loc = lm.my_location(self.consent(False))
        self.assertEqual(loc["source"], "ip")
        self.assertEqual(self.fake.calls, calls)           # telefon se ani nedotazuje

    def test_sharing_turned_off_in_phone_settings(self):
        self.companion_cfg(False)
        self.addCleanup(os.remove, os.path.join(TMP, "config", "luxos", "companion.json"))
        self.assertEqual(lm.my_location(self.consent(True))["source"], "ip")
        self.companion_cfg(True)
        self.assertEqual(lm.my_location(self.consent(True))["source"], "phone")

    def test_stale_or_invalid_fix_falls_back(self):
        for loc in ({"valid": False}, dict(PHONE_FIX, age_ms=16000)):
            self.fake.loc = loc
            self.assertEqual(lm.my_location(self.consent(True))["source"], "ip", loc)

    def test_service_not_running(self):
        os.environ["LUXOS_MAPS_COMPANION_BUS"] = "unix:path=" + os.path.join(TMP, "no-such-bus")
        lm._companion_bus.clear()
        try:
            self.assertEqual(lm.my_location(self.consent(True))["source"], "ip")
        finally:
            os.environ["LUXOS_MAPS_COMPANION_BUS"] = self.fake.address


def car_route():
    return lm.NavRoute.from_osrm(lm.parse_route(fixture("route-car.json"), "car"))


def offset_fix(route, along, meters, accuracy=6.0):
    """Poloha meters vpravo od trasy v miste along (kolmo ke smeru)."""
    lat, lon, head = route.point_at(along)
    a = math.radians(head + 90)
    return {"lat": lat + meters * math.cos(a) / 111195.0,
            "lon": lon + meters * math.sin(a) / (111195.0 * math.cos(math.radians(lat))),
            "accuracy": accuracy, "source": "phone", "name": ""}


def recorded_track(route, speed=11.0, noise=8.0, seed=7):
    """GPS stopa podel trasy z fixture: 1 poloha/s, pseudonahodna chyba do +-noise m kolmo i podel trasy."""
    import random
    rnd = random.Random(seed)
    along, out = 0.0, []
    while True:
        f = offset_fix(route, min(route.length, along + rnd.uniform(-noise, noise) / 2), rnd.uniform(-noise, noise))
        f.update(speed=speed, bearing=route.point_at(along)[2])
        out.append(f)
        if along >= route.length:
            return out
        along = min(route.length, along + speed)


class TestNavigation(unittest.TestCase):
    """Navigace bez site a bez okna: postup po krocich, mimo trasu, prepocet (omezeny), prijezd, cas
    prijezdu a smer - simulovana stopa GPS podel ulozene trasy OSRM (route-car.json)."""

    def test_bearing_and_route_geometry(self):
        self.assertAlmostEqual(lm.bearing(50.0, 14.0, 50.01, 14.0), 0.0, places=6)
        self.assertAlmostEqual(lm.bearing(50.0, 14.0, 50.0, 14.01), 90.0, delta=0.01)
        self.assertAlmostEqual(lm.bearing(50.0, 14.0, 49.99, 14.0), 180.0, places=6)
        self.assertAlmostEqual(lm.bearing(50.0, 14.0, 50.0, 13.99), 270.0, delta=0.01)
        self.assertAlmostEqual(lm.angle_diff(350, 10), 20)
        self.assertAlmostEqual(lm.angle_diff(10, 350), -20)
        r = car_route()
        self.assertAlmostEqual(r.length, 2415.3, delta=10)          # OSRM: 2415,3 m
        alongs = [s["along"] for s in r.steps]
        self.assertEqual(alongs, sorted(alongs))
        self.assertEqual((alongs[0], alongs[-1]), (0.0, r.length))
        # bod manevru lezi na trase a vzdalenosti mezi manevry odpovidaji krokum OSRM
        for a, b in zip(r.steps, r.steps[1:]):
            self.assertAlmostEqual(b["along"] - a["along"], a["distance"], delta=max(3.0, a["distance"] * 0.02))
        lat, lon, _h = r.point_at(r.steps[5]["along"])
        self.assertLess(lm.distance_m(lat, lon, r.steps[5]["lat"], r.steps[5]["lon"]), 1.0)
        f = offset_fix(r, 1000, 30)
        _seg, along, off = r.project(f["lat"], f["lon"])
        self.assertAlmostEqual(off, 30, delta=2)
        self.assertAlmostEqual(along, 1000, delta=15)

    def test_step_advance_and_arrival_along_recorded_track(self):
        r = car_route()
        nav = lm.Navigator(r)
        seen, t, last_next = [], 1000.0, 1
        prev_to_next = None
        for fix in recorded_track(r):
            st = nav.update(fix, t)
            t += 1
            self.assertFalse(st["off_route"], (t, st["offset"]))       # chyba GPS 8 m neni mimo trasu
            self.assertGreaterEqual(st["next"], last_next)               # krok se nikdy nevraci
            if st["next"] == last_next and prev_to_next is not None and not st["arrived"]:
                self.assertLess(st["to_next"], prev_to_next + 12)        # k manevru se blizime
            last_next, prev_to_next = st["next"], st["to_next"]
            seen.append(st["next"])
            if st["arrived"]:
                break
        self.assertTrue(nav.arrived)
        self.assertEqual(nav.next, len(r.steps) - 1)
        # kazdy manevr byl jednou "dalsi" (zadny se nepreskocil, i ty 38 m od sebe)
        self.assertEqual(sorted(set(seen)), list(range(1, len(r.steps))))
        st = nav.update(recorded_track(r)[-1], t)
        self.assertEqual((st["remaining_m"], st["remaining_s"], st["to_next"]), (0.0, 0.0, 0.0))

    def test_advance_only_after_passing_maneuver(self):
        r = car_route()
        nav = lm.Navigator(r)
        m = r.steps[3]["along"]
        st = nav.update(offset_fix(r, m - 20, 0), 0)
        self.assertEqual(st["next"], 3)
        self.assertAlmostEqual(st["to_next"], 20, delta=1)
        st = nav.update(offset_fix(r, m - 1, 0), 1)
        self.assertEqual(st["next"], 3)
        st = nav.update(offset_fix(r, m + lm.NAV_PASS_M + 2, 0), 2)
        self.assertEqual((st["next"], st["advanced"]), (4, True))
        self.assertEqual(st["step"]["type"], r.steps[4]["type"])
        self.assertIs(st["following"], r.steps[5])

    def test_off_route_three_fixes_and_rate_limited_reroute(self):
        r = car_route()
        nav = lm.Navigator(r)
        for i, a in enumerate((900, 911, 922)):
            st = nav.update(offset_fix(r, a, 0), i)
        self.assertFalse(st["off_route"])
        # 150 m od trasy: 1. a 2. poloha jeste ne, 3. po sobe (a aspon 4 s) = mimo trasu a prepocet
        res = [nav.update(offset_fix(r, 930 + i, -150), 3 + 2 * i) for i in range(3)]
        self.assertEqual([s["off_route"] for s in res], [False, False, True])
        self.assertEqual([s["reroute"] for s in res], [False, False, True])
        self.assertAlmostEqual(res[-1]["offset"], 150, delta=3)
        # dalsi polohy mimo trasu: novy prepocet az za NAV_REROUTE_GAP s
        more = [nav.update(offset_fix(r, 935, -160), 8 + i) for i in range(10)]
        self.assertTrue(all(s["off_route"] for s in more))
        self.assertFalse(any(s["reroute"] for s in more))
        self.assertTrue(nav.update(offset_fix(r, 935, -160), 7 + lm.NAV_REROUTE_GAP)["reroute"])
        # neuspesny prepocet: pauza NAV_REROUTE_BACKOFF s
        nav.reroute_failed(100)
        self.assertFalse(nav.update(offset_fix(r, 935, -160), 100 + lm.NAV_REROUTE_GAP)["reroute"])
        self.assertTrue(nav.update(offset_fix(r, 935, -160), 100 + lm.NAV_REROUTE_BACKOFF)["reroute"])
        # krok se mimo trasu neposunul a navrat na trasu stav zrusi
        self.assertEqual(nav.next, res[0]["next"])
        st = nav.update(offset_fix(r, 940, 5), 200)
        self.assertFalse(st["off_route"])
        self.assertAlmostEqual(nav.along, 940, delta=3)

    def test_off_route_by_time_and_noise_tolerance(self):
        r = car_route()
        nav = lm.Navigator(r)
        nav.update(offset_fix(r, 500, 0), 0)
        self.assertFalse(nav.update(offset_fix(r, 505, 90), 1)["off_route"])
        self.assertTrue(nav.update(offset_fix(r, 505, 90), 1 + lm.NAV_OFF_ROUTE_S)["off_route"])   # 2 polohy, 10 s
        nav = lm.Navigator(r)
        for i in range(30):                     # stale 35 m vedle trasy (sum, soubezna ulice): ne mimo trasu
            self.assertFalse(nav.update(offset_fix(r, 300 + i * 5, 35), i)["off_route"])
        # nepresna poloha (300 m) o mimo trasu nerozhoduje
        for i in range(5):
            st = nav.update(offset_fix(r, 450, 400, accuracy=300), 40 + i)
        self.assertFalse(st["off_route"])
        self.assertFalse(st["reroute"])
        # Navigator bez prepoctu (MHD): mimo trasu ano, prepocet ne
        nav = lm.Navigator(r, reroute=False)
        nav.update(offset_fix(r, 500, 0), 0)
        for i in range(4):
            st = nav.update(offset_fix(r, 505, 150), 1 + 2 * i)
        self.assertTrue(st["off_route"])
        self.assertFalse(st["reroute"])

    def test_reroute_set_route_resets_progress(self):
        r = car_route()
        nav = lm.Navigator(r)
        for i in range(3):
            st = nav.update(offset_fix(r, 1500, 200), 2 * i)
        self.assertTrue(st["reroute"])
        new = lm.NavRoute.from_osrm(lm.parse_route(fixture("route-foot.json"), "walk"))
        nav.set_route(new)
        st = nav.update(offset_fix(new, 0, 0), 3)
        self.assertEqual((st["next"], st["off_route"], st["arrived"]), (1, False, False))
        self.assertAlmostEqual(st["remaining_m"], new.length, delta=5)
        self.assertFalse(nav.update(offset_fix(new, 10, 200), 4)["reroute"])     # pocitadlo od nuly

    def test_eta_math(self):
        r = car_route()
        total = sum(s["duration"] for s in r.steps)
        self.assertAlmostEqual(r.remaining_s(0, 0), total, places=6)
        self.assertAlmostEqual(r.duration, 384.4, places=3)
        # v polovine kroku 4 zbyva pulka jeho doby + vsechny dalsi kroky
        a, b = r.steps[4]["along"], r.steps[5]["along"]
        rest = sum(s["duration"] for s in r.steps[5:])
        self.assertAlmostEqual(r.remaining_s((a + b) / 2, 4), r.steps[4]["duration"] / 2 + rest, places=6)
        nav = lm.Navigator(r)
        st = nav.update(offset_fix(r, (a + b) / 2, 0), 5000.0)
        self.assertEqual(st["next"], 5)
        self.assertAlmostEqual(st["remaining_s"], r.steps[4]["duration"] / 2 + rest, delta=1.0)
        self.assertAlmostEqual(st["eta"], 5000.0 + st["remaining_s"], places=6)
        self.assertAlmostEqual(st["remaining_m"], r.length - (a + b) / 2, delta=2)
        # MHD: cas prijezdu podle jizdniho radu, ne podle vzdalenosti
        it = lm.parse_itinerary(fixture("transitous-plan.json")["itineraries"][0])
        tr = lm.transit_nav_route(it)
        arr = lm.parse_iso(it["arrival"]).timestamp()
        nav = lm.Navigator(tr, reroute=False)
        st = nav.update({"lat": tr.points[0][0], "lon": tr.points[0][1], "accuracy": 5}, arr - 600)
        self.assertAlmostEqual(st["remaining_s"], 600, places=3)
        self.assertAlmostEqual(st["eta"], arr, places=3)

    def test_heading(self):
        r = car_route()
        nav = lm.Navigator(r)
        st = nav.update(dict(offset_fix(r, 100, 0), speed=10.0, bearing=123.0), 0)
        self.assertEqual(st["heading"], 123.0)                   # kurz z GPS pri jizde
        # bez kurzu (nebo stani): z pohybu o >= 8 m, jinak posledni
        nav.update(offset_fix(r, 103, 0), 1)
        st = nav.update(dict(offset_fix(r, 105, 0), speed=0.2, bearing=5.0), 2)
        self.assertEqual(st["heading"], 123.0)
        st = nav.update(offset_fix(r, 1530, 0), 3)
        self.assertAlmostEqual(st["heading"], lm.bearing(*r.point_at(100)[:2], *r.point_at(1530)[:2]), delta=0.5)
        st = nav.update(offset_fix(r, 1560, 0), 4)
        self.assertAlmostEqual(st["heading"], r.point_at(1545)[2], delta=10)
        # bez jakekoli informace: smer trasy
        nav = lm.Navigator(r)
        st = nav.update(offset_fix(r, 1000, 0), 0)
        self.assertAlmostEqual(st["heading"], r.point_at(1000)[2], delta=1)

    def test_transit_steps(self):
        it = lm.parse_itinerary(fixture("transitous-plan.json")["itineraries"][0])
        tr = lm.transit_nav_route(it)
        self.assertEqual([s["type"] for s in tr.steps], ["walk", "board", "alight", "arrive"])
        self.assertEqual(tr.steps[2]["arg"], it["legs"][1]["to"]["name"])
        self.assertEqual(lm.step_instruction(tr.steps[0]), "Walk to %s" % it["legs"][0]["to"]["name"])
        nav = lm.Navigator(tr, reroute=False)
        t = 0
        for fix in lm.simulate_track(tr, speed=30):
            st = nav.update(fix, t)
            t += 1
        self.assertTrue(st["arrived"])

    def test_simulated_track(self):
        r = car_route()
        fixes = list(lm.simulate_track(r, speed=100, interval=1.0))
        self.assertEqual(len(fixes), math.ceil(r.length / 100) + 1)
        self.assertEqual(fixes[0]["source"], "simulated")
        self.assertLess(lm.distance_m(fixes[-1]["lat"], fixes[-1]["lon"], *r.points[-1]), 0.5)

    # ---- prepocet podle realisticke stopy telefonu (fixture nav-tracks.json) ----
    def replay(self, name):
        """Prehraje stopu z fixture; vraci (stopa, casy prepoctu, stav v case prvniho prepoctu)."""
        tr = fixture("nav-tracks.json")[name]
        r = lm.NavRoute.from_osrm(lm.parse_route(fixture("route-foot.json" if tr["mode"] == "walk"
                                                         else "route-car.json"), tr["mode"]))
        nav = lm.Navigator(r)
        times, first = [], None
        for t, lat, lon, acc, sp, b in tr["fixes"]:
            fix = {"lat": lat, "lon": lon, "accuracy": acc, "speed": sp}
            if b is not None:
                fix["bearing"] = b
            st = nav.update(fix, 1000.0 + t)
            if st["reroute"]:
                times.append(t)
                first = first or dict(st, fix=fix)
        return tr, times, first

    def test_replay_reroute_when_leaving_route(self):
        # fixy po 1-5 s, presnost 5-50 m: soubezna ulice 80 m, vedlejsi ulice, otoceni zpet po trase
        limits = {"walk_parallel": 40, "walk_side_street": 60, "walk_opposite": 90,
                  "car_parallel": 30, "car_side_street": 25, "car_opposite": 40}
        for name, limit in limits.items():
            tr, times, st = self.replay(name)
            dev = tr["deviation_s"]
            self.assertTrue(times, name)
            self.assertGreater(times[0], dev, name)                       # ne pred odbockou
            self.assertLess(times[0] - dev, limit, (name, times[0] - dev))
            self.assertEqual(st["reason"], "wrong_way" if name.endswith("opposite") else "off_route", name)
            # nejvys 1 prepocet za NAV_REROUTE_GAP s (prepocet se tu nepouzije, takze se opakuje)
            self.assertTrue(all(b - a >= lm.NAV_REROUTE_GAP for a, b in zip(times, times[1:])), name)

    def test_replay_gps_jitter_never_reroutes(self):
        for name in ("walk_jitter", "walk_standing", "car_jitter", "car_standing"):
            tr, times, _st = self.replay(name)
            self.assertGreater(len(tr["fixes"]), 50)
            self.assertEqual(times, [], name)

    def test_reroute_from_current_position_then_on_route(self):
        """Po prepoctu nova trasa zacina v miste posledni polohy: dalsi polohy jsou na ni, zadny dalsi prepocet."""
        _tr, _times, st = self.replay("walk_side_street")
        foot = lm.NavRoute.from_osrm(lm.parse_route(fixture("route-foot.json"), "walk"))
        i = foot.steps[3]["along"]
        new = lm.NavRoute([(st["fix"]["lat"], st["fix"]["lon"])] + [foot.point_at(i + k * 20)[:2] for k in range(30)],
                          [], "walk")
        nav = lm.Navigator(foot)
        nav.set_route(new)
        for k, along in enumerate(range(0, 400, 7)):
            res = nav.update(offset_fix(new, along, 6 * math.sin(k)), 5000 + k * 5)
            self.assertFalse(res["reroute"])
            self.assertTrue(res["located"])
        self.assertAlmostEqual(nav.along, 399, delta=8)

    def test_wrong_way_on_route(self):
        r = car_route()
        nav = lm.Navigator(r)
        t = 0
        for a in range(600, 900, 10):                  # jede po trase
            st = nav.update(dict(offset_fix(r, a, 0), speed=10.0, bearing=r.point_at(a)[2]), t)
            t += 1
        self.assertFalse(st["off_route"])
        for a in range(890, 600, -10):                 # otoci se: na trase, ale proti smeru
            st = nav.update(dict(offset_fix(r, a, 0), speed=10.0, bearing=(r.point_at(a)[2] + 180) % 360), t)
            t += 1
            if st["reroute"]:
                break
        self.assertTrue(st["reroute"])
        self.assertEqual(st["reason"], "wrong_way")
        self.assertGreater(a, 780)                     # do 110 m (11 s)
        # stani na miste se sumem zpet po trase: ne
        nav = lm.Navigator(r)
        for k in range(200):
            st = nav.update(dict(offset_fix(r, 1000 - 30 * (k % 2), 0, accuracy=20), speed=0.0), k)
            self.assertFalse(st["reroute"])

    def test_transit_missed_connection_and_vehicle_threshold(self):
        it = lm.parse_itinerary(fixture("transitous-plan.json")["itineraries"][0])
        tr = lm.transit_nav_route(it)
        self.assertEqual(len(tr.legs), 3)
        self.assertEqual((tr.legs[0]["start"], tr.legs[-1]["end"]), (0.0, tr.length))
        dep = tr.legs[1]["departure"]
        self.assertEqual(dep, lm.parse_iso(it["legs"][1]["departure"]).timestamp())
        nav = lm.Navigator(tr)
        start = {"lat": tr.points[0][0], "lon": tr.points[0][1], "accuracy": 5}
        self.assertFalse(nav.update(start, dep - 60)["missed"])
        self.assertFalse(nav.update(start, dep + lm.NAV_MISSED_S - 1)["missed"])
        st = nav.update(start, dep + lm.NAV_MISSED_S + 1)
        self.assertEqual((st["missed"], st["reroute"], st["reason"]), (True, True, "missed"))
        self.assertFalse(nav.update(start, dep + lm.NAV_MISSED_S + 20)["reroute"])          # 1 plan / 60 s
        self.assertTrue(nav.update(start, dep + lm.NAV_MISSED_S + 1 + lm.NAV_TRANSIT_REROUTE_GAP)["reroute"])
        # ve vozidle: 100 m od linky (tvar linky je priblizny) neni mimo trasu, 200 m ano
        nav = lm.Navigator(tr)
        mid = (tr.legs[1]["start"] + tr.legs[1]["end"]) / 2
        for k in range(5):
            st = nav.update(offset_fix(tr, mid - 100 + k * 20, 0), dep + 60 + k)
        self.assertFalse(st["missed"])                                  # nastoupil
        for k in range(6):
            st = nav.update(offset_fix(tr, mid + k * 10, 100), dep + 70 + 2 * k)
        self.assertFalse(st["off_route"])
        for k in range(6):
            st = nav.update(offset_fix(tr, mid + k * 10, 200), dep + 90 + 2 * k)
        self.assertTrue(st["off_route"])
        # pesky usek: 50 m od trasy uz je mimo (prah chuze 35 m)
        nav = lm.Navigator(tr)
        w = tr.legs[2]["start"] + 100
        nav.update(offset_fix(tr, w, 0), dep + 900)
        for k in range(4):
            st = nav.update(offset_fix(tr, w + k, 50), dep + 902 + 2 * k)
        self.assertTrue(st["off_route"])

    def test_nav_motion_smooth_between_fixes(self):
        r = car_route()
        mo = lm.NavMotion()
        self.assertFalse(mo.active(0))
        lat, lon, h = r.point_at(500)
        mo.on_fix(10.0, {"lat": lat, "lon": lon, "accuracy": 5, "speed": 10.0}, h, r, 500)
        self.assertTrue(mo.active(10.0))
        # dopocet po trase rychlosti 10 m/s, nejvys NAV_EXTRAPOLATE_S s, pak stoji (a animace konci)
        p = mo.frame(10.5)
        _s, along, off = r.project(p[0], p[1])
        self.assertAlmostEqual(along, 505, delta=0.5)
        self.assertLess(off, 0.1)
        p = mo.frame(13.0)
        self.assertAlmostEqual(r.project(p[0], p[1])[1], 500 + 10 * lm.NAV_EXTRAPOLATE_S, delta=0.5)
        self.assertFalse(mo.active(13.0))
        # dalsi poloha 3 m za dopoctenym mistem: zadny skok, rozdil dobehne plynule
        lat2, lon2, h2 = r.point_at(518)
        before = mo.frame(14.0)
        mo.on_fix(14.0, {"lat": lat2, "lon": lon2, "accuracy": 5, "speed": 10.0}, h2, r, 518)
        after = mo.frame(14.0)
        self.assertLess(lm.distance_m(before[0], before[1], after[0], after[1]), 0.01)
        steps = []
        prev = after
        for k in range(1, 46):                         # 1,5 s po 1/30 s
            cur = mo.frame(14.0 + k / 30.0)
            steps.append(lm.distance_m(prev[0], prev[1], cur[0], cur[1]))
            prev = cur
        self.assertLess(max(steps), 10.0 / 30 + 0.5)   # zadny snimek neposkoci o vic nez ~rychlost/30 + dorovnani
        self.assertAlmostEqual(r.project(prev[0], prev[1])[1], 518 + 15, delta=1.0)
        # stoji (rychlost 0): bez dopoctu, po dorovnani neaktivni
        mo2 = lm.NavMotion()
        mo2.on_fix(0.0, {"lat": lat, "lon": lon, "accuracy": 5, "speed": 0.0}, 90.0)
        self.assertFalse(mo2.active(0.01))
        # otaceni nejkratsi cestou (350 -> 10 pres sever) a postupne
        mo3 = lm.NavMotion()
        mo3.on_fix(0.0, {"lat": lat, "lon": lon, "accuracy": 5, "speed": 0.0}, 350.0)
        mo3.on_fix(1.0, {"lat": lat, "lon": lon, "accuracy": 5, "speed": 0.0}, 10.0)
        hs = [mo3.heading(1.0 + k / 30.0) for k in range(60)]
        self.assertTrue(all(lm.angle_diff(350.0, x) >= -0.01 and lm.angle_diff(x, 10.0) >= -0.01 for x in hs), hs)
        self.assertAlmostEqual(lm.angle_diff(hs[-1], 10.0), 0.0, delta=0.5)
        # skok (prvni poloha po prepoctu daleko): bez animace
        far = r.point_at(2000)
        mo.on_fix(20.0, {"lat": far[0], "lon": far[1], "accuracy": 5, "speed": 0.0}, far[2])
        p = mo.frame(20.0)
        self.assertLess(lm.distance_m(p[0], p[1], far[0], far[1]), 0.01)
        # rychlost bez udaje telefonu: z poslednich poloh (a sum v ramci presnosti neni pohyb)
        mo4 = lm.NavMotion()
        mo4.on_fix(0.0, offset_fix(r, 100, 0, accuracy=5), None)
        mo4.on_fix(1.0, offset_fix(r, 112, 0, accuracy=5), None)
        self.assertAlmostEqual(mo4.speed, 12.0, delta=0.5)
        mo4.on_fix(2.0, offset_fix(r, 113, 0, accuracy=30), None)
        self.assertEqual(mo4.speed, 0.0)

    def test_route_bearing_param(self):
        clean_state()
        a, b = {"lat": 50.0875, "lon": 14.4208}, {"lat": 50.0895, "lon": 14.3995}
        lm.route(a, b, "car", bearing=271.6)
        self.assertEqual(SERVER.last_q("/routed-car/")["bearings"], "272,60;")
        n = SERVER.count("/routed-car/")
        lm.route(a, b, "car")                                       # bez smeru: jiny dotaz
        self.assertEqual(SERVER.count("/routed-car/"), n + 1)
        self.assertNotIn("bearings", SERVER.last_q("/routed-car/"))

    def test_config_sidebar_and_nav_prefs(self):
        clean_state()
        cfg = lm.load_config()
        self.assertNotIn("sidebar_width", cfg)
        self.assertEqual((cfg["nav_heading_up"], cfg["nav_voice"]), (True, False))   # hlas vychozi vypnuty
        for bad in (10, 5000, "400", True, 400.5):
            lm.save_config(dict(cfg, sidebar_width=bad))
            self.assertNotIn("sidebar_width", lm.load_config(), bad)
        lm.save_config(dict(cfg, sidebar_width=420, nav_heading_up=False, nav_voice=True))
        cfg = lm.load_config()
        self.assertEqual((cfg["sidebar_width"], cfg["nav_heading_up"], cfg["nav_voice"]), (420, False, True))


class TestSuggest(unittest.TestCase):
    """Naseptavani pri psani: Photon (falesny server), mistni zdroje, odklad, ruseni, razeni."""

    def setUp(self):
        clean_state()
        self.calls = []
        self.got = threading.Event()

    def cb(self, gen, query, res, err):
        self.calls.append((gen, query, res, err))
        self.got.set()

    def suggester(self, delay=0.15, cfg=None, lang="cs"):
        sg = lm.Suggester(self.cb, cfg, lang, delay=delay)
        self.addCleanup(sg.stop)
        return sg

    def test_fold_and_spans(self):
        self.assertEqual(lm.fold("Můstek, Žluťoučký KŮŇ"), "mustek, zlutoucky kun")
        self.assertEqual(len(lm.fold("Straße Łódź")), len("Straße Łódź"))
        self.assertEqual(lm.match_spans("Karlovo náměstí", "karlovo nam"), [(0, 7), (8, 11)])
        self.assertEqual(lm.match_spans("Václavské náměstí", "NAMESTI"), [(10, 17)])
        self.assertEqual(lm.match_spans("Karlovo náměstí", "ovo"), [])        # jen zacatky slov
        self.assertEqual(lm.match_score({"name": "Karlovo náměstí"}, "karlovo nam"), 0)
        self.assertEqual(lm.match_score({"name": "Karlovo náměstí"}, "namesti karl"), 1)
        self.assertEqual(lm.match_score({"name": "Apetit", "address": "Vodičkova 30, Praha"}, "vodickova 30"), 2)
        self.assertIsNone(lm.match_score({"name": "Apetit", "address": "Praha"}, "vodickova"))

    def test_parse_photon(self):
        res = lm.parse_photon(fixture("photon-karlovo.json"))
        # 7 prvku: namesti jako plocha + 3 useky ulice stejneho jmena -> jedno; Trebic dvakrat -> jednou
        self.assertEqual([(p["name"], p["kind"]) for p in res],
                         [("Karlovo náměstí", "street"), ("SÚZ ČVUT - Výdejna Karlovo nám.", "poi"),
                          ("Karlovo nám.", "street")])
        sq = res[0]
        self.assertAlmostEqual(sq["lat"], 50.0757441)
        self.assertAlmostEqual(sq["lon"], 14.4199101)
        self.assertEqual(sq["address"], "obvod Praha 2, Praha, Česko")
        self.assertEqual(sq["osm"], "relation/2052491")
        s, n, w, e = sq["bbox"]
        self.assertTrue(s < n and w < e)
        self.assertEqual(res[1]["address"], "Resslova, Praha, Česko")
        house = lm.parse_photon(fixture("photon-vodickova-30.json"))
        self.assertEqual(house[2]["name"], "Vodičkova 2141/30")
        self.assertEqual(house[2]["kind"], "address")
        self.assertEqual(house[0]["address"], "Vodičkova 30, Praha, Česko")
        stops = lm.parse_photon(fixture("photon-mustek.json"))
        self.assertEqual([(p["name"], p["kind"]) for p in stops], [("Můstek", "stop"), ("Můstek", "poi")])
        self.assertTrue(lm.is_transit_place(stops[0]))                      # misto nabidne Odjezdy
        self.assertEqual(lm.parse_photon({"features": [{"geometry": {"coordinates": ["x"]}}, {}, 3]}), [])
        with self.assertRaises(lm.MapsError):
            lm.parse_photon([])

    def test_params(self):
        self.assertEqual(lm.photon_params("  karlovo   nam ", "cs", (50.08123, 14.4199)),
                         {"q": "karlovo nam", "limit": 7, "lang": "default", "lat": "50.08", "lon": "14.42"})
        self.assertEqual(lm.photon_params("x", "de")["lang"], "de")
        self.assertNotIn("lat", lm.photon_params("x", "en"))

    def test_local_ranking(self):
        items = [
            {"name": "Náměstí Míru", "lat": 50.0755, "lon": 14.4378, "source": "stop"},
            {"name": "Karlovo náměstí", "lat": 50.0757, "lon": 14.4199, "source": "recent"},
            {"name": "Domov", "address": "Náměstí Republiky 1, Praha", "lat": 50.088, "lon": 14.428,
             "source": "favorite"},
            {"name": "Staroměstské náměstí", "lat": 50.0875, "lon": 14.4208, "source": "recent"},
            {"name": "Karlovo náměstí", "lat": 50.0757, "lon": 14.4199, "source": "stop"},   # stejne misto
            {"name": "broken", "lat": "x", "lon": 1},
        ]
        center = (50.0757, 14.4199)
        res = lm.suggest_local("namesti", items, center)
        self.assertEqual([p["name"] for p in res][:2], ["Domov", "Karlovo náměstí"])   # oblibene, nedavne
        self.assertEqual([p["name"] for p in res],
                         ["Domov", "Karlovo náměstí", "Staroměstské náměstí", "Náměstí Míru"])
        self.assertEqual([p["name"] for p in lm.suggest_local("nam mir", items, center)], ["Náměstí Míru"])
        self.assertEqual(lm.suggest_local("n", items, center), [])                  # min. 2 znaky
        self.assertEqual(lm.suggest_local("esti", items, center), [])               # jen zacatky slov
        self.assertEqual(len(lm.suggest_local("namesti", items, center, limit=2)), 2)

    def test_merge(self):
        remote = lm.parse_photon(fixture("photon-vodickova-30.json"))
        local = [{"name": "Apetit", "lat": 50.0807439, "lon": 14.4247841, "source": "favorite"}]
        me = {"name": "My Location", "lat": 50.08, "lon": 14.42, "me": True}
        res = lm.merge_suggestions("vodickova 30", local, remote, (50.0757, 14.4199), me=me)
        self.assertEqual([p["name"] for p in res], ["My Location", "Apetit", "Vodičkova 2141/30", "Saint Tropez"])
        self.assertEqual(res[0]["source"], "me")
        self.assertEqual(res[1]["source"], "favorite")
        self.assertEqual(res[2]["source"], "online")
        self.assertTrue(500 < res[2]["distance"] < 700)
        self.assertEqual(len(lm.merge_suggestions("x", local * 3, remote * 5)), 3)        # bez duplicit
        self.assertEqual(len(lm.merge_suggestions("x", local, remote, limit=2)), 2)

    def test_recent_and_config(self):
        cfg = lm.load_config()
        self.assertTrue(cfg["suggest_online"])
        self.assertEqual(cfg["recent"], [])
        for i in range(lm.RECENT_MAX + 3):
            lm.add_recent(cfg, {"name": f"P{i}", "lat": 50 + i / 100, "lon": 14.0, "source": "online", "distance": 3})
        lm.add_recent(cfg, {"name": "p5", "lat": 50.05, "lon": 14.0})             # stejne misto nahoru
        lm.add_recent(cfg, {"name": "My Location", "lat": 1, "lon": 1, "me": True})
        self.assertEqual(len(cfg["recent"]), lm.RECENT_MAX)
        self.assertEqual(cfg["recent"][0], {"name": "p5", "lat": 50.05, "lon": 14.0})
        self.assertEqual(sum(1 for r in cfg["recent"] if lm.fold(r["name"]) == "p5"), 1)
        self.assertNotIn("distance", cfg["recent"][1])
        cfg["suggest_online"] = False
        cfg["suggest_url"] = "https://photon.example/api"
        cfg["recent"].append({"name": "bad"})
        lm.save_config(cfg)
        cfg = lm.load_config()
        self.assertFalse(cfg["suggest_online"])
        self.assertEqual(cfg["suggest_url"], "https://photon.example/api")
        self.assertEqual(len(cfg["recent"]), lm.RECENT_MAX)
        lm.save_config(dict(cfg, suggest_url="file:///etc/passwd", suggest_online="no"))
        cfg = lm.load_config()
        self.assertNotIn("suggest_url", cfg)
        self.assertTrue(cfg["suggest_online"])

    def test_debounce_only_last_query(self):
        sg = self.suggester(delay=0.2)
        for text in ("ka", "kar", "karl", "karlo", "karlovo"):
            sg.request(text, (50.08, 14.42))
            time.sleep(0.03)
        self.assertTrue(self.got.wait(5))
        time.sleep(0.4)
        self.assertEqual(SERVER.count("/photon"), 1)
        self.assertEqual(len(self.calls), 1)
        gen, query, res, err = self.calls[0]
        self.assertEqual((gen, query, err), (sg.gen, "karlovo", None))
        self.assertEqual(res[0]["name"], "Karlovo náměstí")
        q = SERVER.last_q("/photon")
        self.assertEqual((q["q"], q["limit"], q["lang"], q["lat"], q["lon"]),
                         ("karlovo", "7", "default", "50.08", "14.42"))
        self.assertTrue(SERVER.headers[-1]["User-Agent"].startswith("LuxOS-Maps/1.0"))
        # stejny dotaz ze stejneho okoli: z mezipameti, bez dalsiho pozadavku
        self.got.clear()
        sg.request("karlovo", (50.081, 14.421))
        self.assertTrue(self.got.wait(5))
        self.assertEqual(SERVER.count("/photon"), 1)

    def test_cancel_before_send(self):
        sg = self.suggester(delay=0.2)
        sg.request("karlovo")
        time.sleep(0.05)
        sg.cancel()
        time.sleep(0.5)
        self.assertEqual(SERVER.count("/photon"), 0)
        self.assertEqual(self.calls, [])

    def test_cancel_running_request(self):
        SERVER.delay = 1.0
        sg = self.suggester(delay=0.05)
        sg.request("karlovo")
        deadline = time.time() + 5
        while SERVER.count("/photon") < 1 and time.time() < deadline:
            time.sleep(0.01)
        t0 = time.monotonic()
        sg.request("mustek")                     # novy text: rozbehnuty pozadavek se prerusi
        self.assertTrue(self.got.wait(5))
        self.assertLess(time.monotonic() - t0, 1.9)  # neceka na dokonceni stareho dotazu (1 s) + novy (1 s)
        time.sleep(1.2)
        self.assertEqual([c[1] for c in self.calls], ["mustek"])         # stary vysledek se nikdy neohlasi
        self.assertEqual(self.calls[0][2][0]["kind"], "stop")
        self.assertEqual(SERVER.count("/photon"), 2)

    def test_offline_then_backoff(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                # nikdo neposloucha
        old = os.environ["LUXOS_MAPS_SUGGEST"]
        os.environ["LUXOS_MAPS_SUGGEST"] = f"http://127.0.0.1:{port}/api/"
        self.addCleanup(os.environ.__setitem__, "LUXOS_MAPS_SUGGEST", old)
        sg = self.suggester(delay=0.01)
        sg.request("karlovo")
        self.assertTrue(self.got.wait(5))
        self.assertEqual(self.calls[0][2], [])
        self.assertTrue(self.calls[0][3])
        self.assertEqual(sg.sent, 1)
        self.got.clear()
        sg.request("mustek")                     # 30 s pauza: bez dalsiho pokusu, hned "offline"
        self.assertTrue(self.got.wait(5))
        self.assertEqual(self.calls[1][3], "offline")
        self.assertEqual(sg.sent, 1)

    def providers_env(self, *urls):
        old = os.environ.get("LUXOS_MAPS_SUGGEST_PROVIDERS")
        os.environ["LUXOS_MAPS_SUGGEST_PROVIDERS"] = " ".join(urls)

        def restore():
            if old is None:
                os.environ.pop("LUXOS_MAPS_SUGGEST_PROVIDERS", None)
            else:
                os.environ["LUXOS_MAPS_SUGGEST_PROVIDERS"] = old
        self.addCleanup(restore)

    def two_providers(self):
        self.providers_env(SERVER.base + "/geocode/api", SERVER.base + "/photon/api/")

    def test_providers_config(self):
        old = os.environ.pop("LUXOS_MAPS_SUGGEST")
        self.addCleanup(os.environ.__setitem__, "LUXOS_MAPS_SUGGEST", old)
        self.assertEqual(lm.Suggester(self.cb).providers(), [lm.GEOCODER_URL, lm.PHOTON_URL])
        self.assertEqual(lm.Suggester(self.cb, {"suggest_url": "https://p.example/api"}).providers(),
                         ["https://p.example/api"])                    # vlastni Photon: jen on
        cfg = lm.load_config()
        lm.save_config(dict(cfg, suggest_providers=["https://a.example/geocode/api", "file:///x", 3,
                                                    "https://b.example/api"]))
        cfg = lm.load_config()
        self.assertEqual(cfg["suggest_providers"], ["https://a.example/geocode/api", "https://b.example/api"])
        self.assertEqual(lm.Suggester(self.cb, cfg).providers(), cfg["suggest_providers"])
        lm.save_config(dict(cfg, suggest_providers="https://x.example/api"))
        self.assertNotIn("suggest_providers", lm.load_config())
        self.assertTrue(lm.is_luxos_geocoder(lm.GEOCODER_URL))
        self.assertFalse(lm.is_luxos_geocoder(lm.PHOTON_URL))
        self.assertTrue(lm.in_coverage((50.08, 14.42)) and lm.in_coverage((48.15, 17.11)))     # Praha, Bratislava
        self.assertFalse(lm.in_coverage((52.52, 13.40)) or lm.in_coverage((48.21, 16.37)))   # Berlin, Viden
        self.assertEqual(lm.SUGGEST_DELAY, 0.15)

    def test_primary_geocoder(self):
        self.two_providers()
        sg = self.suggester(delay=0.01, lang="cs")
        sg.request("karlovo", (50.08, 14.42))
        self.assertTrue(self.got.wait(5))
        time.sleep(0.3)
        self.assertEqual(len(self.calls), 1)
        _gen, _q, res, err = self.calls[0]
        self.assertIsNone(err)
        self.assertEqual(res[0]["name"], "Karlovo náměstí")
        self.assertEqual({p["provider"] for p in res}, {"luxos"})
        self.assertEqual((SERVER.count("/geocode/api"), SERVER.count("/photon")), (1, 0))
        q = SERVER.last_q("/geocode/api")
        self.assertEqual((q["q"], q["lang"], q["lat"], q["lon"], q["limit"]), ("karlovo", "cs", "50.08", "14.42", "7"))

    def test_fallback_when_primary_slow(self):
        self.two_providers()
        SERVER.geocode = "slow"
        sg = self.suggester(delay=0.01)
        t0 = time.monotonic()
        sg.request("karlovo", (50.08, 14.42))
        self.assertTrue(self.got.wait(5))
        self.assertLess(time.monotonic() - t0, 1.9)                # 1,2 s na geocoder, pak hned Photon
        res = self.calls[0][2]
        self.assertEqual((res[0]["name"], res[0]["provider"]), ("Karlovo náměstí", "photon"))
        self.assertEqual(SERVER.last_q("/photon")["lang"], "default")
        self.assertGreater(sg.backoff[SERVER.base + "/geocode/api"], time.monotonic() + 20)
        # dalsi dotaz behem pauzy: rovnou Photon
        self.got.clear()
        sg.request("mustek", (50.08, 14.42))
        self.assertTrue(self.got.wait(5))
        self.assertEqual(SERVER.count("/geocode/api"), 1)
        self.assertEqual(SERVER.count("/photon"), 2)
        deadline = time.time() + 5            # pomaly geocoder dobehne (dalsi testy pocitaji soubezne pozadavky)
        while SERVER.active and time.time() < deadline:
            time.sleep(0.05)

    def test_fallback_when_primary_fails_or_empty(self):
        self.two_providers()
        for mode in ("fail", "empty"):
            SERVER.reset()
            SERVER.geocode = mode
            self.calls.clear()
            self.got.clear()
            sg = self.suggester(delay=0.01)
            sg.request("karlovo", (50.08, 14.42))
            self.assertTrue(self.got.wait(5))
            time.sleep(0.2)
            self.assertEqual(len(self.calls), 1, mode)
            _gen, _q, res, err = self.calls[0]
            self.assertIsNone(err, mode)
            self.assertEqual((res[0]["name"], res[0]["provider"]), ("Karlovo náměstí", "photon"), mode)
            self.assertEqual((SERVER.count("/geocode/api"), SERVER.count("/photon")), (1, 1), mode)

    def test_few_results_merged_with_photon(self):
        self.two_providers()
        SERVER.geocode = "one"
        sg = self.suggester(delay=0.01)
        sg.request("karlovo", (50.08, 14.42))
        deadline = time.time() + 5
        while len(self.calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.calls), 2)                   # nejdriv rychly vysledek, pak doplneny
        first, second = self.calls[0][2], self.calls[1][2]
        self.assertEqual(self.calls[0][0], self.calls[1][0])
        self.assertEqual([(p["name"], p["provider"]) for p in first], [("Karlovo náměstí", "luxos")])
        self.assertEqual(second[0], first[0])                  # co uz je videt, zustane nahore
        self.assertEqual([p["name"] for p in second[1:]], ["SÚZ ČVUT - Výdejna Karlovo nám.", "Karlovo nám."])
        self.assertEqual({p["provider"] for p in second[1:]}, {"photon"})

    def test_outside_coverage_photon_only(self):
        self.two_providers()
        sg = self.suggester(delay=0.01)
        sg.request("karlovo", (48.21, 16.37))                  # Viden
        self.assertTrue(self.got.wait(5))
        self.assertEqual((SERVER.count("/geocode/api"), SERVER.count("/photon")), (0, 1))
        self.assertEqual(self.calls[0][2][0]["provider"], "photon")

    def test_keepalive_and_stale_connection(self):
        self.providers_env(SERVER.base + "/geocode/api")
        sg = self.suggester(delay=0.01)
        for i, text in enumerate(("karlovo", "mustek", "vodickova")):
            self.got.clear()
            sg.request(text, (50.08, 14.42))
            self.assertTrue(self.got.wait(5))
            self.assertIsNone(self.calls[-1][3])
        self.assertEqual(len(set(SERVER.ports)), 1)          # tri dotazy jednim spojenim (bez noveho TLS)
        self.assertEqual(sg.sent, 3)
        SERVER.drop_idle = True                               # server zavre necinne spojeni
        for text in ("karlovo nam", "mustek x"):
            self.got.clear()
            sg.request(text, (50.08, 14.42))
            self.assertTrue(self.got.wait(5))
            self.assertIsNone(self.calls[-1][3], text)        # nove spojeni bez chyby a bez pauzy
        self.assertEqual(sg.backoff, {})
        self.assertEqual(sg.sent, 5)
        self.assertEqual(len(set(SERVER.ports)), 2)          # stare spojeni jeste jednou, pak nove
        sg.stop()
        self.assertEqual(sg.conns, {})

    def test_busy_backoff(self):
        SERVER.fail = True                        # 503
        sg = self.suggester(delay=0.01)
        sg.request("karlovo")
        self.assertTrue(self.got.wait(5))
        self.assertIn("503", self.calls[0][3])
        self.assertGreater(sg.backoff_until, time.monotonic() + 20)


class TestPackaging(unittest.TestCase):
    def strings(self):
        with open(os.path.join(FILES, "luxos-maps"), encoding="utf-8") as f:
            src = f.read()
        found = set(re.findall(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)', src))
        # vicerakove texty _( "..." "..." )
        for m in re.finditer(r'_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', src):
            found.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
        found |= {t for _k, t in re.findall(r'\("(car|bike|walk|transit)", "([^"]+)"\)', src)}
        app = types.SimpleNamespace()
        exec(compile(re.search(r"^NEARBY_LABELS = .*?\)\)\n", src, re.S | re.M).group(0), "labels", "exec"),
             {}, app.__dict__)
        found |= {t for _k, t in app.NEARBY_LABELS}
        found |= {name for name, _c in lm.TRANSIT_MODES.values()} | {"Public transport"}
        found |= set(lm.TURNS.values())
        found |= {"Depart", "Continue straight", "Arrive at your destination", "Destination is on the left", "Destination is on the right",
                  "Enter the roundabout and take exit %s", "Enter the roundabout", "Keep left", "Keep right",
                  "Merge", "Take the ramp", "Take the exit", "%d min", "%d h %d min", "%d h"}
        return {s.encode().decode("unicode_escape").encode("latin-1").decode("utf-8") for s in found}

    def test_translations(self):
        strings = self.strings()
        self.assertGreater(len(strings), 60)
        for lang in LANGS:
            with open(os.path.join(ROOT, "luxos-i18n", "files", f"{lang}.tsv"), encoding="utf-8") as f:
                tr = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            missing = sorted(s for s in strings if not tr.get(s))
            self.assertEqual(missing, [], lang)
            for s in strings:
                self.assertEqual(tr[s].count("%s"), s.count("%s"), (lang, s))
                self.assertEqual(tr[s].count("%d"), s.count("%d"), (lang, s))

    def test_desktop_file(self):
        with open(os.path.join(FILES, "luxos-maps.desktop"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("MimeType=x-scheme-handler/geo;", text)
        self.assertIn("Exec=luxos-maps %u", text)
        self.assertIn("Name[cs]=Mapy", text)
        for lang in LANGS:
            self.assertIn(f"Name[{lang}]=", text)
            self.assertIn(f"Comment[{lang}]=", text)


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
        cls.Gtk, cls.GLib, cls.Gdk = Gtk, GLib, Gdk
        if Gdk.Screen.get_default() is None:
            raise unittest.SkipTest("no X display")
        loader = importlib.machinery.SourceFileLoader("luxos_maps_app", os.path.join(FILES, "luxos-maps"))
        spec = importlib.util.spec_from_loader("luxos_maps_app", loader)
        cls.app = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.app)
        provider = Gtk.CssProvider()
        provider.load_from_data(cls.app.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def setUp(self):
        clean_state()

    def pump(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if cond():
                return True
            time.sleep(0.02)
        return False

    def settle(self, t=0.6):
        self.pump(lambda: False, t)

    def shot(self, win, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if not out:
            return
        self.settle(0.8)
        gw = win.get_window()
        pix = self.Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        os.makedirs(out, exist_ok=True)
        pix.savev(os.path.join(out, name), "png", [], [])

    def window(self, view=None, **cfg):
        c = lm.load_config()
        c.update(cfg)
        if view:
            c["view"] = dict(zip(("lat", "lon", "zoom"), view))
        lm.save_config(c)
        win = self.app.MapsWindow()
        win.resize(1100, 720)
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(self.pump(lambda: win.map.get_allocated_width() > 300))
        return win

    def tiles_loaded(self, win):
        st = win.map.store

        def ok():
            with st.cond:
                return bool(win.map.mem) and not st.busy and not st.net_queue and not st.disk_queue \
                    and win.map.missing_sent == ()
        return ok

    def test_start_tiles_attribution(self):
        win = self.window((50.0875, 14.4208, 14))
        self.assertTrue(win.get_titlebar().get_visible())
        self.assertTrue(win.get_titlebar().get_show_close_button())
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.settle(0.4)
        w, h = win.map.get_allocated_width(), win.map.get_allocated_height()
        visible = (w // 256 + 2) * (h // 256 + 2)
        self.assertLessEqual(SERVER.count("/tiles/"), visible)       # jen viditelne, zadne prednacitani
        self.assertTrue(all(z == 14 for z, _x, _y in win.map.mem))
        self.assertIn("OpenStreetMap", win.attribution.get_text())
        self.assertTrue(win.attribution.get_mapped())
        self.assertEqual(SERVER.count("/ip"), 0)                      # poloha jen po souhlasu
        self.assertEqual(SERVER.count("/search"), 0)
        # zoom klavesou a tazeni mysi
        z = win.map.zoom
        ev = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
        ev.keyval = self.Gdk.KEY_plus
        ev.state = 0
        win.map.grab_focus()
        win.on_key(win, ev)
        self.assertTrue(self.pump(lambda: win.map.anim is None and abs(win.map.zoom - z - 1) < 1e-6))
        mx = win.map.mx
        E = types.SimpleNamespace
        press = E(type=self.Gdk.EventType.BUTTON_PRESS, button=1, x=500, y=300, time=1000, state=0)
        win.map.on_press(win.map, press)
        win.map.on_motion(win.map, E(x=400, y=300, time=1300))
        win.map.on_release(win.map, E(button=1, x=400, y=300, time=1600))
        self.assertAlmostEqual(win.map.mx - mx, 100 / win.map.scale, places=9)
        self.shot(win, "maps-start.png")
        win.save_view()
        self.assertAlmostEqual(lm.load_config()["view"]["zoom"], 15)

    def test_search_place_favorite_route(self):
        win = self.window((50.08, 14.42, 13))
        win.search_entry.set_text("Karlovo náměstí")
        win.search_entry.emit("activate")
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "place"))   # 1 vysledek
        self.assertEqual(SERVER.count("/search"), 1)
        self.assertIn("viewbox", [q for p, q in SERVER.requests if p == "/search"][-1])
        self.assertEqual(len(win.res_list.get_children()), 1)
        win.search_entry.set_text("náměstí Praha")
        win.search_entry.emit("activate")
        self.assertTrue(self.pump(lambda: len(win.res_list.get_children()) == 3))
        self.assertEqual(win.stack.get_visible_child_name(), "results")
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-search.png")
        win.res_list.emit("row-activated", win.res_list.get_row_at_index(2))
        self.assertEqual(win.stack.get_visible_child_name(), "place")
        self.assertEqual(win.pl_name.get_text(), "Karlovo náměstí")
        self.assertIsNotNone(win.map.marker)
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        win.toggle_favorite()
        self.assertEqual(lm.load_config()["favorites"][0]["name"], "Karlovo náměstí")
        self.assertEqual(win.pl_star.get_label(), self.app._("Saved"))
        self.assertEqual(len(win.fav_list.get_children()), 1)
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-place.png")
        win.copy_geo()
        self.assertTrue(self.pump(lambda: (self.Gtk.Clipboard.get(self.Gdk.SELECTION_CLIPBOARD).wait_for_text()
                                           or "").startswith("geo:50.0757,14.4199?z=")))
        # trasa z Staromestskeho namesti
        win.directions_to(win.place)
        win.from_entry.set_text("50.0875, 14.4208")
        win.from_entry.emit("activate")
        self.assertTrue(self.pump(lambda: len(win.steps_list.get_children()) > 5))
        self.assertEqual(SERVER.count("/routed-car/"), 1)
        self.assertEqual(win.rt_time.get_text(), "6 min")
        self.assertEqual(win.rt_dist.get_text(), "2.4 km")
        self.assertIsNotNone(win.map.route)
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        win.steps_list.emit("row-activated", win.steps_list.get_row_at_index(4))
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        win.map.fit_bbox(50.084, 50.093, 14.398, 14.424)
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-route.png")
        win.mode_buttons["walk"].set_active(True)
        self.assertTrue(self.pump(lambda: SERVER.count("/routed-foot/") == 1 and win.map.route
                                  and win.map.route["mode"] == "walk"))
        self.assertEqual(lm.load_config()["mode"], "walk")
        win.close_directions()
        self.assertIsNone(win.map.route)

    def key(self, win, keyval):
        """Stisk klavesy pres okno (jako skutecna klavesnice: okno -> pole s fokusem)."""
        ev = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
        ev.keyval = keyval
        ev.state = 0
        ev.window = win.get_window()
        ev.set_device(self.Gdk.Display.get_default().get_default_seat().get_keyboard())
        return win.emit("key-press-event", ev)

    def type_text(self, entry, text):
        for i in range(1, len(text) + 1):          # rychle psani: pod 150 ms mezi znaky
            entry.set_text(text[:i])
            entry.set_position(-1)
            self.settle(0.03)

    def test_suggestions_search_and_route(self):
        fav = {"name": "Karlín", "lat": 50.0925, "lon": 14.4517, "address": "Praha 8"}
        win = self.window((50.08, 14.42, 15), favorites=[fav], location_consent=True)
        Gdk = self.Gdk
        sb = win.suggest["search"]
        win.search_entry.grab_focus()
        self.type_text(win.search_entry, "karl")
        self.assertTrue(sb.visible())                                   # oblibene hned, bez site
        self.assertEqual(sb.list.get_row_at_index(0).place["name"], "Karlín")
        self.assertTrue(self.pump(lambda: sb.remote))
        self.settle(0.4)
        self.assertEqual(SERVER.count("/photon"), 1)                    # jen posledni text po 150 ms
        self.assertEqual(SERVER.last_q("/photon")["q"], "karl")
        self.assertEqual(SERVER.last_q("/photon")["lat"], "50.08")
        names = [r.place["name"] for r in sb.list.get_children()]
        self.assertEqual(names, ["Karlín", "Karlovo náměstí", "SÚZ ČVUT - Výdejna Karlovo nám.", "Karlovo nám."])
        row1 = self.find_texts(sb.list.get_row_at_index(1))
        self.assertIn("obvod Praha 2, Praha, Česko", row1)
        self.assertTrue(any(t.endswith(" m") for t in row1))           # vzdalenost od stredu mapy
        self.assertIn("Photon", sb.footer.get_text())
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-suggest-search.png")
        # sipky + Enter: vybere Karlovo namesti bez dalsiho hledani v Nominatim
        self.assertTrue(self.key(win, Gdk.KEY_Down))
        self.assertTrue(self.key(win, Gdk.KEY_Down))
        self.assertEqual(sb.list.get_selected_row().get_index(), 1)
        self.assertTrue(self.key(win, Gdk.KEY_Up))
        self.assertTrue(self.key(win, Gdk.KEY_Down))
        self.assertTrue(self.key(win, Gdk.KEY_Return))
        self.assertFalse(sb.visible())
        self.assertEqual(win.stack.get_visible_child_name(), "place")
        self.assertEqual(win.pl_name.get_text(), "Karlovo náměstí")
        self.assertEqual(win.search_entry.get_text(), "Karlovo náměstí")
        self.settle(0.4)
        self.assertFalse(sb.visible())                                  # vyber nabidku znovu neotevre
        self.assertEqual(SERVER.count("/search"), 0)
        self.assertEqual(SERVER.count("/photon"), 1)
        self.assertEqual(lm.load_config()["recent"][0]["name"], "Karlovo náměstí")
        # trasa: Moje poloha prvni, pak zastavka z Photonu; vyber prepocita trasu
        win.directions_to(win.place)
        fb = win.suggest["from"]
        win.from_entry.grab_focus()
        self.type_text(win.from_entry, "mustek")
        self.assertTrue(self.pump(lambda: fb.visible() and fb.remote))
        rows = fb.list.get_children()
        self.assertTrue(rows[0].place.get("me"))
        self.assertEqual(self.find_texts(rows[0])[0], self.app._("My Location"))
        self.assertEqual([(r.place["name"], self.app.suggestion_kind(r.place)) for r in rows[1:]],
                         [("Můstek", "stop"), ("Můstek", "poi")])
        self.key(win, Gdk.KEY_Down)
        self.key(win, Gdk.KEY_Down)
        self.shot(win, "maps-suggest-route.png")
        self.assertTrue(self.key(win, Gdk.KEY_Return))
        self.assertFalse(fb.visible())
        self.assertEqual(win.from_entry.get_text(), "Můstek")
        self.assertTrue(lm.is_transit_place(win.route_from))
        self.assertTrue(self.pump(lambda: win.map.route is not None and len(win.steps_list.get_children()) > 3))
        self.assertEqual(SERVER.count("/routed-car/"), 1)
        self.assertTrue(any(p.startswith("/routed-car/route/v1/driving/14.423345,50.083413;")
                            for p, _q in SERVER.requests))                  # souradnice primo z Photonu
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-suggest-route-done.png")
        # Esc zavre nabidku, text zustane; klik mysi na radek (nedavne misto je mezi navrhy)
        tb = win.suggest["to"]
        win.to_entry.grab_focus()
        self.type_text(win.to_entry, "karlov")
        self.assertTrue(self.pump(lambda: tb.visible() and tb.remote))
        self.assertEqual(tb.list.get_row_at_index(1).place["source"], "recent")
        self.assertTrue(self.key(win, Gdk.KEY_Escape))
        self.assertFalse(tb.visible())
        self.assertEqual(win.to_entry.get_text(), "karlov")
        self.type_text(win.to_entry, "karlovo")
        self.assertTrue(self.pump(lambda: tb.visible()))
        tb.list.emit("row-activated", tb.list.get_row_at_index(1))
        self.assertFalse(tb.visible())
        self.assertEqual(win.to_entry.get_text(), "Karlovo náměstí")
        self.assertEqual(win.route_to["name"], "Karlovo náměstí")
        self.assertTrue(self.pump(lambda: win.map.route is not None))      # stejna trasa: z pameti
        # bez naseptavani online: jen mistni zdroje, zadny pozadavek na Photon
        win.suggest_item.set_active(False)
        self.assertFalse(lm.load_config()["suggest_online"])
        n = SERVER.count("/photon")
        win.search_entry.grab_focus()
        win.search_entry.set_text("")
        self.type_text(win.search_entry, "karl")
        self.settle(0.5)
        self.assertEqual(SERVER.count("/photon"), n)
        self.assertEqual([r.place["name"] for r in sb.list.get_children()], ["Karlín", "Karlovo náměstí"])
        self.assertFalse(sb.footer.get_visible())

    def test_geo_uri_dark_offline(self):
        win = self.window((20, 0, 1.6))
        win.cfg["appearance"] = "dark"
        win.apply_appearance()
        self.assertTrue(win.map.dark)
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-dark.png")
        win.handle_args(["geo:50.0875,14.4208?z=17&q=50.0875,14.4208(Staroměstské náměstí)"])
        self.assertEqual(win.pl_name.get_text(), "Staroměstské náměstí")
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertAlmostEqual(win.map.zoom, 17)
        win.handle_args(["geo:0,0?q=Karlovo%20n%C3%A1m%C4%9Bst%C3%AD"])
        self.assertTrue(self.pump(lambda: len(win.res_list.get_children()) == 1))
        self.assertEqual(win.pl_name.get_text(), "Karlovo náměstí")
        # bez site: upozorneni, mapa z mezipameti
        SERVER.fail = True
        win.map.fly_to(-33.86, 151.2, 12)
        self.assertTrue(self.pump(lambda: win.offline_rev.get_reveal_child(), timeout=8))
        self.shot(win, "maps-offline.png")

    def find_texts(self, widget):
        out = []
        if isinstance(widget, self.Gtk.Label):
            out.append(widget.get_text())
        if isinstance(widget, self.Gtk.Container):
            for c in widget.get_children():
                out += self.find_texts(c)
        return out

    def find_classes(self, widget, cls):
        out = []
        if isinstance(widget, self.Gtk.Label) and widget.get_style_context().has_class(cls):
            out.append(widget.get_text())
        if isinstance(widget, self.Gtk.Container):
            for c in widget.get_children():
                out += self.find_classes(c, cls)
        return out

    def test_transit_directions_and_departures(self):
        win = self.window((50.083, 14.41, 14), mode="car")
        _ = self.app._
        self.assertFalse(win.transit_opts.get_visible())
        win.mode_buttons["transit"].set_active(True)
        self.assertTrue(win.transit_opts.get_visible())
        self.assertFalse(win.steps_list.get_visible())
        self.assertEqual(lm.load_config()["mode"], "transit")
        self.assertIn("Transitous", win.rt_attr.get_text())
        win.directions_to({"name": "Pražský hrad", "lat": 50.0905, "lon": 14.3995})
        win.from_entry.set_text("50.0757, 14.4199")
        win.from_entry.emit("activate")
        self.assertTrue(self.pump(lambda: len(win.itin_list.get_children()) == 3))
        self.assertEqual(SERVER.count("/transitous/plan"), 1)
        self.assertEqual(SERVER.count("/routed-"), 0)
        self.assertIn("fromPlace=50.075700%2C14.419900", SERVER.last_raw("/transitous"))
        self.assertEqual(win.rt_dist.get_text(), "19:10 – 19:33")
        self.assertEqual(win.rt_time.get_text(), "23 min")
        row0 = self.find_texts(win.itin_list.get_row_at_index(0))
        self.assertIn("19:10 – 19:33", row0)
        self.assertIn("+" + _("%d min") % 1, row0)                    # zpozdeni tramvaje
        self.assertEqual(len(win.legs_list.get_children()), 3)
        self.assertEqual(win.map.route["mode"], "transit")
        self.assertEqual(len(win.map.route["legs"]), 3)
        self.assertEqual([lg["walk"] for lg in win.map.route["legs"]], [True, False, True])
        self.assertEqual([s["name"] for s in win.map.stops], ["Karlovo náměstí", "Malostranské náměstí"])
        legs = self.find_texts(win.legs_list)
        self.assertIn(_("Tram") + " 22 → Vypich", legs)
        self.assertTrue(any(_("Platform %s") % "C" in t for t in legs), legs)
        self.assertEqual(self.find_classes(win.legs_list, "late"), ["+" + _("%d min") % 1])
        win.itin_list.select_row(win.itin_list.get_row_at_index(1))
        self.assertEqual(win.rt_dist.get_text(), "19:16 – 19:39")
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-transit.png")
        # klik na usek tramvaje: odjezdy z te zastavky (stopId)
        win.legs_list.emit("row-activated", win.legs_list.get_row_at_index(1))
        self.assertEqual(win.stack.get_visible_child_name(), "departures")
        self.assertTrue(self.pump(lambda: len(win.dep_list.get_children()) > 0))
        self.assertIn("stopId=cz-PID_U237Z3P", SERVER.last_raw("/transitous"))
        self.assertIn("n=20", SERVER.last_raw("/transitous"))
        self.assertEqual(win.dep_name.get_text(), "Karlovo náměstí")
        self.assertIsNotNone(win.dep_timer)                            # obnovuje se, dokud je videt
        win.departures_back()
        self.assertEqual(win.stack.get_visible_child_name(), "directions")
        # klik na zastavku na mape
        x, y = win.map.latlon_to_screen(win.map.stops[1]["lat"], win.map.stops[1]["lon"])
        self.assertEqual(win.map.hit_marker(x, y), ("stop", 1))
        win.on_marker_click(("stop", 1))
        self.assertEqual(win.dep_name.get_text(), "Malostranské náměstí")
        self.assertTrue(self.pump(lambda: "stopId=cz-PID_U361Z2P" in SERVER.last_raw("/transitous")))
        win.departures_back()
        # cela tabule Karlova namesti (okoli bodu): 20 odjezdu, zpozdeni cervene, preskrtnuty planovany cas
        win.close_directions()
        win.show_departures({"name": "Karlovo náměstí", "lat": 50.0759, "lon": 14.419612})
        self.assertTrue(self.pump(lambda: len(win.dep_list.get_children()) == 20))
        self.assertIn("center=50.075900%2C14.419612", SERVER.last_raw("/transitous"))
        self.assertIn("radius=300", SERVER.last_raw("/transitous"))
        late = self.find_classes(win.dep_list, "late")
        self.assertGreaterEqual(len(late), 3)
        self.assertTrue(all(t.startswith("+") for t in late))
        row = self.find_texts(win.dep_list.get_row_at_index(6))
        self.assertIn("19:11", row)
        self.assertIn("19:10", row)                                     # planovany cas (preskrtnuty)
        self.assertIn("Vypich", row)
        self.assertIn(self.app._("Updated %s") % time.strftime("%H:%M"), win.dep_updated.get_text())
        n = SERVER.count("/transitous/stoptimes")
        win.load_departures(True)                                       # Obnovit hned: z mezipameti
        self.settle(0.4)
        self.assertEqual(SERVER.count("/transitous/stoptimes"), n)
        age_api_cache(20)
        win.load_departures(True)                                       # Obnovit po 20 s: znovu
        self.assertTrue(self.pump(lambda: SERVER.count("/transitous/stoptimes") == n + 1))
        self.assertTrue(self.pump(lambda: len(win.dep_list.get_children()) == 20))
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-departures.png")
        win.dep_kind["arrivals"].set_active(True)
        self.assertTrue(self.pump(lambda: "arriveBy=true" in SERVER.last_raw("/transitous")))
        self.assertEqual(win.dep_title.get_text(), _("Arrivals").upper())
        ev = self.Gdk.Event.new(self.Gdk.EventType.KEY_PRESS)
        ev.keyval = self.Gdk.KEY_Escape
        ev.state = 0
        win.map.grab_focus()
        win.on_key(win, ev)
        self.assertNotEqual(win.stack.get_visible_child_name(), "departures")
        # sluzba pretizena: srozumitelna hlaska
        SERVER.busy = True
        win.show_directions(False)
        win.when_combo.set_active_id("depart")
        win.when_entry.set_text("8:15")
        win.compute_route()
        self.assertTrue(self.pump(lambda: not win.rt_spinner.get_property("active")))
        self.assertIn("time=", SERVER.last_raw("/transitous"))
        self.assertEqual(win.rt_status.get_text(),
                         _("The public transport service is busy. Try again in a moment."))
        win.when_entry.set_text("99:99")
        win.compute_route()
        self.assertEqual(win.rt_status.get_text(), _("Enter the time as HH:MM."))

    def test_nearby_and_place_departures(self):
        win = self.window((50.0757, 14.4199, 16))
        _ = self.app._
        win.select_place({"name": "Karlovo náměstí", "lat": 50.0757, "lon": 14.4199, "category": "place",
                          "type": "square"}, zoom=16)
        self.assertFalse(win.pl_departures.get_visible())
        items = win.pl_nearby.get_popup().get_children()
        self.assertEqual(len(items), 13)
        self.assertIn(_("Public Transport Stops"), [i.get_label() for i in items])
        items[[i.get_label() for i in items].index(_("Pharmacies"))].activate()
        self.assertTrue(self.pump(lambda: SERVER.count("/overpass") == 1 and not win.res_spinner.get_property(
            "active")))
        self.assertIn('["amenity"="pharmacy"]', SERVER.last_q("/overpass")["data"])
        self.assertEqual(win.res_status.get_text(), _("Nothing found nearby."))
        win.show_nearby(50.0757, 14.4199, "public_transport")
        self.assertTrue(self.pump(lambda: len(win.res_list.get_children()) == 2))
        self.assertIn("around:600,", SERVER.last_q("/overpass")["data"])
        self.assertEqual(win.res_title.get_text(), _("Public Transport Stops").upper())
        self.assertEqual([r.place["name"] for r in win.res_list.get_children()],
                         ["Karlovo náměstí", "Novoměstská radnice"])
        self.assertEqual(len(win.map.results), 2)
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-nearby.png")
        win.res_list.emit("row-activated", win.res_list.get_row_at_index(0))
        self.assertEqual(win.stack.get_visible_child_name(), "place")
        self.assertTrue(win.pl_departures.get_visible())
        self.assertIn(_("Platforms: %s") % "", win.pl_extra.get_text())
        win.pl_departures.clicked()
        self.assertEqual(win.stack.get_visible_child_name(), "departures")
        self.assertTrue(self.pump(lambda: len(win.dep_list.get_children()) > 0))
        self.assertIn("radius=300", SERVER.last_raw("/transitous"))
        win.departures_back()
        self.assertEqual(win.stack.get_visible_child_name(), "place")
        win.place_back()
        self.assertEqual(win.stack.get_visible_child_name(), "results")   # zpet na seznam okoli
        # klik na bod vysledku na mape
        x, y = win.map.latlon_to_screen(win.map.results[1]["lat"], win.map.results[1]["lon"])
        hit = win.map.hit_marker(x, y)
        self.assertEqual(hit, ("result", 1))
        win.on_marker_click(hit)
        self.assertEqual(win.pl_name.get_text(), "Novoměstská radnice")
        # Overpass pretizeny
        SERVER.busy = True
        win.show_nearby(50.0757, 14.4199, "cafes")
        self.assertTrue(self.pump(lambda: win.res_status.get_visible()))
        self.assertEqual(win.res_status.get_text(),
                         _("The map data service (Overpass) is busy. Try again in a moment."))

    def test_location_consent(self):
        win = self.window((50.08, 14.42, 12))
        asked = []
        win.ask_consent = lambda: asked.append(1) or False
        win.on_locate()
        self.assertEqual(asked, [1])
        self.settle(0.3)
        self.assertEqual(SERVER.count("/ip"), 0)
        self.assertFalse(lm.load_config()["location_consent"])
        win.ask_consent = lambda: True
        win.on_locate()
        self.assertTrue(self.pump(lambda: win.map.me is not None))
        self.assertTrue(lm.load_config()["location_consent"])
        self.assertTrue(win.consent_item.get_active())
        self.assertEqual(win.map.me["source"], "ip")
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        self.assertAlmostEqual(win.map.zoom, 11)
        ok = self.pump(self.tiles_loaded(win))
        st = win.map.store
        self.assertTrue(ok, (len(win.map.mem), st.busy, list(st.net_queue), list(st.disk_queue), win.map.missing_sent,
                             win.map.failed))
        self.shot(win, "maps-location.png")
        # trasa z moji polohy
        win.show_directions()
        self.assertEqual(win.from_entry.get_text(), self.app._("My Location"))
        win.consent_item.set_active(False)
        self.assertFalse(lm.load_config()["location_consent"])
        self.assertIsNone(win.map.me)

    def test_live_phone_tracking(self):
        if not shutil.which("dbus-daemon"):
            self.skipTest("dbus-daemon missing")
        fake = FakeCompanion()
        self.addCleanup(fake.close)
        os.environ["LUXOS_MAPS_COMPANION_BUS"] = fake.address
        os.environ["LUXOS_MAPS_PHONE"] = "1"
        self.addCleanup(os.environ.pop, "LUXOS_MAPS_COMPANION_BUS", None)
        self.addCleanup(os.environ.__setitem__, "LUXOS_MAPS_PHONE", "0")
        fake.loc = dict(PHONE_FIX)
        win = self.window(view=(50.0, 14.0, 12), location_consent=True)
        win.on_locate()
        self.assertTrue(self.pump(lambda: win.map.me is not None))
        self.assertEqual(win.map.me["source"], "phone")
        self.assertTrue(win.tracking and win.follow)
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        # telefon se pohne: modry bod jde za nim, mapa ho sleduje
        fake.emit(dict(PHONE_FIX, latitude=50.0800, longitude=14.4400, accuracy=4.0))
        self.assertTrue(self.pump(lambda: abs(win.map.me["lat"] - 50.08) < 1e-9))
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        lat, lon = self.app.lm.from_world(win.map.mx, win.map.my)
        self.assertAlmostEqual(lat, 50.08, places=4)
        self.assertAlmostEqual(lon, 14.44, places=4)
        self.shot(win, "maps-phone-tracking.png")
        # uzivatel mapu posune: dalsi polohy jen posouvaji bod
        win.stop_follow()
        fake.emit(dict(PHONE_FIX, latitude=50.0900, longitude=14.4500))
        self.assertTrue(self.pump(lambda: abs(win.map.me["lat"] - 50.09) < 1e-9))
        lat2, _lon2 = self.app.lm.from_world(win.map.mx, win.map.my)
        self.assertAlmostEqual(lat2, lat, places=6)
        # odpojeni / zastarani: sedy bod
        fake.emit({"valid": False})
        self.assertTrue(self.pump(lambda: win.map.me.get("stale")))
        # sdileni vypnute v nastaveni Telefon: polohy se ignoruji
        path = os.path.join(TMP, "config", "luxos", "companion.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"share_location": False}, f)
        self.addCleanup(os.remove, path)
        fake.emit(dict(PHONE_FIX, latitude=10.0))
        self.settle(0.3)
        self.assertTrue(win.map.me.get("stale"))
        # odvolani souhlasu: konec sledovani
        win.consent_item.set_active(False)
        self.assertFalse(win.tracking)
        self.assertIsNone(win.phone_sub)

    def overflow(self, page):
        """Viditelne widgety stranky panelu, ktere presahuji jeji sirku (vodorovne preteceni)."""
        width = page.get_allocated_width()
        bad = []

        def walk(w):
            if not w.get_visible() or not w.get_mapped():
                return
            pos = w.translate_coordinates(page, 0, 0)
            if pos and (pos[0] < -1 or pos[0] + w.get_allocated_width() > width + 1):
                bad.append((type(w).__name__, pos[0], w.get_allocated_width(),
                            w.get_text() if isinstance(w, self.Gtk.Label) else ""))
            if isinstance(w, self.Gtk.Container):
                for c in w.get_children():
                    walk(c)
        walk(page)
        return bad

    def test_long_connection_fits_sidebar(self):
        """Dlouhe spojeni (Ex1 (IC 547) > M1 (Os 3751) > tramvaj, 7 useku): odznaky se zalamuji, nic nepretece
        panel 280-560 px; stejne odjezdy a vysledky hledani."""
        win = self.window((50.1, 15.1, 9), mode="transit")
        win.directions_to({"name": "Fakultní nemocnice Hradec Králové", "lat": 50.1985, "lon": 15.802})
        win.set_endpoint("from", {"name": "Praha hlavní nádraží", "lat": 50.0835, "lon": 14.434})
        self.assertTrue(self.pump(lambda: len(win.itin_list.get_children()) == 2))
        self.assertTrue(self.pump(lambda: len(win.legs_list.get_children()) == 7))
        row0 = win.itin_list.get_row_at_index(0)
        strip = [w for w in self.descendants(row0) if isinstance(w, self.app.BadgeStrip)]
        self.assertEqual(len(strip), 1)
        strip = strip[0]
        self.assertEqual([c.text for c in strip.chips if not c.walk], ["Ex1 (IC 547)", "M1 (Os 3751)", "5"])
        self.assertTrue(all(c.width <= self.app.BADGE_MAX for c in strip.chips))
        badges = [w for w in self.descendants(win.legs_list) if isinstance(w, self.app.LineBadge)]
        self.assertEqual(len(badges), 7)
        self.assertTrue(all(b.get_size_request()[0] <= self.app.LEG_BADGE_MAX for b in badges))
        self.assertEqual(badges[1].get_tooltip_text(), "Ex1 (IC 547)")         # zkraceny, cely v tipu
        page = win.stack.get_child_by_name("directions")
        lines = []
        for width in (lm.SIDEBAR_MIN, 360, lm.SIDEBAR_MAX):
            win.paned.set_position(width)
            self.settle(0.4)
            self.assertEqual(win.stack.get_allocated_width(), width)
            # nejmensi sirka obsahu panelu (vsechny stranky Gtk.Stack) se vejde do nejuzsiho panelu
            self.assertLessEqual(win.stack.get_preferred_width()[0], lm.SIDEBAR_MIN)
            self.assertEqual(self.overflow(page), [], width)
            # 7 odznaku: na 280 px na vic radku, v sirsim panelu na mene radku
            rows = {y for _x, y, _c in strip.place(strip.get_allocated_width())}
            lines.append(len(rows))
            self.assertEqual(strip.get_allocated_height(), max(rows) + self.app.BadgeChip.H)
            self.assertTrue(self.pump(lambda: win.map.anim is None))
            self.shot(win, "maps-long-connection-%d.png" % width)
            if width == lm.SIDEBAR_MIN:              # podrobnosti spojeni (posunuto dolu)
                adj = page.get_vadjustment()
                adj.set_value(adj.get_upper())
                self.shot(win, "maps-long-connection-%d-legs.png" % width)
                adj.set_value(0)
        self.assertGreater(lines[0], 2)
        self.assertEqual(lines, sorted(lines, reverse=True))
        self.assertLess(lines[-1], lines[0])
        # odjezdy a vysledky hledani v nejuzsim panelu
        win.paned.set_position(lm.SIDEBAR_MIN)
        win.show_departures({"name": "Karlovo náměstí", "lat": 50.0759, "lon": 14.419612})
        self.assertTrue(self.pump(lambda: len(win.dep_list.get_children()) == 20))
        self.settle(0.4)
        self.assertLessEqual(win.stack.get_preferred_width()[0], lm.SIDEBAR_MIN)
        self.assertEqual(self.overflow(win.stack.get_child_by_name("departures")), [])
        self.shot(win, "maps-departures-280.png")
        win.departures_back()
        win.search_entry.set_text("náměstí Praha")
        win.search_entry.emit("activate")
        self.assertTrue(self.pump(lambda: len(win.res_list.get_children()) == 3))
        self.settle(0.4)
        self.assertLessEqual(win.stack.get_preferred_width()[0], lm.SIDEBAR_MIN)
        self.assertEqual(self.overflow(win.stack.get_child_by_name("results")), [])
        self.shot(win, "maps-results-280.png")

    def descendants(self, w):
        out = [w]
        if isinstance(w, self.Gtk.Container):
            for c in w.get_children():
                out += self.descendants(c)
        return out

    def test_sidebar_resize_persisted(self):
        win = self.window((50.0875, 14.4208, 14))
        self.assertTrue(self.pump(lambda: win.paned.get_position() == self.app.SIDEBAR_DEFAULT))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        # tazeni oddelovace (Gtk.Paned): sirka se pamatuje v maps.json
        win.paned.set_position(450)
        self.settle(0.3)
        self.assertEqual(win.side_width, 450)
        self.assertEqual(win.stack.get_allocated_width(), 450)
        self.assertTrue(self.pump(lambda: win.save_id is None, 5))           # ulozi se se zobrazenim mapy
        self.assertEqual(lm.load_config()["sidebar_width"], 450)
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-sidebar-wide.png")
        # nejvys SIDEBAR_MAX a mapa aspon MAP_MIN_WIDTH; nejmene SIDEBAR_MIN
        win.paned.set_position(2000)
        self.settle(0.3)
        width = win.paned.get_allocated_width()
        self.assertEqual(win.paned.get_position(), min(lm.SIDEBAR_MAX, width - self.app.MAP_MIN_WIDTH))
        self.assertGreaterEqual(win.map.get_allocated_width(), self.app.MAP_MIN_WIDTH - 2)
        win.paned.set_position(100)
        self.settle(0.3)
        self.assertGreaterEqual(win.stack.get_allocated_width(), lm.SIDEBAR_MIN)
        win.paned.set_position(380)
        self.settle(0.3)
        # skryti a zobrazeni panelu sirku zachova
        win.side_btn.set_active(False)
        self.settle(0.3)
        self.assertFalse(win.side.get_visible())
        self.assertGreater(win.map.get_allocated_width(), 1000)
        win.side_btn.set_active(True)
        self.settle(0.3)
        self.assertEqual(win.stack.get_allocated_width(), 380)
        # uzke okno (1280x800 s panelem 560): panel se zuzi, po roztazeni okna se vrati
        win.paned.set_position(560)
        self.settle(0.3)
        win.resize(900, 700)
        self.assertTrue(self.pump(lambda: win.get_allocated_width() <= 905))
        self.settle(0.4)
        self.assertGreaterEqual(win.map.get_allocated_width(), self.app.MAP_MIN_WIDTH - 2)
        self.assertEqual(win.side_width, 560)
        win.resize(1240, 720)
        self.assertTrue(self.pump(lambda: win.paned.get_position() == 560))
        win.save_view()
        win.destroy()
        win2 = self.window((50.0875, 14.4208, 14))
        self.assertTrue(self.pump(lambda: win2.stack.get_allocated_width() == 560))

    def nav_window(self, fake=None, **cfg):
        """Okno s trasou autem Staromestske namesti -> Thunovska (fixture), pripravene k navigaci."""
        if fake:
            os.environ["LUXOS_MAPS_COMPANION_BUS"] = fake.address
            os.environ["LUXOS_MAPS_INHIBIT_BUS"] = fake.address
            os.environ["LUXOS_MAPS_PHONE"] = "1"
            self.addCleanup(os.environ.pop, "LUXOS_MAPS_COMPANION_BUS", None)
            self.addCleanup(os.environ.pop, "LUXOS_MAPS_INHIBIT_BUS", None)
            self.addCleanup(os.environ.__setitem__, "LUXOS_MAPS_PHONE", "0")
        win = self.window(view=(50.088, 14.41, 15), location_consent=True, **cfg)
        win.route_from = {"name": "Staroměstské náměstí", "lat": 50.0875, "lon": 14.4208}
        win.directions_to({"name": "Thunovská", "lat": 50.0895, "lon": 14.3995})
        self.assertTrue(self.pump(lambda: len(win.steps_list.get_children()) > 5))
        self.assertTrue(win.nav_btn.get_visible())
        self.assertTrue(self.pump(lambda: win.map.anim is None))
        return win

    def phone(self, fix):
        return {"valid": True, "latitude": fix["lat"], "longitude": fix["lon"], "accuracy": fix["accuracy"],
                "timestamp_ms": 1793098800000, "age_ms": 400, "mock": False, "device": "Pixel",
                "speed": fix.get("speed", 0.0), "bearing": fix.get("bearing", 0.0)}

    def test_navigation_with_phone(self):
        if not shutil.which("dbus-daemon"):
            self.skipTest("dbus-daemon missing")
        fake = FakeCompanion()
        self.addCleanup(fake.close)
        win = self.nav_window(fake)
        route = lm.NavRoute.from_osrm(win.route_res)
        fake.loc = {"valid": False}
        calls = []
        update = None

        win.nav_btn.clicked()
        self.assertIsNotNone(win.nav)
        update = win.nav.update

        def counting(fix, now=None):
            calls.append(time.monotonic())
            return update(fix, now)
        win.nav.update = counting
        self.assertTrue(win.nav_banner.get_visible() and win.nav_bottom.get_visible())
        self.assertFalse(win.nav_btn.get_visible())
        # obrazovka nezhasne: xfce4-screensaver i xfce4-power-manager
        self.assertTrue(self.pump(lambda: len(fake.inhibits) == 2))
        self.assertEqual(sorted(v[0] for v in fake.inhibits.values()),
                         ["org.freedesktop.PowerManagement.Inhibit", "org.freedesktop.ScreenSaver"])
        self.assertEqual(win.nav_status.get_text(), self.app._("Waiting for your location…"))
        # zive polohy z telefonu (LocationChanged) podel trasy
        track = list(lm.simulate_track(route, speed=11.0))
        for fix in track[:11]:
            fake.emit(self.phone(fix))
            self.settle(0.22)
        self.assertTrue(self.pump(lambda: win.nav_fix is not None and abs(win.nav_fix["lat"] - track[10]["lat"]) < 1e-9))
        self.assertFalse(win.nav_status.get_visible())
        st = win.nav_state
        self.assertEqual(st["next"], 2)
        self.assertEqual(win.nav_instr.get_text(), lm.step_instruction(route.steps[2], self.app._))
        self.assertEqual(win.nav_street.get_text(), "Dlouhá")
        self.assertEqual(win.nav_dist.get_text(), lm.format_distance(st["to_next"]))
        self.assertTrue(win.nav_then.get_visible())
        self.assertIn(lm.step_instruction(route.steps[3], self.app._), win.nav_then_lbl.get_text())
        self.assertIs(win.steps_list.get_selected_row(), win.steps_list.get_row_at_index(2))
        self.assertIn(self.app._("Arrival %s") % time.strftime("%H:%M", time.localtime(st["eta"])),
                      win.nav_more.get_text())
        # mapa po smeru jizdy, poloha ve spodni casti, sipka misto bodu; po animaci (dopocet nejvys 1,5 s)
        # sipka stoji na trase kousek pred posledni polohou, otoceni dobehlo ke smeru trasy
        self.assertTrue(self.pump(lambda: win.nav_anim_id is None, 4))
        self.assertIsNotNone(win.map.nav_heading)
        self.assertAlmostEqual(win.map.rotation, -math.radians(win.map.nav_heading), places=6)
        self.assertLess(abs(lm.angle_diff(win.map.nav_heading, st["heading"])), 30)
        me = win.map.me
        self.assertLess(lm.distance_m(me["lat"], me["lon"], win.nav_fix["lat"], win.nav_fix["lon"]),
                        11.0 * lm.NAV_EXTRAPOLATE_S + 1)
        self.assertLess(route.project(me["lat"], me["lon"])[2], 1.0)            # prichycena k trase
        x, y = win.map.latlon_to_screen(me["lat"], me["lon"])
        self.assertAlmostEqual(x, win.map.get_allocated_width() / 2, delta=1)
        self.assertGreater(y, win.map.get_allocated_height() * 0.6)
        lat, lon = win.map.screen_to_latlon(x, y)                   # prevody s otocenim jsou inverzni
        self.assertAlmostEqual(lat, me["lat"], places=7)
        self.assertAlmostEqual(lon, me["lon"], places=7)
        self.assertEqual(win.map.zoom, self.app.NAV_ZOOM["car"])
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-nav-heading-up.png")
        # mezi polohami se sipka i mapa posouvaji plynule (snimky), po dopoctu animace stoji (zadna prace)
        seen = set()
        fake.emit(self.phone(track[11]))
        end = time.time() + 0.8
        while time.time() < end:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            seen.add((round(win.map.me["lat"], 7), round(win.map.me["lon"], 7), round(win.map.mx, 9)))
            time.sleep(0.005)
        self.assertGreater(len(seen), 6)
        self.assertTrue(self.pump(lambda: win.nav_anim_id is None, 4))
        # nejvys 5 zpracovani za sekundu, i kdyz telefon posle polohy rychleji
        n0 = len(calls)
        for fix in track[11:21]:
            fake.emit(self.phone(fix))
        self.settle(0.5)
        self.assertTrue(self.pump(lambda: abs(win.nav_fix["lat"] - track[20]["lat"]) < 1e-9))
        burst = calls[n0:]
        self.assertLessEqual(len(burst), 4)
        self.assertTrue(all(b - a >= 0.19 for a, b in zip(burst, burst[1:])), burst)
        # sever nahoru
        win.nav_compass.clicked()
        self.assertFalse(lm.load_config()["nav_heading_up"])
        self.assertEqual(win.map.rotation, 0.0)
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-nav-north-up.png")
        win.nav_compass.clicked()
        # mimo trasu: 3 polohy > 50 m (aspon 4 s) -> prepocet trasy z aktualni polohy (jeden pozadavek)
        routed = SERVER.count("/routed-car/")
        off = []
        for i in range(5):
            lat, lon, head = route.point_at(935 + i)
            a = math.radians(head - 90)
            off.append({"lat": lat + 160 * math.cos(a) / 111195.0,
                        "lon": lon + 160 * math.sin(a) / (111195.0 * math.cos(math.radians(lat))), "accuracy": 6.0})
        for fix in off:                      # po 1 s (mimo trasu az po 3 polohach a aspon 4 s)
            fake.emit(self.phone(fix))
            self.settle(1.0)
        self.assertTrue(self.pump(lambda: SERVER.count("/routed-car/") == routed + 1))
        self.assertTrue(self.pump(lambda: not win.nav_status.get_visible()))   # nova trasa prisla
        self.settle(0.5)
        self.assertEqual(SERVER.count("/routed-car/"), routed + 1)              # omezeno: 1 prepocet / 15 s
        last = [p for p, _q in SERVER.requests if p.startswith("/routed-car/")][-1]
        self.assertTrue(any(last.endswith("%.6f,%.6f;14.399500,50.089500" % (f["lon"], f["lat"])) for f in off[3:]),
                        last)
        # zpet na trasu a do cile
        for fix in track[90::12] + [track[-1]]:
            fake.emit(self.phone(fix))
            self.settle(0.25)
        self.assertTrue(self.pump(lambda: win.nav_state["arrived"]))
        self.assertEqual(win.nav_dist.get_text(), self.app._("You have arrived"))
        self.assertFalse(win.nav_then.get_visible())
        self.shot(win, "maps-nav-arrived.png")
        # konec navigace: inhibit uvolnen, mapa zpet na sever
        win.end_navigation()
        self.assertTrue(self.pump(lambda: not fake.inhibits))
        self.assertEqual([e[0] for e in fake.inhibit_log], ["Inhibit", "Inhibit", "UnInhibit", "UnInhibit"])
        self.assertFalse(win.nav_banner.get_visible())
        self.assertEqual(win.map.rotation, 0.0)
        self.assertIsNone(win.map.nav_heading)
        self.assertTrue(win.nav_btn.get_visible())
        self.assertIsNone(win.nav)
        self.assertFalse(win.tracking)                  # "Moje poloha" predtim vypnuta: sledovani konci

    def test_navigation_without_location_and_simulation(self):
        self.app.NAV_WAIT_S = 1
        self.addCleanup(setattr, self.app, "NAV_WAIT_S", 12)
        win = self.nav_window()
        os.environ["LUXOS_MAPS_INHIBIT_BUS"] = "unix:path=" + os.path.join(TMP, "no-such-bus")
        self.addCleanup(os.environ.pop, "LUXOS_MAPS_INHIBIT_BUS", None)
        win.start_navigation()
        self.assertTrue(self.pump(lambda: "LuxOS Companion" in win.nav_status.get_text(), 4))
        self.assertFalse(win.nav_sim_btn.get_visible())             # simulace jen s LUXOS_MAPS_SIMULATE
        self.shot(win, "maps-nav-no-location.png")
        win.end_navigation()
        os.environ["LUXOS_MAPS_SIMULATE"] = "40"
        self.addCleanup(os.environ.pop, "LUXOS_MAPS_SIMULATE", None)
        win.start_navigation()
        self.assertTrue(self.pump(lambda: win.nav_sim_btn.get_visible(), 4))
        win.nav_sim_btn.clicked()
        self.assertTrue(self.pump(lambda: win.nav_state and win.nav_state["next"] >= 3, 6))
        self.assertEqual(win.nav_status.get_text(), self.app._("Simulated location (testing)"))
        self.assertEqual(win.map.me["source"], "simulated")
        self.assertTrue(self.pump(lambda: win.nav_state["arrived"], 10))
        win.end_navigation()
        self.assertIsNone(win.map.me)
        self.assertIsNone(win.nav_sim_id)

    def test_transit_navigation(self):
        if not shutil.which("dbus-daemon"):
            self.skipTest("dbus-daemon missing")
        fake = FakeCompanion()
        self.addCleanup(fake.close)
        win = self.nav_window(fake)
        win.route_to = None
        win.mode_buttons["transit"].set_active(True)
        win.set_endpoint("from", {"name": "Karlovo náměstí", "lat": 50.0757, "lon": 14.4199})
        win.set_endpoint("to", {"name": "Pražský hrad", "lat": 50.0905, "lon": 14.4005})
        self.assertTrue(self.pump(lambda: win.transit_res and win.nav_btn.get_visible()))
        win.nav_btn.clicked()
        self.assertIsNotNone(win.nav)
        self.assertTrue(win.nav.reroute_enabled)                     # MHD se taky prepocita
        route = win.nav.route
        self.assertEqual([lg["transit"] for lg in route.legs], [False, True, False])
        dep = route.legs[1]["departure"]
        # hodiny navigace podle jizdniho radu fixture (5 min pred odjezdem tramvaje)
        clock = [dep - 300]
        update = win.nav.update
        win.nav.update = lambda fix, now=None: update(fix, clock[0])
        fake.emit(self.phone({"lat": route.points[0][0], "lon": route.points[0][1], "accuracy": 5.0}))
        self.assertTrue(self.pump(lambda: win.nav_fix is not None))
        # na ceste k zastavce: dalsi pokyn je nastup (vzdalenost k zastavce), potom vystup
        self.assertEqual(win.nav_instr.get_text(), "Take Tram 22 → Vypich")
        self.assertIn("Karlovo náměstí", win.nav_street.get_text())
        self.assertEqual(win.nav_then_lbl.get_text(), "Then: Get off at Malostranské náměstí")
        board = route.steps[1]
        fake.emit(self.phone({"lat": board["lat"], "lon": board["lon"], "accuracy": 5.0}))
        self.settle(0.3)
        clock[0] = dep + 60
        along = route.steps[1]["along"] + 40
        lat, lon, _h = route.point_at(along)
        fake.emit(self.phone({"lat": lat, "lon": lon, "accuracy": 5.0}))
        self.assertTrue(self.pump(lambda: win.nav_state["next"] == 2))
        self.assertFalse(win.nav_state["missed"])                    # nastoupil: spoj nezmeskal
        self.assertTrue(win.nav_instr.get_text().startswith(self.app._("Get off at %s").split("%s")[0]))
        self.assertIs(win.legs_list.get_selected_row(), win.legs_list.get_row_at_index(1))
        self.assertTrue(self.pump(self.tiles_loaded(win)))
        self.shot(win, "maps-nav-transit.png")
        # mimo trasu (jina tramvaj, 330 m od linky): nove spojeni z aktualni polohy, odjezd ted
        plans = SERVER.count("/transitous/plan")
        off = {"lat": lat + 0.003, "lon": lon + 0.003, "accuracy": 5.0, "speed": 8.0}
        for i in range(4):
            clock[0] += 2
            fake.emit(self.phone(off))
            self.settle(0.25)
        self.assertTrue(self.pump(lambda: SERVER.count("/transitous/plan") == plans + 1))
        q = SERVER.last_q("/transitous/plan")
        self.assertEqual(q["fromPlace"], "%.6f,%.6f" % (off["lat"], off["lon"]))
        self.assertEqual(q["toPlace"], "50.090500,14.400500")
        self.assertEqual(q["arriveBy"], "false")
        self.assertNotIn("time", q)
        self.assertTrue(self.pump(lambda: win.nav.route is not route))  # nove spojeni nahradilo stare
        self.assertTrue(self.pump(lambda: not win.nav_status.get_visible()
                                  or win.nav_status.get_text() == self.app._("Finding a new connection…")))
        self.assertEqual(win.itin_idx, 0)
        self.assertEqual(len(win.legs_list.get_children()), 3)
        self.assertEqual(win.map.route["mode"], "transit")
        # dalsi polohy mimo trasu: nejvys 1 plan za NAV_TRANSIT_REROUTE_GAP s
        for i in range(4):
            clock[0] += 2
            fake.emit(self.phone(off))
            self.settle(0.25)
        self.assertEqual(SERVER.count("/transitous/plan"), plans + 1)
        # zmeskany spoj: uzivatel stoji na zacatku, tramvaj odjela pred 2 min -> nove spojeni, "prijezd do"
        # zustava (puvodni hledani "Arrive By 19:45")
        win.transit_query = (lm.parse_user_time("19:45"), True)
        route = win.nav.route
        clock[0] = route.legs[1]["departure"] + lm.NAV_MISSED_S + 60
        start = {"lat": route.points[0][0], "lon": route.points[0][1], "accuracy": 5.0}
        for i in range(2):
            clock[0] += 2
            fake.emit(self.phone(start))
            self.settle(0.25)
        self.assertTrue(self.pump(lambda: SERVER.count("/transitous/plan") == plans + 2))
        q = SERVER.last_q("/transitous/plan")
        self.assertEqual(q["arriveBy"], "true")
        self.assertIn("time", q)
        self.assertEqual(q["fromPlace"], "%.6f,%.6f" % (start["lat"], start["lon"]))
        win.end_navigation()
        self.assertTrue(self.pump(lambda: not fake.inhibits))

if __name__ == "__main__":
    unittest.main()
