/*
 * LuxOS - GTK 3 modul pro posouvani jako v macOS (nacita ho xsettings Gtk/Modules, tedy kazda aplikace GTK 3):
 *
 *  - Plynule kolecko mysi: v GtkScrolledWindow kolecko neskace o kus stranky, ale dojede tam plynule
 *    (200 ms, ease-out); dalsi zarazky behem animace cil posouvaji dal. Vzdalenost je stejna jako v GTK.
 *    Jen kdyz ScrolledWindow udalost opravdu dostane (vlastni obsluha posunu v aplikaci ma prednost),
 *    jen bez Ctrl/Alt/Super (Ctrl+kolecko = zoom v aplikaci) a jen se zapnutymi animacemi
 *    (Gtk/EnableAnimations - omezeni pohybu a Uspora baterie animaci kolecka vypnou).
 *  - Setrvacnost na touchpadu: xf86-input-libinput po zvednuti prstu posle udalost s nulovym posunem,
 *    GDK z ni udela "stop" a GtkScrolledWindow, Firefox a WebKitGTK podle rychlosti dojedou setrvacnosti.
 *    Modul ji pri vypnute volbe zrusi (stop dorazi az po DEFER_MS, takze rychlost vyjde nulova - i pro
 *    Firefox, ktery cas udalosti v budoucnosti neprijme) a zastavi ji dotykem touchpadu (pohyb kurzoru,
 *    klepnuti/klik), protoze libinput na X11 samotne polozeni prstu neposila.
 *  - Prvni zarazka kolecka po vstupu ukazatele do okna se neztrati (GDK na X11 ji jinak zahodi).
 *
 * Volby: ~/.config/luxos/scrolling.conf, [scrolling] smooth_wheel=true|false, kinetic=true|false
 * (zmena se projevi hned, soubor se sleduje). LUXOS_SCROLL=0 modul v procesu vypne.
 */
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <gmodule.h>
#include <X11/extensions/XInput2.h>
#include <math.h>
#include <string.h>

#define WHEEL_MS 200           /* delka animace kolecka */
#define DEFER_MS 250           /* o kolik se pri vypnute setrvacnosti opozdi "stop" touchpadu */
#define GLIDE_MAX_US (10 * G_USEC_PER_SEC)  /* dele setrvacnost GTK netrva */
#define GLIDE_MOVING_US (80 * 1000)          /* obsah se posunul pred mene nez 80 ms = jeste jede */

static gboolean opt_smooth_wheel = TRUE;
static gboolean opt_kinetic = TRUE;
static GFileMonitor *config_monitor;
static gboolean (*orig_scroll_event)(GtkWidget *, GdkEventScroll *);
static GQuark anim_quark, glide_quark;

/* ---- volby ------------------------------------------------------------------------------------------ */

static gboolean key_bool(GKeyFile *kf, const char *key, gboolean def)
{
    GError *e = NULL;
    gboolean v = g_key_file_get_boolean(kf, "scrolling", key, &e);
    if (e) {
        g_error_free(e);
        return def;
    }
    return v;
}

static void load_config(void)
{
    char *path = g_build_filename(g_get_user_config_dir(), "luxos", "scrolling.conf", NULL);
    GKeyFile *kf = g_key_file_new();
    if (g_key_file_load_from_file(kf, path, G_KEY_FILE_NONE, NULL)) {
        opt_smooth_wheel = key_bool(kf, "smooth_wheel", TRUE);
        opt_kinetic = key_bool(kf, "kinetic", TRUE);
    } else {
        opt_smooth_wheel = opt_kinetic = TRUE;
    }
    g_key_file_free(kf);
    g_free(path);
}

static void on_config_changed(GFileMonitor *m, GFile *f, GFile *other, GFileMonitorEvent ev, gpointer data)
{
    (void)m; (void)f; (void)other; (void)data;
    if (ev == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT || ev == G_FILE_MONITOR_EVENT_CREATED ||
        ev == G_FILE_MONITOR_EVENT_DELETED || ev == G_FILE_MONITOR_EVENT_RENAMED ||
        ev == G_FILE_MONITOR_EVENT_MOVED_IN || ev == G_FILE_MONITOR_EVENT_MOVED_OUT)
        load_config();
}

