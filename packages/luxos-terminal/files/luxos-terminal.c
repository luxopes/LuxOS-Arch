/*
 * LuxOS Terminal - lehky terminal (GTK3 + VTE) ve stylu macOS: panely, svetly/tmavy profil podle
 * systemu, obrazky SIXEL (VTE z [luxos] s obnovenou podporou SIXEL, viz packages/vte3), hledani,
 * odkazy, zvetseni pisma, pamatuje si velikost okna.
 *
 * Jeden proces pro vsechna okna (GtkApplication jako xfce4-terminal): dalsi "luxos-terminal" jen
 * preda prikazovou radku (adresar, prostredi) bezicimu procesu a skonci - nove okno je okamzite.
 * Volby kompatibilni s xfce4-terminal: -x/--execute, -e/--command, -T/--title, -w/--working-directory,
 * -H/--hold, --tab, --window, --maximize, --fullscreen, --geometry=SLOUPCExRADKY, --disable-server.
 *
 * Nastaveni: ~/.config/luxos/terminal.conf ([terminal] font, theme=dark|light|auto (vychozi dark jako
 * drive xfce4-terminal LuxOS, pozadi #1c1c22; auto = podle vzhledu systemu), opacity (vychozi 0.94 -
 * jen lehce pruhledne, 1 = nepruhledne), scrollback, sixel (obrazky), logo (logo fastfetch jako obrazek);
 * [state] columns, rows - posledni velikost okna).
 * Preklady: /usr/share/luxos/i18n/<jazyk>.tsv (LUXOS_I18N_DIR pro testy).
 */
#define PCRE2_CODE_UNIT_WIDTH 0
#include <pcre2.h>
#include <gtk/gtk.h>
#include <vte/vte.h>
#include <errno.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Tmave pozadi jako drive xfce4-terminal v LuxOS (#1c1c22, pruhlednost 0.94) */
#define DARK_BG "#1c1c22"

#ifndef LUXOS_TERMINAL_VERSION
#define LUXOS_TERMINAL_VERSION "1.0.0"
#endif
#define APP_ID "cz.luxos.Terminal"
#define DEFAULT_FONT "JetBrainsMono Nerd Font 11"

/* ---------- preklady (radek "anglicky<TAB>preklad", hleda se az pri pouziti) ---------- */
static char *tr_data;
static gboolean tr_loaded;

static const char *T(const char *en)
{
    if (!tr_loaded) {
        tr_loaded = TRUE;
        const char *l = g_getenv("LC_ALL");
        if (!l || !*l) l = g_getenv("LC_MESSAGES");
        if (!l || !*l) l = g_getenv("LANG");
        if (l && *l) {
            char lang[16];
            size_t n = strcspn(l, "_.@");
            if (n > 0 && n < sizeof lang - 1 && strncmp(l, "en", n) != 0 && strcmp(l, "C") && strcmp(l, "POSIX")) {
                memcpy(lang, l, n);
                lang[n] = 0;
                const char *dir = g_getenv("LUXOS_I18N_DIR");
                char *path = g_strdup_printf("%s/%s.tsv", dir && *dir ? dir : "/usr/share/luxos/i18n", lang);
                char *data = NULL;
                if (g_file_get_contents(path, &data, NULL, NULL)) {
                    tr_data = g_strconcat("\n", data, NULL);
                    g_free(data);
                }
                g_free(path);
            }
        }
    }
    if (!tr_data) return en;
    /* plati posledni radek s prekladem (jako i18n.sh) */
    size_t kl = strlen(en);
    const char *res = NULL, *p = tr_data;
    while ((p = strstr(p, en))) {
        if (p[-1] == '\n' && p[kl] == '\t') {
            const char *v = p + kl;
            while (*v == '\t') v++;
            if (*v && *v != '\n') res = v;
        }
        p += kl;
    }
    if (!res) return en;
    /* vysledek se pamatuje (texty jsou kratke a stale stejne) */
    static GHashTable *cache;
    if (!cache) cache = g_hash_table_new(g_str_hash, g_str_equal);
    char *v = g_hash_table_lookup(cache, en);
    if (!v) {
        size_t vl = strcspn(res, "\n");
        while (vl && (res[vl - 1] == '\t' || res[vl - 1] == '\r')) vl--;
        v = g_strndup(res, vl);
        g_hash_table_insert(cache, (gpointer)en, v);
    }
    return v;
}

/* ---------- nastaveni ---------- */
static struct {
    char *font;
    char *theme;        /* dark (vychozi), light, auto */
    double opacity;
    int scrollback;
    gboolean sixel;
    gboolean logo;
    int columns, rows;  /* posledni velikost okna */
} cfg;

static char *config_path(void)
{
    return g_build_filename(g_get_user_config_dir(), "luxos", "terminal.conf", NULL);
}

static void load_config(void)
{
    GKeyFile *kf = g_key_file_new();
    char *path = config_path();
    g_key_file_load_from_file(kf, path, G_KEY_FILE_NONE, NULL);
    g_free(path);
    cfg.font = g_key_file_get_string(kf, "terminal", "font", NULL);
    if (!cfg.font || !*cfg.font) { g_free(cfg.font); cfg.font = g_strdup(DEFAULT_FONT); }
    cfg.theme = g_key_file_get_string(kf, "terminal", "theme", NULL);
    if (cfg.theme && !strcmp(cfg.theme, "system")) { g_free(cfg.theme); cfg.theme = g_strdup("auto"); }
    if (!cfg.theme || (strcmp(cfg.theme, "light") && strcmp(cfg.theme, "auto"))) {
        g_free(cfg.theme);
        cfg.theme = g_strdup("dark");
    }
    GError *e = NULL;
    double o = g_key_file_get_double(kf, "terminal", "opacity", &e);
    /* jen lehce pruhledne (vic by bylo spatne citelne - prosvital by text okna pod terminalem) */
    if (e) { g_clear_error(&e); cfg.opacity = 0.94; }
    else cfg.opacity = CLAMP(o, 0.3, 1.0);
    cfg.scrollback = g_key_file_get_integer(kf, "terminal", "scrollback", &e);
    if (e) { g_clear_error(&e); cfg.scrollback = 10000; }
    cfg.sixel = g_key_file_get_boolean(kf, "terminal", "sixel", &e);
    if (e) { g_clear_error(&e); cfg.sixel = TRUE; }
    cfg.logo = g_key_file_get_boolean(kf, "terminal", "logo", &e);
    if (e) { g_clear_error(&e); cfg.logo = TRUE; }
    cfg.columns = g_key_file_get_integer(kf, "state", "columns", NULL);
    cfg.rows = g_key_file_get_integer(kf, "state", "rows", NULL);
    if (cfg.columns < 20 || cfg.columns > 1000) cfg.columns = 100;
    if (cfg.rows < 5 || cfg.rows > 500) cfg.rows = 30;
    g_key_file_free(kf);
}

static void save_size(long cols, long rows)
{
    if (cols < 20 || rows < 5 || (cols == cfg.columns && rows == cfg.rows)) return;
    cfg.columns = cols;
    cfg.rows = rows;
    GKeyFile *kf = g_key_file_new();
    char *path = config_path();
    g_key_file_load_from_file(kf, path, G_KEY_FILE_KEEP_COMMENTS, NULL);
    g_key_file_set_integer(kf, "state", "columns", cols);
    g_key_file_set_integer(kf, "state", "rows", rows);
    char *dir = g_path_get_dirname(path);
    g_mkdir_with_parents(dir, 0700);
    g_key_file_save_to_file(kf, path, NULL);
    g_free(dir);
    g_free(path);
    g_key_file_free(kf);
}

/* ---------- barvy (svetly a tmavy profil, paleta jako drive v xfce4-terminal) ---------- */
static const char *dark_palette[16] = {
    "#2e2e38", "#ff6b81", "#5ad08c", "#ffcc66", "#6ea8ff", "#c58bff", "#5fd7e6", "#d8d8e0",
    "#6c6c7a", "#ff8fa3", "#7ee2a8", "#ffd98a", "#93bfff", "#d6a8ff", "#8be8f2", "#ffffff"};
static const char *light_palette[16] = {
    "#1d1d1f", "#c4314b", "#1f8a4c", "#a16a00", "#2563d9", "#8a3fd1", "#0f7c8c", "#b8b8c2",
    "#6c6c7a", "#e0475f", "#2aa35c", "#b8860b", "#3d7bff", "#a45cf0", "#1597a8", "#8e8e99"};

