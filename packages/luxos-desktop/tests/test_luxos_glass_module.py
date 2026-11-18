#!/usr/bin/env python3
"""GTK modul luxos-glass (files/src/luxos-glass.c): sklo oznameni a nabidky v liste, bez displeje.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_glass_module.py -v

Material v C musi byt stejny jako u widgetu (files/lsl/luxos-widgets.lsl): stejne pixely rozmazane
tapety a stejna volba svetleho/tmaveho skla. Nabidka v liste ma barvu textu podle motivu, takze
zavoj pro vynucenou barvu textu musi drzet kontrast na kazde tapete. Sklo se kresli pod obsah okna.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "files/src/luxos-glass.c"
WIDGETS = HERE.parent / "files/lsl/luxos-widgets.lsl"
GLASS_LSL = HERE.parent / "files/lsl/luxos_glass.lsl"
THEME_CSS = HERE.parent.parent / "luxos-themes/files/luxos-gtk3.css"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
CC = shutil.which("gcc")

COLORS = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.7, 0.3],
          [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.5, 0.5]]


def function(source, name):
    start = source.index("function " + name + "(")
    return source[start:source.index("\nend", start) + 4]


def rgb(pixel):
    return [(pixel >> shift & 255) / 255 for shift in (16, 8, 0)]


def luminance(color):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in color]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(pixel, light, veil, alpha):
    worst = None
    for sheen in (0, 0.08):
        background = [(v * (1 - veil) + int(light) * veil) * (1 - sheen) + sheen for v in rgb(pixel)]
        ink = (25 / 255, 31 / 255, 43 / 255) if light else (1, 1, 1)
        foreground = [i * alpha + v * (1 - alpha) for i, v in zip(ink, background)]
        values = sorted((luminance(foreground), luminance(background)))
        c = (values[1] + 0.05) / (values[0] + 0.05)
        worst = c if worst is None else min(worst, c)
    return worst


C_HARNESS = r'''
#define LUXOS_GLASS_MATERIAL_ONLY 1
#include "SRC"
#include <stdio.h>

static double colors[10][3] = {{0,0,0},{1,1,1},{1,0,0},{0,1,0},{0,0,1},{1,0.7,0.3},{1,0,1},{0,1,1},{1,1,0},{0.5,0.5,0.5}};

static cairo_surface_t *solid(double r, double g, double b)
{
    cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_RGB24, 16, 16);
    cairo_t *cr = cairo_create(s);
    cairo_set_source_rgb(cr, r, g, b);
    cairo_paint(cr);
    cairo_destroy(cr);
    return s;
}

static void path_case(const char *const *keys, int n)
{
    GHashTable *t = g_hash_table_new_full(g_str_hash, g_str_equal, NULL, NULL);
    GValue v[8] = {G_VALUE_INIT};
    gchar *p;
    for (int i = 0; i < n; i += 2) {
        g_value_init(&v[i / 2], G_TYPE_STRING);
        g_value_set_string(&v[i / 2], keys[i + 1]);
        g_hash_table_insert(t, (gpointer)keys[i], &v[i / 2]);
    }
    p = glass_wallpaper_path(t);
    printf("\"%s\"", p ? p : "");
    g_free(p);
    g_hash_table_destroy(t);
}

int main(void)
{
    printf("{\"solid\": [");
    for (int i = 0; i < 10; i++) {
        cairo_surface_t *g = glass_surface(solid(colors[i][0], colors[i][1], colors[i][2]), 16, 16);
        printf("%s%u", i ? ", " : "", glass_pixel(g, 8, 8));
        cairo_surface_destroy(g);
    }
    printf("], \"styles\": [");
    for (int i = 0; i < 10; i++) {
        cairo_surface_t *g = glass_surface(solid(colors[i][0], colors[i][1], colors[i][2]), 16, 16);
        gboolean light; double veil;
        GlassStats st = glass_stats(g, 0, 0, 16, 16);
        glass_style(g, 0, 0, 16, 16, &light, &veil);
        printf("%s[%s, %.17g, %.17g, %.17g]", i ? ", " : "", light ? "true" : "false", veil,
               glass_veil(st, TRUE), glass_veil(st, FALSE));
        cairo_surface_destroy(g);
    }
    printf("], \"edge\": [");
    {
        cairo_surface_t *s = solid(0, 0, 0);
        cairo_t *cr = cairo_create(s);
        cairo_set_source_rgb(cr, 1, 1, 1);
        cairo_rectangle(cr, 8, 0, 8, 16);
        cairo_fill(cr);
        cairo_destroy(cr);
        cairo_surface_t *g = glass_surface(s, 16, 16);
        for (int x = 5; x < 11; x++)
            printf("%s%u", x > 5 ? ", " : "", glass_pixel(g, x, 8));
        cairo_surface_destroy(g);
    }
    printf("], \"paths\": [");
    {
        const char *a[] = {"/backdrop/screen0/monitorHDMI-1/workspace0/last-image", "/hdmi.jpg",
                           "/backdrop/screen0/monitoreDP-1/workspace0/last-image", "/edp.jpg",
                           "/backdrop/screen0/monitoreDP-1/workspace1/last-image", "/ws1.jpg",
                           "/backdrop/screen0/monitoreDP-1/workspace0/image-style", "/style"};
        const char *b[] = {"/backdrop/screen0/monitorHDMI-1/workspace0/last-image", "/hdmi.jpg"};
        const char *c[] = {"/backdrop/screen0/monitoreDP-1/workspace1/last-image", "/ws1.jpg"};
        path_case(a, 8); printf(", "); path_case(b, 2); printf(", "); path_case(c, 2);
    }
    /* Sklo pod obsahem: obsah (cerveny ctverec) zustane, prazdne misto je neprusvitne sklo,
       roh za zaoblenim zustane pruhledny */
    printf("], \"paint\": [");
    {
        cairo_surface_t *win = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 64, 64);
        cairo_t *cr = cairo_create(win);
        cairo_set_source_rgba(cr, 1, 0, 0, 1);
        cairo_rectangle(cr, 20, 20, 10, 10);
        cairo_fill(cr);
        glass.surface = glass_surface(solid(0.2, 0.4, 0.8), 16, 16);
        glass.map[0] = 16; glass.map[1] = 16; glass.map[2] = 0.25; glass.map[3] = 0; glass.map[4] = 0;
        gboolean light = glass_paint(cr, 0, 0, 64, 64, 16, 0, 0, 1);
        cairo_destroy(cr);
        cairo_surface_flush(win);
        unsigned char *d = cairo_image_surface_get_data(win);
        int stride = cairo_image_surface_get_stride(win);
        guint32 content = *(guint32 *)(d + 25 * stride + 25 * 4);
        guint32 empty = *(guint32 *)(d + 40 * stride + 40 * 4);
        guint32 corner = *(guint32 *)(d + 0 * stride + 0 * 4);
        printf("%s, %u, %u, %u", light ? "true" : "false", content, empty, corner);
    }
    /* Tapeta 200x100 na monitoru 1920x1080 na pozici 0,0: zmensenina 96x48, styl "priblizit" */
    printf("], \"map\": [");
    {
        cairo_surface_t *png = cairo_image_surface_create(CAIRO_FORMAT_RGB24, 200, 100);
        cairo_t *cr = cairo_create(png);
        cairo_set_source_rgb(cr, 0.3, 0.5, 0.7);
        cairo_paint(cr);
        cairo_destroy(cr);
        cairo_surface_write_to_png(png, "MAPPNG");
        cairo_surface_destroy(png);
        GdkRectangle geo = {0, 0, 1920, 1080};
        glass_load_path("MAPPNG", geo);
        printf("%.17g, %.17g, %.17g, %.17g, %.17g, %d", glass.map[0], glass.map[1], glass.map[2], glass.map[3],
               glass.map[4], glass.surface != NULL);
        glass_load_path("/nonexistent/wallpaper.jpg", geo);
        printf(", %d", glass.surface != NULL);
    }
    printf("]}\n");
    return 0;
}
'''

LSL_HARNESS = '''
colors = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.7, 0.3], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.5, 0.5]]
solid = []
styles = []
for color in colors:
    s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
    cr = cairo.create(s)
    call cairo.set_source_rgb(cr, color[0], color[1], color[2])
    call cairo.paint(cr)
    call cairo.destroy(cr)
    glass = glass_surface(s, 16, 16)
    solid.append(cairo.image_surface_pixel(glass, 8, 8))
    styles.append(glass_style(glass, 0, 0, 16, 16))
    call cairo.surface_destroy(glass)
end
s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
cr = cairo.create(s)
call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
call cairo.paint(cr)
call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
call cairo.rectangle(cr, 8, 0, 8, 16)
call cairo.fill(cr)
call cairo.destroy(cr)
glass = glass_surface(s, 16, 16)
edge = []
for x in range(5, 11):
    edge.append(cairo.image_surface_pixel(glass, x, 8))
end
call cairo.surface_destroy(glass)
print(json.encode([solid, edge, styles]))
'''


def pkg_flags():
    r = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk+-3.0"], capture_output=True, text=True)
    return r.stdout.split() if r.returncode == 0 else None


@unittest.skipUnless(CC and pkg_flags(), "needs gcc and gtk+-3.0 headers")
class GlassModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(prefix="glass-module-") as tmp:
            src, binary = Path(tmp) / "harness.c", Path(tmp) / "harness"
            src.write_text(C_HARNESS.replace("SRC", str(SRC)).replace("MAPPNG", str(Path(tmp) / "wall.png")))
            r = subprocess.run([CC, "-O2", "-Wall", "-Werror", "-o", str(binary), str(src), *pkg_flags(), "-lm"],
                               capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise AssertionError(r.stdout + r.stderr)
            cls.c = json.loads(subprocess.check_output([str(binary)], text=True, timeout=10))
        cls.lsl = None
        if LSLC:
            source = WIDGETS.read_text()
            harness = ("load cairo, json\n" + function(source, "clamp") + "\n" + function(source, "glass_surface")
                       + "\n" + function(source, "glass_style") + LSL_HARNESS)
            with tempfile.TemporaryDirectory(prefix="glass-lsl-") as tmp:
                src, binary = Path(tmp) / "glass.lsl", Path(tmp) / "glass"
                src.write_text(harness)
                r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src), str(binary)],
                                   capture_output=True, text=True, timeout=120)
                if r.returncode:
                    raise AssertionError(r.stdout + r.stderr)
                cls.lsl = json.loads(subprocess.check_output([str(binary)], text=True, timeout=10))

    def test_same_material_as_widgets(self):
        if self.lsl is None:
            self.skipTest("needs lslc (comparison with luxos-widgets.lsl)")
        solid, edge, styles = self.lsl
        # LSL vraci pixel RGB24 i s nepouzitym hornim bajtem (0xFF), porovnava se jen barva
        solid = [p & 0xFFFFFF for p in solid]
        edge = [p & 0xFFFFFF for p in edge]
        self.assertEqual(self.c["solid"], solid, "rozmazana tapeta pixel po pixelu jako widgety")
        self.assertEqual(self.c["edge"], edge, "prechod ostre hrany jako widgety")
        for (light, veil, *_), (lsl_light, lsl_veil) in zip(self.c["styles"], styles):
            self.assertEqual(light, lsl_light)
            self.assertAlmostEqual(veil, lsl_veil, places=12)

    def test_notification_text_contrast(self):
        # oznameni: barva textu podle tapety (jako widgety), text i tlumeny text (90 %)
        for pixel, (light, veil, *_) in zip(self.c["solid"], self.c["styles"]):
            for alpha in (1.0, 0.90):
                self.assertGreaterEqual(contrast(pixel, light, veil, alpha), 4.5, (rgb(pixel), light, veil))

    def test_menu_text_contrast_with_theme_ink(self):
        # nabidka: barva textu podle motivu, zavoj musi drzet kontrast na kazde tapete
        for pixel, (_, _, veil_light, veil_dark) in zip(self.c["solid"], self.c["styles"]):
            self.assertGreaterEqual(contrast(pixel, True, veil_light, 1.0), 4.5, ("svetly motiv", rgb(pixel)))
            self.assertGreaterEqual(contrast(pixel, False, veil_dark, 1.0), 4.5, ("tmavy motiv", rgb(pixel)))

    def test_wallpaper_choice_like_widgets(self):
        # vestaveny displej pred HDMI, jen workspace0/last-image
        self.assertEqual(self.c["paths"], ["/edp.jpg", "/hdmi.jpg", ""])

    def test_glass_goes_under_window_content(self):
        light, content, empty, corner = self.c["paint"]
        self.assertTrue(light)
        self.assertEqual(content, 0xFFFF0000, "obsah okna zustane nad sklem")
        self.assertEqual(empty >> 24, 0xFF, "prazdne misto okna je neprusvitne sklo")
        self.assertNotEqual(empty & 0xFFFFFF, 0, "sklo ma barvu tapety")
        self.assertEqual(corner, 0, "roh za zaoblenim zustane pruhledny")

    def test_wallpaper_map_like_widgets(self):
        # load_wallpaper z luxos-widgets.lsl: mapa obrazku na monitor (styl "priblizit")
        pw, ph, sc, ox, oy, loaded, missing = self.c["map"]
        self.assertEqual((pw, ph), (96, 48))
        exp_sc = min(96 / 1920, 48 / 1080)
        self.assertAlmostEqual(sc, exp_sc, places=12)
        self.assertAlmostEqual(ox, (96 - 1920 * exp_sc) / 2, places=9)
        self.assertAlmostEqual(oy, (48 - 1080 * exp_sc) / 2, places=9)
        self.assertEqual(loaded, 1)
        self.assertEqual(missing, 0, "chybejici tapeta: zadne sklo (okno podle motivu)")

    def test_lsl_panel_material_is_widget_material(self):
        # Ovladaci centrum (luxos_glass.panel): doslovna kopie glass_surface a stejny zavoj jako glass_style
        widgets, glass = WIDGETS.read_text(), GLASS_LSL.read_text()
        self.assertEqual(function(glass, "glass_surface"), function(widgets, "glass_surface"))
        if not LSLC:
            self.skipTest("needs lslc")
        harness = ("load cairo, json\n" + function(widgets, "clamp") + "\n" + function(widgets, "glass_surface")
                   + "\n" + function(widgets, "glass_style") + "\n" + function(glass, "glass_extremes")
                   + "\n" + function(glass, "glass_veil") + """
