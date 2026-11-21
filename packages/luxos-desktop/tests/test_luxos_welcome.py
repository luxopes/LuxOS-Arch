#!/usr/bin/env python3
"""LuxOS - Uvitani (files/lsl/luxos-welcome.lsl) v Xvfb a v luxwm headless: tlacitka po ctyrech (okno ne pres
1260 px jako drive yad na Waylandu), Aktualizovat otevre Aktualizace softwaru (ne Terminal se sudo lux update -
audit 1.0.2), Tmavy rezim prepne vzhled a popisek, LuxAI jen bez uctu, na live ISO Nainstalovat LuxOS, po zavreni
welcome-done.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_welcome.py -v

Spoustene programy jsou falesne (zapisuji, s cim byly spusteny).
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

import lsl_app_harness as h

COMMANDS = ["luxos-appearance", "luxos-update", "luxos-terminal", "luxos-store", "luxos-tour", "luxos-shortcuts",
            "luxos-account", "luxos-install-gui"]


def shots():
    out = h.REPO / "out/welcome-test"
    out.mkdir(parents=True, exist_ok=True)
    return out


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-welcome")


class Base(unittest.TestCase):
    backend = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="welcome-", dir=h.private_dir()))
        self.env = h.base_env(self.tmp)
        self.env["PATH"] = str(h.fake_bin(self.tmp / "bin", COMMANDS)) + ":" + os.environ["PATH"]
        self.env["FAKE_OUT_luxos_appearance"] = "light"
        self.done = self.tmp / "config/luxos/welcome-done"

    def run_app(self, script):
        app = self.backend([str(h.build("luxos-welcome"))], self.env, script, tmp=self.tmp)
        self.addCleanup(app.close)
        return app

    def calls(self):
        log = self.tmp / "fake.log"
        return log.read_text().splitlines() if log.exists() else []

    def buttons(self, dump):
        # GtkGrid vraci deti od posledniho pridaneho
        return [line.split("\t")[1] for line in dump if line.startswith("GtkButton\t")][::-1]


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11(Base):
    backend = h.X11App

    def test_buttons_size_and_actions(self):
        app = self.run_app(["dump", "click Update", "click Dark Mode", "wait 300", "dump", "click Close"])
        first = app.wait_dump(1)
        self.assertEqual(self.buttons(first), ["Dark Mode", "LuxOS Store", "Update", "Sign in to LuxAI", "LuxOS Tour",
                                               "Shortcuts", "Close"])
        self.assertIn("GtkLabel\tWelcome to LuxOS", first)
        win = app.window("Welcome to LuxOS")
        self.assertLessEqual(win["width"], 820, win)
        self.assertLessEqual(win["height"], 420, win)
        self.assertIn("Light Mode", self.buttons(app.wait_dump(2)))
        app.wait_exit()
        calls = self.calls()
        self.assertIn("luxos-update", calls)
        self.assertNotIn("luxos-terminal", " ".join(calls))
        self.assertIn("luxos-appearance toggle", calls)
        self.assertTrue(self.done.exists())

    def test_live_and_signed_in(self):
        self.env["LUXOS_WELCOME_LIVE"] = "1"
        account = self.tmp / "config/luxai/account.json"
        account.parent.mkdir(parents=True)
        account.write_text('{"user": "x"}')
        app = self.run_app(["dump", "click Install LuxOS"])
        self.assertEqual(self.buttons(app.wait_dump()), ["Install LuxOS", "Dark Mode", "LuxOS Tour", "Shortcuts", "Close"])
        app.wait_exit()
        self.assertIn("luxos-install-gui", self.calls())
        self.assertTrue(self.done.exists())

    def test_czech_width(self):
        self.env["LANG"] = "cs_CZ.UTF-8"
        app = self.run_app(["dump"])
        self.assertIn("Přihlásit se k LuxAI", self.buttons(app.wait_dump()))
        win = app.window("Vítejte v LuxOS")
        app.shot(shots() / "welcome-cs-x11.png")
        self.assertLessEqual(win["width"], 900, win)


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(Base):
    backend = h.WaylandApp

    def test_wayland(self):
        self.env["LANG"] = "cs_CZ.UTF-8"
        app = self.run_app(["dump", "wait 3000", "click Prohlídka LuxOS", "click Zavřít"])
        d = app.wait_dump()
        self.assertIn("Zavřít", self.buttons(d))
        time.sleep(0.5)
        app.shot(shots() / "welcome-cs-wayland.png")
        app.wait_exit()
        self.assertIn("luxos-tour", self.calls())
        self.assertTrue(self.done.exists())


if __name__ == "__main__":
    unittest.main()
