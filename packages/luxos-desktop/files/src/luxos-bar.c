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
 * 3. Bile pismo na prilis svetle tapete (BAR_TEXT=white ve svetlem rezimu): kdyz je kontrast bileho
 *    pisma na vyrezu tapety pod listou (s kourovym tonem listy) nizky - bila, bezova nebo jina velmi
 *    svetla tapeta -, prepne se lista na tmave pismo se svetlym tonem; na tmavsi tapete zpet na bile.
 *    Rozhoduje kontrast podle WCAG (prumer linearniho jasu vyrezu) s hysterezi, aby lista neblikala.
 *    Pocita se pro monitor s listou a tapetu aktivni plochy, znovu pri zmene tapety, plochy
 *    a monitoru. Bez restartu panelu: plugin prepne tridu okna listy (luxos-ink-dark / luxos-ink-white,
 *    pravidla ve spravovanem bloku gtk.css) - pluginy v procesu panelu se prebarvi hned. Rozhodnuti
 *    zapise "luxos-appearance bar-ink dark|white live" (zakladni pravidla bloku pro externi pluginy)
 *    a po jeho dobehnuti plugin restartuje externi pluginy (wrapper-2.0 = vlastni procesy: logo,
 *    rozlozeni klavesnice, zvuk, zvonek) signalem SIGUSR1 - panel je spusti znovu bez ptani
 *    a nactou novy blok. Lista ani tapeta pod ni nezmizi.
 *
 * 4. Zavoj pod listou na velmi svetle tapete (jako macOS): kdyz je pismo listy bile (tmavy rezim nebo
 *    BAR_TEXT=white) a tapeta nahore svetla (bila, bezova, bily len), ztmavi se tapeta pod listou
 *    a kousek pod ni plynulym prechodem do cerne (nahore nejvys SCRIM_MAX, do ztracena na SCRIM_HEIGHT
 *    px). Neni to ton listy: plugin zavoj kresli do vyrezu tapety v liste a pod listou samostatnym
 *    pruhlednym oknem plochy (typ DESKTOP, nad tapetou xfdesktop, pod widgety a okny, bez vstupu -
 *    kliky jdou na plochu). Sila podle jasu tapety v pasu pod listou (prumerny linearni jas, ulozeny
 *    pro kazdou tapetu - prepnuti plochy jen prekresli prechod); bezne tapety vcetne svetle Sunrise
 *    zustavaji beze zmeny. Bile pismo tak zustava bile a citelne, tmave pismo jen kdyz ani se zavojem
 *    kontrast nestaci. Vypnuti: DESKTOP_SCRIM=0 v appearance.conf (luxos-appearance desktop-scrim off).
 *    Bez kompozitoru zavoj neni (okno by nebylo pruhledne) - pak jako drive tmave pismo (bod 3).
 *
 * Zmeny appearance.conf se nacitaji hned (GFileMonitor), bez restartu panelu.
 */
#define WNCK_I_KNOW_THIS_IS_UNSTABLE
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <libwnck/libwnck.h>
#include <libxfce4panel/libxfce4panel.h>
#include <xfconf/xfconf.h>
#include <glib/gstdio.h>
#include <signal.h>
#include <stdio.h>
#include <sys/types.h>
#include <unistd.h>
#include <math.h>
#include <string.h>
#include <time.h>

#define DEFAULT_OPACITY 62
enum { COVER_WALLPAPER, COVER_TRANSLUCENT, COVER_SOLID };
#define CLOCK_FORMAT "%a %-d. %b  %H:%M"
#define TOOLTIP_FORMAT "%A %-d. %B %Y"

/* Zavoj pod listou (bod 4): vyska v logickych px od horniho okraje monitoru, nejvyssi alfa cerne
 * nahore. Sila 0-1 podle kontrastu bileho pisma na tapete v pasu zavoje: nad SCRIM_C_NONE zadny
 * (Sunrise ~2,2 : 1, Lagoon ~2,3), pod SCRIM_C_FULL plny (bila 1,0, bezova ~1,2, bily len ~1,15). */
#define SCRIM_HEIGHT 128
#define SCRIM_MAX 0.38
#define SCRIM_C_NONE 2.0
#define SCRIM_C_FULL 1.3

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
    gboolean dark_ink;          /* ~/.config/luxos/bar-ink = dark: bile pismo prepnute na tmave (svetla tapeta) */
    gchar *ink_path;
    gchar *ink_key;             /* tapeta a ton, pro ktere uz bylo pismo rozhodnuto */
    gint64 ink_spawned;         /* kdy naposledy spusten luxos-appearance bar-ink (us) */
    gboolean ext_ink;           /* pismo, se kterym bezi externi pluginy (nactene z gtk.css) */
    guint ext_id;               /* odlozeny restart externich pluginu */
    gboolean ink_path_read;
    gint ext_tries;
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
    gboolean scrim_enabled;     /* DESKTOP_SCRIM (vychozi 1) */
    gdouble scrim;              /* aktualni sila zavoje 0-1 */
    GtkWidget *scrim_win;       /* zavoj pod listou (okno plochy) */
    GdkRectangle scrim_geo;     /* naposledy nastavena poloha a velikost okna zavoje */
    GHashTable *lum_cache;      /* tapeta|mtime|styl|rozmery -> jas pasu zavoje (gdouble *) */
    gchar *scrim_key;           /* vyrez, pro ktery uz byl zavoj rozhodnut (pruhledna lista) */
    guint precompute_id;
} Bar;

/* ---- nastaveni ------------------------------------------------------------------------- */
static void
read_conf (Bar *bar) {
    gchar *data = NULL;
    bar->center = FALSE;
    bar->opacity = DEFAULT_OPACITY;
    bar->white = FALSE;
    bar->cover = COVER_WALLPAPER;
    bar->scrim_enabled = TRUE;
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
        else if (strcmp (*l, "DESKTOP_SCRIM") == 0)
            bar->scrim_enabled = strcmp (v, "0") != 0;
    }
    g_strfreev (lines);
    g_free (data);
}