static void watch_config(void)
{
    char *path = g_build_filename(g_get_user_config_dir(), "luxos", "scrolling.conf", NULL);
    GFile *f = g_file_new_for_path(path);
    /* WATCH_MOVES: luxos-scrolling zapisuje pres docasny soubor a prejmenovani */
    config_monitor = g_file_monitor_file(f, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
    if (config_monitor)
        g_signal_connect(config_monitor, "changed", G_CALLBACK(on_config_changed), NULL);
    g_object_unref(f);
    g_free(path);
}

static gboolean animations_enabled(GtkWidget *w)
{
    gboolean on = TRUE;
    g_object_get(gtk_widget_get_settings(w), "gtk-enable-animations", &on, NULL);
    return on;
}

static GdkInputSource event_source(const GdkEvent *e)
{
    GdkDevice *d = gdk_event_get_source_device(e);
    return d ? gdk_device_get_source(d) : GDK_SOURCE_MOUSE;
}

/* ---- plynule kolecko ------------------------------------------------------------------------------- */

typedef struct {
    GtkAdjustment *adj;
    double from, target, last_set;
    gint64 start;
    gboolean active;
} Axis;

typedef struct {
    GtkWidget *sw;
    Axis ax[2];                /* 0 = vodorovne, 1 = svisle */
    guint tick;
} Anim;

static void axis_stop(Axis *a)
{
    a->active = FALSE;
    g_clear_object(&a->adj);
}

static void anim_stop(Anim *an)
{
    axis_stop(&an->ax[0]);
    axis_stop(&an->ax[1]);
    if (an->tick) {
        gtk_widget_remove_tick_callback(an->sw, an->tick);
        an->tick = 0;
    }
}

static void anim_free(gpointer p)
{
    Anim *an = p;
    axis_stop(&an->ax[0]);
    axis_stop(&an->ax[1]);
    /* tick callback zrusi GTK s widgetem (qdata se uvolnuji pri finalizaci) */
    g_free(an);
}

static void on_unrealize(GtkWidget *sw, gpointer data)
{
    Anim *an = g_object_get_qdata(G_OBJECT(sw), anim_quark);
    (void)data;
    if (an)
        anim_stop(an);
}

static Anim *anim_get(GtkWidget *sw, gboolean create)
{
    Anim *an = g_object_get_qdata(G_OBJECT(sw), anim_quark);
    if (!an && create) {
        an = g_new0(Anim, 1);
        an->sw = sw;
        g_object_set_qdata_full(G_OBJECT(sw), anim_quark, an, anim_free);
        g_signal_connect(sw, "unrealize", G_CALLBACK(on_unrealize), NULL);
    }
    return an;
}

static double ease_out_cubic(double t)
{
    double u = 1.0 - t;
    return 1.0 - u * u * u;
}

static gboolean anim_tick(GtkWidget *sw, GdkFrameClock *clock, gpointer data)
{
    Anim *an = data;
    gint64 now = gdk_frame_clock_get_frame_time(clock);
    gboolean running = FALSE;
    (void)sw;
    for (int i = 0; i < 2; i++) {
        Axis *a = &an->ax[i];
        if (!a->active)
            continue;
        double v = gtk_adjustment_get_value(a->adj);
        /* posunul nekdo jiny (posuvnik, klavesy, aplikace, touchpad): animace konci */
        if (fabs(v - a->last_set) > 0.5) {
            axis_stop(a);
            continue;
        }
        double lower = gtk_adjustment_get_lower(a->adj);
        double maxv = MAX(lower, gtk_adjustment_get_upper(a->adj) - gtk_adjustment_get_page_size(a->adj));
        double t = (double)(now - a->start) / (WHEEL_MS * 1000.0);
        t = CLAMP(t, 0.0, 1.0);
        a->target = CLAMP(a->target, lower, maxv);
        gtk_adjustment_set_value(a->adj, a->from + (a->target - a->from) * ease_out_cubic(t));
        a->last_set = gtk_adjustment_get_value(a->adj);
        if (t >= 1.0)
            axis_stop(a);
        else
            running = TRUE;
    }
    if (!running) {
        an->tick = 0;
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

/* Stejny krok jako GtkScrolledWindow (get_scroll_unit, _gtk_range_get_wheel_delta) */
static double scroll_unit(GtkAdjustment *adj)
{
    double page = gtk_adjustment_get_page_size(adj);
    return MIN(pow(page, 2.0 / 3.0), page / 2.0);
}

/* Muze ScrolledWindow v teto ose posouvat? (may_hscroll/may_vscroll v GTK) */
static GtkAdjustment *axis_adjustment(GtkScrolledWindow *sw, int vertical)
{
    GtkWidget *bar = vertical ? gtk_scrolled_window_get_vscrollbar(sw) : gtk_scrolled_window_get_hscrollbar(sw);
    GtkPolicyType hp, vp;
    gtk_scrolled_window_get_policy(sw, &hp, &vp);
    if (!bar || !(gtk_widget_get_child_visible(bar) || (vertical ? vp : hp) == GTK_POLICY_EXTERNAL))
        return NULL;
    return vertical ? gtk_scrolled_window_get_vadjustment(sw) : gtk_scrolled_window_get_hadjustment(sw);
}

static gboolean is_wheel(GdkEventScroll *e)
{
    GdkInputSource src = event_source((GdkEvent *)e);
    if (gdk_event_get_pointer_emulated((GdkEvent *)e))
        return FALSE;
    if (src == GDK_SOURCE_TOUCHPAD || src == GDK_SOURCE_TOUCHSCREEN || src == GDK_SOURCE_TRACKPOINT)
        return FALSE;
    if (e->direction != GDK_SCROLL_SMOOTH)
        return TRUE;
    if (gdk_event_is_scroll_stop_event((GdkEvent *)e))
        return FALSE;
    return src == GDK_SOURCE_MOUSE;
}

/* Kolecko: vraci TRUE, kdyz udalost obslouzila animace (jinak ji dostane puvodni obsluha GTK) */
static gboolean wheel_scroll(GtkScrolledWindow *sw, GdkEventScroll *e)
{
    GtkWidget *w = GTK_WIDGET(sw);
    double d[2] = {0, 0};      /* posun v jednotkach GTK: vodorovne, svisle */
    gboolean shifted = (e->state & GDK_SHIFT_MASK) != 0;

    if (!opt_smooth_wheel || !gtk_widget_get_mapped(w) || !animations_enabled(w))
        return FALSE;
    if (e->state & (GDK_CONTROL_MASK | GDK_MOD1_MASK | GDK_SUPER_MASK | GDK_HYPER_MASK | GDK_META_MASK))
        return FALSE;
    if (e->direction == GDK_SCROLL_SMOOTH) {
        if (!gdk_event_get_scroll_deltas((GdkEvent *)e, &d[0], &d[1]))
            return FALSE;
        if (shifted) {
            double t = d[0];
            d[0] = d[1];
            d[1] = t;
        }
    } else {
        int vertical = (e->direction == GDK_SCROLL_UP || e->direction == GDK_SCROLL_DOWN) != shifted;
        int neg = (e->direction == GDK_SCROLL_UP || e->direction == GDK_SCROLL_LEFT);
        d[vertical] = neg ? -1.0 : 1.0;
    }

    GtkAdjustment *adj[2] = {NULL, NULL};
    gboolean any = FALSE;
    for (int i = 0; i < 2; i++) {
        if (d[i] == 0.0)
            continue;
        adj[i] = axis_adjustment(sw, i);
        if (!adj[i])
            continue;
        double lower = gtk_adjustment_get_lower(adj[i]);
        double maxv = gtk_adjustment_get_upper(adj[i]) - gtk_adjustment_get_page_size(adj[i]);
        if (maxv <= lower) {
            adj[i] = NULL;     /* neni kam posouvat - jako dosud */
            continue;
        }
        any = TRUE;
    }
    /* nic k animaci: puvodni chovani GTK (vcetne predani udalosti vnejsimu ScrolledWindow) */
    if (!any)
        return FALSE;

    Anim *an = anim_get(w, TRUE);
    gint64 now = g_get_monotonic_time();
    for (int i = 0; i < 2; i++) {
        if (!adj[i])
            continue;
        Axis *a = &an->ax[i];
        double v = gtk_adjustment_get_value(adj[i]);
        if (a->active && (a->adj != adj[i] || fabs(v - a->last_set) > 0.5))
            axis_stop(a);
        double lower = gtk_adjustment_get_lower(adj[i]);
        double maxv = gtk_adjustment_get_upper(adj[i]) - gtk_adjustment_get_page_size(adj[i]);
        double base = a->active ? a->target : v;
        double target = CLAMP(base + d[i] * scroll_unit(adj[i]), lower, maxv);
        if (!a->active && fabs(target - v) < 0.01)
            continue;          /* na okraji: nic se nehybe, udalost je presto obslouzena */
        if (!a->adj)
            a->adj = g_object_ref(adj[i]);
        a->from = v;
        a->target = target;
        a->last_set = v;
        a->start = now;
        a->active = TRUE;
    }
    if (!an->tick && (an->ax[0].active || an->ax[1].active))
        an->tick = gtk_widget_add_tick_callback(w, anim_tick, an, NULL);
    return TRUE;
}

/* ---- setrvacnost touchpadu ------------------------------------------------------------------------- */

/* ScrolledWindow, ktery po poslednim "stop" muze jet setrvacnosti (dotyk touchpadu ho zastavi) */
typedef struct {
    gint64 stopped;            /* kdy prisel stop */
    gint64 moved;              /* kdy se naposledy posunul obsah */
} Glide;

static GWeakRef glide_sw;

static void on_glide_value(GtkAdjustment *adj, GtkWidget *sw)
{
    Glide *g = g_object_get_qdata(G_OBJECT(sw), glide_quark);
    (void)adj;
    if (g)
        g->moved = g_get_monotonic_time();
}

static void glide_start(GtkWidget *sw)
{
    Glide *g = g_object_get_qdata(G_OBJECT(sw), glide_quark);
    if (!g) {
        g = g_new0(Glide, 1);
        g_object_set_qdata_full(G_OBJECT(sw), glide_quark, g, g_free);
        g_signal_connect_object(gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(sw)), "value-changed",
                                G_CALLBACK(on_glide_value), sw, 0);
        g_signal_connect_object(gtk_scrolled_window_get_hadjustment(GTK_SCROLLED_WINDOW(sw)), "value-changed",
                                G_CALLBACK(on_glide_value), sw, 0);
    }
    g->stopped = g->moved = g_get_monotonic_time();
    g_weak_ref_set(&glide_sw, sw);
}

/* Zastavi probihajici setrvacnost: GtkScrolledWindow ji rusi pri zmene kinetic-scrolling */
static void glide_cancel(void)
{
    GtkWidget *sw = g_weak_ref_get(&glide_sw);
    if (!sw)
        return;
    Glide *g = g_object_get_qdata(G_OBJECT(sw), glide_quark);
    gint64 now = g_get_monotonic_time();
    if (g && now - g->stopped < GLIDE_MAX_US && now - g->moved < GLIDE_MOVING_US) {
        gboolean k = gtk_scrolled_window_get_kinetic_scrolling(GTK_SCROLLED_WINDOW(sw));
        gtk_scrolled_window_set_kinetic_scrolling(GTK_SCROLLED_WINDOW(sw), !k);
        gtk_scrolled_window_set_kinetic_scrolling(GTK_SCROLLED_WINDOW(sw), k);
        g_weak_ref_set(&glide_sw, NULL);
    }
    g_object_unref(sw);
}

static gboolean is_touchpad_stop(const GdkEvent *e)
{
    return e->type == GDK_SCROLL && e->scroll.direction == GDK_SCROLL_SMOOTH &&
           event_source(e) == GDK_SOURCE_TOUCHPAD && gdk_event_is_scroll_stop_event(e);
}

static gboolean sw_scroll_event(GtkWidget *w, GdkEventScroll *e)
{
    GtkScrolledWindow *sw = GTK_SCROLLED_WINDOW(w);
    if (is_wheel(e)) {
        if (wheel_scroll(sw, e))
            return TRUE;
    } else {
        Anim *an = anim_get(w, FALSE);
        if (an)
            anim_stop(an);
    }
    if (is_touchpad_stop((GdkEvent *)e)) {
        if (!opt_kinetic) {
            /* bez setrvacnosti: stop "o sekundu pozdeji" - historie posunu je stara, rychlost nulova */
            GdkEvent *late = gdk_event_copy((GdkEvent *)e);
            late->scroll.time += 1000;
            gboolean r = orig_scroll_event(w, &late->scroll);
            gdk_event_free(late);
            return r;
        }
        gboolean r = orig_scroll_event(w, e);
        glide_start(w);
        return r;
    }
    return orig_scroll_event(w, e);
}

/* ---- prvni zarazka kolecka po vstupu do okna ---------------------------------------------------------
 * GDK (X11, XInput2) pocita posun z rozdilu hodnot valuatoru a pri vstupu ukazatele do okna nebo pri
 * prepnuti zarizeni (touchpad -> mys) hodnotu zapomene: prvni zarazka pak ma posun 0 a ztrati se
 * (nahradni udalost tlacitka 4/5 GDK u oken s plynulym posunem zahodi). Modul si hodnotu valuatoru
 * mysi pamatuje (pri vstupu do okna ji zjisti z X serveru, pak pricita posuny) a ztracenou zarazku doplni. */

typedef struct {
    int id;                    /* XI zarizeni (fyzicka mys) */
    int axis[2];               /* cislo valuatoru vodorovne/svisle, -1 = neni */
    double incr[2];
    double value[2];
    gboolean known;            /* value[] odpovida tomu, co GDK naposledy videlo */
} WheelDev;

static GArray *wheel_devs;     /* WheelDev */

static WheelDev *wheel_dev(int id, gboolean create)
{
    for (guint i = 0; i < wheel_devs->len; i++) {
        WheelDev *w = &g_array_index(wheel_devs, WheelDev, i);
        if (w->id == id)
            return w;
    }
    if (!create)
        return NULL;
    WheelDev w = {id, {-1, -1}, {0, 0}, {0, 0}, FALSE};
    g_array_append_val(wheel_devs, w);
    return &g_array_index(wheel_devs, WheelDev, wheel_devs->len - 1);
}

/* Aktualni hodnoty plynulych valuatoru (jeden dotaz na X server); id = XIAllDevices nebo jedno zarizeni */
static void query_wheel_values(int id)
{
    GdkDisplay *display = gdk_display_get_default();
    if (!display || !GDK_IS_X11_DISPLAY(display))
        return;
    int n = 0;
    gdk_x11_display_error_trap_push(display);
    XIDeviceInfo *info = XIQueryDevice(GDK_DISPLAY_XDISPLAY(display), id, &n);
    gdk_x11_display_error_trap_pop_ignored(display);
    for (int i = 0; info && i < n; i++) {
        if (info[i].use != XISlavePointer)
            continue;
        double vals[64];
        gboolean have[64] = {FALSE};
        int axis[2] = {-1, -1};
        double incr[2] = {0, 0};
        for (int c = 0; c < info[i].num_classes; c++) {
            XIAnyClassInfo *any = info[i].classes[c];
            if (any->type == XIValuatorClass) {
                XIValuatorClassInfo *v = (XIValuatorClassInfo *)any;
                if (v->number >= 0 && v->number < 64) {
                    vals[v->number] = v->value;
                    have[v->number] = TRUE;
                }
            } else if (any->type == XIScrollClass) {
                XIScrollClassInfo *s = (XIScrollClassInfo *)any;
                int k = s->scroll_type == XIScrollTypeVertical ? 1 : 0;
                axis[k] = s->number;
                incr[k] = s->increment;
            }
        }
        if (axis[0] < 0 && axis[1] < 0) {
            continue;
        }
        WheelDev *w = wheel_dev(info[i].deviceid, TRUE);
        w->known = TRUE;
        for (int k = 0; k < 2; k++) {
            w->axis[k] = axis[k];
            w->incr[k] = incr[k];
            if (axis[k] >= 0 && axis[k] < 64 && have[axis[k]] && incr[k] != 0)
                w->value[k] = vals[axis[k]];
            else
                w->axis[k] = -1;
        }
    }
    if (info)
        XIFreeDeviceInfo(info);
}

static void wheel_track(GdkEvent *e)
{
    if (e->type == GDK_ENTER_NOTIFY) {
        /* stejna podminka jako reset v GDK (XI_Enter do okna nejvyssi urovne) */
        if (e->crossing.detail != GDK_NOTIFY_INFERIOR && e->crossing.window &&
            gdk_window_get_window_type(e->crossing.window) == GDK_WINDOW_TOPLEVEL)
            query_wheel_values(XIAllDevices);
        return;
    }
    if (e->type != GDK_SCROLL || e->scroll.direction != GDK_SCROLL_SMOOTH || event_source(e) != GDK_SOURCE_MOUSE)
        return;
    GdkDevice *src = gdk_event_get_source_device(e);
    if (!src || !GDK_IS_X11_DEVICE_XI2(src))
        return;
    int id = gdk_x11_device_get_id(src);
    WheelDev *w = wheel_dev(id, FALSE);
    if (e->scroll.delta_x == 0.0 && e->scroll.delta_y == 0.0) {
        /* GDK zacalo pocitat znovu: kolik se ztratilo = hodnota ted - hodnota, kterou GDK videlo naposledy */
        gboolean known = w && w->known;
        double before[2] = {w ? w->value[0] : 0, w ? w->value[1] : 0};
        query_wheel_values(id);
        w = wheel_dev(id, FALSE);
        if (!known || !w)
            return;
        double d[2] = {0, 0};
        for (int k = 0; k < 2; k++)
            if (w->axis[k] >= 0)
                d[k] = (w->value[k] - before[k]) / w->incr[k];
        /* jen jedna udalost (jedna zarazka, u jemneho kolecka zlomek): jinak radeji nic */
        if ((d[0] != 0.0 || d[1] != 0.0) && fabs(d[0]) <= 1.5 && fabs(d[1]) <= 1.5) {
            e->scroll.delta_x = d[0];
            e->scroll.delta_y = d[1];
            e->scroll.is_stop = FALSE;
        }
        return;
    }
    if (w && w->known) {
        if (w->axis[0] >= 0)
            w->value[0] += e->scroll.delta_x * w->incr[0];
        if (w->axis[1] >= 0)
            w->value[1] += e->scroll.delta_y * w->incr[1];
    }
}

/* ---- udalosti celeho procesu (Firefox, WebKitGTK a dotyk touchpadu) --------------------------------- */

static GdkEvent *held_stop;
static gint64 held_at;
static guint held_timer;

static void flush_held(void)
{
    GdkEvent *e = held_stop;
    if (!e)
        return;
    held_stop = NULL;
    if (held_timer) {
        g_source_remove(held_timer);
        held_timer = 0;
    }
    e->scroll.time += (guint32)((g_get_monotonic_time() - held_at) / 1000);
    gtk_main_do_event(e);
    gdk_event_free(e);
}

static gboolean on_held_timeout(gpointer data)
{
    (void)data;
    held_timer = 0;
    flush_held();
    return G_SOURCE_REMOVE;
}

static void event_handler(GdkEvent *e, gpointer data)
{
    (void)data;
    wheel_track(e);
    if (held_stop && (e->type == GDK_SCROLL || e->type == GDK_BUTTON_PRESS || e->type == GDK_TOUCH_BEGIN))
        flush_held();
    if (is_touchpad_stop(e) && !opt_kinetic) {
        held_stop = gdk_event_copy(e);
        held_at = g_get_monotonic_time();
        held_timer = g_timeout_add(DEFER_MS, on_held_timeout, NULL);
        return;
    }
    /* dotyk touchpadu (pohyb kurzoru) nebo klik/klepnuti zastavi setrvacnost jako v macOS */
    if ((e->type == GDK_MOTION_NOTIFY && event_source(e) == GDK_SOURCE_TOUCHPAD) || e->type == GDK_BUTTON_PRESS)
        glide_cancel();
    gtk_main_do_event(e);
}

/* Modul zustava v pameti: GTK 3 modul z Gtk/Modules uvolni (g_module_close), kdyz ho nekdo z hodnoty
   odebere (Editor nastaveni, jiny program prepise Gtk/Modules). Prepsana metoda GtkScrolledWindow a obsluha
   udalosti by pak ukazovaly do uvolneneho kodu a spadly by vsechny bezici aplikace GTK 3 vcetne xfsettingsd
   (s nim by se ztratilo tema, pisma i tmavy rezim). */
G_MODULE_EXPORT const gchar *g_module_check_init(GModule *module)
{
    g_module_make_resident(module);
    return NULL;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    static gboolean done;
    const char *off = g_getenv("LUXOS_SCROLL");
    (void)argc; (void)argv;
    if (done || (off && strcmp(off, "0") == 0))
        return;
    done = TRUE;
    anim_quark = g_quark_from_static_string("luxos-scroll-anim");
    glide_quark = g_quark_from_static_string("luxos-scroll-glide");
    g_weak_ref_init(&glide_sw, NULL);
    wheel_devs = g_array_new(FALSE, FALSE, sizeof(WheelDev));
    load_config();
    watch_config();

    GtkWidgetClass *klass = g_type_class_ref(GTK_TYPE_SCROLLED_WINDOW);
    orig_scroll_event = klass->scroll_event;
    klass->scroll_event = sw_scroll_event;

    /* Vlastni zpracovani udalosti jen pri startu aplikace (modul z Gtk/Modules se muze nacist i do bezici
       aplikace, ktera uz mohla nastavit vlastni gdk_event_handler - ten se nesmi prepsat). Pri startu je
       nastaveny gtk_main_do_event (gtk_init ho nastavi pred nactenim modulu). */
    GList *tops = gtk_window_list_toplevels();
    if (!tops)
        gdk_event_handler_set(event_handler, NULL, NULL);
    g_list_free(tops);
}
