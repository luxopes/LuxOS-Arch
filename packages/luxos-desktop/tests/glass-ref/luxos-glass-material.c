/*
 * Referencni material skla v C pro test luxos_material.lsl (tests/test_luxos_material.py).
 * Doslovny vyrez files/src/luxos-glass.c z vetve gpt-features-1.1.1 (eaee2515), radky 49-297:
 * glass_surface, glass_stats, glass_veil, glass_style, glass_wallpaper_path, glass_load_path, glass_paint.
 * Neupravovat rucne - test porovnava text s vetvi, pokud je v repozitari k dispozici.
 */
#include <gtk/gtk.h>
#include <math.h>
#include <string.h>

#define GLASS_SIZE 96
/* window#whiskermenu-window > frame > border v luxos.css: margin 8px, border-radius 16px */
#define MENU_MARGIN 8.0
#define MENU_RADIUS 16.0

static double glass_clamp(double x, double lo, double hi)
{
    return fmax(lo, fmin(hi, x));
}

/* Pixel obrazku RGB24 jako 0xRRGGBB (cairo.image_surface_pixel v LSL) */
static guint32 glass_pixel(cairo_surface_t *s, int x, int y)
{
    unsigned char *data;
    cairo_surface_flush(s);
    data = cairo_image_surface_get_data(s);
    return *(guint32 *)(data + y * cairo_image_surface_get_stride(s) + x * 4) & 0xffffff;
}

/* glass_surface: dvoupruchodovy Gaussuv filtr (1, 4, 6, 4, 1) na malem obrazku; vstup uvolni */
static cairo_surface_t *glass_surface(cairo_surface_t *source, int w, int h)
{
    static const double weights[5] = {1.0, 4.0, 6.0, 4.0, 1.0};
    int axis, x, y, k;
    for (axis = 0; axis < 2; axis++) {
        cairo_surface_t *out = cairo_image_surface_create(CAIRO_FORMAT_RGB24, w, h);
        cairo_t *cr = cairo_create(out);
        for (y = 0; y < h; y++) {
            for (x = 0; x < w; x++) {
                double rgb[3] = {0.0, 0.0, 0.0};
                for (k = 0; k < 5; k++) {
                    int sx = x, sy = y;
                    guint32 px;
                    if (axis == 0)
                        sx = (int)glass_clamp(x + k - 2, 0, w - 1);
                    else
                        sy = (int)glass_clamp(y + k - 2, 0, h - 1);
                    px = glass_pixel(source, sx, sy);
                    rgb[0] = rgb[0] + (double)((px >> 16) & 255) * weights[k] / 4080.0;
                    rgb[1] = rgb[1] + (double)((px >> 8) & 255) * weights[k] / 4080.0;
                    rgb[2] = rgb[2] + (double)(px & 255) * weights[k] / 4080.0;
                }
                if (axis == 1) {
                    double lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
                    double r = 0.22 + (rgb[0] * 0.72 + lum * 0.28) * 0.72;
                    double g = 0.22 + (rgb[1] * 0.72 + lum * 0.28) * 0.72;
                    double b = 0.22 + (rgb[2] * 0.72 + lum * 0.28) * 0.72;
                    rgb[0] = r;
                    rgb[1] = g;
                    rgb[2] = b;
                }
                cairo_set_source_rgb(cr, rgb[0], rgb[1], rgb[2]);
                cairo_rectangle(cr, x, y, 1, 1);
                cairo_fill(cr);
            }
        }
        cairo_destroy(cr);
        cairo_surface_destroy(source);
        source = out;
    }
    return source;
}

typedef struct {
    double lo;      /* nejtmavsi jas vyrezu */
    double hi;      /* nejvyssi RMS energie (rezerva pro syte barvy) */
    double mean;    /* prumerny jas */
} GlassStats;