static void
read_ink (Bar *bar) {
    gchar *data = NULL;
    bar->dark_ink = g_file_get_contents (bar->ink_path, &data, NULL, NULL) && g_str_has_prefix (data, "dark");
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
/* Ton listy bez okna pod ni. smoked = kourovy (tmavy) ton pod bilym pismem ve svetlem rezimu;
 * light_ink = bile pismo prepnute na tmave kvuli svetle tapete - svetly ton se stejnou slabou alfou. */
static void
tint_for (Bar *bar, gboolean dark_ink, GdkRGBA *c) {
    gboolean dark = xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE);
    gboolean faint = bar->white && !dark;
    gboolean smoked = faint && !dark_ink;
    *c = dark || smoked ? (GdkRGBA) { 0.09, 0.09, 0.12, 1 } : (GdkRGBA) { 0.96, 0.96, 0.97, 1 };
    c->alpha = bar->opacity / 100.0 * (faint ? 0.45 : 1.0);
}

static void
apply_alpha (Bar *bar) {
    GdkRGBA *rgba = NULL;
    if (!bar->toplevel || !g_object_class_find_property (G_OBJECT_GET_CLASS (bar->toplevel), "background-rgba"))
        return;
    g_object_get (bar->toplevel, "background-rgba", &rgba, NULL);
    if (!rgba)
        return;
    /* barvy jako luxos-appearance apply() */
    GdkRGBA want;
    tint_for (bar, bar->dark_ink, &want);
    if (bar->covered)
        want.alpha = 1.0;
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

/* Tapeta monitoru s listou na plose ws (-1 = aktivni): cesta (g_free) a styl xfdesktop (image-style) */
static gchar *
wallpaper_for (Bar *bar, GdkMonitor *mon, gint ws, gint *style) {
    XfconfChannel *ch = xfconf_channel_get ("xfce4-desktop");
    /* xfdesktop bez ulozene volby ukazuje na vsech plochach tapetu plochy single-workspace-number
     * (vychozi TRUE, "Pouzit pro vsechny plochy"); drive tu bylo FALSE - lista pak na dalsich plochach
     * kreslila starou tapetu te plochy, ktera na plose videt nebyla */
    if (xfconf_channel_get_bool (ch, "/backdrop/single-workspace-mode", TRUE))
        ws = xfconf_channel_get_int (ch, "/backdrop/single-workspace-number", 0);
    else if (ws < 0 && bar->screen && wnck_screen_get_active_workspace (bar->screen))
        ws = wnck_workspace_get_number (wnck_screen_get_active_workspace (bar->screen));
    ws = MAX (ws, 0);
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
    tint_for (bar, bar->dark_ink, c);
}

/* ---- bile nebo tmave pismo podle tapety -------------------------------------------------
 * Kontrast bileho pisma podle WCAG: (1,05) / (L + 0,05), L = prumerny linearni jas vyrezu tapety
 * po kourovem tonu listy. Prahy jsou nastavene podle skutecnych tapet: svetla tapeta Sunrise
 * (~2,4 : 1, pod bilym pismem jeste jemny tmavy zavoj readable_alpha a stin textu) zustava bila,
 * Light/Citrus (~1,5), bezova a bila (~1,0-1,2) prepnou na tmave pismo. Hystereze: na tmave pod
 * 2,0, zpet na bile az nad 2,3 - tapeta na hranici nebo drobna zmena tonu listu nerozblika. */
#define INK_DARK_BELOW 2.0
#define INK_WHITE_ABOVE 2.3

static gdouble
srgb_linear (guchar v) {
    gdouble c = v / 255.0;
    return c <= 0.04045 ? c / 12.92 : pow ((c + 0.055) / 1.055, 2.4);
}

static gdouble
white_contrast (GdkPixbuf *pb, const GdkRGBA *tint) {
    static gdouble lut[256];
    static gboolean lut_ready;
    if (!lut_ready) {
        for (gint i = 0; i < 256; i++)
            lut[i] = srgb_linear ((guchar) i);
        lut_ready = TRUE;
    }
    gint w = gdk_pixbuf_get_width (pb), h = gdk_pixbuf_get_height (pb);
    gint rs = gdk_pixbuf_get_rowstride (pb), n = gdk_pixbuf_get_n_channels (pb);
    const guchar *px = gdk_pixbuf_read_pixels (pb);
    gdouble a = CLAMP (tint->alpha, 0.0, 1.0);
    gdouble tc[3] = { tint->red, tint->green, tint->blue };
    gdouble sum = 0.0;
    for (gint y = 0; y < h; y++)
        for (gint x = 0; x < w; x++) {
            const guchar *p = px + y * rs + x * n;
            gdouble lin[3];
            for (gint i = 0; i < 3; i++) {
                /* ton se michá v sRGB jako pri kresleni listy */
                gdouble v = p[i] * (1.0 - a) + tc[i] * 255.0 * a;
                lin[i] = lut[(guchar) CLAMP (v + 0.5, 0, 255)];
            }
            sum += 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
        }
    gdouble l = w > 0 && h > 0 ? sum / ((gdouble) w * h) : 0.0;
    return 1.05 / (l + 0.05);
}

/* Rozhoduje se jen pro bile pismo ve svetlem rezimu (v tmavem je lista tmava vzdy) */
static gboolean
ink_needed (Bar *bar) {
    return bar->white && !xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE);
}

