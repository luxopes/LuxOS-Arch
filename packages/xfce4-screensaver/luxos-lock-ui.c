/*
 * LuxOS - vzhled zamykaciho dialogu xfce4-screensaver jako zamykaci obrazovka luxos-greeter.
 *
 * Bezpecnost zustava v xfce4-screensaver (grab vstupu, PAM v procesu dialogu, necinnost
 * a zamykani); tady je jen vzhled: tapeta plochy uzivatele pres celou obrazovku, datum
 * a velke tenke hodiny nahore, kulaty avatar (obrazek z AccountsService nebo inicial),
 * jmeno, matne pole pro heslo se sipkou, hlasky (Caps Lock, spatne heslo, zamceny ucet
 * z pam_faillock, otisk prstu), vpravo nahore rozlozeni klavesnice, sit a baterie, dole
 * Prepnout uzivatele / Uspat / Restartovat / Vypnout. Rozmery, barvy a pisma jsou stejne
 * jako v luxos-greeter (packages/luxos-greeter/files/luxos-greeter) - pri zmene tam
 * upravit i tady. Klidovy stav (t = 0) vypada stejne jako setric "Tapeta plochy a hodiny"
 * (luxos-screensaver --style desktop), takze prechod setric -> dialog je plynuly.
 *
 * Testy (xfce4-screensaver-dialog spusteny samostatne v Xvfb): LUXOS_LOCK_DEMO_NAME (jmeno),
 * LUXOS_LOCK_DEMO_AVATAR (obrazek), LUXOS_LOCK_DEMO_FPRINT=1 (otisk prstu zapnuty),
 * LUXOS_LOCK_DEMO_USERS=N (pocet uzivatelu; tlacitka napajeni pak jen zapisou do logu),
 * LUXOS_I18N_DIR a LUXOS_GREETER_CONF (preklady a nastaveni z jineho mista).
 */
#include <ctype.h>
#include <math.h>
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <gio/gio.h>
#include <glib/gstdio.h>
#include <gtk/gtk.h>
#include <pango/pangocairo.h>
#include <xfconf/xfconf.h>

#ifdef ENABLE_X11
#include <X11/XKBlib.h>
#include <gdk/gdkx.h>
#include <libxklavier/xklavier.h>
#endif

#include "luxos-lock-ui.h"

#define GREETER_CONF "/etc/lightdm/luxos-greeter.conf"
#define I18N_DIR "/usr/share/luxos/i18n"
#define PAM_SERVICE_FILE "/etc/pam.d/xfce4-screensaver"
#define FPRINT_MODULE "/usr/lib/security/pam_fprintd.so"

typedef void (*IconFunc) (cairo_t *cr, double cx, double cy, double s);

typedef struct {
    LuxLock *ll;
    GtkWidget *button;
    GtkWidget *area;
    GtkWidget *label;
    IconFunc icon;
    const char *key;
    const char *method;     /* logind (Suspend, Reboot, PowerOff), jinak NULL */
} Round;

struct _LuxLock {
    GtkWidget *plug;
    GtkWidget *overlay;
    GtkWidget *bg;
    GtkWidget *status;
    GtkWidget *kbd_btn;
    GtkWidget *kbd_label;
    GtkWidget *net_icon;
    GtkWidget *bat_icon;
    GtkWidget *bat_label;
    GtkWidget *login;
    GtkWidget *status_msg;
    GtkWidget *users_box;
    GtkWidget *user_btn;
    GtkWidget *avatar;
    GtkWidget *name;
    GtkWidget *pw;
    GtkWidget *entry;
    GtkWidget *go;
    GtkWidget *go_area;
    GtkWidget *hint;
    GtkWidget *power;
    GList *rounds;

    GtkCssProvider *css;
    int W, H, scale;
    double u;
    struct {
        int avatar, pw_w, pw_h, round, status, pad, pw_pad, pw_font;
    } sz;

    cairo_surface_t *bg_surf;
    cairo_surface_t *blur_surf;
    GdkPixbuf *face;
    cairo_surface_t *face_surf;
    int face_size;
    char *real_name;

    char *font;
    char *clock_fmt;
    char *date_fmt;
    gboolean show_battery;
    gboolean show_network;

    double t, target, anim_from;
    gint64 anim_start;
    guint anim_id;
    LuxLockFunc leave_done;
    gpointer leave_data;

    guint tick_id;
    guint status_id;
    int last_minute;
    int bat_level;
    gboolean bat_charging;
    gboolean has_bat;
    int net;                  /* 0 nic, 1 kabel, 2 Wi-Fi */

    char *placeholder;
    gboolean error_shown;
    gboolean caps_hint;
    gboolean fprint;
    gboolean fp_wait;
    gboolean prompted;
    char *locked_hint;
    guint shake_id;
    gint64 shake_start;

    char **layouts;
    char **variants;
    int n_layouts;
};

/* ---- preklady (luxos-i18n) ------------------------------------------------------------ */
static GHashTable *tr_table = NULL;

static char *
env_lang (const char *const *vars) {
    const char *v = NULL;
    char *code;
    for (; *vars; vars++) {
        v = g_getenv (*vars);
        if (v && *v)
            break;
        v = NULL;
    }
    if (!v)
        v = "en";
    code = g_strdup (v);
    code[strcspn (code, "_.@")] = '\0';
    if (!*code) {
        g_free (code);
        code = g_strdup ("en");
    }
    return code;
}

const char *
lux_tr (const char *text) {
    const char *v;
    if (tr_table == NULL) {
        static const char *const vars[] = { "LC_ALL", "LC_MESSAGES", "LANG", NULL };
        char *lang = env_lang (vars);
        const char *dir = g_getenv ("LUXOS_I18N_DIR");
        char *path = g_strdup_printf ("%s/%s.tsv", dir && *dir ? dir : I18N_DIR, lang);
        char *data = NULL;
        tr_table = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);
        if (g_file_get_contents (path, &data, NULL, NULL)) {
            char **lines = g_strsplit (data, "\n", -1);
            for (char **l = lines; *l; l++) {
                char *tab;
                if (**l == '#' || (tab = strchr (*l, '\t')) == NULL || tab[1] == '\0')
                    continue;
                g_hash_table_replace (tr_table, g_strndup (*l, tab - *l), g_strdup (tab + 1));
            }
            g_strfreev (lines);
            g_free (data);
        }
        g_free (path);
        g_free (lang);
    }
    v = g_hash_table_lookup (tr_table, text);
    return v ? v : text;
}

/* ---- nastaveni (stejny soubor jako luxos-greeter) ------------------------------------- */
static gboolean
conf_flag (GKeyFile *kf, const char *key, gboolean def) {
    char *v = kf ? g_key_file_get_string (kf, "greeter", key, NULL) : NULL;
    gboolean r = def;
    if (v) {
        g_strstrip (v);
        if (*v && g_ascii_strcasecmp (v, "auto") != 0)
            r = !g_ascii_strcasecmp (v, "1") || !g_ascii_strcasecmp (v, "true")
                || !g_ascii_strcasecmp (v, "yes") || !g_ascii_strcasecmp (v, "on");
    }
    g_free (v);
    return r;
}

static char *
conf_str (GKeyFile *kf, const char *key, const char *def) {
    char *v = kf ? g_key_file_get_string (kf, "greeter", key, NULL) : NULL;
    if (v) {
        g_strstrip (v);
        if (*v)
            return v;
        g_free (v);
    }
    return g_strdup (def);
}

static void
load_config (LuxLock *ll) {
    static const char *const vars[] = { "LC_ALL", "LC_TIME", "LANG", NULL };
    const char *path = g_getenv ("LUXOS_GREETER_CONF");
    GKeyFile *kf = g_key_file_new ();
    char *lang = env_lang (vars);
    gboolean en = g_strcmp0 (lang, "en") == 0;
    if (!g_key_file_load_from_file (kf, path && *path ? path : GREETER_CONF, G_KEY_FILE_NONE, NULL)) {
        g_key_file_free (kf);
        kf = NULL;
    }
    ll->font = conf_str (kf, "font", "Inter");
    ll->clock_fmt = conf_str (kf, "clock-format", conf_flag (kf, "clock-24h", !en) ? "%-H:%M" : "%-I:%M");
    ll->date_fmt = conf_str (kf, "date-format", g_strcmp0 (lang, "cs") == 0 ? "%A %-d. %B" : "%A, %B %-d");
    ll->show_battery = conf_flag (kf, "show-battery", TRUE);
    ll->show_network = conf_flag (kf, "show-network", TRUE);
    if (kf)
        g_key_file_free (kf);
    g_free (lang);
}

/* ---- kresleni ------------------------------------------------------------------------- */
static double
ease (double t) {
    return t < 0.5 ? 4 * t * t * t : 1 - pow (-2 * t + 2, 3) / 2;
}

static void
rounded (cairo_t *cr, double x, double y, double w, double h, double r) {
    r = MIN (r, MIN (w / 2, h / 2));
    cairo_new_sub_path (cr);
    cairo_arc (cr, x + w - r, y + r, r, -G_PI / 2, 0);
    cairo_arc (cr, x + w - r, y + h - r, r, 0, G_PI / 2);
    cairo_arc (cr, x + r, y + h - r, r, G_PI / 2, G_PI);
    cairo_arc (cr, x + r, y + r, r, G_PI, 1.5 * G_PI);
    cairo_close_path (cr);
}

