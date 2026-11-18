/*
 * LuxOS - GTK modul: oznameni (xfce4-notifyd) a nabidka aplikaci v liste (Whisker Menu) z matneho skla
 * jako widgety na plose (luxos-widgets) a horni lista.
 *
 * Material je prepis files/lsl/luxos-widgets.lsl se stejnymi cisly (test tests/test_luxos_glass_module.py
 * porovnava vysledky s LSL):
 *   glass_surface   tapeta 96 px, dva pruchody filtru 1-4-6-4-1, mirna desaturace a mlecny zavoj
 *   glass_style     svetle/tmave sklo a sila zavoje podle vyrezu tapety pod kartou
 *   wallpaper_path  tapeta z xfconf (xfce4-desktop), vestaveny displej ma prednost pred HDMI
 *   on_card_draw    podklad, vyrez tapety, zavoj, odlesk
 * X11/xfwm4 rozmazani pod oknem neumi, proto se kresli vyrez tapety pod oknem (bez snimani obrazovky).
 *
 * Sklo se kresli az po vlastnim kresleni okna operatorem DEST_OVER - tedy POD pozadi a obsah, ktere
 * program uz nakreslil. CSS motivu (luxos-themes) pro okna se tridou luxos-glass pozadi zpruhledni
 * a nastavi okraj karty jako u widgetu:
 *   Oznameni  barva textu jako widgety: ve svetlem rezimu podle tapety (trida luxos-glass-light =
 *             tmavy text), v tmavem rezimu (motiv GTK *-Dark) vzdy tmave sklo s bilym textem;
 *             pri vyjizdeni do boku (slideout) jede sklo s obsahem: posun se meri na potomkovi okna
 *             (GTK mu kresleni posune o vyjeti i o jeho misto v okne)
 *   Nabidky   (Whisker Menu i vyskakovaci nabidky listy - rozlozeni klavesnice, prave tlacitko na pluginu)
 *             barva textu podle motivu (svetly text = tmave sklo) - nabidky maji mnoho prvku barvenych motivem;
 *             zavoj se dopocita tak, aby text motivu mel na tapete dost kontrastu (vzorec widgetu);
 *             podklad je skutecna obrazovka pod nabidkou (snimek pri otevreni, stejne zmenseni a rozostreni
 *             jako tapeta) - s MENU_GLASS=wallpaper v ~/.config/luxos/appearance.conf zase tapeta
 * Bez kompozitoru, bez tapety nebo na Waylandu modul nic nekresli a okna zustanou podle motivu.
 *
 * Klik v liste: levym tlacitkem na ikonu zvuku (xfce4-pulseaudio-plugin) a zvonku (notification-plugin)
 * se misto nabidek Xfce otevre okno LuxOS "luxos-bar-popup sound|notifications" (luxos_bar_popups.lsl).
 * Zvuku zustane vse ostatni (klavesy hlasitosti, ukazatel, kolecko, prostredni tlacitko = ztlumit),
 * zvonku ikona s teckou neprectenych; prostredni tlacitko na zvonku prepne Nerusit, prave = nabidka listy.
 *
 * Systray v liste: ikona nm-applet je skryta (Wi-Fi ma vlastni ikonu a okno LuxOS); kdyz systray
 * neskryva nic jineho, nema ani sipku pro rozbaleni skrytych ikon (jinak by po rozbaleni byla Wi-Fi dvakrat).
 *
 * S LUXOS_GLASS_MATERIAL_ONLY jen material (bez modulu): vklada si ho plugin listy luxos-bar.c
 * a test tests/test_luxos_glass_module.py.
 *
 * Nacita se pres GTK_MODULES: lista (override-bin/xfce4-panel, externi pluginy promennou zdedi)
 * a xfce4-notifyd (drop-in systemd xfce4-notifyd.service.d/20-luxos-glass.conf); jinde nedela nic.
 */
#include <gtk/gtk.h>
#include <math.h>
#include <string.h>
#ifndef LUXOS_GLASS_MATERIAL_ONLY
#include <gdk/gdkx.h>
#include <xfconf/xfconf.h>
#endif

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

#ifndef LUXOS_GLASS_MATERIAL_ONLY

