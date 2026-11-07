#!/usr/bin/env python3
"""LuxOS Store - GUI: sekce Aplikace LuxOS (katalog) a kolecko pri kontrole aktualizaci.

Jen pod virtualnim displejem, se soukromym XDG_RUNTIME_DIR a docasnym HOME (test si je nastavi sam):
    env -u DISPLAY xvfb-run -a dbus-run-session python3 packages/luxos-store/tests/test_store_gui.py -v
Zadna skutecna databaze balicku ani instalace: lux, lux-engine a AppStream jsou nahrazene.
STORE_SHOTS=SLOZKA ulozi snimky stranek ve svetlem a tmavem vzhledu.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import source_catalog  # noqa: E402

FILES = os.path.join(source_catalog.PACKAGES, "luxos-store", "files")
I18N = os.path.join(source_catalog.PACKAGES, "luxos-i18n", "files")

TMP = tempfile.mkdtemp(prefix="luxos-store-gui-")
os.environ["HOME"] = os.path.join(TMP, "home")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.makedirs(os.environ["HOME"])
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.chmod(os.environ["XDG_RUNTIME_DIR"], 0o700)
# .desktop "nainstalovanych" aplikaci jen z docasne slozky; ikony a motivy ze systemu (jen cteni)
DATA = os.path.join(TMP, "data")
os.makedirs(os.path.join(DATA, "applications"))
for d in ("icons", "themes", "mime"):
    if os.path.isdir(f"/usr/share/{d}"):
        os.symlink(f"/usr/share/{d}", os.path.join(DATA, d))
os.environ["XDG_DATA_DIRS"] = DATA
os.environ.pop("XDG_DATA_HOME", None)
os.environ.update({"LUXOS_I18N_DIR": I18N, "LANG": "en_US.UTF-8", "LC_ALL": "", "LC_MESSAGES": "",
                   "LANGUAGE": "en", "GTK_THEME": "", "NO_AT_BRIDGE": "1"})
REPO = os.path.join(TMP, "repo")
os.makedirs(os.path.join(REPO, "app-icons"))
os.environ["LUXOS_STORE_CATALOG_URL"] = "file://" + os.path.join(REPO, "apps.json")
SHOTS = os.environ.get("STORE_SHOTS")

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    # moduly z pracovni kopie maji prednost pred nainstalovanymi (/usr/lib/luxos/python)
    sys.path.insert(0, FILES)
    sys.path.insert(0, I18N)
    import luxos_app_catalog  # noqa: E402,F401
    import luxos_i18n  # noqa: E402,F401
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

# ---- nahrazena data -------------------------------------------------------------
CATALOG = source_catalog.source_catalog() if HAVE_DISPLAY else {"apps": []}
SYNC_EXTRA = [("luxos", "vte3-utils", "0.84.1-1.1", "VTE utilities"),
              ("luxos-apps", "lsl", "0.10.8-1", "Lux Simple Lang - self-hosted programming language"),
              ("luxos-apps", "luxos-docs", "1.0.0-34", "Offline LuxOS and LSL reference library"),
              ("extra", "firefox", "140.0-1", "Fast, private and safe web browser")]
NOT_INSTALLED = {"luxos-mail", "luxai", "lsl-ide", "lux-code", "luxos-safe", "luxos-sandbox", "firefox", "lsl",
                 "luxos-docs", "vte3-utils"}
# aplikace prisla az v novejsi verzi luxos-desktop: balik je nainstalovany, jeji .desktop jeste ne
NEW_IN_UPDATE = "luxos-whats-new"


def sync_packages():
    pkgs = {a["package"]: ("luxos-apps" if a["package"] in ("luxai", "lsl-ide", "lux-code", "luxos-mail")
                           else "luxos") for a in CATALOG["apps"]}
    pkgs["luxos-desktop"] = "luxos"
    rows = [(repo, name, "1.0.0-1", "LuxOS package") for name, repo in sorted(pkgs.items())]
    return rows + SYNC_EXTRA


INSTALLED = sorted({r[1] for r in sync_packages()} - NOT_INSTALLED)
CALLS = []


def fake_run(*cmd, timeout=60):
    CALLS.append(cmd)
    if cmd[0] == store.LUX_ALPM and "list" in cmd:
        return "".join(f"{repo}\t{name}\t{ver}\t1048576\t{desc}\n" for repo, name, ver, desc in sync_packages())
    if cmd[0] == store.ENGINE and cmd[1] == "-Qq":
        return "\n".join(INSTALLED) + "\n"
    if cmd[0] == store.ENGINE and cmd[1] == "-Ql":
        out = []
        for a in CATALOG["apps"]:
            if a["package"] in cmd[2:]:
                out.append(f"{a['package']} {store.APPLICATIONS_DIR}{a['id']}.desktop")
        return "\n".join(out) + "\n"
    if cmd[0] == "curl":                # file:// z docasne slozky (zadna sit)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    if cmd[0] == "lux" and cmd[1:] == ("__index",):
        return "{}"
    return ""                           # flatpak, ostatni


class FakePool:
    """AppStream: firefox z Archu a knihovna vte3 (balik z repozitare LuxOS) - ta se nesmi zobrazit."""

    def load(self):
        pass

    def get_components_by_kind(self, _kind):
        comps = []
        for pkg, name, summary in (("firefox", "Firefox", "Browse the web"),
                                   ("vte3-utils", "VTE Terminal for GTK3", "Test application for the VTE widget")):
            c = AppStream.Component()
            c.set_kind(AppStream.ComponentKind.DESKTOP_APP)
            c.set_pkgnames([pkg])
            c.set_id(pkg + ".desktop")
            c.set_name(name, "C")
            c.set_summary(summary, "C")
            c.add_category("Utility")
            comps.append(c)

        class Box:
            def as_array(self):
                return comps
        return Box()


def write_fixture():
    """Katalog na "serveru" (file://) a .desktop nainstalovanych aplikaci."""
    for a in CATALOG["apps"]:
        if a["package"] in INSTALLED and a["id"] != NEW_IN_UPDATE:
            with open(os.path.join(DATA, "applications", a["id"] + ".desktop"), "w") as f:
                f.write(f"[Desktop Entry]\nType=Application\nName={a['name']}\nExec=true\nIcon={a['icon']}\n")
    # ikona nenainstalovane aplikace jen na serveru (app-icons/)
    for a in CATALOG["apps"]:
        if a["id"] == "luxos-mail":
            svg = next((os.path.join(r, f) for r, _d, fs in os.walk(source_catalog.PACKAGES) for f in fs
                        if f == "luxos-mail.svg" and "/tests/" not in r), None)
            if svg:
                shutil.copy(svg, os.path.join(REPO, "app-icons", "luxos-mail.svg"))
                a["icon_file"] = "luxos-mail.svg"
    with open(os.path.join(REPO, "apps.json"), "w", encoding="utf-8") as f:
        json.dump(CATALOG, f, ensure_ascii=False)


def pump(cond=lambda: False, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def widgets(w):
    out = [w]
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += widgets(c)
    return out


def cards(win):
    return [c for c in widgets(win.scroll) if isinstance(c, store.AppCard)]


def card(win, name):
    found = [c for c in cards(win) if c.app.name == name]
    return found[0] if found else None


def set_theme(dark):
    s = Gtk.Settings.get_default()
    names = ("WhiteSur-Dark", "WhiteSur-dark") if dark else ("WhiteSur-Light", "WhiteSur-light")
    if os.path.isdir(f"/usr/share/themes/{names[0]}"):
        s.set_property("gtk-theme-name", names[0])
        s.set_property("gtk-icon-theme-name", names[1])
    else:
        s.set_property("gtk-theme-name", "Adwaita")
        s.set_property("gtk-application-prefer-dark-theme", dark)


def shot(win, name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pump(timeout=0.6)
    gw = win.get_window()
    pix = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    pix.savev(os.path.join(SHOTS, name + ".png"), "png", [], [])


@unittest.skipUnless(HAVE_DISPLAY, "needs a virtual display (xvfb-run)")
class StoreGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_fixture()
        store.run = fake_run
        store.AppStream.Pool = FakePool
        cls.check_release = threading.Event()
        cls.checks = 0

        def slow_check(catalog):
            cls.checks += 1
            cls.check_release.wait(30)
            catalog.update_info, catalog.updates = {}, []
            return True
        store.Catalog.check_updates = slow_check
        provider = Gtk.CssProvider()
        provider.load_from_data(store.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        set_theme(False)
        cls.win = store.Store()
        cls.win.show_all()
        assert pump(lambda: cls.win.catalog.apps and cls.win.current == ("discover", None) and cards(cls.win), 30)

    @classmethod
    def tearDownClass(cls):
        cls.check_release.set()
        cls.win.destroy()
        pump(timeout=0.2)
        shutil.rmtree(TMP, ignore_errors=True)

    # ---- kolecko na strance Aktualizace ----
    def assert_spinning(self, view):
        self.assertEqual(view.icon_stack.get_visible_child_name(), "spin")
        self.assertIs(view.icon_stack.get_visible_child(), view.spinner)
        self.assertTrue(view.spinner.get_mapped(), "spinner is not on screen")
        self.assertTrue(view.spinner.get_property("active"))
        self.assertEqual(view.headline.get_text(), "Checking for updates…")

    def test_1_updates_spinner_first_open(self):
        """Prvni otevreni stranky po spusteni: kontrola bezi a kolecko se toci (driv chybelo)."""
        self.check_release.clear()
        self.win.open_updates()
        view = self.win.update_view
        self.assertTrue(pump(lambda: view.spinner.get_mapped(), 3))
        self.assert_spinning(view)
        set_theme(False)
        shot(self.win, "updates-spinner-light")
        set_theme(True)
        shot(self.win, "updates-spinner-dark")
        set_theme(False)
        # hotova kontrola: misto kolecka ikona vysledku
        self.check_release.set()
        self.assertTrue(pump(lambda: view.icon_stack.get_visible_child_name() == "icon", 5))
        self.assertFalse(view.spinner.get_property("active"))
        self.assertEqual(view.headline.get_text(), "Your computer is up to date")
        # znovu otevrena stranka (nova kontrola) a Zkontrolovat znovu: kolecko zase je
        self.check_release.clear()
        self.win.show_page("discover")
        self.win.open_updates()
        view = self.win.update_view
        self.assertTrue(pump(lambda: view.spinner.get_mapped(), 3))
        self.assert_spinning(view)
        self.check_release.set()
        self.assertTrue(pump(lambda: view.icon_stack.get_visible_child_name() == "icon", 5))

    # ---- sekce Aplikace LuxOS ----
    def luxos_names(self):
        self.win.show_page("luxos")
        pump(timeout=0.3)
        return [c.app.name for c in cards(self.win)]

    def test_2_luxos_page_lists_real_apps(self):
        names = self.luxos_names()
        for want in ("LuxAI", "Terminal", "Text Editor", "Maps", "Weather", "Mail", "Calculator", "Backups", "Safe",
                     "LuxDrop", "Connect to Computer", "Router", "Wi-Fi QR Code", "Phone", "Screenshot",
                     "Emoji & Symbols", "Printers & Scanners", "Scanner", "LuxAI Account", "Profile Picture",
                     "What's New", "LuxOS Tour", "Firewall", "Lux Guard", "Sandbox", "Drivers", "LSL IDE",
                     "Lux Code"):
            self.assertIn(want, names)
        for never in ("VTE Terminal for GTK3", "VTE Terminal for GTK4", "luxos-docs", "Lux Simple Lang", "lsl",
                      "Bluetooth", "Displays", "LuxOS Store", "Install LuxOS", "Launchpad", "Firefox",
                      "Keyboard Layouts", "Welcome to LuxOS"):
            self.assertNotIn(never, names)
        self.assertEqual(names[:6], ["LuxAI", "Terminal", "Text Editor", "Maps", "Weather", "Mail"])
        self.assertEqual(len(names), len(set(names)))
        rest = names[len([a for a in CATALOG["apps"] if a.get("featured")]):]
        self.assertEqual(rest, sorted(rest, key=str.lower))
        # karta: badge LuxOS a popis z .desktop
        c = card(self.win, "Safe")
        texts = [w.get_text() for w in widgets(c) if isinstance(w, Gtk.Label)]
        self.assertIn("✦ LuxOS", texts)
        self.assertIn("Encrypted folder for sensitive files", texts)
        for dark in (False, True):
            set_theme(dark)
            shot(self.win, "luxos-apps-" + ("dark" if dark else "light"))
        set_theme(False)

    def test_3_open_get_update_states(self):
        self.luxos_names()
        self.assertEqual(card(self.win, "Terminal").button.get_label(), "Open")
        self.assertEqual(card(self.win, "Calculator").button.get_label(), "Open")
        self.assertEqual(card(self.win, "Mail").button.get_label(), "Get")
        self.assertEqual(card(self.win, "LuxAI").button.get_label(), "Get")
        self.assertEqual(card(self.win, "What's New").button.get_label(), "Update")
        # znama aktualizace balicku: Aktualizovat i u nainstalovane aplikace
        self.win.catalog.update_info = {"luxos-backup": ("1.0.0-1", "1.0.0-2")}
        try:
            self.luxos_names()
            self.assertEqual(card(self.win, "Backups").button.get_label(), "Update")
            self.assertEqual(card(self.win, "LuxDrop").button.get_label(), "Open")
        finally:
            self.win.catalog.update_info = {}
        # Aktualizovat vede na stranku Aktualizace (zadna instalace)
        self.check_release.set()
        self.luxos_names()
        card(self.win, "What's New").button.clicked()
        self.assertEqual(self.win.current, ("updates", "check"))
        self.assertFalse([c for c in CALLS if c and c[0] == "pkexec"])

    def test_4_detail_never_offers_removing_the_desktop(self):
        for name, removable in (("Calculator", False), ("Terminal", False), ("LuxDrop", True)):
            self.luxos_names()
            self.win.show_detail(card(self.win, name).app)
            pump(timeout=0.2)
            labels = [w.get_label() for w in widgets(self.win.scroll) if isinstance(w, Gtk.Button)]
            self.assertIn("Open", labels)
            self.assertEqual("Remove" in labels, removable, name)

    def test_5_discover_and_categories(self):
        self.win.show_page("discover")
        pump(timeout=0.3)
        names = [c.app.name for c in cards(self.win)]
        self.assertEqual(names[:store.DISCOVER_LUXOS], ["LuxAI", "Terminal", "Text Editor", "Maps", "Weather", "Mail"])
        self.assertIn("Firefox", names)                  # oblibene aplikace z Archu dal
        self.assertNotIn("VTE Terminal for GTK3", names)
        self.win.show_page("utilities")
        pump(timeout=0.3)
        util = [c.app.name for c in cards(self.win)]
        for want in ("Calculator", "Weather", "Maps", "Safe", "Firefox"):
            self.assertIn(want, util)
        self.assertNotIn("VTE Terminal for GTK3", util)
        self.win.show_page("system")
        pump(timeout=0.3)
        self.assertIn("Terminal", [c.app.name for c in cards(self.win)])
        self.win.show_page("search", "terminal")
        pump(timeout=0.3)
        found = [c.app.name for c in cards(self.win)]
        self.assertIn("Terminal", found)
        self.assertNotIn("VTE Terminal for GTK3", found)

    def test_6_icon_of_not_installed_app_from_server(self):
        self.luxos_names()
        mail = card(self.win, "Mail").app
        if not any(a.get("icon_file") for a in CATALOG["apps"] if a["id"] == "luxos-mail"):
            self.skipTest("no luxos-mail.svg in the source tree")
        self.assertTrue(pump(lambda: mail.icon_file and os.path.exists(mail.icon_file), 10))
        self.assertTrue(mail.icon_file.startswith(store.ICON_CACHE))

    def test_7_czech(self):
        """Nazvy a popisy v jazyce uzivatele: z .desktop (Name[cs]), jinak z luxos-i18n."""
        tr = {}
        with open(os.path.join(I18N, "cs.tsv"), encoding="utf-8") as f:
            for line in f:
                if "\t" in line and not line.startswith("#"):
                    k, v = line.rstrip("\n").split("\t", 1)
                    tr[k] = v
        old = store.LANG, store._
        store.LANG, store._ = "cs", lambda t: tr.get(t, t)
        try:
            cat = store.Catalog()
            cat.load()
            by_id = {a.desktop: a for a in cat.apps.values() if a.luxos}
        finally:
            store.LANG, store._ = old
        self.assertEqual(by_id["luxos-terminal"].name, "Terminál")
        self.assertEqual(by_id["luxos-weather"].name, "Počasí")
        self.assertEqual(by_id["luxos-calculator"].name, "Kalkulačka")
        self.assertEqual(by_id["luxos-safe"].summary, "Šifrovaná složka pro citlivá data")
        self.assertEqual(by_id["luxai"].name, "LuxAI")

    def test_8_offline_first_start_uses_installed_apps(self):
        """Bez katalogu (offline, prazdna mezipamet): stejny vyber z nainstalovanych baliku LuxOS."""
        url, cache = store.CATALOG_URL, store.CATALOG_CACHE
        store.CATALOG_URL = "file://" + os.path.join(TMP, "missing.json")
        store.CATALOG_CACHE = os.path.join(TMP, "cache", "offline-apps.json")
        # .desktop "nainstalovanych" aplikaci s plnym obsahem (jako v /usr/share/applications)
        full = {did: text for p in source_catalog.source_packages() for did, text in p["desktop"].items()}
        saved = {}
        for did, text in full.items():
            path = os.path.join(DATA, "applications", did + ".desktop")
            if os.path.exists(path):
                with open(path) as f:
                    saved[path] = f.read()
                with open(path, "w") as f:
                    f.write(text)
        try:
            cat = store.Catalog()
            cat.load()
        finally:
            store.CATALOG_URL, store.CATALOG_CACHE = url, cache
            for path, text in saved.items():
                with open(path, "w") as f:
                    f.write(text)
        lux = {a.desktop for a in cat.apps.values() if a.luxos}
        self.assertIn("luxos-terminal", lux)
        self.assertIn("luxos-calculator", lux)
        self.assertNotIn("luxos-mail", lux)                  # nenainstalovana: bez katalogu neznama
        self.assertNotIn("luxos-bluetooth", lux)
        self.assertFalse(any("Vte" in (a.desktop or a.pkg) or a.pkg == "vte3-utils" for a in cat.apps.values()))


if __name__ == "__main__":
    unittest.main()