/* Trida okna listy podle pisma (pravidla v gtk.css od luxos-appearance) */
static void
apply_ink_class (Bar *bar) {
    GtkStyleContext *ctx = bar->toplevel ? gtk_widget_get_style_context (bar->toplevel) : NULL;
    if (!ctx)
        return;
    gboolean need = ink_needed (bar);
    gboolean dark = need && bar->dark_ink, white = need && !bar->dark_ink;
    if (dark != gtk_style_context_has_class (ctx, "luxos-ink-dark")) {
        if (dark)
            gtk_style_context_add_class (ctx, "luxos-ink-dark");
        else
            gtk_style_context_remove_class (ctx, "luxos-ink-dark");
    }
    if (white != gtk_style_context_has_class (ctx, "luxos-ink-white")) {
        if (white)
            gtk_style_context_add_class (ctx, "luxos-ink-white");
        else
            gtk_style_context_remove_class (ctx, "luxos-ink-white");
    }
}

/* Externi pluginy teto listy = deti procesu panelu "wrapper-2.0"; SIGUSR1 = panel je spusti znovu
 * bez ptani (panel_plugin_external_child_watch: "the panel asked for a restart") */
static void
restart_external_plugins (void) {
    GDir *dir = g_dir_open ("/proc", 0, NULL);
    if (!dir)
        return;
    pid_t self = getpid ();
    const gchar *name;
    while ((name = g_dir_read_name (dir))) {
        if (name[0] < '0' || name[0] > '9')
            continue;
        gchar *path = g_build_filename ("/proc", name, "stat", NULL), *stat = NULL;
        gboolean ok = g_file_get_contents (path, &stat, NULL, NULL);
        g_free (path);
        /* pid (comm) stav ppid ... - comm muze obsahovat mezery, ppid az za posledni ')' */
        const gchar *rp = ok ? strrchr (stat, ')') : NULL;
        const gchar *lp = ok ? strchr (stat, '(') : NULL;
        gint ppid = 0;
        if (rp && lp && sscanf (rp + 1, " %*c %d", &ppid) == 1 && ppid == self
            && g_str_has_prefix (lp + 1, "wrapper-2.0)")) {
            pid_t pid = (pid_t) g_ascii_strtoll (name, NULL, 10);
            if (pid > 1)
                kill (pid, SIGUSR1);
        }
        g_free (stat);
    }
    g_dir_close (dir);
}

/* Ikony StatusNotifier v oznamovaci oblasti (systray v procesu panelu: nm-applet --indicator, blueman, ...)
 * si symbolickou ikonu prebarvi jen pri zmene motivu ikon - stejny nazev motivu je jen znovu nacte
 * (GtkIconTheme se nemeni). Starsi ikony XEmbed (GtkStatusIcon v GTK 3) barvu listy prevezmou jen pri
 * svem spusteni; pozdejsi zmenu barvy (_NET_SYSTEM_TRAY_COLORS) ani nove ukotveni neprekresli. */
static void
refresh_tray_icons (void) {
    g_object_notify (G_OBJECT (gtk_settings_get_default ()), "gtk-icon-theme-name");
}

/* Externi pluginy restartovat az po zapsani gtk.css a az se pismo ustali (rychle prepinani ploch
 * s ruznymi tapetami: jeden restart na konci); kdyz se pismo vratilo na puvodni, restart neni potreba */
static gboolean
ext_restart_timeout (gpointer data) {
    Bar *bar = data;
    bar->ext_id = 0;
    if (bar->dark_ink == bar->ext_ink)
        return G_SOURCE_REMOVE;
    gchar *ink = NULL;
    gboolean file_dark = g_file_get_contents (bar->ink_path, &ink, NULL, NULL) && g_str_has_prefix (ink, "dark");
    g_free (ink);
    if (file_dark != bar->dark_ink) {
        /* luxos-appearance jeste nedobehl (nejdele ~3 s, pak az pri dalsi zmene) */
        if (++bar->ext_tries < 10)
            bar->ext_id = g_timeout_add (300, ext_restart_timeout, bar);
        return G_SOURCE_REMOVE;
    }
    restart_external_plugins ();
    bar->ext_ink = bar->dark_ink;
    return G_SOURCE_REMOVE;
}

/* TRUE = tmave pismo. current = dosavadni rozhodnuti (hystereze) */
static gboolean
want_dark_ink (gdouble contrast, gboolean current) {
    return current ? contrast < INK_WHITE_ABOVE : contrast < INK_DARK_BELOW;
}

/* Rozhodnout pismo pro vyrez tapety pod listou (pred tonem) */
static void
decide_ink (Bar *bar, GdkPixbuf *strip, const gchar *key) {
    if (!ink_needed (bar) || g_strcmp0 (key, bar->ink_key) == 0)
        return;
    GdkRGBA smoke;
    tint_for (bar, FALSE, &smoke);
    gboolean want = want_dark_ink (white_contrast (strip, &smoke), bar->dark_ink);
    if (want != bar->dark_ink) {
        /* nejvys jednou za 1 s (prepinani ploch s ruznymi tapetami, prezentace tapet); jinak pri
         * dalsi udalosti */
        gint64 now = g_get_monotonic_time ();
        if (bar->ink_spawned && now - bar->ink_spawned < G_USEC_PER_SEC)
            return;
        gchar *argv[] = { "luxos-appearance", "bar-ink", want ? "dark" : "white", "live", NULL };
        if (!g_spawn_async (NULL, argv, NULL, G_SPAWN_SEARCH_PATH | G_SPAWN_STDOUT_TO_DEV_NULL
                            | G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL, NULL, NULL))
            return;
        if (bar->ext_id)
            g_source_remove (bar->ext_id);
        bar->ext_tries = 0;
        bar->ext_id = g_timeout_add (800, ext_restart_timeout, bar);
        bar->ink_spawned = now;
        bar->dark_ink = want;
        /* pluginy v procesu panelu hned */
        apply_ink_class (bar);
        refresh_tray_icons ();
    }
    g_free (bar->ink_key);
    bar->ink_key = g_strdup (key);
}

/* Alfa tonu, se kterou je text listy citelny: nejmene nastavena (BAR_OPACITY), na prilis svetle
 * (pod bilym textem) nebo prilis tmave (pod tmavym textem) tapete vic. Meri se 90. percentil jasu
 * vyrezu, aby rozhodovala svetla mista, ne prumer. */