enum { KIND_NOTIFY = 1, KIND_MENU = 2, KIND_POPUP = 3 };

static void glass_reload(void)
{
    XfconfChannel *channel = xfconf_channel_get("xfce4-desktop");
    GHashTable *props = xfconf_channel_get_properties(channel, "/backdrop");
    gchar *path = glass_wallpaper_path(props);
    GdkMonitor *monitor = gdk_display_get_monitor(gdk_display_get_default(), 0);
    GList *wins, *l;
    if (monitor) {
        GdkRectangle geo;
        gdk_monitor_get_geometry(monitor, &geo);
        glass_load_path(path, geo);
    }
    g_free(path);
    if (props)
        g_hash_table_destroy(props);
    wins = gtk_window_list_toplevels();
    for (l = wins; l; l = l->next)
        gtk_widget_queue_draw(GTK_WIDGET(l->data));
    g_list_free(wins);
}

static gboolean glass_reload_once(gpointer data)
{
    (void)data;
    glass_reload();
    return G_SOURCE_REMOVE;
}

/* Nova tapeta: prekreslit (s odstupem, xfdesktop meni vic vlastnosti najednou) */
static void on_desktop_changed(XfconfChannel *channel, const gchar *property, const GValue *value, gpointer data)
{
    (void)channel; (void)value; (void)data;
    if (g_str_has_suffix(property, "last-image"))
        g_timeout_add(300, glass_reload_once, NULL);
}

static void glass_ensure(void)
{
    GError *error = NULL;
    if (glass.loaded)
        return;
    glass.loaded = TRUE;
    if (!xfconf_init(&error)) {
        g_clear_error(&error);
        return;
    }
    g_signal_connect(xfconf_channel_get("xfce4-desktop"), "property-changed", G_CALLBACK(on_desktop_changed), NULL);
    glass_reload();
}

static void set_class(GtkWidget *widget, const char *name, gboolean on)
{
    GtkStyleContext *context = gtk_widget_get_style_context(widget);
    if (on && !gtk_style_context_has_class(context, name))
        gtk_style_context_add_class(context, name);
    else if (!on && gtk_style_context_has_class(context, name))
        gtk_style_context_remove_class(context, name);
}

/* Tmavy rezim systemu: luxos-appearance prepina motiv GTK (WhiteSur-Light/Dark) a prefer-dark */
static gboolean settings_dark(GtkWidget *widget)
{
    GtkSettings *settings = gtk_widget_get_settings(widget);
    gchar *name = NULL, *lower;
    gboolean prefer = FALSE, dark;
    g_object_get(settings, "gtk-theme-name", &name, "gtk-application-prefer-dark-theme", &prefer, NULL);
    lower = name ? g_ascii_strdown(name, -1) : NULL;
    dark = prefer || (lower && strstr(lower, "dark"));
    g_free(lower);
    g_free(name);
    return dark;
}

/* Tmavy motiv = svetly text motivu (spolehlive i s GTK_THEME nebo motivem bez "dark" v nazvu) */
static gboolean theme_is_dark(GtkWidget *widget)
{
    GtkStyleContext *context = gtk_widget_get_style_context(widget);
    GdkRGBA fg;
    gtk_style_context_get_color(context, gtk_style_context_get_state(context), &fg);
    return 0.2126 * fg.red + 0.7152 * fg.green + 0.0722 * fg.blue > 0.5;
}

/* Pred kreslenim okna: matice cairo, aby slo zjistit posun, ktery okno pri kresleni prida */
static gboolean on_draw_before(GtkWidget *widget, cairo_t *cr, gpointer data)
{
    cairo_matrix_t *before = g_object_get_data(G_OBJECT(widget), "luxos-glass-matrix");
    if (before)
        cairo_get_matrix(cr, before);
    /* Oznameni: notifyd okno "vycisti" cairo_fill bez cesty (nic neudela), takze pri vyjizdeni do boku
       by v okne zustalo sklo z predchozich snimku (DEST_OVER pod nej uz nekresli) - vycistit doopravdy */
    if (GPOINTER_TO_INT(data) == KIND_NOTIFY && glass.surface
        && gdk_screen_is_composited(gtk_widget_get_screen(widget))) {
        cairo_save(cr);
        cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
        cairo_paint(cr);
        cairo_restore(cr);
    }
    return FALSE;
}

