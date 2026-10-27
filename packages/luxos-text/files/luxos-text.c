/*
 * LuxOS Textovy editor (luxos-text) - lehky editor textu a kodu ve stylu macOS (GTK3 + GtkSourceView 4, C).
 *
 * Okno: postranni panel se stromem slozky (tlacitko vedle tlacitek okna), horni lista s nazvem souboru,
 * vyber jazyka (zvyrazneni syntaxe) a informace o dokumentu, tenka lista s osnovou (nadpisy, funkce)
 * a sipkami predchozi/dalsi, editor s cisly radku, zalamovanim a volitelne neviditelnymi znaky, dole
 * pocty radku/znaku/slov, velikost, kodovani a konce radku. Svetly/tmavy vzhled podle systemu.
 *
 * Jeden proces pro vsechna okna (GtkApplication): dalsi "luxos-text SOUBOR" jen preda soubory bezicimu
 * procesu, ktery otevre nove okno (jako TextEdit). Vic souboru v jednom volani = panely jednoho okna.
 * Kodovani: rozpoznani UTF-8, UTF-16 (BOM i bez), Windows-1250/ISO 8859-2, Windows-1252, Windows-1251;
 * pri ulozeni se zachova kodovani, BOM i konce radku (LF/CRLF/CR).
 *
 * Nastaveni: ~/.config/luxos/text-editor.conf (pismo, zalamovani, neviditelne znaky, nedavne soubory).
 * Preklady: /usr/share/luxos/i18n/<jazyk>.tsv (LUXOS_I18N_DIR pro testy).
 * Mereni (xvfb, prvni vykresleni okna, median 7 behu) viz PKGBUILD.
 */
#include "text-core.h"
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <X11/Xatom.h>
#include <gtksourceview/gtksource.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifndef LUXOS_TEXT_VERSION
#define LUXOS_TEXT_VERSION "1.0.0"
#endif
#define APP_ID "cz.luxos.TextEditor"
#define APP_ICON "luxos-text"
#define MAX_RECENT 15
#define URI_INFO 4242

/* ---------- preklady (radek "anglicky<TAB>preklad", jako luxos-terminal) ---------- */
static char *tr_data;
static gboolean tr_loaded;
static char lang_code[8] = "en";

static void tr_load(void)
{
    tr_loaded = TRUE;
    const char *l = g_getenv("LC_ALL");
    if (!l || !*l) l = g_getenv("LC_MESSAGES");
    if (!l || !*l) l = g_getenv("LANG");
    if (!l || !*l) return;
    size_t n = strcspn(l, "_.@");
    if (n == 0 || n >= sizeof lang_code - 1 || !strcmp(l, "C") || !strcmp(l, "POSIX")) return;
    memcpy(lang_code, l, n);
    lang_code[n] = 0;
    if (!strcmp(lang_code, "en")) return;
    const char *dir = g_getenv("LUXOS_I18N_DIR");
    char *path = g_strdup_printf("%s/%s.tsv", dir && *dir ? dir : "/usr/share/luxos/i18n", lang_code);
    char *data = NULL;
    if (g_file_get_contents(path, &data, NULL, NULL)) {
        tr_data = g_strconcat("\n", data, NULL);
        g_free(data);
    }
    g_free(path);
}

static const char *T(const char *en)
{
    if (!tr_loaded) tr_load();
    if (!tr_data) return en;
    static GHashTable *cache;
    if (!cache) cache = g_hash_table_new(g_str_hash, g_str_equal);
    char *v = g_hash_table_lookup(cache, en);
    if (v) return v;
    /* plati posledni radek s prekladem (jako i18n.sh) */
    size_t kl = strlen(en);
    const char *res = NULL, *p = tr_data;
    while ((p = strstr(p, en))) {
        if (p[-1] == '\n' && p[kl] == '\t') {
            const char *q = p + kl;
            while (*q == '\t') q++;
            if (*q && *q != '\n') res = q;
        }
        p += kl;
    }
    if (!res) v = (char *)en;
    else {
        size_t vl = strcspn(res, "\n");
        while (vl && (res[vl - 1] == '\t' || res[vl - 1] == '\r')) vl--;
        v = g_strndup(res, vl);
    }
    g_hash_table_insert(cache, (gpointer)en, v);
    return v;
}

/* ---------- nastaveni ---------- */
static struct {
    int font_size;
    gboolean wrap, invisibles, line_numbers;
    int width, height, sidebar_width;
    char **recent;
} cfg;

static char *config_path(void)
{
    return g_build_filename(g_get_user_config_dir(), "luxos", "text-editor.conf", NULL);
}

static void load_config(void)
{
    cfg.font_size = 11;
    cfg.wrap = TRUE;
    cfg.invisibles = FALSE;
    cfg.line_numbers = TRUE;
    cfg.width = 980;
    cfg.height = 680;
    cfg.sidebar_width = 220;
    GKeyFile *k = g_key_file_new();
    char *p = config_path();
    if (g_key_file_load_from_file(k, p, G_KEY_FILE_NONE, NULL)) {
        GError *e = NULL;
        int v = g_key_file_get_integer(k, "editor", "font-size", &e);
        if (!e && v >= 6 && v <= 72) cfg.font_size = v;
        g_clear_error(&e);
#define BOOLKEY(grp, key, var) do { gboolean b = g_key_file_get_boolean(k, grp, key, &e); if (!e) var = b; g_clear_error(&e); } while (0)
        BOOLKEY("editor", "wrap", cfg.wrap);
        BOOLKEY("editor", "invisibles", cfg.invisibles);
        BOOLKEY("editor", "line-numbers", cfg.line_numbers);
#define INTKEY(grp, key, var, lo, hi) do { int i = g_key_file_get_integer(k, grp, key, &e); if (!e && i >= lo && i <= hi) var = i; g_clear_error(&e); } while (0)
        INTKEY("window", "width", cfg.width, 400, 10000);
        INTKEY("window", "height", cfg.height, 300, 10000);
        INTKEY("window", "sidebar-width", cfg.sidebar_width, 120, 800);
        cfg.recent = g_key_file_get_string_list(k, "recent", "files", NULL, NULL);
    }
    g_free(p);
    g_key_file_free(k);
}

static guint save_config_id;

static gboolean save_config_now(gpointer d)
{
    save_config_id = 0;
    GKeyFile *k = g_key_file_new();
    char *p = config_path();
    g_key_file_load_from_file(k, p, G_KEY_FILE_KEEP_COMMENTS, NULL);
    g_key_file_set_integer(k, "editor", "font-size", cfg.font_size);
    g_key_file_set_boolean(k, "editor", "wrap", cfg.wrap);
    g_key_file_set_boolean(k, "editor", "invisibles", cfg.invisibles);
    g_key_file_set_boolean(k, "editor", "line-numbers", cfg.line_numbers);
    g_key_file_set_integer(k, "window", "width", cfg.width);
    g_key_file_set_integer(k, "window", "height", cfg.height);
    g_key_file_set_integer(k, "window", "sidebar-width", cfg.sidebar_width);
    g_key_file_set_string_list(k, "recent", "files", (const char *const *)(cfg.recent ? cfg.recent : (char *[]){NULL}),
                               cfg.recent ? g_strv_length(cfg.recent) : 0);
    char *dir = g_path_get_dirname(p);
    g_mkdir_with_parents(dir, 0700);
    g_key_file_save_to_file(k, p, NULL);
    g_free(dir);
    g_free(p);
    g_key_file_free(k);
    return G_SOURCE_REMOVE;
}

static void save_config(void)
{
    if (!save_config_id) save_config_id = g_timeout_add(500, save_config_now, NULL);
}

/* ---------- typy ---------- */
typedef struct Win Win;

typedef struct {
    Win *win;
    GtkWidget *page;           /* svisly box: infobar + editor */
    GtkWidget *infobar, *info_label;
    GtkSourceView *view;
    GtkSourceBuffer *buf;
    GtkSourceSearchContext *search;
    char *path;                /* NULL = novy dokument */
    int untitled;
    const TxEncoding *enc;
    TxLineEnd le;
    gboolean lang_manual;
    GFileMonitor *mon;
    gboolean disk_exists;
    gint64 disk_mtime;
    goffset disk_size;
    guint scan_id, check_id;
    TxStats stats;
    GPtrArray *outline;
    GtkWidget *tab_label;
    GtkTextTag *nolig;
} Doc;

struct Win {
    GtkWindow *win;
    GtkHeaderBar *header;
    GtkWidget *title, *subtitle;
    GtkWidget *sidebar_btn, *lang_btn, *lang_label, *info_btn;
    GtkWidget *paned, *sidebar, *tree, *root_label;
    GtkTreeStore *store;
    char *root;
    GHashTable *dir_mons;      /* cesta -> GFileMonitor */
    GtkWidget *notebook;
    GtkWidget *nav_prev, *nav_next, *outline_btn, *outline_label, *outline_list;
    GtkWidget *find_rev, *find_entry, *replace_entry, *replace_row, *find_count, *case_btn, *regex_btn, *word_btn;
    GtkSourceSearchSettings *ss;
    GtkWidget *st_lines, *st_chars, *st_words, *st_size, *pos_btn, *enc_btn, *le_btn;
    GtkWidget *lang_list, *lang_search;
    GtkWidget *info_grid;
    GtkWidget *goto_pop, *goto_entry;
    int replaced;              /* posledni "Nahradit vse" (zobrazit misto "Zadne vysledky") */
    Doc *cur;
    gboolean closing;
};

static GtkApplication *app;
static GList *windows;
static GtkCssProvider *font_css;
static GMenu *recent_menu;
static int untitled_counter;
static gboolean test_mode;

enum { COL_ICON, COL_NAME, COL_PATH, COL_DIR, COL_LOADED, COL_WEIGHT, N_COLS };

static void update_window(Win *w);
static void update_title(Win *w);
static void update_status(Win *w);
static void update_outline_ui(Win *w);
static void schedule_scan(Doc *d, gboolean soon);
static Doc *new_doc(Win *w);
static gboolean load_doc(Doc *d, const char *path, const TxEncoding *force, GError **err);
static void sidebar_set_root(Win *w, const char *dir);
static void sidebar_show(Win *w, gboolean show);
static void sidebar_select_current(Win *w);
static gboolean save_doc(Doc *d, gboolean as);
static void close_doc(Doc *d);
static void remember_size(Win *w);
static void open_paths(Win *w, char **paths, int line);
static Win *new_window(void);
static void search_update_count(Win *w);

/* ---------- pomocne ---------- */
static const char *home_dir(void) { return g_get_home_dir(); }

/* ~/Dokumenty/x misto /home/jan/Dokumenty/x */
static char *pretty_dir(const char *path)
{
    const char *home = home_dir();
    size_t hl = strlen(home);
    if (!strcmp(path, home)) return g_strdup("~");
    if (hl > 1 && !strncmp(path, home, hl) && path[hl] == '/') return g_strconcat("~", path + hl, NULL);
    return g_strdup(path);
}

static char *doc_name(Doc *d)
{
    if (d->path) return g_path_get_basename(d->path);
    if (d->untitled <= 1) return g_strdup(T("Untitled"));
    return g_strdup_printf("%s %d", T("Untitled"), d->untitled);
}

static char *encoding_label(const TxEncoding *e)
{
    if (!e->region) {
        return g_strdup_printf("Unicode (%s)", !strcmp(e->id, "UTF-8-BOM") ? T("UTF-8 with BOM") : e->name);
    }
    return g_strdup_printf("%s (%s)", T(e->region), e->name);
}

static gboolean system_dark(void)
{
    const char *env = g_getenv("GTK_THEME");
    if (env && *env) return strstr(env, "dark") || strstr(env, "Dark");
    gboolean prefer = FALSE;
    char *name = NULL;
    g_object_get(gtk_settings_get_default(), "gtk-application-prefer-dark-theme", &prefer, "gtk-theme-name", &name, NULL);
    char *low = name ? g_ascii_strdown(name, -1) : NULL;
    gboolean dark = prefer || (low && strstr(low, "dark"));
    g_free(low);
    g_free(name);
    return dark;
}

static GtkSourceStyleScheme *current_scheme(void)
{
    GtkSourceStyleSchemeManager *m = gtk_source_style_scheme_manager_get_default();
    gboolean dark = system_dark();
    GtkSourceStyleScheme *s = gtk_source_style_scheme_manager_get_scheme(m, dark ? "luxos-dark" : "luxos-light");
    if (!s) s = gtk_source_style_scheme_manager_get_scheme(m, dark ? "oblivion" : "classic");
    return s;
}

static GList *all_docs(Win *w)
{
    GList *l = NULL;
    int n = gtk_notebook_get_n_pages(GTK_NOTEBOOK(w->notebook));
    for (int i = 0; i < n; i++) {
        GtkWidget *p = gtk_notebook_get_nth_page(GTK_NOTEBOOK(w->notebook), i);
        Doc *d = g_object_get_data(G_OBJECT(p), "doc");
        if (d) l = g_list_append(l, d);
    }
    return l;
}

static Doc *find_open_doc(const char *path, Win **win_out)
{
    for (GList *wl = windows; wl; wl = wl->next) {
        GList *docs = all_docs(wl->data);
        for (GList *l = docs; l; l = l->next) {
            Doc *d = l->data;
            if (d->path && !strcmp(d->path, path)) {
                if (win_out) *win_out = wl->data;
                g_list_free(docs);
                return d;
            }
        }
        g_list_free(docs);
    }
    return NULL;
}

static gboolean doc_is_blank(Doc *d)
{
    return d && !d->path && !gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf)) &&
           gtk_text_buffer_get_char_count(GTK_TEXT_BUFFER(d->buf)) == 0;
}

static char *buffer_text(Doc *d)
{
    GtkTextIter s, e;
    gtk_text_buffer_get_bounds(GTK_TEXT_BUFFER(d->buf), &s, &e);
    return gtk_text_buffer_get_text(GTK_TEXT_BUFFER(d->buf), &s, &e, TRUE);
}

static void message(GtkWindow *parent, const char *primary, const char *secondary)
{
    GtkWidget *m = gtk_message_dialog_new(parent, GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT, GTK_MESSAGE_ERROR,
                                          GTK_BUTTONS_CLOSE, "%s", primary);
    if (secondary) gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(m), "%s", secondary);
    gtk_dialog_run(GTK_DIALOG(m));
    gtk_widget_destroy(m);
}

/* Ikona okna i ve velkych velikostech (Alt+Tab ukazuje ~100 px): gtk_window_set_icon_name posle spravci
 * oken jen male velikosti a xfwm4 je zvetsi rozmazane. Nacte se jednou (po prvnim vykresleni okna). */
static GList *icon_list;

static GList *window_icons(void)
{
    static gboolean tried;
    if (tried) return icon_list;
    tried = TRUE;
    static const int sizes[] = {16, 24, 32, 48, 64, 128, 256};
    GtkIconTheme *theme = gtk_icon_theme_get_default();
    const char *file = g_getenv("LUXOS_TEXT_ICON");
    gboolean themed = !(file && *file) && gtk_icon_theme_has_icon(theme, APP_ICON);
    for (guint i = 0; i < G_N_ELEMENTS(sizes); i++) {
        GdkPixbuf *pb = NULL;
        if (themed) pb = gtk_icon_theme_load_icon(theme, APP_ICON, sizes[i], GTK_ICON_LOOKUP_FORCE_SIZE, NULL);
        else if (file && *file) pb = gdk_pixbuf_new_from_file_at_size(file, sizes[i], sizes[i], NULL);
        if (pb) icon_list = g_list_append(icon_list, pb);
    }
    if (icon_list) gtk_window_set_default_icon_list(icon_list);
    return icon_list;
}

/* GDK posle do _NET_WM_ICON jen ikony do velikosti jednoho pozadavku X bez BIG-REQUESTS (64k slov) -
 * 256 px vynecha. Cely seznam 16-256 px se proto zapise primo (Xlib pouzije BIG-REQUESTS). */
static void write_net_wm_icon(GtkWidget *wdg)
{
    GdkWindow *gw = gtk_widget_get_window(wdg);
    if (!icon_list || !gw || !GDK_IS_X11_WINDOW(gw)) return;
    gsize n = 0;
    for (GList *l = icon_list; l; l = l->next)
        n += 2 + gdk_pixbuf_get_width(l->data) * gdk_pixbuf_get_height(l->data);
    unsigned long *data = g_new(unsigned long, n), *p = data;   /* Xlib: format 32 = pole long */
    for (GList *l = icon_list; l; l = l->next) {
        GdkPixbuf *pb = l->data;
        int w = gdk_pixbuf_get_width(pb), h = gdk_pixbuf_get_height(pb), rs = gdk_pixbuf_get_rowstride(pb);
        int nc = gdk_pixbuf_get_n_channels(pb);
        gboolean alpha = gdk_pixbuf_get_has_alpha(pb);
        const guchar *px = gdk_pixbuf_read_pixels(pb);
        *p++ = w;
        *p++ = h;
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++) {
                const guchar *q = px + y * rs + x * nc;
                *p++ = ((unsigned long)(alpha ? q[3] : 255) << 24) | (q[0] << 16) | (q[1] << 8) | q[2];
            }
    }
    GdkDisplay *gd = gdk_window_get_display(gw);
    Display *dpy = GDK_DISPLAY_XDISPLAY(gd);
    gdk_x11_display_error_trap_push(gd);
    XChangeProperty(dpy, GDK_WINDOW_XID(gw), gdk_x11_get_xatom_by_name_for_display(gd, "_NET_WM_ICON"), XA_CARDINAL,
                    32, PropModeReplace, (guchar *)data, n);
    gdk_x11_display_error_trap_pop_ignored(gd);
    g_free(data);
}

static void set_window_icons(GtkWindow *win)
{
    GList *l = window_icons();
    if (l) {
        gtk_window_set_icon_list(win, l);
        if (gtk_widget_get_realized(GTK_WIDGET(win))) write_net_wm_icon(GTK_WIDGET(win));
        if (!g_object_get_data(G_OBJECT(win), "icon-hook")) {
            g_object_set_data(G_OBJECT(win), "icon-hook", GINT_TO_POINTER(1));
            g_signal_connect_after(win, "realize", G_CALLBACK(write_net_wm_icon), NULL);
        }
    } else gtk_window_set_icon_name(win, APP_ICON);
}

static gboolean icons_idle(gpointer p)
{
    for (GList *l = windows; l; l = l->next) set_window_icons(((Win *)l->data)->win);
    return G_SOURCE_REMOVE;
}

