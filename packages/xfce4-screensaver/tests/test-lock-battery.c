/*
 * LuxOS - ikona baterie zamykaci obrazovky (luxos-lock-battery.c): blesk pri nabijeni musi byt
 * videt pri kazdem nabiti (0-100 %), na svetle, stredni i tmave tapete, pri meritku 1x i 2x.
 *
 *     gcc -o test-lock-battery tests/test-lock-battery.c luxos-lock-battery.c -I. \
 *         $(pkg-config --cflags --libs cairo glib-2.0) -lm
 *     ./test-lock-battery [DIR]      (s DIR ulozi i obrazky ikon v kazde kombinaci)
 *
 * Ikona se nakresli do obrazku a porovna se jas pixelu uvnitr blesku s jeho okolim: s lemem tesne
 * kolem blesku a s plochou baterie dal od nej (vypln nebo prazdna cast), zvlast nad vyplni a nad
 * prazdnou casti (pas kolem okraje vyplne se vynecha). Masky blesku a okoli kresli stejna cesta
 * jako ikona (lux_battery_bolt_path), barvy se ale ctou z vysledneho obrazku.
 */
#include <math.h>
#include <stdio.h>

#include <glib.h>

#include "luxos-lock-battery.h"

#define MARGIN_RING 0.35
#define MARGIN_AREA 0.25

static const char *out_dir;

static cairo_surface_t *
mask_surface (int w, int ht, double scale, const LuxBatteryGeom *g, double stroke) {
    cairo_surface_t *s = cairo_image_surface_create (CAIRO_FORMAT_A8, w, ht);
    cairo_t *cr = cairo_create (s);
    cairo_scale (cr, scale, scale);
    lux_battery_bolt_path (cr, g);
    if (stroke > 0) {
        cairo_set_line_width (cr, stroke);
        cairo_set_line_join (cr, CAIRO_LINE_JOIN_ROUND);
        cairo_stroke_preserve (cr);
    }
    cairo_fill (cr);
    cairo_destroy (cr);
    cairo_surface_flush (s);
    return s;
}

static inline guint8
mask_at (cairo_surface_t *s, int x, int y) {
    return cairo_image_surface_get_data (s)[y * cairo_image_surface_get_stride (s) + x];
}

static double
lum_at (cairo_surface_t *s, int x, int y) {
    guint32 p = ((guint32 *) (cairo_image_surface_get_data (s) + y * cairo_image_surface_get_stride (s)))[x];
    return (0.2126 * ((p >> 16) & 0xff) + 0.7152 * ((p >> 8) & 0xff) + 0.0722 * (p & 0xff)) / 255.0;
}

/* stred pixelu uvnitr tela baterie (aspon 0.5 px od obrysu) */
static gboolean
inside_px (const LuxBatteryGeom *g, double scale, int px, int py) {
    double lx = (px + 0.5) / scale, ly = (py + 0.5) / scale;
    return lx > g->ix + 0.5 && lx < g->ix + g->iw - 0.5 && ly > g->iy + 0.5 && ly < g->iy + g->ih - 0.5;
}

typedef struct { double sum; int n; } Acc;

static double
mean (const Acc *a) {
    return a->n ? a->sum / a->n : 0;
}