/* Kresleni potomka okna oznameni: matice obsahuje posun pri vyjizdeni + misto potomka v okne */
static gboolean on_child_draw(GtkWidget *child, cairo_t *cr, gpointer data)
{
    cairo_matrix_t *m = data;
    (void)child;
    cairo_get_matrix(cr, m);
    m->xy = 1.0;                         /* znacka: potomek se v tomto snimku kreslil */
    return FALSE;
}

static gboolean menu_glass_paint(GtkWidget *widget, cairo_t *cr, double x, double y, double w, double h,
                                 double radius, double screen_x, double screen_y, int ink);

static gboolean on_draw_after(GtkWidget *widget, cairo_t *cr, gpointer data)
{
    int kind = GPOINTER_TO_INT(data);
    cairo_matrix_t *before = g_object_get_data(G_OBJECT(widget), "luxos-glass-matrix");
    gboolean on = FALSE;
    GtkAllocation a;
    gint wx = 0, wy = 0;
    glass_ensure();
    gtk_widget_get_allocation(widget, &a);
    gtk_window_get_position(GTK_WINDOW(widget), &wx, &wy);
    if (glass.surface && gdk_screen_is_composited(gtk_widget_get_screen(widget))) {
        if (kind == KIND_NOTIFY) {
            /* notifyd posune kresleni (vyjizdeni) cairo_translate a neobnovi ho: rozdil oproti
               stavu pred kreslenim je posun karty v okne */
            double dx = 0.0, dy = 0.0, radius = 0.0;
            gint border_radius = 0;
            GtkStyleContext *context = gtk_widget_get_style_context(widget);
            cairo_matrix_t *child_m = g_object_get_data(G_OBJECT(widget), "luxos-glass-child");
            GtkWidget *child = gtk_bin_get_child(GTK_BIN(widget));
            double px = 0.0, py = 0.0;
            if (before && child_m && child && child_m->xy == 1.0 && before->xx != 0.0 && before->yy != 0.0) {
                GtkAllocation ca;
                cairo_matrix_t now;
                gtk_widget_get_allocation(child, &ca);
                dx = (child_m->x0 - before->x0) / before->xx - (ca.x - a.x);
                dy = (child_m->y0 - before->y0) / before->yy - (ca.y - a.y);
                /* posun, ktery v cr po kresleni okna jeste plati (GTK ho muze vratit) - zbytek pridat */
                cairo_get_matrix(cr, &now);
                px = dx - (now.x0 - before->x0) / before->xx;
                py = dy - (now.y0 - before->y0) / before->yy;
                child_m->xy = 0.0;
            }
            gtk_style_context_get(context, gtk_style_context_get_state(context),
                                  GTK_STYLE_PROPERTY_BORDER_RADIUS, &border_radius, NULL);
            radius = border_radius;
            set_class(widget, "luxos-glass-light",
                      glass_paint(cr, a.x + px, a.y + py, a.width, a.height, radius, wx + dx, wy + dy,
                                  settings_dark(widget) ? 0 : -1));
            on = TRUE;
        } else if (kind == KIND_POPUP) {
            /* vyskakovaci nabidka GTK: sklo pod nabidkou se zaoblenim z CSS (luxos.css: 12px) */
            GtkWidget *menu = gtk_bin_get_child(GTK_BIN(widget));
            if (menu && gtk_widget_get_visible(menu)) {
                GtkAllocation m;
                GtkStyleContext *mc = gtk_widget_get_style_context(menu);
                gint border_radius = 0;
                gboolean dark = theme_is_dark(menu);
                gtk_widget_get_allocation(menu, &m);
                gtk_style_context_get(mc, gtk_style_context_get_state(mc),
                                      GTK_STYLE_PROPERTY_BORDER_RADIUS, &border_radius, NULL);
                menu_glass_paint(widget, cr, m.x, m.y, m.width, m.height, border_radius, wx + m.x, wy + m.y,
                                 dark ? 0 : 1);
                set_class(widget, "luxos-glass-light", !dark);
                on = TRUE;
            }
        } else {
            GtkWidget *frame = gtk_bin_get_child(GTK_BIN(widget));
            if (frame && gtk_widget_get_visible(frame)) {
                GtkAllocation f;
                gboolean dark = theme_is_dark(widget);
                gtk_widget_get_allocation(frame, &f);
                menu_glass_paint(widget, cr, f.x + MENU_MARGIN, f.y + MENU_MARGIN, f.width - 2 * MENU_MARGIN,
                                 f.height - 2 * MENU_MARGIN, MENU_RADIUS,
                                 wx + f.x + MENU_MARGIN, wy + f.y + MENU_MARGIN, dark ? 0 : 1);
                set_class(widget, "luxos-glass-light", !dark);
                on = TRUE;
            }
        }
    }
    /* trida az po prvnim skle: do te doby (a bez tapety) zustane pozadi motivu */
    set_class(widget, "luxos-glass", on);
    return FALSE;
}

