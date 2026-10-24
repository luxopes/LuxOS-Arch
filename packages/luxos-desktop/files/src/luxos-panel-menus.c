/*
 * LuxOS - GTK modul pro horni listu (xfce4-panel a jeho externi pluginy wrapper-2.0):
 * kontextova nabidka pluginu (prave tlacitko) nezacina sedym nazvem pluginu, na ktery nejde
 * kliknout (napr. "Rozlozeni klavesnice" nad "Nastaveni klavesnice"). Jako v macOS nabidka
 * obsahuje jen akce. Nacita se pres GTK_MODULES z override-bin/xfce4-panel; v jinych
 * programech nedela nic.
 */
#include <gtk/gtk.h>
#include <string.h>

/* Nabidka pluginu (xfce_panel_plugin_menu_get): pripojena k XfcePanelPlugin, prvni polozka
 * je neaktivni nazev pluginu */
static void hide_title(GtkWidget *menu)
{
    static GType plugin_type;
    GtkWidget *attach = gtk_menu_get_attach_widget(GTK_MENU(menu));
    if (!plugin_type)
        plugin_type = g_type_from_name("XfcePanelPlugin");
    if (!attach || !plugin_type || !g_type_is_a(G_OBJECT_TYPE(attach), plugin_type))
        return;
    GList *items = gtk_container_get_children(GTK_CONTAINER(menu));
    GtkWidget *first = items ? items->data : NULL;
    if (first && GTK_IS_MENU_ITEM(first) && !GTK_IS_SEPARATOR_MENU_ITEM(first)
        && !gtk_widget_get_sensitive(first) && !gtk_menu_item_get_submenu(GTK_MENU_ITEM(first)))
        gtk_widget_hide(first);
    g_list_free(items);
}

static gboolean on_show(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GtkWidget *w = g_value_get_object(&params[0]);
    (void)hint; (void)n; (void)data;
    if (GTK_IS_MENU(w))
        hide_title(w);
    return TRUE;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    const char *name = g_get_prgname();
    (void)argc; (void)argv;
    if (!name || (strcmp(name, "xfce4-panel") && strncmp(name, "wrapper-", 8) && strncmp(name, "panel-", 6)))
        return;
    g_type_class_ref(GTK_TYPE_MENU);
    g_signal_add_emission_hook(g_signal_lookup("show", GTK_TYPE_WIDGET), 0, on_show, NULL, NULL);
}
