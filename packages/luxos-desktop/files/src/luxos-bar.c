/*
 * luxos-bar - plugin horni listy (bezi v procesu xfce4-panel), nahrazuje rozpinaci oddelovac
 * mezi levou a pravou casti listy.
 *
 * 1. Hodiny uprostred listy (BAR_CLOCK=center v ~/.config/luxos/appearance.conf): text se kresli
 *    na stred celeho okna listy, ne na stred pluginu - leva a prava cast listy jsou ruzne siroke
 *    (nazev aplikace se meni), rozpinaci oddelovace po stranach by hodiny posouvaly. Stejny format
 *    jako luxos-clock, klik = Kalendar. Hodiny vpravo (genmon s prikazem luxos-clock) se pritom
 *    skryji, s BAR_CLOCK=right se zase ukazou.
 *
 * 2. Neprustupna lista pod okny (jen s BAR_COVER=solid, vychozi je lista vzdy pruhledna
 *    a pod ni prosvita tapeta): kdyz nejake okno na aktualni plose zasahuje pod listu nebo se
 *    jí dotyka (maximalizovane okno, celoobrazovkova aplikace v pozadi pod mensim oknem), lista
 *    prepne pozadi na plne neprusvitne - jinak by pres pruhlednou listu prosvital obsah okna.
 *    Pruhlednost bez oken je BAR_OPACITY (nastaveni Plocha a Dock, vychozi 62 %). Plugin nastavuje
 *    vlastnost background-rgba okna panelu - panel ji sam preda i externim pluginum (kazdy bezi ve
 *    vlastnim procesu, CSS pluginu by k nim nedoslo). Barva podle /panels/dark-mode jako
 *    luxos-appearance; s bilym pismem ve svetlem rezimu (BAR_TEXT=white) je lista tmave
 *    zakourena (bez oken slabsi pruhlednost, pod oknem neprusvitna) - na svetle liste by bile
 *    pismo nebylo citelne.
 *
 * Zmeny appearance.conf se nacitaji hned (GFileMonitor), bez restartu panelu.
 */
#define WNCK_I_KNOW_THIS_IS_UNSTABLE
#include <gtk/gtk.h>
#include <libwnck/libwnck.h>
#include <libxfce4panel/libxfce4panel.h>
#include <xfconf/xfconf.h>
#include <glib/gstdio.h>
#include <math.h>
#include <string.h>
#include <time.h>

#define DEFAULT_OPACITY 62
enum { COVER_WALLPAPER, COVER_TRANSLUCENT, COVER_SOLID };
#define CLOCK_FORMAT "%a %-d. %b  %H:%M"
#define TOOLTIP_FORMAT "%A %-d. %B %Y"

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *area;
    GtkWidget *toplevel;
    WnckHandle *handle;
    WnckScreen *screen;
    GFileMonitor *monitor;
    gchar *conf_path;
    gboolean center;            /* BAR_CLOCK=center */
    gint opacity;               /* BAR_OPACITY 0-100 */
    gboolean white;             /* BAR_TEXT=white */
    gint cover;                 /* BAR_COVER: COVER_WALLPAPER (vychozi), _TRANSLUCENT, _SOLID */
    gchar *bg_key;              /* naposledy vykreslena tapeta (zdroj, rozmery, ton) */
    gchar *bg_file;             /* obrazek pozadi listy v ~/.cache/luxos */
    gboolean setting_bg;
    guint bg_id;                /* odlozene prekresleni tapety */
    gboolean covered;           /* okno pod listou / na ni */
    gboolean hover;
    gchar *text;                /* zobrazeny cas */
    GdkRectangle hit;           /* oblast textu v souradnicich pluginu (klik, hover) */
    guint tick_id;
    guint eval_id;
    gulong rgba_handler;
    gboolean setting_rgba;
} Bar;

/* ---- nastaveni ------------------------------------------------------------------------- */
static void
read_conf (Bar *bar) {
    gchar *data = NULL;
    bar->center = FALSE;
    bar->opacity = DEFAULT_OPACITY;
    bar->white = FALSE;
    bar->cover = COVER_WALLPAPER;
    if (!g_file_get_contents (bar->conf_path, &data, NULL, NULL))
        return;
    gchar **lines = g_strsplit (data, "\n", -1);
    for (gchar **l = lines; *l; l++) {
        gchar *v = strchr (*l, '=');
        if (!v)
            continue;
        *v++ = '\0';
        g_strstrip (*l);
        g_strstrip (v);
        if (strcmp (*l, "BAR_CLOCK") == 0)
            bar->center = strcmp (v, "center") == 0;
        else if (strcmp (*l, "BAR_OPACITY") == 0 && *v)
            bar->opacity = CLAMP ((gint) g_ascii_strtoll (v, NULL, 10), 0, 100);
        else if (strcmp (*l, "BAR_TEXT") == 0)
            bar->white = strcmp (v, "white") == 0;
        else if (strcmp (*l, "BAR_COVER") == 0)
            bar->cover = strcmp (v, "solid") == 0 ? COVER_SOLID
                         : strcmp (v, "translucent") == 0 ? COVER_TRANSLUCENT : COVER_WALLPAPER;
    }
    g_strfreev (lines);
    g_free (data);
}