/* ---------- vzhled ---------- */
static const char *APP_CSS =
    ".lt-nav { border-bottom: 1px solid alpha(currentColor, 0.10); padding: 0 6px; min-height: 26px; }"
    ".lt-nav button, .lt-status button { padding: 0 6px; min-height: 20px; min-width: 20px; border: none;"
    "  box-shadow: none; background: none; }"
    ".lt-nav button:hover, .lt-status button:hover { background-color: alpha(currentColor, 0.08); }"
    ".lt-nav label { font-size: 0.92em; }"
    ".lt-status { border-top: 1px solid alpha(currentColor, 0.10); padding: 0 8px; min-height: 24px; }"
    ".lt-status label { font-size: 0.86em; color: alpha(currentColor, 0.72); }"
    ".lt-status .lt-sep { min-width: 1px; background-color: alpha(currentColor, 0.15); margin: 5px 4px; }"
    ".lt-pill { border-radius: 999px; padding: 0 10px; min-height: 22px; border: none; box-shadow: none;"
    "  background-color: alpha(currentColor, 0.07); }"
    ".lt-pill label { font-size: 0.92em; }"
    ".lt-pill:hover, .lt-pill:checked { background-color: alpha(currentColor, 0.14); }"
    ".lt-title { font-weight: bold; }"
    ".lt-subtitle { font-size: 0.82em; color: alpha(currentColor, 0.55); }"
    ".lt-sidebar { background-color: #f2f2f5; border-right: 1px solid alpha(currentColor, 0.08); }"
    ".lt-dark .lt-sidebar { background-color: #26262b; }"
    ".lt-sidebar treeview { background-color: transparent; }"
    ".lt-sidebar treeview.view:selected { background-color: #3d7bff; color: #ffffff; }"
    ".lt-sidebar treeview.view:selected:backdrop { background-color: rgba(0, 0, 0, 0.10); color: #1d1d1f; }"
    ".lt-dark .lt-sidebar treeview.view:selected:backdrop { background-color: rgba(255, 255, 255, 0.12); color: #e6e6ea; }"
    ".lt-sidebar .lt-root { font-weight: bold; font-size: 0.85em; color: alpha(currentColor, 0.6); padding: 8px 10px 4px 12px; }"
    ".lt-sidebar .lt-sidebar-bar { border-top: 1px solid alpha(currentColor, 0.08); padding: 2px 4px; }"
    ".lt-sidebar .lt-sidebar-bar button { border: none; box-shadow: none; background: none; padding: 2px 6px; }"
    ".lt-find { border-bottom: 1px solid alpha(currentColor, 0.10); padding: 4px 8px; }"
    ".lt-find .lt-count { font-size: 0.86em; color: alpha(currentColor, 0.6); min-width: 70px; }"
    ".lt-find .lt-toggle { padding: 0 6px; min-width: 24px; font-family: monospace; }"
    ".lt-dim { color: alpha(currentColor, 0.5); }"
    ".lt-info .lt-key { color: alpha(currentColor, 0.6); }"
    "notebook.lt-tabs > header { padding: 0; }"
    "notebook.lt-tabs > header tab { padding: 2px 6px; min-height: 0; }"
    "notebook.lt-tabs > header tab button { padding: 0; min-height: 16px; min-width: 16px; }";

static void apply_font(void)
{
    char *css = g_strdup_printf("textview.lt-editor { font-family: Monospace; font-size: %dpt; }", cfg.font_size);
    gtk_css_provider_load_from_data(font_css, css, -1, NULL);
    g_free(css);
}

static void apply_theme(void)
{
    GtkSourceStyleScheme *s = current_scheme();
    gboolean dark = system_dark();
    for (GList *wl = windows; wl; wl = wl->next) {
        Win *w = wl->data;
        GtkStyleContext *sc = gtk_widget_get_style_context(GTK_WIDGET(w->win));
        if (dark) gtk_style_context_add_class(sc, "lt-dark");
        else gtk_style_context_remove_class(sc, "lt-dark");
        GList *docs = all_docs(w);
        for (GList *l = docs; l; l = l->next) gtk_source_buffer_set_style_scheme(((Doc *)l->data)->buf, s);
        g_list_free(docs);
    }
}

static void on_theme_changed(GObject *o, GParamSpec *p, gpointer d) { apply_theme(); }

static void apply_view_settings(Doc *d)
{
    GtkSourceView *v = d->view;
    gtk_source_view_set_show_line_numbers(v, cfg.line_numbers);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(v), cfg.wrap ? GTK_WRAP_WORD_CHAR : GTK_WRAP_NONE);
    GtkSourceSpaceDrawer *sd = gtk_source_view_get_space_drawer(v);
    gtk_source_space_drawer_set_types_for_locations(sd, GTK_SOURCE_SPACE_LOCATION_ALL,
        GTK_SOURCE_SPACE_TYPE_NEWLINE | GTK_SOURCE_SPACE_TYPE_TAB | GTK_SOURCE_SPACE_TYPE_NBSP);
    gtk_source_space_drawer_set_types_for_locations(sd, GTK_SOURCE_SPACE_LOCATION_TRAILING,
        GTK_SOURCE_SPACE_TYPE_NEWLINE | GTK_SOURCE_SPACE_TYPE_TAB | GTK_SOURCE_SPACE_TYPE_NBSP |
        GTK_SOURCE_SPACE_TYPE_SPACE);
    gtk_source_space_drawer_set_enable_matrix(sd, cfg.invisibles);
}

static void apply_all_view_settings(void)
{
    for (GList *wl = windows; wl; wl = wl->next) {
        GList *docs = all_docs(wl->data);
        for (GList *l = docs; l; l = l->next) apply_view_settings(l->data);
        g_list_free(docs);
    }
    save_config();
}

/* ---------- dokument: stav na disku, sledovani zmen ---------- */
static void record_disk_state(Doc *d)
{
    GStatBuf st;
    d->disk_exists = d->path && g_stat(d->path, &st) == 0;
    d->disk_mtime = d->disk_exists ? (gint64)st.st_mtim.tv_sec * 1000000000 + st.st_mtim.tv_nsec : 0;
    d->disk_size = d->disk_exists ? st.st_size : 0;
}

static void hide_infobar(Doc *d)
{
    if (d->infobar) gtk_widget_hide(d->infobar);
}

static void on_infobar_response(GtkInfoBar *bar, int resp, Doc *d)
{
    hide_infobar(d);
    if (resp == 1 && d->path) {
        GError *err = NULL;
        if (!load_doc(d, d->path, d->enc, &err)) {
            char *name = doc_name(d);
            char *msg = g_strdup_printf(T("Could not open “%s”."), name);
            message(d->win->win, msg, err ? err->message : NULL);
            g_free(msg);
            g_free(name);
            g_clear_error(&err);
        }
    } else {
        record_disk_state(d);   /* zmenu ignorovat az do dalsi */
    }
}

static void show_infobar(Doc *d, gboolean deleted)
{
    if (!d->infobar) {
        d->infobar = gtk_info_bar_new();
        gtk_info_bar_set_message_type(GTK_INFO_BAR(d->infobar), GTK_MESSAGE_WARNING);
        d->info_label = gtk_label_new(NULL);
        gtk_label_set_line_wrap(GTK_LABEL(d->info_label), TRUE);
        gtk_label_set_xalign(GTK_LABEL(d->info_label), 0);
        gtk_container_add(GTK_CONTAINER(gtk_info_bar_get_content_area(GTK_INFO_BAR(d->infobar))), d->info_label);
        g_signal_connect(d->infobar, "response", G_CALLBACK(on_infobar_response), d);
        gtk_box_pack_start(GTK_BOX(d->page), d->infobar, FALSE, FALSE, 0);
        gtk_box_reorder_child(GTK_BOX(d->page), d->infobar, 0);
    }
    /* tlacitka podle druhu zmeny */
    GtkWidget *area = gtk_info_bar_get_action_area(GTK_INFO_BAR(d->infobar));
    GList *ch = gtk_container_get_children(GTK_CONTAINER(area));
    for (GList *l = ch; l; l = l->next) gtk_widget_destroy(l->data);
    g_list_free(ch);
    gboolean modified = gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf));
    if (deleted) {
        gtk_label_set_text(GTK_LABEL(d->info_label), T("The file was deleted or moved by another program. Save it to keep it."));
        gtk_info_bar_add_button(GTK_INFO_BAR(d->infobar), T("OK"), 2);
    } else {
        char *t = g_strconcat(T("The file was changed by another program."), modified ? " " : NULL,
                              modified ? T("Reloading discards your unsaved changes.") : NULL, NULL);
        gtk_label_set_text(GTK_LABEL(d->info_label), t);
        g_free(t);
        gtk_info_bar_add_button(GTK_INFO_BAR(d->infobar), T("Reload"), 1);
        gtk_info_bar_add_button(GTK_INFO_BAR(d->infobar), T("Ignore"), 2);
    }
    gtk_widget_show_all(d->infobar);
}

static gboolean check_disk(gpointer p)
{
    Doc *d = p;
    d->check_id = 0;
    if (!d->path) return G_SOURCE_REMOVE;
    gboolean was = d->disk_exists;
    gint64 mt = d->disk_mtime;
    goffset sz = d->disk_size;
    GStatBuf st;
    gboolean exists = g_stat(d->path, &st) == 0;
    if (!exists && was) {
        /* smazany soubor: zavreni panelu se zepta na ulozeni */
        gtk_text_buffer_set_modified(GTK_TEXT_BUFFER(d->buf), TRUE);
        show_infobar(d, TRUE);
    }
    else if (exists && (!was || (gint64)st.st_mtim.tv_sec * 1000000000 + st.st_mtim.tv_nsec != mt || st.st_size != sz))
        show_infobar(d, FALSE);
    return G_SOURCE_REMOVE;
}

static void on_file_changed(GFileMonitor *m, GFile *f, GFile *o, GFileMonitorEvent ev, Doc *d)
{
    if (ev == G_FILE_MONITOR_EVENT_ATTRIBUTE_CHANGED) return;
    if (d->check_id) g_source_remove(d->check_id);
    d->check_id = g_timeout_add(300, check_disk, d);
}

static void watch_file(Doc *d)
{
    if (d->mon) {
        g_signal_handlers_disconnect_by_data(d->mon, d);
        g_file_monitor_cancel(d->mon);
        g_clear_object(&d->mon);
    }
    if (!d->path) return;
    GFile *f = g_file_new_for_path(d->path);
    d->mon = g_file_monitor_file(f, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
    g_object_unref(f);
    if (d->mon) g_signal_connect(d->mon, "changed", G_CALLBACK(on_file_changed), d);
}

/* ---------- nedavne soubory ---------- */
static void rebuild_recent_menu(void)
{
    if (!recent_menu) return;
    g_menu_remove_all(recent_menu);
    GMenu *files = g_menu_new();
    for (int i = 0; cfg.recent && cfg.recent[i] && i < MAX_RECENT; i++) {
        char *base = g_path_get_basename(cfg.recent[i]);
        char *dir = g_path_get_dirname(cfg.recent[i]);
        char *pd = pretty_dir(dir);
        char *raw = g_strdup_printf("%s — %s", base, pd);
        /* "_" by v nabidce byl zkratkou (mnemonic) */
        char **parts = g_strsplit(raw, "_", -1);
        char *label = g_strjoinv("__", parts);
        g_strfreev(parts);
        g_free(raw);
        GMenuItem *it = g_menu_item_new(label, NULL);
        g_menu_item_set_action_and_target_value(it, "app.open-recent", g_variant_new_string(cfg.recent[i]));
        g_menu_append_item(files, it);
        g_object_unref(it);
        g_free(label);
        g_free(pd);
        g_free(dir);
        g_free(base);
    }
    g_menu_append_section(recent_menu, NULL, G_MENU_MODEL(files));
    g_object_unref(files);
    GMenu *clear = g_menu_new();
    g_menu_append(clear, T("Clear Menu"), "app.clear-recent");
    g_menu_append_section(recent_menu, NULL, G_MENU_MODEL(clear));
    g_object_unref(clear);
}

static void add_recent(const char *path)
{
    cfg.recent = tx_recent_add(cfg.recent, path, MAX_RECENT);
    rebuild_recent_menu();
    save_config();
}

/* ---------- pocty, osnova ---------- */
static gboolean scan_now(gpointer p)
{
    Doc *d = p;
    d->scan_id = 0;
    /* 1 MB: text 2 ms, pocty 3,5 ms, osnova 3 ms */
    char *text = buffer_text(d);
    gsize len = strlen(text);
    tx_count(text, len, d->enc, d->le, &d->stats);
    GtkSourceLanguage *l = gtk_source_buffer_get_language(d->buf);
    const char *id = l ? gtk_source_language_get_id(l) : NULL;
    if (d->outline) g_ptr_array_unref(d->outline);
    d->outline = tx_outline_supported(id) ? tx_outline(id, text, len) : NULL;
    g_free(text);
    if (d->win->cur == d) {
        update_status(d->win);
        update_outline_ui(d->win);
    }
    return G_SOURCE_REMOVE;
}

static void schedule_scan(Doc *d, gboolean soon)
{
    if (d->scan_id) g_source_remove(d->scan_id);
    int chars = gtk_text_buffer_get_char_count(GTK_TEXT_BUFFER(d->buf));
    /* velke soubory mene casto; priorita "idle" = az po vykresleni okna */
    int delay = soon ? 0 : chars > 2000000 ? 1000 : chars > 200000 ? 400 : 150;
    d->scan_id = g_timeout_add_full(G_PRIORITY_DEFAULT_IDLE, delay, scan_now, d, NULL);
}

/* ---------- hlavicka, panely, stavovy radek ---------- */
static void update_tab_label(Doc *d)
{
    if (!d->tab_label) return;
    char *name = doc_name(d);
    gboolean mod = gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf));
    char *t = mod ? g_strconcat("• ", name, NULL) : g_strdup(name);
    gtk_label_set_text(GTK_LABEL(d->tab_label), t);
    gtk_widget_set_tooltip_text(d->tab_label, d->path ? d->path : name);
    g_free(t);
    g_free(name);
}

static void update_title(Win *w)
{
    Doc *d = w->cur;
    if (!d) return;
    char *name = doc_name(d);
    gboolean mod = gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf));
    char *title = mod ? g_strdup_printf("%s — %s", name, T("Edited")) : g_strdup(name);
    gtk_label_set_text(GTK_LABEL(w->title), title);
    char *sub;
    if (d->path) {
        char *dir = g_path_get_dirname(d->path);
        char *pd = pretty_dir(dir);
        sub = g_strdup_printf("%s — %s", T("Text Editor"), pd);
        g_free(pd);
        g_free(dir);
    } else sub = g_strdup(T("Text Editor"));
    gtk_label_set_text(GTK_LABEL(w->subtitle), sub);
    char *wt = g_strdup_printf("%s%s — %s", mod ? "• " : "", name, T("Text Editor"));
    gtk_window_set_title(w->win, wt);
    g_free(wt);
    g_free(sub);
    g_free(title);
    g_free(name);
    update_tab_label(d);
}

static void set_label_count(GtkWidget *l, const char *fmt, gint64 n)
{
    char num[32];
    g_snprintf(num, sizeof num, "%'" G_GINT64_FORMAT, n);
    char *t = g_strdup_printf(fmt, num);
    gtk_label_set_text(GTK_LABEL(l), t);
    g_free(t);
}

static void update_position(Win *w)
{
    Doc *d = w->cur;
    if (!d) return;
    GtkTextIter it;
    gtk_text_buffer_get_iter_at_mark(GTK_TEXT_BUFFER(d->buf), &it,
                                     gtk_text_buffer_get_insert(GTK_TEXT_BUFFER(d->buf)));
    char *t = g_strdup_printf("%d:%d", gtk_text_iter_get_line(&it) + 1,
                              gtk_source_view_get_visual_column(d->view, &it) + 1);
    gtk_button_set_label(GTK_BUTTON(w->pos_btn), t);
    g_free(t);
}

static void update_status(Win *w)
{
    Doc *d = w->cur;
    if (!d) return;
    set_label_count(w->st_lines, T("Lines: %s"), d->stats.lines);
    set_label_count(w->st_chars, T("Characters: %s"), d->stats.chars);
    set_label_count(w->st_words, T("Words: %s"), d->stats.words);
    char *sz = g_format_size(d->stats.bytes);
    gtk_label_set_text(GTK_LABEL(w->st_size), sz);
    g_free(sz);
    char *el = encoding_label(d->enc);
    gtk_button_set_label(GTK_BUTTON(w->enc_btn), el);
    g_free(el);
    gtk_button_set_label(GTK_BUTTON(w->le_btn), tx_line_ending_name(d->le));
    /* stav prepinacu v nabidkach */
    GAction *a = g_action_map_lookup_action(G_ACTION_MAP(w->win), "encoding");
    if (a) g_simple_action_set_state(G_SIMPLE_ACTION(a), g_variant_new_string(d->enc->id));
    a = g_action_map_lookup_action(G_ACTION_MAP(w->win), "line-ending");
    if (a) g_simple_action_set_state(G_SIMPLE_ACTION(a), g_variant_new_string(tx_line_ending_name(d->le)));
    update_position(w);
}

static void update_language_ui(Win *w)
{
    Doc *d = w->cur;
    if (!d) return;
    GtkSourceLanguage *l = gtk_source_buffer_get_language(d->buf);
    gtk_label_set_text(GTK_LABEL(w->lang_label), l ? gtk_source_language_get_name(l) : T("Plain Text"));
}

/* Symbol osnovy, ve kterem je kurzor (posledni s radkem <= radek kurzoru) */
static int current_symbol(Doc *d, int line)
{
    if (!d->outline) return -1;
    int best = -1;
    for (guint i = 0; i < d->outline->len; i++) {
        TxSymbol *s = d->outline->pdata[i];
        if (s->line <= line) best = i;
        else break;
    }
    return best;
}

static int cursor_line(Doc *d)
{
    GtkTextIter it;
    gtk_text_buffer_get_iter_at_mark(GTK_TEXT_BUFFER(d->buf), &it, gtk_text_buffer_get_insert(GTK_TEXT_BUFFER(d->buf)));
    return gtk_text_iter_get_line(&it);
}

static void update_outline_ui(Win *w)
{
    Doc *d = w->cur;
    if (!d) return;
    gboolean any = d->outline && d->outline->len > 0;
    gtk_widget_set_sensitive(w->outline_btn, any);
    GtkStyleContext *sc = gtk_widget_get_style_context(w->outline_label);
    if (!any) {
        gtk_label_set_text(GTK_LABEL(w->outline_label), d->outline ? T("No Symbols") : T("No Outline"));
        gtk_style_context_add_class(sc, "lt-dim");
        gtk_widget_set_sensitive(w->nav_prev, FALSE);
        gtk_widget_set_sensitive(w->nav_next, FALSE);
        return;
    }
    gtk_style_context_remove_class(sc, "lt-dim");
    int line = cursor_line(d);
    int i = current_symbol(d, line);
    TxSymbol *s = i >= 0 ? d->outline->pdata[i] : NULL;
    gtk_label_set_text(GTK_LABEL(w->outline_label), s ? s->title : T("Top of Document"));
    gtk_widget_set_sensitive(w->nav_prev, i > 0 || (s && s->line < line));
    gtk_widget_set_sensitive(w->nav_next, (guint)(i + 1) < d->outline->len);
}

static void update_window(Win *w)
{
    update_title(w);
    update_language_ui(w);
    update_status(w);
    update_outline_ui(w);
}

/* ---------- dokument ---------- */
static void jump_to_line(Doc *d, int line, int col)
{
    GtkTextIter it;
    GtkTextBuffer *b = GTK_TEXT_BUFFER(d->buf);
    if (line < 0) line = 0;
    if (line >= gtk_text_buffer_get_line_count(b)) line = gtk_text_buffer_get_line_count(b) - 1;
    gtk_text_buffer_get_iter_at_line(b, &it, line);
    if (col > 0) {
        int n = gtk_text_iter_get_chars_in_line(&it);
        gtk_text_iter_set_line_offset(&it, MIN(col, MAX(n - 1, 0)));
    }
    gtk_text_buffer_place_cursor(b, &it);
    gtk_text_view_scroll_to_mark(GTK_TEXT_VIEW(d->view), gtk_text_buffer_get_insert(b), 0.1, TRUE, 0.0, 0.3);
    gtk_widget_grab_focus(GTK_WIDGET(d->view));
}

static void on_modified_changed(GtkTextBuffer *b, Doc *d)
{
    if (d->win->cur == d) update_title(d->win);
    else update_tab_label(d);
}

static void on_buffer_changed(GtkTextBuffer *b, Doc *d)
{
    schedule_scan(d, FALSE);
}

