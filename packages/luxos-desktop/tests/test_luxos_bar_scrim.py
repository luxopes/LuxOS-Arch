#!/usr/bin/env python3
"""LuxOS - zavoj pod listou na velmi svetle tapete (scrim_* a readable_alpha v files/src/luxos-bar.c).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_bar_scrim.py -v

Prelozi maly program, ktery vlozi zdroj pluginu (bez displeje): sila zavoje podle jasu tapety,
prubeh zavoje bez hrany, kontrast bileho pisma listy se zavojem a tonem listy, beze zmeny na
beznych tapetach (Sunrise, Lagoon, tmave) a stejny vyrez tapety jako drive (wallpaper_region).
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
static GdkPixbuf *solid (const char *hex, int w, int h) {
    GdkPixbuf *pb = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, w, h);
    gdk_pixbuf_fill (pb, ((guint32) strtoul (hex + 1, NULL, 16) << 8) | 0xff);
    return pb;
}
static double mean_lin (GdkPixbuf *pb) {
    int w = gdk_pixbuf_get_width (pb), h = gdk_pixbuf_get_height (pb), rs = gdk_pixbuf_get_rowstride (pb);
    const guchar *px = gdk_pixbuf_read_pixels (pb);
    double s = 0;
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            const guchar *p = px + y * rs + x * 3;
            s += 0.2126 * srgb_linear (p[0]) + 0.7152 * srgb_linear (p[1]) + 0.0722 * srgb_linear (p[2]);
        }
    return s / (w * h);
}
int main (int argc, char **argv) {
    const char *cmd = argv[1];
    if (strcmp (cmd, "strength") == 0) {            /* strength LUM */
        printf ("%%.4f\n", scrim_strength (atof (argv[2])));
    } else if (strcmp (cmd, "profile") == 0) {      /* profile T */
        printf ("%%.4f\n", scrim_profile (atof (argv[2])));
    } else if (strcmp (cmd, "lum") == 0) {          /* lum SOUBOR: jas pasu zavoje na 1920x1080 */
        printf ("%%.4f\n", measure_top_lum (argv[2], 5, 1920, 1080, 1));
    } else if (strcmp (cmd, "bar") == 0) {          /* bar #rrggbb SILA ALFA_TONU: kontrast bileho pisma */
        GdkPixbuf *pb = solid (argv[2], 400, 28);
        double s = atof (argv[3]);
        apply_scrim_rows (pb, s, 0, 1);
        GdkRGBA t = { 0.09, 0.09, 0.12, atof (argv[4]) };
        double a = CLAMP (readable_alpha (pb, &t, s), 0.0, 1.0);
        guchar *px = gdk_pixbuf_get_pixels (pb);
        int rs = gdk_pixbuf_get_rowstride (pb);
        for (int y = 0; y < 28; y++)
            for (int x = 0; x < 400; x++)
                for (int i = 0; i < 3; i++) {
                    guchar *p = px + y * rs + x * 3 + i;
                    double tc = (i == 2 ? t.blue : i == 1 ? t.green : t.red) * 255.0 * a;
                    *p = (guchar) CLAMP (*p * (1.0 - a) + tc + 0.5, 0, 255);
                }
        /* nejhorsi radek (spodni, nejslabsi zavoj) */
        GdkPixbuf *row = gdk_pixbuf_new_subpixbuf (pb, 0, 27, 400, 1);
        printf ("%%.3f %%.4f\n", 1.05 / (mean_lin (row) + 0.05), a);
    } else if (strcmp (cmd, "region") == 0) {       /* region SOUBOR: vyrez listy jako drive */
        GdkPixbuf *src = gdk_pixbuf_new_from_file (argv[2], NULL);
        int iw = gdk_pixbuf_get_width (src), ih = gdk_pixbuf_get_height (src);
        GdkPixbuf *a = wallpaper_region (src, iw, ih, 5, 1920, 1080, 0, 0, 1920, 28, 1920, 28);
        double s = MAX (1920.0 / iw, 1080.0 / ih);
        GdkPixbuf *b = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, 1920, 28);
        gdk_pixbuf_scale (src, b, 0, 0, 1920, 28, (1920 - iw * s) / 2, (1080 - ih * s) / 2, s, s, GDK_INTERP_BILINEAR);
        int diff = 0, rs = gdk_pixbuf_get_rowstride (a);
        for (int y = 0; y < 28; y++)
            for (int x = 0; x < 1920 * 3; x++)
                diff = MAX (diff, abs (gdk_pixbuf_get_pixels (a)[y * rs + x] - gdk_pixbuf_get_pixels (b)[y * gdk_pixbuf_get_rowstride (b) + x]));
        printf ("%%d\n", diff);
    } else if (strcmp (cmd, "load") == 0) {         /* load SOUBOR STYL: velka tapeta na 1920x1080 */
        int style = atoi (argv[3]);
        GdkPixbuf *big = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, 5760, 2400);
        int rs = gdk_pixbuf_get_rowstride (big);
        for (int y = 0; y < 2400; y++)
            for (int x = 0; x < 5760; x++) {
                guchar *p = gdk_pixbuf_get_pixels (big) + y * rs + x * 3;
                p[0] = x * 255 / 5759; p[1] = y * 255 / 2399; p[2] = 128;
            }
        gdk_pixbuf_save (big, argv[2], "png", NULL, NULL);
        int ow, oh;
        GdkPixbuf *src = load_wallpaper (argv[2], style, 1920, 1080, &ow, &oh);
        GdkPixbuf *a = wallpaper_region (src, ow, oh, style, 1920, 1080, 0, 0, 1920, 28, 1920, 28);
        GdkPixbuf *b = wallpaper_region (big, 5760, 2400, style, 1920, 1080, 0, 0, 1920, 28, 1920, 28);
        int diff = 0, ra = gdk_pixbuf_get_rowstride (a), rb = gdk_pixbuf_get_rowstride (b);
        for (int y = 0; y < 28; y++)
            for (int x = 0; x < 1920 * 3; x++)
                diff = MAX (diff, abs (gdk_pixbuf_get_pixels (a)[y * ra + x] - gdk_pixbuf_get_pixels (b)[y * rb + x]));
        printf ("%%d %%d %%d %%d %%d\n", gdk_pixbuf_get_width (src), gdk_pixbuf_get_height (src), ow, oh, diff);
    }
    (void) argc;
    return 0;
}
'''


def have():
    return shutil.which("gcc") and shutil.which("pkg-config") and \
        subprocess.run(["pkg-config", "--exists", *PKGS]).returncode == 0


@unittest.skipUnless(have(), "needs gcc and xfce4-panel/wnck/xfconf headers")
class BarScrim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.mkdtemp(prefix="luxos-bar-scrim-")
        c = os.path.join(cls.t, "main.c")
        with open(c, "w") as f:
            f.write(MAIN % SRC)
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", *PKGS], capture_output=True, text=True,
                               check=True).stdout.split()
        cls.bin = os.path.join(cls.t, "scrim")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-Wno-unused-function", "-o", cls.bin, c, *flags,
                        "-lm"], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, True)

    def run_bin(self, *args):
        return subprocess.run([self.bin, *map(str, args)], capture_output=True, text=True,
                              check=True).stdout.split()

    def strength(self, lum):
        return float(self.run_bin("strength", lum)[0])

    def test_strength_by_brightness(self):
        """Bila, bezova a bily len plny zavoj; Sunrise (0,43) a tmavsi zadny; mezi plynule."""
        self.assertAlmostEqual(self.strength(1.0), 1.0, places=3)
        self.assertAlmostEqual(self.strength(0.84), 1.0, places=3)    # bezova
        self.assertAlmostEqual(self.strength(0.43), 0.0, places=3)    # Sunrise
        self.assertAlmostEqual(self.strength(0.40), 0.0, places=3)    # Lagoon
        self.assertAlmostEqual(self.strength(0.0), 0.0, places=3)
        last = -1.0
        for i in range(0, 101):
            s = self.strength(i / 100)
            self.assertGreaterEqual(s, last - 1e-9, i)
            last = s

    def test_profile_has_no_edge(self):
        """1 nahore, 0 dole, klesa a na koncich je plochy (zadna viditelna hrana)."""
        p = lambda t: float(self.run_bin("profile", t)[0])  # noqa: E731
        self.assertAlmostEqual(p(0), 1.0, places=4)
        self.assertAlmostEqual(p(1), 0.0, places=4)
        self.assertAlmostEqual(p(1.5), 0.0, places=4)
        self.assertLess(abs(p(0.99) - p(1.0)), 0.001)
        self.assertLess(abs(p(0.0) - p(0.01)), 0.001)
        vals = [p(i / 20) for i in range(21)]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_white_text_readable_with_scrim(self):
        """Svetla lista s bilym pismem (BAR_TEXT=white, ton 0,62 x 0,45) na bile, bezove a lnene
        tapete: se zavojem aspon 4,5 : 1 (WCAG AA) i ve spodnim radku listy."""
        for col in ("#ffffff", "#f3ecdc", "#f2f0eb"):
            c, a = map(float, self.run_bin("bar", col, 1.0, 0.279))
            self.assertGreaterEqual(c, 4.5, (col, c, a))

    def test_no_scrim_keeps_old_tint(self):
        """Bez zavoje (s = 0) stejny ton jako drive: readable_alpha s puvodnim stropem 0,58."""
        c, a = map(float, self.run_bin("bar", "#ffffff", 0.0, 0.279))
        # (1 - 0,58) / (1 - 0,0914) = 0,462
        self.assertAlmostEqual(a, 0.462, delta=0.01)

    def test_region_same_as_before(self):
        """Vyrez tapety pod listou (styl vyplnit) se refaktoringem nezmenil."""
        path = os.path.join(WALLS, "luxos-sunrise.jpg")
        if not os.path.exists(path):
            self.skipTest("LuxOS wallpapers not installed")
        self.assertLessEqual(int(self.run_bin("region", path)[0]), 1)

    def test_big_wallpaper_loaded_at_screen_size(self):
        """Velka tapeta se pro vyrez pod listou nacte jen v rozliseni monitoru, vyrez je stejny."""
        path = os.path.join(self.t, "big.png")
        for style, size in ((5, (2592, 1080)), (4, (1920, 800)), (3, (1920, 1080))):
            w, h, ow, oh, diff = map(int, self.run_bin("load", path, style))
            self.assertEqual((ow, oh), (5760, 2400))
            self.assertLessEqual(abs(w - size[0]) + abs(h - size[1]), 2, (style, w, h))
            self.assertLessEqual(diff, 3, style)
        w, h, *_ = map(int, self.run_bin("load", path, 1))     # na stred: puvodni velikost
        self.assertEqual((w, h), (5760, 2400))

    @unittest.skipUnless(os.path.exists(os.path.join(WALLS, "luxos-sunrise.jpg")), "LuxOS wallpapers not installed")
    def test_luxos_wallpapers(self):
        """Sunrise, Lagoon a tmave tapety beze zmeny; svetle Light/Citrus jen castecny zavoj."""
        for name, lo, hi in (("sunrise", 0.0, 0.0), ("lagoon", 0.0, 0.0), ("dark", 0.0, 0.0),
                             ("aurora-blue", 0.0, 0.0), ("twilight", 0.0, 0.0),
                             ("light", 0.3, 0.9), ("citrus", 0.3, 0.95)):
            path = os.path.join(WALLS, "luxos-%s.jpg" % name)
            if not os.path.exists(path):
                continue
            lum = float(self.run_bin("lum", path)[0])
            s = self.strength(lum)
            self.assertTrue(lo - 1e-3 <= s <= hi + 1e-3, (name, lum, s))


if __name__ == "__main__":
    unittest.main()