/* ---- hodiny vpravo (genmon s prikazem luxos-clock) ------------------------------------- */
static gboolean
is_clock_plugin (gint id) {
    XfconfChannel *ch = xfconf_channel_get ("xfce4-panel");
    gchar *prop = g_strdup_printf ("/plugins/plugin-%d/command", id);
    gchar *cmd = xfconf_channel_get_string (ch, prop, NULL);
    gboolean yes = cmd && g_str_has_prefix (g_strstrip (cmd), "luxos-clock");
    g_free (cmd);
    g_free (prop);
    return yes;
}

static void
sync_right_clock (Bar *bar) {
    GtkWidget *parent = gtk_widget_get_parent (GTK_WIDGET (bar->plugin));
    if (!GTK_IS_CONTAINER (parent))
        return;
    GList *kids = gtk_container_get_children (GTK_CONTAINER (parent));
    for (GList *k = kids; k; k = k->next) {
        if (!XFCE_IS_PANEL_PLUGIN (k->data) || k->data == (gpointer) bar->plugin)
            continue;
        if (!is_clock_plugin (xfce_panel_plugin_get_unique_id (k->data)))
            continue;
        gtk_widget_set_no_show_all (k->data, bar->center);
        gtk_widget_set_visible (k->data, !bar->center);
    }
    g_list_free (kids);
}

/* ---- pruhlednost listy ----------------------------------------------------------------- */
static void
apply_alpha (Bar *bar) {
    GdkRGBA *rgba = NULL;
    if (!bar->toplevel || !g_object_class_find_property (G_OBJECT_GET_CLASS (bar->toplevel), "background-rgba"))
        return;
    g_object_get (bar->toplevel, "background-rgba", &rgba, NULL);
    if (!rgba)
        return;
    /* barvy jako luxos-appearance apply() */
    gboolean dark = xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE);
    gboolean smoked = bar->white && !dark;
    GdkRGBA want = dark || smoked ? (GdkRGBA) { 0.09, 0.09, 0.12, 1 } : (GdkRGBA) { 0.96, 0.96, 0.97, 1 };
    want.alpha = bar->covered ? 1.0 : bar->opacity / 100.0 * (smoked ? 0.45 : 1.0);
    if (fabs (rgba->alpha - want.alpha) > 0.004 || fabs (rgba->red - want.red) > 0.004
        || fabs (rgba->green - want.green) > 0.004 || fabs (rgba->blue - want.blue) > 0.004) {
        *rgba = want;
        bar->setting_rgba = TRUE;
        g_object_set (bar->toplevel, "background-rgba", rgba, NULL);
        bar->setting_rgba = FALSE;
    }
    gdk_rgba_free (rgba);
}

/* ---- tapeta pod listou ----------------------------------------------------------------
 * Vychozi (BAR_COVER=wallpaper): lista neni skutecne pruhledna, plugin do ni nakresli vyrez
 * tapety, ktery na obrazovce lezi presne pod ni, s tonem listy (stejna barva a alfa jako
 * pruhledna lista). Vypada pruhledne nad tapetou, ale pres listu nikdy neprosvita okno
 * (celoobrazovkova aplikace v pozadi, okno posunute pod listu) a nikdy nezcerna. Panel dostane
 * obrazek jako background-image (styl 2) - preda ho i externim pluginum. */

static void
panel_set_uint (GObject *obj, const gchar *name, guint value) {
    GParamSpec *ps = g_object_class_find_property (G_OBJECT_GET_CLASS (obj), name);
    if (!ps)
        return;
    GValue from = G_VALUE_INIT, to = G_VALUE_INIT;
    g_value_init (&from, G_TYPE_UINT);
    g_value_set_uint (&from, value);
    g_value_init (&to, G_PARAM_SPEC_VALUE_TYPE (ps));
    if (g_value_transform (&from, &to))
        g_object_set_property (obj, name, &to);
    g_value_unset (&from);
    g_value_unset (&to);
}

static guint
panel_get_uint (GObject *obj, const gchar *name) {
    GParamSpec *ps = g_object_class_find_property (G_OBJECT_GET_CLASS (obj), name);
    if (!ps)
        return 0;
    GValue v = G_VALUE_INIT, out = G_VALUE_INIT;
    g_value_init (&v, G_PARAM_SPEC_VALUE_TYPE (ps));
    g_object_get_property (obj, name, &v);
    g_value_init (&out, G_TYPE_UINT);
    guint r = g_value_transform (&v, &out) ? g_value_get_uint (&out) : 0;
    g_value_unset (&v);
    g_value_unset (&out);
    return r;
}

