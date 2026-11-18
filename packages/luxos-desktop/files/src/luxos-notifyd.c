/*
 * LuxOS - GTK modul pro xfce4-notifyd: historie oznameni synchronizovana s aplikacemi jako v Androidu.
 *
 *   - Aplikace oznameni zavre (CloseNotification - napr. Posta po precteni zpravy, Kalendar po
 *     odbyte udalosti) -> zaznam zmizi i z historie (zvonek v liste), ne jen "precteny".
 *   - Klik na zaznam v okne Oznameni (luxos_bar_popups.lsl) vola metodu Activate tohoto modulu:
 *     dokud aplikace bezi a oznameni ma vychozi akci, dostane ActionInvoked(id, "default") jako
 *     pri kliknuti na bublinu (Posta otevre konkretni zpravu) a oznameni se zavre (a z historie zmizi).
 *     Jinak Activate vrati false a okno Oznameni otevre aplikaci podle desktop-entry.
 *
 * xfce4-notifyd 0.9.7 v historii neuklada cislo oznameni, proto modul sleduje zpravy D-Bus sveho
 * procesu (g_dbus_connection_add_filter na sdilenem spojeni sezeni): prichozi Notify s hintem
 * x-luxos-keep (jen ta jdou do historie LuxOS), odchozi odpoved s cislem oznameni a signal RowAdded
 * (novy zaznam historie - xfce4-notifyd ho posle az po odpovedi; zaznam patri nejstarsimu oznameni,
 * ktere na nej ceka, nejdele 2 s). Tak vznikne dvojice cislo oznameni -> zaznamy historie. Po restartu xfce4-notifyd dvojice
 * nezname: Activate vrati false (okno otevre aplikaci), zavreni aplikaci zaznam nesmaze.
 *
 * API pro aplikace a okna LuxOS (viz docs/developers/notifications.md):
 *   jmeno org.freedesktop.Notifications, objekt /cz/luxos/NotificationHistory,
 *   rozhrani cz.luxos.NotificationHistory, metoda Activate(s log_id) -> (b handled)
 *
 * Nacita se pres GTK_MODULES (systemd drop-in xfce4-notifyd-luxos-glass.conf) jen v xfce4-notifyd.
 */
#include <gtk/gtk.h>
#include <gio/gio.h>
#include <string.h>

#define FDO_IFACE "org.freedesktop.Notifications"
#define FDO_PATH "/org/freedesktop/Notifications"
#define LOG_IFACE "org.xfce.Notifyd.Log"
#define HISTORY_PATH "/cz/luxos/NotificationHistory"
#define HISTORY_IFACE "cz.luxos.NotificationHistory"

typedef struct {
    guint32 serial;     /* prichozi Notify (cislo zpravy) */
    gchar *sender;
    gboolean has_default;
    guint32 id;         /* cislo oznameni z odpovedi, 0 = jeste bez odpovedi */
    gint64 replied;     /* kdy prisla odpoved (monotonni cas) */
    gchar *log_id;      /* RowAdded pred odpovedi (jine verze xfce4-notifyd) */
} Pending;

#define ROW_WAIT_US (2 * G_USEC_PER_SEC)

typedef struct {
    gchar *sender;
    gboolean has_default;
    gboolean gone;      /* zavrel uzivatel nebo aplikace (duvod 2, 3): akce uz nema komu */
    GPtrArray *log_ids;
} Note;

static struct {
    GDBusConnection *conn;
    GMutex lock;
    GQueue pending;     /* Pending*, nejstarsi prvni */
    GHashTable *notes;  /* id oznameni -> Note* */
} S;

static void pending_free(Pending *p)
{
    g_free(p->sender);
    g_free(p->log_id);
    g_free(p);
}

static void note_free(gpointer data)
{
    Note *n = data;
    g_free(n->sender);
    g_ptr_array_unref(n->log_ids);
    g_free(n);
}

/* Pro testy (tests/test_luxos_notifyd_sync.py): LUXOS_NOTIFYD_TEST_LOG */
static void test_log(const char *fmt, ...)
{
    const char *path = g_getenv("LUXOS_NOTIFYD_TEST_LOG");
    va_list ap;
    gchar *line;
    FILE *f;
    if (!path || !*path)
        return;
    va_start(ap, fmt);
    line = g_strdup_vprintf(fmt, ap);
    va_end(ap);
    f = fopen(path, "a");
    if (f) {
        fprintf(f, "%s\n", line);
        fclose(f);
    }
    g_free(line);
}

