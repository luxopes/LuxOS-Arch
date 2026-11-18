/*
 * LuxOS - rozlozeni klavesnice v horni liste jako text velkymi pismeny (US, CZ, DE...).
 *
 * Nahrazuje plugin xkb z Xfce (umi jen vlajku nebo kod malymi pismeny). Rozlozeni bere z vlastnosti
 * _XKB_RULES_NAMES korenoveho okna (stejne jako setxkbmap -query), aktualni skupinu a Caps Lock
 * z udalosti XKB - zmena (klavesova zkratka, klik, setxkbmap) se ukaze hned, bez dotazovani.
 * Vzhled jako v macOS: kod v tenkem zaoblenem ramecku barvou pisma listy (bile/tmave podle listy).
 * Klik = dalsi rozlozeni; zapnuty Caps Lock = vyplneny odznak; tooltip = cely nazev rozlozeni;
 * prave tlacitko "Nastaveni klavesnice" = aplikace Rozlozeni klavesnice (luxos-keyboard) jako u xkb.
 *
 *   gcc -shared -fPIC -o libluxos-xkb.so luxos-xkb.c \
 *       $(pkg-config --cflags --libs libxfce4panel-2.0 gtk+-3.0 x11)
 */
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <libxfce4panel/libxfce4panel.h>
#include <X11/XKBlib.h>
#include <X11/Xatom.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *button;
    GtkWidget *label;
    Display *dpy;
    int xkb_event;
    gchar **codes;      /* "US", "CZ" ... podle poradi skupin */
    gint n;
    gint group;
    gboolean caps;
    gint log_x, log_y;  /* posledni zapsana poloha (testovaci zaznam) */
} Kb;

/* Kody rozlozeni z _XKB_RULES_NAMES: rules\0model\0layout\0variant\0options\0, layout "us,cz" */
static void
load_layouts (Kb *kb) {
    Atom names = XInternAtom (kb->dpy, "_XKB_RULES_NAMES", True);
    Atom type = None;
    int format = 0;
    unsigned long count = 0, after = 0;
    unsigned char *data = NULL;
    g_strfreev (kb->codes);
    kb->codes = NULL;
    kb->n = 0;
    if (names != None
        && XGetWindowProperty (kb->dpy, DefaultRootWindow (kb->dpy), names, 0, 1024, False, XA_STRING, &type,
                               &format, &count, &after, &data) == Success && data && format == 8) {
        /* treti retezec = layout */
        unsigned long pos = 0;
        for (int field = 0; field < 2 && pos < count; field++)
            pos += strnlen ((const char *) data + pos, count - pos) + 1;
        if (pos < count) {
            gchar *layout = g_strndup ((const char *) data + pos, count - pos);
            gchar **parts = g_strsplit (layout, ",", -1);
            gint len = (gint) g_strv_length (parts);
            kb->codes = g_new0 (gchar *, len + 1);
            for (gint i = 0; i < len; i++) {
                gchar *code = g_strstrip (parts[i]);
                gchar *paren = strchr (code, '(');
                if (paren)
                    *paren = '\0';
                if (*code)
                    kb->codes[kb->n++] = g_ascii_strup (code, -1);
            }
            g_strfreev (parts);
            g_free (layout);
        }
    }
    if (data)
        XFree (data);
}

/* Cely nazev skupiny z XKB ("Czech", "English (US)") pro tooltip */
static gchar *
group_name (Kb *kb, gint group) {
    XkbDescPtr desc = XkbAllocKeyboard ();
    gchar *name = NULL;
    if (!desc)
        return NULL;
    if (XkbGetNames (kb->dpy, XkbGroupNamesMask, desc) == Success && desc->names
        && group >= 0 && group < XkbNumKbdGroups && desc->names->groups[group] != None) {
        char *atom = XGetAtomName (kb->dpy, desc->names->groups[group]);
        if (atom) {
            name = g_strdup (atom);
            XFree (atom);
        }
    }
    XkbFreeKeyboard (desc, 0, True);
    return name;
}