/* Tapeta monitoru s listou na aktivni plose: cesta (g_free) a styl xfdesktop (image-style) */
static gchar *
wallpaper_for (Bar *bar, GdkMonitor *mon, gint *style) {
    XfconfChannel *ch = xfconf_channel_get ("xfce4-desktop");
    gint ws = 0;
    if (xfconf_channel_get_bool (ch, "/backdrop/single-workspace-mode", FALSE))
        ws = xfconf_channel_get_int (ch, "/backdrop/single-workspace-number", 0);
    else if (bar->screen && wnck_screen_get_active_workspace (bar->screen))
        ws = wnck_workspace_get_number (wnck_screen_get_active_workspace (bar->screen));
    const gchar *model = mon ? gdk_monitor_get_model (mon) : NULL;
    gchar *want = g_strdup_printf ("/workspace%d/last-image", ws);
    gchar *best = NULL;
    gint score = -1;
    GHashTable *props = xfconf_channel_get_properties (ch, "/backdrop");
    if (props) {
        GHashTableIter it;
        gpointer key;
        g_hash_table_iter_init (&it, props);
        while (g_hash_table_iter_next (&it, &key, NULL)) {
            const gchar *k = key;
            if (!g_str_has_suffix (k, "/last-image"))
                continue;
            /* 4 = monitor i plocha, 2 = monitor, 1 = plocha, 0 = jakakoli tapeta */
            gint sc = 0;
            gchar *mon_part = model ? g_strdup_printf ("/monitor%s/", model) : NULL;
            if (mon_part && strstr (k, mon_part))
                sc += 2;
            g_free (mon_part);
            if (g_str_has_suffix (k, want))
                sc += 1;
            if (sc > score || (sc == score && best && strcmp (k, best) < 0)) {
                g_free (best);
                best = g_strdup (k);
                score = sc;
            }
        }
        g_hash_table_destroy (props);
    }
    g_free (want);
    gchar *path = NULL;
    *style = 5;
    if (best) {
        path = xfconf_channel_get_string (ch, best, NULL);
        gchar *sp = g_strdup_printf ("%.*simage-style", (int) (strlen (best) - strlen ("last-image")), best);
        *style = xfconf_channel_get_int (ch, sp, 5);
        g_free (sp);
        g_free (best);
    }
    if (path && (!*path || !g_file_test (path, G_FILE_TEST_IS_REGULAR))) {
        g_free (path);
        path = NULL;
    }
    return path;
}

/* Barva a alfa tonu listy (jako apply_alpha bez okna pod listou) */
static void
bar_tint (Bar *bar, GdkRGBA *c) {
    gboolean dark = xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE);
    gboolean smoked = bar->white && !dark;
    *c = dark || smoked ? (GdkRGBA) { 0.09, 0.09, 0.12, 1 } : (GdkRGBA) { 0.96, 0.96, 0.97, 1 };
    c->alpha = bar->opacity / 100.0 * (smoked ? 0.45 : 1.0);
}

/* Alfa tonu, se kterou je text listy citelny: nejmene nastavena (BAR_OPACITY), na prilis svetle
 * (pod bilym textem) nebo prilis tmave (pod tmavym textem) tapete vic. Meri se 90. percentil jasu
 * vyrezu, aby rozhodovala svetla mista, ne prumer. */
#define READABLE_LIGHT_TEXT 0.58    /* nejvyssi jas pozadi pod bilym textem */
#define READABLE_DARK_TEXT 0.62     /* nejnizsi jas pozadi pod tmavym textem */
static gdouble
readable_alpha (GdkPixbuf *pb, const GdkRGBA *tint) {
    gint w = gdk_pixbuf_get_width (pb), h = gdk_pixbuf_get_height (pb);
    gint rs = gdk_pixbuf_get_rowstride (pb), n = gdk_pixbuf_get_n_channels (pb);
    const guchar *px = gdk_pixbuf_read_pixels (pb);
    guint hist[256] = { 0 };
    for (gint y = 0; y < h; y++)
        for (gint x = 0; x < w; x++) {
            const guchar *p = px + y * rs + x * n;
            hist[(p[0] * 54 + p[1] * 183 + p[2] * 19) >> 8]++;
        }
    gboolean light_text = 0.2126 * tint->red + 0.7152 * tint->green + 0.0722 * tint->blue < 0.5;
    /* bily text: 90. percentil od nejsvetlejsich; tmavy text: od nejtmavsich */
    guint64 limit = (guint64) w * h / 10, sum = 0;
    gint v = light_text ? 255 : 0;
    for (; v >= 0 && v <= 255; v += light_text ? -1 : 1) {
        sum += hist[v];
        if (sum > limit)
            break;
    }
    gdouble l = CLAMP (v, 0, 255) / 255.0;
    gdouble t = 0.2126 * tint->red + 0.7152 * tint->green + 0.0722 * tint->blue;
    gdouble need = 0.0;
    if (light_text && l > READABLE_LIGHT_TEXT && l > t)
        need = (l - READABLE_LIGHT_TEXT) / (l - t);
    else if (!light_text && l < READABLE_DARK_TEXT && l < t)
        need = (READABLE_DARK_TEXT - l) / (t - l);
    return MAX (tint->alpha, need);
}