static void on_mark_set(GtkTextBuffer *b, GtkTextIter *loc, GtkTextMark *mark, Doc *d)
{
    if (mark != gtk_text_buffer_get_insert(b) || d->win->cur != d) return;
    update_position(d->win);
    update_outline_ui(d->win);
    if (d->search) search_update_count(d->win);
}

/* Bez ligatur pisma (JetBrains Mono dela z -> a >= sipky): GtkTextView nebere font-feature-settings z CSS,
 * proto znacka s font-features na vsem textu (i na nove vlozenem) */
static void on_insert_text(GtkTextBuffer *b, GtkTextIter *end, char *text, int len, Doc *d)
{
    GtkTextIter start;
    gtk_text_buffer_get_iter_at_offset(b, &start, gtk_text_iter_get_offset(end) - g_utf8_strlen(text, len));
    gtk_text_buffer_apply_tag(b, d->nolig, &start, end);
}

static void on_language_changed(GObject *o, GParamSpec *p, Doc *d)
{
    if (d->win->cur == d) update_language_ui(d->win);
    schedule_scan(d, TRUE);
}

/* Ctrl + kolecko = velikost pisma */
static gboolean on_view_scroll(GtkWidget *v, GdkEventScroll *e, Doc *d)
{
    if (!(e->state & GDK_CONTROL_MASK)) return FALSE;
    /* touchpad posila male kroky - po celych dilcich */
    static double acc;
    double dy = 0;
    if (e->direction == GDK_SCROLL_UP) dy = -1;
    else if (e->direction == GDK_SCROLL_DOWN) dy = 1;
    else if (e->direction == GDK_SCROLL_SMOOTH) gdk_event_get_scroll_deltas((GdkEvent *)e, NULL, &dy);
    acc += dy;
    if (acc > -1 && acc < 1) return TRUE;
    cfg.font_size = CLAMP(cfg.font_size + (acc < 0 ? 1 : -1), 6, 72);
    acc = 0;
    apply_font();
    save_config();
    return TRUE;
}

/* Pretazene soubory se otevrou (text a vyber se vklada jako obvykle) */
static void on_drag_data(GtkWidget *wdg, GdkDragContext *ctx, int x, int y, GtkSelectionData *sel, guint info,
                         guint time, Win *w)
{
    if (info != URI_INFO) return;
    char **uris = gtk_selection_data_get_uris(sel);
    GPtrArray *paths = g_ptr_array_new_with_free_func(g_free);
    for (int i = 0; uris && uris[i]; i++) {
        char *p = g_filename_from_uri(uris[i], NULL, NULL);
        if (p) g_ptr_array_add(paths, p);
    }
    g_ptr_array_add(paths, NULL);
    g_strfreev(uris);
    gtk_drag_finish(ctx, paths->len > 1, FALSE, time);
    g_signal_stop_emission_by_name(wdg, "drag-data-received");
    if (paths->len > 1) open_paths(w, (char **)paths->pdata, -1);
    g_ptr_array_unref(paths);
}

static void add_uri_target(GtkWidget *wdg, Win *w)
{
    GtkTargetList *old = gtk_drag_dest_get_target_list(wdg);
    GtkTargetList *tl = gtk_target_list_new(NULL, 0);
    gtk_target_list_add_uri_targets(tl, URI_INFO);   /* soubory maji prednost pred textem */
    if (old) {
        int n = 0;
        GtkTargetEntry *e = gtk_target_table_new_from_list(old, &n);
        gtk_target_list_add_table(tl, e, n);
        gtk_target_table_free(e, n);
    }
    gtk_drag_dest_set_target_list(wdg, tl);
    gtk_target_list_unref(tl);
    g_signal_connect(wdg, "drag-data-received", G_CALLBACK(on_drag_data), w);
}

static void on_tab_close(GtkButton *b, Doc *d) { close_doc(d); }

static Doc *new_doc(Win *w)
{
    Doc *d = g_new0(Doc, 1);
    d->win = w;
    d->enc = tx_encoding_utf8();
    d->le = TX_LF;
    d->untitled = ++untitled_counter;
    d->buf = gtk_source_buffer_new(NULL);
    gtk_source_buffer_set_style_scheme(d->buf, current_scheme());
    gtk_source_buffer_set_highlight_matching_brackets(d->buf, TRUE);
    d->view = GTK_SOURCE_VIEW(gtk_source_view_new_with_buffer(d->buf));
    g_object_unref(d->buf);
    GtkSourceView *v = d->view;
    gtk_style_context_add_class(gtk_widget_get_style_context(GTK_WIDGET(v)), "lt-editor");
    gtk_source_view_set_highlight_current_line(v, TRUE);
    gtk_source_view_set_auto_indent(v, TRUE);
    gtk_source_view_set_indent_on_tab(v, TRUE);
    gtk_source_view_set_tab_width(v, 4);
    gtk_source_view_set_smart_backspace(v, TRUE);
    gtk_source_view_set_smart_home_end(v, GTK_SOURCE_SMART_HOME_END_BEFORE);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(v), 6);
    gtk_text_view_set_right_margin(GTK_TEXT_VIEW(v), 10);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(v), 4);
    /* bez spodniho okraje: s bottom-margin GtkTextView pri prvnim vykresleni rozvrhne cely soubor
     * (1 MB: 1,2 s misto 0,19 s) */
    apply_view_settings(d);
    /* mezera mezi cisly radku a textem */
    GtkSourceGutterRenderer *pad = gtk_source_gutter_renderer_text_new();
    gtk_source_gutter_renderer_text_set_text(GTK_SOURCE_GUTTER_RENDERER_TEXT(pad), " ", -1);
    gtk_source_gutter_renderer_set_size(pad, 8);
    gtk_source_gutter_insert(gtk_source_view_get_gutter(v, GTK_TEXT_WINDOW_LEFT), pad,
                             GTK_SOURCE_VIEW_GUTTER_POSITION_LINES + 1);
    g_signal_connect(d->buf, "modified-changed", G_CALLBACK(on_modified_changed), d);
    g_signal_connect(d->buf, "changed", G_CALLBACK(on_buffer_changed), d);
    g_signal_connect(d->buf, "mark-set", G_CALLBACK(on_mark_set), d);
    g_signal_connect(d->buf, "notify::language", G_CALLBACK(on_language_changed), d);
    d->nolig = gtk_text_buffer_create_tag(GTK_TEXT_BUFFER(d->buf), NULL, "font-features", "calt 0, liga 0, dlig 0", NULL);
    g_signal_connect_after(d->buf, "insert-text", G_CALLBACK(on_insert_text), d);
    g_signal_connect(v, "scroll-event", G_CALLBACK(on_view_scroll), d);
    add_uri_target(GTK_WIDGET(v), w);

    GtkWidget *sw = gtk_scrolled_window_new(NULL, NULL);
    gtk_container_add(GTK_CONTAINER(sw), GTK_WIDGET(v));
    d->page = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_box_pack_end(GTK_BOX(d->page), sw, TRUE, TRUE, 0);
    g_object_set_data(G_OBJECT(d->page), "doc", d);

    GtkWidget *tab = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    d->tab_label = gtk_label_new(NULL);
    gtk_label_set_ellipsize(GTK_LABEL(d->tab_label), PANGO_ELLIPSIZE_MIDDLE);
    gtk_label_set_max_width_chars(GTK_LABEL(d->tab_label), 28);
    gtk_box_pack_start(GTK_BOX(tab), d->tab_label, TRUE, TRUE, 0);
    GtkWidget *x = gtk_button_new_from_icon_name("window-close-symbolic", GTK_ICON_SIZE_MENU);
    gtk_button_set_relief(GTK_BUTTON(x), GTK_RELIEF_NONE);
    gtk_widget_set_tooltip_text(x, T("Close Tab"));
    g_signal_connect(x, "clicked", G_CALLBACK(on_tab_close), d);
    gtk_box_pack_start(GTK_BOX(tab), x, FALSE, FALSE, 0);
    gtk_widget_show_all(tab);
    update_tab_label(d);
    gtk_widget_show_all(d->page);

    int n = gtk_notebook_append_page(GTK_NOTEBOOK(w->notebook), d->page, tab);
    gtk_notebook_set_tab_reorderable(GTK_NOTEBOOK(w->notebook), d->page, TRUE);
    gtk_notebook_set_current_page(GTK_NOTEBOOK(w->notebook), n);
    schedule_scan(d, TRUE);
    return d;
}

static void set_doc_language(Doc *d, const char *data, gsize len)
{
    if (d->lang_manual) return;
    GtkSourceLanguageManager *lm = gtk_source_language_manager_get_default();
    gtk_source_buffer_set_language(d->buf, tx_guess_language(lm, d->path, data, MIN(len, 4096)));
}

/* Nacte soubor (force = kodovani, jinak rozpoznat). Neexistujici soubor = prazdny dokument s cestou. */
static gboolean load_doc(Doc *d, const char *path, const TxEncoding *force, GError **err)
{
    char *data = NULL;
    gsize len = 0;
    GError *e = NULL;
    if (!g_file_get_contents(path, &data, &len, &e)) {
        if (!g_error_matches(e, G_FILE_ERROR, G_FILE_ERROR_NOENT)) {
            g_propagate_error(err, e);
            return FALSE;
        }
        g_clear_error(&e);
        data = g_strdup("");
        len = 0;
    }
    const TxEncoding *enc = force ? force : tx_detect_encoding(data, len, lang_code);
    if (!enc) {
        g_set_error(err, G_IO_ERROR, G_IO_ERROR_INVALID_DATA, "%s", T("The file appears to be a binary file."));
        g_free(data);
        return FALSE;
    }
    gsize ulen = 0;
    char *u = tx_decode(data, len, enc, &ulen, &e);
    g_free(data);
    if (!u) {
        char *el = encoding_label(enc);
        g_set_error(err, G_IO_ERROR, G_IO_ERROR_INVALID_DATA, T("The file cannot be read as %s."), el);
        g_free(el);
        g_clear_error(&e);
        return FALSE;
    }
    TxLineEnd le = tx_detect_line_ending(u, ulen);
    gsize nlen = 0;
    char *norm = tx_normalize_newlines(u, ulen, &nlen);
    g_free(u);

    /* znovu nacteny soubor: kurzor zustane na stejnem radku */
    int keep_line = !g_strcmp0(d->path, path) ? cursor_line(d) : -1;
    if (keep_line < 0) {
        g_free(d->path);
        d->path = g_strdup(path);
    }
    d->enc = enc;
    d->le = le;
    GtkTextBuffer *b = GTK_TEXT_BUFFER(d->buf);
    gtk_source_buffer_begin_not_undoable_action(d->buf);
    gtk_text_buffer_set_text(b, norm, nlen);
    gtk_source_buffer_end_not_undoable_action(d->buf);
    gtk_text_buffer_set_modified(b, FALSE);
    GtkTextIter start;
    if (keep_line > 0) gtk_text_buffer_get_iter_at_line(b, &start, keep_line);
    else gtk_text_buffer_get_start_iter(b, &start);
    gtk_text_buffer_place_cursor(b, &start);
    gtk_source_view_set_insert_spaces_instead_of_tabs(d->view, !tx_detect_tabs(norm, nlen));
    set_doc_language(d, norm, nlen);
    g_free(norm);
    record_disk_state(d);
    watch_file(d);
    hide_infobar(d);
    if (d->disk_exists) add_recent(path);
    schedule_scan(d, TRUE);
    if (d->win->cur == d) update_window(d->win);
    else update_tab_label(d);
    return TRUE;
}

/* ---------- ulozeni ---------- */
static char *choose_save_path(Doc *d)
{
    GtkFileChooserNative *fc = gtk_file_chooser_native_new(T("Save As"), d->win->win, GTK_FILE_CHOOSER_ACTION_SAVE,
                                                          T("Save"), T("Cancel"));
    GtkFileChooser *ch = GTK_FILE_CHOOSER(fc);
    gtk_file_chooser_set_do_overwrite_confirmation(ch, TRUE);
    if (d->path) gtk_file_chooser_set_filename(ch, d->path);
    else {
        gtk_file_chooser_set_current_folder(ch, d->win->root ? d->win->root : home_dir());
        char *name = g_strconcat(T("Untitled"), ".txt", NULL);
        gtk_file_chooser_set_current_name(ch, name);
        g_free(name);
    }
    char *path = NULL;
    if (gtk_native_dialog_run(GTK_NATIVE_DIALOG(fc)) == GTK_RESPONSE_ACCEPT) path = gtk_file_chooser_get_filename(ch);
    g_object_unref(fc);
    return path;
}

/* Znaky, ktere zvolene kodovani neumi: nabidnout ulozeni v UTF-8 */
static gboolean ask_save_utf8(Doc *d)
{
    char *el = encoding_label(d->enc);
    char *msg = g_strdup_printf(T("Some characters cannot be saved in %s."), el);
    GtkWidget *m = gtk_message_dialog_new(d->win->win, GTK_DIALOG_MODAL, GTK_MESSAGE_WARNING, GTK_BUTTONS_NONE, "%s", msg);
    gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(m), "%s",
                                             T("Save the document in Unicode (UTF-8) instead?"));
    gtk_dialog_add_buttons(GTK_DIALOG(m), T("Cancel"), GTK_RESPONSE_CANCEL, T("Save as UTF-8"), GTK_RESPONSE_ACCEPT, NULL);
    gtk_dialog_set_default_response(GTK_DIALOG(m), GTK_RESPONSE_ACCEPT);
    int r = gtk_dialog_run(GTK_DIALOG(m));
    gtk_widget_destroy(m);
    g_free(msg);
    g_free(el);
    return r == GTK_RESPONSE_ACCEPT;
}

static gboolean save_doc(Doc *d, gboolean as)
{
    char *path = NULL;
    if (as || !d->path) {
        path = choose_save_path(d);
        if (!path) return FALSE;
    } else path = g_strdup(d->path);
    char *text = buffer_text(d);
    gsize n = 0;
    GError *err = NULL;
    char *bytes = tx_encode(text, strlen(text), d->enc, d->le, &n, &err);
    if (!bytes) {
        g_clear_error(&err);
        if (!ask_save_utf8(d)) {
            g_free(text);
            g_free(path);
            return FALSE;
        }
        d->enc = tx_encoding_utf8();
        bytes = tx_encode(text, strlen(text), d->enc, d->le, &n, NULL);
    }
    g_free(text);
    GFile *f = g_file_new_for_path(path);
    gboolean ok = g_file_replace_contents(f, bytes, n, NULL, FALSE, G_FILE_CREATE_NONE, NULL, NULL, &err);
    g_object_unref(f);
    g_free(bytes);
    if (!ok) {
        char *base = g_path_get_basename(path);
        char *msg = g_strdup_printf(T("Could not save “%s”."), base);
        message(d->win->win, msg, err->message);
        g_free(msg);
        g_free(base);
        g_error_free(err);
        g_free(path);
        return FALSE;
    }
    gboolean renamed = g_strcmp0(d->path, path) != 0;
    g_free(d->path);
    d->path = path;
    gtk_text_buffer_set_modified(GTK_TEXT_BUFFER(d->buf), FALSE);
    record_disk_state(d);
    hide_infobar(d);
    if (renamed) {
        watch_file(d);
        char *head = NULL;
        GtkTextIter s, e;
        gtk_text_buffer_get_start_iter(GTK_TEXT_BUFFER(d->buf), &s);
        e = s;
        gtk_text_iter_forward_chars(&e, 2048);
        head = gtk_text_buffer_get_text(GTK_TEXT_BUFFER(d->buf), &s, &e, TRUE);
        set_doc_language(d, head, strlen(head));
        g_free(head);
        if (d->win->root) sidebar_select_current(d->win);
    }
    add_recent(d->path);
    update_window(d->win);
    return TRUE;
}

/* Neulozene zmeny: TRUE = muze se zavrit */
static gboolean confirm_close(Doc *d)
{
    if (!gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf))) return TRUE;
    gtk_notebook_set_current_page(GTK_NOTEBOOK(d->win->notebook),
                                  gtk_notebook_page_num(GTK_NOTEBOOK(d->win->notebook), d->page));
    gtk_window_present(d->win->win);
    char *name = doc_name(d);
    char *msg = g_strdup_printf(T("Do you want to save the changes to “%s”?"), name);
    GtkWidget *m = gtk_message_dialog_new(d->win->win, GTK_DIALOG_MODAL, GTK_MESSAGE_WARNING, GTK_BUTTONS_NONE, "%s", msg);
    gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(m), "%s",
                                             T("Your changes will be lost if you don't save them."));
    gtk_dialog_add_buttons(GTK_DIALOG(m), T("Don't Save"), GTK_RESPONSE_REJECT, T("Cancel"), GTK_RESPONSE_CANCEL,
                           T("Save"), GTK_RESPONSE_ACCEPT, NULL);
    gtk_dialog_set_default_response(GTK_DIALOG(m), GTK_RESPONSE_ACCEPT);
    int r = gtk_dialog_run(GTK_DIALOG(m));
    gtk_widget_destroy(m);
    g_free(msg);
    g_free(name);
    if (r == GTK_RESPONSE_REJECT) return TRUE;
    if (r == GTK_RESPONSE_ACCEPT) return save_doc(d, FALSE);
    return FALSE;
}

static void free_doc(Doc *d)
{
    if (d->scan_id) g_source_remove(d->scan_id);
    if (d->check_id) g_source_remove(d->check_id);
    if (d->mon) {
        g_signal_handlers_disconnect_by_data(d->mon, d);
        g_file_monitor_cancel(d->mon);
        g_object_unref(d->mon);
    }
    g_clear_object(&d->search);
    if (d->outline) g_ptr_array_unref(d->outline);
    g_free(d->path);
    g_free(d);
}

/* Zavre panel (posledni panel zavre okno) */
static void close_doc(Doc *d)
{
    if (!confirm_close(d)) return;
    Win *w = d->win;
    if (gtk_notebook_get_n_pages(GTK_NOTEBOOK(w->notebook)) <= 1) {
        remember_size(w);
        w->closing = TRUE;
        gtk_widget_destroy(GTK_WIDGET(w->win));
        return;
    }
    if (w->cur == d) w->cur = NULL;
    g_signal_handlers_disconnect_by_data(d->buf, d);
    gtk_widget_destroy(d->page);
    free_doc(d);
}

/* Otevre soubory v okne: uz otevreny soubor se jen ukaze, prazdny novy dokument se nahradi. */
static void open_paths(Win *w, char **paths, int line)
{
    for (int i = 0; paths && paths[i]; i++) {
        char *abs = g_canonicalize_filename(paths[i], NULL);
        if (g_file_test(abs, G_FILE_TEST_IS_DIR)) {
            sidebar_set_root(w, abs);
            sidebar_show(w, TRUE);
            g_free(abs);
            continue;
        }
        Win *ow = NULL;
        Doc *d = find_open_doc(abs, &ow);
        if (d) {
            gtk_notebook_set_current_page(GTK_NOTEBOOK(ow->notebook), gtk_notebook_page_num(GTK_NOTEBOOK(ow->notebook), d->page));
            gtk_window_present(ow->win);
            if (line > 0) jump_to_line(d, line - 1, 0);
            g_free(abs);
            continue;
        }
        gboolean created = !doc_is_blank(w->cur);
        d = created ? new_doc(w) : w->cur;
        GError *err = NULL;
        if (!load_doc(d, abs, NULL, &err)) {
            char *base = g_path_get_basename(abs);
            char *msg = g_strdup_printf(T("Could not open “%s”."), base);
            message(w->win, msg, err ? err->message : NULL);
            g_free(msg);
            g_free(base);
            g_clear_error(&err);
            if (created && gtk_notebook_get_n_pages(GTK_NOTEBOOK(w->notebook)) > 1) close_doc(d);
            cfg.recent = tx_recent_remove(cfg.recent, abs);
            rebuild_recent_menu();
        } else {
            gtk_notebook_set_current_page(GTK_NOTEBOOK(w->notebook), gtk_notebook_page_num(GTK_NOTEBOOK(w->notebook), d->page));
            if (line > 0) jump_to_line(d, line - 1, 0);
        }
        g_free(abs);
    }
    if (w->root) sidebar_select_current(w);
}