static PangoLayout *
text_layout (cairo_t *cr, const char *text, double px, PangoWeight weight, const char *family) {
    PangoLayout *lay = pango_cairo_create_layout (cr);
    PangoFontDescription *fd = pango_font_description_new ();
    char *fam = g_strdup_printf ("%s,Inter,Cantarell,Noto Sans,sans-serif", family);
    pango_font_description_set_family (fd, fam);
    pango_font_description_set_weight (fd, weight);
    pango_font_description_set_absolute_size (fd, px * PANGO_SCALE);
    pango_layout_set_font_description (lay, fd);
    pango_layout_set_text (lay, text, -1);
    pango_font_description_free (fd);
    g_free (fam);
    return lay;
}

static void
shadow_text (cairo_t *cr, PangoLayout *lay, double x, double y, double alpha, double blur) {
    /* mekky stin: nekolik posunutych kopii s malou pruhlednosti */
    static const double off[5][2] = { { 0, 1 }, { 0, 2 }, { -1, 1.5 }, { 1, 1.5 }, { 0, 3 } };
    for (int i = 0; i < 5; i++) {
        cairo_move_to (cr, x + off[i][0] * blur * 0.35, y + off[i][1] * blur * 0.45);
        cairo_set_source_rgba (cr, 0, 0, 0, 0.055 * alpha);
        pango_cairo_show_layout (cr, lay);
    }
    cairo_move_to (cr, x, y);
    cairo_set_source_rgba (cr, 1, 1, 1, alpha);
    pango_cairo_show_layout (cr, lay);
}

/* Rozmaze malou ImageSurface (RGB24) na miste; kanaly zvlast (jako box_blur v luxos-greeter) */
static void
blur_line (const float *src, float *dst, int start, int step, int n, int radius) {
    int win = 2 * radius + 1;
    float acc = src[start] * (radius + 1);
    for (int i = 0; i < radius; i++)
        acc += src[start + MIN (i, n - 1) * step];
    for (int i = 0; i < n; i++) {
        acc += src[start + MIN (i + radius, n - 1) * step] - src[start + MAX (i - radius - 1, 0) * step];
        dst[start + i * step] = acc / win;
    }
}

static void
box_blur (cairo_surface_t *surf, int radius, int passes, double saturate) {
    int w = cairo_image_surface_get_width (surf);
    int h = cairo_image_surface_get_height (surf);
    int stride = cairo_image_surface_get_stride (surf);
    unsigned char *data;
    float *ch[3], *tmp;

    cairo_surface_flush (surf);
    data = cairo_image_surface_get_data (surf);
    for (int c = 0; c < 3; c++)
        ch[c] = g_new (float, w * h);
    tmp = g_new (float, w * h);
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
            for (int c = 0; c < 3; c++)
                ch[c][y * w + x] = data[y * stride + 4 * x + c];
    for (int c = 0; c < 3; c++) {
        for (int p = 0; p < passes; p++) {
            for (int y = 0; y < h; y++)
                blur_line (ch[c], tmp, y * w, 1, w, radius);
            for (int x = 0; x < w; x++)
                blur_line (tmp, ch[c], x, w, h, radius);
        }
    }
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int i = y * w + x, o = y * stride + 4 * x;
            float b = ch[0][i], g = ch[1][i], r = ch[2][i];
            float lum = 0.0722f * b + 0.7152f * g + 0.2126f * r;
            data[o] = CLAMP ((int) (lum + (b - lum) * saturate), 0, 255);
            data[o + 1] = CLAMP ((int) (lum + (g - lum) * saturate), 0, 255);
            data[o + 2] = CLAMP ((int) (lum + (r - lum) * saturate), 0, 255);
        }
    }
    cairo_surface_mark_dirty (surf);
    for (int c = 0; c < 3; c++)
        g_free (ch[c]);
    g_free (tmp);
}

/* ---- ikony (stejne kresby jako luxos-greeter) ----------------------------------------- */
static void
icon_sleep (cairo_t *cr, double cx, double cy, double s) {
    double r = s * 0.40;
    cairo_save (cr);
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy, r, 0, 2 * G_PI);
    cairo_clip (cr);
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy, r, 0, 2 * G_PI);
    cairo_new_sub_path (cr);
    cairo_arc (cr, cx + r * 0.55, cy - r * 0.45, r * 0.82, 0, 2 * G_PI);
    cairo_set_fill_rule (cr, CAIRO_FILL_RULE_EVEN_ODD);
    cairo_fill (cr);
    cairo_restore (cr);
}

static void
icon_restart (cairo_t *cr, double cx, double cy, double s) {
    double r = s * 0.36, a0 = -G_PI / 2 + 0.25, a1 = -G_PI / 2 + 2 * G_PI - 0.75;
    double ex, ey, tx, ty, nx, ny, k = s * 0.2;
    cairo_set_line_width (cr, MAX (1.4, s * 0.085));
    cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy, r, a0, a1);
    cairo_stroke (cr);
    /* sipka na konci oblouku (ve smeru hodinovych rucicek) */
    ex = cx + r * cos (a1);
    ey = cy + r * sin (a1);
    tx = -sin (a1);
    ty = cos (a1);
    nx = cos (a1);
    ny = sin (a1);
    cairo_move_to (cr, ex + tx * k * 0.9, ey + ty * k * 0.9);
    cairo_line_to (cr, ex + nx * k * 0.75 - tx * k * 0.25, ey + ny * k * 0.75 - ty * k * 0.25);
    cairo_line_to (cr, ex - nx * k * 0.75 - tx * k * 0.25, ey - ny * k * 0.75 - ty * k * 0.25);
    cairo_close_path (cr);
    cairo_fill (cr);
}

static void
icon_power (cairo_t *cr, double cx, double cy, double s) {
    double r = s * 0.36;
    cairo_set_line_width (cr, MAX (1.4, s * 0.085));
    cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy + s * 0.03, r, -G_PI / 2 + 0.62, -G_PI / 2 - 0.62 + 2 * G_PI);
    cairo_stroke (cr);
    cairo_move_to (cr, cx, cy - s * 0.45);
    cairo_line_to (cr, cx, cy - s * 0.05);
    cairo_stroke (cr);
}

static void
icon_arrow (cairo_t *cr, double cx, double cy, double s) {
    cairo_set_line_width (cr, MAX (1.5, s * 0.11));
    cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);
    cairo_set_line_join (cr, CAIRO_LINE_JOIN_ROUND);
    cairo_move_to (cr, cx - s * 0.3, cy);
    cairo_line_to (cr, cx + s * 0.3, cy);
    cairo_move_to (cr, cx + s * 0.05, cy - s * 0.25);
    cairo_line_to (cr, cx + s * 0.3, cy);
    cairo_line_to (cr, cx + s * 0.05, cy + s * 0.25);
    cairo_stroke (cr);
}

static void
icon_person (cairo_t *cr, double cx, double cy, double s) {
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy - s * 0.16, s * 0.17, 0, 2 * G_PI);
    cairo_fill (cr);
    cairo_save (cr);
    cairo_translate (cr, cx, cy + s * 0.34);
    cairo_scale (cr, s * 0.32, s * 0.27);
    cairo_arc (cr, 0, 0, 1, G_PI, 2 * G_PI);
    cairo_restore (cr);
    cairo_close_path (cr);
    cairo_fill (cr);
}

/* dve postavy: prepnout uzivatele */
static void
icon_users (cairo_t *cr, double cx, double cy, double s) {
    /* zadni postava polopruhledne, predni plne */
    cairo_pattern_t *src = cairo_get_source (cr);
    double r, g, b, a;
    if (cairo_pattern_get_rgba (src, &r, &g, &b, &a) != CAIRO_STATUS_SUCCESS) {
        r = g = b = a = 1;
    }
    cairo_set_source_rgba (cr, r, g, b, a * 0.55);
    icon_person (cr, cx + s * 0.17, cy - s * 0.05, s * 0.8);
    cairo_set_source_rgba (cr, r, g, b, a);
    icon_person (cr, cx - s * 0.1, cy + s * 0.03, s * 0.92);
}

/* dvere se sipkou ven: odhlasit */
static void
icon_logout (cairo_t *cr, double cx, double cy, double s) {
    cairo_set_line_width (cr, MAX (1.4, s * 0.085));
    cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);
    cairo_set_line_join (cr, CAIRO_LINE_JOIN_ROUND);
    cairo_new_path (cr);
    cairo_move_to (cr, cx + s * 0.02, cy - s * 0.36);
    cairo_line_to (cr, cx - s * 0.36, cy - s * 0.36);
    cairo_line_to (cr, cx - s * 0.36, cy + s * 0.36);
    cairo_line_to (cr, cx + s * 0.02, cy + s * 0.36);
    cairo_stroke (cr);
    icon_arrow (cr, cx + s * 0.12, cy, s * 0.75);
}

static void
icon_wifi (cairo_t *cr, double x, double y, double s) {
    double cx = x + s / 2, cy = y + s * 0.86;
    static const double rs[3] = { 0.3, 0.55, 0.8 };
    cairo_set_line_width (cr, MAX (1.3, s * 0.11));
    cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);
    for (int i = 0; i < 3; i++) {
        cairo_new_path (cr);
        cairo_arc (cr, cx, cy, s * rs[i] * 0.85, -G_PI * 0.75, -G_PI * 0.25);
        cairo_stroke (cr);
    }
    cairo_arc (cr, cx, cy, s * 0.08, 0, 2 * G_PI);
    cairo_fill (cr);
}

