#!/usr/bin/env python3
"""Aktualizace softwaru: radky "Historie oprav a aktualizaci" jdou rozbalit - co presne se aktualizovalo
(stara -> nova verze, nainstalovano/odebrano, nazev aplikace) a co oprava udelala. Klik na upozorneni
"LuxOS byl aktualizovan" (luxos-update --latest update) otevre okno s rozbalenym nejnovejsim zaznamem.
Regrese 1.0.3 (majitel): z radku "Aktualizovano 34 balicku · prave ted" nebylo videt CO se aktualizovalo.

    xvfb-run -a dbus-run-session -- python3 packages/luxos-care/tests/test_update_history_gui.py

Falesny koren (LUXOS_CARE_ROOT) s historii, zaznamem jadra a mistni databazi; nic se nespousti.
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
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
ROOT = tempfile.mkdtemp(prefix="luxos-update-history-")
BIN = os.path.join(ROOT, "fake-bin")
os.environ["LUXOS_CARE_ROOT"] = ROOT
os.environ["LC_ALL"] = "C"                                 # anglicke texty
os.environ["GIO_USE_VFS"] = "local"                        # zadny gvfs (nesahat do skutecneho /run/user)
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")
# moduly z repozitare (ne nainstalovane v /usr/lib/luxos/python)
sys.path.insert(0, FILES)
sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
import luxos_i18n  # noqa: E402,F401
import luxos_care  # noqa: E402,F401
import luxos_protect  # noqa: E402,F401

NOW = int(time.time())
OLD = NOW - 2 * 86400


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))


def w(path, text):
    p = ROOT + path
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def setup_root():
    many = [{"name": f"lib{i:02d}", "action": "upgraded", "old": "1.0-1", "new": "1.1-1"} for i in range(20)]
    newest = many + [
        {"name": "firefox", "action": "upgraded", "old": "149.0-1", "new": "150.0-1"},
        {"name": "libnew", "action": "installed", "old": "", "new": "0.4-1"},
        {"name": "oldlib", "action": "removed", "old": "2.1-3", "new": ""},
        {"name": "luxos-branding", "action": "upgraded", "old": "1.1.0-31", "new": "1.1.0-32"},
    ]
    hist = [
        # starsi aktualizace bez seznamu verzi (pred LuxOS 1.0.3) - dohleda se v lux.log
        {"time": OLD, "kind": "update", "ok": True, "count": 2, "packages": ["htop", "nano"]},
        # jeste starsi bez nazvu i bez zaznamu
        {"time": OLD - 86400 * 30, "kind": "update", "ok": True, "count": 34},
        {"time": NOW - 3600, "kind": "repair", "problem": "pkg_broken", "title": "Package %s is damaged",
         "args": ["gtk3"], "action": "reinstall_package", "target": "gtk3", "source": "rule", "ok": True,
         "output": "reinstalling gtk3...", "changes": [{"name": "gtk3", "action": "reinstalled",
                                                         "old": "3.24.50-1", "new": "3.24.50-1"}]},
        {"time": NOW - 60, "kind": "update", "ok": True, "count": len(newest), "packages": [c["name"] for c in newest],
         "kernel": False, "changes": newest},
        {"time": NOW - 30, "kind": "mode", "mode": "carefree"},          # novejsi, ale ne aktualizace
    ]
    hist.sort(key=lambda h: h["time"])
    w("/var/lib/luxos-care/history.jsonl", "".join(json.dumps(h) + "\n" for h in hist))
    w("/var/lib/luxos-care/state.json", json.dumps({"last_update": NOW - 60}))
    w("/var/log/lux.log",
      f"[{stamp(OLD - 120)}] [ALPM] transaction started\n"
      f"[{stamp(OLD - 100)}] [ALPM] upgraded htop (3.3-1 -> 3.4-1)\n"
      f"[{stamp(OLD - 90)}] [ALPM] upgraded nano (8.6-1 -> 8.7-1)\n"
      f"[{stamp(OLD - 90)}] [ALPM] upgraded zsh (5.9-5 -> 5.9-6)\n"
      f"[{stamp(OLD - 80)}] [ALPM] transaction completed\n")
    w("/var/lib/lux/local/firefox-150.0-1/files", "%FILES%\nusr/share/applications/firefox.desktop\n")
    w("/usr/share/applications/firefox.desktop",
      "[Desktop Entry]\nType=Application\nName=Firefox Web Browser\nExec=firefox\n")
    w("/fake-bin/luxos-whats-new", '#!/bin/sh\necho "whats-new $*" >>"%s/whats-new.log"\n' % ROOT)
    os.chmod(BIN + "/luxos-whats-new", 0o755)


def load_app():
    loader = importlib.machinery.SourceFileLoader("luxos_update_app", os.path.join(FILES, "luxos-update"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    setup_root()
    upd = load_app()
    from gi.repository import GLib, Gtk  # noqa: E402


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        kids = []
        widget.forall(lambda c, _d: kids.append(c), None)
        for c in kids:
            yield from walk(c)


def texts(widget):
    out = []
    for c in walk(widget):
        if isinstance(c, Gtk.Label) and c.get_text():
            out.append(c.get_text())
    return out


@unittest.skipUnless(HAVE_DISPLAY, "needs a virtual display (xvfb-run)")
class HistoryRows(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ROOT, ignore_errors=True)

    def make(self, latest=""):
        app = upd.App(latest=latest)
        app.win.disconnect_by_func(Gtk.main_quit)
        self.addCleanup(app.win.destroy)
        pump(0.5)
        return app

    def expanders(self, app):
        """[(titulek radku, expander)] v poradi od nejnovejsiho."""
        out = []
        for c in walk(app.history_group):
            if isinstance(c, Gtk.Expander):
                out.append((texts(c.get_label_widget())[0], c))
        return out

    def test_rows_expand_and_list_packages(self):
        app = self.make()
        rows = self.expanders(app)
        self.assertEqual([t for t, _e in rows],
                         ["Updated 24 packages", "Reinstalled a package (gtk3)", "Updated 2 packages",
                          "Updated 34 packages"])
        self.assertFalse(any(e.get_expanded() for _t, e in rows))           # bez --latest nic rozbalene
        self.assertNotIn("Mode changed to Carefree", [t for t, _e in rows])  # rezim se nerozbaluje
        newest = rows[0][1]
        self.assertIsNone(newest.get_child())                               # podrobnosti az po kliknuti
        newest.set_expanded(True)
        pump()
        got = texts(newest.get_child())
        self.assertIn("Firefox Web Browser", got)                           # nazev aplikace z .desktop
        self.assertIn("firefox · 149.0-1 → 150.0-1", got)
        self.assertIn("Installed 0.4-1", got)
        self.assertIn("Removed 2.1-3", got)
        self.assertIn("1.1.0-31 → 1.1.0-32", got)
        names = [t for t in got if t.startswith("lib") or t in ("Firefox Web Browser", "luxos-branding", "oldlib")]
        self.assertEqual(names, sorted(names, key=str.lower))               # serazene
        # dlouhy seznam se posouva a nenatahne okno
        sws = [c for c in walk(newest.get_child()) if isinstance(c, Gtk.ScrolledWindow)]
        self.assertEqual(len(sws), 1)
        self.assertLessEqual(sws[0].get_allocated_height(), 260)
        # luxos-branding se zmenil -> Poznamky k vydani (Co je noveho)
        btn = [c for c in walk(newest.get_child()) if isinstance(c, Gtk.Button)
               and c.get_label() == "LuxOS release notes"]
        self.assertEqual(len(btn), 1)
        btn[0].clicked()
        for _i in range(50):
            if os.path.exists(ROOT + "/whats-new.log"):
                break
            time.sleep(0.05)
        with open(ROOT + "/whats-new.log") as f:
            self.assertEqual(f.read().strip(), "whats-new")
        # obnoveni okna (zmena stavu) rozbaleni zachova
        app.refresh()
        pump()
        self.assertTrue(self.expanders(app)[0][1].get_expanded())
        # sbaleni a znovu rozbaleni
        self.expanders(app)[0][1].set_expanded(False)
        app.refresh()
        pump()
        self.assertFalse(self.expanders(app)[0][1].get_expanded())

    def test_older_entries(self):
        app = self.make()
        rows = dict(self.expanders(app))
        old = rows["Updated 2 packages"]
        old.set_expanded(True)
        pump()
        got = texts(old.get_child())
        self.assertIn("htop", got)
        self.assertIn("3.3-1 → 3.4-1", got)                                 # verze dohledane v lux.log
        self.assertIn("8.6-1 → 8.7-1", got)
        self.assertNotIn("zsh", got)                                        # jen balicky teto aktualizace
        self.assertNotIn("LuxOS release notes", got)
        none = rows["Updated 34 packages"]
        none.set_expanded(True)
        pump()
        self.assertEqual(texts(none.get_child()), ["Details aren't available for this older update."])

    def test_repair_details(self):
        app = self.make()
        rep = dict(self.expanders(app))["Reinstalled a package (gtk3)"]
        rep.set_expanded(True)
        pump()
        got = texts(rep.get_child())
        self.assertIn("Problem: Package gtk3 is damaged", got)
        self.assertIn("What LuxOS did: Reinstalled a package (gtk3)", got)
        self.assertIn("reinstalling gtk3...", got)
        self.assertIn("Reinstalled 3.24.50-1", got)
        self.assertNotIn("The repair did not help", got)

    def test_latest_update_opens_expanded(self):
        app = self.make(latest="update")
        rows = self.expanders(app)
        self.assertEqual([e.get_expanded() for _t, e in rows], [True, False, False, False])
        self.assertIn("firefox · 149.0-1 → 150.0-1", texts(rows[0][1].get_child()))
        pump(0.6)
        self.assertGreater(app.scroll.get_vadjustment().get_value(), 0)     # okno posunute k zaznamu

    def test_latest_repair_opens_repair(self):
        app = self.make(latest="repair")
        rows = dict(self.expanders(app))
        self.assertTrue(rows["Reinstalled a package (gtk3)"].get_expanded())
        self.assertFalse(rows["Updated 24 packages"].get_expanded())

    def test_command_line(self):
        """luxos-hub spousti "luxos-update --latest update"; jine argumenty okno jen otevrou."""
        seen = []
        with mock.patch.object(upd, "App", lambda latest="": seen.append(latest)), \
                mock.patch.object(upd.Gtk, "main", lambda: None):
            for argv in (["luxos-update", "--latest", "update"], ["luxos-update"], ["luxos-update", "--latest"]):
                with mock.patch.object(sys, "argv", argv):
                    upd.main()
        self.assertEqual(seen, ["update", "", ""])


if __name__ == "__main__":
    unittest.main()