/* ---------- postranni panel: strom slozky ---------- */
typedef struct {
    char *name;
    char *ctype;
    gboolean dir;
} Entry;

static int entry_cmp(gconstpointer a, gconstpointer b)
{
    const Entry *x = *(Entry **)a, *y = *(Entry **)b;
    if (x->dir != y->dir) return x->dir ? -1 : 1;
    char *kx = g_utf8_collate_key_for_filename(x->name, -1), *ky = g_utf8_collate_key_for_filename(y->name, -1);
    int r = strcmp(kx, ky);
    g_free(kx);
    g_free(ky);
    return r;
}

static void entry_free(gpointer p)
{
    Entry *e = p;
    g_free(e->name);
    g_free(e->ctype);
    g_free(e);
}

static void watch_dir(Win *w, const char *dir);

/* Obsah slozky pod parent (NULL = koren); slozky dostanou zastupny radek, aby sly rozbalit */
static void populate_dir(Win *w, GtkTreeIter *parent, const char *dir)
{
    GFile *f = g_file_new_for_path(dir);
    GFileEnumerator *en = g_file_enumerate_children(f, G_FILE_ATTRIBUTE_STANDARD_NAME "," G_FILE_ATTRIBUTE_STANDARD_TYPE ","
                                                    G_FILE_ATTRIBUTE_STANDARD_IS_HIDDEN "," G_FILE_ATTRIBUTE_STANDARD_IS_BACKUP ","
                                                    G_FILE_ATTRIBUTE_STANDARD_FAST_CONTENT_TYPE,
                                                    G_FILE_QUERY_INFO_NONE, NULL, NULL);
    g_object_unref(f);
    if (!en) return;
    GPtrArray *a = g_ptr_array_new_with_free_func(entry_free);
    GFileInfo *fi;
    while ((fi = g_file_enumerator_next_file(en, NULL, NULL))) {
        if (!g_file_info_get_is_hidden(fi) && !g_file_info_get_is_backup(fi)) {
            Entry *e = g_new0(Entry, 1);
            e->name = g_strdup(g_file_info_get_name(fi));
            e->dir = g_file_info_get_file_type(fi) == G_FILE_TYPE_DIRECTORY;
            const char *ct = g_file_info_get_attribute_string(fi, G_FILE_ATTRIBUTE_STANDARD_FAST_CONTENT_TYPE);
            e->ctype = g_strdup(ct ? ct : "text/plain");
            g_ptr_array_add(a, e);
        }
        g_object_unref(fi);
    }
    g_object_unref(en);
    g_ptr_array_sort(a, entry_cmp);
    GIcon *folder = g_themed_icon_new_with_default_fallbacks("folder");
    for (guint i = 0; i < a->len; i++) {
        Entry *e = a->pdata[i];
        char *p = g_build_filename(dir, e->name, NULL);
        GIcon *icon = e->dir ? g_object_ref(folder) : g_content_type_get_icon(e->ctype);
        GtkTreeIter it;
        gtk_tree_store_insert_with_values(w->store, &it, parent, -1, COL_ICON, icon, COL_NAME, e->name, COL_PATH, p,
                                          COL_DIR, e->dir, COL_LOADED, FALSE, COL_WEIGHT, PANGO_WEIGHT_NORMAL, -1);
        if (e->dir) gtk_tree_store_insert_with_values(w->store, NULL, &it, -1, COL_NAME, NULL, -1);
        g_object_unref(icon);
        g_free(p);
    }
    g_object_unref(folder);
    g_ptr_array_unref(a);
    watch_dir(w, dir);
}

/* Najde radek podle cesty (jen nactene casti stromu) */
static gboolean find_row(Win *w, const char *path, GtkTreeIter *out)
{
    if (!w->root || strncmp(path, w->root, strlen(w->root))) return FALSE;
    const char *rel = path + strlen(w->root);
    while (*rel == '/') rel++;
    if (!*rel) return FALSE;
    char **parts = g_strsplit(rel, "/", -1);
    GtkTreeModel *m = GTK_TREE_MODEL(w->store);
    GtkTreeIter it, *parent = NULL, pit;
    gboolean found = FALSE;
    for (int i = 0; parts[i]; i++) {
        found = FALSE;
        if (gtk_tree_model_iter_children(m, &it, parent)) {
            do {
                char *name = NULL;
                gtk_tree_model_get(m, &it, COL_NAME, &name, -1);
                gboolean eq = name && !strcmp(name, parts[i]);
                g_free(name);
                if (eq) { found = TRUE; break; }
            } while (gtk_tree_model_iter_next(m, &it));
        }
        if (!found) break;
        pit = it;
        parent = &pit;
    }
    g_strfreev(parts);
    if (found) *out = it;
    return found;
}

static void ensure_loaded(Win *w, GtkTreeIter *it)
{
    gboolean loaded = FALSE, dir = FALSE;
    char *path = NULL;
    gtk_tree_model_get(GTK_TREE_MODEL(w->store), it, COL_LOADED, &loaded, COL_DIR, &dir, COL_PATH, &path, -1);
    if (dir && !loaded) {
        GtkTreeIter ch;
        while (gtk_tree_model_iter_children(GTK_TREE_MODEL(w->store), &ch, it)) gtk_tree_store_remove(w->store, &ch);
        gtk_tree_store_set(w->store, it, COL_LOADED, TRUE, -1);
        populate_dir(w, it, path);
    }
    g_free(path);
}

static gboolean on_test_expand(GtkTreeView *tv, GtkTreeIter *it, GtkTreePath *p, Win *w)
{
    ensure_loaded(w, it);
    return FALSE;
}

/* Rozbali cestu k souboru a vybere ho (soubor v okne zvyrazneny) */
static void sidebar_select_current(Win *w)
{
    if (!w->root || !w->tree || !gtk_widget_get_visible(w->sidebar)) return;
    GtkTreeSelection *sel = gtk_tree_view_get_selection(GTK_TREE_VIEW(w->tree));
    Doc *d = w->cur;
    size_t rl = strlen(w->root);
    if (!d || !d->path || strncmp(d->path, w->root, rl) || d->path[rl] != '/') {
        gtk_tree_selection_unselect_all(sel);
        return;
    }
    /* po slozkach od korene: nacist a rozbalit */
    char **parts = g_strsplit(d->path + rl + 1, "/", -1);
    GString *cur = g_string_new(w->root);
    GtkTreeIter it;
    gboolean ok = TRUE;
    for (int i = 0; parts[i] && ok; i++) {
        g_string_append_c(cur, '/');
        g_string_append(cur, parts[i]);
        ok = find_row(w, cur->str, &it);
        if (ok && parts[i + 1]) {
            ensure_loaded(w, &it);
            GtkTreePath *tp = gtk_tree_model_get_path(GTK_TREE_MODEL(w->store), &it);
            gtk_tree_view_expand_row(GTK_TREE_VIEW(w->tree), tp, FALSE);
            gtk_tree_path_free(tp);
        }
    }
    if (ok) {
        GtkTreePath *tp = gtk_tree_model_get_path(GTK_TREE_MODEL(w->store), &it);
        gtk_tree_selection_select_path(sel, tp);
        gtk_tree_view_scroll_to_cell(GTK_TREE_VIEW(w->tree), tp, NULL, FALSE, 0, 0);
        gtk_tree_path_free(tp);
    } else gtk_tree_selection_unselect_all(sel);
    g_string_free(cur, TRUE);
    g_strfreev(parts);
}

/* Znovu nacte slozku a zachova rozbalene podslozky */
static void collect_expanded(GtkTreeView *tv, GtkTreePath *p, gpointer list)
{
    GtkTreeIter it;
    char *path = NULL;
    GtkTreeModel *m = gtk_tree_view_get_model(tv);
    if (gtk_tree_model_get_iter(m, &it, p)) gtk_tree_model_get(m, &it, COL_PATH, &path, -1);
    if (path) g_ptr_array_add(list, path);
}

static int by_length(gconstpointer a, gconstpointer b)
{
    return (int)strlen(*(char **)a) - (int)strlen(*(char **)b);
}

static void rescan_dir(Win *w, const char *dir)
{
    if (!w->root) return;
    GPtrArray *exp = g_ptr_array_new_with_free_func(g_free);
    gtk_tree_view_map_expanded_rows(GTK_TREE_VIEW(w->tree), collect_expanded, exp);
    if (!strcmp(dir, w->root)) {
        gtk_tree_store_clear(w->store);
        populate_dir(w, NULL, w->root);
    } else {
        GtkTreeIter it, ch;
        gboolean loaded = FALSE;
        if (!find_row(w, dir, &it)) goto out;
        gtk_tree_model_get(GTK_TREE_MODEL(w->store), &it, COL_LOADED, &loaded, -1);
        if (!loaded) goto out;
        while (gtk_tree_model_iter_children(GTK_TREE_MODEL(w->store), &ch, &it)) gtk_tree_store_remove(w->store, &ch);
        populate_dir(w, &it, dir);
    }
    g_ptr_array_sort(exp, by_length);
    for (guint i = 0; i < exp->len; i++) {
        GtkTreeIter it;
        if (find_row(w, exp->pdata[i], &it)) {
            ensure_loaded(w, &it);
            GtkTreePath *tp = gtk_tree_model_get_path(GTK_TREE_MODEL(w->store), &it);
            gtk_tree_view_expand_row(GTK_TREE_VIEW(w->tree), tp, FALSE);
            gtk_tree_path_free(tp);
        }
    }
    sidebar_select_current(w);
out:
    g_ptr_array_unref(exp);
}

/* Zmena ve slozce: znovu nacist za chvili (okno muze mezitim zaniknout - "win" je pak NULL) */
static gboolean rescan_idle(gpointer p)
{
    GFileMonitor *m = p;
    Win *w = g_object_get_data(G_OBJECT(m), "win");
    g_object_set_data(G_OBJECT(m), "pending", NULL);
    if (w) rescan_dir(w, g_object_get_data(G_OBJECT(m), "dir"));
    g_object_unref(m);
    return G_SOURCE_REMOVE;
}

static void on_dir_changed(GFileMonitor *m, GFile *f, GFile *o, GFileMonitorEvent ev, Win *w)
{
    if (ev == G_FILE_MONITOR_EVENT_CHANGED || ev == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT ||
        ev == G_FILE_MONITOR_EVENT_ATTRIBUTE_CHANGED || g_object_get_data(G_OBJECT(m), "pending"))
        return;
    g_object_set_data(G_OBJECT(m), "pending", GINT_TO_POINTER(1));
    g_timeout_add(250, rescan_idle, g_object_ref(m));
}

static void watch_dir(Win *w, const char *dir)
{
    if (g_hash_table_contains(w->dir_mons, dir)) return;
    GFile *f = g_file_new_for_path(dir);
    GFileMonitor *m = g_file_monitor_directory(f, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
    g_object_unref(f);
    if (!m) return;
    g_object_set_data_full(G_OBJECT(m), "dir", g_strdup(dir), g_free);
    g_object_set_data(G_OBJECT(m), "win", w);
    g_signal_connect(m, "changed", G_CALLBACK(on_dir_changed), w);
    g_hash_table_insert(w->dir_mons, g_strdup(dir), m);
}

static void drop_dir_monitors(Win *w)
{
    GHashTableIter hi;
    gpointer k, v;
    g_hash_table_iter_init(&hi, w->dir_mons);
    while (g_hash_table_iter_next(&hi, &k, &v)) {
        g_object_set_data(G_OBJECT(v), "win", NULL);
        g_signal_handlers_disconnect_by_data(v, w);
        g_file_monitor_cancel(v);
    }
    g_hash_table_remove_all(w->dir_mons);
}

static void sidebar_set_root(Win *w, const char *dir)
{
    if (w->root && !strcmp(w->root, dir)) return;
    g_free(w->root);
    w->root = g_strdup(dir);
    drop_dir_monitors(w);
    gtk_tree_store_clear(w->store);
    char *base = g_path_get_basename(dir);
    gtk_label_set_text(GTK_LABEL(w->root_label), !strcmp(dir, "/") ? "/" : base);
    gtk_widget_set_tooltip_text(w->root_label, dir);
    g_free(base);
    if (gtk_widget_get_visible(w->sidebar)) {
        populate_dir(w, NULL, w->root);
        sidebar_select_current(w);
    } else g_object_set_data(G_OBJECT(w->tree), "stale", GINT_TO_POINTER(1));
}

static void sidebar_show(Win *w, gboolean show)
{
    GAction *a = g_action_map_lookup_action(G_ACTION_MAP(w->win), "sidebar");
    if (a) g_simple_action_set_state(G_SIMPLE_ACTION(a), g_variant_new_boolean(show));
    if (show == gtk_widget_get_visible(w->sidebar)) return;
    if (show && !w->root) {
        char *dir = w->cur && w->cur->path ? g_path_get_dirname(w->cur->path) : g_strdup(home_dir());
        sidebar_set_root(w, dir);
        g_free(dir);
    }
    gtk_widget_set_visible(w->sidebar, show);
    if (show) {
        gtk_paned_set_position(GTK_PANED(w->paned), cfg.sidebar_width);
        if (g_object_get_data(G_OBJECT(w->tree), "stale")) {
            g_object_set_data(G_OBJECT(w->tree), "stale", NULL);
            populate_dir(w, NULL, w->root);
        }
        sidebar_select_current(w);
    }
}

static gboolean on_tree_release(GtkWidget *tv, GdkEventButton *e, Win *w)
{
    if (e->button != 1) return FALSE;
    GtkTreePath *tp = NULL;
    GtkTreeViewColumn *col = NULL;
    int cx, cy;
    if (!gtk_tree_view_get_path_at_pos(GTK_TREE_VIEW(tv), e->x, e->y, &tp, &col, &cx, &cy)) return FALSE;
    /* klik na sipku rozbaleni nic neotvira */
    GdkRectangle cell;
    gtk_tree_view_get_cell_area(GTK_TREE_VIEW(tv), tp, col, &cell);
    GtkTreeIter it;
    char *path = NULL;
    gboolean dir = FALSE;
    if (e->x >= cell.x && gtk_tree_model_get_iter(GTK_TREE_MODEL(w->store), &it, tp))
        gtk_tree_model_get(GTK_TREE_MODEL(w->store), &it, COL_PATH, &path, COL_DIR, &dir, -1);
    if (path && dir) {
        if (gtk_tree_view_row_expanded(GTK_TREE_VIEW(tv), tp)) gtk_tree_view_collapse_row(GTK_TREE_VIEW(tv), tp);
        else gtk_tree_view_expand_row(GTK_TREE_VIEW(tv), tp, FALSE);
    } else if (path) {
        char *paths[] = {path, NULL};
        open_paths(w, paths, -1);
    }
    g_free(path);
    gtk_tree_path_free(tp);
    return FALSE;
}

static void on_tree_activated(GtkTreeView *tv, GtkTreePath *tp, GtkTreeViewColumn *c, Win *w)
{
    GtkTreeIter it;
    char *path = NULL;
    gboolean dir = FALSE;
    if (!gtk_tree_model_get_iter(GTK_TREE_MODEL(w->store), &it, tp)) return;
    gtk_tree_model_get(GTK_TREE_MODEL(w->store), &it, COL_PATH, &path, COL_DIR, &dir, -1);
    if (path && !dir) {
        char *paths[] = {path, NULL};
        open_paths(w, paths, -1);
    }
    g_free(path);
}

/* Slozka pro novy soubor: vybrana slozka, slozka vybraneho souboru, jinak koren */
static char *target_dir(Win *w)
{
    GtkTreeIter it;
    GtkTreeModel *m;
    char *path = NULL;
    gboolean dir = FALSE;
    if (w->tree && gtk_tree_selection_get_selected(gtk_tree_view_get_selection(GTK_TREE_VIEW(w->tree)), &m, &it))
        gtk_tree_model_get(m, &it, COL_PATH, &path, COL_DIR, &dir, -1);
    if (path && !dir) {
        char *p = g_path_get_dirname(path);
        g_free(path);
        return p;
    }
    return path ? path : g_strdup(w->root ? w->root : home_dir());
}

static char *ask_name(Win *w, const char *title, const char *initial)
{
    GtkWidget *dlg = gtk_dialog_new_with_buttons(title, w->win, GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT |
                                                 GTK_DIALOG_USE_HEADER_BAR, T("Cancel"), GTK_RESPONSE_CANCEL,
                                                 T("Create"), GTK_RESPONSE_ACCEPT, NULL);
    gtk_dialog_set_default_response(GTK_DIALOG(dlg), GTK_RESPONSE_ACCEPT);
    GtkWidget *box = gtk_dialog_get_content_area(GTK_DIALOG(dlg));
    gtk_container_set_border_width(GTK_CONTAINER(box), 12);
    GtkWidget *lbl = gtk_label_new(T("Name:"));
    gtk_label_set_xalign(GTK_LABEL(lbl), 0);
    GtkWidget *e = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(e), initial);
    gtk_entry_set_activates_default(GTK_ENTRY(e), TRUE);
    gtk_entry_set_width_chars(GTK_ENTRY(e), 32);
    gtk_box_pack_start(GTK_BOX(box), lbl, FALSE, FALSE, 4);
    gtk_box_pack_start(GTK_BOX(box), e, FALSE, FALSE, 0);
    gtk_widget_show_all(dlg);
    /* jmeno bez pripony vybrane */
    const char *dot = strrchr(initial, '.');
    gtk_editable_select_region(GTK_EDITABLE(e), 0, dot && dot != initial ? g_utf8_pointer_to_offset(initial, dot) : -1);
    char *res = NULL;
    if (gtk_dialog_run(GTK_DIALOG(dlg)) == GTK_RESPONSE_ACCEPT) {
        const char *t = gtk_entry_get_text(GTK_ENTRY(e));
        if (*t && !strchr(t, '/') && strcmp(t, ".") && strcmp(t, "..")) res = g_strdup(t);
    }
    gtk_widget_destroy(dlg);
    return res;
}

static void sidebar_new(Win *w, gboolean folder)
{
    char *dir = target_dir(w);
    char *initial = folder ? g_strdup(T("New Folder")) : g_strconcat(T("untitled"), ".txt", NULL);
    char *name = ask_name(w, folder ? T("New Folder") : T("New File"), initial);
    g_free(initial);
    if (!name) { g_free(dir); return; }
    char *path = g_build_filename(dir, name, NULL);
    gboolean ok;
    if (g_file_test(path, G_FILE_TEST_EXISTS)) {
        char *msg = g_strdup_printf(T("“%s” already exists."), name);
        message(w->win, msg, NULL);
        g_free(msg);
        ok = FALSE;
    } else if (folder) ok = g_mkdir(path, 0755) == 0;
    else ok = g_file_set_contents(path, "", 0, NULL);
    if (!ok && !g_file_test(path, G_FILE_TEST_EXISTS)) {
        char *msg = g_strdup_printf(T("Could not create “%s”."), name);
        message(w->win, msg, g_strerror(errno));
        g_free(msg);
    } else if (ok) {
        /* hned zobrazit (sledovani slozky by to udelalo az za chvili) */
        GtkTreeIter it;
        if (find_row(w, dir, &it)) {
            ensure_loaded(w, &it);
            GtkTreePath *tp = gtk_tree_model_get_path(GTK_TREE_MODEL(w->store), &it);
            gtk_tree_view_expand_row(GTK_TREE_VIEW(w->tree), tp, FALSE);
            gtk_tree_path_free(tp);
        }
        rescan_dir(w, dir);
        if (!folder) {
            char *paths[] = {path, NULL};
            open_paths(w, paths, -1);
        }
    }
    g_free(path);
    g_free(name);
    g_free(dir);
}