static void
icon_wired (cairo_t *cr, double x, double y, double s) {
    double b = s * 0.26;
    rounded (cr, x + s / 2 - b / 2, y + s * 0.08, b, b, b * 0.2);
    rounded (cr, x + s * 0.08, y + s * 0.66, b, b, b * 0.2);
    rounded (cr, x + s * 0.92 - b, y + s * 0.66, b, b, b * 0.2);
    cairo_fill (cr);
    cairo_set_line_width (cr, MAX (1.2, s * 0.08));
    cairo_move_to (cr, x + s / 2, y + s * 0.08 + b);
    cairo_line_to (cr, x + s / 2, y + s * 0.52);
    cairo_move_to (cr, x + s * 0.08 + b / 2, y + s * 0.66);
    cairo_line_to (cr, x + s * 0.08 + b / 2, y + s * 0.52);
    cairo_line_to (cr, x + s * 0.92 - b / 2, y + s * 0.52);
    cairo_line_to (cr, x + s * 0.92 - b / 2, y + s * 0.66);
    cairo_stroke (cr);
}

static void
icon_battery (cairo_t *cr, double x, double y, double h, int level, gboolean charging) {
    double w = h * 2.05, lw = MAX (1.0, h * 0.09), inner, frac;
    cairo_set_line_width (cr, lw);
    cairo_set_source_rgba (cr, 1, 1, 1, 0.55);
    rounded (cr, x + lw / 2, y + lw / 2, w - h * 0.22 - lw, h - lw, h * 0.26);
    cairo_stroke (cr);
    rounded (cr, x + w - h * 0.2, y + h * 0.33, h * 0.14, h * 0.34, h * 0.06);
    cairo_fill (cr);
    inner = w - h * 0.22 - lw * 2 - h * 0.16;
    frac = CLAMP (level / 100.0, 0.0, 1.0);
    if (level <= 15 && !charging)
        cairo_set_source_rgba (cr, 1.0, 0.36, 0.33, 1);
    else
        cairo_set_source_rgba (cr, 1, 1, 1, 0.95);
    rounded (cr, x + lw + h * 0.08, y + lw + h * 0.08, MAX (h * 0.12, inner * frac), h - 2 * lw - h * 0.16, h * 0.14);
    cairo_fill (cr);
    if (charging) {
        double cx = x + (w - h * 0.22) / 2, cy = y + h / 2;
        cairo_set_source_rgba (cr, 0, 0, 0, 0.75);
        cairo_move_to (cr, cx + h * 0.08, cy - h * 0.42);
        cairo_line_to (cr, cx - h * 0.2, cy + h * 0.06);
        cairo_line_to (cr, cx - h * 0.01, cy + h * 0.06);
        cairo_line_to (cr, cx - h * 0.08, cy + h * 0.42);
        cairo_line_to (cr, cx + h * 0.2, cy - h * 0.06);
        cairo_line_to (cr, cx + h * 0.01, cy - h * 0.06);
        cairo_close_path (cr);
        cairo_fill (cr);
    }
}

/* ---- tapeta: stejne poradi jako setric (luxos-screensaver desktop_wallpaper) ---------- */
static char *
desktop_wallpaper (const char *model) {
    XfconfChannel *ch = xfconf_channel_get ("xfce4-desktop");
    GHashTable *props = ch ? xfconf_channel_get_properties (ch, "/backdrop/screen0") : NULL;
    GHashTable *have = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);
    GPtrArray *keys = g_ptr_array_new_with_free_func (g_free);
    GList *names = NULL;
    char *found = NULL, *cfg, *mode = NULL;
    const char *prefix = "/backdrop/screen0/";
    GHashTableIter it;
    gpointer k, v;

    if (props) {
        g_hash_table_iter_init (&it, props);
        while (g_hash_table_iter_next (&it, &k, &v)) {
            const char *prop = k;
            GValue *val = v;
            size_t n = strlen (prop);
            if (g_str_has_prefix (prop, "/backdrop/screen0/monitor") && g_str_has_suffix (prop, "/last-image")
                && G_VALUE_HOLDS_STRING (val) && g_value_get_string (val) && *g_value_get_string (val)) {
                char *name = g_strndup (prop + strlen (prefix), n - strlen (prefix) - strlen ("/last-image"));
                char *path = g_strstrip (g_strdup (g_value_get_string (val)));
                g_hash_table_replace (have, name, path);
            }
        }
        g_hash_table_destroy (props);
    }
    if (model && *model) {
        g_ptr_array_add (keys, g_strdup_printf ("monitor%s/workspace0", model));
        g_ptr_array_add (keys, g_strdup_printf ("monitor%s", model));
    }
    g_ptr_array_add (keys, g_strdup ("monitor0/workspace0"));
    names = g_list_sort (g_hash_table_get_keys (have), (GCompareFunc) g_strcmp0);
    for (GList *l = names; l; l = l->next)
        if (g_str_has_suffix (l->data, "/workspace0"))
            g_ptr_array_add (keys, g_strdup (l->data));
    for (GList *l = names; l; l = l->next)
        g_ptr_array_add (keys, g_strdup (l->data));
    g_list_free (names);
    for (guint i = 0; i < keys->len && !found; i++) {
        const char *p = g_hash_table_lookup (have, g_ptr_array_index (keys, i));
        if (p && g_file_test (p, G_FILE_TEST_IS_REGULAR))
            found = g_strdup (p);
    }
    g_ptr_array_unref (keys);
    g_hash_table_destroy (have);
    if (found)
        return found;
    /* bez tapety: vychozi tapeta LuxOS aktualniho rezimu (svetly/tmavy) */
    cfg = g_build_filename (g_get_user_config_dir (), "luxos", "appearance", NULL);
    if (g_file_get_contents (cfg, &mode, NULL, NULL))
        g_strstrip (mode);
    found = g_strdup_printf ("/usr/share/backgrounds/luxos/luxos-%s.jpg",
                             g_strcmp0 (mode, "dark") == 0 ? "dark" : "light");
    g_free (mode);
    g_free (cfg);
    return found;
}

static void
build_backgrounds (LuxLock *ll, const char *model) {
    char *path = desktop_wallpaper (model);
    GdkPixbuf *pb = gdk_pixbuf_new_from_file (path, NULL);
    int W = ll->W, H = ll->H, s = ll->scale, sh = 64, sw;
    cairo_t *cr;
    cairo_surface_t *small;

    if (pb == NULL)
        pb = gdk_pixbuf_new_from_file ("/usr/share/backgrounds/luxos/luxos-light.jpg", NULL);
    g_clear_pointer (&ll->bg_surf, cairo_surface_destroy);
    g_clear_pointer (&ll->blur_surf, cairo_surface_destroy);
    ll->bg_surf = cairo_image_surface_create (CAIRO_FORMAT_RGB24, W * s, H * s);
    cairo_surface_set_device_scale (ll->bg_surf, s, s);
    cr = cairo_create (ll->bg_surf);
    if (pb) {
        int pw = gdk_pixbuf_get_width (pb), ph = gdk_pixbuf_get_height (pb);
        double sc = MAX ((double) W / pw, (double) H / ph);
        int tw = MAX (1, (int) round (pw * sc)), th = MAX (1, (int) round (ph * sc));
        GdkPixbuf *scaled = gdk_pixbuf_scale_simple (pb, tw * s, th * s, GDK_INTERP_BILINEAR);
        cairo_save (cr);
        cairo_scale (cr, 1.0 / s, 1.0 / s);
        gdk_cairo_set_source_pixbuf (cr, scaled, ((W - tw) / 2.0) * s, ((H - th) / 2.0) * s);
        cairo_paint (cr);
        cairo_restore (cr);
        g_object_unref (scaled);
        g_object_unref (pb);
    } else {
        /* nahradni prechod v barvach LuxOS */
        cairo_pattern_t *g = cairo_pattern_create_linear (0, 0, W, H);
        cairo_pattern_add_color_stop_rgb (g, 0, 0.10, 0.11, 0.25);
        cairo_pattern_add_color_stop_rgb (g, 0.6, 0.27, 0.20, 0.52);
        cairo_pattern_add_color_stop_rgb (g, 1, 0.55, 0.36, 0.78);
        cairo_set_source (cr, g);
        cairo_paint (cr);
        cairo_pattern_destroy (g);
    }
    cairo_destroy (cr);

    /* rozmazani: zmensit na ~64 px vysky, rozmazat, zvetsit bilinearne */
    sw = MAX (8, (int) round ((double) W * sh / H));
    small = cairo_image_surface_create (CAIRO_FORMAT_RGB24, sw, sh);
    cr = cairo_create (small);
    cairo_scale (cr, (double) sw / W, (double) sh / H);
    cairo_set_source_surface (cr, ll->bg_surf, 0, 0);
    cairo_pattern_set_filter (cairo_get_source (cr), CAIRO_FILTER_GOOD);
    cairo_paint (cr);
    cairo_destroy (cr);
    box_blur (small, 2, 3, 1.25);
    ll->blur_surf = cairo_image_surface_create (CAIRO_FORMAT_RGB24, W * s, H * s);
    cairo_surface_set_device_scale (ll->blur_surf, s, s);
    cr = cairo_create (ll->blur_surf);
    cairo_scale (cr, (double) W / sw, (double) H / sh);
    cairo_set_source_surface (cr, small, 0, 0);
    cairo_pattern_set_filter (cairo_get_source (cr), CAIRO_FILTER_BILINEAR);
    cairo_pattern_set_extend (cairo_get_source (cr), CAIRO_EXTEND_PAD);
    cairo_paint (cr);
    cairo_destroy (cr);
    cairo_surface_destroy (small);
    g_free (path);
}

/* matny panel: vyrez rozmazane tapety pod widgetem + svetly zavoj + jemny okraj */
static void
frost (LuxLock *ll, GtkWidget *w, cairo_t *cr, double x, double y, double wd, double h, double r,
       double tint, double border) {
    int ox = 0, oy = 0;
    gtk_widget_translate_coordinates (w, ll->bg, 0, 0, &ox, &oy);
    cairo_save (cr);
    rounded (cr, x, y, wd, h, r);
    cairo_clip (cr);
    if (ll->blur_surf) {
        cairo_set_source_surface (cr, ll->blur_surf, -ox, -oy);
        cairo_paint (cr);
    }
    cairo_set_source_rgba (cr, 1, 1, 1, tint);
    cairo_paint (cr);
    cairo_restore (cr);
    if (border > 0) {
        rounded (cr, x + 0.5, y + 0.5, wd - 1, h - 1, r);
        cairo_set_source_rgba (cr, 1, 1, 1, border);
        cairo_set_line_width (cr, 1);
        cairo_stroke (cr);
    }
}

