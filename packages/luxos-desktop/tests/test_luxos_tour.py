#!/usr/bin/env python3
"""LuxOS - Prohlidka: nahledy Svetly/Tmavy/Auto jdou vybrat kliknutim (files/bin/luxos-tour).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_tour.py -v

Jen prepocet souradnic kliknuti na rezim (stejna mrizka jako draw_appearance), bez okna.
Klikani ve skutecnem okne overuje GUI test pod Xvfb nize (jen s xvfb-run).
"""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "files", "bin", "luxos-tour")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


def load():
    loader = importlib.machinery.SourceFileLoader("luxos_tour", SCRIPT)
    spec = importlib.util.spec_from_loader("luxos_tour", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakeArea:
    def __init__(self, w, h):
        self.w, self.h = w, h

    def get_allocated_width(self):
        return self.w

    def get_allocated_height(self):
        return self.h


class AppearanceHit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tour = load()

    def hit(self, area, vx, vy):
        """Bod virtualni plochy 640x300 -> souradnice okna nahledu (jako on_draw)."""
        w, h = area.w, area.h
        s = min(w / self.tour.VW, h / self.tour.VH)
        return self.tour.TourWindow.appearance_hit(area, (w - self.tour.VW * s) / 2 + vx * s, vy * s)

    def test_each_preview_and_its_label(self):
        for area in (FakeArea(732, 336), FakeArea(1000, 400), FakeArea(500, 300)):
            for i, key in enumerate(("light", "dark", "auto")):
                x = 28 + i * 200
                self.assertEqual(self.hit(area, x + 92, 125), key, (area.w, key))
                self.assertEqual(self.hit(area, x + 92, 240), key, "popisek pod nahledem")

    def test_outside_previews(self):
        area = FakeArea(732, 336)
        for vx, vy in ((10, 125), (220, 125), (620, 125), (300, 20), (300, 280)):
            self.assertIsNone(self.hit(area, vx, vy), (vx, vy))
        self.assertIsNone(self.tour.TourWindow.appearance_hit(FakeArea(0, 0), 5, 5))


@unittest.skipUnless(UNDER_XVFB and shutil.which("xdotool"), "GUI only under xvfb-run (never on a real display)")
class ClickInWindow(unittest.TestCase):
    def test_click_on_dark_and_auto_previews(self):
        t = tempfile.mkdtemp(prefix="luxos-tour-")
        self.addCleanup(shutil.rmtree, t, True)
        fake = os.path.join(t, "bin")
        os.makedirs(fake)
        calls = os.path.join(t, "calls")
        with open(os.path.join(fake, "luxos-appearance"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\n' % calls)
        os.chmod(os.path.join(fake, "luxos-appearance"), 0o755)
        env = dict(os.environ, HOME=t, XDG_CONFIG_HOME=os.path.join(t, ".config"), LANG="C",
                   PATH=fake + ":" + os.environ["PATH"], GIO_USE_VFS="local", NO_AT_BRIDGE="1")
        p = subprocess.Popen(["dbus-run-session", "--", "python3", SCRIPT, "--page", "7"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: (os.killpg(p.pid, 15), p.wait(timeout=10)))
        win = ""
        for _ in range(80):
            win = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "LuxOS Tour"],
                                 capture_output=True, text=True).stdout.split()
            if win:
                break
            time.sleep(0.1)
        self.assertTrue(win, "okno Prohlidky")
        subprocess.run(["xdotool", "windowmove", "--sync", win[0], "0", "0"])
        time.sleep(0.8)

        def read():
            try:
                with open(calls) as f:
                    return f.read().split()
            except OSError:
                return []
        # nahledy v okne 780 px: Tmavy uprostred, Auto vpravo; pod nahledy prazdne misto
        for x, y in ((390, 230), (620, 230), (390, 430)):
            subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
            time.sleep(0.6)
        self.assertEqual([c for c in read() if c != "mode"], ["dark", "auto"])


if __name__ == "__main__":
    unittest.main()