static GtkWidget *build_sidebar(Win *w)
{
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(box), "lt-sidebar");
    w->root_label = gtk_label_new(NULL);
    gtk_label_set_xalign(GTK_LABEL(w->root_label), 0);
    gtk_label_set_ellipsize(GTK_LABEL(w->root_label), PANGO_ELLIPSIZE_MIDDLE);
    gtk_style_context_add_class(gtk_widget_get_style_context(w->root_label), "lt-root");
    gtk_box_pack_start(GTK_BOX(box), w->root_label, FALSE, FALSE, 0);

    w->store = gtk_tree_store_new(N_COLS, G_TYPE_ICON, G_TYPE_STRING, G_TYPE_STRING, G_TYPE_BOOLEAN, G_TYPE_BOOLEAN, G_TYPE_INT);
    w->tree = gtk_tree_view_new_with_model(GTK_TREE_MODEL(w->store));
    g_object_unref(w->store);
    gtk_tree_view_set_headers_visible(GTK_TREE_VIEW(w->tree), FALSE);
    gtk_tree_view_set_enable_search(GTK_TREE_VIEW(w->tree), TRUE);
    gtk_tree_view_set_search_column(GTK_TREE_VIEW(w->tree), COL_NAME);
    gtk_tree_view_set_activate_on_single_click(GTK_TREE_VIEW(w->tree), FALSE);
    GtkTreeViewColumn *col = gtk_tree_view_column_new();
    GtkCellRenderer *pr = gtk_cell_renderer_pixbuf_new();
    g_object_set(pr, "stock-size", GTK_ICON_SIZE_MENU, "xpad", 2, NULL);
    gtk_tree_view_column_pack_start(col, pr, FALSE);
    gtk_tree_view_column_add_attribute(col, pr, "gicon", COL_ICON);
    GtkCellRenderer *tr = gtk_cell_renderer_text_new();
    g_object_set(tr, "ellipsize", PANGO_ELLIPSIZE_MIDDLE, "ypad", 2, NULL);
    gtk_tree_view_column_pack_start(col, tr, TRUE);
    gtk_tree_view_column_add_attribute(col, tr, "text", COL_NAME);
    gtk_tree_view_append_column(GTK_TREE_VIEW(w->tree), col);
    g_signal_connect(w->tree, "test-expand-row", G_CALLBACK(on_test_expand), w);
    g_signal_connect(w->tree, "button-release-event", G_CALLBACK(on_tree_release), w);
    g_signal_connect(w->tree, "row-activated", G_CALLBACK(on_tree_activated), w);
    GtkWidget *sw = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(sw), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_container_add(GTK_CONTAINER(sw), w->tree);
    gtk_box_pack_start(GTK_BOX(box), sw, TRUE, TRUE, 0);

    GtkWidget *bar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(bar), "lt-sidebar-bar");
    GtkWidget *add = gtk_menu_button_new();
    gtk_button_set_image(GTK_BUTTON(add), gtk_image_new_from_icon_name("list-add-symbolic", GTK_ICON_SIZE_BUTTON));
    gtk_widget_set_tooltip_text(add, T("New File or Folder"));
    GMenu *m = g_menu_new();
    g_menu_append(m, T("New File…"), "win.new-file");
    g_menu_append(m, T("New Folder…"), "win.new-folder");
    gtk_menu_button_set_menu_model(GTK_MENU_BUTTON(add), G_MENU_MODEL(m));
    g_object_unref(m);
    gtk_box_pack_start(GTK_BOX(bar), add, FALSE, FALSE, 0);
    gtk_box_pack_end(GTK_BOX(box), bar, FALSE, FALSE, 0);
    gtk_widget_show_all(box);
    gtk_widget_set_no_show_all(box, TRUE);
    gtk_widget_hide(box);
    return box;
}

/* ---------- hledani a nahrazovani ---------- */
static GtkSourceSearchContext *doc_search(Doc *d)
{
    if (!d->search) {
        d->search = gtk_source_search_context_new(d->buf, d->win->ss);
        g_signal_connect_swapped(d->search, "notify::occurrences-count", G_CALLBACK(search_update_count), d->win);
    }
    gtk_source_search_context_set_highlight(d->search, gtk_revealer_get_reveal_child(GTK_REVEALER(d->win->find_rev)));
    return d->search;
}

static void search_update_count(Win *w)
{
    Doc *d = w->cur;
    if (!d || !d->search || !gtk_revealer_get_reveal_child(GTK_REVEALER(w->find_rev))) return;
    GtkStyleContext *sc = gtk_widget_get_style_context(w->find_entry);
    GError *re = gtk_source_search_context_get_regex_error(d->search);
    const char *text = gtk_source_search_settings_get_search_text(w->ss);
    if (re) {
        gtk_label_set_text(GTK_LABEL(w->find_count), T("Invalid pattern"));
        gtk_widget_set_tooltip_text(w->find_count, re->message);
        gtk_style_context_add_class(sc, "error");
        g_error_free(re);
        return;
    }
    gtk_style_context_remove_class(sc, "error");
    gtk_widget_set_tooltip_text(w->find_count, NULL);
    if (w->replaced) {
        char *t = g_strdup_printf(T("%d replaced"), w->replaced);
        gtk_label_set_text(GTK_LABEL(w->find_count), t);
        g_free(t);
        return;
    }
    if (!text || !*text) {
        gtk_label_set_text(GTK_LABEL(w->find_count), "");
        return;
    }
    int count = gtk_source_search_context_get_occurrences_count(d->search);
    if (count < 0) return;   /* jeste se pocita */
    if (count == 0) {
        gtk_label_set_text(GTK_LABEL(w->find_count), T("No results"));
        gtk_style_context_add_class(sc, "error");
        return;
    }
    GtkTextIter s, e;
    gtk_text_buffer_get_selection_bounds(GTK_TEXT_BUFFER(d->buf), &s, &e);
    int pos = gtk_source_search_context_get_occurrence_position(d->search, &s, &e);
    char *t = pos > 0 ? g_strdup_printf(T("%d of %d"), pos, count) : g_strdup_printf(T("%d found"), count);
    gtk_label_set_text(GTK_LABEL(w->find_count), t);
    g_free(t);
}

static gboolean search_move(Win *w, gboolean forward, gboolean from_start_of_selection)
{
    Doc *d = w->cur;
    w->replaced = 0;
    if (!d) return FALSE;
    const char *text = gtk_source_search_settings_get_search_text(w->ss);
    if (!text || !*text) return FALSE;
    GtkSourceSearchContext *ctx = doc_search(d);
    GtkTextIter s, e, ms, me;
    gboolean wrapped;
    gtk_text_buffer_get_selection_bounds(GTK_TEXT_BUFFER(d->buf), &s, &e);
    gboolean found = forward ? gtk_source_search_context_forward(ctx, from_start_of_selection ? &s : &e, &ms, &me, &wrapped)
                             : gtk_source_search_context_backward(ctx, &s, &ms, &me, &wrapped);
    if (found) {
        gtk_text_buffer_select_range(GTK_TEXT_BUFFER(d->buf), &ms, &me);
        gtk_text_view_scroll_to_mark(GTK_TEXT_VIEW(d->view), gtk_text_buffer_get_insert(GTK_TEXT_BUFFER(d->buf)),
                                     0.1, FALSE, 0, 0);
    }
    search_update_count(w);
    return found;
}

static void on_find_changed(GtkSearchEntry *e, Win *w)
{
    const char *t = gtk_entry_get_text(GTK_ENTRY(e));
    w->replaced = 0;
    gtk_source_search_settings_set_search_text(w->ss, *t ? t : NULL);
    if (w->cur) {
        doc_search(w->cur);
        if (*t) search_move(w, TRUE, TRUE);   /* hledani pri psani od zacatku vyberu */
        search_update_count(w);
    }
}

static void find_next(Win *w) { search_move(w, TRUE, FALSE); }
static void find_prev(Win *w) { search_move(w, FALSE, FALSE); }

static void hide_find(Win *w)
{
    gtk_revealer_set_reveal_child(GTK_REVEALER(w->find_rev), FALSE);
    GList *docs = all_docs(w);
    for (GList *l = docs; l; l = l->next)
        if (((Doc *)l->data)->search) gtk_source_search_context_set_highlight(((Doc *)l->data)->search, FALSE);
    g_list_free(docs);
    if (w->cur) gtk_widget_grab_focus(GTK_WIDGET(w->cur->view));
}

static void show_find(Win *w, gboolean replace)
{
    Doc *d = w->cur;
    if (!d) return;
    /* druhe Ctrl+H v poli hledani = do pole Nahradit */
    if (replace && gtk_revealer_get_reveal_child(GTK_REVEALER(w->find_rev)) && gtk_widget_get_visible(w->replace_row) &&
        gtk_widget_has_focus(w->find_entry)) {
        gtk_widget_grab_focus(w->replace_entry);
        return;
    }
    w->replaced = 0;
    gtk_widget_set_visible(w->replace_row, replace);
    gtk_revealer_set_reveal_child(GTK_REVEALER(w->find_rev), TRUE);
    /* vybrany text (jeden radek) jako hledany */
    GtkTextIter s, e;
    if (gtk_text_buffer_get_selection_bounds(GTK_TEXT_BUFFER(d->buf), &s, &e) &&
        gtk_text_iter_get_line(&s) == gtk_text_iter_get_line(&e)) {
        char *sel = gtk_text_buffer_get_text(GTK_TEXT_BUFFER(d->buf), &s, &e, FALSE);
        if (gtk_source_search_settings_get_regex_enabled(w->ss)) {
            char *q = g_regex_escape_string(sel, -1);
            g_free(sel);
            sel = q;
        }
        gtk_entry_set_text(GTK_ENTRY(w->find_entry), sel);
        g_free(sel);
    }
    doc_search(d);
    search_update_count(w);
    gtk_widget_grab_focus(w->find_entry);
    gtk_editable_select_region(GTK_EDITABLE(w->find_entry), 0, -1);
}

static void replace_one(Win *w)
{
    Doc *d = w->cur;
    if (!d || !gtk_source_search_settings_get_search_text(w->ss)) return;
    GtkSourceSearchContext *ctx = doc_search(d);
    GtkTextIter s, e;
    gtk_text_buffer_get_selection_bounds(GTK_TEXT_BUFFER(d->buf), &s, &e);
    /* vybrany vyskyt nahradit, pak najit dalsi */
    if (gtk_source_search_context_get_occurrence_position(ctx, &s, &e) > 0) {
        const char *r = gtk_entry_get_text(GTK_ENTRY(w->replace_entry));
        gtk_source_search_context_replace(ctx, &s, &e, r, -1, NULL);
        gtk_text_buffer_place_cursor(GTK_TEXT_BUFFER(d->buf), &e);
    }
    search_move(w, TRUE, FALSE);
}

static void replace_all(Win *w)
{
    Doc *d = w->cur;
    if (!d || !gtk_source_search_settings_get_search_text(w->ss)) return;
    GtkSourceSearchContext *ctx = doc_search(d);
    guint n = gtk_source_search_context_replace_all(ctx, gtk_entry_get_text(GTK_ENTRY(w->replace_entry)), -1, NULL);
    w->replaced = n;
    search_update_count(w);
}

static gboolean on_find_key(GtkWidget *e, GdkEventKey *ev, Win *w)
{
    if (ev->keyval == GDK_KEY_Escape) {
        hide_find(w);
        return TRUE;
    }
    if (ev->keyval == GDK_KEY_Return || ev->keyval == GDK_KEY_KP_Enter) {
        if (e == w->replace_entry) replace_one(w);
        else if (ev->state & GDK_SHIFT_MASK) find_prev(w);
        else find_next(w);
        return TRUE;
    }
    return FALSE;
}

/* Volby hledani jako akce okna (tlacitka Aa, ab|, .* a Alt+C, Alt+W, Alt+R) */
static void act_find_option(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    GVariant *st = g_action_get_state(G_ACTION(a));
    gboolean on = !g_variant_get_boolean(st);
    g_variant_unref(st);
    g_simple_action_set_state(a, g_variant_new_boolean(on));
    const char *name = g_action_get_name(G_ACTION(a));
    if (!strcmp(name, "find-case")) gtk_source_search_settings_set_case_sensitive(w->ss, on);
    else if (!strcmp(name, "find-regex")) gtk_source_search_settings_set_regex_enabled(w->ss, on);
    else gtk_source_search_settings_set_at_word_boundaries(w->ss, on);
    w->replaced = 0;
    search_update_count(w);
}

static GtkWidget *small_button(const char *icon, const char *tip, GCallback cb, gpointer data)
{
    GtkWidget *b = gtk_button_new_from_icon_name(icon, GTK_ICON_SIZE_MENU);
    gtk_widget_set_tooltip_text(b, tip);
    gtk_widget_set_valign(b, GTK_ALIGN_CENTER);
    if (cb) g_signal_connect_swapped(b, "clicked", cb, data);
    return b;
}

static GtkWidget *toggle(const char *label, const char *tip, const char *action)
{
    GtkWidget *b = gtk_toggle_button_new_with_label(label);
    gtk_widget_set_tooltip_text(b, tip);
    gtk_widget_set_valign(b, GTK_ALIGN_CENTER);
    gtk_style_context_add_class(gtk_widget_get_style_context(b), "lt-toggle");
    gtk_actionable_set_action_name(GTK_ACTIONABLE(b), action);
    return b;
}

static GtkWidget *build_find(Win *w)
{
    w->ss = gtk_source_search_settings_new();
    gtk_source_search_settings_set_wrap_around(w->ss, TRUE);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    gtk_style_context_add_class(gtk_widget_get_style_context(box), "lt-find");
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    w->find_entry = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(w->find_entry), T("Find"));
    g_signal_connect(w->find_entry, "search-changed", G_CALLBACK(on_find_changed), w);
    g_signal_connect(w->find_entry, "key-press-event", G_CALLBACK(on_find_key), w);
    gtk_box_pack_start(GTK_BOX(row), w->find_entry, TRUE, TRUE, 0);
    w->find_count = gtk_label_new("");
    gtk_style_context_add_class(gtk_widget_get_style_context(w->find_count), "lt-count");
    gtk_box_pack_start(GTK_BOX(row), w->find_count, FALSE, FALSE, 4);
    GtkWidget *nav = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(nav), "linked");
    gtk_box_pack_start(GTK_BOX(nav), small_button("go-up-symbolic", T("Previous"), G_CALLBACK(find_prev), w), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), small_button("go-down-symbolic", T("Next"), G_CALLBACK(find_next), w), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), nav, FALSE, FALSE, 0);
    w->case_btn = toggle("Aa", T("Match Case"), "win.find-case");
    w->word_btn = toggle("ab|", T("Whole Words"), "win.find-words");
    w->regex_btn = toggle(".*", T("Regular Expression"), "win.find-regex");
    gtk_box_pack_start(GTK_BOX(row), w->case_btn, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), w->word_btn, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), w->regex_btn, FALSE, FALSE, 0);
    GtkWidget *done = gtk_button_new_with_label(T("Done"));
    gtk_widget_set_valign(done, GTK_ALIGN_CENTER);
    g_signal_connect_swapped(done, "clicked", G_CALLBACK(hide_find), w);
    gtk_box_pack_start(GTK_BOX(row), done, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), row, FALSE, FALSE, 0);

    w->replace_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    w->replace_entry = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(w->replace_entry), T("Replace"));
    g_signal_connect(w->replace_entry, "key-press-event", G_CALLBACK(on_find_key), w);
    gtk_box_pack_start(GTK_BOX(w->replace_row), w->replace_entry, TRUE, TRUE, 0);
    GtkWidget *r1 = gtk_button_new_with_label(T("Replace"));
    g_signal_connect_swapped(r1, "clicked", G_CALLBACK(replace_one), w);
    GtkWidget *r2 = gtk_button_new_with_label(T("Replace All"));
    gtk_actionable_set_action_name(GTK_ACTIONABLE(r2), "win.replace-all");
    gtk_box_pack_start(GTK_BOX(w->replace_row), r1, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(w->replace_row), r2, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(box), w->replace_row, FALSE, FALSE, 0);
    gtk_widget_show_all(box);

    w->find_rev = gtk_revealer_new();
    gtk_revealer_set_transition_duration(GTK_REVEALER(w->find_rev), 120);
    gtk_container_add(GTK_CONTAINER(w->find_rev), box);
    return w->find_rev;
}

/* ---------- prejit na radek ---------- */
static void on_goto_activate(GtkEntry *e, Win *w)
{
    int line = 0, col = 0;
    const char *t = gtk_entry_get_text(e);
    if (sscanf(t, "%d:%d", &line, &col) >= 1 && w->cur) {
        jump_to_line(w->cur, line - 1, col > 0 ? col - 1 : 0);
        gtk_popover_popdown(GTK_POPOVER(w->goto_pop));
    }
}

static void show_goto(Win *w)
{
    if (!w->cur) return;
    char *t = g_strdup_printf("%d", cursor_line(w->cur) + 1);
    gtk_entry_set_text(GTK_ENTRY(w->goto_entry), t);
    g_free(t);
    gtk_popover_popup(GTK_POPOVER(w->goto_pop));
    gtk_widget_grab_focus(w->goto_entry);
    gtk_editable_select_region(GTK_EDITABLE(w->goto_entry), 0, -1);
}

/* ---------- jazyk (zvyrazneni syntaxe) ---------- */
static void on_lang_row(GtkListBox *lb, GtkListBoxRow *row, Win *w)
{
    if (!w->cur) return;
    const char *id = g_object_get_data(G_OBJECT(row), "lang");
    GtkSourceLanguageManager *lm = gtk_source_language_manager_get_default();
    w->cur->lang_manual = TRUE;
    gtk_source_buffer_set_language(w->cur->buf, id && *id ? gtk_source_language_manager_get_language(lm, id) : NULL);
    gtk_popover_popdown(GTK_POPOVER(gtk_widget_get_ancestor(GTK_WIDGET(lb), GTK_TYPE_POPOVER)));
    gtk_widget_grab_focus(GTK_WIDGET(w->cur->view));
}

static gboolean lang_filter(GtkListBoxRow *row, gpointer p)
{
    Win *w = p;
    const char *q = gtk_entry_get_text(GTK_ENTRY(w->lang_search));
    if (!*q) return TRUE;
    const char *name = g_object_get_data(G_OBJECT(row), "name");
    char *a = g_utf8_casefold(name, -1), *b = g_utf8_casefold(q, -1);
    gboolean r = strstr(a, b) != NULL;
    g_free(a);
    g_free(b);
    return r;
}

static int lang_cmp(gconstpointer a, gconstpointer b)
{
    GtkSourceLanguageManager *lm = gtk_source_language_manager_get_default();
    GtkSourceLanguage *x = gtk_source_language_manager_get_language(lm, *(char **)a);
    GtkSourceLanguage *y = gtk_source_language_manager_get_language(lm, *(char **)b);
    return g_utf8_collate(gtk_source_language_get_name(x), gtk_source_language_get_name(y));
}

static GtkWidget *lang_row(const char *id, const char *name)
{
    GtkWidget *row = gtk_list_box_row_new();
    GtkWidget *l = gtk_label_new(name);
    gtk_label_set_xalign(GTK_LABEL(l), 0);
    g_object_set(l, "margin-start", 8, "margin-end", 8, "margin-top", 3, "margin-bottom", 3, NULL);
    gtk_container_add(GTK_CONTAINER(row), l);
    g_object_set_data_full(G_OBJECT(row), "lang", g_strdup(id), g_free);
    g_object_set_data_full(G_OBJECT(row), "name", g_strdup(name), g_free);
    return row;
}

