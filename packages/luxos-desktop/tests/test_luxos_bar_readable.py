#!/usr/bin/env python3
"""LuxOS - lista nad tapetou: ton jen tolik, aby byl text citelny (readable_alpha v files/src/luxos-bar.c).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_readable.py -v

Prelozi maly program, ktery vlozi zdroj pluginu a zavola readable_alpha na jednobarevny vyrez.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "files", "src", "luxos-bar.c"))
PKGS = ("libxfce4panel-2.0", "libwnck-3.0", "libxfconf-0", "gtk+-3.0")

MAIN = r'''
#include "%s"
int main (int argc, char **argv) {
    /* argv: r g b (0-255) tint_r tint_g tint_b tint_alpha */
    GdkPixbuf *pb = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, 64, 8);
    gdk_pixbuf_fill (pb, ((guint32) atoi (argv[1]) << 24) | ((guint32) atoi (argv[2]) << 16)
                         | ((guint32) atoi (argv[3]) << 8) | 0xff);
    if (argc > 8) /* svetly pruh pres 20 %% sirky (napr. mrak na jinak tmave tapete) */
        for (int y = 0; y < 8; y++)
            for (int x = 0; x < 13; x++)
                memset (gdk_pixbuf_get_pixels (pb) + y * gdk_pixbuf_get_rowstride (pb) + x * 3, 250, 3);
    GdkRGBA t = { atof (argv[4]), atof (argv[5]), atof (argv[6]), atof (argv[7]) };
    printf ("%%.4f\n", readable_alpha (pb, &t));
    return 0;
}
'''


def have():
    return shutil.which("gcc") and shutil.which("pkg-config") and \
        subprocess.run(["pkg-config", "--exists", *PKGS]).returncode == 0


@unittest.skipUnless(have(), "needs gcc and xfce4-panel/wnck/xfconf headers")
class ReadableAlpha(unittest.TestCase):
    DARK = (0.09, 0.09, 0.12)   # ton pod bilym textem
    LIGHT = (0.96, 0.96, 0.97)  # ton pod tmavym textem

    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-bar-readable-")
        c = os.path.join(cls.t, "main.c")
        with open(c, "w") as f:
            f.write(MAIN % SRC)
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", *PKGS], capture_output=True, text=True,
                               check=True).stdout.split()
        cls.bin = os.path.join(cls.t, "readable")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-Wno-unused-function", "-o", cls.bin, c, *flags,
                        "-lm"], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def alpha(self, rgb, tint, a, cloud=False):
        args = [self.bin, *map(str, rgb), *map(str, tint), str(a)] + (["cloud"] if cloud else [])
        return float(subprocess.run(args, capture_output=True, text=True, check=True).stdout)

    @staticmethod
    def lum(rgb, tint, a):
        y = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
        t = 0.2126 * tint[0] + 0.7152 * tint[1] + 0.0722 * tint[2]
        return y * (1 - a) + t * a

    def test_dark_wallpaper_stays_clean(self):
        self.assertEqual(self.alpha((30, 40, 70), self.DARK, 0), 0)
        self.assertEqual(self.alpha((120, 110, 100), self.DARK, 0), 0)

    def test_light_wallpaper_darkened_just_enough(self):
        for rgb in ((240, 230, 200), (255, 255, 255), (200, 220, 160)):
            a = self.alpha(rgb, self.DARK, 0)
            self.assertGreater(a, 0.1, rgb)
            self.assertLess(a, 0.8, rgb)
            self.assertAlmostEqual(self.lum(rgb, self.DARK, a), 0.58, delta=0.02, msg=rgb)

    def test_configured_tint_is_minimum(self):
        self.assertEqual(self.alpha((30, 40, 70), self.DARK, 0.28), 0.28)
        self.assertEqual(self.alpha((255, 255, 255), self.DARK, 0.95), 0.95)

    def test_bright_spots_decide_not_average(self):
        """Svetly mrak pres petinu listy na tmave tapete: text nad nim musi byt citelny."""
        self.assertGreater(self.alpha((20, 20, 30), self.DARK, 0, cloud=True), 0.3)

    def test_dark_text_on_dark_wallpaper_gets_light_tint(self):
        a = self.alpha((20, 20, 30), self.LIGHT, 0)
        self.assertGreater(a, 0.5)
        self.assertAlmostEqual(self.lum((20, 20, 30), self.LIGHT, a), 0.62, delta=0.02)
        self.assertEqual(self.alpha((240, 240, 240), self.LIGHT, 0), 0)


if __name__ == "__main__":
    unittest.main()