static void
focus_ring (cairo_t *cr, double x, double y, double w, double h, double r) {
    rounded (cr, x + 1, y + 1, w - 2, h - 2, r);
    cairo_set_source_rgba (cr, 1, 1, 1, 0.75);
    cairo_set_line_width (cr, 2);
    cairo_stroke (cr);
}

static gboolean
draw_frost_widget (GtkWidget *w, cairo_t *cr, LuxLock *ll, double radius_frac, double tint) {
    int aw = gtk_widget_get_allocated_width (w), ah = gtk_widget_get_allocated_height (w);
    gboolean hover = (gtk_widget_get_state_flags (w) & GTK_STATE_FLAG_PRELIGHT) != 0;
    frost (ll, w, cr, 0, 0, aw, ah, ah * radius_frac, tint + (hover ? 0.06 : 0), 0.18);
    if (gtk_widget_has_visible_focus (w))
        focus_ring (cr, 0, 0, aw, ah, ah * radius_frac);
    return FALSE;
}

static gboolean
draw_kbd (GtkWidget *w, cairo_t *cr, LuxLock *ll) {
    return draw_frost_widget (w, cr, ll, 0.5, 0.16);
}

static gboolean
draw_bg (GtkWidget *w, cairo_t *cr, LuxLock *ll) {
    double e = ease (ll->t), u = ll->u, cx, y0, alpha, cy;
    time_t now = time (NULL);
    struct tm tm;
    char clock[64] = "", date[256] = "";
    PangoLayout *dl, *cl;
    PangoRectangle ink, logi;

    if (ll->bg_surf) {
        cairo_set_source_surface (cr, ll->bg_surf, 0, 0);
        cairo_paint (cr);
    }
    /* jemne ztmaveni pri prihlaseni */
    cairo_set_source_rgba (cr, 0, 0, 0, 0.10 + 0.14 * e);
    cairo_paint (cr);
    localtime_r (&now, &tm);
    if (!strftime (clock, sizeof clock, ll->clock_fmt, &tm))
        strftime (clock, sizeof clock, "%H:%M", &tm);
    if (!strftime (date, sizeof date, ll->date_fmt, &tm))
        strftime (date, sizeof date, "%x", &tm);
    {
        /* strftime vraci text v kodovani locale */
        char *d8 = g_locale_to_utf8 (date, -1, NULL, NULL, NULL);
        if (d8) {
            g_strlcpy (date, d8, sizeof date);
            g_free (d8);
        }
    }
    cx = ll->W / 2.0;
    y0 = ll->H * 0.105 - e * ll->H * 0.045;
    alpha = 1.0 - 0.12 * e;
    dl = text_layout (cr, date, 27 * u, PANGO_WEIGHT_SEMIBOLD, ll->font);
    pango_layout_get_pixel_extents (dl, &ink, &logi);
    shadow_text (cr, dl, cx - logi.width / 2.0, y0, alpha * 0.92, 2 * u);
    cl = text_layout (cr, clock, 180 * u, PANGO_WEIGHT_ULTRALIGHT, ll->font);
    {
        PangoRectangle cink;
        pango_layout_get_pixel_extents (cl, &cink, NULL);
        /* horni okraj cislic tesne pod datum */
        cy = y0 + logi.height + 14 * u - cink.y;
        shadow_text (cr, cl, cx - cink.x - cink.width / 2.0, cy, alpha, 4 * u);
    }
    g_object_unref (dl);
    g_object_unref (cl);
    return FALSE;
}

static gboolean
draw_pw (GtkWidget *w, cairo_t *cr, LuxLock *ll) {
    /* pole pro heslo: matny oval + vlastni zastupny text (GTK 3 ho u aktivniho pole skryva) */
    draw_frost_widget (w, cr, ll, 0.5, 0.20);
    if (ll->placeholder && *ll->placeholder && !*gtk_entry_get_text (GTK_ENTRY (ll->entry))) {
        int ex = 0, ey = 0;
        int ew = gtk_widget_get_allocated_width (ll->entry), eh = gtk_widget_get_allocated_height (ll->entry);
        PangoLayout *lay = text_layout (cr, ll->placeholder, ll->sz.pw_font, PANGO_WEIGHT_NORMAL, ll->font);
        PangoRectangle lg;
        gtk_widget_translate_coordinates (ll->entry, w, 0, 0, &ex, &ey);
        pango_layout_set_width (lay, MAX (1, ew - ll->sz.pw_pad - 4) * PANGO_SCALE);
        pango_layout_set_ellipsize (lay, PANGO_ELLIPSIZE_END);
        pango_layout_get_pixel_extents (lay, NULL, &lg);
        cairo_new_path (cr);
        cairo_move_to (cr, ex + ll->sz.pw_pad + 2, ey + (eh - lg.height) / 2.0);
        cairo_set_source_rgba (cr, 1, 1, 1, gtk_widget_is_sensitive (ll->entry) ? 0.62 : 0.35);
        pango_cairo_show_layout (cr, lay);
        g_object_unref (lay);
    }
    return FALSE;
}

static gboolean
draw_go (GtkWidget *area, cairo_t *cr, LuxLock *ll) {
    int ah = gtk_widget_get_allocated_height (area), aw = gtk_widget_get_allocated_width (area);
    double d = ah - MAX (8, (int) round (ll->sz.pw_h * 0.26));
    double cx = aw / 2.0 - 2, cy = ah / 2.0;
    gboolean has = *gtk_entry_get_text (GTK_ENTRY (ll->entry)) != '\0';
    gboolean hover = (gtk_widget_get_state_flags (ll->go) & GTK_STATE_FLAG_PRELIGHT) != 0;
    cairo_arc (cr, cx, cy, d / 2, 0, 2 * G_PI);
    cairo_set_source_rgba (cr, 1, 1, 1, (has ? 0.30 : 0.12) + (hover ? 0.1 : 0));
    cairo_fill (cr);
    cairo_set_source_rgba (cr, 1, 1, 1, has ? 0.95 : 0.55);
    icon_arrow (cr, cx, cy, d * 0.62);
    if (gtk_widget_has_visible_focus (ll->go)) {
        cairo_new_path (cr);
        cairo_arc (cr, cx, cy, d / 2 + 2, 0, 2 * G_PI);
        cairo_set_source_rgba (cr, 1, 1, 1, 0.8);
        cairo_set_line_width (cr, 1.5);
        cairo_stroke (cr);
    }
    return FALSE;
}

static gboolean
draw_round (GtkWidget *area, cairo_t *cr, Round *rb) {
    LuxLock *ll = rb->ll;
    int aw = gtk_widget_get_allocated_width (area), ah = gtk_widget_get_allocated_height (area);
    double d = ll->sz.round, x = (aw - d) / 2, y = (ah - d) / 2;
    GtkStateFlags fl = gtk_widget_get_state_flags (rb->button);
    double tint = 0.16 + ((fl & GTK_STATE_FLAG_PRELIGHT) ? 0.10 : 0) + ((fl & GTK_STATE_FLAG_ACTIVE) ? 0.12 : 0);
    frost (ll, area, cr, x, y, d, d, d / 2, tint, 0.18);
    if (gtk_widget_has_visible_focus (rb->button)) {
        cairo_new_path (cr);
        cairo_arc (cr, aw / 2.0, ah / 2.0, d / 2 + 2.5, 0, 2 * G_PI);
        cairo_set_source_rgba (cr, 1, 1, 1, 0.8);
        cairo_set_line_width (cr, 2);
        cairo_stroke (cr);
    }
    cairo_set_source_rgba (cr, 1, 1, 1, 0.95);
    rb->icon (cr, aw / 2.0, ah / 2.0, d * 0.46);
    return FALSE;
}