static void on_lang_search(GtkSearchEntry *e, Win *w) { gtk_list_box_invalidate_filter(GTK_LIST_BOX(w->lang_list)); }

static void on_lang_search_activate(GtkEntry *e, Win *w)
{
    /* Enter = prvni viditelny jazyk */
    for (int i = 0;; i++) {
        GtkListBoxRow *r = gtk_list_box_get_row_at_index(GTK_LIST_BOX(w->lang_list), i);
        if (!r) break;
        if (gtk_widget_get_child_visible(GTK_WIDGET(r)) && lang_filter(r, w)) {
            on_lang_row(GTK_LIST_BOX(w->lang_list), r, w);
            break;
        }
    }
}

/* Seznam jazyku az pri prvnim otevreni (start okna nezdrzuje) */
static void on_lang_popover_show(GtkWidget *pop, Win *w)
{
    if (!w->lang_list) {
        GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 6);
        gtk_container_set_border_width(GTK_CONTAINER(box), 6);
        w->lang_search = gtk_search_entry_new();
        g_signal_connect(w->lang_search, "search-changed", G_CALLBACK(on_lang_search), w);
        g_signal_connect(w->lang_search, "activate", G_CALLBACK(on_lang_search_activate), w);
        gtk_box_pack_start(GTK_BOX(box), w->lang_search, FALSE, FALSE, 0);
        GtkWidget *sw = gtk_scrolled_window_new(NULL, NULL);
        gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(sw), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
        gtk_scrolled_window_set_min_content_height(GTK_SCROLLED_WINDOW(sw), 320);
        gtk_scrolled_window_set_min_content_width(GTK_SCROLLED_WINDOW(sw), 220);
        w->lang_list = gtk_list_box_new();
        gtk_list_box_set_activate_on_single_click(GTK_LIST_BOX(w->lang_list), TRUE);
        gtk_list_box_set_filter_func(GTK_LIST_BOX(w->lang_list), lang_filter, w, NULL);
        g_signal_connect(w->lang_list, "row-activated", G_CALLBACK(on_lang_row), w);
        gtk_container_add(GTK_CONTAINER(sw), w->lang_list);
        gtk_list_box_insert(GTK_LIST_BOX(w->lang_list), lang_row("", T("Plain Text")), -1);
        GtkSourceLanguageManager *lm = gtk_source_language_manager_get_default();
        const char *const *ids = gtk_source_language_manager_get_language_ids(lm);
        GPtrArray *a = g_ptr_array_new();
        for (int i = 0; ids && ids[i]; i++)
            if (!gtk_source_language_get_hidden(gtk_source_language_manager_get_language(lm, ids[i])))
                g_ptr_array_add(a, (char *)ids[i]);
        g_ptr_array_sort(a, lang_cmp);
        for (guint i = 0; i < a->len; i++) {
            GtkSourceLanguage *l = gtk_source_language_manager_get_language(lm, a->pdata[i]);
            gtk_list_box_insert(GTK_LIST_BOX(w->lang_list), lang_row(a->pdata[i], gtk_source_language_get_name(l)), -1);
        }
        g_ptr_array_free(a, TRUE);
        gtk_box_pack_start(GTK_BOX(box), sw, TRUE, TRUE, 0);
        gtk_container_add(GTK_CONTAINER(pop), box);
        gtk_widget_show_all(box);
    }
    gtk_entry_set_text(GTK_ENTRY(w->lang_search), "");
    /* aktualni jazyk vybrany */
    GtkSourceLanguage *cur = w->cur ? gtk_source_buffer_get_language(w->cur->buf) : NULL;
    const char *cid = cur ? gtk_source_language_get_id(cur) : "";
    for (int i = 0;; i++) {
        GtkListBoxRow *r = gtk_list_box_get_row_at_index(GTK_LIST_BOX(w->lang_list), i);
        if (!r) break;
        if (!g_strcmp0(g_object_get_data(G_OBJECT(r), "lang"), cid)) {
            gtk_list_box_select_row(GTK_LIST_BOX(w->lang_list), r);
            break;
        }
    }
    gtk_widget_grab_focus(w->lang_search);
}

/* ---------- informace o dokumentu ---------- */
static char *format_time(guint64 secs)
{
    GDateTime *dt = g_date_time_new_from_unix_local(secs);
    char *s = g_date_time_format(dt, "%x %H:%M");
    g_date_time_unref(dt);
    return s;
}

static void info_row(GtkGrid *g, int row, const char *key, const char *val)
{
    GtkWidget *k = gtk_label_new(key), *v = gtk_label_new(val);
    gtk_label_set_xalign(GTK_LABEL(k), 1);
    gtk_label_set_xalign(GTK_LABEL(v), 0);
    gtk_label_set_selectable(GTK_LABEL(v), TRUE);
    gtk_label_set_line_wrap(GTK_LABEL(v), TRUE);
    gtk_label_set_line_wrap_mode(GTK_LABEL(v), PANGO_WRAP_CHAR);
    gtk_label_set_max_width_chars(GTK_LABEL(v), 44);
    gtk_style_context_add_class(gtk_widget_get_style_context(k), "lt-key");
    gtk_grid_attach(g, k, 0, row, 1, 1);
    gtk_grid_attach(g, v, 1, row, 1, 1);
}

static void on_info_popover_show(GtkWidget *pop, Win *w)
{
    Doc *d = w->cur;
    if (w->info_grid) gtk_widget_destroy(w->info_grid);
    w->info_grid = gtk_grid_new();
    GtkGrid *g = GTK_GRID(w->info_grid);
    gtk_grid_set_row_spacing(g, 6);
    gtk_grid_set_column_spacing(g, 12);
    gtk_container_set_border_width(GTK_CONTAINER(g), 12);
    gtk_style_context_add_class(gtk_widget_get_style_context(w->info_grid), "lt-info");
    if (!d) return;
    int r = 0;
    char *name = doc_name(d);
    GtkWidget *title = gtk_label_new(name);
    gtk_style_context_add_class(gtk_widget_get_style_context(title), "lt-title");
    gtk_label_set_xalign(GTK_LABEL(title), 0);
    gtk_grid_attach(g, title, 0, r++, 2, 1);
    g_free(name);
    info_row(g, r++, T("Path:"), d->path ? d->path : T("Not saved"));
    GFile *f = d->path ? g_file_new_for_path(d->path) : NULL;
    GFileInfo *fi = f ? g_file_query_info(f, G_FILE_ATTRIBUTE_STANDARD_SIZE "," G_FILE_ATTRIBUTE_TIME_CREATED ","
                                          G_FILE_ATTRIBUTE_TIME_MODIFIED, G_FILE_QUERY_INFO_NONE, NULL, NULL) : NULL;
    if (fi) {
        goffset sz = g_file_info_get_size(fi);
        char *fs = g_format_size_full(sz, G_FORMAT_SIZE_LONG_FORMAT);
        info_row(g, r++, T("Size:"), fs);
        g_free(fs);
    } else {
        char *fs = g_format_size(d->stats.bytes);
        info_row(g, r++, T("Size:"), fs);
        g_free(fs);
    }
    char *el = encoding_label(d->enc);
    info_row(g, r++, T("Encoding:"), el);
    g_free(el);
    const char *les[] = {"LF (Unix, Linux)", "CRLF (Windows)", "CR"};
    info_row(g, r++, T("Line Endings:"), les[d->le]);
    GtkSourceLanguage *l = gtk_source_buffer_get_language(d->buf);
    info_row(g, r++, T("Syntax:"), l ? gtk_source_language_get_name(l) : T("Plain Text"));
    if (fi) {
        if (g_file_info_has_attribute(fi, G_FILE_ATTRIBUTE_TIME_CREATED)) {
            char *t = format_time(g_file_info_get_attribute_uint64(fi, G_FILE_ATTRIBUTE_TIME_CREATED));
            info_row(g, r++, T("Created:"), t);
            g_free(t);
        }
        char *t = format_time(g_file_info_get_attribute_uint64(fi, G_FILE_ATTRIBUTE_TIME_MODIFIED));
        info_row(g, r++, T("Modified:"), t);
        g_free(t);
        g_object_unref(fi);
    }
    if (f) g_object_unref(f);
    gtk_container_add(GTK_CONTAINER(pop), w->info_grid);
    gtk_widget_show_all(w->info_grid);
}

/* ---------- osnova ---------- */
static void on_outline_row(GtkListBox *lb, GtkListBoxRow *row, Win *w)
{
    int line = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(row), "line"));
    gtk_popover_popdown(GTK_POPOVER(gtk_widget_get_ancestor(GTK_WIDGET(lb), GTK_TYPE_POPOVER)));
    if (w->cur) jump_to_line(w->cur, line, 0);
}

static void on_outline_popover_show(GtkWidget *pop, Win *w)
{
    GtkWidget *old = gtk_bin_get_child(GTK_BIN(pop));
    if (old) gtk_widget_destroy(old);
    Doc *d = w->cur;
    if (!d || !d->outline) return;
    GtkWidget *sw = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(sw), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_max_content_height(GTK_SCROLLED_WINDOW(sw), 420);
    gtk_scrolled_window_set_propagate_natural_height(GTK_SCROLLED_WINDOW(sw), TRUE);
    gtk_scrolled_window_set_min_content_width(GTK_SCROLLED_WINDOW(sw), 240);
    GtkWidget *lb = gtk_list_box_new();
    gtk_list_box_set_activate_on_single_click(GTK_LIST_BOX(lb), TRUE);
    g_signal_connect(lb, "row-activated", G_CALLBACK(on_outline_row), w);
    int cur = current_symbol(d, cursor_line(d));
    GtkListBoxRow *sel = NULL;
    for (guint i = 0; i < d->outline->len; i++) {
        TxSymbol *s = d->outline->pdata[i];
        GtkWidget *row = gtk_list_box_row_new();
        GtkWidget *l = gtk_label_new(s->title);
        gtk_label_set_xalign(GTK_LABEL(l), 0);
        gtk_label_set_ellipsize(GTK_LABEL(l), PANGO_ELLIPSIZE_END);
        gtk_label_set_max_width_chars(GTK_LABEL(l), 50);
        g_object_set(l, "margin-start", 8 + 14 * MIN(s->level, 6), "margin-end", 8, "margin-top", 2, "margin-bottom", 2, NULL);
        gtk_container_add(GTK_CONTAINER(row), l);
        g_object_set_data(G_OBJECT(row), "line", GINT_TO_POINTER(s->line));
        gtk_list_box_insert(GTK_LIST_BOX(lb), row, -1);
        if ((int)i == cur) sel = GTK_LIST_BOX_ROW(row);
    }
    gtk_container_add(GTK_CONTAINER(sw), lb);
    gtk_container_add(GTK_CONTAINER(pop), sw);
    gtk_widget_show_all(sw);
    if (sel) gtk_list_box_select_row(GTK_LIST_BOX(lb), sel);
}

static void outline_step(Win *w, int dir)
{
    Doc *d = w->cur;
    if (!d || !d->outline || !d->outline->len) return;
    int line = cursor_line(d);
    int i = current_symbol(d, line);
    int target;
    if (dir > 0) target = i + 1;
    else target = (i >= 0 && ((TxSymbol *)d->outline->pdata[i])->line < line) ? i : i - 1;
    if (target < 0 || target >= (int)d->outline->len) return;
    jump_to_line(d, ((TxSymbol *)d->outline->pdata[target])->line, 0);
}

static void nav_prev(Win *w) { outline_step(w, -1); }
static void nav_next(Win *w) { outline_step(w, 1); }

/* ---------- kodovani a konce radku ---------- */
enum { ENC_CANCEL, ENC_REINTERPRET, ENC_CONVERT };

static void change_encoding(Win *w, const char *id)
{
    Doc *d = w->cur;
    const TxEncoding *e = tx_encoding_find(id);
    if (!d || !e || e == d->enc) return;
    char *el = encoding_label(e);
    int choice = ENC_CONVERT;
    if (d->path && d->disk_exists && !gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf))) {
        char *msg = g_strdup_printf(T("Change the encoding to %s?"), el);
        GtkWidget *m = gtk_message_dialog_new(w->win, GTK_DIALOG_MODAL, GTK_MESSAGE_QUESTION, GTK_BUTTONS_NONE, "%s", msg);
        gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(m), "%s",
            T("Reinterpret reads the file again in the new encoding (when it was opened in a wrong one). "
              "Convert keeps the text and saves it in the new encoding."));
        gtk_dialog_add_buttons(GTK_DIALOG(m), T("Cancel"), ENC_CANCEL, T("Reinterpret"), ENC_REINTERPRET,
                               T("Convert"), ENC_CONVERT, NULL);
        gtk_dialog_set_default_response(GTK_DIALOG(m), ENC_REINTERPRET);
        choice = gtk_dialog_run(GTK_DIALOG(m));
        gtk_widget_destroy(m);
        g_free(msg);
        if (choice < 0) choice = ENC_CANCEL;
    }
    if (choice == ENC_REINTERPRET) {
        GError *err = NULL;
        if (!load_doc(d, d->path, e, &err)) {
            message(w->win, err->message, NULL);
            g_error_free(err);
        }
    } else if (choice == ENC_CONVERT) {
        char *text = buffer_text(d);
        char *b = tx_encode(text, strlen(text), e, d->le, NULL, NULL);
        g_free(text);
        if (!b) {
            char *msg = g_strdup_printf(T("Some characters cannot be saved in %s."), el);
            message(w->win, msg, NULL);
            g_free(msg);
        } else {
            d->enc = e;
            gtk_text_buffer_set_modified(GTK_TEXT_BUFFER(d->buf), TRUE);
            schedule_scan(d, TRUE);
        }
        g_free(b);
    }
    g_free(el);
    update_status(w);
}

static void act_encoding(GSimpleAction *a, GVariant *v, gpointer p)
{
    change_encoding(p, g_variant_get_string(v, NULL));
}

static void act_line_ending(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    int le = tx_line_ending_from_name(g_variant_get_string(v, NULL));
    if (!w->cur || le < 0 || (TxLineEnd)le == w->cur->le) return;
    w->cur->le = le;
    gtk_text_buffer_set_modified(GTK_TEXT_BUFFER(w->cur->buf), TRUE);
    schedule_scan(w->cur, TRUE);
    update_status(w);
}

/* ---------- akce okna ---------- */
static void act_new_tab(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    new_doc(w);
    gtk_widget_grab_focus(GTK_WIDGET(w->cur->view));
}

static void act_open(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    GtkFileChooserNative *fc = gtk_file_chooser_native_new(T("Open"), w->win, GTK_FILE_CHOOSER_ACTION_OPEN, T("Open"),
                                                          T("Cancel"));
    gtk_file_chooser_set_select_multiple(GTK_FILE_CHOOSER(fc), TRUE);
    char *dir = w->cur && w->cur->path ? g_path_get_dirname(w->cur->path) : g_strdup(w->root ? w->root : home_dir());
    gtk_file_chooser_set_current_folder(GTK_FILE_CHOOSER(fc), dir);
    g_free(dir);
    if (gtk_native_dialog_run(GTK_NATIVE_DIALOG(fc)) == GTK_RESPONSE_ACCEPT) {
        GSList *files = gtk_file_chooser_get_filenames(GTK_FILE_CHOOSER(fc));
        GPtrArray *a2 = g_ptr_array_new();
        for (GSList *l = files; l; l = l->next) g_ptr_array_add(a2, l->data);
        g_ptr_array_add(a2, NULL);
        open_paths(w, (char **)a2->pdata, -1);
        g_ptr_array_free(a2, TRUE);
        g_slist_free_full(files, g_free);
    }
    g_object_unref(fc);
}

static void act_open_folder(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    GtkFileChooserNative *fc = gtk_file_chooser_native_new(T("Open Folder"), w->win, GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER,
                                                          T("Open"), T("Cancel"));
    if (w->root) gtk_file_chooser_set_current_folder(GTK_FILE_CHOOSER(fc), w->root);
    if (gtk_native_dialog_run(GTK_NATIVE_DIALOG(fc)) == GTK_RESPONSE_ACCEPT) {
        char *dir = gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(fc));
        if (dir) {
            sidebar_set_root(w, dir);
            sidebar_show(w, TRUE);
        }
        g_free(dir);
    }
    g_object_unref(fc);
}

static void act_save(GSimpleAction *a, GVariant *v, gpointer p) { Win *w = p; if (w->cur) save_doc(w->cur, FALSE); }
static void act_save_as(GSimpleAction *a, GVariant *v, gpointer p) { Win *w = p; if (w->cur) save_doc(w->cur, TRUE); }
static void act_close_tab(GSimpleAction *a, GVariant *v, gpointer p) { Win *w = p; if (w->cur) close_doc(w->cur); }
static void act_find(GSimpleAction *a, GVariant *v, gpointer p) { show_find(p, FALSE); }
static void act_replace(GSimpleAction *a, GVariant *v, gpointer p) { show_find(p, TRUE); }
static void act_find_next(GSimpleAction *a, GVariant *v, gpointer p) { find_next(p); }
static void act_replace_all(GSimpleAction *a, GVariant *v, gpointer p) { replace_all(p); }
static void act_find_prev(GSimpleAction *a, GVariant *v, gpointer p) { find_prev(p); }
static void act_goto(GSimpleAction *a, GVariant *v, gpointer p) { show_goto(p); }
static void act_new_file(GSimpleAction *a, GVariant *v, gpointer p) { Win *w = p; sidebar_show(w, TRUE); sidebar_new(w, FALSE); }
static void act_new_folder(GSimpleAction *a, GVariant *v, gpointer p) { Win *w = p; sidebar_show(w, TRUE); sidebar_new(w, TRUE); }

static void act_doc_info(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w->info_btn), TRUE);
}

static void act_undo(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    if (w->cur && gtk_source_buffer_can_undo(w->cur->buf)) gtk_source_buffer_undo(w->cur->buf);
}

static void act_redo(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    if (w->cur && gtk_source_buffer_can_redo(w->cur->buf)) gtk_source_buffer_redo(w->cur->buf);
}

static void act_sidebar(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = p;
    gboolean show = !gtk_widget_get_visible(w->sidebar);
    if (v) show = g_variant_get_boolean(v);
    sidebar_show(w, show);
}

static const GActionEntry win_actions[] = {
    {"new-tab", act_new_tab}, {"open", act_open}, {"open-folder", act_open_folder}, {"save", act_save},
    {"save-as", act_save_as}, {"close-tab", act_close_tab}, {"find", act_find}, {"replace", act_replace},
    {"find-next", act_find_next}, {"find-prev", act_find_prev}, {"goto-line", act_goto}, {"doc-info", act_doc_info},
    {"undo", act_undo}, {"redo", act_redo}, {"new-file", act_new_file}, {"new-folder", act_new_folder},
    {"sidebar", NULL, NULL, "false", act_sidebar}, {"replace-all", act_replace_all},
    {"find-case", act_find_option, NULL, "false"}, {"find-words", act_find_option, NULL, "false"},
    {"find-regex", act_find_option, NULL, "false"},
    {"encoding", NULL, "s", "'UTF-8'", act_encoding},
    {"line-ending", NULL, "s", "'LF'", act_line_ending},
};

