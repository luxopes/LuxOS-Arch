#!/usr/bin/env python3
"""LuxOS Store - seznam aplikaci hned po spusteni (velky katalog, kopie z minuleho spusteni, offline,
obnoveni katalogu na pozadi, pomaly index .lux).

Jen pod virtualnim displejem, se soukromym XDG_RUNTIME_DIR a docasnym HOME (test si je nastavi sam):
    env -u DISPLAY xvfb-run -a dbus-run-session python3 packages/luxos-store/tests/test_store_startup.py -v
Zadna skutecna databaze balicku ani sit: lux, lux-engine a AppStream jsou nahrazene (s umyslnym zpozdenim
jako pomaly pocitac), katalog podava mistni server. STORE_BUDGET = limit prvniho zobrazeni v sekundach.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGES = os.path.abspath(os.path.join(HERE, "..", ".."))
FILES = os.path.join(PACKAGES, "luxos-store", "files")
I18N = os.path.join(PACKAGES, "luxos-i18n", "files")

TMP = tempfile.mkdtemp(prefix="luxos-store-startup-")
os.environ["HOME"] = os.path.join(TMP, "home")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.makedirs(os.environ["HOME"])
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
DATA = os.path.join(TMP, "data")
os.makedirs(os.path.join(DATA, "applications"))
for d in ("icons", "themes", "mime"):
    if os.path.isdir(f"/usr/share/{d}"):
        os.symlink(f"/usr/share/{d}", os.path.join(DATA, d))
os.environ["XDG_DATA_DIRS"] = DATA
os.environ.pop("XDG_DATA_HOME", None)
os.environ.update({"LUXOS_I18N_DIR": I18N, "LANG": "en_US.UTF-8", "LC_ALL": "", "LC_MESSAGES": "",
                   "LANGUAGE": "en", "GTK_THEME": "", "NO_AT_BRIDGE": "1"})
BUDGET = float(os.environ.get("STORE_BUDGET", "1.0"))
N_LUXOS, N_ARCH = 300, 300


class Server:
    """Mistni server katalogu: ETag/If-None-Match (304), pocitadlo stazeni; hang = spojeni prijme
    a neodpovi (sit, ktera nefunguje - curl ceka na casovy limit)."""

    def __init__(self):
        self.catalog = b""
        self.etag = "v1"
        self.hang = threading.Event()
        self.bodies = self.not_modified = 0
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                while srv.hang.is_set():
                    time.sleep(0.05)
                if self.path != "/apps.json":
                    self.send_error(404)
                    return
                if self.headers.get("If-None-Match") == f'"{srv.etag}"':
                    srv.not_modified += 1
                    self.send_response(304)
                    self.end_headers()
                    return
                srv.bodies += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("ETag", f'"{srv.etag}"')
                self.send_header("Content-Length", str(len(srv.catalog)))
                self.end_headers()
                self.wfile.write(srv.catalog)

            def log_message(self, *_a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d/apps.json" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


SERVER = Server()
os.environ["LUXOS_STORE_CATALOG_URL"] = SERVER.url

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    sys.path.insert(0, FILES)
    sys.path.insert(0, I18N)
    import luxos_app_catalog  # noqa: E402
    import gi  # noqa: E402
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("AppStream", "1.0")
    from gi.repository import AppStream, Gdk, Gtk  # noqa: E402

    loader = importlib.machinery.SourceFileLoader("luxos_store", os.path.join(FILES, "luxos-store"))
    spec = importlib.util.spec_from_loader("luxos_store", loader)
    store = importlib.util.module_from_spec(spec)
    loader.exec_module(store)
    store.APPLICATIONS_DIR = os.path.join(DATA, "applications") + "/"
    store.LOCAL_CATALOGS = ()


def catalog(extra=()):
    apps = [{"id": "demo-app-%03d" % i, "package": "demo-app-%03d" % i, "name": "Demo App %03d" % i,
             "summary": "LuxOS demo application number %d" % i, "icon": "", "categories": ["Utility"],
             **({"featured": i + 1} if i < 6 else {})} for i in range(N_LUXOS)]
    return {"format": 1, "apps": apps + list(extra)}


def write_cache(data, age=0):
    os.makedirs(store.CACHE_DIR, exist_ok=True)
    with open(store.CATALOG_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    t = time.time() - age
    os.utime(store.CATALOG_CACHE, (t, t))


# ---- nahrazena data (zpozdeni jako pomaly pocitac) ---------------------------------
DELAY = {"sync": 0.0, "pool": 0.0, "index": 0.0}
INDEX = {"packages": []}
SYNC = ([("luxos-apps", "demo-app-%03d" % i, "1.0-1") for i in range(N_LUXOS + 5)] +
        [("extra", "arch-app-%03d" % i, "2.0-1") for i in range(N_ARCH - 1)] + [("extra", "firefox", "140.0-1")])
INSTALLED = {"demo-app-000", "arch-app-000"}
CALLS = []


def fake_run(*cmd, timeout=60):
    CALLS.append(cmd)
    if cmd[0] == store.LUX_ALPM and "list" in cmd:
        time.sleep(DELAY["sync"])
        return "".join(f"{r}\t{n}\t{v}\t1048576\tdesc\n" for r, n, v in SYNC)
    if cmd[0] == store.ENGINE and cmd[1] == "-Qq":
        return "\n".join(sorted(INSTALLED)) + "\n"
    if cmd[0] == "curl":
        import subprocess
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
        except subprocess.TimeoutExpired:
            return ""
    if cmd[0] == "lux" and cmd[1:] == ("__index",):
        time.sleep(DELAY["index"])
        return json.dumps(INDEX)
    return ""


class FakePool:
    def load(self):
        time.sleep(DELAY["pool"])

    def get_components_by_kind(self, _kind):
        comps = []
        for i in range(N_ARCH):
            # posledni = oblibena aplikace (Objevovat › Oblibene aplikace)
            pkg = "arch-app-%03d" % i if i < N_ARCH - 1 else "firefox"
            c = AppStream.Component()
            c.set_kind(AppStream.ComponentKind.DESKTOP_APP)
            c.set_pkgnames([pkg])
            c.set_id(pkg + ".desktop")
            c.set_name("Arch App %03d" % i, "C")
            c.set_summary("Application from Arch Linux %d" % i, "C")
            c.set_description("<p>Long description %d.</p>" % i, "C")
            c.add_category("Utility")
            comps.append(c)

        class Box:
            def as_array(self):
                return comps
        return Box()


def pump(cond=lambda: False, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def widgets(w):
    out = [w]
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += widgets(c)
    return out


def mapped_cards(win):
    return [c for c in widgets(win.scroll) if isinstance(c, store.AppCard) and c.get_mapped()]


@unittest.skipUnless(HAVE_DISPLAY, "needs a virtual display (xvfb-run)")
class StoreStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.run = fake_run
        store.AppStream.Pool = FakePool
        store.Catalog.check_updates = lambda catalog: True
        provider = Gtk.CssProvider()
        provider.load_from_data(store.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        SERVER.catalog = json.dumps(catalog()).encode()
        # nainstalovana aplikace LuxOS ma svuj .desktop (jinak by nabizela Aktualizovat)
        with open(os.path.join(DATA, "applications", "demo-app-000.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Demo App 000\nExec=true\n")

    @classmethod
    def tearDownClass(cls):
        SERVER.hang.clear()
        SERVER.httpd.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        DELAY.update(sync=0.0, pool=0.0, index=0.0)
        SERVER.hang.clear()
        self.win = None
        if os.path.isdir(store.CACHE_DIR):
            write_cache(catalog())          # cerstvy zakladni katalog (testy ho meni)

    def tearDown(self):
        if self.win:
            self.win.destroy()
            pump(timeout=0.1)

    def start(self):
        """Okno obchodu -> (cas do prvni karty na obrazovce, katalog uz uplne nacteny v tu chvili?)"""
        t0 = time.monotonic()
        self.win = store.Store()
        self.win.show_all()
        self.assertTrue(pump(lambda: mapped_cards(self.win), 30), "no app card shown")
        return time.monotonic() - t0, self.win.catalog.loaded

    def wait_loaded(self, timeout=15):
        self.assertTrue(pump(lambda: self.win.catalog.loaded and not self.win.snapshot_save, timeout))
        pump(timeout=0.2)

    # ---- prvni spusteni: zastupne karty, pak seznam; kopie pro pristi spusteni ----
    def test_1_first_start_skeleton_then_list(self):
        shutil.rmtree(store.CACHE_DIR, ignore_errors=True)
        DELAY.update(sync=0.6, pool=1.5)
        self.win = store.Store()
        self.win.show_all()
        pump(timeout=0.1)
        ws = widgets(self.win.scroll)
        self.assertFalse([w for w in ws if isinstance(w, Gtk.Spinner)], "blocking spinner instead of the list")
        self.assertTrue([w for w in ws if w.get_style_context().has_class("skeleton")])
        # aplikace LuxOS driv nez AppStream (prvni spusteni, AppStream se nacita dlouho)
        self.assertTrue(pump(lambda: mapped_cards(self.win), 10))
        self.assertFalse(self.win.catalog.loaded)
        self.assertTrue(all(c.app.luxos for c in mapped_cards(self.win)))
        self.wait_loaded()
        self.assertFalse([w for w in widgets(self.win.scroll) if w.get_style_context().has_class("skeleton")])
        self.assertTrue(os.path.exists(store.SNAPSHOT))
        with open(store.SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual(len(snap["apps"]), N_LUXOS + N_ARCH)
        self.assertEqual(SERVER.bodies, 1)

    # ---- dalsi spusteni: seznam z kopie hned, i kdyz uplne nacteni trva ----
    def test_2_cached_start_within_budget(self):
        if not os.path.exists(store.SNAPSHOT):
            self.test_1_first_start_skeleton_then_list()
            self.tearDown()
        DELAY.update(sync=2.5, pool=2.5)
        dt, loaded = self.start()
        print(f"\n  cached start: first app card on screen after {dt * 1000:.0f} ms (budget {BUDGET * 1000:.0f} ms)",
              file=sys.stderr)
        self.assertLess(dt, BUDGET)
        self.assertFalse(loaded, "list waited for the full catalog load")
        names = [c.app.name for c in mapped_cards(self.win)]
        self.assertEqual(names[:6], ["Demo App %03d" % i for i in range(6)])
        before = list(self.win.cards)
        self.wait_loaded()
        # stejny obsah: karty zustaly, maji jen novejsi zaznamy (AppStream s popisem)
        self.assertEqual(self.win.current, ("discover", None))
        self.assertEqual([id(c) for c in self.win.cards], [id(c) for c in before])
        self.assertFalse(any(c.app.partial for c in self.win.cards))
        # stav tlacitek z kopie: nainstalovana Open, ostatni Get
        by_name = {c.app.name: c for c in self.win.cards}
        self.assertEqual(by_name["Demo App 000"].button.get_label(), "Open")
        self.assertEqual(by_name["Demo App 001"].button.get_label(), "Get")

    def test_3_large_category_builds_incrementally(self):
        dt, _l = self.start()
        self.wait_loaded()
        t0 = time.monotonic()
        self.win.show_page("utilities")
        took = time.monotonic() - t0
        print(f"\n  category with {N_LUXOS + N_ARCH} apps: show_page {took * 1000:.0f} ms", file=sys.stderr)
        self.assertLess(took, 0.5)
        self.assertEqual(len(self.win.cards), store.GRID_FIRST)
        self.assertTrue(pump(lambda: len(self.win.cards) == N_LUXOS + N_ARCH, 20))
        self.assertEqual(len([c for c in widgets(self.win.scroll) if isinstance(c, store.AppCard)]),
                         N_LUXOS + N_ARCH)
        # ikony se nacitaji na pozadi; jiz nactene jsou v pameti (druhe zobrazeni je ma hned)
        pump(timeout=1.0)
        self.win.show_page("discover")
        self.win.show_page("utilities")
        self.assertTrue(all(c.image.get_storage_type() != Gtk.ImageType.EMPTY
                            for c in self.win.cards if c.app.icon_name or c.app.component))

    def test_4_offline_cached_start(self):
        """Stara kopie katalogu a sit, ktera neodpovida: seznam hned, uplne nacteni neceka na sit."""
        write_cache(catalog(), age=7 * 3600)
        SERVER.hang.set()
        DELAY.update(sync=0.3)
        try:
            dt, _l = self.start()
            self.assertLess(dt, BUDGET)
            t0 = time.monotonic()
            self.assertTrue(pump(lambda: self.win.catalog.loaded, 6))
            self.assertLess(time.monotonic() - t0, 3.0, "full load waited for the network")
            self.win.show_page("luxos")
            pump(timeout=0.5)
            self.assertEqual(len(self.win.cards), N_LUXOS)
        finally:
            SERVER.hang.clear()

    def test_5_background_refresh_updates_list(self):
        """Starsi katalog: zobrazi se hned, novy (ETag) doplni seznam na miste; nezmeneny = 304."""
        write_cache(catalog(), age=7 * 3600)
        new = {"id": "brand-new-tool", "package": "demo-app-%03d" % N_LUXOS, "name": "Brand New Tool",
               "summary": "Arrived with the refreshed catalog", "icon": "", "categories": ["Utility"]}
        SERVER.catalog = json.dumps(catalog([new])).encode()
        SERVER.etag = "v2"
        bodies = SERVER.bodies
        try:
            self.start()
            self.win.show_page("luxos")
            self.assertTrue(pump(lambda: "Brand New Tool" in [c.app.name for c in self.win.cards], 10))
            self.assertEqual(self.win.current, ("luxos", None))
            self.assertEqual(SERVER.bodies, bodies + 1)
            self.wait_loaded()
            # dalsi obnoveni: server rekne "nezmeneno" (ETag), katalog se nestahuje a je opet cerstvy
            t = time.time() - 7 * 3600
            os.utime(store.CATALOG_CACHE, (t, t))
            not_modified = SERVER.not_modified
            self.assertFalse(self.win.catalog.fetch_catalog())
            self.assertEqual(SERVER.not_modified, not_modified + 1)
            self.assertEqual(SERVER.bodies, bodies + 1)
            self.assertTrue(self.win.catalog.catalog_fresh())
            with open(store.CATALOG_CACHE, encoding="utf-8") as f:
                self.assertIn("Brand New Tool", f.read())
        finally:
            SERVER.catalog = json.dumps(catalog()).encode()
            SERVER.etag = "v1"

    def test_6_slow_lux_index_does_not_block(self):
        INDEX["packages"] = [{"name": "lux-demo", "title": "Lux Demo Package", "summary": "A .lux package",
                              "version": "1.0", "release": 1, "size": 1000, "categories": ["Utility"]}]
        DELAY.update(index=3.0)
        try:
            t0 = time.monotonic()
            self.start()
            self.assertTrue(pump(lambda: self.win.catalog.loaded, 10))
            self.assertLess(time.monotonic() - t0, 2.0, "full load waited for lux __index")
            self.assertNotIn("lux-demo", self.win.catalog.apps)
            self.win.search.set_text("Lux Demo")
            self.assertTrue(pump(lambda: "Lux Demo Package" in [c.app.name for c in self.win.cards], 10))
            self.assertEqual(self.win.current, ("search", "Lux Demo"))
        finally:
            INDEX["packages"] = []

    def test_7_search_typed_during_load_stays(self):
        """Hledani zadane pred dokoncenim nacteni (luxos-store "text"): po nacteni zustane (driv Objevovat)."""
        DELAY.update(sync=1.0)
        self.win = store.Store()
        self.win.show_all()
        self.win.search.set_text("Arch App 01")
        self.wait_loaded()
        self.assertEqual(self.win.current, ("search", "Arch App 01"))
        names = [c.app.name for c in self.win.cards]
        self.assertIn("Arch App 010", names)

    def test_8_cards_tracked_and_detail_kept(self):
        """Karty stranky jsou v seznamu (aktualizace tlacitek po instalaci); stazene ikony neprekresli
        stranku aplikace na prazdnou."""
        self.start()
        self.wait_loaded()
        self.win.show_page("luxos")
        pump(timeout=0.5)
        shown = [c for c in widgets(self.win.scroll) if isinstance(c, store.AppCard)]
        self.assertEqual(len(self.win.cards), len(shown))
        self.assertEqual(len(shown), N_LUXOS)
        app = self.win.catalog.apps["demo-app-003"]
        self.win.show_detail(app)
        self.win.icons_fetched({app.key})
        self.win.catalog_changed()
        pump(timeout=0.3)
        self.assertEqual(self.win.current, ("detail", app))
        labels = [w.get_text() for w in widgets(self.win.scroll) if isinstance(w, Gtk.Label)]
        self.assertIn("Demo App 003", labels)
        self.win.go_back()
        self.assertEqual(self.win.current, ("luxos", None))

    def test_9_partial_detail_fills_in(self):
        """Stranka aplikace otevrena z kopie (bez popisu AppStream) se po nacteni doplni."""
        DELAY.update(sync=1.5)
        self.start()
        app = self.win.catalog.apps["arch-app-007"]
        self.assertTrue(app.partial)
        self.win.show_detail(app)
        self.wait_loaded()
        cur = self.win.current
        self.assertEqual(cur[0], "detail")
        self.assertFalse(cur[1].partial)
        labels = [w.get_text() for w in widgets(self.win.scroll) if isinstance(w, Gtk.Label)]
        self.assertIn("Long description 7.", labels)
        self.win.go_back()
        self.assertEqual(self.win.current, ("discover", None))


if __name__ == "__main__":
    unittest.main()
