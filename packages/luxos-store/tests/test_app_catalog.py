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


def metainfo(did="luxos-maps", langs=cat.LANGS, drop=(), extra_li=None, untranslated_p=False):
    """Metainfo s odstavcem a seznamem; drop = jazyky bez prekladu polozky seznamu, extra_li = jazyk s polozkou
    navic, untranslated_p = druhy odstavec jen anglicky."""
    def tr(tag, en, skip=()):
        out = [f"<{tag}>{en}</{tag}>"]
        out += [f'<{tag} xml:lang="{lg}">{en} ({lg})</{tag}>' for lg in langs if lg not in skip]
        return "\n".join(out)
    extra = f'<li xml:lang="{extra_li}">navic</li>' if extra_li else ""
    second = "<p>  Second\n   paragraph.  </p>\n" if untranslated_p else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<component type="desktop-application">\n<id>{did}</id>\n'
            f'<launchable type="desktop-id">{did}.desktop</launchable>\n<description>\n'
            f'{tr("p", "Find places &amp; routes.")}\n{second}'
            f'<ul>\n{tr("li", "Offline maps")}\n{tr("li", "Search", drop)}\n{extra}</ul>\n</description>\n</component>\n')


class Descriptions(unittest.TestCase):
    def test_parse_metainfo_all_languages(self):
        did, desc = cat.parse_metainfo(metainfo())
        self.assertEqual(did, "luxos-maps")
        self.assertEqual(set(desc), {"en"} | set(cat.LANGS))
        self.assertEqual(desc["en"], [{"p": "Find places & routes."}, {"ul": ["Offline maps", "Search"]}])
        self.assertEqual(desc["cs"], [{"p": "Find places & routes. (cs)"}, {"ul": ["Offline maps (cs)", "Search (cs)"]}])

    def test_incomplete_translation_falls_back_to_english(self):
        _did, desc = cat.parse_metainfo(metainfo(drop=("de",), extra_li="fr"))
        self.assertNotIn("de", desc)          # chybi polozka seznamu
        self.assertNotIn("fr", desc)          # polozka navic
        self.assertIn("cs", desc)
        # odstavec bez prekladu: zadny jazyk neni uplny, zbyva anglictina (whitespace se slouci)
        _did, desc = cat.parse_metainfo(metainfo(untranslated_p=True))
        self.assertEqual(list(desc), ["en"])
        self.assertEqual(desc["en"][1], {"p": "Second paragraph."})

    def test_desktop_id_and_invalid_files(self):
        self.assertEqual(cat.parse_metainfo("<component><id>x.desktop</id><description><p>A</p></description>"
                                            "</component>"), ("x", {"en": [{"p": "A"}]}))
        self.assertEqual(cat.parse_metainfo("<component><id>x</id></component>"), ("x", {}))
        self.assertEqual(cat.parse_metainfo("<component><description>"), (None, {}))
        self.assertEqual(cat.parse_metainfo(""), (None, {}))

    def test_build_catalog_attaches_description_by_desktop_id(self):
        c = cat.build_catalog([dict(pkg("luxos-maps", **{"luxos-maps": desktop("Maps")}),
                                    metainfo={"luxos-maps.metainfo.xml": metainfo(),
                                              "other.metainfo.xml": metainfo("luxos-other"),
                                              "broken.metainfo.xml": "<component"})])
        [app] = c["apps"]
        self.assertEqual(app["description"]["en"][0], {"p": "Find places & routes."})
        self.assertEqual(app["description"]["sv"][1]["ul"][0], "Offline maps (sv)")
        c = cat.build_catalog([pkg("luxos-maps", **{"luxos-maps": desktop("Maps")})])
        self.assertNotIn("description", c["apps"][0])

    def test_appstream_markup(self):
        self.assertEqual(cat.description_blocks(
            "<p>Fast &amp; <em>private</em> browser.</p><ul><li>Tabs</li><li> Sync\n</li></ul><p>More</p>"),
            [{"p": "Fast & private browser."}, {"ul": ["Tabs", "Sync"]}, {"p": "More"}])
        self.assertEqual(cat.description_blocks("Plain text only"), [{"p": "Plain text only"}])
        self.assertEqual(cat.description_blocks(""), [])
        self.assertEqual(cat.description_blocks("<ol><li>One</li></ol>"), [{"ul": ["One"]}])


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

    def test_every_app_has_a_complete_localized_description(self):
        """Dlouhy popis kazde aplikace (metainfo balicku): odstavec a seznam vlastnosti, anglicky a ve vsech
        12 jazycich se stejnou stavbou, preklad neni anglicky text."""
        problems = []
        for a in self.catalog["apps"]:
            desc = a.get("description") or {}
            if not desc:
                problems.append((a["id"], "no description"))
                continue
            en = desc["en"]
            if not any("p" in b for b in en) or not any("ul" in b for b in en):
                problems.append((a["id"], "needs a paragraph and a feature list"))
            words = sum(len(" ".join(b.get("ul", [b.get("p", "")])).split()) for b in en)
            if not 25 <= words <= 140:
                problems.append((a["id"], f"{words} English words"))
            for lang in cat.LANGS:
                if lang not in desc:
                    problems.append((a["id"], f"{lang} missing or incomplete"))
                elif json.dumps(desc[lang]) == json.dumps(en):
                    problems.append((a["id"], f"{lang} is English"))
        self.assertEqual(problems, [])

    def test_metainfo_matches_desktop(self):
        """Nazev a popis v metainfo odpovidaji .desktop (jeden zdroj pravdy pro kratke texty)."""
        import xml.etree.ElementTree as ET
        for p in source_catalog.source_packages():
            for fname, text in p.get("metainfo", {}).items():
                root = ET.fromstring(text)
                did = fname[:-len(".metainfo.xml")]
                self.assertEqual(root.findtext("id"), did, fname)
                self.assertIn(did, p["desktop"], f"{fname}: no {did}.desktop in {p['name']}")
                entry = cat.parse_desktop(p["desktop"][did])
                self.assertEqual(root.findtext("name"), entry["Name"], fname)
                self.assertEqual(root.findtext("summary"), entry.get("Comment", ""), fname)

    def test_screenshots(self):
        """Snimky v packages/luxos-store/screens: kazda aplikace katalogu 1-3 snimky, WebP do 150 KB a 1280 px,
        rozmery v manifestu sedi se souborem."""
        screens = os.path.join(source_catalog.PACKAGES, "luxos-store", "screens")
        with open(os.path.join(screens, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(sorted(set(manifest) - set(self.by_id)), [])     # zadne snimky odebranych aplikaci
        for app_id, shots in manifest.items():
            self.assertTrue(1 <= len(shots) <= 3, app_id)
            for e in shots:
                for key in ("file", "dark"):
                    if not e.get(key):
                        continue
                    path = os.path.join(screens, app_id, e[key])
                    self.assertLessEqual(os.path.getsize(path), 150 * 1024, path)
                    self.assertEqual(webp_size(path), (e["width"], e["height"]), path)
                    self.assertLessEqual(e["width"], 1280, path)
        self.assertEqual(sorted(f for f in os.listdir(screens) if f != "manifest.json"), sorted(manifest))


def webp_size(path):
    """Rozmery obrazku WebP z hlavicky (VP8, VP8L, VP8X) bez knihoven."""
    import struct
    with open(path, "rb") as f:
        head = f.read(40)
    assert head[:4] == b"RIFF" and head[8:12] == b"WEBP", path
    chunk = head[12:16]
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        b = head[21:25]
        return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
    if chunk == b"VP8X":
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    raise AssertionError(path)


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
        self.assertNotIn("screenshots", by_id["luxos-weather"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "app-screens")))

    def test_descriptions_and_screenshots(self):
        app = "usr/share/applications/"
        self.repo("luxos", [
            {"name": "luxos-weather", "version": "1-1", "files": {
                app + "luxos-weather.desktop": desktop("Weather").encode(),
                "usr/share/metainfo/luxos-weather.metainfo.xml": metainfo("luxos-weather").encode()}},
            {"name": "luxos-maps", "version": "1-1", "files": {app + "luxos-maps.desktop": desktop("Maps").encode()}},
        ])
        screens = os.path.join(self.root, "src-screens")
        for d in ("luxos-weather", "luxos-maps", "luxos-removed"):
            os.makedirs(os.path.join(screens, d))
        for name in ("luxos-weather/1.webp", "luxos-weather/1-dark.webp", "luxos-weather/2.webp",
                     "luxos-maps/1.webp", "luxos-removed/1.webp"):
            with open(os.path.join(screens, name), "wb") as f:
                f.write(b"RIFF" + name.encode())
        with open(os.path.join(screens, "manifest.json"), "w") as f:
            json.dump({"luxos-weather": [{"file": "1.webp", "width": 900, "height": 640, "dark": "1-dark.webp"},
                                         {"file": "2.webp", "width": 800, "height": 600}],
                       "luxos-maps": [{"file": "missing.webp", "width": 1, "height": 1},
                                      {"file": "1.webp", "width": "bad"}],
                       "luxos-removed": [{"file": "1.webp", "width": 10, "height": 10}]}, f)
        os.makedirs(os.path.join(self.root, "app-screens", "old-app"))       # z drivejsiho behu
        cat.generate(self.root, screens=screens)
        with open(os.path.join(self.root, "apps.json"), encoding="utf-8") as f:
            by_id = {a["id"]: a for a in cat.load_catalog(f.read())["apps"]}
        w = by_id["luxos-weather"]
        self.assertEqual(w["description"]["en"][0], {"p": "Find places & routes."})
        self.assertEqual(w["description"]["cs"][1], {"ul": ["Offline maps (cs)", "Search (cs)"]})
        self.assertEqual(w["screenshots"], [
            {"url": "app-screens/luxos-weather/1.webp", "width": 900, "height": 640,
             "dark": "app-screens/luxos-weather/1-dark.webp"},
            {"url": "app-screens/luxos-weather/2.webp", "width": 800, "height": 600}])
        self.assertNotIn("description", by_id["luxos-maps"])
        self.assertNotIn("screenshots", by_id["luxos-maps"])                  # chybejici soubor, spatny zaznam
        out = os.path.join(self.root, "app-screens")
        self.assertEqual(sorted(os.listdir(out)), ["luxos-weather"])
        self.assertEqual(sorted(os.listdir(os.path.join(out, "luxos-weather"))), ["1-dark.webp", "1.webp", "2.webp"])
        with open(os.path.join(out, "luxos-weather", "2.webp"), "rb") as f:
            self.assertEqual(f.read(), b"RIFFluxos-weather/2.webp")

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