static gboolean system_dark(void)
{
    if (!strcmp(cfg.theme, "dark")) return TRUE;
    if (!strcmp(cfg.theme, "light")) return FALSE;
    const char *env = g_getenv("GTK_THEME");   /* napr. Adwaita:dark */
    if (env && *env) return strstr(env, "dark") || strstr(env, "Dark");
    GtkSettings *s = gtk_settings_get_default();
    gboolean prefer = FALSE;
    char *name = NULL;
    g_object_get(s, "gtk-application-prefer-dark-theme", &prefer, "gtk-theme-name", &name, NULL);
    char *low = name ? g_ascii_strdown(name, -1) : NULL;
    gboolean dark = prefer || (low && strstr(low, "dark"));
    g_free(low);
    g_free(name);
    return dark;
}

static void apply_colors(VteTerminal *t)
{
    gboolean dark = system_dark();
    GdkRGBA pal[16], fg, bg, cur, sel;
    for (int i = 0; i < 16; i++) gdk_rgba_parse(&pal[i], (dark ? dark_palette : light_palette)[i]);
    gdk_rgba_parse(&fg, dark ? "#e6e6f0" : "#1d1d1f");
    gdk_rgba_parse(&bg, dark ? DARK_BG : "#ffffff");
    gdk_rgba_parse(&cur, dark ? "#a77bff" : "#7a4dff");
    gdk_rgba_parse(&sel, dark ? "#3a3a55" : "#c9d8ff");
    GdkScreen *scr = gtk_widget_get_screen(GTK_WIDGET(t));
    bg.alpha = scr && gdk_screen_is_composited(scr) ? cfg.opacity : 1.0;
    vte_terminal_set_colors(t, &fg, &bg, pal, 16);
    vte_terminal_set_color_cursor(t, &cur);
    vte_terminal_set_color_cursor_foreground(t, &bg);
    vte_terminal_set_color_highlight(t, &sel);
    vte_terminal_set_color_highlight_foreground(t, NULL);
    vte_terminal_set_color_bold(t, NULL);
}

/* ---------- okna a panely ---------- */
typedef struct {
    GtkWindow *win;
    GtkHeaderBar *header;
    GtkNotebook *nb;
    GtkWidget *search_bar, *search_entry;
    double scale;
    gboolean dead;      /* okno se rusi: signaly potomku uz nesmi sahat na Win */
} Win;

typedef struct {
    Win *w;
    VteTerminal *term;
    GtkWidget *scroller, *label;
    GPid pid;
    char *fixed_title;
    gboolean hold, exited;
    gboolean closed;    /* panel zrusen, Tab se uvolni az se scroller uvolni z pameti */
    GtkWidget *menu;    /* otevrena kontextova nabidka */
    char *link;         /* odkaz pod mysi pri otevreni nabidky */
} Tab;

static GtkApplication *app;
static gboolean sixel_available;
static VteRegex *url_regex;
static int url_tag = -1;
static GList *windows;  /* Win* */

static Tab *tab_of(GtkWidget *page) { return page ? g_object_get_data(G_OBJECT(page), "luxos-tab") : NULL; }

static Tab *current_tab(Win *w)
{
    int n = gtk_notebook_get_current_page(w->nb);
    return n < 0 ? NULL : tab_of(gtk_notebook_get_nth_page(w->nb, n));
}

static const char *tab_title(Tab *t)
{
    if (t->fixed_title) return t->fixed_title;
    const char *s = vte_terminal_get_termprop_string(t->term, VTE_TERMPROP_XTERM_TITLE, NULL);
    return s && *s ? s : T("Terminal");
}

static void update_title(Win *w)
{
    Tab *t = current_tab(w);
    const char *title = t ? tab_title(t) : T("Terminal");
    gtk_header_bar_set_title(w->header, title);
    gtk_window_set_title(w->win, title);
}

static void update_tabs_visible(Win *w)
{
    gtk_notebook_set_show_tabs(w->nb, gtk_notebook_get_n_pages(w->nb) > 1);
}

static char *cwd_of(Tab *t)
{
    /* adresar shellu (OSC 7 - termprop typu URI, jinak /proc/PID/cwd) */
    GUri *guri = vte_terminal_ref_termprop_uri(t->term, VTE_TERMPROP_CURRENT_DIRECTORY_URI);
    if (guri) {
        char *uri = g_uri_to_string(guri);
        char *p = uri ? g_filename_from_uri(uri, NULL, NULL) : NULL;
        g_free(uri);
        g_uri_unref(guri);
        if (p && g_file_test(p, G_FILE_TEST_IS_DIR)) return p;
        g_free(p);
    }
    if (t->pid > 0) {
        char proc[64];
        g_snprintf(proc, sizeof proc, "/proc/%d/cwd", (int)t->pid);
        char *p = g_file_read_link(proc, NULL);
        if (p && g_file_test(p, G_FILE_TEST_IS_DIR)) return p;
        g_free(p);
    }
    return NULL;
}

/* bezi v panelu jiny program nez shell? vrati jeho jmeno */
static char *running_process(Tab *t)
{
    if (t->exited || t->pid <= 0) return NULL;
    VtePty *pty = vte_terminal_get_pty(t->term);
    if (!pty) return NULL;
    pid_t fg = tcgetpgrp(vte_pty_get_fd(pty));
    if (fg <= 0 || fg == t->pid) return NULL;
    char path[64], *comm = NULL;
    g_snprintf(path, sizeof path, "/proc/%d/comm", (int)fg);
    if (g_file_get_contents(path, &comm, NULL, NULL)) g_strstrip(comm);
    return comm ? comm : g_strdup("?");
}

static gboolean confirm_close(GtkWindow *parent, const char *title, const char *detail)
{
    GtkWidget *d = gtk_message_dialog_new(parent, GTK_DIALOG_MODAL | GTK_DIALOG_DESTROY_WITH_PARENT,
                                          GTK_MESSAGE_QUESTION, GTK_BUTTONS_NONE, "%s", title);
    gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d), "%s", detail);
    gtk_dialog_add_button(GTK_DIALOG(d), T("Cancel"), GTK_RESPONSE_CANCEL);
    GtkWidget *b = gtk_dialog_add_button(GTK_DIALOG(d), T("Close"), GTK_RESPONSE_ACCEPT);
    gtk_style_context_add_class(gtk_widget_get_style_context(b), "destructive-action");
    gtk_dialog_set_default_response(GTK_DIALOG(d), GTK_RESPONSE_CANCEL);
    int r = gtk_dialog_run(GTK_DIALOG(d));
    gtk_widget_destroy(d);
    return r == GTK_RESPONSE_ACCEPT;
}

static gboolean is_fullscreen(Win *w)
{
    GdkWindow *gw = gtk_widget_get_window(GTK_WIDGET(w->win));
    return gw && (gdk_window_get_state(gw) & GDK_WINDOW_STATE_FULLSCREEN);
}

static void remember_size(Win *w)
{
    /* jen okno, ktere uz bylo videt, v bezne velikosti a pisma */
    Tab *t = current_tab(w);
    if (t && gtk_widget_get_mapped(GTK_WIDGET(w->win)) && !gtk_window_is_maximized(w->win) && !is_fullscreen(w) &&
        w->scale > 0.999 && w->scale < 1.001)
        save_size(vte_terminal_get_column_count(t->term), vte_terminal_get_row_count(t->term));
}

static void close_tab(Tab *t, gboolean ask)
{
    Win *w = t->w;
    if (t->closed || w->dead) return;
    if (ask) {
        char *p = running_process(t);
        if (p) {
            char *msg = g_strdup_printf(T("A process is still running in this tab: %s"), p);
            /* behem dialogu muze program skoncit a panel/okno zmizet - drzet odkazy a pak overit */
            GtkWidget *sc = g_object_ref(t->scroller);
            GtkWidget *win = g_object_ref(GTK_WIDGET(w->win));
            gboolean ok = confirm_close(w->win, T("Close this tab?"), msg);
            g_free(msg);
            g_free(p);
            gboolean gone = t->closed || w->dead;
            g_object_unref(win);
            g_object_unref(sc);   /* muze uvolnit t i w */
            if (!ok || gone) return;
        }
    }
    if (gtk_notebook_get_n_pages(w->nb) == 1) {
        remember_size(w);
        gtk_widget_destroy(GTK_WIDGET(w->win));
        return;
    }
    gtk_widget_destroy(t->scroller);
    update_tabs_visible(w);
    update_title(w);
}