/* vrati pocet porovnanych oblasti (nad vyplni / nad prazdnou casti) */
static int
check_icon (double h, double scale, double bg, int level) {
    double x = 4, y = 4;
    int w = (int) ceil ((h * 2.05 + 8) * scale), ht = (int) ceil ((h + 8) * scale), compared = 0;
    LuxBatteryGeom g;
    cairo_surface_t *img, *m_bolt, *m_ring, *m_far;
    cairo_t *cr;
    Acc bolt[2] = { 0 }, ring[2] = { 0 }, area[2] = { 0 };
    double ex, band, outline_diff = 0;

    lux_battery_geom (x, y, h, level, &g);
    img = cairo_image_surface_create (CAIRO_FORMAT_ARGB32, w, ht);
    cr = cairo_create (img);
    cairo_set_source_rgb (cr, bg, bg, bg);
    cairo_paint (cr);
    cairo_scale (cr, scale, scale);
    lux_battery_draw (cr, x, y, h, level, TRUE);
    cairo_destroy (cr);
    cairo_surface_flush (img);
    if (out_dir) {
        char *name = g_strdup_printf ("%s/bat-h%.1f-x%.0f-bg%.2f-%03d.png", out_dir, h, scale, bg, level);
        cairo_surface_write_to_png (img, name);
        g_free (name);
    }

    m_bolt = mask_surface (w, ht, scale, &g, 0);
    m_ring = mask_surface (w, ht, scale, &g, 2 * g.ring);
    m_far = mask_surface (w, ht, scale, &g, 2 * (g.ring + 2.0));
    ex = (g.fx + g.fw) * scale;
    band = (g.ring + 2.5) * scale;
    for (int py = 0; py < ht; py++) {
        for (int px = 0; px < w; px++) {
            double dx = px + 0.5;
            gboolean inside = inside_px (&g, scale, px, py);
            guint8 b = mask_at (m_bolt, px, py), r = mask_at (m_ring, px, py), f = mask_at (m_far, px, py);
            int side;
            double l = lum_at (img, px, py);
            /* obrys tela mimo vnitrek: na kazde tapete se musi lisit od pozadi */
            if (!inside && fabs (l - bg) > outline_diff)
                outline_diff = fabs (l - bg);
            if (!inside || fabs (dx - ex) < band)
                continue;
            side = dx < ex ? 0 : 1;
            if (b >= 192) {
                bolt[side].sum += l;
                bolt[side].n++;
            } else if (b <= 40 && r >= 160) {
                ring[side].sum += l;
                ring[side].n++;
            } else if (r <= 5 && f >= 250) {
                area[side].sum += l;
                area[side].n++;
            }
        }
    }
    /* mistni kontrast vcetne mista, kde okraj vyplne protina blesk: kazdy pixel blesku proti lemu
     * kolem nej na stejne strane okraje vyplne */
    {
        double rad = g.ring * scale + 1.5;
        int checked = 0, passed = 0, rr = (int) ceil (rad);
        for (int py = 0; py < ht; py++) {
            for (int px = 0; px < w; px++) {
                double dx = px + 0.5, l, sum = 0;
                int n = 0;
                if (mask_at (m_bolt, px, py) < 192 || fabs (dx - ex) < 1.0 || !inside_px (&g, scale, px, py))
                    continue;
                l = lum_at (img, px, py);
                for (int qy = MAX (0, py - rr); qy <= MIN (ht - 1, py + rr); qy++) {
                    for (int qx = MAX (0, px - rr); qx <= MIN (w - 1, px + rr); qx++) {
                        double qdx = qx + 0.5;
                        if ((qx - px) * (qx - px) + (qy - py) * (qy - py) > rad * rad
                            || mask_at (m_bolt, qx, qy) > 40 || mask_at (m_ring, qx, qy) < 160
                            || fabs (qdx - ex) < 1.0 || (qdx < ex) != (dx < ex) || !inside_px (&g, scale, qx, qy))
                            continue;
                        sum += lum_at (img, qx, qy);
                        n++;
                    }
                }
                if (!n)
                    continue;
                checked++;
                if (fabs (l - sum / n) >= MARGIN_RING)
                    passed++;
            }
        }
        if (checked >= 3) {
            compared++;
            if (passed < checked * 0.9) {
                g_printerr ("FAIL h=%.1f scale=%.0f bg=%.2f level=%d: only %d of %d bolt pixels stand out from "
                            "the edge around them\n", h, scale, bg, level, passed, checked);
                g_test_fail ();
            }
        }
    }
    for (int side = 0; side < 2; side++) {
        if (bolt[side].n < 3 || ring[side].n < 3)
            continue;
        compared++;
        if (fabs (mean (&bolt[side]) - mean (&ring[side])) < MARGIN_RING
            || (area[side].n >= 3 && fabs (mean (&bolt[side]) - mean (&area[side])) < MARGIN_AREA)) {
            g_printerr ("FAIL h=%.1f scale=%.0f bg=%.2f level=%d %s: bolt %.2f (%d px), ring %.2f (%d px), "
                        "area %.2f (%d px)\n", h, scale, bg, level, side ? "over empty part" : "over fill",
                        mean (&bolt[side]), bolt[side].n, mean (&ring[side]), ring[side].n,
                        mean (&area[side]), area[side].n);
            g_test_fail ();
        }
    }
    if (outline_diff < 0.25) {
        g_printerr ("FAIL h=%.1f scale=%.0f bg=%.2f level=%d: battery outline blends into the wallpaper (%.2f)\n",
                    h, scale, bg, level, outline_diff);
        g_test_fail ();
    }
    cairo_surface_destroy (m_bolt);
    cairo_surface_destroy (m_ring);
    cairo_surface_destroy (m_far);
    cairo_surface_destroy (img);
    return compared;
}

