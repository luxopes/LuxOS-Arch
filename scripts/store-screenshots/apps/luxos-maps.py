"""Mapy: trasa autem pres Prahu, misto s detailem a spojeni MHD.

Vsechny sluzby (dlazdice, Nominatim, OSRM, Transitous, Overpass, naseptavani) nahrazuje mistni falesny
server (s.serve_http) s odpovedmi z testovacich dat packages/luxos-maps/tests/fixtures. Dlazdice se
generuji (_b_maptiles.py) - zadna skutecna sluzba dlazdic ani mezipamet uzivatele. Bez polohy
(LUXOS_MAPS_GEOCLUE=0, LUXOS_MAPS_PHONE=0).

luxos-maps pridava na zacatek sys.path /usr/lib/luxos/python (nainstalovany luxos_maps) - spoustec
v s.tmp proto nejdriv nacte luxos_i18n a luxos_maps z pracovni kopie.
"""
import http.server
import importlib.util
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

PLACES = {   # nazev -> (lat, lon, druh, adresa)
    "staroměstské náměstí": ("Staroměstské náměstí", 50.08782, 14.420636, "square",
                             {"square": "Staroměstské náměstí", "suburb": "Staré Město"}),
    "thunovská": ("Thunovská", 50.089155, 14.400308, "road",
                  {"road": "Thunovská", "suburb": "Malá Strana"}),
    "karlovo náměstí": ("Karlovo náměstí", 50.0757441, 14.4199101, "square",
                        {"square": "Karlovo náměstí", "suburb": "Nové Město"}),
}