#define READABLE_LIGHT_TEXT 0.58    /* nejvyssi jas pozadi pod bilym textem */
#define READABLE_DARK_TEXT 0.62     /* nejnizsi jas pozadi pod tmavym textem */
/* Se zavojem (svetla tapeta, bod 4) prisnejsi strop pod bilym textem: plny zavoj ~4,5 : 1 (WCAG AA);
 * bez zavoje (vsechny bezne tapety) beze zmeny. */
#define READABLE_LIGHT_TEXT_SCRIM 0.45
static gdouble
readable_alpha (GdkPixbuf *pb, const GdkRGBA *tint, gdouble scrim) {
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
    gdouble need = 0.0, cap = READABLE_LIGHT_TEXT - (READABLE_LIGHT_TEXT - READABLE_LIGHT_TEXT_SCRIM) * CLAMP (scrim, 0.0, 1.0);
    if (light_text && l > cap && l > t)
        need = (l - cap) / (l - t);
    else if (!light_text && l < READABLE_DARK_TEXT && l < t)
        need = (READABLE_DARK_TEXT - l) / (t - l);
    return MAX (tint->alpha, need);
}

/* Obdelnik monitoru (rx, ry, rw, rh v px zarizeni, monitor W x H) z obrazku tapety src se stylem
 * xfdesktop do noveho obrazku out_w x out_h. src muze byt zmenseny: orig_w x orig_h = rozmery
 * puvodniho souboru (styl "na stred" pocita s puvodni velikosti). Mimo tapetu cerna. */
static GdkPixbuf *
wallpaper_region (GdkPixbuf *src, gint orig_w, gint orig_h, gint style, gint W, gint H,
                  gint rx, gint ry, gint rw, gint rh, gint out_w, gint out_h) {
    gdouble iw = orig_w, ih = orig_h;
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
    /* monitor -> vystup */
    gdouble fx = (gdouble) out_w / rw, fy = (gdouble) out_h / rh;
    gdouble ox = ((W - iw * sx) / 2.0 - rx) * fx, oy = ((H - ih * sy) / 2.0 - ry) * fy;
    /* puvodni px -> px zdroje */
    gdouble kx = gdk_pixbuf_get_width (src) / iw, ky = gdk_pixbuf_get_height (src) / ih;
    gdouble scx = sx * fx / kx, scy = sy * fy / ky;
    GdkPixbuf *dest = gdk_pixbuf_new (GDK_COLORSPACE_RGB, FALSE, 8, out_w, out_h);
    gdk_pixbuf_fill (dest, 0x000000ff);
    gint x0 = MAX (0, (gint) ceil (ox)), y0 = MAX (0, (gint) ceil (oy));
    gint x1 = MIN (out_w, (gint) floor (ox + iw * sx * fx)), y1 = MIN (out_h, (gint) floor (oy + ih * sy * fy));
    if (x1 > x0 && y1 > y0)
        gdk_pixbuf_scale (src, dest, x0, y0, x1 - x0, y1 - y0, ox, oy, scx, scy, GDK_INTERP_BILINEAR);
    return dest;
}

/* Monitor s listou, jeho rozmery a poloha listy na nem v px zarizeni; FALSE = neni okno listy */
static gboolean
bar_geometry (Bar *bar, GdkMonitor **mon, gint *W, gint *H, GdkRectangle *b, gint *scale) {
    GdkWindow *gw = bar->toplevel ? gtk_widget_get_window (bar->toplevel) : NULL;
    if (!gw)
        return FALSE;
    *mon = gdk_display_get_monitor_at_window (gdk_window_get_display (gw), gw);
    if (!*mon)
        return FALSE;
    GdkRectangle geo, r;
    gdk_monitor_get_geometry (*mon, &geo);
    gdk_window_get_frame_extents (gw, &r);
    *scale = gdk_window_get_scale_factor (gw);
    *W = geo.width * *scale;
    *H = geo.height * *scale;
    *b = (GdkRectangle) { (r.x - geo.x) * *scale, (r.y - geo.y) * *scale, r.width * *scale, r.height * *scale };
    return TRUE;
}

/* Klic tapety pro mezipamet jasu: zdroj, zmena souboru, styl, rozmery monitoru (g_free) */
static gchar *
wall_key (const gchar *path, gint style, gint W, gint H) {
    GStatBuf st;
    gint64 mtime = g_stat (path, &st) == 0 ? (gint64) st.st_mtime : 0;
    return g_strdup_printf ("%s|%" G_GINT64_FORMAT "|%d|%dx%d", path, mtime, style, W, H);
}

/* Vyrez tapety, ktery na obrazovce lezi presne pod listou (bez tonu). *skey = zdroj, styl a rozmery
 * (g_free). Obrazek se nenacita (vraci NULL) s key_only nebo kdyz je klic stejny jako skip_key.
 * *skey NULL: neni tapeta nebo okno listy. *wkey (muze byt NULL) = klic tapety (wall_key). */
static GdkPixbuf *
wallpaper_strip (Bar *bar, gchar **skey, gchar **wkey, const gchar *skip_key, gboolean key_only) {
    *skey = NULL;
    if (wkey)
        *wkey = NULL;
    GdkMonitor *mon;
    GdkRectangle b;
    gint W, H, scale, style = 5;
    if (!bar_geometry (bar, &mon, &W, &H, &b, &scale))
        return NULL;
    gchar *path = wallpaper_for (bar, mon, -1, &style);
    if (!path)
        return NULL;
    gchar *wk = wall_key (path, style, W, H);
    *skey = g_strdup_printf ("%s|%d,%d,%dx%d", wk, b.x, b.y, b.width, b.height);
    if (wkey)
        *wkey = wk;
    else
        g_free (wk);
    if (key_only || (skip_key && strcmp (*skey, skip_key) == 0)) {
        g_free (path);
        return NULL;
    }
    GdkPixbuf *src = b.width > 0 && b.height > 0 ? gdk_pixbuf_new_from_file (path, NULL) : NULL;
    g_free (path);
    if (!src)
        return NULL;
    GdkPixbuf *dest = wallpaper_region (src, gdk_pixbuf_get_width (src), gdk_pixbuf_get_height (src), style,
                                        W, H, b.x, b.y, b.width, b.height, b.width, b.height);
    g_object_unref (src);
    return dest;
}

