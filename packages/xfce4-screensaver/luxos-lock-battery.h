/*
 * LuxOS - ikona baterie zamykaci obrazovky (jen cairo, bez GTK - testy: tests/test-lock-battery.c).
 * Stejna kresba je v luxos-greeter (icon_battery) - pri zmene upravit obe.
 */
#ifndef LUXOS_LOCK_BATTERY_H
#define LUXOS_LOCK_BATTERY_H

#include <cairo.h>
#include <glib.h>

/* vyska ikony vuci velikosti stavovych ikon (sz.status); sirka je 2.05 * vyska. Driv 0.78 - pri
 * 1280x800 (sz.status 12) mela ikona 9 px a blesk jen 3x6 px. */
#define LUX_BATTERY_H 0.9

typedef struct {
    double lw;                 /* sirka obrysu */
    double bx, by, bw, bh, br; /* obrys tela (stred cary) */
    double ix, iy, iw, ih;     /* vnitrek tela */
    double fx, fy, fw, fh;     /* vypln podle nabiti */
    double cx, cy, k;          /* stred a polovina vysky blesku */
    double ring;               /* sirka kontrastniho lemu kolem blesku */
} LuxBatteryGeom;

void lux_battery_geom (double x, double y, double h, int level, LuxBatteryGeom *g);
void lux_battery_bolt_path (cairo_t *cr, const LuxBatteryGeom *g);
void lux_battery_draw (cairo_t *cr, double x, double y, double h, int level, gboolean charging);

#endif