static gboolean on_delete(GtkWidget *win, GdkEvent *ev, Win *w)
{
    int n = gtk_notebook_get_n_pages(w->nb), running = 0;
    char *name = NULL;
    for (int i = 0; i < n; i++) {
        char *p = running_process(tab_of(gtk_notebook_get_nth_page(w->nb, i)));
        if (p) { running++; if (!name) name = p; else g_free(p); }
    }
    if (running) {
        char *msg = running == 1 ? g_strdup_printf(T("A process is still running in this window: %s"), name)
                                 : g_strdup(T("Processes are still running in this window."));
        g_object_ref(win);
        gboolean ok = confirm_close(w->win, T("Close this window?"), msg);
        g_free(msg);
        g_free(name);
        gboolean gone = w->dead;   /* vsechny panely mezitim skoncily */
        g_object_unref(win);
        if (!ok || gone) return TRUE;
    }
    remember_size(w);
    return FALSE;
}

/* "destroy" prijde na zacatku ruseni okna, pred rusenim potomku: jejich signaly (switch-page,
 * page-removed, search-mode) by jinak pracovaly s uvolnenym Win. Odpojit je, Win uvolnit az
 * s oknem (weak ref = po dispose vsech potomku). */
static void on_win_destroy(GtkWidget *win, Win *w)
{
    w->dead = TRUE;
    windows = g_list_remove(windows, w);
    g_signal_handlers_disconnect_by_data(w->nb, w);
    g_signal_handlers_disconnect_by_data(w->search_bar, w);
    g_signal_handlers_disconnect_by_data(w->search_entry, w);
    g_signal_handlers_disconnect_by_data(win, w);
}

static void win_free(gpointer w, GObject *where) { g_free(w); }

/* ---------- spusteni shellu ---------- */
typedef struct {
    char **argv;        /* NULL = shell uzivatele */
    char *cwd;
    char **env;         /* prostredi volajiciho */
    char *title;
    gboolean hold;
} Spawn;

static void spawn_free(Spawn *s)
{
    g_strfreev(s->argv);
    g_free(s->cwd);
    g_strfreev(s->env);
    g_free(s->title);
}

static void on_spawned(VteTerminal *term, GPid pid, GError *err, gpointer data)
{
    Tab *t = g_object_get_data(G_OBJECT(term), "luxos-tab");
    if (!t) return;  /* panel uz je zavreny */
    if (err) {
        char *msg = g_strdup_printf("\r\n%s\r\n", err->message);
        vte_terminal_feed(term, msg, -1);
        g_free(msg);
        t->exited = TRUE;
        return;
    }
    t->pid = pid;
}

static void on_child_exited(VteTerminal *term, int status, Tab *t)
{
    t->exited = TRUE;
    t->pid = -1;
    if (t->hold) {
        char *msg = g_strdup_printf("\r\n\e[2m[%s]\e[0m", T("Process completed"));
        vte_terminal_feed(term, msg, -1);
        g_free(msg);
        return;
    }
    close_tab(t, FALSE);
}

static void on_title_changed(VteTerminal *term, const char *prop, Tab *t)
{
    gtk_label_set_text(GTK_LABEL(t->label), tab_title(t));
    gtk_widget_set_tooltip_text(t->label, tab_title(t));
    if (current_tab(t->w) == t) update_title(t->w);
}

static void open_uri(Win *w, const char *uri)
{
    char *u;
    if (g_str_has_prefix(uri, "www.")) u = g_strconcat("http://", uri, NULL);
    else if (!strstr(uri, ":") && strchr(uri, '@')) u = g_strconcat("mailto:", uri, NULL);
    else u = g_strdup(uri);
    GError *e = NULL;
    if (!gtk_show_uri_on_window(w->win, u, gtk_get_current_event_time(), &e)) {
        g_warning("%s", e->message);
        g_error_free(e);
    }
    g_free(u);
}

static char *link_at(Tab *t, GdkEvent *ev)
{
    char *l = vte_terminal_hyperlink_check_event(t->term, ev);
    if (!l) {
        int tag;
        l = vte_terminal_match_check_event(t->term, ev, &tag);
    }
    return l;
}

/* akce okna (klavesy a nabidka) */
static void new_tab(Win *w, Spawn *s);
static Win *new_window(Spawn *s);
static void zoom(Win *w, int dir);
static void show_search(Win *w);

static void act_copy(GtkWidget *mi, Tab *t) { vte_terminal_copy_clipboard_format(t->term, VTE_FORMAT_TEXT); }
static void act_paste(GtkWidget *mi, Tab *t) { vte_terminal_paste_clipboard(t->term); }
static void act_select_all(GtkWidget *mi, Tab *t) { vte_terminal_select_all(t->term); }
static void act_find(GtkWidget *mi, Tab *t) { show_search(t->w); }
static void act_close_tab(GtkWidget *mi, Tab *t) { close_tab(t, TRUE); }
static void act_new_tab(GtkWidget *mi, Tab *t)
{
    Spawn s = {0};
    s.cwd = cwd_of(t);
    new_tab(t->w, &s);
    spawn_free(&s);
}
static void act_new_window(GtkWidget *mi, Tab *t)
{
    Spawn s = {0};
    s.cwd = cwd_of(t);
    Win *nw = new_window(&s);
    gtk_window_present(nw->win);   /* new_window okno jen vytvori (prikazova radka ho ukaze sama) */
    spawn_free(&s);
}
static void act_open_link(GtkWidget *mi, Tab *t)
{
    if (t->link) open_uri(t->w, t->link);
}
static void act_copy_link(GtkWidget *mi, Tab *t)
{
    if (t->link) gtk_clipboard_set_text(gtk_clipboard_get(GDK_SELECTION_CLIPBOARD), t->link, -1);
}

/* nabidka se rusi az po aktivaci polozky (deactivate prichazi pred "activate") */
static gboolean menu_destroy_idle(gpointer menu)
{
    gtk_widget_destroy(menu);
    g_object_unref(menu);
    return G_SOURCE_REMOVE;
}

static void on_menu_deactivate(GtkWidget *menu, Tab *t)
{
    if (t->menu == menu) t->menu = NULL;
    g_signal_handlers_disconnect_by_data(menu, t);
    g_idle_add(menu_destroy_idle, g_object_ref(menu));
}

static GtkWidget *menu_item(GtkWidget *menu, const char *label, const char *accel, GCallback cb, Tab *t)
{
    GtkWidget *mi = gtk_menu_item_new_with_label(label);
    if (accel) {
        guint key;
        GdkModifierType mods;
        gtk_accelerator_parse(accel, &key, &mods);
        gtk_accel_label_set_accel(GTK_ACCEL_LABEL(gtk_bin_get_child(GTK_BIN(mi))), key, mods);
    }
    g_signal_connect(mi, "activate", cb, t);
    gtk_menu_shell_append(GTK_MENU_SHELL(menu), mi);
    return mi;
}

static void menu_sep(GtkWidget *menu) { gtk_menu_shell_append(GTK_MENU_SHELL(menu), gtk_separator_menu_item_new()); }

static gboolean on_button(VteTerminal *term, GdkEventButton *ev, Tab *t)
{
    if (ev->type != GDK_BUTTON_PRESS) return FALSE;
    if (ev->button == 1 && (ev->state & GDK_CONTROL_MASK)) {
        char *l = link_at(t, (GdkEvent *)ev);
        if (l) { open_uri(t->w, l); g_free(l); return TRUE; }
        return FALSE;
    }
    if (ev->button != 3) return FALSE;
    /* Shift+prave tlacitko a aplikace s mysi (mc, htop) dostanou klik samy */
    if (vte_terminal_get_has_selection(term) == FALSE && (ev->state & GDK_SHIFT_MASK)) return FALSE;

    if (t->menu) gtk_widget_destroy(t->menu);
    GtkWidget *menu = t->menu = gtk_menu_new();
    char *l = link_at(t, (GdkEvent *)ev);
    g_free(t->link);
    t->link = l;
    if (l) {
        menu_item(menu, T("Open Link"), NULL, G_CALLBACK(act_open_link), t);
        menu_item(menu, T("Copy Link Address"), NULL, G_CALLBACK(act_copy_link), t);
        menu_sep(menu);
    }
    GtkWidget *c = menu_item(menu, T("Copy"), "<Primary><Shift>c", G_CALLBACK(act_copy), t);
    gtk_widget_set_sensitive(c, vte_terminal_get_has_selection(term));
    menu_item(menu, T("Paste"), "<Primary><Shift>v", G_CALLBACK(act_paste), t);
    menu_item(menu, T("Select All"), "<Primary><Shift>a", G_CALLBACK(act_select_all), t);
    menu_sep(menu);
    menu_item(menu, T("New Tab"), "<Primary><Shift>t", G_CALLBACK(act_new_tab), t);
    menu_item(menu, T("New Window"), "<Primary><Shift>n", G_CALLBACK(act_new_window), t);
    menu_item(menu, T("Find…"), "<Primary><Shift>f", G_CALLBACK(act_find), t);
    menu_sep(menu);
    menu_item(menu, T("Close Tab"), "<Primary><Shift>w", G_CALLBACK(act_close_tab), t);
    gtk_widget_show_all(menu);
    gtk_menu_attach_to_widget(GTK_MENU(menu), GTK_WIDGET(term), NULL);
    g_signal_connect(menu, "deactivate", G_CALLBACK(on_menu_deactivate), t);
    gtk_menu_popup_at_pointer(GTK_MENU(menu), (GdkEvent *)ev);
    return TRUE;
}