static gboolean
draw_avatar (GtkWidget *area, cairo_t *cr, LuxLock *ll) {
    int aw = gtk_widget_get_allocated_width (area), ah = gtk_widget_get_allocated_height (area);
    int d = ll->sz.avatar, s = ll->scale;
    double cx = aw / 2.0, cy = ah / 2.0;
    gboolean hover = (gtk_widget_get_state_flags (ll->user_btn) & GTK_STATE_FLAG_PRELIGHT) != 0;

    /* obrazek predpocitany v presne velikosti (HYPER), jako v luxos-greeter */
    if (ll->face && ll->face_size != d * s) {
        int pw = gdk_pixbuf_get_width (ll->face), ph = gdk_pixbuf_get_height (ll->face);
        double sc = MAX ((double) d * s / pw, (double) d * s / ph);
        GdkPixbuf *p = gdk_pixbuf_scale_simple (ll->face, MAX (1, (int) round (pw * sc)),
                                                MAX (1, (int) round (ph * sc)), GDK_INTERP_HYPER);
        g_clear_pointer (&ll->face_surf, cairo_surface_destroy);
        ll->face_surf = gdk_cairo_surface_create_from_pixbuf (p, s, NULL);
        ll->face_size = d * s;
        g_object_unref (p);
    }
    /* stin */
    cairo_arc (cr, cx, cy + d * 0.03, d / 2.0 + 1, 0, 2 * G_PI);
    cairo_set_source_rgba (cr, 0, 0, 0, 0.18);
    cairo_fill (cr);
    cairo_save (cr);
    cairo_arc (cr, cx, cy, d / 2.0, 0, 2 * G_PI);
    cairo_clip (cr);
    if (ll->face_surf) {
        double fw = cairo_image_surface_get_width (ll->face_surf) / (double) s;
        double fh = cairo_image_surface_get_height (ll->face_surf) / (double) s;
        cairo_set_source_surface (cr, ll->face_surf, cx - fw / 2, cy - fh / 2);
        cairo_pattern_set_filter (cairo_get_source (cr), CAIRO_FILTER_GOOD);
        cairo_paint (cr);
    } else {
        cairo_pattern_t *g = cairo_pattern_create_linear (cx - d / 2.0, cy - d / 2.0, cx + d / 2.0, cy + d / 2.0);
        const char *name = ll->real_name ? ll->real_name : "?";
        char initial[8] = "?";
        PangoLayout *lay;
        PangoRectangle ink;
        cairo_pattern_add_color_stop_rgb (g, 0, 0.30, 0.52, 1.0);   /* modra */
        cairo_pattern_add_color_stop_rgb (g, 1, 0.66, 0.42, 0.98);  /* fialova */
        cairo_set_source (cr, g);
        cairo_paint (cr);
        cairo_pattern_destroy (g);
        while (*name && g_unichar_isspace (g_utf8_get_char (name)))
            name = g_utf8_next_char (name);
        if (*name) {
            gunichar c = g_unichar_toupper (g_utf8_get_char (name));
            initial[g_unichar_to_utf8 (c, initial)] = '\0';
        }
        lay = text_layout (cr, initial, d * 0.44, PANGO_WEIGHT_MEDIUM, ll->font);
        pango_layout_get_pixel_extents (lay, &ink, NULL);
        cairo_move_to (cr, cx - ink.x - ink.width / 2.0, cy - ink.y - ink.height / 2.0);
        cairo_set_source_rgba (cr, 1, 1, 1, 0.97);
        pango_cairo_show_layout (cr, lay);
        g_object_unref (lay);
    }
    cairo_restore (cr);
    cairo_new_path (cr);
    cairo_arc (cr, cx, cy, d / 2.0 - 0.5, 0, 2 * G_PI);
    cairo_set_source_rgba (cr, 1, 1, 1, 0.22);
    cairo_set_line_width (cr, hover ? 1.5 : 1);
    cairo_stroke (cr);
    return FALSE;
}

static gboolean
draw_battery (GtkWidget *area, cairo_t *cr, LuxLock *ll) {
    double h = ll->sz.status * 0.78;
    if (ll->has_bat)
        icon_battery (cr, 1, (gtk_widget_get_allocated_height (area) - h) / 2, h, ll->bat_level, ll->bat_charging);
    return FALSE;
}

static gboolean
draw_net (GtkWidget *area, cairo_t *cr, LuxLock *ll) {
    int s = ll->sz.status;
    double x = (gtk_widget_get_allocated_width (area) - s) / 2.0;
    double y = (gtk_widget_get_allocated_height (area) - s) / 2.0;
    if (!ll->net)
        return FALSE;
    cairo_set_source_rgba (cr, 1, 1, 1, 0.95);
    if (ll->net == 2)
        icon_wifi (cr, x, y, s);
    else
        icon_wired (cr, x, y, s);
    return FALSE;
}

/* ---- avatar a jmeno ------------------------------------------------------------------- */
static char *
accounts_icon_file (void) {
    GDBusConnection *bus = g_bus_get_sync (G_BUS_TYPE_SYSTEM, NULL, NULL);
    GVariant *r, *v;
    char *path = NULL, *user = NULL;
    if (!bus)
        return NULL;
    r = g_dbus_connection_call_sync (bus, "org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                                     "org.freedesktop.Accounts", "FindUserByName",
                                     g_variant_new ("(s)", g_get_user_name ()), G_VARIANT_TYPE ("(o)"),
                                     G_DBUS_CALL_FLAGS_NONE, 2000, NULL, NULL);
    if (r) {
        g_variant_get (r, "(o)", &user);
        g_variant_unref (r);
        r = g_dbus_connection_call_sync (bus, "org.freedesktop.Accounts", user, "org.freedesktop.DBus.Properties",
                                         "Get", g_variant_new ("(ss)", "org.freedesktop.Accounts.User", "IconFile"),
                                         G_VARIANT_TYPE ("(v)"), G_DBUS_CALL_FLAGS_NONE, 2000, NULL, NULL);
        if (r) {
            g_variant_get (r, "(v)", &v);
            if (g_variant_is_of_type (v, G_VARIANT_TYPE_STRING))
                path = g_variant_dup_string (v, NULL);
            g_variant_unref (v);
            g_variant_unref (r);
        }
        g_free (user);
    }
    g_object_unref (bus);
    return path;
}

static void
load_face (LuxLock *ll) {
    const char *demo = g_getenv ("LUXOS_LOCK_DEMO_AVATAR");
    char *paths[3] = { NULL, NULL, NULL };
    paths[0] = demo ? g_strdup (demo) : accounts_icon_file ();
    paths[1] = g_build_filename (g_get_home_dir (), ".face", NULL);
    for (int i = 0; i < 2 && !ll->face; i++) {
        if (paths[i] && g_file_test (paths[i], G_FILE_TEST_IS_REGULAR) && g_access (paths[i], R_OK) == 0)
            ll->face = gdk_pixbuf_new_from_file (paths[i], NULL);
    }
    g_free (paths[0]);
    g_free (paths[1]);
}

static char *
user_real_name (void) {
    const char *demo = g_getenv ("LUXOS_LOCK_DEMO_NAME");
    const char *name = g_get_real_name ();
    if (demo && *demo)
        return g_strdup (demo);
    if (name == NULL || !*name || g_strcmp0 (name, "Unknown") == 0)
        name = g_get_user_name ();
    return g_locale_to_utf8 (name, -1, NULL, NULL, NULL);
}

gboolean
lux_lock_multi_user (void) {
    struct passwd *pw;
    int n = 0;
    const char *demo = g_getenv ("LUXOS_LOCK_DEMO_USERS");
    if (demo && *demo)
        return atoi (demo) > 1;
    setpwent ();
    while ((pw = getpwent ()) != NULL) {
        if (pw->pw_uid < 1000 || pw->pw_uid >= 60000 || !pw->pw_shell)
            continue;
        if (g_str_has_suffix (pw->pw_shell, "nologin") || g_str_has_suffix (pw->pw_shell, "false"))
            continue;
        n++;
    }
    endpwent ();
    return n > 1;
}

/* ---- stav systemu (baterie, sit) ------------------------------------------------------ */
static char *
read_file (const char *path) {
    char *s = NULL;
    if (!g_file_get_contents (path, &s, NULL, NULL))
        return NULL;
    return g_strstrip (s);
}

static gint
cmp_str_ptr (gconstpointer a, gconstpointer b) {
    return g_strcmp0 (*(const char *const *) a, *(const char *const *) b);
}

static void
battery_state (LuxLock *ll) {
    GDir *d = g_dir_open ("/sys/class/power_supply", 0, NULL);
    GPtrArray *names = g_ptr_array_new_with_free_func (g_free);
    const char *n;
    ll->has_bat = FALSE;
    if (!d)
        goto out;
    while ((n = g_dir_read_name (d)))
        g_ptr_array_add (names, g_strdup (n));
    g_dir_close (d);
    g_ptr_array_sort (names, cmp_str_ptr);
    for (guint i = 0; i < names->len && !ll->has_bat; i++) {
        const char *name = g_ptr_array_index (names, i);
        char *base = g_build_filename ("/sys/class/power_supply", name, NULL);
        char *p1 = g_build_filename (base, "type", NULL), *p2 = g_build_filename (base, "scope", NULL);
        char *type = read_file (p1), *scope = read_file (p2);
        if (g_strcmp0 (type, "Battery") == 0 && g_strcmp0 (scope, "Device") != 0) {
            char *p3 = g_build_filename (base, "capacity", NULL), *p4 = g_build_filename (base, "status", NULL);
            char *cap = read_file (p3), *st = read_file (p4);
            if (cap) {
                ll->has_bat = TRUE;
                ll->bat_level = atoi (cap);
                ll->bat_charging = g_strcmp0 (st, "Charging") == 0;
            }
            g_free (cap);
            g_free (st);
            g_free (p3);
            g_free (p4);
        }
        g_free (type);
        g_free (scope);
        g_free (p1);
        g_free (p2);
        g_free (base);
    }
out:
    g_ptr_array_unref (names);
}

static void
network_state (LuxLock *ll) {
    GDir *d = g_dir_open ("/sys/class/net", 0, NULL);
    const char *n;
    ll->net = 0;
    if (!d)
        return;
    while ((n = g_dir_read_name (d)) && ll->net != 2) {
        char *base, *p, *st;
        if (g_strcmp0 (n, "lo") == 0)
            continue;
        base = g_build_filename ("/sys/class/net", n, NULL);
        p = g_build_filename (base, "operstate", NULL);
        st = read_file (p);
        if (g_strcmp0 (st, "up") == 0) {
            char *w1 = g_build_filename (base, "wireless", NULL), *w2 = g_build_filename (base, "phy80211", NULL);
            char *dev = g_build_filename (base, "device", NULL);
            if (g_file_test (w1, G_FILE_TEST_IS_DIR) || g_file_test (w2, G_FILE_TEST_EXISTS))
                ll->net = 2;
            else if (g_file_test (dev, G_FILE_TEST_EXISTS))
                ll->net = 1;
            g_free (w1);
            g_free (w2);
            g_free (dev);
        }
        g_free (st);
        g_free (p);
        g_free (base);
    }
    g_dir_close (d);
}

