/*
 * Referencni vystupy materialu skla v C pro tests/test_luxos_material.py (porovnani s luxos_material.lsl).
 *   material-ref gen DIR          testovaci tapety (PNG, JPEG) do DIR
 *   material-ref dump CASES OUT   pro kazdy radek CASES "tapeta W H x y w h polomer ink": rozostrena tapeta,
 *                                 mapa a pixely karty skla (glass_paint do pruhledneho ARGB32 w x h) do OUT
 *   material-ref basics           jednobarevne a hranove zmenseniny, styl a zavoj (jako test_luxos_glass_module.py)
 *   material-ref bench DIR        casy v C pro srovnani s LSL (median, ms)
 */
#include "luxos-glass-material.c"
#include <stdio.h>
#include <stdlib.h>

static double colors[10][3] = {{0,0,0},{1,1,1},{1,0,0},{0,1,0},{0,0,1},{1,0.7,0.3},{1,0,1},{0,1,1},{1,1,0},{0.5,0.5,0.5}};

static void write_wall(const char *dir, const char *name, int w, int h, int kind)
{
    char path[1024];
    cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_RGB24, w, h);
    cairo_t *cr = cairo_create(s);
    cairo_pattern_t *p = cairo_pattern_create_linear(0, 0, w, h);
    cairo_pattern_add_color_stop_rgb(p, 0, 0.95, 0.55, 0.25);
    cairo_pattern_add_color_stop_rgb(p, 0.5, 0.92, 0.9, 0.82);
    cairo_pattern_add_color_stop_rgb(p, 1, 0.08, 0.2, 0.55);
    cairo_set_source(cr, p);
    cairo_paint(cr);
    cairo_pattern_destroy(p);
    if (kind == 1) {
        /* ostre skvrny: hrany a syte barvy pro rozmazani i statistiky */
        unsigned int seed = 12345;
        for (int i = 0; i < 160; i++) {
            seed = seed * 1103515245u + 12345u;
            double x = (seed >> 8) % w, y = ((seed >> 4) * 7u) % h;
            seed = seed * 1103515245u + 12345u;
            double r = 20 + (seed >> 9) % 220;
            cairo_set_source_rgb(cr, ((seed >> 3) & 255) / 255.0, ((seed >> 11) & 255) / 255.0, ((seed >> 19) & 255) / 255.0);
            cairo_rectangle(cr, x, y, r, r * 0.6);
            cairo_fill(cr);
        }
    }
    cairo_destroy(cr);
    snprintf(path, sizeof path, "%s/%s.png", dir, name);
    cairo_surface_write_to_png(s, path);
    if (kind == 1) {
        GdkPixbuf *pb = gdk_pixbuf_get_from_surface(s, 0, 0, w, h);
        snprintf(path, sizeof path, "%s/%s.jpg", dir, name);
        gdk_pixbuf_save(pb, path, "jpeg", NULL, "quality", "90", NULL);
        g_object_unref(pb);
    }
    cairo_surface_destroy(s);
}

static void dump_pixels(FILE *out, cairo_surface_t *s, int w, int h)
{
    unsigned char *d;
    int stride;
    cairo_surface_flush(s);
    d = cairo_image_surface_get_data(s);
    stride = cairo_image_surface_get_stride(s);
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
            fprintf(out, " %u", *(guint32 *)(d + y * stride + x * 4));
}

