#!/usr/bin/env python3
"""Katalog aplikaci LuxOS (luxos_app_catalog): vyber aplikaci z .desktop, preklady, generovani z repozitare.

    python3 packages/luxos-store/tests/test_app_catalog.py -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import source_catalog  # noqa: E402
from source_catalog import luxos_app_catalog as cat  # noqa: E402

I18N = os.path.join(source_catalog.PACKAGES, "luxos-i18n", "files")


def desktop(name="App", comment="Does things", cats="Utility;GTK;", extra=""):
    return (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\nExec=app\nIcon=app-icon\n"
            f"Categories={cats}\n{extra}\n[Desktop Action new]\nName=Should be ignored\nExec=app --new\n")


def pkg(name, repo="luxos", **desktops):
    return {"name": name, "repo": repo, "version": "1.0-1", "desktop": desktops}


def ids(catalog):
    return [a["id"] for a in catalog["apps"]]


class Selection(unittest.TestCase):
    def test_plain_app_with_localized_name_and_summary(self):
        d = desktop("Maps", "Maps of the world", "Utility;Maps;GTK;",
                    "Name[cs]=Mapy\nComment[cs]=Mapy světa\nName[xx]=nepodporovany jazyk")
        [app] = cat.build_catalog([pkg("luxos-maps", **{"luxos-maps": d})])["apps"]
        self.assertEqual(app["id"], "luxos-maps")
        self.assertEqual(app["package"], "luxos-maps")
        self.assertEqual(app["name"], "Maps")                 # [Desktop Action] neprepise Name
        self.assertEqual(app["names"], {"cs": "Mapy"})
        self.assertEqual(app["summaries"], {"cs": "Mapy světa"})
        self.assertEqual(app["categories"], ["Utility"])
        self.assertEqual(app["icon"], "app-icon")
        self.assertEqual(app["featured"], cat.FEATURED.index("luxos-maps") + 1)

    def test_hidden_settings_and_launchpad_copies_are_not_apps(self):
        c = cat.build_catalog([pkg("luxos-desktop", **{
            "luxos-calculator": desktop("Calculator"),
            "luxos-search": desktop("Search", extra="NoDisplay=true"),
            "luxos-gone": desktop("Gone", extra="Hidden=true"),
            "luxos-bluetooth": desktop("Bluetooth", cats="Settings;HardwareSettings;X-XFCE-SettingsDialog;"),
            "luxos-keyboard-launchpad": desktop("Keyboard Layouts"),
            "luxos-kde": desktop("KDE only", extra="OnlyShowIn=KDE;"),
            "luxos-link": desktop("Link").replace("Type=Application", "Type=Link"),
            "luxos-noexec": "[Desktop Entry]\nType=Application\nName=No Exec\n",
        })])
        self.assertEqual(ids(c), ["luxos-calculator"])

    def test_store_key_show_and_hide(self):
        c = cat.build_catalog([pkg("luxos-desktop", **{
            "luxos-profile-picture": desktop("Profile Picture", cats="Settings;DesktopSettings;",
                                             extra="X-LuxOS-Store=show"),
            "luxos-whats-new": desktop("What's New", cats="System;", extra="NoDisplay=true\nX-LuxOS-Store=show"),
            "luxos-launchpad": desktop("Launchpad", cats="System;", extra="X-LuxOS-Store=hide"),
            "luxos-deleted": desktop("Deleted", extra="Hidden=true\nX-LuxOS-Store=show"),
            "luxos-printers-launchpad": desktop("Printers", cats="Settings;", extra="X-LuxOS-Store=show"),
        })])
        self.assertEqual(sorted(ids(c)), ["luxos-profile-picture", "luxos-whats-new"])
        # panel Nastaveni bez hlavni kategorie Obchodu patri do System
        self.assertEqual(c["apps"][ids(c).index("luxos-profile-picture")]["categories"], ["System"])

    def test_only_luxos_packages(self):
        c = cat.build_catalog([
            pkg("vte3-utils", **{"org.gnome.Vte.App.Gtk3": desktop("VTE Terminal for GTK3")}),
            pkg("rofi", **{"rofi": desktop("Rofi")}),
            pkg("xfwm4", **{"xfce-wm-settings": desktop("Windows")}),
            pkg("luxos-docs", "luxos-apps"),                  # dokumentace bez .desktop
            pkg("lsl", "luxos-apps"),                         # prekladac bez .desktop
            pkg("luxos-terminal-debug", **{"luxos-terminal": desktop("Terminal")}),
            pkg("luxos-terminal", "extra", **{"luxos-terminal": desktop("Terminal")}),  # cizi repozitar
            pkg("lsl-ide", "luxos-apps", **{"lsl-ide": desktop("LSL IDE", cats="Development;")}),
            pkg("luxdrop", **{"luxdrop": desktop("LuxDrop", cats="Network;")}),
        ])
        self.assertEqual(sorted(ids(c)), ["lsl-ide", "luxdrop"])

    def test_same_desktop_id_once_luxos_apps_first(self):
        c = cat.build_catalog([pkg("luxos-thing", **{"luxos-x": desktop("From luxos")}),
                               pkg("luxos-x", "luxos-apps", **{"luxos-x": desktop("From apps")})])
        self.assertEqual([(a["id"], a["name"]) for a in c["apps"]], [("luxos-x", "From apps")])

    def test_system_apps_are_luxos_desktop_and_its_dependencies(self):
        d = cat.build_catalog([
            dict(pkg("luxos-desktop", **{"luxos-calculator": desktop("Calculator")}),
                 depends=["luxos-terminal>=1.0", "luxos-printing", "python"]),
            pkg("luxos-terminal", **{"luxos-terminal": desktop("Terminal")}),
            pkg("luxos-printing", **{"luxos-scan": desktop("Scanner")}),
            pkg("luxos-mail", "luxos-apps", **{"luxos-mail": desktop("Mail")}),
        ])
        system = {a["id"]: bool(a.get("system")) for a in d["apps"]}
        self.assertEqual(system, {"luxos-calculator": True, "luxos-terminal": True, "luxos-scan": True,
                                  "luxos-mail": False})

    def test_sorting_featured_first_then_name(self):
        c = cat.build_catalog([
            pkg("luxos-desktop", **{"luxos-zebra": desktop("Zebra"), "luxos-calculator": desktop("Calculator"),
                                    "luxos-alpha": desktop("alpha")}),
            pkg("luxos-terminal", **{"luxos-terminal": desktop("Terminal")}),
            pkg("luxai", "luxos-apps", **{"luxai": desktop("LuxAI")}),
        ])
        self.assertEqual(ids(c), ["luxai", "luxos-terminal", "luxos-calculator", "luxos-alpha", "luxos-zebra"])

    def test_load_catalog_validates(self):
        good = json.dumps({"format": 1, "apps": [{"id": "a", "package": "p", "name": "A"}, {"id": "broken"}, 5]})
        self.assertEqual(cat.load_catalog(good)["apps"], [{"id": "a", "package": "p", "name": "A"}])
        for bad in ("", "{", "[]", json.dumps({"format": 2, "apps": []}), json.dumps({"format": 1, "apps": {}})):
            self.assertIsNone(cat.load_catalog(bad), bad)


class SourceTree(unittest.TestCase):
    """Skutecne .desktop v repozitari: co v sekci Aplikace LuxOS je a co ne."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = source_catalog.source_catalog()
        cls.by_id = {a["id"]: a for a in cls.catalog["apps"]}

    def test_real_luxos_apps_are_listed(self):
        want = ["luxai", "luxos-terminal", "luxos-text", "luxos-maps", "luxos-weather", "luxos-mail",
                "luxos-calculator", "luxos-backup", "luxos-safe", "luxdrop", "luxdrop-connect", "luxos-router",
                "luxos-wifi-qr", "luxos-companion", "luxos-screenshot", "luxos-emoji", "luxos-printers",
                "luxos-scan", "luxos-account", "luxos-profile-picture", "luxos-whats-new", "luxos-tour",
                "luxos-firewall-settings", "luxos-guard", "luxos-sandbox", "luxos-drivers", "luxos-camera",
                "luxos-monitor", "luxos-feedback", "lsl-ide", "lux-code"]
        self.assertEqual([w for w in want if w not in self.by_id], [])

    def test_system_parts_settings_panes_and_helpers_are_not_listed(self):
        never = ["luxos-store", "luxos-install", "luxos-oem-seal", "luxos-launchpad", "luxos-about",
                 "luxos-welcome", "luxos-control-center", "luxos-search", "luxos-network-login",
                 "luxos-bluetooth", "luxos-display-settings", "luxos-keyboard", "luxos-power",
                 "luxos-lock-settings", "luxos-settings", "luxos-shortcuts", "luxos-appearance", "luxos-app-reset",
                 "luxos-fingerprint", "luxos-update", "luxos-domain-settings", "luxos-mail-background",
                 "luxos-guard-agent", "luxos-sandbox-launchers", "luxos-terminal-helper",
                 "luxos-printers-launchpad", "luxos-drivers-launchpad", "luxos-display-settings-launchpad"]
        self.assertEqual([n for n in never if n in self.by_id], [])
        for a in self.catalog["apps"]:
            self.assertNotIn("Vte", a["id"])
            self.assertTrue(set(a["categories"]) <= set(cat.STORE_CATEGORIES), a)

    def test_featured_order(self):
        self.assertEqual([a["id"] for a in self.catalog["apps"][:6]],
                         ["luxai", "luxos-terminal", "luxos-text", "luxos-maps", "luxos-weather", "luxos-mail"])

    def test_luxos_desktop_apps_are_system(self):
        for i in ("luxos-calculator", "luxos-terminal", "luxos-text", "luxos-screenshot", "luxos-whats-new"):
            self.assertTrue(self.by_id[i].get("system"), i)
        for i in ("luxos-mail", "luxai", "lsl-ide", "lux-code"):
            self.assertFalse(self.by_id[i].get("system"), i)

    def test_every_name_and_summary_is_translated(self):
        """Nazev a popis kazde aplikace ve vsech 12 jazycich: z .desktop, jinak z luxos-i18n
        (nazvy produktu jako LuxAI se neprekladaji)."""
        products = {"LuxAI", "LuxDrop", "LSL IDE", "Lux Code"}
        missing = []
        for lang in cat.LANGS:
            tsv = {}
            with open(os.path.join(I18N, f"{lang}.tsv"), encoding="utf-8") as f:
                for line in f:
                    if "\t" in line and not line.startswith("#"):
                        k, v = line.rstrip("\n").split("\t", 1)
                        tsv[k] = v
            for a in self.catalog["apps"]:
                for key, loc in (("name", "names"), ("summary", "summaries")):
                    text = a[key]
                    if text and text not in products and not (a.get(loc) or {}).get(lang) and not tsv.get(text):
                        missing.append((lang, text))
        self.assertEqual(missing, [])