/* ---- nabidky: sklo z obrazovky pod nimi ----------------------------------------------- */

/* Podklad nabidky: rozostreny snimek obrazovky a jeho mapa (jako glass.surface a glass.map) */
typedef struct {
    cairo_surface_t *surface;
    double map[5];
} Backdrop;

static void backdrop_free(gpointer data)
{
    Backdrop *b = data;
    if (b->surface)
        cairo_surface_destroy(b->surface);
    g_free(b);
}

/* MENU_GLASS z ~/.config/luxos/appearance.conf: "wallpaper" = tapeta, jinak obrazovka pod nabidkou.
   Cte se pri kazdem otevreni - zmena plati hned. */
static gboolean menu_glass_from_screen(void)
{
    gchar *path = g_build_filename(g_get_user_config_dir(), "luxos", "appearance.conf", NULL);
    gchar *text = NULL;
    gboolean screen = TRUE;
    if (g_file_get_contents(path, &text, NULL, NULL)) {
        gchar **lines = g_strsplit(text, "\n", -1);
        for (gchar **l = lines; *l; l++) {
            gchar *line = g_strstrip(*l);
            if (g_str_has_prefix(line, "MENU_GLASS="))
                screen = g_strcmp0(g_strstrip(line + 11), "wallpaper") != 0;
        }
        g_strfreev(lines);
    }
    g_free(text);
    g_free(path);
    return screen;
}

#define BACKDROP_MARGIN 64      /* okoli navic, aby rozostreni na okraji nabidky melo z ceho brat */

/* Pri zobrazeni nabidky (okno uz je namapovane, ale jeste nic nenakreslilo): snimek obrazovky pod ni.
   Bez kompozitoru nebo s MENU_GLASS=wallpaper zadny podklad - kresli se tapeta. */
static void on_menu_map(GtkWidget *widget, gpointer data)
{
    GdkScreen *screen = gtk_widget_get_screen(widget);
    GdkWindow *root = gdk_screen_get_root_window(screen);
    GdkMonitor *monitor;
    GdkRectangle geo;
    GtkAllocation a;
    gint wx = 0, wy = 0, x0, y0, x1, y1, pw, ph;
    double sc;
    GdkPixbuf *shot;
    cairo_surface_t *small;
    cairo_t *cr;
    Backdrop *b;
    (void)data;
    g_object_set_data(G_OBJECT(widget), "luxos-glass-backdrop", NULL);
    if (!gdk_screen_is_composited(screen) || !menu_glass_from_screen())
        return;
    gtk_window_get_position(GTK_WINDOW(widget), &wx, &wy);
    gtk_widget_get_allocation(widget, &a);
    monitor = gdk_display_get_monitor_at_point(gtk_widget_get_display(widget), wx + a.width / 2, wy + a.height / 2);
    if (!monitor)
        return;
    gdk_monitor_get_geometry(monitor, &geo);
    x0 = MAX(geo.x, wx - BACKDROP_MARGIN);
    y0 = MAX(geo.y, wy - BACKDROP_MARGIN);
    x1 = MIN(geo.x + geo.width, wx + a.width + BACKDROP_MARGIN);
    y1 = MIN(geo.y + geo.height, wy + a.height + BACKDROP_MARGIN);
    if (x1 - x0 < 8 || y1 - y0 < 8)
        return;
    shot = gdk_pixbuf_get_from_window(root, x0, y0, x1 - x0, y1 - y0);
    if (!shot)
        return;
    /* stejne zmenseni jako tapeta (GLASS_SIZE px na delsi stranu monitoru) = stejne rozostreni */
    sc = (double)GLASS_SIZE / (double)MAX(geo.width, geo.height);
    pw = MAX(4, (int)ceil((x1 - x0) * sc));
    ph = MAX(4, (int)ceil((y1 - y0) * sc));
    small = cairo_image_surface_create(CAIRO_FORMAT_RGB24, pw, ph);
    cr = cairo_create(small);
    cairo_scale(cr, (double)pw / (x1 - x0), (double)ph / (y1 - y0));
    gdk_cairo_set_source_pixbuf(cr, shot, 0, 0);
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_GOOD);
    cairo_paint(cr);
    cairo_destroy(cr);
    g_object_unref(shot);
    b = g_new0(Backdrop, 1);
    b->surface = glass_surface(small, pw, ph);
    b->map[0] = pw;
    b->map[1] = ph;
    b->map[2] = (double)pw / (x1 - x0);
    b->map[3] = -x0 * b->map[2];
    b->map[4] = -y0 * b->map[2];
    g_object_set_data_full(G_OBJECT(widget), "luxos-glass-backdrop", b, backdrop_free);
}