static int dump(const char *cases, const char *outpath)
{
    FILE *in = fopen(cases, "r"), *out = fopen(outpath, "w");
    char wall[1024], last[1024] = "";
    int W, H, x, y, w, h, ink, last_w = 0, last_h = 0, n = 0;
    double radius;
    if (!in || !out)
        return 1;
    while (fscanf(in, "%1023s %d %d %d %d %d %d %lf %d", wall, &W, &H, &x, &y, &w, &h, &radius, &ink) == 9) {
        if (strcmp(wall, last) != 0 || W != last_w || H != last_h) {
            GdkRectangle geo = {0, 0, W, H};
            glass_load_path(wall, geo);
            fprintf(out, "glass %s %d %d %.17g %.17g %.17g %.17g %.17g", wall, W, H,
                    glass.map[0], glass.map[1], glass.map[2], glass.map[3], glass.map[4]);
            dump_pixels(out, glass.surface, cairo_image_surface_get_width(glass.surface),
                        cairo_image_surface_get_height(glass.surface));
            fprintf(out, "\n");
            snprintf(last, sizeof last, "%s", wall);
            last_w = W;
            last_h = H;
        }
        cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
        cairo_t *cr = cairo_create(s);
        gboolean light = glass_paint(cr, 0, 0, w, h, radius, x, y, ink);
        cairo_destroy(cr);
        fprintf(out, "case %d %d", n++, light ? 1 : 0);
        dump_pixels(out, s, w, h);
        fprintf(out, "\n");
        cairo_surface_destroy(s);
    }
    fclose(in);
    fclose(out);
    return 0;
}

static cairo_surface_t *solid(double r, double g, double b)
{
    cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_RGB24, 16, 16);
    cairo_t *cr = cairo_create(s);
    cairo_set_source_rgb(cr, r, g, b);
    cairo_paint(cr);
    cairo_destroy(cr);
    return s;
}

static void basics(void)
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
        gboolean light;
        double veil;
        GlassStats st = glass_stats(g, 0, 0, 16, 16);
        glass_style(g, 0, 0, 16, 16, &light, &veil);
        printf("%s[%s, %.17g, %.17g, %.17g]", i ? ", " : "", light ? "true" : "false", veil,
               glass_veil(st, TRUE), glass_veil(st, FALSE));
        cairo_surface_destroy(g);
    }
    printf("], \"edge\": [");
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
    printf("]}\n");
}

static double now_ms(void)
{
    return g_get_monotonic_time() / 1000.0;
}

static int cmp_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return x < y ? -1 : x > y;
}

static double median(double *v, int n)
{
    qsort(v, n, sizeof *v, cmp_double);
    return v[n / 2];
}

static void bench(const char *dir)
{
    char png[1024], jpg[1024];
    double t[15];
    GdkRectangle geo = {0, 0, 1920, 1080};
    snprintf(png, sizeof png, "%s/noise.png", dir);
    snprintf(jpg, sizeof jpg, "%s/noise.jpg", dir);
    printf("{");
    for (int i = 0; i < 15; i++) {
        double a = now_ms();
        glass_load_path(png, geo);
        t[i] = now_ms() - a;
    }
    printf("\"glass_png_ms\": %.3f", median(t, 15));
    for (int i = 0; i < 15; i++) {
        double a = now_ms();
        glass_load_path(jpg, geo);
        t[i] = now_ms() - a;
    }
    printf(", \"glass_jpg_ms\": %.3f", median(t, 15));
    for (int i = 0; i < 15; i++) {
        cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1920, 32);
        cairo_t *cr = cairo_create(s);
        double a = now_ms();
        glass_paint(cr, 0, 0, 1920, 32, 0, 0, 0, -1);
        cairo_surface_flush(s);
        t[i] = now_ms() - a;
        cairo_destroy(cr);
        cairo_surface_destroy(s);
    }
    printf(", \"strip_ms\": %.3f}\n", median(t, 15));
}

int main(int argc, char **argv)
{
    if (argc == 3 && strcmp(argv[1], "gen") == 0) {
        write_wall(argv[2], "gradient", 1920, 1080, 0);
        write_wall(argv[2], "noise", 1920, 1080, 1);
        write_wall(argv[2], "portrait", 1000, 1500, 1);
        write_wall(argv[2], "tiny", 40, 30, 1);
        return 0;
    }
    if (argc == 4 && strcmp(argv[1], "dump") == 0)
        return dump(argv[2], argv[3]);
    if (argc == 2 && strcmp(argv[1], "basics") == 0) {
        basics();
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "bench") == 0) {
        bench(argv[2]);
        return 0;
    }
    fprintf(stderr, "usage: material-ref gen DIR | dump CASES OUT | basics | bench DIR\n");
    return 2;
}
