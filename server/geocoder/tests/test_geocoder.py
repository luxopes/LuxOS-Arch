#!/usr/bin/env python3
"""Testy geocoderu LuxOS: sestaveni male databaze z OSM (Praha, Brno), razeni, format Photonu pro klienta
Map, limity, omezeni rychlosti, HTTP keep-alive a vymena databaze. Jen standardni knihovna:

    python3 -m unittest server/geocoder/tests/test_geocoder.py
"""

import asyncio
import contextlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "server", "geocoder"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "geocoder"))
sys.path.insert(0, os.path.join(ROOT, "packages", "luxos-maps", "files"))
import build  # noqa: E402
import luxos_geocoder as G  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "prague.osm")
PRAHA = (50.08, 14.42)
BRNO = (49.19, 16.60)


def names(feats):
    out = []
    for f in feats:
        p = f["properties"]
        out.append(p.get("name") or f"{p.get('street')} {p.get('housenumber')}")
    return out


class GeocoderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-geocoder-test-")
        cls.db = os.path.join(cls.tmp, "geocoder.sqlite")
        with contextlib.redirect_stderr(io.StringIO()):
            build.build([FIXTURE], cls.db, cls.tmp)
        cls.searcher = G.Searcher(cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def search(self, q, center=None, limit=7, lang="default"):
        return self.searcher.search(G.Query(q, *(center or (None, None)), limit=limit, lang=lang))


class TestBuild(GeocoderTestCase):
    def test_contents(self):
        import sqlite3
        db = sqlite3.connect(self.db)
        meta = dict(db.execute("SELECT k, v FROM meta"))
        self.assertEqual(meta["schema"], "1")
        self.assertEqual(meta["countries"], "CZ,SK")
        kinds = dict(db.execute("SELECT kind, count(*) FROM feat GROUP BY kind"))
        # Praha, Brno, Vinohrady (Wien je mimo pokryti); 2 zastavky (4 body Namesti Miru -> 1);
        # 6 ulic (2 useky Vodickovy -> 1); kavarna + muzeum (lavicka ne); 6 adres
        self.assertEqual(kinds, {G.K_CITY: 3, G.K_STOP: 2, G.K_STREET: 6, G.K_POI: 2, G.K_ADDRESS: 6})
        # rowid = poradi dulezitosti: Praha prvni
        self.assertEqual(db.execute("SELECT name FROM feat WHERE id = 1").fetchone()[0], "Praha")
        imps = [r[0] for r in db.execute("SELECT imp FROM feat ORDER BY id")]
        self.assertEqual(imps, sorted(imps, reverse=True))

    @unittest.skipUnless(importlib.util.find_spec("osmium"), "pyosmium not installed")
    def test_osmium_reader_same_result(self):
        """Stejna data pres pyosmium (cesta pro .pbf) = stejna databaze jako cteni XML."""
        import sqlite3
        out = os.path.join(self.tmp, "osmium.sqlite")
        with contextlib.redirect_stderr(io.StringIO()):
            build.build([FIXTURE], out, self.tmp, reader="osmium")
        q = "SELECT kind, name, hn, lat, lon FROM feat ORDER BY id"
        self.assertEqual(sqlite3.connect(out).execute(q).fetchall(), sqlite3.connect(self.db).execute(q).fetchall())

    def test_fold_and_tokens(self):
        self.assertEqual(G.fold("Náměstí Míru, Žluťoučký KŮŇ"), "namesti miru, zlutoucky kun")
        self.assertEqual(G.tokens("Vodičkova 681/30"), ["vodickova", "681", "30"])
        self.assertEqual(G.fold("Łódź Straße"), "lodz strasse")

    def test_prague_levels(self):
        """Praha je v OSM jen kraj (admin_level 4) - obec se vezme z nej, cast z mestskych casti (9/10)."""
        p = self.search("korunni")[0]["properties"]
        self.assertEqual((p["city"], p["district"], p["state"]), ("Praha", "Vinohrady", "Praha"))
        p = self.search("vodickova 28")[0]["properties"]
        self.assertEqual((p["city"], p["district"]), ("Praha", "Nové Město"))

    def test_chain_segments(self):
        seg = lambda a, b: ((a, b), (a + 0.002, b + 0.002))                          # noqa: E731
        segs = [seg(50.0, 14.0), seg(50.002, 14.002), seg(50.004, 14.004),       # navazuji
                seg(50.2, 14.3)]                                                  # stejne jmeno jinde
        groups = build.chain_segments(segs, lambda s: s)
        self.assertEqual([len(g) for g in groups], [3, 1])

    def test_rings_and_raster(self):
        sq = [(0, 0), (0, 1), (1, 1)]
        rings = build._join_rings([sq, [(1, 1), (1, 0), (0, 0)]])
        self.assertEqual(len(rings), 1)
        self.assertEqual((len(rings[0]), rings[0][0] == rings[0][-1], set(rings[0])),
                         (5, True, {(0, 0), (0, 1), (1, 1), (1, 0)}))
        self.assertEqual(build._join_rings([sq]), [])                     # neuzavreny zbytek
        r = build.Raster(50.0, 14.0, 50.2, 14.2)
        r.fill(8, [[(50.05, 14.05), (50.05, 14.15), (50.15, 14.15), (50.15, 14.05), (50.05, 14.05)],
                   [(50.09, 14.09), (50.09, 14.11), (50.11, 14.11), (50.11, 14.09), (50.09, 14.09)]], 7)
        self.assertEqual(r.get(8, 50.07, 14.07, near=False), 7)
        self.assertEqual(r.get(8, 50.10, 14.10, near=False), 0)          # dira (inner)
        self.assertEqual(r.get(8, 50.18, 14.18, near=False), 0)


class TestRanking(GeocoderTestCase):
    def test_accents_and_stop_before_street_and_address(self):
        res = self.search("namesti miru", PRAHA)
        self.assertEqual(names(res)[:3], ["Náměstí Míru", "náměstí Míru", "náměstí Míru 820/9"])
        self.assertEqual(res[0]["properties"]["osm_key"], "railway")         # stanice (slouceno 4 -> 1)
        self.assertEqual(res[1]["properties"]["type"], "street")
        self.assertEqual(res[2]["properties"]["type"], "house")
        self.assertEqual(names(self.search("NÁMĚSTÍ míru", PRAHA))[:3], names(res)[:3])
        self.assertEqual(names(self.search("nam mir", PRAHA))[0], "Náměstí Míru")

    def test_distance_bias(self):
        self.assertEqual(names(self.search("masarykov", PRAHA))[0], "Masarykovo nábřeží")
        self.assertEqual(names(self.search("masarykov", BRNO))[0], "Masarykova")
        # dlouhe slovo: FTS hleda indexovanou predponu "masaryko", cele slovo overi Python
        self.assertEqual(names(self.search("masarykovo", BRNO)), ["Masarykovo nábřeží"])
        brno = self.search("namesti miru", BRNO)
        self.assertEqual(brno[0]["properties"]["city"], "Brno")
        self.assertEqual(names(self.search("namesti miru"))[0], "Náměstí Míru")   # bez polohy: dulezitost

    def test_address(self):
        res = self.search("vodickova 30", PRAHA)
        self.assertEqual(names(res)[0], "Vodičkova 681/30")
        p = res[0]["properties"]
        self.assertEqual((p["street"], p["housenumber"], p["postcode"], p["city"], p["district"]),
                         ("Vodičkova", "681/30", "11000", "Praha", "Nové Město"))
        # jednoznakove cislo: FTS ho nefiltruje (bez indexu 1 znaku), dofiltruje se v Pythonu
        self.assertEqual(names(self.search("vodickova 3", PRAHA))[0], "Vodičkova 3/3")
        self.assertEqual(names(self.search("vodickova", PRAHA))[0], "Vodičkova")
        self.assertEqual(self.search("vodickova 9", PRAHA), [])

    def test_poi_and_context(self):
        self.assertEqual(names(self.search("kavarna", PRAHA)), ["Kavárna Míru"])
        self.assertIn("Kavárna Míru", names(self.search("kavarna vodickova")))     # ulice v kontextu
        self.assertEqual(self.search("lavicka"), [])                               # lavicky se neindexuji
        self.assertEqual(names(self.search("muzeum", PRAHA)), ["Národní muzeum"])

    def test_lang_and_variants(self):
        self.assertEqual(names(self.search("prag"))[0], "Praha")
        self.assertEqual(names(self.search("prag", lang="de"))[0], "Prag")
        self.assertEqual(names(self.search("national mus", lang="en"))[0], "National Museum")
        self.assertEqual(self.search("prag", lang="en")[0]["properties"]["country"], "Czechia")
        self.assertEqual(self.search("prag", lang="cs")[0]["properties"]["country"], "Česko")

    def test_outside_coverage_and_short(self):
        self.assertEqual(self.search("wien"), [])
        self.assertEqual(self.search("v"), [])
        self.assertEqual(self.search(""), [])
        self.assertEqual(self.search('"; DROP TABLE feat; --'), [])
        self.assertEqual(self.search("náměstí* OR NEAR(a b)"), [])
        self.assertEqual(len(self.search("namesti", limit=2)), 2)
        self.assertEqual(G.Query("x" * 300).text, "x" * G.MAX_Q)
        self.assertEqual(G.Query("a", limit=99).limit, G.MAX_LIMIT)

    def test_client_parser_compatibility(self):
        import luxos_maps as lm
        data = {"type": "FeatureCollection", "features": self.search("namesti miru", PRAHA)}
        res = lm.parse_photon(json.loads(json.dumps(data)))
        self.assertEqual([(p["name"], p["kind"]) for p in res][:3],
                         [("Náměstí Míru", "stop"), ("náměstí Míru", "street"), ("náměstí Míru 820/9", "address")])
        self.assertEqual(res[0]["address"], "Praha, Česko")
        self.assertTrue(lm.is_transit_place(res[0]))
        self.assertEqual(res[0]["osm"].split("/")[0], "node")
        city = lm.parse_photon({"features": self.search("praha")})[0]
        self.assertEqual((city["name"], city["kind"], city["address"]), ("Praha", "city", "Česko"))
        poi = lm.parse_photon({"features": self.search("kavarna")})[0]
        self.assertEqual((poi["kind"], poi["address"]), ("poi", "Vodičkova 681/30, Praha, Česko"))
        addr = lm.parse_photon({"features": self.search("vodickova 30")})[0]
        self.assertEqual((addr["name"], addr["kind"], addr["address"]),
                         ("Vodičkova 681/30", "address", "Nové Město, Praha, Česko"))


class TestRateLimit(unittest.TestCase):
    def test_bucket(self):
        now = [0.0]
        rl = G.RateLimiter(burst=3, per_s=1.0, max_ips=2, clock=lambda: now[0])
        self.assertEqual([rl.allow("a") for _ in range(4)], [True, True, True, False])
        self.assertTrue(rl.allow("b"))
        now[0] = 1.0
        self.assertEqual([rl.allow("a"), rl.allow("a")], [True, False])
        now[0] = 100.0
        self.assertTrue(rl.allow("c"))           # plno: stare zaznamy se zahodi
        self.assertLessEqual(len(rl.buckets), 2)

    def test_client_ip(self):
        self.assertEqual(G.client_ip({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, "127.0.0.1"), "5.6.7.8")
        self.assertEqual(G.client_ip({"x-forwarded-for": "1.2.3.4"}, "9.9.9.9"), "9.9.9.9")   # jen od Caddy
        self.assertEqual(G.client_ip({}, "127.0.0.1"), "127.0.0.1")


class TestHTTP(GeocoderTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = G.App(cls.searcher, G.RateLimiter(burst=200, per_s=50))
        cls.loop = asyncio.new_event_loop()
        cls.stop = None
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(cls.loop)

            async def main():
                cls.stop = asyncio.Event()
                await G.serve(cls.app, "127.0.0.1", 0, ready=lambda p: (setattr(cls, "port", p), ready.set()),
                              stop=cls.stop)
            cls.loop.run_until_complete(main())
        cls.thread = threading.Thread(target=run, daemon=True)
        cls.thread.start()
        assert ready.wait(10)

    @classmethod
    def tearDownClass(cls):
        cls.loop.call_soon_threadsafe(cls.stop.set)
        cls.thread.join(10)
        super().tearDownClass()

    def get(self, path, conn=None, method="GET", headers=None):
        c = conn or http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        if conn is None:
            c.close()
        return r.status, dict(r.getheaders()), body

    def api(self, **params):
        return "/api?" + urllib.parse.urlencode(params)

    def test_api_keepalive(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        for q in ("namesti miru", "vodickova 30", "praha"):        # jedno spojeni, tri dotazy
            st, hdr, body = self.get(self.api(q=q, lat=50.08, lon=14.42, limit=3, lang="cs"), conn)
            self.assertEqual(st, 200)
            self.assertEqual(hdr["Content-Type"], "application/json; charset=utf-8")
            data = json.loads(body)
            self.assertEqual(data["type"], "FeatureCollection")
            self.assertLessEqual(len(data["features"]), 3)
            self.assertTrue(data["features"])
        conn.close()
        st, _h, body = self.get("/geocode/api?q=namesti")             # i s predponou (bez handle_path)
        self.assertEqual(st, 200)

    def test_limits(self):
        self.assertEqual(self.get(self.api(q="x" * 101))[0], 400)
        self.assertEqual(self.get(self.api(q="praha", limit="abc"))[0], 400)
        st, _h, body = self.get(self.api(q="namesti", limit=50))
        self.assertEqual(st, 200)
        self.assertLessEqual(len(json.loads(body)["features"]), G.MAX_LIMIT)
        st, _h, body = self.get(self.api(q="praha", lat="nan", lon="999"))      # spatna poloha = bez polohy
        self.assertEqual((st, names(json.loads(body)["features"])[0]), (200, "Praha"))
        self.assertEqual(self.get("/nothing")[0], 404)
        self.assertEqual(self.get(self.api(q="praha"), method="POST")[0], 405)
        st, _h, body = self.get(self.api(q="praha"), method="HEAD")
        self.assertEqual((st, body), (200, b""))
        st, _h, body = self.get("/health")
        self.assertEqual((st, json.loads(body)["features"]), (200, 19))

    def test_bad_requests(self):
        import socket
        for raw in (b"GARBAGE\r\n\r\n", b"GET /api?q=praha HTTP/1.1\r\nContent-Length: 5\r\n\r\nhello",
                    b"GET /api HTTP/1.1\r\n" + b"X: " + b"a" * 9000 + b"\r\n\r\n"):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            s.sendall(raw)
            resp = s.recv(4096)
            s.close()
            self.assertRegex(resp, rb"^HTTP/1.1 4(00|13|31) ")

    def test_rate_limit_http(self):
        old = self.app.limiter
        self.app.limiter = G.RateLimiter(burst=3, per_s=0.001)
        self.addCleanup(setattr, self.app, "limiter", old)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        codes = [self.get(self.api(q="praha"), conn, headers={"X-Forwarded-For": "203.0.113.5"})[0] for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        st, hdr, _b = self.get(self.api(q="praha"), conn, headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertEqual((st, hdr.get("Retry-After")), (429, "1"))
        # jina adresa ma vlastni limit
        self.assertEqual(self.get(self.api(q="praha"), headers={"X-Forwarded-For": "203.0.113.6"})[0], 200)

    def test_errors_do_not_log_query(self):
        old = self.searcher.search

        def boom(_q):
            raise RuntimeError("secret query text")
        self.searcher.search = boom
        self.addCleanup(setattr, self.searcher, "search", old)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            st, _h, body = self.get(self.api(q="moje tajna adresa"))
        self.assertEqual(st, 500)
        self.assertNotIn("tajna", err.getvalue() + body.decode())
        self.assertNotIn("secret", err.getvalue() + body.decode())


class TestReload(GeocoderTestCase):
    def test_symlink_swap(self):
        rel1, rel2 = os.path.join(self.tmp, "r1"), os.path.join(self.tmp, "r2")
        for d in (rel1, rel2):
            os.makedirs(d, exist_ok=True)
            shutil.copy(self.db, os.path.join(d, "geocoder.sqlite"))
        cur = os.path.join(self.tmp, "current")
        os.symlink(rel1, cur)
        s = G.Searcher(os.path.join(cur, "geocoder.sqlite"))
        self.assertTrue(s.search(G.Query("praha")))
        db1 = s.local.db
        self.assertFalse(s.check_reload())
        os.symlink(rel2, cur + ".new")
        os.replace(cur + ".new", cur)                       # jako deploy.sh: atomicka vymena
        self.assertTrue(s.check_reload())
        self.assertTrue(s.search(G.Query("praha")))
        self.assertIsNot(s.local.db, db1)


if __name__ == "__main__":
    unittest.main()
