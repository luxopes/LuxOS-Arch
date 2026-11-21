#!/usr/bin/env python3
"""LuxOS - Prohlidka LuxOS (files/lsl/luxos-tour.lsl, luxos_tour_draw.lsl): nahledy Svetly/Tmavy/Auto jdou vybrat
kliknutim, strankovani, jen jedno spusteni po prvnim prihlaseni, jedna instance; v Xvfb i v luxwm headless.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=2G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_tour.py -v

luxos-appearance a spoustene aplikace jsou falesne programy (zapisuji, s cim byly spusteny).
"""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import lsl_app_harness as h

HERE = Path(__file__).resolve().parent
COMMANDS = ["luxos-appearance", "luxos-cc-toggle", "luxos-launchpad", "luxos-search", "thunar", "luxos-safe",
            "luxos-store", "luxos-terminal", "luxos-settings", "luxdrop", "luxos-printers", "luxos-shortcuts",
            "luxos-feedback"]
HIT_TEST = """load luxos_tour_draw as draw
for p in [[120.0, 125.0], [120.0, 240.0], [320.0, 125.0], [320.0, 240.0], [520.0, 125.0], [520.0, 240.0],
          [10.0, 125.0], [220.0, 125.0], [620.0, 125.0], [300.0, 20.0], [300.0, 280.0]]:
    print draw.appearance_hit(p[0], p[1]) + "|"
end
"""


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-tour")


