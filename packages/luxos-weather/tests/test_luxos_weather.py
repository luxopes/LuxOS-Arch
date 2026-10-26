#!/usr/bin/env python3
"""LuxOS Pocasi - testy dat (Open-Meteo), mezipameti, jednotek a okna aplikace.

    python3 -m unittest packages/luxos-weather/tests/test_luxos_weather.py -v
    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x900x24" python3 -m unittest packages/luxos-weather/tests/test_luxos_weather.py -v

Zadny skutecny pozadavek: Open-Meteo, hledani mest i ipinfo.io nahrazuje mistni falesny server HTTP
s ulozenymi odpovedmi (tests/fixtures, Praha 2026-10-26). HOME, mezipamet a nastaveni jsou v docasne
slozce. Okno se testuje jen pod xvfb-run (nikdy na skutecne obrazovce); snimky okna do
LUXOS_TEST_SHOTS (je-li nastaveno).
"""
import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
FIXTURES = os.path.join(HERE, "fixtures")
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, FILES)
sys.path.insert(1, os.path.join(ROOT, "luxos-i18n", "files"))

UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


class FakeServer:
    """Falesne Open-Meteo (/v1/forecast, /v1/search) a ipinfo (/ip)."""

    def __init__(self):
        self.requests = []
        self.fail = False
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                server.requests.append((url.path, q))
                if server.fail:
                    self.send_response(503)
                    self.end_headers()
                    return
                if url.path == "/v1/forecast":
                    body = fixture("forecast-prague.json")
                elif url.path == "/v1/search":
                    body = fixture("geocoding-prague.json") if q.get("name", "").lower() in ("prague", "praha") \
                        else {"generationtime_ms": 0.1}
                elif url.path == "/ip":
                    body = {"ip": "192.0.2.1", "city": "Brno", "region": "South Moravian",
                            "country": "CZ", "loc": "49.1952,16.6080", "timezone": "Europe/Prague"}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def count(self, path):
        return sum(1 for p, _q in self.requests if p == path)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SERVER = FakeServer()
TMP = tempfile.mkdtemp(prefix="luxos-weather-test-")
os.environ.update({
    "LUXOS_WEATHER_API": SERVER.base + "/v1/forecast",
    "LUXOS_WEATHER_GEO": SERVER.base + "/v1/search",
    "LUXOS_WEATHER_IP": SERVER.base + "/ip",
    "LUXOS_WEATHER_TZ": "Europe/Prague",
    "LUXOS_WEATHER_ICONS": os.path.join(FILES, "icons"),
    "LUXOS_I18N_DIR": os.path.join(ROOT, "luxos-i18n", "files"),
    "XDG_CACHE_HOME": os.path.join(TMP, "cache"),
    "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
    "LANG": os.environ.get("LUXOS_TEST_LANG") or "en_GB.UTF-8",   # jednotky jako fixture: °C, km/h
})
for _var in ("LC_ALL", "LC_MESSAGES", "LC_MEASUREMENT"):
    os.environ.pop(_var, None)

import luxos_weather as lw  # noqa: E402

PRAGUE = {"name": "Praha", "lat": 50.088, "lon": 14.4208, "country": "Česko", "tz": "Europe/Prague"}


def tearDownModule():
    SERVER.close()
    shutil.rmtree(TMP, ignore_errors=True)