static void on_bell(VteTerminal *term, Tab *t)
{
    if (!gtk_window_is_active(t->w->win)) gtk_window_set_urgency_hint(t->w->win, TRUE);
}

static gboolean on_focus_in(GtkWidget *win, GdkEvent *ev, Win *w)
{
    gtk_window_set_urgency_hint(w->win, FALSE);
    return FALSE;
}

/* Ruseni panelu: signaly terminalu odpojit hned (VTE muze behem ruseni jeste neco hlasit),
 * Tab uvolnit az s uvolnenim scrolleru (close_tab ho muze drzet pres dialog). */
static void tab_destroyed(GtkWidget *scroller, Tab *t)
{
    t->closed = TRUE;
    g_signal_handlers_disconnect_by_data(t->term, t);
    g_object_set_data(G_OBJECT(t->term), "luxos-tab", NULL);
    if (t->menu) gtk_widget_destroy(t->menu);
}

static void tab_free(gpointer data, GObject *where)
{
    Tab *t = data;
    g_free(t->fixed_title);
    g_free(t->link);
    g_free(t);
}

static void on_tab_close_clicked(GtkButton *b, Tab *t) { close_tab(t, TRUE); }

static gboolean on_tab_label_button(GtkWidget *w, GdkEventButton *ev, Tab *t)
{
    if (ev->type == GDK_BUTTON_PRESS && ev->button == 2) { close_tab(t, TRUE); return TRUE; }
    return FALSE;
}

/* ---------- logo LuxOS jako SIXEL pro fastfetch ----------
 * Obrazek se pripravi pro presnou velikost znaku terminalu (LOGO_COLS x LOGO_ROWS bunek jako logo
 * v /etc/xdg/luxos/fastfetch/config.jsonc), okraje se smichaji s pozadim profilu. Uklada se do
 * ~/.cache/luxos/terminal/ (jednou pro kazdou velikost pisma a profil), shell dostane cestu
 * v LUXOS_TERMINAL_LOGO a fastfetch ho vypise jako "raw" logo. */
#define LOGO_COLS 31
#define LOGO_ROWS 12

static GString *sixel_encode(GdkPixbuf *pb, const GdkRGBA *bg)
{
    int w = gdk_pixbuf_get_width(pb), h = gdk_pixbuf_get_height(pb);
    int nch = gdk_pixbuf_get_n_channels(pb), rs = gdk_pixbuf_get_rowstride(pb);
    gboolean alpha = gdk_pixbuf_get_has_alpha(pb);
    const guchar *px = gdk_pixbuf_read_pixels(pb);
    guint8 *rgb = g_malloc((size_t)w * h * 3);
    gboolean *opaque = g_malloc((size_t)w * h * sizeof(gboolean));
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            const guchar *p = px + y * rs + x * nch;
            double a = alpha ? p[3] / 255.0 : 1.0;
            size_t i = (size_t)y * w + x;
            opaque[i] = a >= 0.5;
            rgb[i * 3] = (guint8)(p[0] * a + bg->red * 255 * (1 - a) + 0.5);
            rgb[i * 3 + 1] = (guint8)(p[1] * a + bg->green * 255 * (1 - a) + 0.5);
            rgb[i * 3 + 2] = (guint8)(p[2] * a + bg->blue * 255 * (1 - a) + 0.5);
        }
    /* paleta: barvy zaokrouhlene na 5 bitu (VTE ma 1024 registru), pri vice barvach hrubeji */
    int *idx = g_malloc((size_t)w * h * sizeof(int)), ncolors = 0;
    int map[32768];
    long sum[1024][4];
    for (int shift = 3; shift <= 5; shift++) {
        memset(map, -1, sizeof map);
        memset(sum, 0, sizeof sum);
        ncolors = 0;
        int bits = 8 - shift;
        for (size_t i = 0; i < (size_t)w * h && ncolors <= 1024; i++) {
            if (!opaque[i]) { idx[i] = -1; continue; }
            int key = (rgb[i * 3] >> shift) << (2 * bits) | (rgb[i * 3 + 1] >> shift) << bits | (rgb[i * 3 + 2] >> shift);
            if (map[key] < 0) {
                if (ncolors == 1024) { ncolors++; break; }
                map[key] = ncolors++;
            }
            int c = idx[i] = map[key];
            sum[c][0] += rgb[i * 3]; sum[c][1] += rgb[i * 3 + 1]; sum[c][2] += rgb[i * 3 + 2]; sum[c][3]++;
        }
        if (ncolors <= 1024) break;
    }
    GString *s = g_string_sized_new(64 * 1024);
    /* P2=1: nenakreslene body pruhledne */
    g_string_append_printf(s, "\eP0;1;0q\"1;1;%d;%d", w, h);
    for (int c = 0; c < ncolors; c++) {
        long n = MAX(sum[c][3], 1);
        g_string_append_printf(s, "#%d;2;%ld;%ld;%ld", c, (sum[c][0] / n * 100 + 127) / 255,
                               (sum[c][1] / n * 100 + 127) / 255, (sum[c][2] / n * 100 + 127) / 255);
    }
    guint8 *present = g_malloc0(ncolors ? ncolors : 1);
    char *row = g_malloc(w);
    for (int y0 = 0; y0 < h; y0 += 6) {
        memset(present, 0, ncolors ? ncolors : 1);
        for (int y = y0; y < MIN(y0 + 6, h); y++)
            for (int x = 0; x < w; x++)
                if (idx[(size_t)y * w + x] >= 0) present[idx[(size_t)y * w + x]] = 1;
        gboolean first = TRUE;
        for (int c = 0; c < ncolors; c++) {
            if (!present[c]) continue;
            int last = -1;
            for (int x = 0; x < w; x++) {
                int b = 0;
                for (int k = 0; k < 6 && y0 + k < h; k++)
                    if (idx[(size_t)(y0 + k) * w + x] == c) b |= 1 << k;
                row[x] = (char)(63 + b);
                if (b) last = x;
            }
            if (!first) g_string_append_c(s, '$');
            first = FALSE;
            g_string_append_printf(s, "#%d", c);
            for (int x = 0; x <= last;) {
                int r = 1;
                while (x + r <= last && row[x + r] == row[x]) r++;
                if (r > 3) g_string_append_printf(s, "!%d%c", r, row[x]);
                else for (int k = 0; k < r; k++) g_string_append_c(s, row[x]);
                x += r;
            }
        }
        g_string_append_c(s, '-');
    }
    g_string_append(s, "\e\\");
    g_free(row);
    g_free(present);
    g_free(idx);
    g_free(opaque);
    g_free(rgb);
    return s;
}