class AppearanceHit(unittest.TestCase):
    def test_previews_and_labels(self):
        # body virtualni plochy 640x300: nahled a popisek pod nim patri rezimu, mezery a okraje nikomu
        tmp = Path(tempfile.mkdtemp(prefix="tourhit-", dir=h.private_dir()))
        (tmp / "t.lsl").write_text(HIT_TEST)
        r = subprocess.run([h.LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(h.LSL_DIR), str(tmp / "t.lsl"),
                            str(tmp / "t")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = subprocess.run([str(tmp / "t")], capture_output=True, text=True, timeout=20).stdout.split()
        self.assertEqual(out, ["light|", "light|", "dark|", "dark|", "auto|", "auto|", "|", "|", "|", "|", "|"])


class Base(unittest.TestCase):
    backend = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tour-", dir=h.private_dir()))
        self.env = h.base_env(self.tmp)
        self.env["PATH"] = str(h.fake_bin(self.tmp / "bin", COMMANDS)) + ":" + os.environ["PATH"]
        self.env["FAKE_OUT_luxos_appearance"] = "light"
        self.marker = self.tmp / "config/luxos/tour-done"

    def run_app(self, args, script):
        app = self.backend([str(h.build("luxos-tour")), *args], self.env, script, tmp=self.tmp)
        self.addCleanup(app.close)
        return app

    def calls(self):
        log = self.tmp / "fake.log"
        return log.read_text().splitlines() if log.exists() else []

    def buttons(self, dump):
        return [line.split("\t")[1] for line in dump if line.startswith(("GtkButton\t", "GtkRadioButton\t"))]


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class X11(Base):
    backend = h.X11App

    def test_pages_and_finish(self):
        app = self.run_app([], ["dump"] + ["click Continue"] * 8 + ["dump", "click Get Started"])
        first = app.wait_dump(1)
        self.assertIn("GtkLabel\tWelcome to LuxOS", first)
        self.assertIn("Skip Tour", self.buttons(first))
        self.assertNotIn("Back", self.buttons(first))
        last = app.wait_dump(2)
        self.assertIn("GtkLabel\tHelp and Shortcuts", last)
        self.assertIn("Get Started", self.buttons(last))
        self.assertNotIn("Skip Tour", self.buttons(last))
        self.assertIn("Back", self.buttons(last))
        self.assertEqual(app.wait_exit(), 0)
        self.assertTrue(self.marker.exists())

    def test_first_run_only_once(self):
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text("")
        r = subprocess.run([str(h.build("luxos-tour")), "--first-run"], env=dict(self.env, DISPLAY=":nonexistent"),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_actions_launch_apps(self):
        app = self.run_app(["--page", "4"], ["dump", "click Open Launchpad", "click Open Search", "wait 300", "quit"])
        d = app.wait_dump()
        self.assertIn("GtkLabel\tLaunchpad and Search", d)
        app.wait_exit()
        self.assertIn("luxos-launchpad", self.calls())
        self.assertIn("luxos-search", self.calls())

    def test_missing_app_has_no_button(self):
        # PATH jen s falesnymi programy a nastroji relace (skutecny system muze mit luxos-safe)
        (self.tmp / "bin/luxos-safe").unlink()
        tools = self.tmp / "tools"
        tools.mkdir()
        for name in ("dbus-run-session", "dbus-daemon", "sh"):
            (tools / name).symlink_to(subprocess.run(["sh", "-c", "command -v " + name], capture_output=True,
                                                     text=True).stdout.strip())
        self.env["PATH"] = f"{self.tmp / 'bin'}:{tools}"
        d = self.run_app(["--page", "5"], ["dump", "quit"]).wait_dump()
        self.assertIn("Open Files", self.buttons(d))
        self.assertNotIn("Open Safe", self.buttons(d))
        # bez kompozitoru (Xvfb) by prekryv nebyl pruhledny: Ukazat na obrazovce se nenabizi
        d = self.run_app(["--page", "2"], ["dump", "quit"]).wait_dump(2)
        self.assertNotIn("Show on Screen", self.buttons(d))
        self.assertIn("Open Control Center", self.buttons(d))

    def test_click_on_dark_and_auto_previews(self):
        app = self.run_app(["--page", "7"], ["dump", "wait 600000"])
        d = app.wait_dump()
        self.assertIn("Light [current]", self.buttons(d))
        win = app.window("LuxOS Tour")
        app.xdotool("windowmove", "--sync", win["id"], "0", "0")
        time.sleep(0.8)
        # nahledy v okne 780 px: Tmavy uprostred, Auto vpravo; pod nahledy prazdne misto
        for x, y in ((390, 230), (620, 230), (390, 430)):
            app.xdotool("mousemove", str(x), str(y), "click", "1")
            time.sleep(0.6)
        self.assertEqual([c for c in self.calls() if c.startswith("luxos-appearance") and c != "luxos-appearance mode"],
                         ["luxos-appearance dark", "luxos-appearance auto"])

    def test_single_instance(self):
        app = self.run_app([], ["wait 600000"])
        app.window("LuxOS Tour")
        env = dict(self.env, DISPLAY=app.display, DBUS_SESSION_BUS_ADDRESS=self.session_bus(app))
        r = subprocess.run([str(h.build("luxos-tour"))], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0)                 # druha instance jen ukaze prvni okno a skonci
        self.assertIsNone(app.proc.poll())

    def session_bus(self, app):
        pid = app.app_pid()
        for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            if item.startswith(b"DBUS_SESSION_BUS_ADDRESS="):
                return item.split(b"=", 1)[1].decode()
        self.fail("no session bus")

    def test_window_and_czech(self):
        self.env["LANG"] = "cs_CZ.UTF-8"
        app = self.run_app([], ["dump"])
        d = app.wait_dump()
        self.assertIn("Pokračovat", self.buttons(d))
        win = app.window("Prohlídka LuxOS")
        self.assertLessEqual(win["height"], 768)


@unittest.skipUnless(h.HAVE_WAYLAND, "luxwm (LUXWM_BUILD) or wl-test sysroot missing")
class Wayland(Base):
    backend = h.WaylandApp

    def test_wayland(self):
        app = self.run_app(["--page", "2"], ["dump", "click Open Control Center", "wait 300", "click Continue", "dump", "quit"])
        d = app.wait_dump(1)
        self.assertIn("GtkLabel\tThe Menu Bar", d)
        self.assertNotIn("Show on Screen", self.buttons(d))       # poloha listy se na Waylandu nezjistuje
        self.assertIn("GtkLabel\tThe Dock", app.wait_dump(2))
        app.wait_exit()
        self.assertIn("luxos-cc-toggle", self.calls())
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