/* ---- klavesnice (rozlozeni ze serveru X, prepinani skupin XKB) ------------------------ */
static void
kbd_load (LuxLock *ll) {
#ifdef ENABLE_X11
    GdkDisplay *disp = gdk_display_get_default ();
    if (GDK_IS_X11_DISPLAY (disp)) {
        XklEngine *engine = xkl_engine_get_instance (GDK_DISPLAY_XDISPLAY (disp));
        XklConfigRec *rec = xkl_config_rec_new ();
        if (engine && xkl_config_rec_get_from_server (rec, engine) && rec->layouts) {
            ll->layouts = g_strdupv (rec->layouts);
            ll->variants = rec->variants ? g_strdupv (rec->variants) : NULL;
            ll->n_layouts = g_strv_length (ll->layouts);
        }
        g_object_unref (rec);
    }
#endif
    if (ll->n_layouts == 0) {
        g_strfreev (ll->layouts);
        ll->layouts = g_new0 (char *, 2);
        ll->layouts[0] = g_strdup ("us");
        ll->n_layouts = 1;
    }
}

static int
kbd_group (LuxLock *ll) {
#ifdef ENABLE_X11
    GdkDisplay *disp = gdk_display_get_default ();
    if (GDK_IS_X11_DISPLAY (disp)) {
        XkbStateRec st;
        if (XkbGetState (GDK_DISPLAY_XDISPLAY (disp), XkbUseCoreKbd, &st) == Success)
            return st.group % MAX (1, ll->n_layouts);
    }
#endif
    return 0;
}

static void
kbd_update (LuxLock *ll) {
    int i = MIN (kbd_group (ll), ll->n_layouts - 1), dup = 0;
    const char *lay = ll->layouts[i];
    const char *var = ll->variants && (int) g_strv_length (ll->variants) > i ? ll->variants[i] : "";
    char *up = g_ascii_strup (lay, -1), *label;
    for (int j = 0; j < ll->n_layouts; j++)
        dup += g_strcmp0 (ll->layouts[j], lay) == 0;
    label = dup > 1 && var && *var ? g_strdup_printf ("%s %s", up, var) : g_strdup (up);
    if (g_strcmp0 (gtk_label_get_text (GTK_LABEL (ll->kbd_label)), label) != 0)
        gtk_label_set_text (GTK_LABEL (ll->kbd_label), label);
    g_free (label);
    g_free (up);
}

static void
kbd_next (GtkButton *b, LuxLock *ll) {
#ifdef ENABLE_X11
    GdkDisplay *disp = gdk_display_get_default ();
    if (GDK_IS_X11_DISPLAY (disp) && ll->n_layouts > 1) {
        XkbLockGroup (GDK_DISPLAY_XDISPLAY (disp), XkbUseCoreKbd, (kbd_group (ll) + 1) % ll->n_layouts);
        XFlush (GDK_DISPLAY_XDISPLAY (disp));
    }
#endif
    kbd_update (ll);
    gtk_widget_grab_focus (ll->entry);
}

/* ---- hlasky --------------------------------------------------------------------------- */
static void
show_hint (LuxLock *ll, const char *text, gboolean error, gboolean caps) {
    GtkStyleContext *ctx = gtk_widget_get_style_context (ll->hint);
    ll->caps_hint = caps && text && *text;
    if (!error)
        ll->error_shown = FALSE;
    gtk_label_set_text (GTK_LABEL (ll->hint), text ? text : "");
    if (error)
        gtk_style_context_add_class (ctx, "error");
    else
        gtk_style_context_remove_class (ctx, "error");
}

void
lux_lock_hint (LuxLock *ll, const char *text, gboolean error) {
    show_hint (ll, text, error, FALSE);
    if (error)
        ll->error_shown = TRUE;
}

void
lux_lock_update_caps (LuxLock *ll, gboolean on) {
    if (on && !ll->error_shown && !*gtk_label_get_text (GTK_LABEL (ll->hint)))
        show_hint (ll, lux_tr ("Caps Lock is on"), FALSE, TRUE);
    else if (!on && ll->caps_hint)
        show_hint (ll, "", FALSE, FALSE);
}

void
lux_lock_set_status_message (LuxLock *ll, const char *text) {
    gtk_label_set_text (GTK_LABEL (ll->status_msg), text ? text : "");
    gtk_widget_set_visible (ll->status_msg, text && *text);
}

static gboolean
shake_step (gpointer data) {
    LuxLock *ll = data;
    double p = (g_get_monotonic_time () - ll->shake_start) / 480000.0;
    int dx;
    if (p >= 1) {
        gtk_widget_set_margin_start (ll->pw, 0);
        gtk_widget_set_margin_end (ll->pw, 0);
        ll->shake_id = 0;
        return G_SOURCE_REMOVE;
    }
    dx = (int) round (sin (p * G_PI * 8) * (1 - p) * 16 * ll->u);
    /* posun doprava = vetsi levy okraj; GTK_ALIGN_CENTER drzi stred */
    gtk_widget_set_margin_start (ll->pw, MAX (0, 2 * dx));
    gtk_widget_set_margin_end (ll->pw, MAX (0, -2 * dx));
    return G_SOURCE_CONTINUE;
}

static void
shake (LuxLock *ll) {
    if (ll->shake_id)
        g_source_remove (ll->shake_id);
    ll->shake_start = g_get_monotonic_time ();
    ll->shake_id = g_timeout_add (16, shake_step, ll);
}

/* pam_faillock: ucet docasne zamceny -> zbyvajici minuty (0 = neznamo), jinak -1 */
static int
account_locked (const char *text) {
    static const char *keys[] = { "account is locked", "is locked due to", "left to unlock", "zamčen",
                                  "uzamčen", "zablokov", "do odemčení", NULL };
    char *t = g_utf8_strdown (text ? text : "", -1);
    int mins = -1;
    for (int i = 0; keys[i] && mins < 0; i++)
        if (strstr (t, keys[i]))
            mins = 0;
    if (mins == 0) {
        GRegex *re = g_regex_new ("(\\d+)\\s*(?:minute|minut)", 0, 0, NULL);
        GMatchInfo *mi = NULL;
        if (re && g_regex_match (re, t, 0, &mi)) {
            char *num = g_match_info_fetch (mi, 1);
            mins = atoi (num);
            g_free (num);
        }
        if (mi)
            g_match_info_free (mi);
        if (re)
            g_regex_unref (re);
    }
    g_free (t);
    return mins;
}

void
lux_lock_pam_message (LuxLock *ll, const char *text, gboolean is_error) {
    int mins = account_locked (text);
    if (text == NULL || !*text)
        return;
    /* zamceny ucet: neprojde ani spravne heslo, proto to rict jasne */
    if (mins >= 0) {
        g_free (ll->locked_hint);
        ll->locked_hint = mins > 0
            ? g_strdup_printf (lux_tr ("Too many failed attempts. The account is locked for %d min, then try again."), mins)
            : g_strdup (lux_tr ("Too many failed attempts. Wait a moment, then try again."));
        lux_lock_hint (ll, ll->locked_hint, TRUE);
        return;
    }
    /* zpravy pam_fprintd prichazeji pred vyzvou k heslu */
    if (ll->fprint && !ll->prompted) {
        if (!is_error) {
            ll->fp_wait = TRUE;
            if (!ll->error_shown)
                show_hint (ll, lux_tr ("Touch the fingerprint sensor or enter your password"), FALSE, FALSE);
            return;
        }
        if (ll->fp_wait) {
            lux_lock_hint (ll, lux_tr ("Fingerprint not recognized. Try again or enter your password."), TRUE);
            shake (ll);
            return;
        }
    }
    lux_lock_hint (ll, text, is_error);
}

void
lux_lock_set_prompt (LuxLock *ll, const char *text, gboolean secret) {
    char *t = g_strstrip (g_strdup (text ? text : ""));
    size_t n = strlen (t);
    while (n > 0 && t[n - 1] == ':')
        t[--n] = '\0';
    g_strstrip (t);
    ll->prompted = TRUE;
    g_free (ll->placeholder);
    if (secret && (!*t || !g_ascii_strcasecmp (t, "password")))
        ll->placeholder = g_strdup (lux_tr ("Enter Password"));
    else
        ll->placeholder = g_strdup (t);
    g_free (t);
    if (ll->fp_wait) {
        /* otisk vyprsel nebo neprosel: dal uz jen heslo */
        ll->fp_wait = FALSE;
        if (!ll->error_shown)
            show_hint (ll, "", FALSE, FALSE);
    }
    gtk_widget_queue_draw (ll->pw);
}

void
lux_lock_checking (LuxLock *ll) {
    show_hint (ll, "", FALSE, FALSE);
    gtk_widget_queue_draw (ll->pw);
}

void
lux_lock_auth_failed (LuxLock *ll, const char *message) {
    if (ll->locked_hint) {
        lux_lock_hint (ll, ll->locked_hint, TRUE);
        g_clear_pointer (&ll->locked_hint, g_free);
    } else if (!ll->error_shown) {
        lux_lock_hint (ll, message ? message : lux_tr ("Incorrect password. Try again."), TRUE);
    }
    ll->error_shown = TRUE;
    ll->prompted = ll->fp_wait = FALSE;
    shake (ll);
    gtk_widget_queue_draw (ll->pw);
}

static void
entry_changed (GtkEditable *e, LuxLock *ll) {
    gtk_widget_queue_draw (ll->go_area);
    gtk_widget_queue_draw (ll->pw);
    if (ll->error_shown && *gtk_entry_get_text (GTK_ENTRY (ll->entry)))
        show_hint (ll, "", FALSE, FALSE);
}