/* ---- v hlavnim vlakne -------------------------------------------------------------------- */

typedef struct {
    gchar **ids;
} DeleteJob;

static gboolean delete_rows(gpointer data)
{
    DeleteJob *job = data;
    if (job->ids && job->ids[0]) {
        g_dbus_connection_call(S.conn, "org.xfce.Notifyd", "/org/xfce/Notifyd", LOG_IFACE, "Delete",
                               g_variant_new("(^as)", job->ids), NULL, G_DBUS_CALL_FLAGS_NONE, 3000, NULL, NULL, NULL);
        for (gchar **i = job->ids; *i; i++)
            test_log("deleted %s", *i);
    }
    g_strfreev(job->ids);
    g_free(job);
    return G_SOURCE_REMOVE;
}

/* Aplikace (nebo Activate) zavrela oznameni: jeho zaznamy z historie pryc. Vola se z vlakna filtru. */
static void forget_note(guint32 id)
{
    Note *n;
    DeleteJob *job;
    g_mutex_lock(&S.lock);
    n = g_hash_table_lookup(S.notes, GUINT_TO_POINTER(id));
    if (!n) {
        g_mutex_unlock(&S.lock);
        return;
    }
    job = g_new0(DeleteJob, 1);
    job->ids = g_new0(gchar *, n->log_ids->len + 1);
    for (guint i = 0; i < n->log_ids->len; i++)
        job->ids[i] = g_strdup(g_ptr_array_index(n->log_ids, i));
    g_hash_table_remove(S.notes, GUINT_TO_POINTER(id));
    g_mutex_unlock(&S.lock);
    g_main_context_invoke(NULL, delete_rows, job);
}

/* ---- filtr zprav (vlakno GDBus) ---------------------------------------------------------- */

/* Oznameni id ma zaznam log_id (zamceno) */
static void map_row(Pending *p, guint32 id, const gchar *log_id)
{
    Note *n = g_hash_table_lookup(S.notes, GUINT_TO_POINTER(id));
    if (!n) {
        n = g_new0(Note, 1);
        n->log_ids = g_ptr_array_new_with_free_func(g_free);
        g_hash_table_insert(S.notes, GUINT_TO_POINTER(id), n);
    }
    /* nahrazeni stejnym id: novy zaznam (stary smaze xfce4-notifyd), akce podle posledniho */
    g_free(n->sender);
    n->sender = g_strdup(p->sender);
    n->has_default = p->has_default;
    n->gone = FALSE;
    g_ptr_array_add(n->log_ids, g_strdup(log_id));
    test_log("map %u %s", id, log_id);
}

/* Hint x-luxos-keep (b/y/i jako v luxos-log-kept-only.patch) a bez transient */
static gboolean kept_in_history(GVariant *hints)
{
    gboolean keep = FALSE, transient = FALSE;
    GVariantIter it;
    const gchar *key;
    GVariant *value;
    g_variant_iter_init(&it, hints);
    while (g_variant_iter_next(&it, "{&sv}", &key, &value)) {
        gboolean on = FALSE;
        if (g_variant_is_of_type(value, G_VARIANT_TYPE_BOOLEAN))
            on = g_variant_get_boolean(value);
        else if (g_variant_is_of_type(value, G_VARIANT_TYPE_BYTE))
            on = g_variant_get_byte(value) != 0;
        else if (g_variant_is_of_type(value, G_VARIANT_TYPE_INT32))
            on = g_variant_get_int32(value) != 0;
        if (strcmp(key, "x-luxos-keep") == 0)
            keep = on;
        else if (strcmp(key, "transient") == 0)
            transient = on;
        g_variant_unref(value);
    }
    return keep && !transient;
}