/* ---------- okno ---------- */
static void remember_size(Win *w)
{
    if (!gtk_widget_get_realized(GTK_WIDGET(w->win))) return;
    GdkWindowState st = gdk_window_get_state(gtk_widget_get_window(GTK_WIDGET(w->win)));
    if (!(st & (GDK_WINDOW_STATE_MAXIMIZED | GDK_WINDOW_STATE_FULLSCREEN | GDK_WINDOW_STATE_TILED)))
        gtk_window_get_size(w->win, &cfg.width, &cfg.height);
    if (gtk_widget_get_visible(w->sidebar)) cfg.sidebar_width = gtk_paned_get_position(GTK_PANED(w->paned));
    save_config();
}

static gboolean on_delete(GtkWidget *wdg, GdkEvent *e, Win *w)
{
    GList *docs = all_docs(w);
    gboolean stop = FALSE;
    for (GList *l = docs; l && !stop; l = l->next) stop = !confirm_close(l->data);
    g_list_free(docs);
    if (!stop) {
        remember_size(w);
        w->closing = TRUE;
    }
    return stop;
}

static void on_destroy(GtkWidget *wdg, Win *w)
{
    w->closing = TRUE;
    GList *docs = all_docs(w);
    for (GList *l = docs; l; l = l->next) {
        Doc *d = l->data;
        g_signal_handlers_disconnect_by_data(d->buf, d);
        free_doc(d);
        g_object_set_data(G_OBJECT(d->page), "doc", NULL);
    }
    g_list_free(docs);
    drop_dir_monitors(w);
    g_hash_table_unref(w->dir_mons);
    g_clear_object(&w->ss);
    windows = g_list_remove(windows, w);
    g_free(w->root);
    g_free(w);
}

static void on_switch_page(GtkNotebook *nb, GtkWidget *page, guint n, Win *w)
{
    if (w->closing) return;
    Doc *d = g_object_get_data(G_OBJECT(page), "doc");
    if (!d) return;
    w->cur = d;
    update_window(w);
    if (d->search || gtk_revealer_get_reveal_child(GTK_REVEALER(w->find_rev))) {
        doc_search(d);
        search_update_count(w);
    }
    sidebar_select_current(w);
}

static void on_pages_changed(GtkNotebook *nb, GtkWidget *page, guint n, Win *w)
{
    if (w->closing) return;
    gtk_notebook_set_show_tabs(nb, gtk_notebook_get_n_pages(nb) > 1);
}

static void on_page_focus(GtkNotebook *nb, GtkWidget *page, guint n, Win *w)
{
    Doc *d = g_object_get_data(G_OBJECT(page), "doc");
    if (d && !w->closing) gtk_widget_grab_focus(GTK_WIDGET(d->view));
}

static void on_active(GObject *o, GParamSpec *ps, Win *w)
{
    if (!gtk_window_is_active(w->win) || w->closing) return;
    GList *docs = all_docs(w);
    for (GList *l = docs; l; l = l->next) {
        Doc *d = l->data;
        if (d->path && !d->check_id) d->check_id = g_timeout_add(50, check_disk, d);
    }
    g_list_free(docs);
}

static gboolean on_key(GtkWidget *wdg, GdkEventKey *e, Win *w)
{
    if (e->keyval == GDK_KEY_Escape && gtk_revealer_get_reveal_child(GTK_REVEALER(w->find_rev))) {
        hide_find(w);
        return TRUE;
    }
    return FALSE;
}

static void on_paned_position(GObject *o, GParamSpec *ps, Win *w)
{
    if (gtk_widget_get_visible(w->sidebar) && gtk_widget_get_mapped(w->sidebar)) {
        int pos = gtk_paned_get_position(GTK_PANED(w->paned));
        if (pos >= 120 && pos != cfg.sidebar_width) {
            cfg.sidebar_width = pos;
            save_config();
        }
    }
}

static GMenuModel *app_menu, *enc_menu, *le_menu;

static GtkWidget *flat_icon_button(const char *icon, const char *tip)
{
    GtkWidget *b = gtk_button_new_from_icon_name(icon, GTK_ICON_SIZE_MENU);
    gtk_widget_set_tooltip_text(b, tip);
    gtk_button_set_relief(GTK_BUTTON(b), GTK_RELIEF_NONE);
    gtk_widget_set_valign(b, GTK_ALIGN_CENTER);
    return b;
}

static Win *new_window(void)
{
    Win *w = g_new0(Win, 1);
    w->dir_mons = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_object_unref);
    w->win = GTK_WINDOW(gtk_application_window_new(app));
    gtk_application_window_set_show_menubar(GTK_APPLICATION_WINDOW(w->win), FALSE);
    gtk_window_set_default_size(w->win, cfg.width, cfg.height);
    gtk_style_context_add_class(gtk_widget_get_style_context(GTK_WIDGET(w->win)), "lt-window");
    g_action_map_add_action_entries(G_ACTION_MAP(w->win), win_actions, G_N_ELEMENTS(win_actions), w);
    if (icon_list) set_window_icons(w->win);

    /* horni lista: [tlacitka okna][postranni panel]  nazev  [jazyk][i][nabidka] */
    w->header = GTK_HEADER_BAR(gtk_header_bar_new());
    gtk_header_bar_set_show_close_button(w->header, TRUE);
    w->sidebar_btn = gtk_toggle_button_new();
    gtk_button_set_image(GTK_BUTTON(w->sidebar_btn), gtk_image_new_from_icon_name("sidebar-show-symbolic", GTK_ICON_SIZE_BUTTON));
    gtk_widget_set_tooltip_text(w->sidebar_btn, T("Show Sidebar (F9)"));
    gtk_actionable_set_action_name(GTK_ACTIONABLE(w->sidebar_btn), "win.sidebar");
    gtk_widget_set_valign(w->sidebar_btn, GTK_ALIGN_CENTER);
    gtk_header_bar_pack_start(w->header, w->sidebar_btn);

    GtkWidget *tbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_widget_set_valign(tbox, GTK_ALIGN_CENTER);
    w->title = gtk_label_new(NULL);
    w->subtitle = gtk_label_new(NULL);
    gtk_label_set_ellipsize(GTK_LABEL(w->title), PANGO_ELLIPSIZE_MIDDLE);
    gtk_label_set_ellipsize(GTK_LABEL(w->subtitle), PANGO_ELLIPSIZE_START);
    gtk_label_set_max_width_chars(GTK_LABEL(w->title), 50);
    gtk_label_set_max_width_chars(GTK_LABEL(w->subtitle), 60);
    gtk_style_context_add_class(gtk_widget_get_style_context(w->title), "lt-title");
    gtk_style_context_add_class(gtk_widget_get_style_context(w->subtitle), "lt-subtitle");
    gtk_box_pack_start(GTK_BOX(tbox), w->title, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(tbox), w->subtitle, FALSE, FALSE, 0);
    gtk_header_bar_set_custom_title(w->header, tbox);

    GtkWidget *menu = gtk_menu_button_new();
    gtk_button_set_image(GTK_BUTTON(menu), gtk_image_new_from_icon_name("open-menu-symbolic", GTK_ICON_SIZE_BUTTON));
    gtk_widget_set_tooltip_text(menu, T("Menu"));
    gtk_menu_button_set_menu_model(GTK_MENU_BUTTON(menu), app_menu);
    gtk_widget_set_valign(menu, GTK_ALIGN_CENTER);
    gtk_header_bar_pack_end(w->header, menu);

    w->info_btn = gtk_menu_button_new();
    gtk_button_set_image(GTK_BUTTON(w->info_btn), gtk_image_new_from_icon_name("dialog-information-symbolic", GTK_ICON_SIZE_BUTTON));
    gtk_widget_set_tooltip_text(w->info_btn, T("Document Info"));
    gtk_widget_set_valign(w->info_btn, GTK_ALIGN_CENTER);
    GtkWidget *ipop = gtk_popover_new(w->info_btn);
    g_signal_connect(ipop, "show", G_CALLBACK(on_info_popover_show), w);
    gtk_menu_button_set_popover(GTK_MENU_BUTTON(w->info_btn), ipop);
    gtk_header_bar_pack_end(w->header, w->info_btn);

    w->lang_btn = gtk_menu_button_new();
    GtkWidget *lb = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    w->lang_label = gtk_label_new(T("Plain Text"));
    gtk_box_pack_start(GTK_BOX(lb), w->lang_label, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(lb), gtk_image_new_from_icon_name("pan-down-symbolic", GTK_ICON_SIZE_MENU), FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(w->lang_btn), lb);
    gtk_style_context_add_class(gtk_widget_get_style_context(w->lang_btn), "lt-pill");
    gtk_widget_set_tooltip_text(w->lang_btn, T("Syntax"));
    gtk_widget_set_valign(w->lang_btn, GTK_ALIGN_CENTER);
    GtkWidget *lpop = gtk_popover_new(w->lang_btn);
    g_signal_connect(lpop, "show", G_CALLBACK(on_lang_popover_show), w);
    gtk_menu_button_set_popover(GTK_MENU_BUTTON(w->lang_btn), lpop);
    gtk_header_bar_pack_end(w->header, w->lang_btn);
    gtk_widget_show_all(GTK_WIDGET(w->header));
    gtk_window_set_titlebar(w->win, GTK_WIDGET(w->header));

    /* telo: postranni panel | (navigace, hledani, editor, stavovy radek) */
    w->paned = gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);
    w->sidebar = build_sidebar(w);
    gtk_paned_pack1(GTK_PANED(w->paned), w->sidebar, FALSE, FALSE);
    GtkWidget *main = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    gtk_paned_pack2(GTK_PANED(w->paned), main, TRUE, FALSE);
    gtk_paned_set_position(GTK_PANED(w->paned), cfg.sidebar_width);
    g_signal_connect(w->paned, "notify::position", G_CALLBACK(on_paned_position), w);

    GtkWidget *nav = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 2);
    gtk_style_context_add_class(gtk_widget_get_style_context(nav), "lt-nav");
    w->nav_prev = flat_icon_button("go-previous-symbolic", T("Previous Symbol"));
    w->nav_next = flat_icon_button("go-next-symbolic", T("Next Symbol"));
    g_signal_connect_swapped(w->nav_prev, "clicked", G_CALLBACK(nav_prev), w);
    g_signal_connect_swapped(w->nav_next, "clicked", G_CALLBACK(nav_next), w);
    gtk_box_pack_start(GTK_BOX(nav), w->nav_prev, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), w->nav_next, FALSE, FALSE, 0);
    w->outline_btn = gtk_menu_button_new();
    gtk_button_set_relief(GTK_BUTTON(w->outline_btn), GTK_RELIEF_NONE);
    gtk_widget_set_tooltip_text(w->outline_btn, T("Outline"));
    GtkWidget *ob = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    gtk_box_pack_start(GTK_BOX(ob), gtk_image_new_from_icon_name("view-list-symbolic", GTK_ICON_SIZE_MENU), FALSE, FALSE, 0);
    w->outline_label = gtk_label_new(NULL);
    gtk_label_set_ellipsize(GTK_LABEL(w->outline_label), PANGO_ELLIPSIZE_END);
    gtk_label_set_max_width_chars(GTK_LABEL(w->outline_label), 60);
    gtk_box_pack_start(GTK_BOX(ob), w->outline_label, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(ob), gtk_image_new_from_icon_name("pan-down-symbolic", GTK_ICON_SIZE_MENU), FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(w->outline_btn), ob);
    GtkWidget *opop = gtk_popover_new(w->outline_btn);
    g_signal_connect(opop, "show", G_CALLBACK(on_outline_popover_show), w);
    gtk_menu_button_set_popover(GTK_MENU_BUTTON(w->outline_btn), opop);
    gtk_box_pack_start(GTK_BOX(nav), w->outline_btn, FALSE, FALSE, 4);
    gtk_box_pack_start(GTK_BOX(main), nav, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(main), build_find(w), FALSE, FALSE, 0);

    w->notebook = gtk_notebook_new();
    gtk_notebook_set_show_border(GTK_NOTEBOOK(w->notebook), FALSE);
    gtk_notebook_set_show_tabs(GTK_NOTEBOOK(w->notebook), FALSE);
    gtk_notebook_set_scrollable(GTK_NOTEBOOK(w->notebook), TRUE);
    gtk_style_context_add_class(gtk_widget_get_style_context(w->notebook), "lt-tabs");
    g_signal_connect(w->notebook, "switch-page", G_CALLBACK(on_switch_page), w);
    g_signal_connect_after(w->notebook, "switch-page", G_CALLBACK(on_page_focus), w);
    g_signal_connect(w->notebook, "page-added", G_CALLBACK(on_pages_changed), w);
    g_signal_connect(w->notebook, "page-removed", G_CALLBACK(on_pages_changed), w);
    gtk_box_pack_start(GTK_BOX(main), w->notebook, TRUE, TRUE, 0);

    GtkWidget *st = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 14);
    gtk_style_context_add_class(gtk_widget_get_style_context(st), "lt-status");
    w->st_lines = gtk_label_new(NULL);
    w->st_chars = gtk_label_new(NULL);
    w->st_words = gtk_label_new(NULL);
    gtk_box_pack_start(GTK_BOX(st), w->st_lines, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(st), w->st_chars, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(st), w->st_words, FALSE, FALSE, 0);
    w->le_btn = gtk_menu_button_new();
    gtk_button_set_label(GTK_BUTTON(w->le_btn), "LF");
    gtk_widget_set_tooltip_text(w->le_btn, T("Line Endings"));
    gtk_menu_button_set_menu_model(GTK_MENU_BUTTON(w->le_btn), le_menu);
    gtk_menu_button_set_direction(GTK_MENU_BUTTON(w->le_btn), GTK_ARROW_UP);
    gtk_box_pack_end(GTK_BOX(st), w->le_btn, FALSE, FALSE, 0);
    GtkWidget *sep = gtk_separator_new(GTK_ORIENTATION_VERTICAL);
    gtk_box_pack_end(GTK_BOX(st), sep, FALSE, FALSE, 0);
    w->enc_btn = gtk_menu_button_new();
    gtk_widget_set_tooltip_text(w->enc_btn, T("Encoding"));
    gtk_menu_button_set_menu_model(GTK_MENU_BUTTON(w->enc_btn), enc_menu);
    gtk_menu_button_set_direction(GTK_MENU_BUTTON(w->enc_btn), GTK_ARROW_UP);
    gtk_box_pack_end(GTK_BOX(st), w->enc_btn, FALSE, FALSE, 0);
    sep = gtk_separator_new(GTK_ORIENTATION_VERTICAL);
    gtk_box_pack_end(GTK_BOX(st), sep, FALSE, FALSE, 0);
    w->st_size = gtk_label_new(NULL);
    gtk_box_pack_end(GTK_BOX(st), w->st_size, FALSE, FALSE, 0);
    w->pos_btn = gtk_button_new_with_label("1:1");
    gtk_widget_set_tooltip_text(w->pos_btn, T("Go to Line (Ctrl+L)"));
    g_signal_connect_swapped(w->pos_btn, "clicked", G_CALLBACK(show_goto), w);
    gtk_box_pack_end(GTK_BOX(st), w->pos_btn, FALSE, FALSE, 0);
    gtk_box_pack_end(GTK_BOX(main), st, FALSE, FALSE, 0);

    w->goto_pop = gtk_popover_new(w->pos_btn);
    GtkWidget *gb = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_container_set_border_width(GTK_CONTAINER(gb), 8);
    gtk_box_pack_start(GTK_BOX(gb), gtk_label_new(T("Go to Line:")), FALSE, FALSE, 0);
    w->goto_entry = gtk_entry_new();
    gtk_entry_set_width_chars(GTK_ENTRY(w->goto_entry), 10);
    gtk_entry_set_input_hints(GTK_ENTRY(w->goto_entry), GTK_INPUT_HINT_NO_EMOJI);
    g_signal_connect(w->goto_entry, "activate", G_CALLBACK(on_goto_activate), w);
    gtk_box_pack_start(GTK_BOX(gb), w->goto_entry, FALSE, FALSE, 0);
    gtk_widget_show_all(gb);
    gtk_container_add(GTK_CONTAINER(w->goto_pop), gb);

    gtk_widget_show_all(main);
    gtk_revealer_set_reveal_child(GTK_REVEALER(w->find_rev), FALSE);
    gtk_container_add(GTK_CONTAINER(w->win), w->paned);
    gtk_widget_show(w->paned);

    g_signal_connect(w->win, "delete-event", G_CALLBACK(on_delete), w);
    g_signal_connect(w->win, "destroy", G_CALLBACK(on_destroy), w);
    g_signal_connect(w->win, "notify::is-active", G_CALLBACK(on_active), w);
    g_signal_connect(w->win, "key-press-event", G_CALLBACK(on_key), w);
    windows = g_list_append(windows, w);
    if (system_dark()) gtk_style_context_add_class(gtk_widget_get_style_context(GTK_WIDGET(w->win)), "lt-dark");
    new_doc(w);
    return w;
}

/* ---------- akce aplikace ---------- */
static Win *active_win(void)
{
    GtkWindow *a = gtk_application_get_active_window(app);
    for (GList *l = windows; l; l = l->next)
        if (((Win *)l->data)->win == a) return l->data;
    return windows ? windows->data : NULL;
}

static void act_new_window(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *old = active_win();
    Win *w = new_window();
    if (old && old->root) sidebar_set_root(w, old->root);
    update_window(w);
    gtk_window_present(w->win);
}

static void act_open_recent(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    if (!w) {
        w = new_window();
        gtk_window_present(w->win);
    }
    char *paths[] = {(char *)g_variant_get_string(v, NULL), NULL};
    open_paths(w, paths, -1);
}

static void act_clear_recent(GSimpleAction *a, GVariant *v, gpointer p)
{
    g_strfreev(cfg.recent);
    cfg.recent = NULL;
    rebuild_recent_menu();
    save_config();
}

static void act_quit(GSimpleAction *a, GVariant *v, gpointer p)
{
    GList *ws = g_list_copy(windows);
    for (GList *l = ws; l; l = l->next) {
        Win *w = l->data;
        if (on_delete(GTK_WIDGET(w->win), NULL, w)) break;   /* Zrusit = nekoncit */
        gtk_widget_destroy(GTK_WIDGET(w->win));
    }
    g_list_free(ws);
}

static void act_toggle_setting(GSimpleAction *a, GVariant *v, gpointer p)
{
    gboolean on = g_variant_get_boolean(v);
    const char *name = g_action_get_name(G_ACTION(a));
    if (!strcmp(name, "wrap")) cfg.wrap = on;
    else if (!strcmp(name, "invisibles")) cfg.invisibles = on;
    else cfg.line_numbers = on;
    g_simple_action_set_state(a, v);
    apply_all_view_settings();
}

static void act_zoom(GSimpleAction *a, GVariant *v, gpointer p)
{
    const char *name = g_action_get_name(G_ACTION(a));
    if (!strcmp(name, "zoom-in")) cfg.font_size = MIN(cfg.font_size + 1, 72);
    else if (!strcmp(name, "zoom-out")) cfg.font_size = MAX(cfg.font_size - 1, 6);
    else cfg.font_size = 11;
    apply_font();
    save_config();
}

/* ---------- testy (jen LUXOS_TEXT_TEST=1): stav okna jako JSON, snimek okna, psani textu ---------- */
static void json_str(GString *s, const char *v)
{
    if (!v) { g_string_append(s, "null"); return; }
    g_string_append_c(s, '"');
    for (const char *p = v; *p; p++) {
        guchar c = *p;
        if (c == '"' || c == '\\') { g_string_append_c(s, '\\'); g_string_append_c(s, c); }
        else if (c == '\n') g_string_append(s, "\\n");
        else if (c == '\t') g_string_append(s, "\\t");
        else if (c < 0x20) g_string_append_printf(s, "\\u%04x", c);
        else g_string_append_c(s, c);
    }
    g_string_append_c(s, '"');
}