static char *logo_render(long cw, long ch, gboolean dark)
{
    if (cw < 2 || ch < 4 || cw > 200 || ch > 400) return NULL;
    char *name = g_strdup_printf("logo-%ldx%ld-%s.six", cw, ch, dark ? "dark" : "light");
    char *path = g_build_filename(g_get_user_cache_dir(), "luxos", "terminal", name, NULL);
    g_free(name);
    if (g_file_test(path, G_FILE_TEST_EXISTS)) return path;

    /* barevne logo (stejne jako ikona a znakove logo fastfetche): vektor v presne velikosti
     * (zavadec SVG luxos-pixbuf-svg), jinak PNG 256 px z luxos-branding */
    const char *srcs[] = {g_getenv("LUXOS_TERMINAL_LOGO_SOURCE"), "/usr/share/luxos/terminal/logo.png",
                          "/usr/share/luxos/logo/luxos-logo.svg",
                          "/usr/share/pixmaps/luxos-logo.png"};
    /* logo (ctverec) na vysku pole loga, posledni radek volny pro kurzor po obrazku */
    int size = (int)MIN(LOGO_COLS * cw, (LOGO_ROWS - 1) * ch);
    GdkPixbuf *pb = NULL;
    for (guint i = 0; i < G_N_ELEMENTS(srcs) && !pb; i++)
        if (srcs[i] && *srcs[i]) pb = gdk_pixbuf_new_from_file_at_size(srcs[i], size, size, NULL);
    if (!pb) { g_free(path); return NULL; }
    GdkRGBA bg;
    gdk_rgba_parse(&bg, dark ? DARK_BG : "#ffffff");
    GString *six = sixel_encode(pb, &bg);
    g_object_unref(pb);
    char *dir = g_path_get_dirname(path);
    g_mkdir_with_parents(dir, 0700);
    g_free(dir);
    gboolean ok = g_file_set_contents(path, six->str, six->len, NULL);
    g_string_free(six, TRUE);
    if (!ok) { g_free(path); return NULL; }
    return path;
}

static char *logo_for(VteTerminal *t)
{
    return logo_render(vte_terminal_get_char_width(t), vte_terminal_get_char_height(t), system_dark());
}

static char **child_env(char **base, VteTerminal *t)
{
    char **env = base ? g_strdupv(base) : g_get_environ();
    char *logo = NULL;
    if (sixel_available && cfg.sixel && cfg.logo && (logo = logo_for(t)))
        env = g_environ_setenv(env, "LUXOS_TERMINAL_LOGO", logo, TRUE);
    else
        env = g_environ_unsetenv(env, "LUXOS_TERMINAL_LOGO");
    g_free(logo);
    /* TERM volajiciho (napr. tmux, linux pri spusteni z konzole) by prepsal hodnotu VTE */
    env = g_environ_setenv(env, "TERM", "xterm-256color", TRUE);
    env = g_environ_setenv(env, "TERM_PROGRAM", "LuxOS-Terminal", TRUE);
    env = g_environ_setenv(env, "TERM_PROGRAM_VERSION", LUXOS_TERMINAL_VERSION, TRUE);
    env = g_environ_unsetenv(env, "COLUMNS");
    env = g_environ_unsetenv(env, "LINES");
    env = g_environ_unsetenv(env, "DESKTOP_STARTUP_ID");
    env = g_environ_unsetenv(env, "XDG_ACTIVATION_TOKEN");
    env = g_environ_unsetenv(env, "TMUX");     /* spusteno z tmux/screen: novy terminal uz v nem neni */
    env = g_environ_unsetenv(env, "TMUX_PANE");
    env = g_environ_unsetenv(env, "STY");
    if (sixel_available && cfg.sixel) env = g_environ_setenv(env, "LUXOS_TERMINAL_SIXEL", "1", TRUE);
    else env = g_environ_unsetenv(env, "LUXOS_TERMINAL_SIXEL");
    return env;
}

static void new_tab(Win *w, Spawn *s)
{
    Tab *t = g_new0(Tab, 1);
    t->w = w;
    t->hold = s->hold;
    t->fixed_title = g_strdup(s->title);
    t->term = VTE_TERMINAL(vte_terminal_new());
    g_object_set_data(G_OBJECT(t->term), "luxos-tab", t);

    VteTerminal *term = t->term;
    PangoFontDescription *fd = pango_font_description_from_string(cfg.font);
    vte_terminal_set_font(term, fd);
    pango_font_description_free(fd);
    vte_terminal_set_font_scale(term, w->scale);
    vte_terminal_set_scrollback_lines(term, cfg.scrollback);
    vte_terminal_set_cursor_shape(term, VTE_CURSOR_SHAPE_IBEAM);
    vte_terminal_set_cursor_blink_mode(term, VTE_CURSOR_BLINK_ON);
    vte_terminal_set_audible_bell(term, FALSE);
    vte_terminal_set_allow_hyperlink(term, TRUE);
    vte_terminal_set_scroll_on_keystroke(term, TRUE);
    vte_terminal_set_scroll_on_output(term, FALSE);
    vte_terminal_set_mouse_autohide(term, TRUE);
    vte_terminal_set_bold_is_bright(term, FALSE);
    if (sixel_available && cfg.sixel) vte_terminal_set_enable_sixel(term, TRUE);
    if (url_regex) {
        url_tag = vte_terminal_match_add_regex(term, url_regex, 0);
        vte_terminal_match_set_cursor_name(term, url_tag, "pointer");
    }
    vte_terminal_set_size(term, cfg.columns, cfg.rows);
    apply_colors(term);

    t->scroller = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(t->scroller), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_propagate_natural_width(GTK_SCROLLED_WINDOW(t->scroller), TRUE);
    gtk_scrolled_window_set_propagate_natural_height(GTK_SCROLLED_WINDOW(t->scroller), TRUE);
    gtk_container_add(GTK_CONTAINER(t->scroller), GTK_WIDGET(term));
    g_object_set_data(G_OBJECT(t->scroller), "luxos-tab", t);
    g_signal_connect(t->scroller, "destroy", G_CALLBACK(tab_destroyed), t);
    g_object_weak_ref(G_OBJECT(t->scroller), tab_free, t);

    /* stitek panelu: nazev + zaviraci tlacitko, prostrednim tlacitkem zavrit */
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 4);
    t->label = gtk_label_new(tab_title(t));
    gtk_label_set_ellipsize(GTK_LABEL(t->label), PANGO_ELLIPSIZE_START);
    gtk_label_set_width_chars(GTK_LABEL(t->label), 8);
    gtk_widget_set_hexpand(t->label, TRUE);
    GtkWidget *close = gtk_button_new_from_icon_name("window-close-symbolic", GTK_ICON_SIZE_MENU);
    gtk_button_set_relief(GTK_BUTTON(close), GTK_RELIEF_NONE);
    gtk_widget_set_focus_on_click(close, FALSE);
    gtk_widget_set_tooltip_text(close, T("Close Tab"));
    g_signal_connect(close, "clicked", G_CALLBACK(on_tab_close_clicked), t);
    GtkWidget *ev = gtk_event_box_new();
    gtk_event_box_set_visible_window(GTK_EVENT_BOX(ev), FALSE);
    gtk_container_add(GTK_CONTAINER(ev), t->label);
    g_signal_connect(ev, "button-press-event", G_CALLBACK(on_tab_label_button), t);
    gtk_box_pack_start(GTK_BOX(box), ev, TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(box), close, FALSE, FALSE, 0);
    gtk_widget_show_all(box);

    g_signal_connect(term, "child-exited", G_CALLBACK(on_child_exited), t);
    g_signal_connect(term, "termprop-changed::" VTE_TERMPROP_XTERM_TITLE, G_CALLBACK(on_title_changed), t);
    g_signal_connect(term, "button-press-event", G_CALLBACK(on_button), t);
    g_signal_connect(term, "bell", G_CALLBACK(on_bell), t);

    int cur = gtk_notebook_get_current_page(w->nb);
    int pos = gtk_notebook_insert_page(w->nb, t->scroller, box, cur < 0 ? -1 : cur + 1);
    gtk_notebook_set_tab_reorderable(w->nb, t->scroller, TRUE);
    gtk_container_child_set(GTK_CONTAINER(w->nb), t->scroller, "tab-expand", TRUE, NULL);
    gtk_widget_show_all(t->scroller);
    gtk_notebook_set_current_page(w->nb, pos);
    update_tabs_visible(w);
    gtk_widget_grab_focus(GTK_WIDGET(term));

    /* shell uzivatele (ne prihlasovaci, jako xfce4-terminal) nebo zadany prikaz */
    char **argv = s->argv ? g_strdupv(s->argv) : NULL;
    if (!argv) {
        char *sh = vte_get_user_shell();
        if (!sh || !*sh) { g_free(sh); sh = g_strdup(g_getenv("SHELL") ? g_getenv("SHELL") : "/bin/sh"); }
        argv = g_new0(char *, 2);
        argv[0] = sh;
    }
    char **env = child_env(s->env, term);
    const char *cwd = s->cwd && g_file_test(s->cwd, G_FILE_TEST_IS_DIR) ? s->cwd : g_get_home_dir();
    vte_terminal_spawn_async(term, VTE_PTY_DEFAULT, cwd, argv, env, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL,
                             -1, NULL, on_spawned, NULL);
    g_strfreev(argv);
    g_strfreev(env);
}