static void on_incoming(GDBusMessage *m)
{
    const gchar *member = g_dbus_message_get_member(m);
    GVariant *body = g_dbus_message_get_body(m);
    if (g_strcmp0(g_dbus_message_get_interface(m), FDO_IFACE) != 0 || !member || !body)
        return;
    if (strcmp(member, "Notify") == 0 && g_variant_is_of_type(body, G_VARIANT_TYPE("(susssasa{sv}i)"))) {
        Pending *p;
        GVariant *actions, *hints = g_variant_get_child_value(body, 6);
        gsize n;
        gboolean keep = kept_in_history(hints);
        g_variant_unref(hints);
        if (!keep)
            return;                     /* do historie nepatri */
        p = g_new0(Pending, 1);
        actions = g_variant_get_child_value(body, 5);
        n = g_variant_n_children(actions);
        for (gsize i = 0; i < n; i += 2) {
            GVariant *key = g_variant_get_child_value(actions, i);
            if (g_strcmp0(g_variant_get_string(key, NULL), "default") == 0)
                p->has_default = TRUE;
            g_variant_unref(key);
        }
        g_variant_unref(actions);
        p->serial = g_dbus_message_get_serial(m);
        p->sender = g_strdup(g_dbus_message_get_sender(m));
        g_mutex_lock(&S.lock);
        g_queue_push_tail(&S.pending, p);
        g_mutex_unlock(&S.lock);
    } else if (strcmp(member, "CloseNotification") == 0 && g_variant_is_of_type(body, G_VARIANT_TYPE("(u)"))) {
        guint32 id;
        g_variant_get(body, "(u)", &id);
        test_log("close %u", id);
        forget_note(id);
    }
}

static void on_outgoing(GDBusMessage *m)
{
    GDBusMessageType type = g_dbus_message_get_message_type(m);
    GVariant *body = g_dbus_message_get_body(m);
    g_mutex_lock(&S.lock);
    if (type == G_DBUS_MESSAGE_TYPE_SIGNAL && g_strcmp0(g_dbus_message_get_interface(m), LOG_IFACE) == 0
        && g_strcmp0(g_dbus_message_get_member(m), "RowAdded") == 0 && body
        && g_variant_is_of_type(body, G_VARIANT_TYPE("(s)"))) {
        gchar *log_id = NULL;
        gint64 now = g_get_monotonic_time();
        gboolean done = FALSE;
        g_variant_get(body, "(s)", &log_id);
        /* zaznam patri nejstarsimu oznameni, ktere uz ma cislo a ceka na zaznam */
        for (GList *l = S.pending.head; l && !done;) {
            Pending *p = l->data;
            GList *next = l->next;
            if (p->id && now - p->replied > ROW_WAIT_US) {
                g_queue_delete_link(&S.pending, l);     /* zaznam neprisel (historie vypnuta apod.) */
                pending_free(p);
            } else if (p->id) {
                map_row(p, p->id, log_id);
                g_queue_delete_link(&S.pending, l);
                pending_free(p);
                done = TRUE;
            }
            l = next;
        }
        /* jina verze: RowAdded jeste pred odpovedi */
        for (GList *l = S.pending.head; l && !done; l = l->next) {
            Pending *p = l->data;
            if (!p->id && !p->log_id) {
                p->log_id = g_strdup(log_id);
                done = TRUE;
            }
        }
        g_free(log_id);
    } else if (type == G_DBUS_MESSAGE_TYPE_METHOD_RETURN) {
        guint32 reply = g_dbus_message_get_reply_serial(m);
        for (GList *l = S.pending.head; l; l = l->next) {
            Pending *p = l->data;
            if (p->serial != reply || p->id)
                continue;
            if (!body || !g_variant_is_of_type(body, G_VARIANT_TYPE("(u)"))) {
                g_queue_delete_link(&S.pending, l);
                pending_free(p);
                break;
            }
            g_variant_get(body, "(u)", &p->id);
            p->replied = g_get_monotonic_time();
            if (p->log_id) {
                map_row(p, p->id, p->log_id);
                g_queue_delete_link(&S.pending, l);
                pending_free(p);
            }
            break;
        }
    } else if (type == G_DBUS_MESSAGE_TYPE_SIGNAL && g_strcmp0(g_dbus_message_get_interface(m), FDO_IFACE) == 0
               && g_strcmp0(g_dbus_message_get_member(m), "NotificationClosed") == 0 && body
               && g_variant_is_of_type(body, G_VARIANT_TYPE("(uu)"))) {
        guint32 id, reason;
        Note *n;
        g_variant_get(body, "(uu)", &id, &reason);
        n = g_hash_table_lookup(S.notes, GUINT_TO_POINTER(id));
        /* 2 = zavrel uzivatel, 3 = aplikace: aplikace na oznameni zapomnela (Posta), akce by nic neudelala */
        if (n && (reason == 2 || reason == 3))
            n->gone = TRUE;
    }
    g_mutex_unlock(&S.lock);
}

static GDBusMessage *filter(GDBusConnection *conn, GDBusMessage *m, gboolean incoming, gpointer data)
{
    (void)conn; (void)data;
    if (incoming && g_dbus_message_get_message_type(m) == G_DBUS_MESSAGE_TYPE_METHOD_CALL)
        on_incoming(m);
    else if (!incoming)
        on_outgoing(m);
    return m;
}