static void
test_bolt_visible (void) {
    /* ikona na zamku: sz.status 16 (1920x1080) a 12 (nejmensi, 1280x800 a mene) * LUX_BATTERY_H, 18 vetsi */
    static const double heights[] = { 16 * LUX_BATTERY_H, 12 * LUX_BATTERY_H, 18 };
    static const double scales[] = { 1, 2 };
    static const double bgs[] = { 0.04, 0.25, 0.5, 0.75, 0.97 };
    int expected = 0;

    for (guint hi = 0; hi < G_N_ELEMENTS (heights); hi++)
        for (guint si = 0; si < G_N_ELEMENTS (scales); si++)
            for (guint bi = 0; bi < G_N_ELEMENTS (bgs); bi++)
                for (int level = 0; level <= 100; level += 5) {
                    double h = heights[hi], s = scales[si];
                    int n = check_icon (h, s, bgs[bi], level);
                    LuxBatteryGeom g;
                    lux_battery_geom (4, 4, h, level, &g);
                    /* Porovnani musi probehnout (test neprojde naprazdno) - krome nejmensi ikony pri 1x
                     * pod 10.5 px (blesk ma jen par celych pixelu) a nabiti, kdy okraj vyplne protina blesk tak tesne,
                     * ze na zadne strane nezbyde dost pixelu. */
                    if (h * s >= 10.5 && fabs (g.fx + g.fw - g.cx) > 0.58 * g.k + g.ring + 1.0 / s) {
                        expected++;
                        if (n < 1) {
                            g_printerr ("FAIL h=%.1f scale=%.0f bg=%.2f level=%d: nothing compared\n", h, s,
                                        bgs[bi], level);
                            g_test_fail ();
                        }
                    }
                }
    g_assert_cmpint (expected, >=, 250);
}

static void
test_bolt_inside (void) {
    /* blesk zustane uvnitr tela i s lemem (neprekryje obrys) pro ruzne velikosti */
    for (double h = 8; h <= 40; h += 0.5) {
        LuxBatteryGeom g;
        lux_battery_geom (0, 0, h, 50, &g);
        g_assert_cmpfloat (g.cy - g.k - g.ring * 0.5, >=, g.iy - 1e-9);
        g_assert_cmpfloat (g.cy + g.k + g.ring * 0.5, <=, g.iy + g.ih + 1e-9);
        g_assert_cmpfloat (g.cx - 0.5 * g.k - g.ring, >, g.ix);
        g_assert_cmpfloat (g.cx + 0.58 * g.k + g.ring, <, g.ix + g.iw);
        g_assert_cmpfloat (g.k, >, h * 0.25);
    }
}

static void
test_fill_level (void) {
    LuxBatteryGeom lo, mid, full, over, under;
    lux_battery_geom (0, 0, 14.4, 0, &lo);
    lux_battery_geom (0, 0, 14.4, 50, &mid);
    lux_battery_geom (0, 0, 14.4, 100, &full);
    lux_battery_geom (0, 0, 14.4, 150, &over);
    lux_battery_geom (0, 0, 14.4, -20, &under);
    g_assert_cmpfloat (lo.fw, >, 0);                       /* i 0 % ma kousek vyplne */
    g_assert_cmpfloat (lo.fw, <, mid.fw);
    g_assert_cmpfloat (mid.fw, <, full.fw);
    g_assert_cmpfloat (over.fw, ==, full.fw);              /* mimo rozsah se orizne */
    g_assert_cmpfloat (under.fw, ==, lo.fw);
    g_assert_cmpfloat (full.fx + full.fw, <=, full.ix + full.iw);
    g_assert_cmpfloat (full.fy + full.fh, <=, full.iy + full.ih);
}

static void
test_low_red_only_discharging (void) {
    /* pod 15 % bez nabijecky je vypln cervena, s nabijeckou bila */
    for (int charging = 0; charging <= 1; charging++) {
        cairo_surface_t *s = cairo_image_surface_create (CAIRO_FORMAT_ARGB32, 60, 30);
        cairo_t *cr = cairo_create (s);
        LuxBatteryGeom g;
        guint32 p;
        int px, py, r, gr;
        cairo_set_source_rgb (cr, 0.2, 0.2, 0.2);
        cairo_paint (cr);
        lux_battery_draw (cr, 2, 2, 20, 10, charging);
        cairo_destroy (cr);
        cairo_surface_flush (s);
        lux_battery_geom (2, 2, 20, 10, &g);
        px = (int) (g.fx + g.fw / 2);
        py = (int) (g.fy + g.fh / 2);
        p = ((guint32 *) (cairo_image_surface_get_data (s) + py * cairo_image_surface_get_stride (s)))[px];
        r = (p >> 16) & 0xff;
        gr = (p >> 8) & 0xff;
        if (charging)
            g_assert_cmpint (ABS (r - gr), <, 20);
        else
            g_assert_cmpint (r - gr, >, 80);
        cairo_surface_destroy (s);
    }
}

int
main (int argc, char **argv) {
    g_test_init (&argc, &argv, NULL);
    if (argc > 1)
        out_dir = argv[1];
    g_test_add_func ("/battery/bolt-visible", test_bolt_visible);
    g_test_add_func ("/battery/bolt-inside", test_bolt_inside);
    g_test_add_func ("/battery/fill-level", test_fill_level);
    g_test_add_func ("/battery/low-red-only-discharging", test_low_red_only_discharging);
    return g_test_run ();
}