static void zoom(Win *w, int dir)
{
    static const double steps[] = {0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.7, 2.0, 2.4, 3.0};
    int n = G_N_ELEMENTS(steps), i = 0;
    while (i < n - 1 && steps[i] < w->scale - 0.001) i++;
    if (dir > 0 && i < n - 1 && steps[i] <= w->scale + 0.001) i++;
    else if (dir < 0 && i > 0) i--;
    w->scale = dir == 0 ? 1.0 : steps[i];
    for (int p = 0; p < gtk_notebook_get_n_pages(w->nb); p++) {
        Tab *t = tab_of(gtk_notebook_get_nth_page(w->nb, p));
        long c = vte_terminal_get_column_count(t->term), r = vte_terminal_get_row_count(t->term);
        vte_terminal_set_font_scale(t->term, w->scale);
        /* okno se prizpusobi (stejny pocet sloupcu a radku), maximalizovane zustava */
        if (!gtk_window_is_maximized(w->win)) vte_terminal_set_size(t->term, c, r);
    }
    if (!gtk_window_is_maximized(w->win)) gtk_window_resize(w->win, 1, 1);
}

/* ---------- hledani ---------- */
static void search_update(Win *w, int dir)
{
    Tab *t = current_tab(w);
    if (!t) return;
    const char *text = gtk_entry_get_text(GTK_ENTRY(w->search_entry));
    if (dir == 0) {
        VteRegex *re = NULL;
        if (*text) {
            char *esc = g_regex_escape_string(text, -1);
            gboolean upper = FALSE;
            for (const char *p = text; *p; p = g_utf8_next_char(p))
                if (g_unichar_isupper(g_utf8_get_char(p))) upper = TRUE;
            re = vte_regex_new_for_search(esc, -1, PCRE2_MULTILINE | (upper ? 0 : PCRE2_CASELESS), NULL);
            g_free(esc);
        }
        vte_terminal_search_set_regex(t->term, re, 0);
        vte_terminal_search_set_wrap_around(t->term, TRUE);
        if (re) vte_regex_unref(re);
        else { vte_terminal_unselect_all(t->term); return; }
        dir = -1;
    }
    gboolean found = dir < 0 ? vte_terminal_search_find_previous(t->term) : vte_terminal_search_find_next(t->term);
    GtkStyleContext *sc = gtk_widget_get_style_context(w->search_entry);
    if (found || !*text) gtk_style_context_remove_class(sc, "error");
    else gtk_style_context_add_class(sc, "error");
}

static void on_search_changed(GtkSearchEntry *e, Win *w) { search_update(w, 0); }
static void on_search_prev(GtkWidget *b, Win *w) { search_update(w, -1); }
static void on_search_next(GtkWidget *b, Win *w) { search_update(w, 1); }
static void on_search_activate(GtkEntry *e, Win *w) { search_update(w, -1); }

static void on_search_mode(GObject *bar, GParamSpec *ps, Win *w)
{
    if (gtk_search_bar_get_search_mode(GTK_SEARCH_BAR(w->search_bar))) return;
    Tab *t = current_tab(w);
    if (t) {
        vte_terminal_search_set_regex(t->term, NULL, 0);
        gtk_widget_grab_focus(GTK_WIDGET(t->term));
    }
}

static gboolean on_search_key(GtkWidget *e, GdkEventKey *ev, Win *w)
{
    if ((ev->keyval == GDK_KEY_Return || ev->keyval == GDK_KEY_KP_Enter) && (ev->state & GDK_SHIFT_MASK)) {
        search_update(w, 1);
        return TRUE;
    }
    return FALSE;
}

/* Pole hledani dostane fokus az po zobrazeni: drive (lista se teprve vysouva) by uvolneni klaves
 * zkratky slo do nerealizovaneho widgetu (Gtk-CRITICAL gtk_widget_event). */
static void search_entry_mapped(GtkWidget *entry, gpointer d)
{
    g_signal_handlers_disconnect_by_func(entry, search_entry_mapped, d);
    gtk_widget_grab_focus(entry);
    gtk_editable_select_region(GTK_EDITABLE(entry), 0, -1);
}

static void hide_search(Win *w)
{
    gtk_search_bar_set_search_mode(GTK_SEARCH_BAR(w->search_bar), FALSE);
}

static void show_search(Win *w)
{
    gtk_search_bar_set_search_mode(GTK_SEARCH_BAR(w->search_bar), TRUE);
    if (gtk_widget_get_mapped(w->search_entry)) gtk_widget_grab_focus(w->search_entry);
    else if (!g_signal_handler_find(w->search_entry, G_SIGNAL_MATCH_FUNC, 0, 0, NULL, search_entry_mapped, NULL))
        g_signal_connect_after(w->search_entry, "map", G_CALLBACK(search_entry_mapped), NULL);
    Tab *t = current_tab(w);
    if (t && vte_terminal_get_has_selection(t->term)) {
        char *s = vte_terminal_get_text_selected(t->term, VTE_FORMAT_TEXT);
        if (s && *s && !strchr(s, '\n')) gtk_entry_set_text(GTK_ENTRY(w->search_entry), s);
        g_free(s);
    }
    gtk_editable_select_region(GTK_EDITABLE(w->search_entry), 0, -1);
}

/* ---------- klavesy ---------- */
static gboolean on_key(GtkWidget *win, GdkEventKey *ev, Win *w)
{
    GdkModifierType m = ev->state & gtk_accelerator_get_default_mod_mask();
    guint k = gdk_keyval_to_lower(ev->keyval);
    Tab *t = current_tab(w);
    if (!t) return FALSE;
    /* klavesy pro vyhledavaci pole nechat jemu */
    if (gtk_widget_has_focus(w->search_entry) && !(m & GDK_CONTROL_MASK)) return FALSE;

    if (m == (GDK_CONTROL_MASK | GDK_SHIFT_MASK)) {
        switch (k) {
        case GDK_KEY_c: vte_terminal_copy_clipboard_format(t->term, VTE_FORMAT_TEXT); return TRUE;
        case GDK_KEY_v: vte_terminal_paste_clipboard(t->term); return TRUE;
        case GDK_KEY_t: act_new_tab(NULL, t); return TRUE;
        case GDK_KEY_n: act_new_window(NULL, t); return TRUE;
        case GDK_KEY_w: close_tab(t, TRUE); return TRUE;
        case GDK_KEY_q: if (!on_delete(win, NULL, w)) gtk_widget_destroy(win); return TRUE;
        case GDK_KEY_f: show_search(w); return TRUE;
        case GDK_KEY_a: vte_terminal_select_all(t->term); return TRUE;
        case GDK_KEY_g: search_update(w, 1); return TRUE;
        case GDK_KEY_Page_Up: case GDK_KEY_Page_Down: {
            int n = gtk_notebook_get_current_page(w->nb), c = gtk_notebook_get_n_pages(w->nb);
            int to = k == GDK_KEY_Page_Up ? n - 1 : n + 1;
            if (to >= 0 && to < c) gtk_notebook_reorder_child(w->nb, t->scroller, to);
            return TRUE;
        }
        case GDK_KEY_plus: zoom(w, 1); return TRUE;   /* Ctrl+Shift+= na US klavesnici */
        }
    }
    if (m == GDK_CONTROL_MASK) {
        switch (k) {
        case GDK_KEY_plus: case GDK_KEY_equal: case GDK_KEY_KP_Add: zoom(w, 1); return TRUE;
        case GDK_KEY_minus: case GDK_KEY_KP_Subtract: zoom(w, -1); return TRUE;
        case GDK_KEY_0: case GDK_KEY_KP_0: zoom(w, 0); return TRUE;
        case GDK_KEY_Page_Up: gtk_notebook_prev_page(w->nb); return TRUE;
        case GDK_KEY_Page_Down: gtk_notebook_next_page(w->nb); return TRUE;
        }
    }
    if (m == GDK_MOD1_MASK && k >= GDK_KEY_1 && k <= GDK_KEY_9 && gtk_notebook_get_n_pages(w->nb) > 1) {
        int n = k == GDK_KEY_9 ? gtk_notebook_get_n_pages(w->nb) - 1 : (int)(k - GDK_KEY_1);
        if (n < gtk_notebook_get_n_pages(w->nb)) gtk_notebook_set_current_page(w->nb, n);
        return TRUE;
    }
    if (m == 0 && k == GDK_KEY_F11) {
        if (is_fullscreen(w)) gtk_window_unfullscreen(w->win);
        else gtk_window_fullscreen(w->win);
        return TRUE;
    }
    if (m == 0 && k == GDK_KEY_Escape && gtk_search_bar_get_search_mode(GTK_SEARCH_BAR(w->search_bar))) {
        gtk_search_bar_set_search_mode(GTK_SEARCH_BAR(w->search_bar), FALSE);
        return TRUE;
    }
    return FALSE;
}