/* ---- napajeni (logind, bez dotazu na heslo) ------------------------------------------- */
static gboolean
logind_can (const char *method) {
    GDBusConnection *bus = g_bus_get_sync (G_BUS_TYPE_SYSTEM, NULL, NULL);
    GVariant *r;
    gboolean ok = FALSE;
    if (!bus)
        return FALSE;
    r = g_dbus_connection_call_sync (bus, "org.freedesktop.login1", "/org/freedesktop/login1",
                                     "org.freedesktop.login1.Manager", method, NULL, G_VARIANT_TYPE ("(s)"),
                                     G_DBUS_CALL_FLAGS_NONE, 2000, NULL, NULL);
    if (r) {
        const char *s;
        g_variant_get (r, "(&s)", &s);
        /* "challenge" (napr. prihlaseny dalsi uzivatel) by chtelo heslo spravce - tlacitko neukazat */
        ok = g_strcmp0 (s, "yes") == 0;
        g_variant_unref (r);
    }
    g_object_unref (bus);
    return ok;
}

static void
power_done (GObject *src, GAsyncResult *res, gpointer data) {
    LuxLock *ll = data;
    GError *err = NULL;
    GVariant *r = g_dbus_connection_call_finish (G_DBUS_CONNECTION (src), res, &err);
    if (r)
        g_variant_unref (r);
    if (err) {
        g_warning ("logind: %s", err->message);
        lux_lock_hint (ll, lux_tr ("This action is not available right now."), TRUE);
        g_error_free (err);
    }
}

static void
power_clicked (GtkButton *b, Round *rb) {
    GDBusConnection *bus;
    if (g_getenv ("LUXOS_LOCK_DEMO_USERS")) {
        g_message ("demo: %s", rb->method);
        return;
    }
    bus = g_bus_get_sync (G_BUS_TYPE_SYSTEM, NULL, NULL);
    if (!bus) {
        lux_lock_hint (rb->ll, lux_tr ("This action is not available right now."), TRUE);
        return;
    }
    g_dbus_connection_call (bus, "org.freedesktop.login1", "/org/freedesktop/login1",
                            "org.freedesktop.login1.Manager", rb->method, g_variant_new ("(b)", FALSE), NULL,
                            G_DBUS_CALL_FLAGS_NONE, -1, NULL, power_done, rb->ll);
    g_object_unref (bus);
}

/* ---- tlacitka --------------------------------------------------------------------------- */
static void
flat_button (GtkWidget *b, const char *cls) {
    GtkStyleContext *ctx = gtk_widget_get_style_context (b);
    gtk_button_set_relief (GTK_BUTTON (b), GTK_RELIEF_NONE);
    gtk_widget_set_focus_on_click (b, FALSE);
    gtk_style_context_add_class (ctx, "lux");
    gtk_style_context_add_class (ctx, cls);
}

static Round *
round_button (LuxLock *ll, const char *key, const char *label, IconFunc icon, const char *method) {
    Round *rb = g_new0 (Round, 1);
    GtkWidget *box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
    rb->ll = ll;
    rb->key = key;
    rb->icon = icon;
    rb->method = method;
    rb->button = gtk_button_new ();
    flat_button (rb->button, "round");
    rb->area = gtk_drawing_area_new ();
    g_signal_connect (rb->area, "draw", G_CALLBACK (draw_round), rb);
    rb->label = gtk_label_new (label);
    gtk_style_context_add_class (gtk_widget_get_style_context (rb->label), "small");
    gtk_box_pack_start (GTK_BOX (box), rb->area, FALSE, FALSE, 0);
    gtk_box_pack_start (GTK_BOX (box), rb->label, FALSE, FALSE, 0);
    gtk_container_add (GTK_CONTAINER (rb->button), box);
    gtk_widget_show_all (box);
    gtk_box_pack_start (GTK_BOX (ll->power), rb->button, FALSE, FALSE, 0);
    if (method)
        g_signal_connect (rb->button, "clicked", G_CALLBACK (power_clicked), rb);
    ll->rounds = g_list_append (ll->rounds, rb);
    return rb;
}

GtkWidget *
lux_lock_get_button (LuxLock *ll, const char *key) {
    for (GList *l = ll->rounds; l; l = l->next) {
        Round *rb = l->data;
        if (g_strcmp0 (rb->key, key) == 0)
            return rb->button;
    }
    return NULL;
}

/* ---- geometrie a styl podle velikosti obrazovky --------------------------------------- */
static int
px (LuxLock *ll, double v, int lo) {
    return MAX (lo, (int) round (v * ll->u));
}

static void
relayout (LuxLock *ll) {
    char *css;
    ll->u = MAX (0.55, ll->H / 1080.0);
    ll->sz.avatar = px (ll, 104, 64);
    ll->sz.pw_w = px (ll, 250, 180);
    ll->sz.pw_h = px (ll, 36, 28);
    ll->sz.round = px (ll, 44, 34);
    ll->sz.status = px (ll, 16, 12);
    ll->sz.pad = px (ll, 18, 10);
    ll->sz.pw_pad = px (ll, 16, 11);
    ll->sz.pw_font = px (ll, 15, 12);

    gtk_widget_set_margin_top (ll->status, ll->sz.pad);
    gtk_widget_set_margin_end (ll->status, ll->sz.pad);
    gtk_box_set_spacing (GTK_BOX (ll->status), px (ll, 14, 8));
    gtk_box_set_spacing (GTK_BOX (ll->login), px (ll, 14, 9));
    gtk_widget_set_size_request (ll->avatar, ll->sz.avatar + px (ll, 8, 6), ll->sz.avatar + px (ll, 8, 6));
    gtk_box_set_spacing (GTK_BOX (gtk_bin_get_child (GTK_BIN (ll->user_btn))), px (ll, 8, 5));
    gtk_widget_set_size_request (ll->pw, ll->sz.pw_w, ll->sz.pw_h);
    gtk_widget_set_size_request (ll->go_area, ll->sz.pw_h, ll->sz.pw_h);
    gtk_widget_set_size_request (ll->hint, -1, px (ll, 22, 16));
    gtk_widget_set_margin_bottom (ll->power, px (ll, 42, 26));
    gtk_box_set_spacing (GTK_BOX (ll->power), px (ll, 40, 26));
    for (GList *l = ll->rounds; l; l = l->next) {
        Round *rb = l->data;
        gtk_widget_set_size_request (rb->area, ll->sz.round + px (ll, 8, 6), ll->sz.round + px (ll, 8, 6));
        gtk_box_set_spacing (GTK_BOX (gtk_bin_get_child (GTK_BIN (rb->button))), px (ll, 5, 3));
    }
    gtk_widget_set_size_request (ll->net_icon, ll->sz.status + 4, ll->sz.status + 4);
    gtk_widget_set_size_request (ll->bat_icon, (int) round (ll->sz.status * 2.05) + 2, ll->sz.status + 4);

    css = g_strdup_printf (
        "* { font-family: \"%s\", \"Inter\", \"Cantarell\", sans-serif; }\n"
        "label { color: white; text-shadow: 0 1px %dpx rgba(0,0,0,0.45); }\n"
        "label.name { font-size: %dpx; font-weight: 600; }\n"
        "label.small { font-size: %dpx; font-weight: 500; color: rgba(255,255,255,0.92); }\n"
        "label.status { font-size: %dpx; font-weight: 600; }\n"
        "label.hint { font-size: %dpx; font-weight: 500; color: rgba(255,255,255,0.88); }\n"
        "label.hint.error { color: #ff8f86; font-weight: 600; }\n"
        "button.pill { padding: %dpx %dpx; }\n"
        "button.pill label { font-size: %dpx; font-weight: 700; letter-spacing: 1px; }\n"
        "entry.pw { font-size: %dpx; padding: 0 0 0 %dpx; }\n",
        ll->font, px (ll, 3, 2), px (ll, 17, 13), px (ll, 13, 11), px (ll, 14, 11), px (ll, 14, 11),
        px (ll, 3, 2), px (ll, 10, 7), px (ll, 13, 11), ll->sz.pw_font, ll->sz.pw_pad);
    gtk_css_provider_load_from_data (ll->css, css, -1, NULL);
    g_free (css);
}

/* ---- animace klid <-> prihlaseni ------------------------------------------------------ */
static void
apply_t (LuxLock *ll) {
    double e = ease (ll->t);
    gtk_widget_set_opacity (ll->login, e);
    gtk_widget_set_opacity (ll->power, e);
    gtk_widget_set_opacity (ll->status, e);
    /* obsah prijizdi lehce zdola */
    gtk_widget_set_margin_bottom (ll->login, px (ll, 150, 110) - (int) round ((1 - e) * 24 * ll->u));
    gtk_widget_queue_draw (ll->bg);
}