/* glass_paint nad podkladem nabidky (je-li), jinak nad tapetou */
static gboolean menu_glass_paint(GtkWidget *widget, cairo_t *cr, double x, double y, double w, double h,
                                 double radius, double screen_x, double screen_y, int ink)
{
    Backdrop *b = g_object_get_data(G_OBJECT(widget), "luxos-glass-backdrop");
    cairo_surface_t *surface = glass.surface;
    double map[5];
    gboolean light;
    if (!b)
        return glass_paint(cr, x, y, w, h, radius, screen_x, screen_y, ink);
    memcpy(map, glass.map, sizeof map);
    glass.surface = b->surface;
    memcpy(glass.map, b->map, sizeof map);
    light = glass_paint(cr, x, y, w, h, radius, screen_x, screen_y, ink);
    glass.surface = surface;
    memcpy(glass.map, map, sizeof map);
    return light;
}

/* Okno se presunulo (prerovnani oznameni, nabidka u jineho tlacitka): jiny vyrez tapety */
static gboolean on_configure(GtkWidget *widget, GdkEvent *event, gpointer data)
{
    (void)event; (void)data;
    gtk_widget_queue_draw(widget);
    return FALSE;
}

static void attach(GtkWidget *window, int kind)
{
    if (g_object_get_data(G_OBJECT(window), "luxos-glass-matrix"))
        return;
    g_object_set_data_full(G_OBJECT(window), "luxos-glass-matrix", g_new0(cairo_matrix_t, 1), g_free);
    g_signal_connect(window, "draw", G_CALLBACK(on_draw_before), GINT_TO_POINTER(kind));
    g_signal_connect_after(window, "draw", G_CALLBACK(on_draw_after), GINT_TO_POINTER(kind));
    if (kind == KIND_NOTIFY) {
        GtkWidget *child = gtk_bin_get_child(GTK_BIN(window));
        if (child) {
            cairo_matrix_t *m = g_new0(cairo_matrix_t, 1);
            g_object_set_data_full(G_OBJECT(window), "luxos-glass-child", m, g_free);
            g_signal_connect(child, "draw", G_CALLBACK(on_child_draw), m);
        }
    }
    g_signal_connect(window, "configure-event", G_CALLBACK(on_configure), NULL);
    if (kind == KIND_MENU || kind == KIND_POPUP)
        g_signal_connect_after(window, "map", G_CALLBACK(on_menu_map), NULL);
}

/* ---- klik na ikonu v liste ------------------------------------------------------------- */

/* Program oken listy: LUXOS_BAR_POPUP, jinak z PATH, jinak ~/.local/bin (lista spustena sezenim
   tuto slozku v PATH mit nemusi) */
