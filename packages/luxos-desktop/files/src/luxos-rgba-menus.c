/*
 * LuxOS - GTK modul pro prihlasovaci obrazovku: vyskakovacim oknum (nabidky)
 * nastavi RGBA visual, aby se uplatnily pruhlednost a zaoblene rohy z luxos.css.
 * GTK 3 nabidky samo RGBA nedostanou a X server rohy vyplni cernou.
 * Nacita se pres GTK_MODULES=luxos-rgba-menus (greeter-wrapper LightDM).
 */
#include <gtk/gtk.h>

static void make_rgba(GtkWidget *win)
{
    GdkScreen *screen;
    GdkVisual *rgba;
    if (!GTK_IS_WINDOW(win) || gtk_widget_get_realized(win) ||
        gtk_window_get_window_type(GTK_WINDOW(win)) != GTK_WINDOW_POPUP)
        return;
    screen = gtk_widget_get_screen(win);
    rgba = gdk_screen_get_rgba_visual(screen);
    if (rgba && gdk_screen_is_composited(screen))
        gtk_widget_set_visual(win, rgba);
}

/* "parent-set": nabidka se vklada do sveho vyskakovaciho okna uz pri vytvoreni,
   tedy davno pred jeho realizaci (pozdeji uz visual zmenit nejde) */
static gboolean on_parent_set(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GtkWidget *w = g_value_get_object(&params[0]);
    GtkWidget *parent = w ? gtk_widget_get_parent(w) : NULL;
    (void)hint; (void)n; (void)data;
    if (parent)
        make_rgba(parent);
    return TRUE;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    (void)argc; (void)argv;
    /* Signaly GtkWidget existuji az po inicializaci tridy */
    g_type_class_ref(GTK_TYPE_WIDGET);
    g_signal_add_emission_hook(g_signal_lookup("parent-set", GTK_TYPE_WIDGET), 0, on_parent_set, NULL, NULL);
}