/* ---- zavoj pod listou na svetle tapete (bod 4) ----------------------------------------- */

/* Prubeh zavoje: 1 nahore, 0 na SCRIM_HEIGHT, s nulovou smernici na obou koncich (bez hrany) */
static gdouble
scrim_profile (gdouble t) {
    t = CLAMP (t, 0.0, 1.0);
    return 1.0 - t * t * (3.0 - 2.0 * t);
}

/* Sila zavoje 0-1 podle prumerneho linearniho jasu tapety v pasu zavoje */
static gdouble
scrim_strength (gdouble lum) {
    gdouble c = 1.05 / (lum + 0.05);
    gdouble t = CLAMP ((SCRIM_C_NONE - c) / (SCRIM_C_NONE - SCRIM_C_FULL), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

/* Prumerny linearni jas tapety v pasu 0..SCRIM_HEIGHT px nahore na monitoru W x H (px zarizeni).
 * Obrazek se nacte zmenseny (rychle i u velkeho JPEG); -1 = neni tapeta. */
static gdouble
measure_top_lum (const gchar *path, gint style, gint W, gint H, gint scale) {
    gint ow = 0, oh = 0;
    if (!gdk_pixbuf_get_file_info (path, &ow, &oh) || ow <= 0 || oh <= 0)
        return -1.0;
    GdkPixbuf *src = gdk_pixbuf_new_from_file_at_scale (path, MIN (ow, 480), MIN (oh, 480), TRUE, NULL);
    if (!src)
        return -1.0;
    gint rh = MIN (H, SCRIM_HEIGHT * scale);
    gint out_w = MAX (1, MIN (W, 240)), out_h = MAX (1, rh * out_w / MAX (1, W));
    GdkPixbuf *pb = wallpaper_region (src, ow, oh, style, W, H, 0, 0, W, rh, out_w, out_h);
    g_object_unref (src);
    gint rs = gdk_pixbuf_get_rowstride (pb), n = gdk_pixbuf_get_n_channels (pb);
    const guchar *px = gdk_pixbuf_read_pixels (pb);
    gdouble sum = 0.0;
    for (gint y = 0; y < out_h; y++)
        for (gint x = 0; x < out_w; x++) {
            const guchar *p = px + y * rs + x * n;
            sum += 0.2126 * srgb_linear (p[0]) + 0.7152 * srgb_linear (p[1]) + 0.0722 * srgb_linear (p[2]);
        }
    g_object_unref (pb);
    return sum / ((gdouble) out_w * out_h);
}

/* Jas pasu zavoje pro tapetu (z mezipameti; nacte jen s compute) */
static gdouble
top_lum (Bar *bar, const gchar *path, gint style, gint W, gint H, gint scale, gboolean compute) {
    gchar *key = wall_key (path, style, W, H);
    gdouble *v = g_hash_table_lookup (bar->lum_cache, key);
    if (v || !compute) {
        g_free (key);
        return v ? *v : -2.0;
    }
    gdouble l = measure_top_lum (path, style, W, H, scale);
    if (g_hash_table_size (bar->lum_cache) > 64)
        g_hash_table_remove_all (bar->lum_cache);
    g_hash_table_insert (bar->lum_cache, key, g_memdup2 (&l, sizeof l));
    return l;
}

/* Zavoj jen s kompozitorem: bez nej by okno zavoje pod listou nebylo pruhledne a ztmavena by byla
 * jen sama lista - pak jako drive tmave pismo na svetle tapete (rozhodnuti bar-ink) */
static gboolean
scrim_possible (Bar *bar) {
    GdkScreen *screen = bar->toplevel ? gtk_widget_get_screen (bar->toplevel) : NULL;
    return screen && gdk_screen_is_composited (screen) && gdk_screen_get_rgba_visual (screen);
}

/* Muze byt pismo listy bile? (tmavy rezim, nebo BAR_TEXT=white ve svetlem) */
static gboolean
text_may_be_white (Bar *bar) {
    return bar->white || xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE);
}

/* Sila zavoje pro bile pismo na aktivni plose; compute = smi nacist tapetu, -1 = neni v mezipameti */
static gdouble
scrim_for_active (Bar *bar, gboolean compute) {
    if (!bar->scrim_enabled || !text_may_be_white (bar) || !scrim_possible (bar))
        return 0.0;
    GdkMonitor *mon;
    GdkRectangle b;
    gint W, H, scale, style = 5;
    if (!bar_geometry (bar, &mon, &W, &H, &b, &scale))
        return 0.0;
    gchar *path = wallpaper_for (bar, mon, -1, &style);
    if (!path)
        return 0.0;
    gdouble l = top_lum (bar, path, style, W, H, scale, compute);
    g_free (path);
    if (l < -1.5)
        return -1.0;
    return l < 0 ? 0.0 : scrim_strength (l);
}

/* Zavoj do vyrezu tapety pod listou: radek -> logicka vyska od horniho okraje monitoru */
static void
apply_scrim_rows (GdkPixbuf *pb, gdouble s, gint top, gint scale) {
    if (s <= 0.0)
        return;
    gint w = gdk_pixbuf_get_width (pb), h = gdk_pixbuf_get_height (pb);
    gint rs = gdk_pixbuf_get_rowstride (pb), n = gdk_pixbuf_get_n_channels (pb);
    guchar *px = gdk_pixbuf_get_pixels (pb);
    for (gint y = 0; y < h; y++) {
        gdouble keep = 1.0 - s * SCRIM_MAX * scrim_profile ((top + y + 0.5) / (gdouble) scale / SCRIM_HEIGHT);
        if (keep >= 1.0)
            continue;
        for (gint x = 0; x < w; x++) {
            guchar *p = px + y * rs + x * n;
            for (gint i = 0; i < 3; i++)
                p[i] = (guchar) CLAMP (p[i] * keep + 0.5, 0, 255);
        }
    }
}

static gboolean
scrim_draw (GtkWidget *w, cairo_t *cr, Bar *bar) {
    (void) w;
    cairo_set_operator (cr, CAIRO_OPERATOR_SOURCE);
    cairo_pattern_t *p = cairo_pattern_create_linear (0, 0, 0, SCRIM_HEIGHT);
    for (gint i = 0; i <= 32; i++) {
        gdouble t = i / 32.0;
        cairo_pattern_add_color_stop_rgba (p, t, 0, 0, 0, bar->scrim * SCRIM_MAX * scrim_profile (t));
    }
    cairo_set_source (cr, p);
    cairo_paint (cr);
    cairo_pattern_destroy (p);
    return TRUE;
}

/* Bez vstupu: kliky (i pravym tlacitkem - nabidka plochy) jdou na plochu pod oknem zavoje. Vstupni
 * tvar 1 px v levem hornim rohu (pod listou, kam nikdo neklikne): prazdny tvar xfwm4 na ramecek okna
 * neprenese. Znovu po namapovani - xfwm4 tvar klienta na ramecek kopiruje az pri zmene (ShapeNotify),
 * tvar nastaveny pred prevzetim okna ignoruje a ramecek by kliky bral. */
static void
scrim_input_shape (GtkWidget *w) {
    cairo_region_t *corner = cairo_region_create_rectangle (&(cairo_rectangle_int_t) { 0, 0, 1, 1 });
    gtk_widget_input_shape_combine_region (w, NULL);
    gtk_widget_input_shape_combine_region (w, corner);
    cairo_region_destroy (corner);
}

static gboolean
scrim_mapped (GtkWidget *w, GdkEvent *ev, Bar *bar) {
    (void) ev;
    (void) bar;
    scrim_input_shape (w);
    return FALSE;
}

/* Okno zavoje nad tapetou plochy: nove okno plochy (xfdesktop spusteny az po liste nebo znovu) by ho
 * prekrylo. xfwm4 okna typu DESKTOP na pozadani nevytahuje - znovu namapovane okno je navrchu vrstvy. */
static void
scrim_raise (Bar *bar) {
    if (bar->scrim_win && gtk_widget_get_visible (bar->scrim_win)) {
        gtk_widget_hide (bar->scrim_win);
        gtk_widget_show (bar->scrim_win);
    }
}

/* Zobrazit / skryt a prekreslit zavoj pod listou se silou s */
static void
scrim_set (Bar *bar, gdouble s) {
    GdkScreen *screen = bar->toplevel ? gtk_widget_get_screen (bar->toplevel) : NULL;
    GdkMonitor *mon = NULL;
    GdkWindow *gw = bar->toplevel ? gtk_widget_get_window (bar->toplevel) : NULL;
    if (gw)
        mon = gdk_display_get_monitor_at_window (gdk_window_get_display (gw), gw);
    gboolean show = s > 0.004 && screen && mon && gdk_screen_is_composited (screen)
                    && gdk_screen_get_rgba_visual (screen);
    if (fabs (s - bar->scrim) > 0.004) {
        bar->scrim = s;
        if (bar->scrim_win)
            gtk_widget_queue_draw (bar->scrim_win);
    }
    if (!show) {
        if (bar->scrim_win)
            gtk_widget_hide (bar->scrim_win);
        return;
    }
    if (!bar->scrim_win) {
        GtkWidget *w = gtk_window_new (GTK_WINDOW_TOPLEVEL);
        gtk_widget_set_visual (w, gdk_screen_get_rgba_visual (screen));
        gtk_widget_set_app_paintable (w, TRUE);
        gtk_window_set_title (GTK_WINDOW (w), "LuxOS menu bar scrim");
        gtk_window_set_role (GTK_WINDOW (w), "luxos-scrim");
        gtk_window_set_decorated (GTK_WINDOW (w), FALSE);
        gtk_window_set_type_hint (GTK_WINDOW (w), GDK_WINDOW_TYPE_HINT_DESKTOP);
        gtk_window_set_skip_taskbar_hint (GTK_WINDOW (w), TRUE);
        gtk_window_set_skip_pager_hint (GTK_WINDOW (w), TRUE);
        gtk_window_set_accept_focus (GTK_WINDOW (w), FALSE);
        gtk_window_set_focus_on_map (GTK_WINDOW (w), FALSE);
        gtk_window_stick (GTK_WINDOW (w));
        g_signal_connect (w, "draw", G_CALLBACK (scrim_draw), bar);
        scrim_input_shape (w);
        g_signal_connect (w, "map-event", G_CALLBACK (scrim_mapped), bar);
        bar->scrim_win = w;
    }
    GdkRectangle geo;
    gdk_monitor_get_geometry (mon, &geo);
    geo.height = MIN (geo.height, SCRIM_HEIGHT);
    /* jen pri zmene: kazde presunuti okna = udalost oken -> evaluate -> scrim_set (smycka) */
    if (memcmp (&geo, &bar->scrim_geo, sizeof geo) != 0) {
        GtkWindow *win = GTK_WINDOW (bar->scrim_win);
        gtk_widget_set_size_request (bar->scrim_win, geo.width, geo.height);
        gtk_window_resize (win, geo.width, geo.height);
        gtk_window_move (win, geo.x, geo.y);
        bar->scrim_geo = geo;
    }
    if (!gtk_widget_get_visible (bar->scrim_win))
        gtk_widget_show (bar->scrim_win);
}

/* Prepnuti plochy: zavoj hned podle ulozeneho jasu (vyrez listy dobehne pozdeji) */
static void
scrim_quick (Bar *bar) {
    gdouble s = scrim_for_active (bar, FALSE);
    if (s < 0)
        return;
    if (bar->white && bar->dark_ink
        && !xfconf_channel_get_bool (xfconf_channel_get ("xfce4-panel"), "/panels/dark-mode", FALSE))
        s = 0.0;
    scrim_set (bar, s);
}

/* Jas pasu zavoje pro tapety vsech ploch predem (prepnuti plochy pak nic nenacita) */
static gboolean
precompute_idle (gpointer data) {
    Bar *bar = data;
    bar->precompute_id = 0;
    GdkMonitor *mon;
    GdkRectangle b;
    gint W, H, scale;
    if (!bar->scrim_enabled || !text_may_be_white (bar) || !scrim_possible (bar)
        || !bar_geometry (bar, &mon, &W, &H, &b, &scale))
        return G_SOURCE_REMOVE;
    gint n = bar->screen ? wnck_screen_get_workspace_count (bar->screen) : 1;
    for (gint ws = 0; ws < MIN (n, 32); ws++) {
        gint style = 5;
        gchar *path = wallpaper_for (bar, mon, ws, &style);
        if (path)
            top_lum (bar, path, style, W, H, scale, TRUE);
        g_free (path);
    }
    return G_SOURCE_REMOVE;
}

static void
queue_precompute (Bar *bar) {
    if (!bar->precompute_id)
        bar->precompute_id = g_timeout_add (1500, precompute_idle, bar);
}

/* Vyrez tapety pod listou se zavojem a rozhodnutim o pismu. Zavoj patri jen pod bile pismo: kdyz
 * ani se zavojem bile pismo nestaci (tmave pismo), vyrez zustane bez zavoje. Vraci silu zavoje. */
static gdouble
scrim_strip (Bar *bar, GdkPixbuf *strip, const gchar *skey) {
    gdouble s = scrim_for_active (bar, TRUE);
    GdkMonitor *mon;
    GdkRectangle b = { 0 };
    gint W, H, scale = 1;
    bar_geometry (bar, &mon, &W, &H, &b, &scale);
    GdkPixbuf *raw = s > 0.0 && ink_needed (bar) ? gdk_pixbuf_copy (strip) : NULL;
    apply_scrim_rows (strip, s, b.y, scale);
    decide_ink (bar, strip, skey);
    if (s > 0.0 && ink_needed (bar) && bar->dark_ink) {
        s = 0.0;
        if (raw)
            gdk_pixbuf_copy_area (raw, 0, 0, gdk_pixbuf_get_width (raw), gdk_pixbuf_get_height (raw), strip, 0, 0);
    }
    if (raw)
        g_object_unref (raw);
    return s;
}

/* Bez tapety pod listou (BAR_COVER=translucent/solid) se pismo rozhoduje taky - prosvita tapeta;
 * zavoj pod pruhlednou listou kresli jen okno zavoje */
static void
update_ink (Bar *bar) {
    gchar *skey = NULL;
    /* udalosti oken chodi casto: tapeta se nacita jen pri zmene vyrezu nebo nastaveni */
    GdkPixbuf *strip = wallpaper_strip (bar, &skey, NULL, bar->scrim_key, FALSE);
    if (strip) {
        scrim_set (bar, scrim_strip (bar, strip, skey));
        g_object_unref (strip);
        g_free (bar->scrim_key);
        bar->scrim_key = g_strdup (skey);
    } else if (!skey) {
        scrim_set (bar, 0.0);
        g_clear_pointer (&bar->scrim_key, g_free);
    }
    g_free (skey);
}

/* Sila zavoje bez nacteni tapety (z mezipameti) pro dosavadni rozhodnuti o pismu; -1 = nevi se */
static gdouble
known_scrim (Bar *bar) {
    gdouble s = scrim_for_active (bar, FALSE);
    if (s > 0.0 && ink_needed (bar) && bar->dark_ink)
        s = 0.0;
    return s;
}

/* Vykresli vyrez tapety pod listou do PNG; NULL kdyz neni tapeta (pak pruhledna lista) */
static gchar *
render_wallpaper (Bar *bar) {
    GdkRGBA tint;
    gchar *skey = NULL;
    /* bez nacteni obrazku: stejna tapeta, rozmery, ton i zavoj jako minule -> hotovy soubor */
    if (bar->bg_key && bar->bg_file && g_file_test (bar->bg_file, G_FILE_TEST_IS_REGULAR)) {
        wallpaper_strip (bar, &skey, NULL, NULL, TRUE);
        if (!skey)
            return NULL;
        gdouble s = known_scrim (bar);
        bar_tint (bar, &tint);
        gchar *key = g_strdup_printf ("%s|%.3f,%.3f,%.3f,%.3f|%.3f", skey, tint.red, tint.green, tint.blue, tint.alpha, s);
        gboolean same = s >= 0 && strcmp (key, bar->bg_key) == 0;
        g_free (key);
        if (same && (!ink_needed (bar) || g_strcmp0 (skey, bar->ink_key) == 0)) {
            g_free (skey);
            scrim_set (bar, s);
            return g_strdup (bar->bg_file);
        }
        g_free (skey);
        skey = NULL;
    }
    GdkPixbuf *dest = wallpaper_strip (bar, &skey, NULL, NULL, FALSE);
    if (!dest) {
        g_free (skey);
        return NULL;
    }
    /* zavoj a bile/tmave pismo podle tapety (muze zmenit ton) */
    gdouble s = scrim_strip (bar, dest, skey);
    bar_tint (bar, &tint);
    gchar *key = g_strdup_printf ("%s|%.3f,%.3f,%.3f,%.3f|%.3f", skey, tint.red, tint.green, tint.blue, tint.alpha, s);
    g_free (skey);
    gint bw = gdk_pixbuf_get_width (dest), bh = gdk_pixbuf_get_height (dest);
    /* ton listy pres tapetu: stejne jako pruhledna lista nad tapetou */
    guchar *px = gdk_pixbuf_get_pixels (dest);
    gint rs = gdk_pixbuf_get_rowstride (dest), n = gdk_pixbuf_get_n_channels (dest);
    gdouble a = CLAMP (readable_alpha (dest, &tint, s), 0.0, 1.0);
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
    scrim_set (bar, s);
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
        if (bar->cover != COVER_WALLPAPER)
            update_ink (bar);
        else
            scrim_set (bar, 0.0);
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
    if (g_str_has_prefix (prop, "/backdrop/")) {
        queue_background (bar);
        queue_precompute (bar);
    }
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
        /* svetly/tmavy rezim: jiny ton tapety, pismo (a zavoj) rozhodnout znovu */
        g_clear_pointer (&bar->ink_key, g_free);
        g_clear_pointer (&bar->scrim_key, g_free);
        queue_precompute (bar);
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

/* jina plocha: zavoj hned (jas tapety je predem spocitany), vyrez listy po queue_eval */
static void
on_workspace_changed (WnckScreen *s, WnckWorkspace *prev, Bar *bar) {
    (void) s;
    (void) prev;
    scrim_quick (bar);
    queue_eval (bar);
}

/* nove okno plochy (xfdesktop spusteny znovu): zavoj zase nad nim */
static void
on_window_opened_desktop (WnckScreen *s, WnckWindow *w, Bar *bar) {
    (void) s;
    /* vlastni okno zavoje (typ DESKTOP) ne - znovu namapovane by se otevrelo zas a dokola */
    GdkWindow *own = bar->scrim_win ? gtk_widget_get_window (bar->scrim_win) : NULL;
    if (own && GDK_IS_X11_WINDOW (own) && wnck_window_get_xid (w) == gdk_x11_window_get_xid (own))
        return;
    if (wnck_window_get_window_type (w) == WNCK_WINDOW_DESKTOP)
        scrim_raise (bar);
}

/* kompozitor zapnut/vypnut: okno zavoje jen s nim (pruhlednost) */
static void
on_composited_changed (GdkScreen *screen, Bar *bar) {
    (void) screen;
    g_clear_pointer (&bar->scrim_key, g_free);
    g_free (bar->bg_key);
    bar->bg_key = NULL;
    queue_eval (bar);
}
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
    read_ink (bar);
    if (!bar->ink_path_read) {
        /* externi pluginy se spustily s blokem gtk.css podle ulozeneho rozhodnuti */
        bar->ext_ink = bar->dark_ink;
        bar->ink_path_read = TRUE;
    }
    apply_ink_class (bar);
    /* jine nastaveni (pruhlednost, bile pismo, zavoj) - pismo rozhodnout znovu */
    g_clear_pointer (&bar->ink_key, g_free);
    g_clear_pointer (&bar->scrim_key, g_free);
    queue_precompute (bar);
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
        /* data = bar->area, ne bar: disconnect_by_data(bar) ve bar_free by ho nechal - connect_object ho
         * odpoji sam se zanikem plochy (po odebrani pluginu by panel volal prekresleni uvolneneho widgetu) */
        g_signal_connect_object (bar->toplevel, "size-allocate", G_CALLBACK (gtk_widget_queue_draw), bar->area,
                                 G_CONNECT_SWAPPED);
        g_signal_connect_swapped (bar->toplevel, "size-allocate", G_CALLBACK (queue_background), bar);
        if (g_object_class_find_property (G_OBJECT_GET_CLASS (bar->toplevel), "background-style"))
            g_signal_connect (bar->toplevel, "notify::background-style", G_CALLBACK (on_style_changed), bar);
    }
    g_signal_connect (xfconf_channel_get ("xfce4-desktop"), "property-changed", G_CALLBACK (on_desktop_changed), bar);
    if (bar->toplevel)
        g_signal_connect (gtk_widget_get_screen (bar->toplevel), "composited-changed",
                          G_CALLBACK (on_composited_changed), bar);
    bar->handle = wnck_handle_new (WNCK_CLIENT_TYPE_APPLICATION);
    bar->screen = wnck_handle_get_default_screen (bar->handle);
    if (bar->screen) {
        wnck_screen_force_update (bar->screen);
        for (GList *l = wnck_screen_get_windows (bar->screen); l; l = l->next)
            watch_window (bar, l->data);
        g_signal_connect (bar->screen, "window-opened", G_CALLBACK (on_window_opened), bar);
        g_signal_connect (bar->screen, "window-closed", G_CALLBACK (on_screen_changed), bar);
        g_signal_connect (bar->screen, "active-workspace-changed", G_CALLBACK (on_workspace_changed), bar);
        g_signal_connect (bar->screen, "window-opened", G_CALLBACK (on_window_opened_desktop), bar);
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
    if (bar->ext_id)
        g_source_remove (bar->ext_id);
    if (bar->precompute_id)
        g_source_remove (bar->precompute_id);
    g_signal_handlers_disconnect_by_data (xfconf_channel_get ("xfce4-desktop"), bar);
    if (bar->toplevel)
        g_signal_handlers_disconnect_by_data (gtk_widget_get_screen (bar->toplevel), bar);
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
    bar->scrim_enabled = FALSE;
    apply_background (bar);
    if (bar->bg_file)
        g_unlink (bar->bg_file);
    if (bar->scrim_win)
        gtk_widget_destroy (bar->scrim_win);
    g_hash_table_destroy (bar->lum_cache);
    g_free (bar->scrim_key);
    g_free (bar->bg_file);
    g_free (bar->bg_key);
    if (bar->monitor)
        g_object_unref (bar->monitor);
    g_free (bar->conf_path);
    g_free (bar->ink_path);
    g_free (bar->ink_key);
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
    bar->ink_path = g_build_filename (g_get_user_config_dir (), "luxos", "bar-ink", NULL);
    bar->lum_cache = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);

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
