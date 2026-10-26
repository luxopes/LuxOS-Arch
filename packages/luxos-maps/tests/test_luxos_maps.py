#!/usr/bin/env python3
"""LuxOS Mapy - testy dlazdic, mezipameti, hledani, tras, odkazu geo:, rozhrani --json a okna.

    python3 -m unittest packages/luxos-maps/tests/test_luxos_maps.py -v
    (okno jen pod xvfb-run s vlastnim XDG_RUNTIME_DIR, viz scripts/check-titlebars.sh)

Zadny skutecny pozadavek: dlazdice OSM, Nominatim, routing.openstreetmap.de a ipinfo.io nahrazuje
mistni falesny server HTTP. Fixtures (tests/fixtures) jsou ulozene odpovedi skutecnych sluzeb z 2026-10-26:
dlazdice 0/0/0 (© OpenStreetMap contributors, CC BY-SA), hledani "Karlovo namesti Praha" a trasa
Staromestske namesti -> Thunovska autem a pesky (© OpenStreetMap contributors, ODbL). Ostatni dlazdice
kresli server sam (svetla mrizka s cislem dlazdice). Snimky okna do LUXOS_TEST_SHOTS.
"""
import http.server
import importlib.machinery
import importlib.util
import io
import json
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
    """Falesne dlazdice (/tiles), Nominatim (/search, /reverse), OSRM (/routed-*) a ipinfo (/ip)."""

    def __init__(self):
        self.requests = []
        self.headers = []
        self.fail = False
        self.delay = 0.0
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
                    server.headers.append(dict(self.headers))
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
                self.send(404, b"{}")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def count(self, prefix):
        with self.lock:
            return sum(1 for p, _q in self.requests if p.startswith(prefix))

    def reset(self):
        with self.lock:
            self.requests.clear()
            self.headers.clear()
            self.max_active = 0
        self.fail = False
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
    "LUXOS_MAPS_GEOCLUE": "0",
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


class TestPackaging(unittest.TestCase):
    def strings(self):
        with open(os.path.join(FILES, "luxos-maps"), encoding="utf-8") as f:
            src = f.read()
        found = set(re.findall(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)', src))
        # vicerakove texty _( "..." "..." )
        for m in re.finditer(r'_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', src):
            found.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
        found |= {t for _k, t in re.findall(r'\("(car|bike|walk)", "([^"]+)"\)', src)}
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


if __name__ == "__main__":
    unittest.main()