class TestParsing(unittest.TestCase):
    def test_forecast_fixture(self):
        d = lw.parse_forecast(fixture("forecast-prague.json"))
        self.assertEqual(d["current"]["code"], 2)
        self.assertAlmostEqual(d["current"]["temp"], 12.9)
        self.assertTrue(d["current"]["is_day"])
        self.assertEqual(len(d["hourly"]), 24)
        self.assertEqual(d["hourly"][0]["time"], "2026-10-26T14:00")   # od aktualni hodiny
        self.assertEqual(len(d["daily"]), 7)
        self.assertEqual(d["daily"][0]["date"], "2026-10-26")
        self.assertLessEqual(d["daily"][0]["min"], d["daily"][0]["max"])
        self.assertEqual(d["tz"], "Europe/Prague")

    def test_hourly_starts_at_current_hour(self):
        raw = fixture("forecast-prague.json")
        raw["current"]["time"] = raw["hourly"]["time"][5][:13] + ":45"
        d = lw.parse_forecast(raw)
        self.assertEqual(d["hourly"][0]["time"], raw["hourly"]["time"][5])
        self.assertLessEqual(len(d["hourly"]), 24)

    def test_missing_optional_fields(self):
        raw = fixture("forecast-prague.json")
        for k in ("apparent_temperature", "relative_humidity_2m", "pressure_msl"):
            raw["current"].pop(k)
        raw["daily"].pop("uv_index_max")
        raw["hourly"].pop("precipitation_probability")
        d = lw.parse_forecast(raw)
        self.assertIsNone(d["current"]["feels"])
        self.assertIsNone(d["daily"][0]["uv"])
        self.assertIsNone(d["hourly"][0]["pop"])

    def test_broken_forecast_raises(self):
        for raw in ({}, {"current": {}}, {"current": fixture("forecast-prague.json")["current"]}):
            with self.assertRaises((KeyError, TypeError, ValueError)):
                lw.parse_forecast(raw)

    def test_places(self):
        places = lw.parse_places(fixture("geocoding-prague.json"))
        self.assertEqual(places[0]["name"], "Praha")
        self.assertEqual(places[0]["tz"], "Europe/Prague")
        self.assertEqual(lw.parse_places({}), [])
        self.assertEqual(lw.parse_places({"results": [{"name": "x"}]}), [])

    def test_conditions_and_icons(self):
        icons = set(f[:-4] for f in os.listdir(os.path.join(FILES, "icons")))
        for code in list(lw.CODES) + [12345]:
            for day in (True, False):
                self.assertIn(lw.icon_name(code, day), icons, code)
                self.assertIn(lw.sky(code, day).replace("-night", ""),
                              ("clear", "cloudy", "fog", "rain", "storm", "snow"))
        self.assertEqual(lw.icon_name(0, False), "clear-night")
        self.assertEqual(lw.icon_name(95), "storm")
        self.assertEqual(lw.condition(0), "Clear Sky")
        self.assertEqual(lw.compass(0), "North wind")
        self.assertEqual(lw.compass(359), "North wind")
        self.assertEqual(lw.compass(225), "Southwest wind")
        self.assertEqual(lw.compass(None), "")

    def test_condition_texts_translated(self):
        texts = {t for _i, t in lw.CODES.values()} | set(lw.WINDS) | {"Unknown"}
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            with open(os.path.join(ROOT, "luxos-i18n", "files", f"{lang}.tsv"), encoding="utf-8") as f:
                keys = {line.split("\t", 1)[0] for line in f if "\t" in line}
            self.assertFalse(texts - keys, lang)


class TestUnits(unittest.TestCase):
    def test_locale(self):
        self.assertEqual(lw.default_units({"LANG": "cs_CZ.UTF-8"}), "metric")
        self.assertEqual(lw.default_units({"LANG": "en_US.UTF-8"}), "imperial")
        self.assertEqual(lw.default_units({"LANG": "en_GB.UTF-8"}), "metric")
        self.assertEqual(lw.default_units({"LC_ALL": "en_US.UTF-8", "LANG": "cs_CZ.UTF-8"}), "imperial")
        self.assertEqual(lw.default_units({"LC_MEASUREMENT": "cs_CZ.UTF-8", "LANG": "en_US.UTF-8"}), "metric")
        self.assertEqual(lw.default_units({}), "metric")
        self.assertEqual(lw.resolve_units("imperial", {"LANG": "cs_CZ.UTF-8"}), "imperial")
        self.assertEqual(lw.resolve_units("auto", {"LANG": "cs_CZ.UTF-8"}), "metric")

    def test_params(self):
        self.assertEqual(lw.unit_params("metric")["wind_speed_unit"], "kmh")
        self.assertEqual(lw.unit_params("imperial")["temperature_unit"], "fahrenheit")
        self.assertEqual(lw.unit_labels("metric"), {"temp": "°C", "wind": "km/h", "precip": "mm"})