/* Vykresli vyrez tapety pod listou do PNG; NULL kdyz neni tapeta (pak pruhledna lista) */
static gchar *
render_wallpaper (Bar *bar) {
    GdkWindow *gw = bar->toplevel ? gtk_widget_get_window (bar->toplevel) : NULL;
    if (!gw)
        return NULL;
    GdkDisplay *display = gdk_window_get_display (gw);
    GdkMonitor *mon = gdk_display_get_monitor_at_window (display, gw);
    if (!mon)
        return NULL;
    gint style = 5;
    gchar *path = wallpaper_for (bar, mon, &style);
    if (!path)
        return NULL;
    GdkRectangle geo, r;
    gdk_monitor_get_geometry (mon, &geo);
    gdk_window_get_frame_extents (gw, &r);
    gint scale = gdk_window_get_scale_factor (gw);
    gint W = geo.width * scale, H = geo.height * scale;
    gint bx = (r.x - geo.x) * scale, by = (r.y - geo.y) * scale, bw = r.width * scale, bh = r.height * scale;
    GdkRGBA tint;
    bar_tint (bar, &tint);
    GStatBuf st;
    gint64 mtime = g_stat (path, &st) == 0 ? (gint64) st.st_mtime : 0;
    gchar *key = g_strdup_printf ("%s|%" G_GINT64_FORMAT "|%d|%dx%d|%d,%d,%dx%d|%.3f,%.3f,%.3f,%.3f",
                                  path, mtime, style, W, H, bx, by, bw, bh,
                                  tint.red, tint.green, tint.blue, tint.alpha);
    if (bar->bg_key && bar->bg_file && strcmp (key, bar->bg_key) == 0
        && g_file_test (bar->bg_file, G_FILE_TEST_IS_REGULAR)) {
        g_free (key);
        g_free (path);
        return g_strdup (bar->bg_file);
    }
    GdkPixbuf *src = bw > 0 && bh > 0 ? gdk_pixbuf_new_from_file (path, NULL) : NULL;
    g_free (path);
    if (!src) {
        g_free (key);
        return NULL;
    }
    gdouble iw = gdk_pixbuf_get_width (src), ih = gdk_pixbuf_get_height (src);
    gdouble sx, sy;
    switch (style) {
    case 3: /* roztazeny */
        sx = W / iw;
        sy = H / ih;
        break;
    case 4: /* prizpusobeny (cely obrazek) */
        sx = sy = MIN (W / iw, H / ih);
        break;
    case 1: /* na stred */
        sx = sy = 1.0;
        break;
    default: /* 5 zvetseny (vyplnit), dlazdice a dalsi jako vyplnit */
        sx = sy = MAX (W / iw, H / ih);
        break;
    }
    gdouble ox = (W - iw * sx) / 2.0 - bx, oy = (H - ih * sy) / 2.0 - by;
    GdkPixbuf *dest = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, bw, bh);
    gdk_pixbuf_fill (dest, 0x000000ff);
    gint x0 = MAX (0, (gint) ceil (ox)), y0 = MAX (0, (gint) ceil (oy));
    gint x1 = MIN (bw, (gint) floor (ox + iw * sx)), y1 = MIN (bh, (gint) floor (oy + ih * sy));
    if (x1 > x0 && y1 > y0)
        gdk_pixbuf_scale (src, dest, x0, y0, x1 - x0, y1 - y0, ox, oy, sx, sy, GDK_INTERP_BILINEAR);
    g_object_unref (src);
    /* ton listy pres tapetu: stejne jako pruhledna lista nad tapetou */
    guchar *px = gdk_pixbuf_get_pixels (dest);
    gint rs = gdk_pixbuf_get_rowstride (dest), n = gdk_pixbuf_get_n_channels (dest);
    gdouble a = CLAMP (readable_alpha (dest, &tint), 0.0, 1.0);
    gdouble tc[3] = { tint.red * 255.0 * a, tint.green * 255.0 * a, tint.blue * 255.0 * a };
    for (gint y = 0; y < bh; y++)
        for (gint x = 0; x < bw; x++) {
            guchar *p = px + y * rs + x * n;
            for (gint i = 0; i < 3; i++)
                p[i] = (guchar) CLAMP (p[i] * (1.0 - a) + tc[i] + 0.5, 0, 255);
        }
    gchar *dir = g_build_filename (g_get_user_cache_dir (), "luxos", NULL);
    g_mkdir_with_parents (dir, 0700);
    /* novy nazev pro kazdou zmenu - panel obrazek se stejnou cestou znovu nenacte */
    gchar *name = g_strdup_printf ("bar-wallpaper-%08x.png", g_str_hash (key));
    gchar *file = g_build_filename (dir, name, NULL);
    g_free (name);
    g_free (dir);
    gboolean ok = gdk_pixbuf_save (dest, file, "png", NULL, NULL);
    g_object_unref (dest);
    if (!ok) {
        g_free (file);
        g_free (key);
        return NULL;
    }
    if (bar->bg_file && strcmp (bar->bg_file, file) != 0)
        g_unlink (bar->bg_file);
    g_free (bar->bg_file);
    bar->bg_file = g_strdup (file);
    g_free (bar->bg_key);
    bar->bg_key = key;
    return file;
}