/* ---- cz.luxos.NotificationHistory --------------------------------------------------------- */

static const gchar HISTORY_XML[] =
    "<node><interface name='" HISTORY_IFACE "'>"
    "<method name='Activate'><arg type='s' name='log_id' direction='in'/>"
    "<arg type='b' name='handled' direction='out'/></method>"
    "</interface></node>";

static gboolean sender_alive(const gchar *name)
{
    GVariant *r = g_dbus_connection_call_sync(S.conn, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                              "org.freedesktop.DBus", "NameHasOwner", g_variant_new("(s)", name),
                                              G_VARIANT_TYPE("(b)"), G_DBUS_CALL_FLAGS_NONE, 1000, NULL, NULL);
    gboolean alive = FALSE;
    if (r) {
        g_variant_get(r, "(b)", &alive);
        g_variant_unref(r);
    }
    return alive;
}

static void on_history_call(GDBusConnection *conn, const gchar *sender, const gchar *path, const gchar *iface,
                            const gchar *method, GVariant *params, GDBusMethodInvocation *inv, gpointer data)
{
    const gchar *log_id = NULL;
    guint32 found = 0;
    gchar *target = NULL;
    GHashTableIter it;
    gpointer key, value;
    (void)conn; (void)sender; (void)path; (void)iface; (void)data;
    if (g_strcmp0(method, "Activate") != 0) {
        g_dbus_method_invocation_return_dbus_error(inv, "org.freedesktop.DBus.Error.UnknownMethod", method);
        return;
    }
    g_variant_get(params, "(&s)", &log_id);
    g_mutex_lock(&S.lock);
    g_hash_table_iter_init(&it, S.notes);
    while (g_hash_table_iter_next(&it, &key, &value)) {
        Note *n = value;
        for (guint i = 0; i < n->log_ids->len; i++)
            if (strcmp(g_ptr_array_index(n->log_ids, i), log_id) == 0 && n->has_default && !n->gone) {
                found = GPOINTER_TO_UINT(key);
                target = g_strdup(n->sender);
            }
    }
    g_mutex_unlock(&S.lock);
    if (found && target && sender_alive(target)) {
        /* jako klik na bublinu: vychozi akce aplikaci, pak zavrit (z historie zmizi pres filtr) */
        g_dbus_connection_emit_signal(S.conn, NULL, FDO_PATH, FDO_IFACE, "ActionInvoked",
                                      g_variant_new("(us)", found, "default"), NULL);
        g_dbus_connection_call(S.conn, FDO_IFACE, FDO_PATH, FDO_IFACE, "CloseNotification",
                               g_variant_new("(u)", found), NULL, G_DBUS_CALL_FLAGS_NONE, 3000, NULL, NULL, NULL);
        test_log("activate %s %u", log_id, found);
        g_dbus_method_invocation_return_value(inv, g_variant_new("(b)", TRUE));
    } else {
        test_log("activate %s none", log_id);
        g_dbus_method_invocation_return_value(inv, g_variant_new("(b)", FALSE));
    }
    g_free(target);
}

static const GDBusInterfaceVTable HISTORY_VTABLE = { on_history_call, NULL, NULL, { 0 } };

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    GDBusNodeInfo *info;
    GError *error = NULL;
    (void)argc; (void)argv;
    if (g_strcmp0(g_get_prgname(), "xfce4-notifyd") != 0 || S.conn)
        return;
    /* sdilene spojeni sezeni - totez pouziva xfce4-notifyd */
    S.conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &error);
    if (!S.conn) {
        g_warning("luxos-notifyd: %s", error->message);
        g_clear_error(&error);
        return;
    }
    g_mutex_init(&S.lock);
    g_queue_init(&S.pending);
    S.notes = g_hash_table_new_full(g_direct_hash, g_direct_equal, NULL, note_free);
    g_dbus_connection_add_filter(S.conn, filter, NULL, NULL);
    info = g_dbus_node_info_new_for_xml(HISTORY_XML, NULL);
    if (!g_dbus_connection_register_object(S.conn, HISTORY_PATH, info->interfaces[0], &HISTORY_VTABLE, NULL, NULL,
                                           &error)) {
        g_warning("luxos-notifyd: %s", error->message);
        g_clear_error(&error);
    }
    g_dbus_node_info_unref(info);
}