def make_pkg(path, files):
    """Balik .pkg.tar.zst s danymi soubory {clen: bajty}."""
    root = tempfile.mkdtemp()
    try:
        for name, data in files.items():
            full = os.path.join(root, name)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        subprocess.run(["tar", "--zstd", "-cf", path, "-C", root, *files], check=True)
    finally:
        shutil.rmtree(root)


def make_db(path, entries):
    """Databaze repozitare (jako repo-add): <nazev>-<verze>/desc."""
    with tarfile.open(path, "w:gz") as tar:
        for e in entries:
            desc = f"%FILENAME%\n{e['filename']}\n\n%NAME%\n{e['name']}\n\n%VERSION%\n{e['version']}\n\n"
            if e.get("depends"):
                desc += "%DEPENDS%\n" + "\n".join(e["depends"]) + "\n\n"
            data = desc.encode()
            info = tarfile.TarInfo(f"{e['name']}-{e['version']}/desc")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class Generate(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-catalog-")

    def tearDown(self):
        shutil.rmtree(self.root)

    def repo(self, name, packages):
        d = os.path.join(self.root, name, "x86_64")
        os.makedirs(d, exist_ok=True)
        entries = []
        for p in packages:
            fname = f"{p['name']}-{p['version']}-any.pkg.tar.zst"
            make_pkg(os.path.join(d, fname), dict(p["files"], **{".PKGINFO": b"pkgname = " + p["name"].encode()}))
            if p.get("in_db", True):
                entries.append({"name": p["name"], "version": p["version"], "filename": fname,
                                "depends": p.get("depends")})
        make_db(os.path.join(d, f"{name}.db.tar.gz"), entries)

    def test_generate_from_repository(self):
        app = "usr/share/applications/"
        self.repo("luxos", [
            {"name": "luxos-desktop", "version": "1.0-2", "depends": ["luxos-themes", "luxos-terminal>=2"],
             "files": {app + "luxos-calculator.desktop": desktop("Calculator").replace(
                           "Icon=app-icon", "Icon=luxos-calculator").encode(),
                       app + "luxos-bluetooth.desktop": desktop("Bluetooth", cats="Settings;").encode(),
                       "usr/share/applications/screensavers/luxos.desktop": desktop("Saver").encode()}},
            # stara verze balicku lezi ve slozce, ale v databazi neni: nesmi se pouzit
            {"name": "luxos-desktop", "version": "1.0-1", "in_db": False,
             "files": {app + "luxos-old.desktop": desktop("Old app").encode()}},
            {"name": "luxos-themes", "version": "1-1", "files": {
                "usr/share/icons/hicolor/scalable/apps/luxos-calculator.svg": b"<svg/>",
                "usr/share/icons/hicolor/48x48/apps/luxos-calculator.png": b"small",
                "usr/share/icons/hicolor/256x256/apps/luxos-weather.png": b"PNG256",
                "usr/share/icons/hicolor/128x128/apps/luxos-weather.png": b"PNG128"}},
            {"name": "luxos-weather", "version": "1-1", "files": {
                app + "luxos-weather.desktop": desktop("Weather", extra="Name[cs]=Počasí").replace(
                    "Icon=app-icon", "Icon=luxos-weather").encode()}},
            {"name": "vte3-utils", "version": "0.84-1", "files": {
                app + "org.gnome.Vte.App.Gtk3.desktop": desktop("VTE Terminal for GTK3").encode()}},
        ])
        self.repo("luxos-apps", [
            {"name": "luxos-mail", "version": "1.0.0-1", "files": {
                app + "luxos-mail.desktop": desktop("Mail", cats="Network;Email;").encode()}},
            {"name": "luxos-docs", "version": "1.0.0-34", "files": {"usr/share/doc/luxos/index.md": b"# docs"}},
        ])
        os.makedirs(os.path.join(self.root, "app-icons"))
        with open(os.path.join(self.root, "app-icons", "removed-app.svg"), "w") as f:
            f.write("<svg/>")
        cat.generate(self.root)
        with open(os.path.join(self.root, "apps.json"), encoding="utf-8") as f:
            data = cat.load_catalog(f.read())
        by_id = {a["id"]: a for a in data["apps"]}
        self.assertEqual(sorted(by_id), ["luxos-calculator", "luxos-mail", "luxos-weather"])
        self.assertEqual(by_id["luxos-calculator"]["version"], "1.0-2")
        self.assertTrue(by_id["luxos-calculator"]["system"])
        self.assertNotIn("system", by_id["luxos-mail"])
        self.assertEqual(by_id["luxos-weather"]["names"], {"cs": "Počasí"})
        # ikona z jineho balicku (motiv): SVG pred PNG, jinak nejvetsi PNG; stare ikony pryc
        self.assertEqual(by_id["luxos-calculator"]["icon_file"], "luxos-calculator.svg")
        self.assertEqual(by_id["luxos-weather"]["icon_file"], "luxos-weather.png")
        self.assertNotIn("icon_file", by_id["luxos-mail"])            # app-icon v zadnem balicku neni
        icons = sorted(os.listdir(os.path.join(self.root, "app-icons")))
        self.assertEqual(icons, ["luxos-calculator.svg", "luxos-weather.png"])
        with open(os.path.join(self.root, "app-icons", "luxos-weather.png"), "rb") as f:
            self.assertEqual(f.read(), b"PNG256")
        self.assertFalse(os.path.exists(os.path.join(self.root, "apps.json.tmp")))

    def test_cli(self):
        self.repo("luxos", [{"name": "luxos-maps", "version": "1-1", "files": {
            "usr/share/applications/luxos-maps.desktop": desktop("Maps").encode()}}])
        r = subprocess.run([sys.executable, os.path.join(source_catalog.PACKAGES, "luxos-store", "files",
                                                         "luxos_app_catalog.py"), "generate", self.root],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 apps", r.stdout)
        r = subprocess.run([sys.executable, os.path.join(source_catalog.PACKAGES, "luxos-store", "files",
                                                         "luxos_app_catalog.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