/* Pozadi listy: tapeta (vychozi), jinak pruhledna/neprusvitna barva (BAR_COVER) */
static void
apply_background (Bar *bar) {
    if (!bar->toplevel)
        return;
    GObject *obj = G_OBJECT (bar->toplevel);
    gboolean has_image = g_object_class_find_property (G_OBJECT_GET_CLASS (obj), "background-image") != NULL;
    gchar *file = bar->cover == COVER_WALLPAPER && has_image ? render_wallpaper (bar) : NULL;
    bar->setting_bg = TRUE;
    if (file) {
        gchar *cur = NULL;
        g_object_get (obj, "background-image", &cur, NULL);
        if (g_strcmp0 (cur, file) != 0)
            g_object_set (obj, "background-image", file, NULL);
        g_free (cur);
        if (panel_get_uint (obj, "background-style") != 2)
            panel_set_uint (obj, "background-style", 2);
        g_free (file);
    } else {
        if (panel_get_uint (obj, "background-style") == 2)
            panel_set_uint (obj, "background-style", 1);
        apply_alpha (bar);
    }
    bar->setting_bg = FALSE;
}

static gboolean
background_idle (gpointer data) {
    Bar *bar = data;
    bar->bg_id = 0;
    apply_background (bar);
    return G_SOURCE_REMOVE;
}

static void
queue_background (Bar *bar) {
    if (!bar->bg_id)
        bar->bg_id = g_timeout_add (150, background_idle, bar);
}

/* jina tapeta (Nastaveni > Plocha) nebo jiny styl */
static void
on_desktop_changed (XfconfChannel *ch, const gchar *prop, const GValue *v, Bar *bar) {
    (void) ch;
    (void) v;
    if (g_str_has_prefix (prop, "/backdrop/"))
        queue_background (bar);
}

/* nekdo jiny (nastaveni panelu, luxos-appearance) zmenil styl pozadi - tapetu vratit */
static void
on_style_changed (GObject *obj, GParamSpec *pspec, Bar *bar) {
    (void) obj;
    (void) pspec;
    if (!bar->setting_bg)
        queue_background (bar);
}

/* luxos-appearance prepnul svetly/tmavy rezim (zapise alfu BAR_OPACITY) - pod oknem zustat
 * neprusvitny */
static void
on_rgba_changed (GObject *obj, GParamSpec *pspec, Bar *bar) {
    (void) obj;
    (void) pspec;
    if (!bar->setting_rgba) {
        apply_alpha (bar);
        /* svetly/tmavy rezim: jiny ton tapety */
        queue_background (bar);
    }
}

/* Zasahuje nejake okno na aktualni plose pod listu nebo se jí dotyka? */
static gboolean
compute_covered (Bar *bar) {
    GdkWindow *gw = bar->toplevel ? gtk_widget_get_window (bar->toplevel) : NULL;
    if (!gw || !bar->screen)
        return FALSE;
    GdkRectangle r;
    gdk_window_get_frame_extents (gw, &r);
    gint scale = gdk_window_get_scale_factor (gw);
    gint bx = r.x * scale, by = r.y * scale, bw = r.width * scale, bh = r.height * scale;
    WnckWorkspace *ws = wnck_screen_get_active_workspace (bar->screen);
    for (GList *l = wnck_screen_get_windows (bar->screen); l; l = l->next) {
        WnckWindow *w = l->data;
        WnckWindowType t = wnck_window_get_window_type (w);
        if (t == WNCK_WINDOW_DESKTOP || t == WNCK_WINDOW_DOCK || t == WNCK_WINDOW_SPLASHSCREEN
            || t == WNCK_WINDOW_MENU || t == WNCK_WINDOW_TOOLBAR)
            continue;
        if (wnck_window_is_minimized (w) || (ws && !wnck_window_is_visible_on_workspace (w, ws)))
            continue;
        /* okna "vzdy vespod" patri k plose (widgety LuxOS, conky): lista nad nimi zustava pruhledna */
        if (wnck_window_is_below (w))
            continue;
        gint x, y, w_, h;
        wnck_window_get_geometry (w, &x, &y, &w_, &h);
        /* dotyk dolniho okraje listy (maximalizovane okno) se pocita taky */
        if (x < bx + bw && x + w_ > bx && y <= by + bh && y + h > by)
            return TRUE;
    }
    return FALSE;
}

