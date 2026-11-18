/*
 * LuxOS - ikona baterie zamykaci obrazovky (jen cairo, bez GTK - testy: tests/test-lock-battery.c).
 *
 * Blesk pri nabijeni musi byt videt pri kazdem nabiti, na svetle i tmave tapete: nad vyplni je
 * tmavy s bilym lemem, nad prazdnou casti bily s tmavym lemem (jako blesk v baterii macOS).
 * Vnitrek tela ma tmavy podklad a obrys tmavy stin, takze bila baterie zustane videt i na svetle
 * tapete. Driv byl blesk bily nad prazdnou casti bez podkladu - na svetle tapete (a pri nizsim
 * nabiti, kdy blesk lezi cely nad prazdnou casti) splynul s pozadim.
 * Stejna kresba je v luxos-greeter (icon_battery) - pri zmene upravit obe.
 */
#include <math.h>

#include "luxos-lock-battery.h"

/* blesk v jednotkach poloviny vysky (k), stred v (0, 0) */
static const double bolt_pts[][2] = {
    { 0.14, -1.0 }, { -0.58, 0.14 }, { -0.07, 0.14 }, { -0.14, 1.0 }, { 0.58, -0.14 }, { 0.07, -0.14 },
};

static void
rounded (cairo_t *cr, double x, double y, double w, double h, double r) {
    r = MAX (0.0, MIN (r, MIN (w / 2, h / 2)));
    cairo_new_sub_path (cr);
    cairo_arc (cr, x + w - r, y + r, r, -G_PI / 2, 0);
    cairo_arc (cr, x + w - r, y + h - r, r, 0, G_PI / 2);
    cairo_arc (cr, x + r, y + h - r, r, G_PI / 2, G_PI);
    cairo_arc (cr, x + r, y + r, r, G_PI, 1.5 * G_PI);
    cairo_close_path (cr);
}

void
lux_battery_geom (double x, double y, double h, int level, LuxBatteryGeom *g) {
    double w = h * 2.05, inner, frac;
    g->lw = MAX (1.0, h * 0.09);
    g->bx = x + g->lw / 2;
    g->by = y + g->lw / 2;
    g->bw = w - h * 0.22 - g->lw;
    g->bh = h - g->lw;
    g->br = h * 0.26;
    g->ix = x + g->lw;
    g->iy = y + g->lw;
    g->iw = g->bw - g->lw;
    g->ih = h - 2 * g->lw;
    inner = g->iw - h * 0.16;
    frac = CLAMP (level / 100.0, 0.0, 1.0);
    g->fx = g->ix + h * 0.08;
    g->fy = g->iy + h * 0.08;
    g->fw = MAX (h * 0.12, inner * frac);
    g->fh = g->ih - h * 0.16;
    g->ring = MAX (1.0, h * 0.08);
    g->cx = g->bx + g->bw / 2;
    g->cy = y + h / 2;
    g->k = g->ih / 2 - g->ring * 0.75;
}

void
lux_battery_bolt_path (cairo_t *cr, const LuxBatteryGeom *g) {
    cairo_new_path (cr);
    for (guint i = 0; i < G_N_ELEMENTS (bolt_pts); i++)
        cairo_line_to (cr, g->cx + bolt_pts[i][0] * g->k, g->cy + bolt_pts[i][1] * g->k);
    cairo_close_path (cr);
}

void
lux_battery_draw (cairo_t *cr, double x, double y, double h, int level, gboolean charging) {
    LuxBatteryGeom g;
    double halo, ex;

    lux_battery_geom (x, y, h, level, &g);
    halo = MAX (0.75, h * 0.06);
    cairo_save (cr);
    cairo_set_line_join (cr, CAIRO_LINE_JOIN_ROUND);

    /* tmavy stin obrysu a podklad vnitrku: baterie je videt i na svetle tapete */
    cairo_set_source_rgba (cr, 0, 0, 0, 0.38);
    cairo_set_line_width (cr, g.lw + 2 * halo);
    rounded (cr, g.bx, g.by, g.bw, g.bh, g.br);
    cairo_stroke (cr);
    rounded (cr, x + h * 2.05 - h * 0.2 - halo, y + h * 0.33 - halo, h * 0.14 + 2 * halo, h * 0.34 + 2 * halo,
             h * 0.06 + halo);
    cairo_fill (cr);
    cairo_set_source_rgba (cr, 0, 0, 0, 0.38);
    rounded (cr, g.ix, g.iy, g.iw, g.ih, g.br - g.lw / 2);
    cairo_fill (cr);

    /* obrys a vystupek */
    cairo_set_source_rgba (cr, 1, 1, 1, 0.9);
    cairo_set_line_width (cr, g.lw);
    rounded (cr, g.bx, g.by, g.bw, g.bh, g.br);
    cairo_stroke (cr);
    rounded (cr, x + h * 2.05 - h * 0.2, y + h * 0.33, h * 0.14, h * 0.34, h * 0.06);
    cairo_fill (cr);

    /* vypln */
    if (level <= 15 && !charging)
        cairo_set_source_rgba (cr, 1.0, 0.36, 0.33, 1);
    else
        cairo_set_source_rgba (cr, 1, 1, 1, 0.95);
    rounded (cr, g.fx, g.fy, g.fw, g.fh, h * 0.14);
    cairo_fill (cr);

    if (charging) {
        ex = g.fx + g.fw;
        cairo_set_line_width (cr, 2 * g.ring);
        /* nad vyplni: tmavy blesk s bilym lemem (lem zakryje i mezeru mezi vyplni a obrysem) */
        if (ex > g.ix) {
            cairo_save (cr);
            cairo_rectangle (cr, g.ix, g.iy, ex - g.ix, g.ih);
            cairo_clip (cr);
            lux_battery_bolt_path (cr, &g);
            cairo_set_source_rgba (cr, 1, 1, 1, 0.95);
            cairo_stroke_preserve (cr);
            cairo_set_source_rgba (cr, 0.10, 0.10, 0.12, 0.92);
            cairo_fill (cr);
            cairo_restore (cr);
        }
        /* nad prazdnou casti: bily blesk s tmavym lemem */
        if (ex < g.ix + g.iw) {
            cairo_save (cr);
            cairo_rectangle (cr, ex, g.iy, g.ix + g.iw - ex, g.ih);
            cairo_clip (cr);
            lux_battery_bolt_path (cr, &g);
            cairo_set_source_rgba (cr, 0, 0, 0, 0.60);
            cairo_stroke_preserve (cr);
            cairo_set_source_rgba (cr, 1, 1, 1, 0.97);
            cairo_fill (cr);
            cairo_restore (cr);
        }
    }
    cairo_restore (cr);
}
