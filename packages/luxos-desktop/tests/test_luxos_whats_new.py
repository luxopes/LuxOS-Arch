#!/usr/bin/env python3
"""LuxOS - testy ikon v okne Co je noveho (luxos-whats-new).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_whats_new.py -v

Kazda ikona z packages/luxos-branding/files/whats-new/*.json musi existovat jako opravdu
symbolicka ikona: v Adwaite (adwaita-icon-theme, zavislost gtk3), na kterou okno saha, kdyz
motiv ikonu nema nebo ma pod symbolickym nazvem barevnou ikonu (WhiteSur: mark-location-symbolic
-> preferences-system-search.svg = plny modry ctverec), nebo ve zdrojich repozitare.
Nic se nekresli, okno se neotevira.
"""
import glob
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BIN = os.path.join(ROOT, "luxos-desktop", "files", "bin", "luxos-whats-new")
NOTES = os.path.join(ROOT, "luxos-branding", "files", "whats-new")
ADWAITA = "/usr/share/icons/Adwaita"
sys.path.insert(0, os.path.join(ROOT, "luxos-i18n", "files"))

loader = importlib.machinery.SourceFileLoader("luxos_whats_new", BIN)
spec = importlib.util.spec_from_loader("luxos_whats_new", loader)
wn = importlib.util.module_from_spec(spec)
loader.exec_module(wn)


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


class SymbolicFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_real_symbolic(self):
        self.assertTrue(wn.symbolic_file_ok(self.write("a-symbolic.svg", '<svg><path fill="#363636"/></svg>')))

    def test_symlink_to_colour_app_icon_rejected(self):
        """WhiteSur: apps/scalable/mark-location-symbolic.svg -> preferences-system-search.svg."""
        colour = self.write("preferences-system-search.svg",
                            '<svg><defs><linearGradient id="g"><stop stop-color="#0e71de"/></linearGradient>'
                            '</defs><rect fill="url(#g)"/></svg>')
        link = os.path.join(self.d, "mark-location-symbolic.svg")
        os.symlink(os.path.basename(colour), link)
        self.assertFalse(wn.symbolic_file_ok(link))

    def test_symlink_to_monochrome_ok(self):
        mono = self.write("view-grid.svg", '<svg><path class="ColorScheme-Text" fill="currentColor"/></svg>')
        link = os.path.join(self.d, "view-grid-symbolic.svg")
        os.symlink(os.path.basename(mono), link)
        self.assertTrue(wn.symbolic_file_ok(link))

    def test_missing(self):
        self.assertFalse(wn.symbolic_file_ok(None))
        self.assertFalse(wn.symbolic_file_ok(os.path.join(self.d, "nope-symbolic.png")))


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

    def test_shown_once_after_update(self):
        """Po aktualizaci 1.0.0 -> 1.0.1 se ukaze jen 1.0.1; po zobrazeni (mark_seen) uz nic."""
        wn.NOTES_DIR = NOTES
        notes = wn.load_notes()
        self.assertEqual(wn.pending(notes, "1.0.0", "1.0.1"), ["1.0.1"])
        self.assertEqual(wn.pending(notes, "0.9.12", "1.0.1"), ["1.0.1", "1.0.0"])
        self.assertEqual(wn.pending(notes, "1.0.1", "1.0.1"), [])
        # verze 1.0.10 > 1.0.9 (ne retezcove razeni)
        self.assertGreater(wn.vkey("1.0.10"), wn.vkey("1.0.9"))


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
        with open(BIN, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('GLib.set_prgname("luxos-whats-new")', src)
        self.assertIn('set_window_icons(win, "luxos-app")', src)

    def test_window_icon_sizes(self):
        sys.path.insert(0, os.path.join(ROOT, "luxos-desktop", "files", "python"))
        import luxos_wm_icon
        sizes = (16, 24, 32, 48, 64, 128, 256)
        self.assertEqual(luxos_wm_icon.WINDOW_SIZES, sizes)
        try:
            pbs = luxos_wm_icon.window_pixbufs("luxos-app")
        except Exception as e:  # bez Gtk/obrazovky v sestavovacim prostredi
            self.skipTest(str(e))
        if not pbs:
            self.skipTest("luxos-app icon not installed")
        self.assertEqual([p.get_width() for p in pbs], list(sizes))
        argb = luxos_wm_icon._argb(pbs[0])
        self.assertEqual(argb[:2], [16, 16])
        self.assertEqual(len(argb), 2 + 16 * 16)


if __name__ == "__main__":
    unittest.main()
