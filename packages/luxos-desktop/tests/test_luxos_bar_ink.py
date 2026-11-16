#!/usr/bin/env python3
"""LuxOS - bile pismo listy na svetle tapete prepne na tmave (white_contrast, want_dark_ink v files/src/luxos-bar.c).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_ink.py -v

Prelozi maly program, ktery vlozi zdroj pluginu, vyrizne pruh 1920x28 nahore z tapety (jako lista
na monitoru 1920x1080, styl "vyplnit") nebo pouzije jednobarevny pruh a vypise kontrast bileho
pisma pod kourovym tonem listy a rozhodnuti s hysterezi.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "files", "src", "luxos-bar.c"))
PKGS = ("libxfce4panel-2.0", "libwnck-3.0", "libxfconf-0", "gtk+-3.0")
WALLS = "/usr/share/backgrounds/luxos"

MAIN = r'''
#include "%s"
int main (int argc, char **argv) {
    /* argv: zdroj (soubor nebo #rrggbb) alfa_tonu */
    GdkPixbuf *strip;
    if (argv[1][0] == '#') {
        strip = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, 1920, 28);
        gdk_pixbuf_fill (strip, ((guint32) strtoul (argv[1] + 1, NULL, 16) << 8) | 0xff);
    } else {
        GdkPixbuf *src = gdk_pixbuf_new_from_file (argv[1], NULL);
        if (!src)
            return 1;
        gdouble s = MAX (1920.0 / gdk_pixbuf_get_width (src), 1080.0 / gdk_pixbuf_get_height (src));
        gdouble ox = (1920 - gdk_pixbuf_get_width (src) * s) / 2, oy = (1080 - gdk_pixbuf_get_height (src) * s) / 2;
        strip = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, 1920, 28);
        gdk_pixbuf_scale (src, strip, 0, 0, 1920, 28, ox, oy, s, s, GDK_INTERP_BILINEAR);
        g_object_unref (src);
    }
    GdkRGBA smoke = { 0.09, 0.09, 0.12, atof (argv[2]) };
    gdouble c = white_contrast (strip, &smoke);
    printf ("%%.3f %%d %%d\n", c, want_dark_ink (c, FALSE), want_dark_ink (c, TRUE));
    return 0;
}
'''


def have():
    return shutil.which("gcc") and shutil.which("pkg-config") and \
        subprocess.run(["pkg-config", "--exists", *PKGS]).returncode == 0


@unittest.skipUnless(have(), "needs gcc and xfce4-panel/wnck/xfconf headers")
class BarInk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-bar-ink-")
        c = os.path.join(cls.t, "main.c")
        with open(c, "w") as f:
            f.write(MAIN % SRC)
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", *PKGS], capture_output=True, text=True,
                               check=True).stdout.split()
        cls.bin = os.path.join(cls.t, "ink")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-Wno-unused-function", "-o", cls.bin, c, *flags,
                        "-lm"], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def ink(self, src, alpha=0.0):
        out = subprocess.run([self.bin, src, str(alpha)], capture_output=True, text=True, check=True).stdout.split()
        return float(out[0]), out[1] == "1", out[2] == "1"

    def test_wcag_contrast_of_solid_colors(self):
        self.assertAlmostEqual(self.ink("#ffffff")[0], 1.0, places=2)
        self.assertAlmostEqual(self.ink("#000000")[0], 21.0, places=1)
        # #777777: L = 0.184 -> 4.48 : 1 (znama hodnota WCAG)
        self.assertAlmostEqual(self.ink("#777777")[0], 4.48, delta=0.02)

    def test_white_and_beige_switch_to_dark_text(self):
        for col in ("#ffffff", "#f3ecdc", "#f5f5dc", "#e8e8e8"):
            c, from_white, from_dark = self.ink(col)
            self.assertTrue(from_white, (col, c))
            self.assertTrue(from_dark, (col, c))

    def test_dark_wallpaper_keeps_white_text(self):
        for col in ("#101010", "#203050", "#6a4c93", "#808080"):
            c, from_white, from_dark = self.ink(col)
            self.assertFalse(from_white, (col, c))
            self.assertFalse(from_dark, (col, c))

    def test_hysteresis(self):
        """Mezi prahy zustava dosavadni pismo - tapeta na hranici lista nerozblika."""
        c, from_white, from_dark = self.ink("#b4b4b4")
        self.assertTrue(2.0 <= c < 2.3, c)
        self.assertFalse(from_white)
        self.assertTrue(from_dark)

    def test_smoke_tint_counts(self):
        """Kourovy ton listy (BAR_OPACITY) kontrast bileho pisma zvysuje."""
        self.assertGreater(self.ink("#ffffff", 0.45)[0], self.ink("#ffffff", 0.0)[0] + 0.5)

    @unittest.skipUnless(os.path.exists(os.path.join(WALLS, "luxos-sunrise.jpg")), "LuxOS wallpapers not installed")
    def test_luxos_wallpapers(self):
        """Skutecne tapety s pruhlednou listou (BAR_OPACITY=0): Sunrise (svetla, ale bile pismo citelne)
        zustava bila, Light/Citrus/Flow Light prepnou na tmave, tmave tapety zustavaji bile."""
        expect = {"sunrise": False, "light": True, "flow-light": True, "citrus": True, "lagoon": False,
                  "twilight": False, "dark": False, "flow-dark": False, "aurora-blue": False}
        for name, dark in expect.items():
            path = os.path.join(WALLS, "luxos-%s.jpg" % name)
            if not os.path.exists(path):
                continue
            c, from_white, from_dark = self.ink(path)
            self.assertEqual(from_white, dark, (name, c))
            self.assertEqual(from_dark, dark, (name, c))


if __name__ == "__main__":
    unittest.main()