/* Testy (tests/test_luxos_xkb_plugin.py, LUXOS_XKB_TEST_LOG): co lista ukazuje a kde je tlacitko */
static void
test_log (Kb *kb) {
    const gchar *log = g_getenv ("LUXOS_XKB_TEST_LOG");
    if (!log || !*log)
        return;
    const gchar *code = kb->group >= 0 && kb->group < kb->n ? kb->codes[kb->group] : NULL;
    gint x = -1, y = -1;
    GdkWindow *w = gtk_widget_get_window (kb->button);
    GtkAllocation a;
    gtk_widget_get_allocation (kb->button, &a);
    if (w && gtk_widget_get_mapped (kb->button)) {
        gdk_window_get_origin (w, &x, &y);
        x += a.x + a.width / 2;
        y += a.y + a.height / 2;
    }
    kb->log_x = x;
    kb->log_y = y;
    FILE *f = fopen (log, "a");
    if (f) {
        fprintf (f, "label %s caps %d visible %d n %d pos %d %d\n", code ? code : "?", kb->caps ? 1 : 0,
                 gtk_widget_get_visible (GTK_WIDGET (kb->plugin)) ? 1 : 0, kb->n, x, y);
        fclose (f);
    }
}

/* Po rozmisteni v liste: poloha pro testovaci zaznam, jen kdyz se zmenila */
static void
on_allocated (GtkWidget *widget, GdkRectangle *allocation, Kb *kb) {
    GdkWindow *w = gtk_widget_get_window (widget);
    if (!g_getenv ("LUXOS_XKB_TEST_LOG") || !w || !gtk_widget_get_mapped (widget))
        return;
    gint x, y;
    gdk_window_get_origin (w, &x, &y);
    x += allocation->x + allocation->width / 2;
    y += allocation->y + allocation->height / 2;
    if (x != kb->log_x || y != kb->log_y)
        test_log (kb);
}

static void
update_label (Kb *kb) {
    const gchar *code = kb->group >= 0 && kb->group < kb->n ? kb->codes[kb->group] : NULL;
    gtk_label_set_text (GTK_LABEL (kb->label), code ? code : "?");
    GtkStyleContext *ctx = gtk_widget_get_style_context (kb->label);
    if (kb->caps)
        gtk_style_context_add_class (ctx, "caps");
    else
        gtk_style_context_remove_class (ctx, "caps");
    gchar *name = group_name (kb, kb->group);
    gchar *tip = kb->caps ? g_strdup_printf ("%s – Caps Lock", name ? name : (code ? code : ""))
                          : g_strdup (name ? name : (code ? code : ""));
    gtk_widget_set_tooltip_text (kb->button, tip);
    g_free (tip);
    g_free (name);
    /* jedno rozlozeni: neni co prepinat ani ukazovat */
    gtk_widget_set_visible (GTK_WIDGET (kb->plugin), kb->n > 1 || kb->caps);
    test_log (kb);
}

static void
read_state (Kb *kb) {
    XkbStateRec st;
    if (XkbGetState (kb->dpy, XkbUseCoreKbd, &st) == Success) {
        kb->group = st.group;
        kb->caps = (st.locked_mods & LockMask) != 0;
    }
}

static GdkFilterReturn
xkb_filter (GdkXEvent *xevent, GdkEvent *event, gpointer data) {
    Kb *kb = data;
    XEvent *xe = xevent;
    (void) event;
    if (xe->type != kb->xkb_event)
        return GDK_FILTER_CONTINUE;
    XkbEvent *ke = (XkbEvent *) xe;
    if (ke->any.xkb_type == XkbStateNotify) {
        kb->group = ke->state.group;
        kb->caps = (ke->state.locked_mods & LockMask) != 0;
        update_label (kb);
    } else if (ke->any.xkb_type == XkbNewKeyboardNotify || ke->any.xkb_type == XkbNamesNotify) {
        /* setxkbmap / Nastaveni klavesnice: jina rozlozeni */
        load_layouts (kb);
        read_state (kb);
        update_label (kb);
    }
    return GDK_FILTER_CONTINUE;
}

static void
on_clicked (GtkButton *button, Kb *kb) {
    (void) button;
    if (kb->n > 1) {
        XkbLockGroup (kb->dpy, XkbUseCoreKbd, (kb->group + 1) % kb->n);
        XFlush (kb->dpy);
    }
}

static void
on_settings (GtkMenuItem *item, Kb *kb) {
    (void) item;
    (void) kb;
    /* Xfce dialog presmerovava override-bin/xfce4-keyboard-settings; tady primo aplikace LuxOS */
    gchar *argv[] = { "luxos-keyboard", NULL };
    if (!g_spawn_async (NULL, argv, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL, NULL)) {
        gchar *fallback[] = { "xfce4-keyboard-settings", NULL };
        g_spawn_async (NULL, fallback, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL, NULL);
    }
}

