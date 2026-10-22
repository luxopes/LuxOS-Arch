/*
 * LuxOS - GTK modul pro xfce4-screensaver: cerny pruh dole na zamykaci obrazovce po probuzeni.
 *
 * xfce4-screensaver (4.20.x) po probuzeni z uspani (logind PrepareForSleep=false) vola
 * gs_window_show_message(NULL, NULL, NULL) jen proto, aby si vyzadal dialog s heslem
 * (v kodu "FIXME: there is no signal to request password prompt"). Tim na 30 s ukaze
 * prazdnou informacni listu (GtkInfoBar s textem "(null)") pod oknem dialogu. Dialog
 * (cela obrazovka, vycentrovany) se pak nevejde a posune se o pulku vysky listy nahoru:
 * horni lista zamku (hodiny, nazev pocitace) je skoro cela mimo obrazovku a dole je
 * cerny pruh. Po 30 s lista zmizi a dialog "doskoci" na misto.
 *
 * Modul prazdnou listu hned skryje (pred vykreslenim). Skutecne zpravy (ShowMessage
 * s textem) zustavaji beze zmeny. Mimo xfce4-screensaver nic nedela.
 * Nacita se pres GTK_MODULES=luxos-lock-fix (autostart xfce4-screensaver.desktop LuxOS).
 */
#include <gtk/gtk.h>
#include <string.h>

/* Prvni GtkLabel v listu widgetu (do hloubky) */
static GtkWidget *find_label(GtkWidget *w)
{
    GList *children, *l;
    GtkWidget *found = NULL;
    if (GTK_IS_LABEL(w))
        return w;
    if (!GTK_IS_CONTAINER(w))
        return NULL;
    children = gtk_container_get_children(GTK_CONTAINER(w));
    for (l = children; l && !found; l = l->next)
        found = find_label(l->data);
    g_list_free(children);
    return found;
}

static gboolean hide_empty(gpointer data)
{
    GtkWidget *bar = data;
    GtkWidget *label;
    const char *text;
    if (gtk_widget_get_visible(bar)) {
        label = find_label(gtk_info_bar_get_content_area(GTK_INFO_BAR(bar)));
        text = label ? gtk_label_get_text(GTK_LABEL(label)) : NULL;
        /* "<b>%s</b>" s NULL dava "(null)" */
        if (!text || !*text || !strcmp(text, "(null)"))
            gtk_widget_hide(bar);
    }
    g_object_unref(bar);
    return G_SOURCE_REMOVE;
}

static gboolean on_show(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    GObject *w = g_value_get_object(&params[0]);
    (void)hint; (void)n; (void)data;
    /* "show" se emituje pred zviditelnenim - kontrola az po nem, ale pred
       rozvrzenim a vykreslenim (G_PRIORITY_HIGH_IDLE < GDK_PRIORITY_REDRAW) */
    if (GTK_IS_INFO_BAR(w))
        g_idle_add_full(G_PRIORITY_HIGH_IDLE, hide_empty, g_object_ref(w), NULL);
    return TRUE;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    (void)argc; (void)argv;
    if (g_strcmp0(g_get_prgname(), "xfce4-screensaver") != 0)
        return;
    /* signal "show" existuje az po inicializaci tridy GtkWidget */
    g_type_class_ref(GTK_TYPE_WIDGET);
    g_signal_add_emission_hook(g_signal_lookup("show", GTK_TYPE_WIDGET), 0, on_show, NULL, NULL);
}

G_MODULE_EXPORT const gchar *g_module_check_init(GModule *module)
{
    /* modul zustane nacteny (emission hook ukazuje do jeho kodu) */
    g_module_make_resident(module);
    return NULL;
}
