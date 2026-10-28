#!/usr/bin/env python3
"""LuxOS - setric obrazovky: styl "desktop" (tapeta plochy s hodinami, vychozi zamykaci obrazovka).

    env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_screensaver.py -v

xfconf-query je falesny program v PATH; vykresleni se overuje do obrazku v pameti (cairo),
okno jen pod xvfb-run (nikdy na skutecne obrazovce).
"""
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
SAVER = os.path.join(FILES, "screensaver", "luxos-screensaver")
WALLS = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-branding", "files", "wallpapers"))

ss = SourceFileLoader("luxos_screensaver", SAVER).load_module()
import cairo  # noqa: E402


class DesktopWallpaper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-saver-")
        self.fake = os.path.join(self.tmp, "fake")
        os.makedirs(self.fake)
        self.listing = os.path.join(self.tmp, "desktop")
        with open(os.path.join(self.fake, "xfconf-query"), "w") as f:
            f.write('#!/bin/sh\n[ "$*" = "-c xfce4-desktop -l -v" ] && cat "$FAKE_DESKTOP" 2>/dev/null\nexit 0\n')
        os.chmod(os.path.join(self.fake, "xfconf-query"), 0o755)
        self.saved = {k: os.environ.get(k) for k in ("PATH", "FAKE_DESKTOP", "XDG_CONFIG_HOME")}
        os.environ.update({"PATH": self.fake + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
                           "FAKE_DESKTOP": self.listing, "XDG_CONFIG_HOME": os.path.join(self.tmp, "cfg")})
        self.light = os.path.join(WALLS, "luxos-flow-light.jpg")
        self.dark = os.path.join(WALLS, "luxos-flow-dark.jpg")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def props(self, d):
        with open(self.listing, "w") as f:
            for k, v in d.items():
                f.write(f"/backdrop/screen0/{k}/last-image     {v}\n/backdrop/screen0/{k}/image-style    5\n")

    def test_monitor_workspace0(self):
        self.props({"monitorHDMI-1/workspace0": self.dark, "monitoreDP-1/workspace0": self.light,
                    "monitoreDP-1/workspace1": self.dark})
        self.assertEqual(ss.desktop_wallpaper("eDP-1"), self.light)
        self.assertEqual(ss.desktop_wallpaper("HDMI-1"), self.dark)

    def test_unknown_monitor_uses_another(self):
        self.props({"monitoreDP-1/workspace0": self.light})
        self.assertEqual(ss.desktop_wallpaper("DP-3"), self.light)
        self.assertEqual(ss.desktop_wallpaper(None), self.light)

    def test_missing_file_and_mode_fallback(self):
        self.props({"monitoreDP-1/workspace0": "/nonexistent/x.jpg"})
        self.assertEqual(ss.desktop_wallpaper("eDP-1"), "/usr/share/backgrounds/luxos/luxos-light.jpg")
        os.makedirs(os.path.join(self.tmp, "cfg", "luxos"))
        with open(os.path.join(self.tmp, "cfg", "luxos", "appearance"), "w") as f:
            f.write("dark\n")
        self.assertEqual(ss.desktop_wallpaper("eDP-1"), "/usr/share/backgrounds/luxos/luxos-dark.jpg")

    def test_draw_shows_desktop_wallpaper_still(self):
        # styl desktop: stejna tapeta, nemeni se v case (zadne prolinani ani pohyb)
        self.props({"monitoreDP-1/workspace0": self.light})
        saver = ss.Saver("desktop", "eDP-1")
        self.assertEqual(saver.slides, [self.light])

        def frame():
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 320, 200)
            saver.draw(cairo.Context(surf), 320, 200)
            surf.flush()
            return bytes(surf.get_data())
        a = frame()
        saver.start -= ss.SLIDE + 5          # "o slide pozdeji" (ve stylu wallpapers uz jina tapeta)
        b = frame()
        diff = sum(1 for i in range(0, len(a), 4) if a[i:i + 3] != b[i:i + 3])
        self.assertLess(diff, len(a) // 4 // 10)   # zmeni se nejvys hodiny
        # svetla tapeta (po ztmaveni pro hodiny) je jasnejsi nez tmava LuxOS
        mean = sum(a[i + 1] for i in range(0, len(a), 4 * 7)) / (len(a) / (4 * 7))
        self.assertGreater(mean, 100)
        self.assertEqual(ss.fps(saver), 1)
        self.assertEqual(ss.fps(ss.Saver("wallpapers")), ss.FPS)

    def test_unknown_style_is_desktop(self):
        self.props({})
        self.assertEqual(ss.Saver("nonsense").style, "desktop")


class Analog(unittest.TestCase):
    """Styl "analog": tapety LuxOS s prolinanim a rucickove hodiny; mimo prolinani jen ctverec s hodinami."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-saver-analog-")
        self.saved = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp
        walls = sorted(os.path.join(WALLS, f) for f in os.listdir(WALLS) if f.endswith(".jpg"))[:3]
        self.saver = ss.Saver("analog")
        self.saver.analog.slides = walls
        self.saver.analog.offset = 0

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.saved

    def frame(self, w=320, h=200, clip=None):
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        cr = cairo.Context(surf)
        if clip:
            cr.rectangle(*clip)
            cr.clip()
        self.saver.draw(cr, w, h)
        surf.flush()
        return bytes(surf.get_data())

    def test_wallpapers_without_duplicate_symlinks(self):
        self.assertTrue(all(not os.path.islink(w) for w in ss.WALLS))
        self.assertEqual(len(ss.WALLS), len({os.path.realpath(w) for w in ss.WALLS}))
        self.assertIn("analog", ss.STYLES)
        self.assertEqual(ss.fps(self.saver), ss.ANALOG_FPS)
        self.assertLessEqual(ss.ANALOG_FPS, 30)

    def test_only_clock_redrawn_between_fades(self):
        clock = self.saver.analog
        self.assertIsNone(self.saver.dirty(320, 200))          # prvni snimek cely
        self.frame()
        box = self.saver.dirty(320, 200)
        self.assertIsNotNone(box)
        x, y, bw, bh = box
        cx, cy, r = clock.geometry(320, 200)
        self.assertTrue(x <= cx - r and y <= cy - r and x + bw >= cx + r and y + bh >= cy + r, box)
        self.assertLess(bw * bh, 320 * 200 / 2)
        # prolinani: cela obrazovka
        self.saver.start -= ss.ANALOG_SLIDE - ss.ANALOG_FADE / 2
        self.assertIsNone(self.saver.dirty(320, 200))

    def test_hands_move_and_light_dark(self):
        clock = self.saver.analog

        def hands(dark, now):
            clock.dark = dark
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
            clock.draw_hands(cairo.Context(surf), 200, 200, now)
            surf.flush()
            return bytes(surf.get_data())
        t = 1_800_000_000.0
        self.assertNotEqual(hands(False, t), hands(False, t + 1.0))      # vterinova rucicka
        self.assertNotEqual(hands(False, t), hands(False, t + 0.25))     # plynule, ne skokem po vterinach
        self.assertNotEqual(hands(False, t), hands(True, t))             # svetle / tmave rucicky
        clock.dark = True
        dark_face = clock.colors()["face"]
        clock.dark = False
        self.assertNotEqual(dark_face, clock.colors()["face"])

    def test_draw_full_screen_image(self):
        a = self.frame()
        mean = sum(a[i + 1] for i in range(0, len(a), 4 * 11)) / (len(a) / (4 * 11))
        self.assertGreater(mean, 20)            # tapeta, ne cerna


class Defaults(unittest.TestCase):
    def test_default_theme_is_desktop_wallpaper(self):
        tree = ET.parse(os.path.join(FILES, "xdg", "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-screensaver.xml"))
        values = [v.get("value") for v in tree.iter("value")]
        self.assertEqual(values, ["screensavers-luxos-wallpaper"])
        with open(os.path.join(FILES, "screensaver", "luxos-wallpaper.desktop")) as f:
            self.assertIn("Exec=/usr/lib/xfce4-screensaver/luxos --style desktop\n", f.read())
        with open(os.path.join(FILES, "bin", "luxos-lock-settings")) as f:
            src = f.read()
        self.assertIn('("screensavers-luxos-wallpaper", "desktop", "Desktop wallpaper and clock")', src)
        # kazdy styl z nastaveni existuje v setrici a ma .desktop soubor
        for theme, style in re.findall(r'\("(screensavers-[a-z-]+)", "([a-z]+)"', src):
            self.assertIn(style, ss.STYLES)
            name = theme[len("screensavers-"):] + ".desktop"
            with open(os.path.join(FILES, "screensaver", name)) as f:
                self.assertIn(f"--style {style}\n", f.read())


if __name__ == "__main__":
    unittest.main()
