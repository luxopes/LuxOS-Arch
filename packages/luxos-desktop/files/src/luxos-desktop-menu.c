/*
 * LuxOS - GTK modul pro plochu (xfdesktop): nabidka plochy (prave tlacitko na prazdne plose) ma
 * pod "Nastaveni plochy..." polozku "Upravit widgety..." - galerie widgetu (luxos-widgets settings),
 * jako "Upravit widgety..." v macOS. Drive se ke galerii dalo dostat jen z Launchpadu, hledanim
 * nebo pravym tlacitkem na widgetu (kdyz zadny widget nebyl, nijak).
 *
 * Nacita se pres GTK_MODULES z override-bin/xfdesktop; v jinych programech nedela nic a spoustenym
 * aplikacim se z GTK_MODULES odebere. Nabidka plochy se pozna podle podnabidky Aplikace (GarconGtkMenu)
 * - nabidka ikony ji nema. Bez nainstalovaneho luxos-widgets se polozka neprida.
 * Preklad z /usr/share/luxos/i18n/<jazyk>.tsv (jako luxos_i18n.py; LUXOS_I18N_DIR pro testy).
 */
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>

#define MODULE "luxos-desktop-menu"
#define LABEL "Edit Widgets…"

/* Preklad textu (radek "anglicky<TAB>preklad"); g_free */
static gchar *translate(const gchar *text)
{
    const gchar *lang = g_getenv("LC_ALL");
    if (!lang || !*lang)
        lang = g_getenv("LC_MESSAGES");
    if (!lang || !*lang)
        lang = g_getenv("LANG");
    gchar *code = g_strndup(lang && *lang ? lang : "en", strcspn(lang && *lang ? lang : "en", "_.@"));
    const gchar *dir = g_getenv("LUXOS_I18N_DIR");
    gchar *path = g_strdup_printf("%s/%s.tsv", dir && *dir ? dir : "/usr/share/luxos/i18n", code);
    g_free(code);
    gchar *out = NULL;
    FILE *f = fopen(path, "r");
    g_free(path);
    if (f) {
        char line[1024];
        size_t n = strlen(text);
        while (!out && fgets(line, sizeof line, f)) {
            if (strncmp(line, text, n) == 0 && line[n] == '\t') {
                gchar *v = g_strstrip(line + n + 1);
                if (*v)
                    out = g_strdup(v);
            }
        }
        fclose(f);
    }
    return out ? out : g_strdup(text);
}

static void on_edit(GtkMenuItem *item, gpointer data)
{
    gchar *argv[] = { "luxos-widgets", "settings", NULL };
    (void)item; (void)data;
    g_spawn_async(NULL, argv, NULL, G_SPAWN_SEARCH_PATH | G_SPAWN_STDOUT_TO_DEV_NULL | G_SPAWN_STDERR_TO_DEV_NULL,
                  NULL, NULL, NULL, NULL);
}

/* Poradi polozky s podnabidkou Aplikace (GarconGtkMenu), -1 = neni to nabidka plochy */
static gint apps_index(GList *items)
{
    gint i = 0;
    for (GList *l = items; l; l = l->next, i++) {
        GtkWidget *sub = GTK_IS_MENU_ITEM(l->data) ? gtk_menu_item_get_submenu(l->data) : NULL;
        if (sub && strcmp(G_OBJECT_TYPE_NAME(sub), "GarconGtkMenu") == 0)
            return i;
    }
    return -1;
}

static void add_item(GtkWidget *menu)
{
    if (g_object_get_data(G_OBJECT(menu), MODULE))
        return;
    GList *items = gtk_container_get_children(GTK_CONTAINER(menu));
    gint apps = apps_index(items);
    if (apps >= 0) {
        g_object_set_data(G_OBJECT(menu), MODULE, GINT_TO_POINTER(1));
        /* za "Nastaveni plochy...": pred oddelovac nad Aplikacemi */
        gint at = apps;
        GList *prev = apps > 0 ? g_list_nth(items, apps - 1) : NULL;
        if (prev && GTK_IS_SEPARATOR_MENU_ITEM(prev->data))
            at = apps - 1;
        gchar *label = translate(LABEL);
        GtkWidget *item = gtk_menu_item_new_with_label(label);
        g_free(label);
        g_signal_connect(item, "activate", G_CALLBACK(on_edit), NULL);
        gtk_menu_shell_insert(GTK_MENU_SHELL(menu), item, at);
        gtk_widget_show(item);
    }
    g_list_free(items);
}

static gboolean on_show(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GtkWidget *w = g_value_get_object(&params[0]);
    (void)hint; (void)n; (void)data;
    if (GTK_IS_MENU(w))
        add_item(w);
    return TRUE;
}

/* Spoustene aplikace modul nedostanou (GTK_MODULES bez luxos-desktop-menu) */
static void drop_from_env(void)
{
    const gchar *mods = g_getenv("GTK_MODULES");
    if (!mods)
        return;
    gchar **parts = g_strsplit(mods, ":", -1);
    GString *keep = g_string_new(NULL);
    for (gchar **p = parts; *p; p++) {
        if (!**p || strcmp(*p, MODULE) == 0)
            continue;
        if (keep->len)
            g_string_append_c(keep, ':');
        g_string_append(keep, *p);
    }
    if (keep->len)
        g_setenv("GTK_MODULES", keep->str, TRUE);
    else
        g_unsetenv("GTK_MODULES");
    g_string_free(keep, TRUE);
    g_strfreev(parts);
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    const char *name = g_get_prgname();
    (void)argc; (void)argv;
    drop_from_env();
    if (!name || strcmp(name, "xfdesktop") != 0)
        return;
    gchar *widgets = g_find_program_in_path("luxos-widgets");
    if (!widgets)
        return;
    g_free(widgets);
    g_type_class_ref(GTK_TYPE_MENU);
    g_signal_add_emission_hook(g_signal_lookup("show", GTK_TYPE_WIDGET), 0, on_show, NULL, NULL);
}