class TestNetworkAndCache(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.path.join(TMP, "cache"), ignore_errors=True)
        SERVER.requests.clear()
        SERVER.fail = False

    def test_request_parameters(self):
        lw.forecast(PRAGUE, "metric")
        path, q = SERVER.requests[-1]
        self.assertEqual(path, "/v1/forecast")
        self.assertEqual(q["temperature_unit"], "celsius")
        self.assertEqual(q["wind_speed_unit"], "kmh")
        self.assertEqual(q["timezone"], "auto")
        self.assertIn("weather_code", q["daily"])
        lw.forecast(PRAGUE, "imperial")
        self.assertEqual(SERVER.requests[-1][1]["temperature_unit"], "fahrenheit")

    def test_cache_30_minutes(self):
        now = time.time()
        r1 = lw.forecast(PRAGUE, "metric", now=now)
        self.assertFalse(r1["stale"])
        r2 = lw.forecast(PRAGUE, "metric", now=now + 29 * 60)
        self.assertEqual(SERVER.count("/v1/forecast"), 1)
        self.assertEqual(r2["data"]["current"]["temp"], r1["data"]["current"]["temp"])
        lw.forecast(PRAGUE, "metric", now=now + 31 * 60)
        self.assertEqual(SERVER.count("/v1/forecast"), 2)
        lw.forecast(PRAGUE, "metric", force=True, now=now + 31 * 60)
        self.assertEqual(SERVER.count("/v1/forecast"), 3)
        # jine jednotky = jina mezipamet
        lw.forecast(PRAGUE, "imperial", now=now + 31 * 60)
        self.assertEqual(SERVER.count("/v1/forecast"), 4)
        self.assertTrue(os.path.isfile(lw.cache_file(PRAGUE, "metric")))

    def test_offline_uses_last_data(self):
        now = time.time()
        lw.forecast(PRAGUE, "metric", now=now - 3600)
        SERVER.fail = True
        r = lw.forecast(PRAGUE, "metric", now=now)
        self.assertTrue(r["stale"])
        self.assertIn("503", r["error"])
        self.assertIsNotNone(r["data"])
        self.assertAlmostEqual(r["fetched"], now - 3600, places=0)
        self.assertTrue(lw.cached_forecast(PRAGUE, "metric")["stale"])

    def test_offline_without_cache(self):
        SERVER.fail = True
        r = lw.forecast(PRAGUE, "metric")
        self.assertIsNone(r["data"])
        self.assertTrue(r["error"])
        self.assertIsNone(lw.cached_forecast(PRAGUE, "metric"))

    def test_unreachable_server(self):
        old = lw.API
        lw.API = "http://127.0.0.1:9/v1/forecast"     # port discard: spojeni odmitnuto
        try:
            r = lw.forecast(PRAGUE, "metric")
        finally:
            lw.API = old
        self.assertIsNone(r["data"])

    def test_corrupt_cache(self):
        path = lw.cache_file(PRAGUE, "metric")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('{"fetched": %d, "raw": {"current": {}}}' % time.time())
        r = lw.forecast(PRAGUE, "metric")
        self.assertIsNotNone(r["data"])
        self.assertEqual(SERVER.count("/v1/forecast"), 1)

    def test_search(self):
        self.assertEqual(lw.search("P"), [])
        self.assertEqual(SERVER.requests, [])     # kratky dotaz bez pozadavku
        places = lw.search("Praha", "cs")
        self.assertEqual(places[0]["name"], "Praha")
        self.assertEqual(SERVER.requests[-1][1]["language"], "cs")
        self.assertEqual(lw.search("Nowhere"), [])

    def test_timezone_city(self):
        self.assertEqual(lw.timezone_city("cs", "Europe/Prague")["name"], "Praha")
        self.assertIsNone(lw.timezone_city("cs", "UTC"))
        self.assertIsNone(lw.timezone_city("cs", "Etc/GMT+1"))
        self.assertEqual(SERVER.requests[-1][1]["name"], "Prague")

    def test_ip_location(self):
        loc = lw.ip_location()
        self.assertEqual(loc["name"], "Brno")
        self.assertAlmostEqual(loc["lat"], 49.1952)

    def test_summary(self):
        r = lw.forecast(PRAGUE, "metric")
        lw.write_summary(PRAGUE, r, "metric")
        with open(lw.summary_path()) as f:
            s = json.load(f)
        self.assertEqual(s["name"], "Praha")
        self.assertEqual(s["temp"], 13)
        self.assertEqual(s["icon"], "partly-cloudy-day")