static void on_switch_page(GtkNotebook *nb, GtkWidget *page, guint n, Win *w)
{
    Tab *t = tab_of(page);
    if (!t) return;
    const char *title = tab_title(t);
    gtk_header_bar_set_title(w->header, title);
    gtk_window_set_title(w->win, title);
    gtk_widget_grab_focus(GTK_WIDGET(t->term));
}

static void on_page_removed(GtkNotebook *nb, GtkWidget *page, guint n, Win *w) { update_tabs_visible(w); }

static void on_new_tab_button(GtkWidget *b, Win *w)
{
    Tab *t = current_tab(w);
    if (t) act_new_tab(NULL, t);
    else { Spawn s = {0}; new_tab(w, &s); }
}

static Win *new_window(Spawn *s)
{
    Win *w = g_new0(Win, 1);
    w->scale = 1.0;
    w->win = GTK_WINDOW(gtk_application_window_new(app));
    gtk_style_context_add_class(gtk_widget_get_style_context(GTK_WIDGET(w->win)), "luxos-terminal");
    gtk_window_set_icon_name(w->win, "utilities-terminal");
    GdkScreen *scr = gtk_widget_get_screen(GTK_WIDGET(w->win));
    GdkVisual *v = gdk_screen_get_rgba_visual(scr);
    if (v && gdk_screen_is_composited(scr) && cfg.opacity < 1.0) gtk_widget_set_visual(GTK_WIDGET(w->win), v);

    w->header = GTK_HEADER_BAR(gtk_header_bar_new());
    gtk_header_bar_set_show_close_button(w->header, TRUE);
    gtk_header_bar_set_title(w->header, T("Terminal"));
    GtkWidget *plus = gtk_button_new_from_icon_name("tab-new-symbolic", GTK_ICON_SIZE_BUTTON);
    gtk_widget_set_tooltip_text(plus, T("New Tab"));
    gtk_widget_set_focus_on_click(plus, FALSE);
    g_signal_connect(plus, "clicked", G_CALLBACK(on_new_tab_button), w);
    gtk_header_bar_pack_end(w->header, plus);
    GtkWidget *find = gtk_button_new_from_icon_name("edit-find-symbolic", GTK_ICON_SIZE_BUTTON);
    gtk_widget_set_tooltip_text(find, T("Find…"));
    gtk_widget_set_focus_on_click(find, FALSE);
    g_signal_connect_swapped(find, "clicked", G_CALLBACK(show_search), w);
    gtk_header_bar_pack_end(w->header, find);
    gtk_window_set_titlebar(w->win, GTK_WIDGET(w->header));

    GtkWidget *vbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    /* hledani */
    w->search_bar = gtk_search_bar_new();
    GtkWidget *sbox = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_style_context_add_class(gtk_widget_get_style_context(sbox), "linked");
    w->search_entry = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(w->search_entry), T("Find"));
    gtk_entry_set_width_chars(GTK_ENTRY(w->search_entry), 30);
    GtkWidget *up = gtk_button_new_from_icon_name("go-up-symbolic", GTK_ICON_SIZE_BUTTON);
    GtkWidget *down = gtk_button_new_from_icon_name("go-down-symbolic", GTK_ICON_SIZE_BUTTON);
    gtk_widget_set_tooltip_text(up, T("Find Previous"));
    gtk_widget_set_tooltip_text(down, T("Find Next"));
    gtk_box_pack_start(GTK_BOX(sbox), w->search_entry, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(sbox), up, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(sbox), down, FALSE, FALSE, 0);
    gtk_container_add(GTK_CONTAINER(w->search_bar), sbox);
    /* bez gtk_search_bar_connect_entry: lista by dala fokus poli jeste pred jeho realizaci (uvolneni
     * klaves zkratky -> Gtk-CRITICAL); fokus dava show_search, Esc zavira pres stop-search */
    g_signal_connect_swapped(w->search_entry, "stop-search", G_CALLBACK(hide_search), w);
    gtk_search_bar_set_show_close_button(GTK_SEARCH_BAR(w->search_bar), TRUE);
    g_signal_connect(w->search_entry, "search-changed", G_CALLBACK(on_search_changed), w);
    g_signal_connect(w->search_entry, "activate", G_CALLBACK(on_search_activate), w);
    g_signal_connect(w->search_entry, "key-press-event", G_CALLBACK(on_search_key), w);
    g_signal_connect(up, "clicked", G_CALLBACK(on_search_prev), w);
    g_signal_connect(down, "clicked", G_CALLBACK(on_search_next), w);
    g_signal_connect(w->search_bar, "notify::search-mode-enabled", G_CALLBACK(on_search_mode), w);
    gtk_box_pack_start(GTK_BOX(vbox), w->search_bar, FALSE, FALSE, 0);

    w->nb = GTK_NOTEBOOK(gtk_notebook_new());
    gtk_notebook_set_show_border(w->nb, FALSE);
    gtk_notebook_set_scrollable(w->nb, TRUE);
    gtk_widget_set_vexpand(GTK_WIDGET(w->nb), TRUE);
    g_signal_connect_after(w->nb, "switch-page", G_CALLBACK(on_switch_page), w);
    g_signal_connect(w->nb, "page-removed", G_CALLBACK(on_page_removed), w);
    gtk_box_pack_start(GTK_BOX(vbox), GTK_WIDGET(w->nb), TRUE, TRUE, 0);
    gtk_container_add(GTK_CONTAINER(w->win), vbox);

    g_signal_connect(w->win, "key-press-event", G_CALLBACK(on_key), w);
    g_signal_connect(w->win, "delete-event", G_CALLBACK(on_delete), w);
    g_signal_connect(w->win, "destroy", G_CALLBACK(on_win_destroy), w);
    g_object_weak_ref(G_OBJECT(w->win), win_free, w);
    g_signal_connect(w->win, "focus-in-event", G_CALLBACK(on_focus_in), w);
    windows = g_list_prepend(windows, w);

    new_tab(w, s);
    gtk_widget_show_all(vbox);
    gtk_widget_show_all(GTK_WIDGET(w->header));
    update_title(w);
    return w;
}

/* zmena systemoveho vzhledu (svetly/tmavy) -> prebarvit vsechny terminaly */
static void on_theme_changed(GObject *o, GParamSpec *ps, gpointer d)
{
    for (GList *l = windows; l; l = l->next) {
        Win *w = l->data;
        for (int p = 0; p < gtk_notebook_get_n_pages(w->nb); p++)
            apply_colors(tab_of(gtk_notebook_get_nth_page(w->nb, p))->term);
    }
}

/* ---------- prikazova radka ---------- */
typedef struct {
    Spawn s;
    gboolean tab, maximize, fullscreen, help, version, bad;
    int cols, rows;
} Opts;

static gboolean opt_value(char **argv, int *i, const char *s, const char *l, char **out)
{
    const char *a = argv[*i];
    size_t ll = l ? strlen(l) : 0;
    if (l && !strncmp(a, l, ll) && a[ll] == '=') { *out = g_strdup(a + ll + 1); return TRUE; }
    if ((s && !strcmp(a, s)) || (l && !strcmp(a, l))) {
        if (argv[*i + 1]) { *out = g_strdup(argv[++*i]); return TRUE; }
        *out = NULL;
        return TRUE;
    }
    if (s && s[2] == 0 && !strncmp(a, s, 2) && a[2] && a[1] != '-') { *out = g_strdup(a + 2); return TRUE; }
    return FALSE;
}