static gboolean
evaluate (gpointer data) {
    Bar *bar = data;
    bar->eval_id = 0;
    /* vychozi: lista vzdy pruhledna, pod ni tapeta i u maximalizovaneho okna (jako macOS) */
    gboolean c = bar->cover == COVER_SOLID && compute_covered (bar);
    if (c != bar->covered) {
        bar->covered = c;
        GtkStyleContext *ctx = bar->toplevel ? gtk_widget_get_style_context (bar->toplevel) : NULL;
        if (ctx) {
            if (c)
                gtk_style_context_add_class (ctx, "luxos-covered");
            else
                gtk_style_context_remove_class (ctx, "luxos-covered");
        }
    }
    apply_background (bar);
    return G_SOURCE_REMOVE;
}

/* udalosti oken chodi v davkach - vyhodnotit jednou po nich */
static void
queue_eval (Bar *bar) {
    if (!bar->eval_id)
        bar->eval_id = g_timeout_add (60, evaluate, bar);
}

static void on_window_changed (WnckWindow *w, gpointer bar) { (void) w; queue_eval (bar); }
static void on_window_state (WnckWindow *w, WnckWindowState a, WnckWindowState b, gpointer bar) {
    (void) w; (void) a; (void) b; queue_eval (bar);
}

static void
watch_window (Bar *bar, WnckWindow *w) {
    g_signal_connect (w, "geometry-changed", G_CALLBACK (on_window_changed), bar);
    g_signal_connect (w, "workspace-changed", G_CALLBACK (on_window_changed), bar);
    g_signal_connect (w, "state-changed", G_CALLBACK (on_window_state), bar);
}

static void
on_window_opened (WnckScreen *s, WnckWindow *w, Bar *bar) {
    (void) s;
    watch_window (bar, w);
    queue_eval (bar);
}

static void on_screen_changed (WnckScreen *s, gpointer x, Bar *bar) { (void) s; (void) x; queue_eval (bar); }
static void on_stacking_changed (WnckScreen *s, Bar *bar) { (void) s; queue_eval (bar); }

/* ---- kresleni hodin -------------------------------------------------------------------- */
static gchar *
format_now (const char *fmt) {
    char buf[128];
    time_t t = time (NULL);
    struct tm tm;
    localtime_r (&t, &tm);
    if (strftime (buf, sizeof buf, fmt, &tm) == 0)
        return g_strdup ("");
    return g_strdup (buf);
}

static gboolean
draw_area (GtkWidget *w, cairo_t *cr, Bar *bar) {
    bar->hit.width = 0;
    if (!bar->center || !bar->text || !bar->toplevel)
        return FALSE;
    GtkAllocation a;
    gtk_widget_get_allocation (w, &a);
    PangoLayout *layout = gtk_widget_create_pango_layout (w, NULL);
    gchar *markup = g_markup_printf_escaped ("<span weight=\"600\">%s</span>", bar->text);
    PangoFontDescription *fd = pango_font_description_from_string ("Inter 10");
    pango_layout_set_font_description (layout, fd);
    pango_layout_set_markup (layout, markup, -1);
    gint tw, th;
    pango_layout_get_pixel_size (layout, &tw, &th);

    /* stred okna listy v souradnicich pluginu */
    gint ox = 0, oy = 0;
    gtk_widget_translate_coordinates (w, bar->toplevel, 0, 0, &ox, &oy);
    gint center = gtk_widget_get_allocated_width (bar->toplevel) / 2 - ox;
    gint pad = 8;
    gint x = center - tw / 2;
    x = CLAMP (x, pad, MAX (pad, a.width - tw - pad));
    gint y = (a.height - th) / 2;

    GtkStyleContext *ctx = gtk_widget_get_style_context (w);
    GdkRGBA fg;
    gtk_style_context_get_color (ctx, gtk_style_context_get_state (ctx), &fg);
    bar->hit = (GdkRectangle) { x - pad, MAX (0, y - 3), tw + 2 * pad, MIN (a.height, th + 6) };
    if (bar->hover) {
        /* stejne jako tlacitka listy (.xfce4-panel button:hover) */
        double r = 6, hx = bar->hit.x, hy = bar->hit.y, hw = bar->hit.width, hh = bar->hit.height;
        cairo_new_sub_path (cr);
        cairo_arc (cr, hx + hw - r, hy + r, r, -G_PI / 2, 0);
        cairo_arc (cr, hx + hw - r, hy + hh - r, r, 0, G_PI / 2);
        cairo_arc (cr, hx + r, hy + hh - r, r, G_PI / 2, G_PI);
        cairo_arc (cr, hx + r, hy + r, r, G_PI, 3 * G_PI / 2);
        cairo_close_path (cr);
        cairo_set_source_rgba (cr, fg.red, fg.green, fg.blue, 0.08);
        cairo_fill (cr);
    }
    gdk_cairo_set_source_rgba (cr, &fg);
    cairo_move_to (cr, x, y);
    pango_cairo_show_layout (cr, layout);

    pango_font_description_free (fd);
    g_free (markup);
    g_object_unref (layout);
    return FALSE;
}