static gchar *popup_program(void)
{
    const char *cmd = g_getenv("LUXOS_BAR_POPUP");
    gchar *path, *local;
    if (cmd && *cmd)
        return g_strdup(cmd);
    path = g_find_program_in_path("luxos-bar-popup");
    if (path)
        return path;
    local = g_build_filename(g_get_home_dir(), ".local", "bin", "luxos-bar-popup", NULL);
    if (g_file_test(local, G_FILE_TEST_IS_EXECUTABLE))
        return local;
    g_free(local);
    return g_strdup("/usr/bin/luxos-bar-popup");
}

static void spawn_popup(const char *kind)
{
    gchar *program = popup_program();
    gchar *argv[] = { program, (gchar *)kind, NULL };
    GError *error = NULL;
    if (!g_spawn_async(NULL, argv, NULL, G_SPAWN_DEFAULT, NULL, NULL, NULL, &error)) {
        g_warning("luxos-glass: %s", error->message);
        g_clear_error(&error);
    }
    g_free(program);
}

static gboolean on_bar_press(GtkWidget *widget, GdkEventButton *event, gpointer data)
{
    const char *kind = data;
    (void)widget;
    if (event->type != GDK_BUTTON_PRESS)
        return event->button == 1;
    if (event->button == 1) {
        spawn_popup(kind);
        return TRUE;
    }
    /* zvonek: prostredni tlacitko prepne Nerusit (jako puvodni plugin) */
    if (event->button == 2 && strcmp(kind, "notifications") == 0) {
        GError *error = NULL;
        if (xfconf_init(&error)) {
            XfconfChannel *ch = xfconf_channel_get("xfce4-notifyd");
            xfconf_channel_set_bool(ch, "/do-not-disturb", !xfconf_channel_get_bool(ch, "/do-not-disturb", FALSE));
        }
        g_clear_error(&error);
        return TRUE;
    }
    return FALSE;
}

/* Proces externiho pluginu listy (wrapper-2.0) s danou knihovnou */
static gboolean plugin_process(const char *library)
{
    gchar *cmdline = NULL;
    gsize len = 0;
    gboolean found = FALSE;
    if (g_file_get_contents("/proc/self/cmdline", &cmdline, &len, NULL)) {
        for (gsize i = 0; i < len; i += strlen(cmdline + i) + 1)
            if (g_str_has_suffix(cmdline + i, library))
                found = TRUE;
    }
    g_free(cmdline);
    return found;
}

/* Tlacitko pluginu: zvuk ma vlastni typ PulseaudioButton (klik obslouzi tridni metoda, nase obsluha
 * instance ji predbehne); zvonek je obycejne prepinaci tlacitko primo v XfcePanelPlugin a klik obsluhuje
 * jeho vlastni obsluha signalu - ta se zablokuje. */
static void attach_bar_button(GtkWidget *w)
{
    static GType plugin_type;
    GtkWidget *parent;
    if (g_object_get_data(G_OBJECT(w), "luxos-bar-popup"))
        return;
    if (g_strcmp0(G_OBJECT_TYPE_NAME(w), "PulseaudioButton") == 0) {
        g_object_set_data(G_OBJECT(w), "luxos-bar-popup", (gpointer)"sound");
        g_signal_connect(w, "button-press-event", G_CALLBACK(on_bar_press), (gpointer)"sound");
        return;
    }
    if (!plugin_type)
        plugin_type = g_type_from_name("XfcePanelPlugin");
    parent = gtk_widget_get_parent(w);
    if (!plugin_type || !parent || !g_type_is_a(G_OBJECT_TYPE(parent), plugin_type)
        || !plugin_process("libnotification-plugin.so"))
        return;
    g_object_set_data(G_OBJECT(w), "luxos-bar-popup", (gpointer)"notifications");
    g_signal_handlers_block_matched(w, G_SIGNAL_MATCH_ID, g_signal_lookup("button-press-event", GTK_TYPE_WIDGET),
                                    0, NULL, NULL, NULL);
    g_signal_connect(w, "button-press-event", G_CALLBACK(on_bar_press), (gpointer)"notifications");
}

/* ---- systray: bez sipky, kdyz je skryta jen ikona nm-applet ---------------------------- */

static GtkWidget *ancestor_of_type(GtkWidget *w, const char *type_name)
{
    GType type = g_type_from_name(type_name);
    for (; w; w = gtk_widget_get_parent(w))
        if (type && g_type_is_a(G_OBJECT_TYPE(w), type))
            return w;
    return NULL;
}