/* Statistiky vyrezu z glass_style; extremy z celeho vyrezu = jednotna barva textu v cele karte */
static GlassStats glass_stats(cairo_surface_t *surface, double sx, double sy, double sw, double sh)
{
    GlassStats st = {1.0, 0.0, 0.0};
    int pw = cairo_image_surface_get_width(surface);
    int ph = cairo_image_surface_get_height(surface);
    double total = 0.0;
    int count = 0, x, y, step;
    int y0 = (int)fmax(0, sy), y1 = (int)fmin(ph - 1, sy + sh + 1);
    int x0 = (int)fmax(0, sx), x1 = (int)fmin(pw - 1, sx + sw + 1);
    for (y = y0; y <= y1; y++) {
        for (x = x0; x <= x1; x++) {
            guint32 px = glass_pixel(surface, x, y);
            double r = (double)((px >> 16) & 255) / 255.0;
            double g = (double)((px >> 8) & 255) / 255.0;
            double b = (double)(px & 255) / 255.0;
            double lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            /* RMS drzi rezervu i pro syte cervene/modre pozadi (prostemu prumeru by uniklo) */
            double energy = 0.2126 * r * r + 0.7152 * g * g + 0.0722 * b * b;
            double peak = 1.0;
            for (step = 0; step < 6; step++)
                peak = (peak + energy / peak) / 2.0;
            st.lo = fmin(st.lo, lum);
            st.hi = fmax(st.hi, peak);
            total = total + lum;
            count = count + 1;
        }
    }
    st.mean = total / (double)MAX(1, count);
    return st;
}

/* Sila zavoje pro dany text: svetle sklo (tmavy text) bily zavoj, tmave sklo (bily text) cerny */
static double glass_veil(GlassStats st, gboolean light)
{
    if (light)
        return glass_clamp((0.64 - st.lo) / fmax(0.001, 1.0 - st.lo), 0.0, 1.0);
    return glass_clamp(1.0 - 0.37 / fmax(0.001, st.hi), 0.0, 1.0);
}

/* glass_style: svetle sklo, kdyz je vyrez v prumeru svetly; zavoj podle toho (modul pouziva
   glass_stats primo, glass_style je pro porovnani s LSL v testu) */
G_GNUC_UNUSED static void glass_style(cairo_surface_t *surface, double sx, double sy, double sw, double sh,
                        gboolean *light, double *veil)
{
    GlassStats st = glass_stats(surface, sx, sy, sw, sh);
    *light = st.mean >= 0.56;
    *veil = glass_veil(st, *light);
}