static gboolean tick (gpointer data);

/* prekreslit na zacatku dalsi minuty */
static void
schedule_tick (Bar *bar) {
    gint64 now = g_get_real_time ();
    guint ms = (guint) (60000 - (now / 1000) % 60000) + 20;
    bar->tick_id = g_timeout_add (ms, tick, bar);
}

static void
update_text (Bar *bar) {
    gchar *t = format_now (CLOCK_FORMAT);
    if (g_strcmp0 (t, bar->text) != 0) {
        g_free (bar->text);
        bar->text = t;
        gtk_widget_queue_draw (bar->area);
    } else {
        g_free (t);
    }
}

static gboolean
tick (gpointer data) {
    Bar *bar = data;
    update_text (bar);
    schedule_tick (bar);
    return G_SOURCE_REMOVE;
}

static gboolean
in_hit (Bar *bar, double x, double y) {
    return bar->center && bar->hit.width > 0 && x >= bar->hit.x && x < bar->hit.x + bar->hit.width
           && y >= bar->hit.y && y < bar->hit.y + bar->hit.height;
}

static gboolean
on_motion (GtkWidget *w, GdkEventMotion *ev, Bar *bar) {
    gboolean h = in_hit (bar, ev->x, ev->y);
    if (h != bar->hover) {
        bar->hover = h;
        gtk_widget_queue_draw (w);
    }
    return FALSE;
}

static gboolean
on_leave (GtkWidget *w, GdkEventCrossing *ev, Bar *bar) {
    (void) ev;
    if (bar->hover) {
        bar->hover = FALSE;
        gtk_widget_queue_draw (w);
    }
    return FALSE;
}

static gboolean
on_press (GtkWidget *w, GdkEventButton *ev, Bar *bar) {
    (void) w;
    if (ev->button == 1 && ev->type == GDK_BUTTON_PRESS && in_hit (bar, ev->x, ev->y)) {
        g_spawn_command_line_async ("luxos-calendar-toggle", NULL);
        return TRUE;
    }
    return FALSE;
}

static gboolean
on_tooltip (GtkWidget *w, gint x, gint y, gboolean kb, GtkTooltip *tip, Bar *bar) {
    (void) w;
    (void) kb;
    if (!in_hit (bar, x, y))
        return FALSE;
    gchar *full = format_now (TOOLTIP_FORMAT);
    gtk_tooltip_set_text (tip, full);
    g_free (full);
    return TRUE;
}

/* ---- zivotni cyklus -------------------------------------------------------------------- */
static void
apply_conf (Bar *bar) {
    read_conf (bar);
    sync_right_clock (bar);
    gtk_widget_queue_draw (bar->area);
    queue_eval (bar);
}

static void
on_conf_changed (GFileMonitor *m, GFile *f, GFile *o, GFileMonitorEvent ev, Bar *bar) {
    (void) m;
    (void) f;
    (void) o;
    if (ev == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT || ev == G_FILE_MONITOR_EVENT_CREATED
        || ev == G_FILE_MONITOR_EVENT_DELETED || ev == G_FILE_MONITOR_EVENT_RENAMED
        || ev == G_FILE_MONITOR_EVENT_MOVED_IN)
        apply_conf (bar);
}

