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


if __name__ == "__main__":
    unittest.main()
