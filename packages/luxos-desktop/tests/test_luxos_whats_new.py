#!/usr/bin/env python3
"""LuxOS - Co je noveho (files/lsl/luxos-whats-new.lsl, luxos_whats_new.lsl): novinky, ikony a okno.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_whats_new.py -v

Kazda ikona z packages/luxos-branding/files/whats-new/*.json musi existovat jako opravdu
symbolicka ikona: v Adwaite (adwaita-icon-theme, zavislost gtk3), na kterou okno saha, kdyz
motiv ikonu nema nebo ma pod symbolickym nazvem barevnou ikonu (WhiteSur: mark-location-symbolic
-> preferences-system-search.svg = plny modry ctverec), nebo ve zdrojich repozitare.
Logiku aplikace (ktere verze ukazat, jazyk, symbolicke ikony) testuje tests/lsl/luxos-whats-new-test.lsl,
okno bezi jen ve vlastnim Xvfb a v luxwm headless (lsl_app_harness).
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
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "luxos-desktop", "files", "lsl", "luxos-whats-new.lsl")
NOTES = os.path.join(ROOT, "luxos-branding", "files", "whats-new")
ADWAITA = "/usr/share/icons/Adwaita"
sys.path.insert(0, os.path.join(ROOT, "luxos-i18n", "files"))

class wn:
    """Pomucky testu dat novinek (aplikace je v LSL a testuje ji LslModel)."""
    VERSION_FILE = os.path.join(ROOT, "luxos-branding", "files", "version")

    @staticmethod
    def vkey(v):
        return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]

    @classmethod
    def current_version(cls):
        with open(cls.VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION="):
                    return line.split("=", 1)[1].strip().strip('"')
        return ""

    @staticmethod
    def symbolic_file_ok(path):
        if not path:
            return False
        real = os.path.realpath(path)
        base = os.path.basename(real)
        if base.endswith((".symbolic.png", "-symbolic.svg", "-symbolic-rtl.svg")):
            return True
        if not base.endswith(".svg") or not os.path.exists(real):
            return False
        with open(real, encoding="utf-8", errors="replace") as f:
            svg = f.read(200000)
        return "Gradient" not in svg and "<image" not in svg


def referenced_icons():
    """{nazev ikony: [soubory]} ze vsech JSON s novinkami."""
    out = {}
    for path in sorted(glob.glob(os.path.join(NOTES, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            out.setdefault(item.get("icon") or "starred-symbolic", []).append(os.path.basename(path))
    return out


def svg_index(top):
    """{nazev: [cesty]} vsech .svg pod adresarem."""
    idx = {}
    for dirpath, _dirs, files in os.walk(top):
        for name in files:
            if name.endswith(".svg"):
                idx.setdefault(name[:-4], []).append(os.path.join(dirpath, name))
    return idx


class WhatsNewIconsTest(unittest.TestCase):
    def test_every_icon_exists(self):
        icons = referenced_icons()
        self.assertTrue(icons)
        repo = svg_index(ROOT)
        adw = svg_index(ADWAITA) if os.path.isdir(ADWAITA) else None
        missing = []
        for name, files in sorted(icons.items()):
            paths = repo.get(name, []) + ((adw or {}).get(name, []))
            if adw is None and not paths:
                continue        # bez Adwaity v testovacim prostredi kontrolujeme jen symbolicke nazvy nize
            if not any(wn.symbolic_file_ok(p) for p in paths):
                missing.append(f"{name} ({', '.join(files)})")
        self.assertEqual(missing, [], "ikony v whats-new/*.json bez symbolicke SVG v Adwaite ani v repozitari")

    def test_icons_are_symbolic_names(self):
        """Dlazdice ikonu prebarvuje modre - barevne ikony aplikaci do novinek nepatri."""
        bad = [n for n in referenced_icons() if not n.endswith("-symbolic")]
        self.assertEqual(bad, [])

    def test_resolves_in_installed_themes(self):
        """Jako okno: motiv WhiteSur (luxos-themes) nebo zaloha Adwaita musi dat symbolickou ikonu."""
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK 3 neni k dispozici")
        themes = [t for t in ("WhiteSur-light", "WhiteSur-dark") if os.path.isdir(f"/usr/share/icons/{t}")]
        if not themes or not os.path.isdir(ADWAITA):
            self.skipTest("motiv WhiteSur nebo Adwaita neni nainstalovan")
        adw = Gtk.IconTheme.new()
        adw.set_custom_theme("Adwaita")
        bad = []
        for t in themes:
            theme = Gtk.IconTheme.new()
            theme.set_custom_theme(t)
            for name in referenced_icons():
                info = theme.lookup_icon(name, 24, 0)
                if info and wn.symbolic_file_ok(info.get_filename()):
                    continue
                info = adw.lookup_icon(name, 24, 0)
                if not (info and wn.symbolic_file_ok(info.get_filename())):
                    bad.append(f"{t}: {name}")
        self.assertEqual(bad, [])



LANGS = ("en", "cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv")
VERSION_FILE = os.path.join(ROOT, "luxos-branding", "files", "version")


class NotesContentTest(unittest.TestCase):
    """Obsah whats-new/*.json: od 1.0.0 vsech 13 jazyku LuxOS (starsi jen en + cs), verze = nazev souboru, novinky pro aktualni
    verzi z files/version (jinak se po aktualizaci okno Co je noveho neukaze vubec)."""

    def notes(self):
        out = {}
        for path in sorted(glob.glob(os.path.join(NOTES, "*.json"))):
            with open(path, encoding="utf-8") as f:
                out[os.path.basename(path)[:-5]] = json.load(f)
        return out

    def test_every_language_and_version(self):
        problems = []
        for stem, data in self.notes().items():
            if data.get("version") != stem:
                problems.append(f"{stem}.json: version {data.get('version')!r}")
            if not data.get("codename"):
                problems.append(f"{stem}.json: no codename")
            if not data.get("items"):
                problems.append(f"{stem}.json: no items")
            langs = LANGS if wn.vkey(stem) >= wn.vkey("1.0.0") else ("en", "cs")
            for i, item in enumerate(data.get("items", [])):
                for key in ("title", "text"):
                    value = item.get(key) or {}
                    missing = [l for l in langs if not str(value.get(l, "")).strip()]
                    if missing:
                        problems.append(f"{stem}.json item {i} {key}: missing {missing}")
        self.assertEqual(problems, [])

    def test_current_version_has_notes(self):
        wn.VERSION_FILE = VERSION_FILE
        current = wn.current_version()
        self.assertRegex(current, r"^\d+\.\d+\.\d+$")
        self.assertIn(current, self.notes(), "files/version bez whats-new/<verze>.json")
        with open(VERSION_FILE, encoding="utf-8") as f:
            codename = [l.split("=", 1)[1].strip() for l in f if l.startswith("CODENAME=")][0]
        self.assertEqual(self.notes()[current]["codename"], codename)

    def test_current_notes_skip_staging_only_apps(self):
        """Co je noveho aktualni verze jde do stabilniho kanalu: nesmi slibovat aplikace, ktere tam nejsou
        (scripts/compose-stable-repo.sh: Posta, App Studio, Icon Studio, SDK; Lux Code ve stabilni verzi)."""
        wn.VERSION_FILE = VERSION_FILE
        data = self.notes()[wn.current_version()]
        bad = []
        for i, item in enumerate(data["items"]):
            for key in ("title", "text"):
                for lang in ("en", "cs"):
                    text = item[key][lang]
                    for word in ("Mail", "Pošt", "Lux Code", "App Studio", "Icon Studio", "SDK"):
                        if word in text:
                            bad.append(f"item {i} {key} {lang}: {word}")
        self.assertEqual(bad, [])


class DockTest(unittest.TestCase):
    """Dock (Plank) pozna okno podle StartupWMClass: bez souboru .desktop ukazoval nazev programu
    "luxos-whats-new" a rozmazanou ikonu."""

    def test_desktop_file(self):
        path = os.path.join(ROOT, "luxos-desktop", "files", "applications", "luxos-whats-new.desktop")
        with open(path, encoding="utf-8") as f:
            d = f.read()
        self.assertIn("StartupWMClass=luxos-whats-new\n", d)
        self.assertIn("NoDisplay=true\n", d)
        self.assertIn("Icon=luxos-app\n", d)
        self.assertIn("Name[cs]=Co je nového\n", d)
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            self.assertIn(f"Name[{lang}]=", d)
        with open(SRC, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('glib.set_prgname("luxos-whats-new")', src)
        self.assertIn('gtk.window_set_wmclass(window, "luxos-whats-new", "luxos-whats-new")', src)
        # ui.window: ikona okna 16-256 px z motivu (window_set_icon_list), ostra v Docku a Alt+Tab
        self.assertIn('ui.window(i18n.T("What\'s New"), "luxos-app"', src)


class PlainWordsTest(unittest.TestCase):
    """Novinky od 1.0.1 bez prikazu do terminalu uprostred textu (sudo luxos-secureboot enroll,
    luxos-appearance bar-clock center) - misto nich kam kliknout, ve vsech jazycich."""

    def test_no_commands(self):
        import re
        for path in sorted(glob.glob(os.path.join(NOTES, "*.json"))):
            version = tuple(int(x) for x in os.path.basename(path)[:-5].split("."))
            if version < (1, 0, 1):
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("items", []):
                for lang, text in list(item.get("text", {}).items()) + list(item.get("title", {}).items()):
                    with self.subTest(file=os.path.basename(path), lang=lang):
                        self.assertNotRegex(text, r"\bsudo\b|\bluxos-[a-z-]+ [a-z]|\blux (system|update|install)\b")


import lsl_app_harness as h  # noqa: E402

LSL_OK = h.lslc_ok()


@unittest.skipUnless(LSL_OK, "lslc 0.11 is not installed")
class LslModel(unittest.TestCase):
    """Ktere verze ukazat po aktualizaci, chybne soubory, jazyk textu, symbolicke ikony (tests/lsl)."""

    def test_model(self):
        tmp = tempfile.mkdtemp(prefix="wnmodel-", dir=h.private_dir())
        binary = os.path.join(tmp, "t")
        r = subprocess.run([h.LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(h.LSL_DIR),
                            os.path.join(HERE, "lsl", "luxos-whats-new-test.lsl"), binary], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        # WhiteSur: apps/scalable/mark-location-symbolic.svg -> preferences-system-search.svg (barevna)
        os.symlink("preferences-system-search.svg", os.path.join(tmp, "mark-location-symbolic.svg"))
        os.symlink("view-grid.svg", os.path.join(tmp, "view-grid-symbolic.svg"))
        r = subprocess.run([binary, NOTES, tmp], capture_output=True, text=True, timeout=30)
        self.assertEqual([line for line in r.stdout.splitlines() if not line.startswith("ok ")], [], r.stderr)
        self.assertEqual(r.returncode, 0)
        self.assertGreater(len(r.stdout.splitlines()), 20)


class WindowBase(unittest.TestCase):
    backend = None

    @classmethod
    def setUpClass(cls):
        if not LSL_OK:
            raise unittest.SkipTest("lslc 0.11 is not installed")
        cls.binary = str(h.build("luxos-whats-new"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wn-", dir=h.private_dir())
        self.env = h.base_env(self.tmp)
        self.env.update(LUXOS_WHATS_NEW_DIR=NOTES, LUXOS_VERSION_FILE=VERSION_FILE)
        self.seen = os.path.join(self.tmp, "config", "luxos", "whats-new-seen")

    def run_app(self, args, script):
        app = self.backend([self.binary, *args], self.env, script, tmp=self.tmp)
        self.addCleanup(app.close)
        return app

    def labels(self, dump):
        return [line.split("\t")[1] for line in dump if line.startswith("GtkLabel\t")]


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11Window(WindowBase):
    backend = h.X11App

    def test_current_notes(self):
        current = wn.current_version()
        app = self.run_app([], ["dump", "click Continue"])
        d = app.wait_dump()
        self.assertIn(f"What's New in LuxOS {current}", self.labels(d))
        with open(os.path.join(NOTES, current + ".json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn(data["codename"], self.labels(d))
        for item in data["items"]:
            self.assertIn(item["title"]["en"], self.labels(d))
        self.assertEqual(app.wait_exit(), 0)                   # Pokracovat zavre okno
        self.assertFalse(os.path.exists(self.seen))            # rucni otevreni nic neoznaci

    def test_auto_after_update_shows_all_new(self):
        current = wn.current_version()
        notes = sorted((os.path.basename(p)[:-5] for p in glob.glob(os.path.join(NOTES, "*.json"))), key=wn.vkey)
        older = notes[notes.index(current) - 2]
        os.makedirs(os.path.dirname(self.seen))
        with open(self.seen, "w") as f:
            f.write(older + "\n")
        d = self.run_app(["--auto"], ["dump", "quit"]).wait_dump()
        newer = notes[notes.index(older) + 1:notes.index(current) + 1]
        heads = [t for t in self.labels(d) if re.fullmatch(r"LuxOS \d+\.\d+\.\d+", t)]
        self.assertEqual(heads, [f"LuxOS {v}" for v in reversed(newer)])      # nejnovejsi prvni
        with open(self.seen) as f:
            self.assertEqual(f.read().strip(), current)

    def test_auto_once(self):
        os.makedirs(os.path.dirname(self.seen))
        with open(self.seen, "w") as f:
            f.write(wn.current_version() + "\n")
        r = subprocess.run([self.binary, "--auto"], env=dict(self.env, DISPLAY=":nonexistent"), capture_output=True,
                           text=True, timeout=20)
        self.assertEqual((r.returncode, r.stderr), (0, ""))   # bez okna (a bez displeje by GTK hlasilo chybu)

    def test_mark_seen_and_no_notes(self):
        r = subprocess.run([self.binary, "--mark-seen"], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0)
        with open(self.seen) as f:
            self.assertEqual(f.read().strip(), wn.current_version())
        r = subprocess.run([self.binary], env=dict(self.env, LUXOS_WHATS_NEW_DIR=self.tmp), capture_output=True,
                           text=True, timeout=20)
        self.assertEqual(r.returncode, 1)
        self.assertIn("No release notes are available.", r.stderr)

    def test_window_fits_and_czech(self):
        self.env["LANG"] = "cs_CZ.UTF-8"
        app = self.run_app([], ["dump"])
        d = app.wait_dump()
        self.assertIn("GtkButton\tPokračovat", d)
        win = app.window("Co je nového")
        self.assertLessEqual(win["height"], 768 - 16)
        self.assertGreaterEqual(app.hints(win["id"])[1], 300)


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class WaylandWindow(WindowBase):
    backend = h.WaylandApp

    def test_wayland(self):
        app = self.run_app([], ["dump", "click Continue"])
        self.assertIn(f"What's New in LuxOS {wn.current_version()}", self.labels(app.wait_dump()))
        self.assertEqual(app.wait_exit(), 0)


if __name__ == "__main__":
    unittest.main()
