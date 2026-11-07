#!/usr/bin/env python3
"""LuxOS Pocasi - testy dat (Open-Meteo), mezipameti, jednotek a okna aplikace.

    python3 -m unittest packages/luxos-weather/tests/test_luxos_weather.py -v
    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x900x24" python3 -m unittest packages/luxos-weather/tests/test_luxos_weather.py -v

Jednotky (uzemi z locale, en_US jen z LANG -> zeme mista/pasma), migrace nastaveni, dotaz na
jednotky pri prvnim otevreni, sceny pozadi (kody WMO, denni doba, kontrast, castice, snimky/s).
Snimky vsech scen: LUXOS_TEST_SHOTS=adresar (vyber: LUXOS_TEST_SCENES=rain-night,snow-day).
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
import unittest.mock
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
os.environ["LUXOS_WEATHER_LOCALE_CONF"] = ""          # locale.conf systemu testy necte
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


ZONETAB_FIXTURE = """# tzdb (vyrez pro testy)
CZ\t+5005+01426\tEurope/Prague
GB\t+513030-0000731\tEurope/London
US\t+404251-0740023\tAmerica/New_York\tEastern (most areas)
US\t+415100-0873900\tAmerica/Chicago\tCentral (most areas)
PR\t+182806-0660622\tAmerica/Puerto_Rico
LR\t+0618-01047\tAfrica/Monrovia
MM\t+1647+09610\tAsia/Yangon
"""


class TestUnitDetection(unittest.TestCase):
    """Vychozi jednotky: uzemi z locale (POSIX poradi), en_US jen z LANG rozhodne misto/pasmo."""

    @classmethod
    def setUpClass(cls):
        cls.zonetab = os.path.join(TMP, "zone.tab")
        with open(cls.zonetab, "w", encoding="utf-8") as f:
            f.write(ZONETAB_FIXTURE)

    def detect(self, env, tz="", places=None):
        return lw.detect_units(env, tz, places, zonetab=self.zonetab)

    def test_locale_combinations(self):
        cz = [{"name": "Praha", "lat": 50.08, "lon": 14.42, "country_code": "CZ"}]
        us = [{"name": "Boston", "lat": 42.36, "lon": -71.06, "country_code": "US"}]
        cases = [
            # (prostredi, casove pasmo, mista, ocekavane jednotky, duvod)
            ({"LANG": "en_US.UTF-8", "LC_MEASUREMENT": "cs_CZ.UTF-8"}, "", None, "metric", "locale"),
            ({"LANG": "en_US.UTF-8", "LC_MEASUREMENT": "cs_CZ.UTF-8"}, "America/New_York", us, "metric", "locale"),
            ({"LANG": "en_US.UTF-8"}, "", None, "imperial", "locale"),
            ({"LANG": "en_US.UTF-8"}, "America/New_York", None, "imperial", "timezone"),
            # chyba z hlaseni: anglicky system v Evrope (LANG=en_US.UTF-8, pasmo Europe/Prague)
            ({"LANG": "en_US.UTF-8"}, "Europe/Prague", None, "metric", "timezone"),
            ({"LANG": "en_US.UTF-8"}, "Europe/Prague", cz, "metric", "place"),
            ({"LANG": "en_US.UTF-8"}, "", cz, "metric", "place"),
            ({"LANG": "en_US.UTF-8"}, "Europe/Prague", us, "imperial", "place"),     # prvni misto ma prednost
            ({"LANG": "en_US.UTF-8"}, "Mars/Olympus", None, "imperial", "locale"),   # nezname pasmo
            ({"LANG": "en_GB.UTF-8"}, "", None, "metric", "locale"),
            ({"LANG": "en_GB.UTF-8"}, "America/Chicago", us, "metric", "locale"),
            ({"LANG": "cs_CZ.UTF-8"}, "America/New_York", None, "metric", "locale"),
            ({"LANG": "de_DE.UTF-8@euro"}, "", None, "metric", "locale"),
            ({"LANG": "cs_CZ.UTF-8", "LC_MEASUREMENT": "en_US.UTF-8"}, "Europe/Prague", cz, "imperial", "locale"),
            ({"LC_ALL": "en_US.UTF-8", "LANG": "cs_CZ.UTF-8"}, "Europe/Prague", None, "imperial", "locale"),
            ({"LC_ALL": "de_DE.UTF-8", "LC_MEASUREMENT": "en_US.UTF-8"}, "", None, "metric", "locale"),
            ({"LANG": "es_419.UTF-8"}, "", None, "metric", "locale"),
            ({"LANG": "en_LR.UTF-8"}, "", None, "imperial", "locale"),
            ({"LANG": "es_PR.UTF-8"}, "", None, "imperial", "locale"),
            ({"LANG": "en_BS.UTF-8"}, "", None, "imperial", "locale"),
            ({"LANG": "my_MM.UTF-8"}, "", None, "metric", "locale"),
            # bez uzemi: C, POSIX, C.UTF-8, jen jazyk
            ({"LANG": "C"}, "", us, "imperial", "place"),
            ({"LANG": "C.UTF-8"}, "", cz, "metric", "place"),
            ({"LANG": "POSIX"}, "America/New_York", None, "imperial", "timezone"),
            ({"LC_ALL": "C", "LANG": "en_US.UTF-8"}, "Europe/Prague", None, "metric", "timezone"),
            ({"LANG": "C"}, "", None, "metric", "default"),
            ({"LANG": "en"}, "America/Puerto_Rico", None, "imperial", "timezone"),
            ({}, "", None, "metric", "default"),
            ({}, "Africa/Monrovia", None, "imperial", "timezone"),
            ({}, "Asia/Yangon", None, "metric", "timezone"),
        ]
        for env, tz, places, units, why in cases:
            with self.subTest(env=env, tz=tz, places=places and places[0]["country_code"]):
                self.assertEqual(self.detect(env, tz, places), (units, why))

    def test_resolve_and_default(self):
        self.assertEqual(lw.resolve_units("metric", {"LANG": "en_US.UTF-8"}), "metric")
        self.assertEqual(lw.resolve_units("imperial", {"LANG": "cs_CZ.UTF-8"}), "imperial")
        self.assertEqual(lw.resolve_units("auto", {"LANG": "en_US.UTF-8"}, tz="Europe/Prague"), "metric")
        self.assertEqual(lw.resolve_units("bogus", {"LANG": "en_US.UTF-8"},
                                          places=[{"country_code": "CZ"}]), "metric")
        # skutecne prostredi testu: en_GB, pasmo Europe/Prague
        self.assertEqual(lw.resolve_units("auto"), "metric")

    def test_real_environment_reads_locale_conf(self):
        """Zmena formatu v locale.conf plati bez noveho prihlaseni (prostredi relace ji nema)."""
        conf = os.path.join(TMP, "locale.conf")
        with open(conf, "w") as f:
            f.write('# comment\nLANG=en_US.UTF-8\nLC_MEASUREMENT="cs_CZ.UTF-8"\n')
        us_conf = os.path.join(TMP, "locale-us.conf")
        with open(us_conf, "w") as f:
            f.write("LANG=cs_CZ.UTF-8\nLC_MEASUREMENT=en_US.UTF-8\n")
        env = {"LANG": "en_US.UTF-8", "LUXOS_WEATHER_TZ": "", "LUXOS_WEATHER_LOCALE_CONF": conf}
        with unittest.mock.patch.dict(os.environ, env):
            for v in ("LC_ALL", "LC_MEASUREMENT"):
                os.environ.pop(v, None)
            self.assertEqual(lw.locale_territory(), ("CZ", "LC_MEASUREMENT"))
            self.assertEqual(lw.detect_units(tz="")[0], "metric")
            os.environ["LUXOS_WEATHER_LOCALE_CONF"] = os.path.join(TMP, "missing") + ":" + us_conf
            self.assertEqual(lw.detect_units(tz="Europe/Prague")[0], "imperial")
            # promenna prostredi ma prednost pred souborem
            os.environ["LC_MEASUREMENT"] = "de_DE.UTF-8"
            self.assertEqual(lw.detect_units(tz="")[0], "metric")
            os.environ.pop("LC_MEASUREMENT")
            os.environ["LUXOS_WEATHER_LOCALE_CONF"] = ""
            self.assertEqual(lw.detect_units(tz="")[0], "imperial")      # jen LANG=en_US
            self.assertEqual(lw.detect_units(tz="Europe/Prague")[0], "metric")

    def test_zone_country(self):
        self.assertEqual(lw.zone_country("Europe/Prague", self.zonetab), "CZ")
        self.assertEqual(lw.zone_country("America/Chicago", self.zonetab), "US")
        self.assertEqual(lw.zone_country("US/Eastern", self.zonetab), "US")
        for tz in ("", "UTC", "Etc/GMT+1", "Nowhere/City"):
            self.assertEqual(lw.zone_country(tz, self.zonetab), "", tz)
        self.assertEqual(lw.zone_country("Europe/Prague", os.path.join(TMP, "none.tab")), "")
        if os.path.isfile("/usr/share/zoneinfo/zone.tab"):      # skutecna tzdata
            self.assertEqual(lw.zone_country("Europe/Berlin"), "DE")
            self.assertEqual(lw.zone_country("America/Los_Angeles"), "US")

    def test_fahrenheit_countries(self):
        for cc in ("US", "PR", "GU", "VI", "AS", "MP", "UM", "PW", "FM", "MH", "BS", "BZ", "KY", "LR"):
            self.assertEqual(lw.units_for_country(cc), "imperial", cc)
        for cc in ("CZ", "GB", "CA", "DE", "MM", "AU", "", "us-x"):
            self.assertEqual(lw.units_for_country(cc), "metric", cc)
        self.assertEqual(lw.units_for_country("us"), "imperial")


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.path = lw.config_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def write(self, cfg):
        with open(self.path, "w") as f:
            json.dump(cfg, f)

    def test_new_user(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        cfg = lw.load_config()
        self.assertEqual((cfg["units"], cfg["units_asked"], cfg["version"], cfg["animate"]),
                         ("auto", False, lw.CONFIG_VERSION, True))

    def test_v1_automatic_is_reevaluated_and_asked_once(self):
        """1.0.0-1 s "auto" ukazovalo v Evrope °F (chybna detekce): zustane auto, nove °C, zeptat se."""
        self.write({"locations": [PRAGUE], "units": "auto", "selected": 0})
        cfg = lw.load_config()
        self.assertEqual(cfg["units"], "auto")
        self.assertFalse(cfg["units_asked"])
        self.assertEqual(lw.resolve_units(cfg["units"], {"LANG": "en_US.UTF-8"}, cfg["locations"],
                                          tz="Europe/Prague"), "metric")
        # po odpovedi (nebo zavreni pruhu) se uz neptame - ani po dalsim nacteni
        cfg["units_asked"] = True
        lw.save_config(cfg)
        again = lw.load_config()
        self.assertTrue(again["units_asked"])
        self.assertEqual(again["version"], lw.CONFIG_VERSION)

    def test_v1_explicit_choice_kept(self):
        for units in ("imperial", "metric"):
            self.write({"locations": [PRAGUE], "units": units, "selected": 0})
            cfg = lw.load_config()
            self.assertEqual(cfg["units"], units)
            self.assertTrue(cfg["units_asked"], units)
            self.assertEqual(lw.resolve_units(cfg["units"], {"LANG": "cs_CZ.UTF-8"}), units)

    def test_migration_idempotent_and_v2_untouched(self):
        self.write({"locations": [PRAGUE], "units": "auto", "selected": 0})
        first = lw.load_config()
        self.assertEqual(lw.load_config(), first)        # bez ulozeni se migrace jen zopakuje stejne
        lw.save_config(first)
        self.assertEqual(lw.load_config(), first)
        self.write({"locations": [], "units": "auto", "version": 2, "units_asked": True, "animate": False})
        cfg = lw.load_config()
        self.assertTrue(cfg["units_asked"])
        self.assertFalse(cfg["animate"])
        self.write({"locations": [], "units": "imperial", "version": 2, "units_asked": False})
        self.assertFalse(lw.load_config()["units_asked"])   # verze 2: jak je ulozeno


class TestScenes(unittest.TestCase):
    def test_every_code_has_scene(self):
        for code in lw.CODES:
            kind, intensity = lw.SCENES[code]
            self.assertIn(kind, lw.SCENE_KINDS, code)
            self.assertTrue(0 <= intensity <= 1, code)
        self.assertEqual(set(lw.SCENES), set(lw.CODES))
        self.assertEqual(lw.scene(12345)["kind"], "cloudy")

    def test_mapping(self):
        expect = {0: "clear", 1: "partly", 2: "partly", 3: "cloudy", 45: "fog", 48: "fog", 51: "drizzle",
                  56: "drizzle", 61: "rain", 65: "rain", 67: "rain", 80: "rain", 82: "rain", 71: "snow",
                  77: "snow", 86: "snow", 95: "storm", 99: "storm"}
        for code, kind in expect.items():
            self.assertEqual(lw.scene(code)["kind"], kind, code)
        self.assertLess(lw.scene(61)["intensity"], lw.scene(65)["intensity"])
        self.assertEqual(lw.scene(63, False)["name"], "rain-night")

    def test_time_of_day(self):
        rise, sset = "2026-10-26T06:42", "2026-10-26T16:49"
        self.assertEqual(lw.time_of_day("2026-10-26T06:00", False, rise, sset), "dawn")
        self.assertEqual(lw.time_of_day("2026-10-26T07:27", True, rise, sset), "dawn")
        self.assertEqual(lw.time_of_day("2026-10-26T07:28", True, rise, sset), "day")
        self.assertEqual(lw.time_of_day("2026-10-26T12:00", False, rise, sset), "day")   # slunce > priznak
        self.assertEqual(lw.time_of_day("2026-10-26T17:30", False, rise, sset), "dusk")
        self.assertEqual(lw.time_of_day("2026-10-26T17:40", True, rise, sset), "night")
        self.assertEqual(lw.time_of_day("2026-10-26T02:00", True, rise, sset), "night")
        self.assertEqual(lw.time_of_day("2026-10-27T12:00", False, rise, sset), "night")  # jiny den: priznak
        self.assertEqual(lw.time_of_day("bad", True, "", ""), "day")
        self.assertEqual(lw.time_of_day("", False, "x", "y"), "night")

    def test_scene_for_uses_real_local_time(self):
        data = lw.parse_forecast(fixture("forecast-prague.json"))   # Praha, UTC+1, slunce 06:42-16:49
        import calendar
        at = lambda hhmm: calendar.timegm(time.strptime("2026-10-26T" + hhmm, "%Y-%m-%dT%H:%M")) - 3600
        self.assertEqual(lw.local_now(3600, at("14:30")), "2026-10-26T14:30")
        self.assertEqual(lw.scene_for(data, at("14:30"))["name"], "partly-day")
        self.assertEqual(lw.scene_for(data, at("06:50"))["name"], "partly-dawn")
        self.assertEqual(lw.scene_for(data, at("17:00"))["name"], "partly-dusk")
        self.assertEqual(lw.scene_for(data, at("21:00"))["name"], "partly-night")
        # data starsi nez predpoved (jiny den): priznak is_day z Open-Meteo
        self.assertEqual(lw.scene_for(data, at("14:30") + 30 * 86400)["time"], "day")


class TestSkyRenderer(unittest.TestCase):
    """Kreslene pozadi bez GTK (pycairo do obrazku): citelnost, castice, usporne snimky."""

    @classmethod
    def setUpClass(cls):
        try:
            import cairo
            import luxos_weather_sky as sky
        except ImportError as e:
            raise unittest.SkipTest(f"pycairo missing: {e}")
        cls.cairo, cls.sky = cairo, sky

    def test_palette_contrast(self):
        sky = self.sky
        card = sky.hex_rgb("#0b1426")
        for kind in lw.SCENE_KINDS + (None,):
            for tod in lw.SCENE_TIMES:
                for dark in (False, True):
                    stops = sky.palette(kind, tod, dark)
                    self.assertEqual(len(stops), 3)
                    for c in stops:
                        self.assertGreaterEqual(sky.contrast_white(c), sky.TEXT_CONTRAST - 0.01,
                                                (kind, tod, dark, c))
                        # na karte (tmave sklo 20 %) je text jeste citelnejsi
                        self.assertGreaterEqual(sky.contrast_white(sky.mix(c, card, 0.2)), 3.8)
        day = sky.palette("clear", "day")
        self.assertGreater(day[0][2], day[0][0])       # jasny den je modry
        self.assertNotEqual(sky.palette("clear", "day"), sky.palette("clear", "day", dark=True))
        self.assertLess(sky.luminance(sky.palette("storm", "day")[0]), sky.luminance(day[0]))

    def test_darken_to(self):
        sky = self.sky
        self.assertEqual(sky.darken_to((0.1, 0.1, 0.2)), (0.1, 0.1, 0.2))
        d = sky.darken_to((1.0, 1.0, 1.0), 4.5)
        self.assertGreaterEqual(sky.contrast_white(d), 4.5)
        self.assertLess(sky.contrast_white(d), 4.7)

    def test_moon_phase(self):
        import calendar
        new = calendar.timegm((2024, 1, 11, 11, 57, 0))
        full = calendar.timegm((2024, 1, 25, 17, 54, 0))
        self.assertLess(min(self.sky.moon_phase(new), 1 - self.sky.moon_phase(new)), 0.02)
        self.assertAlmostEqual(self.sky.moon_phase(full), 0.5, delta=0.03)

    def render(self, kind, tod, intensity=0.8, w=360, h=300, motion=True, steps=20):
        cairo = self.cairo
        s = self.sky.Sky(seed=3)
        s.set_motion(motion)
        s.set_scene({"kind": kind, "time": tod, "intensity": intensity}, fade=False)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        s.draw(cairo.Context(surf), w, h)
        for _i in range(steps):
            s.advance(1 / 30)
            s.draw(cairo.Context(surf), w, h)
        return s, surf

    def test_all_scenes_render(self):
        for kind in lw.SCENE_KINDS:
            for tod in lw.SCENE_TIMES:
                s, surf = self.render(kind, tod)
                data = bytes(surf.get_data())
                self.assertGreater(len(set(data[i:i + 4] for i in range(0, len(data), 4 * 97))), 5, (kind, tod))
                self.assertEqual(s.name(), f"{kind}-{tod}")

    def test_particles_follow_weather(self):
        s, _ = self.render("rain", "day", 0.4)
        light = len(s.rain)
        s, _ = self.render("rain", "day", 1.0)
        self.assertGreater(len(s.rain), light)
        self.assertFalse(s.snow)
        s, _ = self.render("snow", "night")
        self.assertTrue(s.snow)
        self.assertFalse(s.stars)                       # pri snezeni nejsou videt hvezdy
        s, _ = self.render("clear", "night")
        self.assertTrue(s.stars)
        self.assertFalse(s.clouds)
        s, _ = self.render("clear", "day")
        self.assertFalse(s.stars or s.clouds or s.rain)
        s, _ = self.render("fog", "day")
        self.assertTrue(s.fog)

    def test_fps_policy(self):
        """Animuje se jen to, co se hybe; bez pohybu (Omezit pohyb, Uspora baterie) staticky snimek."""
        expect = {("clear", "day"): 0, ("clear", "dawn"): 0, ("clear", "night"): 8, ("partly", "day"): 15,
                  ("cloudy", "night"): 15, ("fog", "day"): 15, ("rain", "day"): 30, ("storm", "night"): 30,
                  ("snow", "day"): 20, ("drizzle", "dusk"): 24}
        for (kind, tod), fps in expect.items():
            s, _ = self.render(kind, tod, steps=0)
            self.assertEqual(s.fps(), fps, (kind, tod))
            s.set_motion(False)
            self.assertEqual(s.fps(), 0, (kind, tod))
        s = self.sky.Sky()
        self.assertEqual(s.fps(), 0)                    # bez dat

    def test_static_when_motion_off(self):
        s, _ = self.render("rain", "day", steps=0, motion=False)
        before = [list(d) for d in s.rain]
        s.advance(0.2)
        self.assertEqual([list(d) for d in s.rain], before)

    def test_lightning(self):
        s, _ = self.render("storm", "day", steps=0)
        s.flash_at = s.t
        s.advance(0.01)
        self.assertGreater(s.flash_alpha(), 0.5)
        self.assertTrue(s.bolt)
        s.advance(0.25)
        s.advance(0.25)
        s.advance(0.25)
        self.assertEqual(s.flash_alpha(), 0.0)
        self.assertGreaterEqual(s.flash_at - s.t, 4.0)  # dalsi zablesk nejdriv za par sekund
        s.flash_at = s.t
        s.set_motion(False)
        s.advance(0.01)
        self.assertEqual(s.flash_alpha(), 0.0)          # bez pohybu zadne zablesky

    def test_crossfade(self):
        cairo = self.cairo
        s = self.sky.Sky(seed=1)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 150)
        s.set_scene({"kind": "clear", "time": "day", "intensity": 0}, fade=True)
        s.draw(cairo.Context(surf), 200, 150)
        self.assertTrue(s.set_scene({"kind": "rain", "time": "night", "intensity": 0.6}))
        self.assertEqual(s.fps(), 30)                   # prolnuti bezi i u jinak staticke sceny
        self.assertFalse(s.set_scene({"kind": "rain", "time": "night", "intensity": 0.6}))
        for _i in range(30):
            s.advance(1 / 30)
        s.draw(cairo.Context(surf), 200, 150)
        self.assertIsNone(s._old)

    def test_frame_cost(self):
        """Snimek v okne 670x640 (bez GTK) zabere jen par milisekund i v nejnarocnejsi scene."""
        cairo = self.cairo
        worst = 0.0
        for kind in ("partly", "cloudy", "fog", "rain", "storm", "snow"):
            s = self.sky.Sky(seed=2)
            s.set_scene({"kind": kind, "time": "day", "intensity": 1.0}, fade=False)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 670, 640)
            s.draw(cairo.Context(surf), 670, 640)
            t0 = time.perf_counter()
            for _i in range(30):
                s.advance(1 / 30)
                s.draw(cairo.Context(surf), 670, 640)
            worst = max(worst, (time.perf_counter() - t0) / 30)
        self.assertLess(worst, 0.012, f"{worst * 1000:.1f} ms/frame")


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
        self.assertTrue(win.sky_class.startswith("sky-partly"), win.sky_class)   # kod 2: polojasno
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


    def open_window(self):
        win = self.app.WeatherWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(self.pump(lambda: win.stack.get_visible_child_name() == "detail"))
        return win

    def test_units_banner_choice(self):
        """Prvni otevreni: nenapadny dotaz °C/°F (predvybrane zjistene), volba se ulozi, uz se neptame."""
        win = self.open_window()
        self.assertTrue(win.units_banner.get_reveal_child())
        self.assertTrue(win.units_choice["metric"].get_style_context().has_class("primary"))   # en_GB
        self.assertFalse(win.units_choice["imperial"].get_style_context().has_class("primary"))
        self.assertIn("°C", win.units_hint.get_text())
        self.assertIn("13°", self.labels(win.detail))     # data se ukazuji hned, dotaz neblokuje
        self.shot(win, "weather-units-banner.png")
        win.units_choice["imperial"].clicked()
        self.assertFalse(win.units_banner.get_reveal_child())
        cfg = lw.load_config()
        self.assertEqual((cfg["units"], cfg["units_asked"]), ("imperial", True))
        self.assertTrue(win.unit_buttons["imperial"].get_active())
        self.assertTrue(self.pump(lambda: any(p == "/v1/forecast" and q.get("temperature_unit") == "fahrenheit"
                                              for p, q in SERVER.requests)))
        win2 = self.open_window()
        self.assertFalse(win2.units_banner.get_reveal_child())

    def test_units_banner_dismiss_keeps_automatic(self):
        win = self.open_window()
        win.dismiss_units_banner()
        cfg = lw.load_config()
        self.assertEqual((cfg["units"], cfg["units_asked"]), ("auto", True))
        self.assertIn("°C", win.unit_buttons["auto"].get_label())
        win2 = self.open_window()
        self.assertFalse(win2.units_banner.get_reveal_child())

    def test_migrated_v1_user_in_europe(self):
        """Stavajici uzivatel 1.0.0-1 s "auto" a LANG=en_US v Praze: nove °C a jednou dotaz."""
        os.makedirs(os.path.dirname(lw.config_path()), exist_ok=True)
        with open(lw.config_path(), "w") as f:
            json.dump({"locations": [dict(PRAGUE, country_code="CZ")], "units": "auto", "selected": 0}, f)
        with unittest.mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            win = self.open_window()
            self.assertEqual(win.units(), "metric")
            self.assertTrue(win.units_banner.get_reveal_child())
            self.assertEqual(SERVER.requests[-1][1]["temperature_unit"], "celsius")

    def test_explicit_choice_not_asked(self):
        os.makedirs(os.path.dirname(lw.config_path()), exist_ok=True)
        with open(lw.config_path(), "w") as f:
            json.dump({"locations": [PRAGUE], "units": "imperial", "selected": 0}, f)
        win = self.open_window()
        self.assertFalse(win.units_banner.get_reveal_child())
        self.assertEqual(win.units(), "imperial")

    def test_animation_runs_only_when_useful(self):
        """Casovac snimku: jen aktivni okno, scena s pohybem, animace povolene, bez Uspory baterie."""
        win = self.open_window()
        area = win.sky_area
        rain = lw.scene(63, True)
        area.force_active = True
        win.set_sky(rain)
        self.assertTrue(area.timer)
        start = area.frames
        self.pump(lambda: False, 1.0)
        self.assertGreater(area.frames - start, 15)        # ~30 snimku/s
        self.assertLess(area.frames - start, 45)
        area.force_active = False                          # okno na pozadi
        area.update()
        self.assertFalse(area.timer)
        start = area.frames
        self.pump(lambda: False, 0.5)
        self.assertLessEqual(area.frames - start, 1)
        area.force_active = True
        area.update()
        self.assertTrue(area.timer)
        # Uspora baterie (priznak luxos-powersaver)
        os.makedirs(os.path.dirname(self.app.POWERSAVER), exist_ok=True)
        open(self.app.POWERSAVER, "w").close()
        self.addCleanup(lambda: os.path.exists(self.app.POWERSAVER) and os.unlink(self.app.POWERSAVER))
        self.assertTrue(self.pump(lambda: not area.timer, 3))    # inotify, bez dotazovani
        os.unlink(self.app.POWERSAVER)
        self.assertTrue(self.pump(lambda: bool(area.timer), 3))
        # animace GTK vypnute (Omezit pohyb)
        settings = self.Gtk.Settings.get_default()
        settings.set_property("gtk-enable-animations", False)
        self.addCleanup(settings.set_property, "gtk-enable-animations", True)
        self.pump(lambda: False, 0.1)
        self.assertFalse(area.timer)
        settings.set_property("gtk-enable-animations", True)
        self.pump(lambda: False, 0.1)
        self.assertTrue(area.timer)
        # volba v nabidce
        win.animate_btn.set_active(False)
        self.assertFalse(area.timer)
        self.assertFalse(lw.load_config()["animate"])
        win.animate_btn.set_active(True)
        self.assertTrue(area.timer)
        # minimalizovane okno
        area.iconified = True
        area.update()
        self.assertFalse(area.timer)
        area.iconified = False
        area.update()
        # zmena sceny v aktivnim okne se prolne; kdyz okno prestane byt videt, prolnuti se dokonci
        win.set_sky(lw.scene(73, True))
        self.assertGreater(area.sky._fade, 0)
        area.force_active = False
        area.update()
        self.assertEqual(area.sky._fade, 0)
        self.assertIsNone(area.sky._old)
        self.assertFalse(area.timer)
        area.force_active = True
        area.update()
        self.assertEqual(area.timer_fps, 20)            # snih
        # staticka scena (jasny den) casovac nepotrebuje
        win.set_sky(lw.scene(0, True, "2026-10-26T12:00", "2026-10-26T06:42", "2026-10-26T16:49"))
        self.assertTrue(self.pump(lambda: not area.timer, 2))    # po prolnuti stop

    def test_scene_screenshots(self):
        """Snimek okna v kazde scene (LUXOS_TEST_SHOTS), zobrazeni dat ve vsech scenach."""
        win = self.open_window()
        win.dismiss_units_banner()
        rise, sset = "2026-10-26T06:42", "2026-10-26T16:49"
        times = {"day": "2026-10-26T12:00", "night": "2026-10-26T22:00", "dawn": "2026-10-26T06:50",
                 "dusk": "2026-10-26T16:55"}
        codes = {"clear": 0, "partly": 2, "cloudy": 3, "fog": 45, "drizzle": 53, "rain": 63, "storm": 95,
                 "snow": 73}
        area = win.sky_area
        area.force_active = False                       # staticke snimky (casovac stoji)
        area.update()
        area.sky.epoch = 1762500000 + 4 * 86400        # mesic ve stejne fazi na vsech snimcich
        only = os.environ.get("LUXOS_TEST_SCENES", "")
        for kind, code in codes.items():
            for tod, now in times.items():
                if only and f"{kind}-{tod}" not in only.split(","):
                    continue
                raw = fixture("forecast-prague.json")
                raw["current"]["weather_code"] = code
                raw["current"]["is_day"] = int(tod != "night")
                win.results[0] = {"data": lw.parse_forecast(raw), "fetched": time.time(), "stale": False,
                                  "error": None}
                win.show_detail(0)
                scene = lw.scene(code, tod != "night", now, rise, sset)
                self.assertEqual(scene["name"], f"{kind}-{tod}")
                area.sky.set_scene(scene, False, fade=False)
                win.scene = scene
                for _i in range(45):                    # castice rozlozene jako po chvili animace
                    area.sky.advance(1 / 30)
                if kind == "storm":
                    area.sky.flash_t = area.sky.t - 0.03
                    area.sky.bolt = area.sky._make_bolt()
                area.queue_draw()
                self.shot(win, f"scene-{kind}-{tod}.png")
                self.assertEqual(win.stack.get_visible_child_name(), "detail")

if __name__ == "__main__":
    unittest.main()