def load_tiles_module():
    spec = importlib.util.spec_from_file_location("_maptiles_b", os.path.join(HERE, "_b_maptiles.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shots(s):
    fx = s.src("luxos-maps/tests/fixtures")
    sys.path.insert(0, s.src("luxos-maps/files"))
    try:
        spec = importlib.util.spec_from_file_location("luxos_maps_wc", s.src("luxos-maps/files/luxos_maps.py"))
        lm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lm)
    finally:
        sys.path.pop(0)

    def fixture(name):
        with open(os.path.join(fx, name), encoding="utf-8") as f:
            return json.load(f)

    roads = [lm.decode_polyline(fixture(n)["routes"][0]["geometry"]) for n in ("route-car.json", "route-foot.json")]
    for it in fixture("transitous-plan.json")["itineraries"][:1]:
        for leg in it["legs"]:
            g = leg.get("legGeometry")
            if g:
                roads.append(lm.decode_polyline(g["points"], g.get("precision", 5)))
    tiles = load_tiles_module().MapTiles(roads=roads)
    base_place = fixture("search-karlovo.json")[0]
    cache = {}

    def nominatim(key):
        name, lat, lon, kind, addr = PLACES[key]
        a = dict(addr, city="Praha", country="Česko", country_code="cz")
        return dict(base_place, name=name, lat=str(lat), lon=str(lon), type=kind, addresstype=kind,
                    display_name=", ".join([name, addr["suburb"], "Praha", "Česko"]), address=a,
                    boundingbox=None, osm_id=abs(hash(name)) % 1000000)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body=b"", ctype="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            m = re.match(r"^/tiles/(\d+)/(\d+)/(\d+)\.png$", url.path)
            if m:
                key = tuple(int(v) for v in m.groups())
                if key not in cache:
                    cache[key] = tiles.render(*key)
                return self.send(200, cache[key], "image/png")
            if url.path == "/search":
                text = lm.fold(q.get("q", ""))
                hits = [nominatim(k) for k in PLACES if lm.fold(k) in text or text in lm.fold(k)]
                return self.send(200, hits)
            if url.path == "/reverse":
                return self.send(200, nominatim("karlovo náměstí"))
            m = re.match(r"^/routed-(car|bike|foot)/route/v1/driving/", url.path)
            if m:
                return self.send(200, fixture("route-foot.json" if m.group(1) == "foot" else "route-car.json"))
            if url.path == "/transit/plan":
                body = fixture("transitous-plan.json")
                return self.send(200, body)
            if url.path == "/transit/stoptimes":
                return self.send(200, fixture("transitous-stoptimes.json"))
            if url.path == "/overpass":
                data = q.get("data", "")
                return self.send(200, fixture("overpass-public-transport.json") if "public_transport" in data
                                 else fixture("overpass-cafes.json"))
            if url.path == "/suggest/":
                return self.send(200, {"type": "FeatureCollection", "features": []})
            if url.path == "/ip":
                return self.send(200, {"city": "Praha", "loc": "50.0875,14.4208", "country": "CZ"})
            return self.send(404, {})

    port = s.serve_http(Handler)
    srv = "http://127.0.0.1:%d" % port
    env = {"LUXOS_MAPS_TILES": srv + "/tiles/{z}/{x}/{y}.png", "LUXOS_MAPS_SEARCH": srv + "/search",
           "LUXOS_MAPS_REVERSE": srv + "/reverse",
           "LUXOS_MAPS_ROUTE": srv + "/routed-{profile}/route/v1/driving/{coords}",
           "LUXOS_MAPS_IP": srv + "/ip", "LUXOS_MAPS_TRANSIT_PLAN": srv + "/transit/plan",
           "LUXOS_MAPS_STOPTIMES": srv + "/transit/stoptimes", "LUXOS_MAPS_OVERPASS": srv + "/overpass",
           "LUXOS_MAPS_SUGGEST": srv + "/suggest/", "LUXOS_MAPS_SUGGEST_PROVIDERS": srv + "/suggest/",
           "LUXOS_MAPS_GEOCLUE": "0", "LUXOS_MAPS_PHONE": "0", "LUXOS_MAPS_RATE": "0.05",
           # metricke jednotky (en_US by ukazal mile a stopy); jen pro Mapy, GTK zustava v en_US
           "LC_MEASUREMENT": "en_GB.UTF-8",
           "LUXOS_MAPS_EXE": os.path.join(s.tmp, "luxos-maps-run")}
    cfg = {"view": {"lat": 50.0845, "lon": 14.4120, "zoom": 15.0}, "appearance": "light", "sidebar_width": 350,
           "favorites": [{"name": "Home", "lat": 50.0790, "lon": 14.4300},
                         {"name": "Office", "lat": 50.0870, "lon": 14.4260},
                         {"name": "Prague Castle", "lat": 50.0909, "lon": 14.4005}]}
    s.write(".config/luxos/maps.json", json.dumps(cfg))
    run = os.path.join(s.tmp, "luxos-maps-run")
    files = s.src("luxos-maps/files")
    with open(run, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport runpy, sys\nsys.path[:0] = %r\nimport luxos_i18n, luxos_maps  # pracovni kopie\n"
                "sys.argv[0] = %r\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
                % (sys.executable, [s.src("luxos-i18n/files"), files], os.path.join(files, "luxos-maps")))
    os.chmod(run, 0o755)
    s.python_env()

    # 1: trasa autem pres reku
    p = s.launch([run, "--route", "Staroměstské náměstí", "Thunovská", "--mode", "car"], env=env)
    win = s.window(pid=p.pid, size=(1100, 720))
    s.sleep(4.0)
    s.capture("1", win)

    # misto (hledani predane bezicim Mapam)
    s.launch([run, "Karlovo náměstí"], env=env)
    s.sleep(3.0)
    # 2: odjezdy ze zastavek v okoli (kontextova nabidka mapy -> Departures Nearby)
    s.click(708, 400, win, button=3, delay=0.8)
    s.key("Down Down Down Down Return", delay=3.0)
    s.capture("2", win)

    # 3: spojeni MHD
    s.launch([run, "--route", "Karlovo náměstí", "Thunovská", "--mode", "transit"], env=env)
    s.sleep(4.0)
    s.capture("3", win)