/* okno panelu a sourozenci jsou k dispozici az po umisteni pluginu do listy */
static gboolean
late_init (gpointer data) {
    Bar *bar = data;
    bar->toplevel = gtk_widget_get_toplevel (GTK_WIDGET (bar->plugin));
    if (!gtk_widget_is_toplevel (bar->toplevel))
        bar->toplevel = NULL;
    if (bar->toplevel && g_object_class_find_property (G_OBJECT_GET_CLASS (bar->toplevel), "background-rgba"))
        bar->rgba_handler = g_signal_connect (bar->toplevel, "notify::background-rgba",
                                              G_CALLBACK (on_rgba_changed), bar);
    if (bar->toplevel) {
        g_signal_connect_swapped (bar->toplevel, "size-allocate", G_CALLBACK (gtk_widget_queue_draw), bar->area);
        g_signal_connect_swapped (bar->toplevel, "size-allocate", G_CALLBACK (queue_background), bar);
        if (g_object_class_find_property (G_OBJECT_GET_CLASS (bar->toplevel), "background-style"))
            g_signal_connect (bar->toplevel, "notify::background-style", G_CALLBACK (on_style_changed), bar);
    }
    g_signal_connect (xfconf_channel_get ("xfce4-desktop"), "property-changed", G_CALLBACK (on_desktop_changed), bar);
    bar->handle = wnck_handle_new (WNCK_CLIENT_TYPE_APPLICATION);
    bar->screen = wnck_handle_get_default_screen (bar->handle);
    if (bar->screen) {
        wnck_screen_force_update (bar->screen);
        for (GList *l = wnck_screen_get_windows (bar->screen); l; l = l->next)
            watch_window (bar, l->data);
        g_signal_connect (bar->screen, "window-opened", G_CALLBACK (on_window_opened), bar);
        g_signal_connect (bar->screen, "window-closed", G_CALLBACK (on_screen_changed), bar);
        g_signal_connect (bar->screen, "active-workspace-changed", G_CALLBACK (on_screen_changed), bar);
        g_signal_connect (bar->screen, "window-stacking-changed", G_CALLBACK (on_stacking_changed), bar);
    }
    apply_conf (bar);
    evaluate (bar);
    return G_SOURCE_REMOVE;
}

static void
bar_free (XfcePanelPlugin *plugin, Bar *bar) {
    (void) plugin;
    if (bar->tick_id)
        g_source_remove (bar->tick_id);
    if (bar->eval_id)
        g_source_remove (bar->eval_id);
    if (bar->bg_id)
        g_source_remove (bar->bg_id);
    g_signal_handlers_disconnect_by_data (xfconf_channel_get ("xfce4-desktop"), bar);
    if (bar->screen) {
        g_signal_handlers_disconnect_by_data (bar->screen, bar);
        for (GList *l = wnck_screen_get_windows (bar->screen); l; l = l->next)
            g_signal_handlers_disconnect_by_data (l->data, bar);
    }
    if (bar->toplevel)
        g_signal_handlers_disconnect_by_data (bar->toplevel, bar);
    if (bar->handle)
        g_object_unref (bar->handle);
    /* pri odebrani pluginu vratit hodiny vpravo a pruhlednost */
    bar->center = FALSE;
    sync_right_clock (bar);
    bar->covered = FALSE;
    bar->cover = COVER_TRANSLUCENT;
    apply_background (bar);
    if (bar->bg_file)
        g_unlink (bar->bg_file);
    g_free (bar->bg_file);
    g_free (bar->bg_key);
    if (bar->monitor)
        g_object_unref (bar->monitor);
    g_free (bar->conf_path);
    g_free (bar->text);
    g_free (bar);
}

static void
construct (XfcePanelPlugin *plugin) {
    Bar *bar = g_new0 (Bar, 1);
    bar->plugin = plugin;
    xfconf_init (NULL);
    xfce_panel_plugin_set_expand (plugin, TRUE);
    bar->conf_path = g_build_filename (g_get_user_config_dir (), "luxos", "appearance.conf", NULL);

    bar->area = gtk_drawing_area_new ();
    gtk_widget_add_events (bar->area, GDK_POINTER_MOTION_MASK | GDK_LEAVE_NOTIFY_MASK | GDK_BUTTON_PRESS_MASK);
    gtk_widget_set_has_tooltip (bar->area, TRUE);
    g_signal_connect (bar->area, "draw", G_CALLBACK (draw_area), bar);
    g_signal_connect (bar->area, "motion-notify-event", G_CALLBACK (on_motion), bar);
    g_signal_connect (bar->area, "leave-notify-event", G_CALLBACK (on_leave), bar);
    g_signal_connect (bar->area, "button-press-event", G_CALLBACK (on_press), bar);
    g_signal_connect (bar->area, "query-tooltip", G_CALLBACK (on_tooltip), bar);
    gtk_container_add (GTK_CONTAINER (plugin), bar->area);
    gtk_widget_show_all (GTK_WIDGET (plugin));

    GFile *f = g_file_new_for_path (bar->conf_path);
    bar->monitor = g_file_monitor_file (f, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
    g_object_unref (f);
    if (bar->monitor)
        g_signal_connect (bar->monitor, "changed", G_CALLBACK (on_conf_changed), bar);

    update_text (bar);
    schedule_tick (bar);
    g_signal_connect (plugin, "free-data", G_CALLBACK (bar_free), bar);
    g_idle_add (late_init, bar);
}

XFCE_PANEL_PLUGIN_REGISTER (construct);