static gboolean
on_size_changed (XfcePanelPlugin *plugin, gint size, Kb *kb) {
    (void) kb;
    if (xfce_panel_plugin_get_orientation (plugin) == GTK_ORIENTATION_HORIZONTAL)
        gtk_widget_set_size_request (GTK_WIDGET (plugin), -1, size);
    else
        gtk_widget_set_size_request (GTK_WIDGET (plugin), size, -1);
    return TRUE;
}

static void
on_free (XfcePanelPlugin *plugin, Kb *kb) {
    (void) plugin;
    gdk_window_remove_filter (NULL, xkb_filter, kb);
    g_strfreev (kb->codes);
    g_slice_free (Kb, kb);
}

static void
construct (XfcePanelPlugin *plugin) {
    Kb *kb = g_slice_new0 (Kb);
    int opcode, error, major = XkbMajorVersion, minor = XkbMinorVersion;
    kb->plugin = plugin;
    kb->button = xfce_panel_create_button ();
    kb->label = gtk_label_new (NULL);
    /* odznak: ramecek a pismo barvou textu listy (currentColor), nezabira celou vysku listy */
    static const gchar *css =
        "label.luxos-xkb { font-size: 7.5pt; font-weight: 800; letter-spacing: 0.6px;"
        "  padding: 0 4px 0 5px; min-height: 15px; border-radius: 4px;"
        "  border: 1.5px solid alpha(currentColor, 0.9); }"
        "label.luxos-xkb.caps { background-color: alpha(currentColor, 0.28); }";
    GtkCssProvider *provider = gtk_css_provider_new ();
    gtk_css_provider_load_from_data (provider, css, -1, NULL);
    gtk_style_context_add_provider (gtk_widget_get_style_context (kb->label), GTK_STYLE_PROVIDER (provider),
                                    GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
    g_object_unref (provider);
    gtk_style_context_add_class (gtk_widget_get_style_context (kb->label), "luxos-xkb");
    gtk_widget_set_valign (kb->label, GTK_ALIGN_CENTER);
    gtk_container_add (GTK_CONTAINER (kb->button), kb->label);
    gtk_container_add (GTK_CONTAINER (plugin), kb->button);
    xfce_panel_plugin_add_action_widget (plugin, kb->button);
    gtk_widget_show_all (kb->button);
    g_signal_connect (kb->button, "clicked", G_CALLBACK (on_clicked), kb);
    g_signal_connect (plugin, "size-changed", G_CALLBACK (on_size_changed), kb);
    g_signal_connect (plugin, "free-data", G_CALLBACK (on_free), kb);
    /* preklad z pluginu xkb (zavislost balicku) */
    GtkWidget *item = gtk_menu_item_new_with_label (g_dgettext ("xfce4-xkb-plugin", "Keyboard settings"));
    g_signal_connect (item, "activate", G_CALLBACK (on_settings), kb);
    gtk_widget_show (item);
    xfce_panel_plugin_menu_insert_item (plugin, GTK_MENU_ITEM (item));

    GdkDisplay *display = gdk_display_get_default ();
    if (!GDK_IS_X11_DISPLAY (display)
        || !XkbQueryExtension (GDK_DISPLAY_XDISPLAY (display), &opcode, &kb->xkb_event, &error, &major, &minor)) {
        gtk_label_set_text (GTK_LABEL (kb->label), "?");
        return;
    }
    kb->dpy = GDK_DISPLAY_XDISPLAY (display);
    XkbSelectEventDetails (kb->dpy, XkbUseCoreKbd, XkbStateNotify, XkbAllStateComponentsMask,
                           XkbGroupLockMask | XkbModifierLockMask);
    XkbSelectEventDetails (kb->dpy, XkbUseCoreKbd, XkbNamesNotify, XkbAllNamesMask, XkbGroupNamesMask);
    XkbSelectEvents (kb->dpy, XkbUseCoreKbd, XkbNewKeyboardNotifyMask, XkbNewKeyboardNotifyMask);
    gdk_window_add_filter (NULL, xkb_filter, kb);
    load_layouts (kb);
    read_state (kb);
    update_label (kb);
    g_signal_connect_after (kb->button, "size-allocate", G_CALLBACK (on_allocated), kb);
}

XFCE_PANEL_PLUGIN_REGISTER (construct);