/* Skryva systray neco jineho nez nm-applet? (vlastnosti pluginu hidden-items, hidden-legacy-items) */
static gboolean systray_arrow_needed(GtkWidget *button)
{
    GtkWidget *plugin = ancestor_of_type(button, "XfcePanelPlugin");
    gint id = -1;
    gchar *prop;
    gchar **items;
    gboolean needed = FALSE;
    GError *error = NULL;
    if (!plugin || !xfconf_init(&error)) {
        g_clear_error(&error);
        return TRUE;
    }
    g_object_get(plugin, "unique-id", &id, NULL);
    prop = g_strdup_printf("/plugins/plugin-%d/hidden-items", id);
    items = xfconf_channel_get_string_list(xfconf_channel_get("xfce4-panel"), prop);
    for (gchar **i = items; i && *i; i++)
        if (strcmp(*i, "nm-applet") != 0)
            needed = TRUE;
    g_strfreev(items);
    g_free(prop);
    prop = g_strdup_printf("/plugins/plugin-%d/hidden-legacy-items", id);
    items = xfconf_channel_get_string_list(xfconf_channel_get("xfce4-panel"), prop);
    if (items && items[0])
        needed = TRUE;
    g_strfreev(items);
    g_free(prop);
    return needed;
}

static void on_arrow_visible(GObject *button, GParamSpec *pspec, gpointer data)
{
    (void)pspec; (void)data;
    if (gtk_widget_get_visible(GTK_WIDGET(button)) && !systray_arrow_needed(GTK_WIDGET(button)))
        gtk_widget_hide(GTK_WIDGET(button));
}

static void attach_systray_arrow(GtkWidget *w)
{
    if (g_object_get_data(G_OBJECT(w), "luxos-systray-arrow") || !ancestor_of_type(w, "XfceSnPlugin"))
        return;
    g_object_set_data(G_OBJECT(w), "luxos-systray-arrow", w);
    g_signal_connect(w, "notify::visible", G_CALLBACK(on_arrow_visible), NULL);
    on_arrow_visible(G_OBJECT(w), NULL, NULL);
}

/* "realize": okno oznameni (XfceNotifyWindow) nebo nabidky (GtkWindow jmenem whiskermenu-window) */
static gboolean on_realize(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GtkWidget *w = g_value_get_object(&params[0]);
    (void)hint; (void)n; (void)data;
    if (GTK_IS_TOGGLE_BUTTON(w) && strncmp(g_get_prgname() ? g_get_prgname() : "", "wrapper-", 8) == 0) {
        attach_bar_button(w);
        return TRUE;
    }
    if (g_strcmp0(G_OBJECT_TYPE_NAME(w), "XfceArrowButton") == 0) {
        attach_systray_arrow(w);
        return TRUE;
    }
    if (!GTK_IS_WINDOW(w) || !GDK_IS_X11_DISPLAY(gtk_widget_get_display(w)))
        return TRUE;
    if (g_strcmp0(G_OBJECT_TYPE_NAME(w), "XfceNotifyWindow") == 0)
        attach(w, KIND_NOTIFY);
    else if (g_strcmp0(gtk_widget_get_name(w), "whiskermenu-window") == 0)
        attach(w, KIND_MENU);
    else if (gtk_window_get_window_type(GTK_WINDOW(w)) == GTK_WINDOW_POPUP && GTK_IS_MENU(gtk_bin_get_child(GTK_BIN(w)))
             && g_strcmp0(g_get_prgname(), "xfce4-notifyd") != 0)
        attach(w, KIND_POPUP);
    return TRUE;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    const char *name = g_get_prgname();
    (void)argc; (void)argv;
    if (!name || (strcmp(name, "xfce4-notifyd") && strcmp(name, "xfce4-panel") && strncmp(name, "wrapper-", 8)
                  && strncmp(name, "panel-", 6)))
        return;
    g_type_class_ref(GTK_TYPE_WINDOW);
    g_signal_add_emission_hook(g_signal_lookup("realize", GTK_TYPE_WIDGET), 0, on_realize, NULL, NULL);
}

#endif