static gint key_cmp(gconstpointer a, gconstpointer b)
{
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* wallpaper_path: vlastnosti /backdrop kanalu xfce4-desktop (klic -> GValue s textem) */
G_GNUC_UNUSED static gchar *glass_wallpaper_path(GHashTable *props)
{
    GPtrArray *keys;
    GHashTableIter iter;
    gpointer key, value;
    const gchar *best = NULL;
    guint i;
    if (props == NULL)
        return NULL;
    keys = g_ptr_array_new();
    g_hash_table_iter_init(&iter, props);
    while (g_hash_table_iter_next(&iter, &key, &value))
        g_ptr_array_add(keys, key);
    g_ptr_array_sort(keys, key_cmp);
    for (i = 0; i < keys->len; i++) {
        const gchar *k = g_ptr_array_index(keys, i);
        const GValue *v = g_hash_table_lookup(props, k);
        if (g_str_has_suffix(k, "/workspace0/last-image") && v && G_VALUE_HOLDS_STRING(v)) {
            if (best == NULL || strstr(k, "monitorHDMI") == NULL)
                best = g_value_get_string(v);
        }
    }
    g_ptr_array_free(keys, TRUE);
    return best ? g_strdup(best) : NULL;
}

/* Material a mapa [sirka, vyska, meritko, posun x, posun y] tapety "priblizit" vuci monitoru */
static struct {
    cairo_surface_t *surface;
    double map[5];
    gboolean loaded;
} glass;

static void glass_load_path(const gchar *path, GdkRectangle geo)
{
    GdkPixbuf *pb;
    cairo_surface_t *surface;
    cairo_t *cr;
    int pw, ph;
    double mw, mh, sc;
    if (glass.surface) {
        cairo_surface_destroy(glass.surface);
        glass.surface = NULL;
    }
    if (path == NULL || !g_file_test(path, G_FILE_TEST_EXISTS))
        return;
    pb = gdk_pixbuf_new_from_file_at_scale(path, GLASS_SIZE, GLASS_SIZE, TRUE, NULL);
    if (pb == NULL)
        return;
    pw = gdk_pixbuf_get_width(pb);
    ph = gdk_pixbuf_get_height(pb);
    surface = cairo_image_surface_create(CAIRO_FORMAT_RGB24, pw, ph);
    cr = cairo_create(surface);
    cairo_set_source_rgb(cr, 0.15, 0.17, 0.21);
    cairo_paint(cr);
    gdk_cairo_set_source_pixbuf(cr, pb, 0, 0);
    cairo_paint(cr);
    cairo_destroy(cr);
    g_object_unref(pb);
    mw = (double)MAX(1, geo.width);
    mh = (double)MAX(1, geo.height);
    sc = fmin((double)pw / mw, (double)ph / mh);
    glass.surface = glass_surface(surface, pw, ph);
    glass.map[0] = pw;
    glass.map[1] = ph;
    glass.map[2] = sc;
    glass.map[3] = ((double)pw - mw * sc) / 2.0 - (double)geo.x * sc;
    glass.map[4] = ((double)ph - mh * sc) / 2.0 - (double)geo.y * sc;
}

/* Karta skla (x, y, w, h v souradnicich cr; screen_x/y = jeji roh na obrazovce) pod uz nakreslene
 * pixely (DEST_OVER). ink: -1 = podle tapety (widgety), 0 = bily text, 1 = tmavy text.
 * Vraci, zda je sklo svetle (tmavy text). */
static gboolean glass_paint(cairo_t *cr, double x, double y, double w, double h, double radius,
                            double screen_x, double screen_y, int ink)
{
    double *m = glass.map, sx, sy, veil, v;
    gboolean light;
    GlassStats st;
    cairo_pattern_t *sheen;
    /* Polovicni pixel navic drzi bilinearni filtr uvnitr obrazku i na hrane monitoru */
    sx = glass_clamp(m[3] + screen_x * m[2], 0.5, m[0] - 0.5 - w * m[2]);
    sy = glass_clamp(m[4] + screen_y * m[2], 0.5, m[1] - 0.5 - h * m[2]);
    st = glass_stats(glass.surface, sx, sy, w * m[2], h * m[2]);
    light = ink < 0 ? st.mean >= 0.56 : ink == 1;
    veil = glass_veil(st, light);
    /* vrstvy se skladaji do skupiny (sklo shora dolu jako u widgetu), pak cela pod obsah okna */
    cairo_save(cr);
    cairo_new_path(cr);
    radius = fmin(radius, fmin(w, h) / 2.0);
    if (radius > 0.0) {
        cairo_arc(cr, x + w - radius, y + radius, radius, -G_PI / 2.0, 0);
        cairo_arc(cr, x + w - radius, y + h - radius, radius, 0, G_PI / 2.0);
        cairo_arc(cr, x + radius, y + h - radius, radius, G_PI / 2.0, G_PI);
        cairo_arc(cr, x + radius, y + radius, radius, G_PI, 3.0 * G_PI / 2.0);
        cairo_close_path(cr);
    } else {
        cairo_rectangle(cr, x, y, w, h);
    }
    cairo_clip(cr);
    cairo_push_group(cr);
    cairo_set_source_rgba(cr, 0.92, 0.94, 0.98, 0.86);
    cairo_paint(cr);
    cairo_save(cr);
    cairo_translate(cr, x, y);
    cairo_scale(cr, 1.0 / m[2], 1.0 / m[2]);
    cairo_set_source_surface(cr, glass.surface, -sx, -sy);
    cairo_paint(cr);
    cairo_restore(cr);
    v = light ? 1.0 : 0.0;
    cairo_set_source_rgba(cr, v, v, v, veil);
    cairo_paint(cr);
    sheen = cairo_pattern_create_linear(x, y, x + w * 0.35, y + h);
    cairo_pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, 0.08);
    cairo_pattern_add_color_stop_rgba(sheen, 1.0, 1.0, 1.0, 1.0, 0.0);
    cairo_set_source(cr, sheen);
    cairo_paint(cr);
    cairo_pattern_destroy(sheen);
    cairo_pop_group_to_source(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_DEST_OVER);
    cairo_paint(cr);
    cairo_restore(cr);
    return light;
}