static void json_kv(GString *s, const char *k, const char *v)
{
    json_str(s, k);
    g_string_append_c(s, ':');
    json_str(s, v);
    g_string_append_c(s, ',');
}

static void json_kb(GString *s, const char *k, gboolean v)
{
    json_str(s, k);
    g_string_append_printf(s, ":%s,", v ? "true" : "false");
}


static void dump_visible_rows(GString *s, Win *w)
{
    g_string_append(s, "\"sidebar_rows\":[");
    gboolean first = TRUE;
    GtkTreeModel *m = GTK_TREE_MODEL(w->store);
    GtkTreeIter it;
    /* do hloubky, jen rozbalene vetve */
    GPtrArray *stack = g_ptr_array_new_with_free_func((GDestroyNotify)gtk_tree_path_free);
    if (gtk_tree_model_get_iter_first(m, &it)) g_ptr_array_add(stack, gtk_tree_model_get_path(m, &it));
    while (stack->len) {
        GtkTreePath *tp = g_ptr_array_steal_index(stack, stack->len - 1);
        if (gtk_tree_model_get_iter(m, &it, tp)) {
            char *name = NULL;
            gtk_tree_model_get(m, &it, COL_NAME, &name, -1);
            if (name) {
                if (!first) g_string_append_c(s, ',');
                first = FALSE;
                char *ind = g_strnfill(gtk_tree_path_get_depth(tp) - 1, ' ');
                char *v = g_strconcat(ind, name, NULL);
                json_str(s, v);
                g_free(v);
                g_free(ind);
            }
            g_free(name);
            /* sourozenec pozdeji, deti hned */
            GtkTreeIter sib = it;
            if (gtk_tree_model_iter_next(m, &sib)) g_ptr_array_add(stack, gtk_tree_model_get_path(m, &sib));
            GtkTreeIter ch;
            if (gtk_tree_view_row_expanded(GTK_TREE_VIEW(w->tree), tp) && gtk_tree_model_iter_children(m, &ch, &it))
                g_ptr_array_add(stack, gtk_tree_model_get_path(m, &ch));
        }
        gtk_tree_path_free(tp);
    }
    g_ptr_array_unref(stack);
    g_string_append(s, "],");
}

static void act_test_dump(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    GString *s = g_string_new("{");
    g_string_append_printf(s, "\"windows\":%u,", g_list_length(windows));
    if (w && w->cur) {
        Doc *d = w->cur;
        g_string_append_printf(s, "\"tabs\":%d,\"xid\":%lu,", gtk_notebook_get_n_pages(GTK_NOTEBOOK(w->notebook)),
                               gtk_widget_get_realized(GTK_WIDGET(w->win)) ?
                               (unsigned long)gdk_x11_window_get_xid(gtk_widget_get_window(GTK_WIDGET(w->win))) : 0UL);
        json_kv(s, "title", gtk_label_get_text(GTK_LABEL(w->title)));
        json_kv(s, "subtitle", gtk_label_get_text(GTK_LABEL(w->subtitle)));
        json_kv(s, "wm_title", gtk_window_get_title(w->win));
        json_kv(s, "path", d->path);
        json_kv(s, "language", gtk_label_get_text(GTK_LABEL(w->lang_label)));
        GtkSourceLanguage *l = gtk_source_buffer_get_language(d->buf);
        json_kv(s, "language_id", l ? gtk_source_language_get_id(l) : NULL);
        json_kv(s, "lines", gtk_label_get_text(GTK_LABEL(w->st_lines)));
        json_kv(s, "chars", gtk_label_get_text(GTK_LABEL(w->st_chars)));
        json_kv(s, "words", gtk_label_get_text(GTK_LABEL(w->st_words)));
        json_kv(s, "size", gtk_label_get_text(GTK_LABEL(w->st_size)));
        json_kv(s, "encoding_label", gtk_button_get_label(GTK_BUTTON(w->enc_btn)));
        json_kv(s, "encoding", d->enc->id);
        json_kv(s, "line_ending", tx_line_ending_name(d->le));
        json_kv(s, "position", gtk_button_get_label(GTK_BUTTON(w->pos_btn)));
        json_kv(s, "outline_label", gtk_label_get_text(GTK_LABEL(w->outline_label)));
        g_string_append(s, "\"outline\":[");
        for (guint i = 0; d->outline && i < d->outline->len; i++) {
            if (i) g_string_append_c(s, ',');
            json_str(s, ((TxSymbol *)d->outline->pdata[i])->title);
        }
        g_string_append(s, "],");
        json_kb(s, "modified", gtk_text_buffer_get_modified(GTK_TEXT_BUFFER(d->buf)));
        json_kb(s, "infobar", d->infobar && gtk_widget_get_visible(d->infobar));
        json_kb(s, "find_visible", gtk_revealer_get_reveal_child(GTK_REVEALER(w->find_rev)));
        json_kv(s, "find_count", gtk_label_get_text(GTK_LABEL(w->find_count)));
        json_kb(s, "sidebar", gtk_widget_get_visible(w->sidebar));
        json_kv(s, "root", w->root);
        dump_visible_rows(s, w);
        GtkTreeIter it;
        GtkTreeModel *m;
        char *selp = NULL;
        if (gtk_tree_selection_get_selected(gtk_tree_view_get_selection(GTK_TREE_VIEW(w->tree)), &m, &it))
            gtk_tree_model_get(m, &it, COL_PATH, &selp, -1);
        json_kv(s, "sidebar_selected", selp);
        g_free(selp);
        json_kb(s, "dark", gtk_style_context_has_class(gtk_widget_get_style_context(GTK_WIDGET(w->win)), "lt-dark"));
        GtkSourceStyleScheme *sch = gtk_source_buffer_get_style_scheme(d->buf);
        json_kv(s, "scheme", sch ? gtk_source_style_scheme_get_id(sch) : NULL);
        json_kb(s, "insert_spaces", gtk_source_view_get_insert_spaces_instead_of_tabs(d->view));
        char *text = buffer_text(d);
        json_kv(s, "text", text);
        g_free(text);
    }
    g_string_append_printf(s, "\"font_size\":%d,\"wrap\":%s,\"invisibles\":%s}", cfg.font_size,
                           cfg.wrap ? "true" : "false", cfg.invisibles ? "true" : "false");
    g_file_set_contents(g_variant_get_string(v, NULL), s->str, s->len, NULL);
    g_string_free(s, TRUE);
}

static void act_test_shot(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    if (!w) return;
    GdkWindow *gw = gtk_widget_get_window(GTK_WIDGET(w->win));
    GdkPixbuf *pb = gdk_pixbuf_get_from_window(gw, 0, 0, gdk_window_get_width(gw), gdk_window_get_height(gw));
    if (pb) {
        gdk_pixbuf_save(pb, g_variant_get_string(v, NULL), "png", NULL, NULL);
        g_object_unref(pb);
    }
}

static void act_test_type(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    if (w && w->cur)
        gtk_text_buffer_insert_interactive_at_cursor(GTK_TEXT_BUFFER(w->cur->buf), g_variant_get_string(v, NULL), -1, TRUE);
}

static void act_test_goto(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    if (w && w->cur) jump_to_line(w->cur, g_variant_get_int32(v), 0);
}

static const GActionEntry app_actions[] = {
    {"new-window", act_new_window}, {"open-recent", act_open_recent, "s"}, {"clear-recent", act_clear_recent},
    {"quit", act_quit}, {"zoom-in", act_zoom}, {"zoom-out", act_zoom}, {"zoom-reset", act_zoom},
};

/* "jmeno" nebo "jmeno:parametr" = akce aktivniho okna (win.encoding:WINDOWS-1250) */
static void act_test_action(GSimpleAction *a, GVariant *v, gpointer p)
{
    Win *w = active_win();
    if (!w) return;
    char **kv = g_strsplit(g_variant_get_string(v, NULL), ":", 2);
    g_action_group_activate_action(G_ACTION_GROUP(w->win), kv[0], kv[1] ? g_variant_new_string(kv[1]) : NULL);
    g_strfreev(kv);
}

static const GActionEntry test_actions[] = {
    {"test-dump", act_test_dump, "s"}, {"test-shot", act_test_shot, "s"}, {"test-type", act_test_type, "s"},
    {"test-goto", act_test_goto, "i"}, {"test-action", act_test_action, "s"},
};

static void add_toggle(const char *name, gboolean state)
{
    GSimpleAction *a = g_simple_action_new_stateful(name, NULL, g_variant_new_boolean(state));
    g_signal_connect(a, "change-state", G_CALLBACK(act_toggle_setting), NULL);
    g_action_map_add_action(G_ACTION_MAP(app), G_ACTION(a));
    g_object_unref(a);
}

static void build_menus(void)
{
    GMenu *m = g_menu_new(), *s;
    s = g_menu_new();
    g_menu_append(s, T("New Window"), "app.new-window");
    g_menu_append(s, T("New Tab"), "win.new-tab");
    g_menu_append(s, T("Open…"), "win.open");
    g_menu_append(s, T("Open Folder…"), "win.open-folder");
    recent_menu = g_menu_new();
    rebuild_recent_menu();
    g_menu_append_submenu(s, T("Open Recent"), G_MENU_MODEL(recent_menu));
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    s = g_menu_new();
    g_menu_append(s, T("Save"), "win.save");
    g_menu_append(s, T("Save As…"), "win.save-as");
    g_menu_append(s, T("Close Tab"), "win.close-tab");
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    s = g_menu_new();
    g_menu_append(s, T("Undo"), "win.undo");
    g_menu_append(s, T("Redo"), "win.redo");
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    s = g_menu_new();
    g_menu_append(s, T("Find…"), "win.find");
    g_menu_append(s, T("Find and Replace…"), "win.replace");
    g_menu_append(s, T("Go to Line…"), "win.goto-line");
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    s = g_menu_new();
    g_menu_append(s, T("Sidebar"), "win.sidebar");
    g_menu_append(s, T("Wrap Lines"), "app.wrap");
    g_menu_append(s, T("Line Numbers"), "app.line-numbers");
    g_menu_append(s, T("Invisible Characters"), "app.invisibles");
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    /* velikost pisma: tri tlacitka vedle sebe */
    s = g_menu_new();
    const char *zoom[][3] = {{"Smaller Text", "app.zoom-out", "zoom-out-symbolic"},
                             {"Default Text Size", "app.zoom-reset", "zoom-original-symbolic"},
                             {"Bigger Text", "app.zoom-in", "zoom-in-symbolic"}};
    for (int i = 0; i < 3; i++) {
        GMenuItem *it = g_menu_item_new(T(zoom[i][0]), zoom[i][1]);
        g_menu_item_set_attribute(it, "verb-icon", "s", zoom[i][2]);
        g_menu_append_item(s, it);
        g_object_unref(it);
    }
    GMenuItem *sec = g_menu_item_new_section(NULL, G_MENU_MODEL(s));
    g_menu_item_set_attribute(sec, "display-hint", "s", "horizontal-buttons");
    g_menu_append_item(m, sec);
    g_object_unref(sec);
    g_object_unref(s);
    s = g_menu_new();
    g_menu_append(s, T("Document Info"), "win.doc-info");
    g_menu_append_section(m, NULL, G_MENU_MODEL(s));
    g_object_unref(s);
    app_menu = G_MENU_MODEL(m);

    GMenu *e = g_menu_new();
    for (int i = 0; i < tx_n_encodings; i++) {
        char *l = encoding_label(&tx_encodings[i]);
        GMenuItem *it = g_menu_item_new(l, NULL);
        g_menu_item_set_action_and_target_value(it, "win.encoding", g_variant_new_string(tx_encodings[i].id));
        g_menu_append_item(e, it);
        g_object_unref(it);
        g_free(l);
    }
    enc_menu = G_MENU_MODEL(e);
    GMenu *le = g_menu_new();
    const char *les[][2] = {{"LF (Unix, Linux)", "LF"}, {"CRLF (Windows)", "CRLF"}, {"CR", "CR"}};
    for (int i = 0; i < 3; i++) {
        GMenuItem *it = g_menu_item_new(les[i][0], NULL);
        g_menu_item_set_action_and_target_value(it, "win.line-ending", g_variant_new_string(les[i][1]));
        g_menu_append_item(le, it);
        g_object_unref(it);
    }
    le_menu = G_MENU_MODEL(le);
}

static void set_accels(void)
{
    static const struct { const char *action; const char *accels[4]; } a[] = {
        {"app.new-window", {"<Primary>n"}}, {"win.new-tab", {"<Primary>t"}}, {"win.open", {"<Primary>o"}},
        {"win.open-folder", {"<Primary><Shift>o"}}, {"win.save", {"<Primary>s"}}, {"win.save-as", {"<Primary><Shift>s"}},
        {"win.close-tab", {"<Primary>w"}}, {"app.quit", {"<Primary>q"}}, {"win.find", {"<Primary>f"}},
        {"win.replace", {"<Primary>h"}}, {"win.find-next", {"<Primary>g", "F3"}},
        {"win.find-prev", {"<Primary><Shift>g", "<Shift>F3"}}, {"win.goto-line", {"<Primary>l"}},
        {"win.sidebar", {"F9"}}, {"win.doc-info", {"<Primary>i"}}, {"win.undo", {"<Primary>z"}},
        {"win.find-case", {"<Alt>c"}}, {"win.find-words", {"<Alt>w"}}, {"win.find-regex", {"<Alt>r"}},
        {"win.redo", {"<Primary><Shift>z", "<Primary>y"}},
        {"app.zoom-in", {"<Primary>plus", "<Primary>equal", "<Primary>KP_Add"}},
        {"app.zoom-out", {"<Primary>minus", "<Primary>KP_Subtract"}}, {"app.zoom-reset", {"<Primary>0", "<Primary>KP_0"}},
    };
    for (guint i = 0; i < G_N_ELEMENTS(a); i++) gtk_application_set_accels_for_action(app, a[i].action, a[i].accels);
}

static void prepend_lang_path(const char *dir)
{
    GtkSourceLanguageManager *lm = gtk_source_language_manager_get_default();
    const char *const *old = gtk_source_language_manager_get_search_path(lm);
    GPtrArray *p = g_ptr_array_new();
    g_ptr_array_add(p, (char *)dir);
    for (int i = 0; old && old[i]; i++) g_ptr_array_add(p, (char *)old[i]);
    g_ptr_array_add(p, NULL);
    gtk_source_language_manager_set_search_path(lm, (char **)p->pdata);
    g_ptr_array_free(p, TRUE);
}

static void on_startup(GApplication *ga, gpointer d)
{
    load_config();
    /* LUXOS_TEXT_DATA_DIR: barvy a jazyk LSL ze zdroju (testy); po instalaci jsou v adresarich GtkSourceView */
    const char *data = g_getenv("LUXOS_TEXT_DATA_DIR");
    if (data && *data) {
        char *styles = g_build_filename(data, "styles", NULL), *langs = g_build_filename(data, "language-specs", NULL);
        gtk_source_style_scheme_manager_prepend_search_path(gtk_source_style_scheme_manager_get_default(), styles);
        prepend_lang_path(langs);
        g_free(styles);
        g_free(langs);
    }
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_data(css, APP_CSS, -1, NULL);
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(css),
                                              GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_object_unref(css);
    font_css = gtk_css_provider_new();
    apply_font();
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(font_css),
                                              GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_action_map_add_action_entries(G_ACTION_MAP(app), app_actions, G_N_ELEMENTS(app_actions), NULL);
    if (test_mode) g_action_map_add_action_entries(G_ACTION_MAP(app), test_actions, G_N_ELEMENTS(test_actions), NULL);
    add_toggle("wrap", cfg.wrap);
    add_toggle("invisibles", cfg.invisibles);
    add_toggle("line-numbers", cfg.line_numbers);
    build_menus();
    set_accels();
    GtkSettings *s = gtk_settings_get_default();
    g_signal_connect(s, "notify::gtk-theme-name", G_CALLBACK(on_theme_changed), NULL);
    g_signal_connect(s, "notify::gtk-application-prefer-dark-theme", G_CALLBACK(on_theme_changed), NULL);
}

static void on_shutdown(GApplication *ga, gpointer d)
{
    if (save_config_id) {
        g_source_remove(save_config_id);
        save_config_now(NULL);
    }
}

static const char *usage =
    "Usage: luxos-text [OPTION…] [FILE…|FOLDER]\n"
    "LuxOS Text Editor - every call opens a new window (files in tabs, a folder in the sidebar).\n\n"
    "  +LINE              go to line LINE in the first file\n"
    "  --new-process      separate process (no reuse of a running editor)\n"
    "  -h, --help\n"
    "  -V, --version\n";

static int on_command_line(GApplication *ga, GApplicationCommandLine *cl, gpointer p)
{
    int argc;
    char **argv = g_application_command_line_get_arguments(cl, &argc);
    GPtrArray *paths = g_ptr_array_new_with_free_func(g_free);
    int line = -1;
    gboolean opts = TRUE;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (opts && !strcmp(a, "--")) { opts = FALSE; continue; }
        if (opts && a[0] == '+' && g_ascii_isdigit(a[1])) { line = atoi(a + 1); continue; }
        if (opts && a[0] == '-' && a[1]) continue;   /* --new-process, --new-window... */
        GFile *f = g_application_command_line_create_file_for_arg(cl, a);
        char *path = g_file_get_path(f);
        g_object_unref(f);
        if (path) g_ptr_array_add(paths, path);
    }
    g_ptr_array_add(paths, NULL);
    g_strfreev(argv);

    Win *w = new_window();
    open_paths(w, (char **)paths->pdata, line);
    g_ptr_array_unref(paths);
    update_window(w);
    const char *const *env = g_application_command_line_get_environ(cl);
    const char *sid = env ? g_environ_getenv((char **)env, "DESKTOP_STARTUP_ID") : NULL;
    if (sid) gtk_window_set_startup_id(w->win, sid);
    gtk_window_present(w->win);
    gtk_widget_grab_focus(GTK_WIDGET(w->cur->view));
    /* velke ikony az po prvnim vykresleni (nacteni SVG v 7 velikostech zdrzuje start) */
    if (!icon_list) g_idle_add_full(G_PRIORITY_LOW, icons_idle, NULL, NULL);
    return 0;
}

int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    gboolean unique = TRUE;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--")) break;
        if (!strcmp(argv[i], "--new-process")) unique = FALSE;
        if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) { fputs(usage, stdout); return 0; }
        if (!strcmp(argv[i], "-V") || !strcmp(argv[i], "--version")) {
            printf("luxos-text %s (GtkSourceView %d.%d.%d)\n", LUXOS_TEXT_VERSION, GTK_SOURCE_MAJOR_VERSION,
                   GTK_SOURCE_MINOR_VERSION, GTK_SOURCE_MICRO_VERSION);
            return 0;
        }
    }
    g_set_prgname("luxos-text");
    g_set_application_name(T("Text Editor"));
    test_mode = g_strcmp0(g_getenv("LUXOS_TEXT_TEST"), "1") == 0;
    if (g_getenv("LUXOS_TEXT_NEW_PROCESS")) unique = FALSE;
    app = gtk_application_new(APP_ID, G_APPLICATION_HANDLES_COMMAND_LINE | G_APPLICATION_SEND_ENVIRONMENT |
                                          (unique ? 0 : G_APPLICATION_NON_UNIQUE));
    g_signal_connect(app, "startup", G_CALLBACK(on_startup), NULL);
    g_signal_connect(app, "shutdown", G_CALLBACK(on_shutdown), NULL);
    g_signal_connect(app, "command-line", G_CALLBACK(on_command_line), NULL);
    int r = g_application_run(G_APPLICATION(app), argc, argv);
    g_object_unref(app);
    return r;
}