out = []
for color in [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.7, 0.3], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.5, 0.5]]:
    s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
    cr = cairo.create(s)
    call cairo.set_source_rgb(cr, color[0], color[1], color[2])
    call cairo.paint(cr)
    call cairo.destroy(cr)
    g = glass_surface(s, 16, 16)
    st = glass_style(g, 0, 0, 16, 16)
    out.append([st[0], st[1], glass_veil(glass_extremes(g, 0, 0, 16, 16), st[0])])
end
print(json.encode(out))
""")
        with tempfile.TemporaryDirectory(prefix="glass-panel-") as tmp:
            src, binary = Path(tmp) / "p.lsl", Path(tmp) / "p"
            src.write_text(harness)
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src), str(binary)],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rows = json.loads(subprocess.check_output([str(binary)], text=True, timeout=10))
        for light, veil, panel_veil in rows:
            self.assertAlmostEqual(veil, panel_veil, places=12)

    def test_menu_geometry_matches_theme_css(self):
        css = THEME_CSS.read_text()
        block = re.search(r"window#whiskermenu-window > frame > border \{(.*?)\}", css, re.S).group(1)
        self.assertIn("margin: 8px;", block)
        self.assertIn("border-radius: 16px;", block)
        c = SRC.read_text()
        self.assertIn("#define MENU_MARGIN 8.0", c)
        self.assertIn("#define MENU_RADIUS 16.0", c)


if __name__ == "__main__":
    unittest.main()