static void parse_args(char **argv, Opts *o)
{
    char *v;
    for (int i = 1; argv[i]; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-x") || !strcmp(a, "--execute") || !strcmp(a, "--")) {
            if (argv[i + 1]) { g_strfreev(o->s.argv); o->s.argv = g_strdupv(argv + i + 1); }
            return;
        }
        if (opt_value(argv, &i, "-e", "--command", &v)) {
            g_strfreev(o->s.argv);
            o->s.argv = NULL;
            if (v && !g_shell_parse_argv(v, NULL, &o->s.argv, NULL)) o->bad = TRUE;
            g_free(v);
        } else if (opt_value(argv, &i, "-T", "--title", &v)) {
            g_free(o->s.title); o->s.title = v;
        } else if (opt_value(argv, &i, "-w", "--working-directory", &v) ||
                   opt_value(argv, &i, NULL, "--default-working-directory", &v)) {
            g_free(o->s.cwd); o->s.cwd = v;
        } else if (opt_value(argv, &i, NULL, "--geometry", &v)) {
            int c, r;
            if (v && sscanf(v, "%dx%d", &c, &r) == 2) { o->cols = c; o->rows = r; }
            g_free(v);
        } else if (!strcmp(a, "-H") || !strcmp(a, "--hold")) o->s.hold = TRUE;
        else if (!strcmp(a, "--tab")) o->tab = TRUE;
        else if (!strcmp(a, "--window")) o->tab = FALSE;
        else if (!strcmp(a, "--maximize")) o->maximize = TRUE;
        else if (!strcmp(a, "--fullscreen")) o->fullscreen = TRUE;
        else if (!strcmp(a, "-h") || !strcmp(a, "--help")) o->help = TRUE;
        else if (!strcmp(a, "-V") || !strcmp(a, "--version")) o->version = TRUE;
        else if (!strcmp(a, "--disable-server") || !strcmp(a, "--new-process") || !strcmp(a, "--drop-down") ||
                 !strncmp(a, "--display", 9) || !strncmp(a, "--role", 6) || !strncmp(a, "--startup-id", 12)) ;
        else if (a[0] != '-' && !o->s.cwd && g_file_test(a, G_FILE_TEST_IS_DIR)) o->s.cwd = g_strdup(a);
        else { g_printerr("luxos-terminal: unknown option %s\n", a); o->bad = TRUE; }
    }
}

static const char usage[] =
    "Usage: luxos-terminal [OPTION...] [-x COMMAND [ARG...]]\n"
    "  -x, --execute CMD ARG...      run the rest of the command line in the terminal\n"
    "  -e, --command \"CMD\"           run a command (one string)\n"
    "  -w, --working-directory DIR   start in DIR\n"
    "  -T, --title TITLE             fixed tab title\n"
    "  -H, --hold                    keep the tab open after the command exits\n"
    "      --tab                     open a tab in the last window\n"
    "      --window                  open a new window (default)\n"
    "      --geometry COLSxROWS      window size in characters\n"
    "      --maximize, --fullscreen\n"
    "      --disable-server          separate process (no reuse of a running terminal)\n"
    "  -V, --version\n";

static int on_command_line(GApplication *ga, GApplicationCommandLine *cl, gpointer d)
{
    int argc;
    char **argv = g_application_command_line_get_arguments(cl, &argc);
    Opts o = {0};
    parse_args(argv, &o);
    g_strfreev(argv);
    if (o.bad) {
        g_application_command_line_printerr(cl, "%s", usage);
        spawn_free(&o.s);
        return 1;
    }
    const char *ccwd = g_application_command_line_get_cwd(cl);
    if (!o.s.cwd && ccwd) o.s.cwd = g_strdup(ccwd);
    else if (o.s.cwd && !g_path_is_absolute(o.s.cwd) && ccwd) {
        char *p = g_build_filename(ccwd, o.s.cwd, NULL);
        g_free(o.s.cwd);
        o.s.cwd = p;
    }
    const char * const *env = g_application_command_line_get_environ(cl);
    if (env && *env) o.s.env = g_strdupv((char **)env);
    int oc = cfg.columns, orows = cfg.rows;
    if (o.cols >= 10 && o.rows >= 3) { cfg.columns = o.cols; cfg.rows = o.rows; }

    Win *w = NULL;
    if (o.tab && windows) {
        /* posledni pouzite okno */
        GList *ws = gtk_application_get_windows(app);
        for (GList *l = windows; l; l = l->next)
            if (ws && ((Win *)l->data)->win == ws->data) w = l->data;
        if (!w) w = windows->data;
        new_tab(w, &o.s);
    } else {
        w = new_window(&o.s);
        if (o.maximize) gtk_window_maximize(w->win);
        if (o.fullscreen) gtk_window_fullscreen(w->win);
    }
    cfg.columns = oc;
    cfg.rows = orows;
    const char *sid = env ? g_environ_getenv((char **)env, "DESKTOP_STARTUP_ID") : NULL;
    if (sid) gtk_window_set_startup_id(w->win, sid);
    gtk_window_present(w->win);
    spawn_free(&o.s);
    return 0;
}

static void on_startup(GApplication *ga, gpointer d)
{
    load_config();
    sixel_available = (vte_get_feature_flags() & VTE_FEATURE_FLAG_SIXEL) != 0;
    url_regex = vte_regex_new_for_match(
        "(?:(?:https?|ftp|sftp|file|ssh)://|www\\.|mailto:)[^\\s<>\"'`{}|\\\\^]*[^\\s<>\"'`{}|\\\\^.,;:!?)\\]]"
        "|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}",
        -1, PCRE2_MULTILINE | PCRE2_CASELESS, NULL);
    if (!url_regex) g_warning("URL regex failed");
    GtkCssProvider *css = gtk_css_provider_new();
    gtk_css_provider_load_from_data(css,
        "window.luxos-terminal.background, window.luxos-terminal notebook,"
        " window.luxos-terminal notebook > stack, window.luxos-terminal scrolledwindow { background-color: transparent; }"
        " window.luxos-terminal vte-terminal { padding: 4px 8px; }"
        " window.luxos-terminal notebook > header { padding: 0; }"
        " window.luxos-terminal notebook > header tab { padding: 2px 6px; min-height: 0; }"
        " window.luxos-terminal notebook > header tab button { padding: 0; min-height: 16px; min-width: 16px; }",
        -1, NULL);
    gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(css),
                                              /* nad vlastnim stylem VTE (padding 1px) */
                                              GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
    g_object_unref(css);
    GtkSettings *s = gtk_settings_get_default();
    g_signal_connect(s, "notify::gtk-theme-name", G_CALLBACK(on_theme_changed), NULL);
    g_signal_connect(s, "notify::gtk-application-prefer-dark-theme", G_CALLBACK(on_theme_changed), NULL);
}

int main(int argc, char **argv)
{
    setlocale(LC_ALL, "");
    gboolean unique = TRUE;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-x") || !strcmp(argv[i], "--execute") || !strcmp(argv[i], "--")) break;
        if (!strcmp(argv[i], "--disable-server") || !strcmp(argv[i], "--new-process")) unique = FALSE;
        if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) { fputs(usage, stdout); return 0; }
        /* --logo-sixel SIRKAxVYSKA [dark|light]: logo pro danou velikost znaku (testy, ladeni) */
        if (!strcmp(argv[i], "--logo-sixel") && argv[i + 1]) {
            long cw = 0, ch = 0;
            char *path = NULL, *data = NULL;
            gsize len = 0;
            if (sscanf(argv[i + 1], "%ldx%ld", &cw, &ch) == 2 &&
                (path = logo_render(cw, ch, !(argv[i + 2] && !strcmp(argv[i + 2], "light")))) &&
                g_file_get_contents(path, &data, &len, NULL)) {
                fwrite(data, 1, len, stdout);
                printf("\n%s\n", path);
                return 0;
            }
            g_printerr("luxos-terminal: cannot render the logo\n");
            return 1;
        }
        if (!strcmp(argv[i], "-V") || !strcmp(argv[i], "--version")) {
            printf("luxos-terminal %s (VTE %d.%d.%d%s)\n", LUXOS_TERMINAL_VERSION, vte_get_major_version(),
                   vte_get_minor_version(), vte_get_micro_version(),
                   vte_get_feature_flags() & VTE_FEATURE_FLAG_SIXEL ? ", SIXEL" : "");
            return 0;
        }
    }
    g_set_prgname("luxos-terminal");
    /* LUXOS_TERMINAL_NEW_PROCESS=1: testy a mereni bez sdileni procesu */
    if (g_getenv("LUXOS_TERMINAL_NEW_PROCESS")) unique = FALSE;
    app = gtk_application_new(APP_ID, G_APPLICATION_HANDLES_COMMAND_LINE | G_APPLICATION_SEND_ENVIRONMENT |
                                          (unique ? 0 : G_APPLICATION_NON_UNIQUE));
    g_signal_connect(app, "startup", G_CALLBACK(on_startup), NULL);
    g_signal_connect(app, "command-line", G_CALLBACK(on_command_line), NULL);
    int r = g_application_run(G_APPLICATION(app), argc, argv);
    g_object_unref(app);
    return r;
}