class TestConfig(unittest.TestCase):
    def test_sanitize(self):
        path = lw.config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"locations": [PRAGUE, {"name": 5}, "x"], "units": "kelvin", "selected": 7}, f)
        cfg = lw.load_config()
        self.assertEqual(len(cfg["locations"]), 1)
        self.assertEqual(cfg["units"], "auto")
        self.assertEqual(cfg["selected"], 0)
        with open(path, "w") as f:
            f.write("{broken")
        self.assertEqual(lw.load_config()["locations"], [])
        os.unlink(path)

    def test_same_place(self):
        self.assertTrue(lw.same_place(PRAGUE, {"lat": 50.09, "lon": 14.43}))
        self.assertFalse(lw.same_place(PRAGUE, {"lat": 49.19, "lon": 16.6}))


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class TestWindow(unittest.TestCase):
    """Okno: prvni spusteni najde mesto podle casoveho pasma, ukaze predpoved, offline data."""

    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
        cls.Gtk, cls.GLib, cls.Gdk = Gtk, GLib, Gdk
        if Gdk.Screen.get_default() is None:      # Gio.TestDBus jineho testu zrusi DISPLAY
            raise unittest.SkipTest("no X display (run this file on its own under xvfb-run)")
        loader = importlib.machinery.SourceFileLoader("luxos_weather_app", os.path.join(FILES, "luxos-weather"))
        spec = importlib.util.spec_from_loader("luxos_weather_app", loader)
        cls.app = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.app)
        provider = Gtk.CssProvider()
        provider.load_from_data(cls.app.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def setUp(self):
        shutil.rmtree(os.path.join(TMP, "cache"), ignore_errors=True)
        shutil.rmtree(os.path.join(TMP, "config"), ignore_errors=True)
        SERVER.requests.clear()
        SERVER.fail = False

    def pump(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if cond():
                return True
            time.sleep(0.02)
        return False

    def shot(self, win, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if not out:
            return
        self.pump(lambda: False, 0.5)
        gw = win.get_window()
        pix = self.Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        os.makedirs(out, exist_ok=True)
        pix.savev(os.path.join(out, name), "png", [], [])

    def labels(self, widget):
        out = []
        if isinstance(widget, self.Gtk.Label):
            out.append(widget.get_text())
        if isinstance(widget, self.Gtk.Container):
            for c in widget.get_children():
                out += self.labels(c)
        return out

    def test_first_run_and_offline(self):
        win = self.app.WeatherWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(win.get_titlebar().get_visible())
        self.assertTrue(win.get_titlebar().get_show_close_button())
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "detail"))
        self.assertEqual(win.cfg["locations"][0]["name"], "Praha")
        texts = self.labels(win.detail)
        self.assertIn("13°", texts)
        self.assertIn("Praha", texts)
        self.assertTrue(any("Open-Meteo" in t for t in texts))
        self.assertTrue(win.sky_class.startswith("sky-clear"))
        self.assertEqual(SERVER.count("/ip"), 0)        # bez souhlasu zadna sluzba polohy
        self.shot(win, "weather-main.png")
        adj = win.detail_scroller.get_vadjustment()
        adj.set_value(adj.get_upper())
        self.shot(win, "weather-details.png")

        # Druhe okno bez site: posledni data z mezipameti + upozorneni
        SERVER.fail = True
        path = lw.cache_file(win.cfg["locations"][0], win.units())
        with open(path) as f:
            c = json.load(f)
        c["fetched"] -= 3 * 3600
        with open(path, "w") as f:
            json.dump(c, f)
        win2 = self.app.WeatherWindow()
        win2.show_all()
        self.addCleanup(win2.destroy)
        self.assertTrue(self.pump(lambda: 0 not in win2.loading and win2.results.get(0, {}).get("error")))
        self.assertEqual(win2.stack.get_visible_child_name(), "detail")
        offline = self.app._("Offline – showing the forecast from %s").split("%s")[0]
        self.assertTrue(any(t.startswith(offline) for t in self.labels(win2.detail)))
        self.shot(win2, "weather-offline.png")

    def test_search_and_add(self):
        win = self.app.WeatherWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "detail"))
        win.add_btn.set_active(True)
        win.search_entry.set_text("Prague")
        self.assertTrue(self.pump(lambda: len(win.search_list.get_children()) > 0))
        self.shot(win, "weather-search.png")
        # Prague v USA (jine misto nez Praha)
        row = win.search_list.get_row_at_index(1)
        win.on_search_pick(win.search_list, row)
        self.assertEqual(len(win.cfg["locations"]), 2)
        self.assertEqual(win.cfg["selected"], 1)
        # stejne misto podruhe nepridat
        win.add_location(dict(win.cfg["locations"][0]))
        self.assertEqual(len(win.cfg["locations"]), 2)
        self.assertEqual(win.cfg["selected"], 0)
        win.remove_location(1)
        self.assertEqual(len(win.cfg["locations"]), 1)
        self.assertEqual(lw.load_config()["locations"][0]["name"], "Praha")

    def test_units_switch(self):
        win = self.app.WeatherWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "detail"))
        button = next(b for b in win.menu_btn.get_popover().get_child().get_children()
                      if isinstance(b, self.Gtk.RadioButton) and "Fahrenheit" in b.get_label())
        button.set_active(True)
        self.assertTrue(self.pump(lambda: any(p == "/v1/forecast" and q.get("temperature_unit") == "fahrenheit"
                                              for p, q in SERVER.requests)))
        self.assertEqual(lw.load_config()["units"], "imperial")


if __name__ == "__main__":
    unittest.main()