static gboolean
animate (gpointer data) {
    LuxLock *ll = data;
    double dur = ll->target > ll->anim_from ? 380000.0 : 420000.0;
    double p = MIN (1.0, (g_get_monotonic_time () - ll->anim_start) / dur);
    ll->t = ll->anim_from + (ll->target - ll->anim_from) * p;
    apply_t (ll);
    if (p >= 1.0) {
        ll->anim_id = 0;
        if (ll->target == 0 && ll->leave_done) {
            LuxLockFunc f = ll->leave_done;
            ll->leave_done = NULL;
            f (ll->leave_data);
        }
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void
animate_to (LuxLock *ll, double target) {
    ll->target = target;
    ll->anim_from = ll->t;
    ll->anim_start = g_get_monotonic_time ();
    if (!ll->anim_id)
        ll->anim_id = g_timeout_add (16, animate, ll);
}

void
lux_lock_enter (LuxLock *ll) {
    if (ll->target < 1.0)
        animate_to (ll, 1.0);
}

void
lux_lock_leave (LuxLock *ll, LuxLockFunc done, gpointer data) {
    ll->leave_done = done;
    ll->leave_data = data;
    if (!gtk_widget_get_mapped (ll->bg)) {
        ll->leave_done = NULL;
        done (data);
        return;
    }
    animate_to (ll, 0.0);
}

/* ---- periodicke aktualizace ----------------------------------------------------------- */
static gboolean
update_status (gpointer data) {
    LuxLock *ll = data;
    if (ll->show_battery)
        battery_state (ll);
    else
        ll->has_bat = FALSE;
    if (ll->show_network)
        network_state (ll);
    else
        ll->net = 0;
    gtk_widget_set_visible (ll->bat_icon, ll->has_bat);
    gtk_widget_set_visible (ll->bat_label, ll->has_bat);
    if (ll->has_bat) {
        static const char *const vars[] = { "LC_ALL", "LC_MESSAGES", "LANG", NULL };
        char *lang = env_lang (vars);
        char *t = g_strdup_printf (g_strcmp0 (lang, "cs") == 0 ? "%d %%" : "%d%%", ll->bat_level);
        gtk_label_set_text (GTK_LABEL (ll->bat_label), t);
        g_free (t);
        g_free (lang);
    }
    gtk_widget_set_visible (ll->net_icon, ll->net != 0);
    gtk_widget_queue_draw (ll->bat_icon);
    gtk_widget_queue_draw (ll->net_icon);
    return G_SOURCE_CONTINUE;
}

static gboolean
tick (gpointer data) {
    LuxLock *ll = data;
    time_t now = time (NULL);
    struct tm tm;
    localtime_r (&now, &tm);
    if (tm.tm_min != ll->last_minute) {
        ll->last_minute = tm.tm_min;
        gtk_widget_queue_draw (ll->bg);
    }
    kbd_update (ll);
    return G_SOURCE_CONTINUE;
}

static void
keymap_changed (GdkKeymap *km, LuxLock *ll) {
    kbd_update (ll);
}

static void
plug_realized (GtkWidget *w, LuxLock *ll) {
    /* bez pozadi X okna: pred prvnim vykreslenim zadne cerne okno (plynuly prechod ze setrice) */
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    gdk_window_set_background_pattern (gtk_widget_get_window (w), NULL);
    G_GNUC_END_IGNORE_DEPRECATIONS
}

static void
user_clicked (GtkButton *b, LuxLock *ll) {
    gtk_widget_grab_focus (ll->entry);
}

static gboolean
fprint_enabled (void) {
    char *pam = NULL;
    gboolean on = FALSE;
    const char *demo = g_getenv ("LUXOS_LOCK_DEMO_FPRINT");
    if (demo)
        return *demo == '1';
    if (g_file_get_contents (PAM_SERVICE_FILE, &pam, NULL, NULL))
        on = strstr (pam, "pam_fprintd") != NULL && g_file_test (FPRINT_MODULE, G_FILE_TEST_EXISTS);
    g_free (pam);
    return on;
}

#define OBJ(name) GTK_WIDGET (gtk_builder_get_object (builder, name))

LuxLock *
lux_lock_new (GtkBuilder *builder, GtkWidget *plug_widget) {
    LuxLock *ll = g_new0 (LuxLock, 1);

    ll->plug = plug_widget;
    ll->overlay = OBJ ("lock-overlay");
    ll->bg = OBJ ("lock-bg");
    ll->status = OBJ ("lock-status");
    ll->kbd_btn = OBJ ("kbd-button");
    ll->kbd_label = OBJ ("kbd-label");
    ll->net_icon = OBJ ("net-icon");
    ll->bat_icon = OBJ ("bat-icon");
    ll->bat_label = OBJ ("bat-label");
    ll->login = OBJ ("login_window");
    ll->status_msg = OBJ ("status-message-label");
    ll->users_box = OBJ ("users-box");
    ll->user_btn = OBJ ("user-button");
    ll->avatar = OBJ ("auth-face-image");
    ll->name = OBJ ("auth-realname-label");
    ll->pw = OBJ ("pw-box");
    ll->entry = OBJ ("auth-prompt-entry");
    ll->go = OBJ ("auth-unlock-button");
    ll->go_area = OBJ ("go-area");
    ll->hint = OBJ ("auth-hint-label");
    ll->power = OBJ ("auth-action-area");
    ll->last_minute = -1;
    ll->scale = 1;
    ll->placeholder = g_strdup (lux_tr ("Enter Password"));
    ll->fprint = fprint_enabled ();
    load_config (ll);

    flat_button (ll->kbd_btn, "pill");
    flat_button (ll->user_btn, "user");
    flat_button (ll->go, "go");
    gtk_widget_set_can_focus (ll->user_btn, FALSE);

    ll->css = gtk_css_provider_new ();
    gtk_style_context_add_provider_for_screen (gdk_screen_get_default (), GTK_STYLE_PROVIDER (ll->css),
                                               GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 10);

    g_signal_connect (ll->bg, "draw", G_CALLBACK (draw_bg), ll);
    g_signal_connect (ll->kbd_btn, "draw", G_CALLBACK (draw_kbd), ll);
    g_signal_connect (ll->kbd_btn, "clicked", G_CALLBACK (kbd_next), ll);
    g_signal_connect (ll->net_icon, "draw", G_CALLBACK (draw_net), ll);
    g_signal_connect (ll->bat_icon, "draw", G_CALLBACK (draw_battery), ll);
    g_signal_connect (ll->avatar, "draw", G_CALLBACK (draw_avatar), ll);
    g_signal_connect (ll->user_btn, "clicked", G_CALLBACK (user_clicked), ll);
    g_signal_connect (ll->pw, "draw", G_CALLBACK (draw_pw), ll);
    g_signal_connect (ll->go_area, "draw", G_CALLBACK (draw_go), ll);
    g_signal_connect (ll->entry, "changed", G_CALLBACK (entry_changed), ll);
    g_signal_connect (plug_widget, "realize", G_CALLBACK (plug_realized), ll);
    gtk_entry_set_placeholder_text (GTK_ENTRY (ll->entry), NULL);
    g_object_set (ll->entry, "caps-lock-warning", FALSE, NULL);

    ll->real_name = user_real_name ();
    gtk_label_set_text (GTK_LABEL (ll->name), ll->real_name ? ll->real_name : "");
    gtk_widget_set_tooltip_text (ll->user_btn, g_get_user_name ());

    /* spodni rada: Prepnout uzivatele a Odhlasit (podle nastaveni setrice), pak napajeni */
    round_button (ll, "switch", lux_tr ("Switch User"), icon_users, NULL);
    round_button (ll, "logout", lux_tr ("Sign Out"), icon_logout, NULL);
    if (g_getenv ("LUXOS_LOCK_DEMO_USERS") || logind_can ("CanSuspend"))
        round_button (ll, "suspend", lux_tr ("Sleep"), icon_sleep, "Suspend");
    if (g_getenv ("LUXOS_LOCK_DEMO_USERS") || logind_can ("CanReboot"))
        round_button (ll, "restart", lux_tr ("Restart"), icon_restart, "Reboot");
    if (g_getenv ("LUXOS_LOCK_DEMO_USERS") || logind_can ("CanPowerOff"))
        round_button (ll, "shutdown", lux_tr ("Shut Down"), icon_power, "PowerOff");

    kbd_load (ll);
    kbd_update (ll);
    g_signal_connect (gdk_keymap_get_for_display (gdk_display_get_default ()), "state-changed",
                      G_CALLBACK (keymap_changed), ll);
    load_face (ll);
    return ll;
}

void
lux_lock_setup (LuxLock *ll, gint monitor_index) {
    GdkDisplay *display = gdk_display_get_default ();
    GdkMonitor *monitor = gdk_display_get_monitor (display, monitor_index);
    GdkRectangle geo = { 0, 0, 0, 0 };
    if (!monitor)
        monitor = gdk_display_get_primary_monitor (display);
    if (!monitor)
        monitor = gdk_display_get_monitor (display, 0);
    if (monitor) {
        gdk_monitor_get_geometry (monitor, &geo);
        ll->scale = MAX (1, gdk_monitor_get_scale_factor (monitor));
    }
    if (geo.width <= 0 || geo.height <= 0) {
        geo.width = 1920;
        geo.height = 1080;
    }
    ll->W = geo.width;
    ll->H = geo.height;
    relayout (ll);
    build_backgrounds (ll, monitor ? gdk_monitor_get_model (monitor) : NULL);
    apply_t (ll);
    update_status (ll);
    ll->status_id = g_timeout_add_seconds (30, update_status, ll);
    ll->tick_id = g_timeout_add_seconds (1, tick, ll);
}

void
lux_lock_free (LuxLock *ll) {
    if (!ll)
        return;
    if (ll->anim_id)
        g_source_remove (ll->anim_id);
    if (ll->shake_id)
        g_source_remove (ll->shake_id);
    if (ll->tick_id)
        g_source_remove (ll->tick_id);
    if (ll->status_id)
        g_source_remove (ll->status_id);
    g_list_free_full (ll->rounds, g_free);
    g_clear_pointer (&ll->bg_surf, cairo_surface_destroy);
    g_clear_pointer (&ll->blur_surf, cairo_surface_destroy);
    g_clear_pointer (&ll->face_surf, cairo_surface_destroy);
    g_clear_object (&ll->face);
    g_clear_object (&ll->css);
    g_strfreev (ll->layouts);
    g_strfreev (ll->variants);
    g_free (ll->real_name);
    g_free (ll->font);
    g_free (ll->clock_fmt);
    g_free (ll->date_fmt);
    g_free (ll->placeholder);
    g_free (ll->locked_hint);
    g_free (ll);
}
