"""Okna GTK 3 v luxwm: s headerbarem (CSD) dostanou od kompozitoru stin kolem geometrie okna a zaoblene dolni
rohy, bez headerbaru (jako Thunar) si pres org_kde_kwin_server_decoration reknou o zahlavi LuxOS.

  packages/luxwm/tests/build-host.sh
  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    systemd-run --user --scope -p TasksMax=300 -- timeout 900 python3 -m unittest -v packages/luxwm/tests/test_luxwm_csd.py
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_luxwm import BUILD, Session, wlt  # noqa: E402

CLIENT = os.path.join(os.path.dirname(__file__), "clients", "gtk-window.py")
GREEN = (0x20, 0xa0, 0x40)


def have_gtk():
    return subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Gtk', '3.0')"],
                          capture_output=True).returncode == 0


def dark(p):
    return sum(p)


@unittest.skipUnless(os.path.exists(os.path.join(BUILD, "luxwm")) and have_gtk(), "build first, python3-gobject")
class CsdWindows(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.env = {}
        for line in wlt("env", self.s.dir).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.terminate()
            p.wait(5)
        self.s.stop()

    def window(self, kind, title, size="400x300"):
        p = subprocess.Popen([sys.executable, "-u", CLIENT, kind, "--title", title, "--size", size], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), "mapped")
        time.sleep(0.8)
        return self.s.state()["views"][title]

    def test_headerbar_window_gets_shadow_and_rounded_corners(self):
        v = self.window("--headerbar", "Header")
        self.assertEqual(v["top"], 0, "headerbar: zahlavi kresli klient")
        # geometrie bez okraju pro stin klienta: obsah 400x300 + headerbar
        self.assertEqual(v["w"], 400)
        self.assertGreater(v["h"], 300)
        x, y, w, h = v["x"], v["y"], v["w"], v["h"]
        bg = self.s.pixel(20, 780)
        # uvnitr okna barva klienta
        self.assertEqual(self.s.pixel(x + w // 2, y + h // 2), GREEN)
        # pod oknem a vedle nej stin kompozitoru (klient svuj stin nema)
        below = self.s.pixel(x + w // 2, y + h + 4)
        side = self.s.pixel(x - 3, y + h // 2)
        print(f"\n  pozadi {bg}, pod oknem {below}, vlevo {side}")
        self.assertLess(dark(below), dark(bg) - 6, "stin pod oknem")
        self.assertLess(dark(side), dark(bg), "stin vedle okna")
        # daleko od okna stin neni
        self.assertEqual(self.s.pixel(x + w // 2, y + h + 80), bg)
        # dolni roh zaobleny: krajni pixel uz neni barva okna, kousek dovnitr ano
        self.assertNotEqual(self.s.pixel(x, y + h - 1), GREEN)
        self.assertEqual(self.s.pixel(x + 20, y + h - 20), GREEN)

    def test_plain_window_gets_server_side_title_bar(self):
        v = self.window("--plain", "Plain")
        # cizi aplikace: nizke zahlavi (TITLEBAR height_compact)
        self.assertEqual(v["top"], 30, "okno bez headerbaru chce zahlavi LuxOS (org_kde_kwin_server_decoration)")
        # zahlavi nad obsahem: semafor vlevo nahore (cervena)
        r, g, b = self.s.pixel(v["x"] + 18, v["y"] - 16)
        self.assertGreater(r, 180)
        self.assertLess(g, 140)

    def test_shadow_follows_focus_and_maximize(self):
        a = self.window("--headerbar", "A", "300x200")
        b = self.window("--headerbar", "B", "300x200")
        bg = self.s.pixel(20, 780)
        # neaktivni okno ma slabsi stin nez aktivni
        def shade(v):
            return dark(bg) - dark(self.s.pixel(v["x"] + v["w"] // 2, v["y"] + v["h"] + 4))
        st = self.s.state()["views"]
        active, inactive = shade(st["B"]), shade(st["A"])
        print(f"\n  stin aktivni {active}, neaktivni {inactive}")
        self.assertGreater(active, inactive)
        # maximalizovane okno bez stinu a s ostrymi rohy
        self.s.input("keydown super", "key Up", "keyup super", wait=0.8)
        v = self.s.state()["views"]["B"]
        self.assertEqual(v["maximized"], 1)
        self.assertEqual(self.s.pixel(v["x"], v["y"] + v["h"] - 1), GREEN, "maximalizovane: ostry roh")


if __name__ == "__main__":
    unittest.main()
