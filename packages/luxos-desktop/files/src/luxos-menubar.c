/*
 * luxos-menubar - prepinani mezi nabidkami horni listy jednim klikem (jako v macOS).
 *
 * Otevrena nabidka pluginu (popup) drzi grab mysi, takze klik na jinou ikonu
 * v liste ji jen zavre nebo se ztrati. Demon sleduje kliky pres XInput2 raw
 * udalosti (chodi i behem grabu) a kdyz klik na jiny plugin nic neotevrel,
 * zavre starou nabidku klavesou Escape a klik zopakuje pres XTest.
 *
 * Plugin se pozna podle X klienta: kazdy externi plugin bezi ve vlastnim
 * procesu wrapper-2.0, takze popup i ikona pod kurzorem maji stejny zaklad ID.
 * Proto pluginy s nabidkami zustavaji externi; uvnitr panelu bezi jen pluginy
 * bez nabidek (genmon, systray - viz /usr/lib/luxos/panel).
 *
 * Navic: pri automaticky skryvanem Docku (~/.config/luxos/dock-autohide)
 * dotahne ukazatel z poslednich EDGE pixelu obrazovky na samotny okraj -
 * Plank se jinak vysune jen na uplne poslednim radku. Pohyb mysi se sleduje
 * jen pri zapnutem priznaku a dotazy na polohu se slucuji (max. ~60x za s).
 *
 * A: pripojeni/odpojeni monitoru (udalost RandR, zadne dotazovani) spusti
 * "luxos-displays auto" - rozlozeni obrazovek, okna z odpojeneho monitoru, tapeta.
 *
 * A: samotne tuknuti na klavesu Super otevre Launchpad (jako Start ve Windows).
 * Raw udalosti klaves (pasivne, bez grabu); rozpoznani je v luxos-super-tap.h.
 * Super+klavesa nebo Super+mys Launchpad neotevre. Pri zamcene obrazovce, otevrene
 * nabidce apod. (klavesnici drzi grab jineho klienta) se nic nespusti. Vypina se
 * priznakem ~/.config/luxos/super-launchpad-off (aplikace Klavesove zkratky).
 */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/XKBlib.h>
#include <X11/extensions/XInput2.h>
#include <X11/extensions/XTest.h>
#include <X11/extensions/Xrandr.h>
#include <X11/keysym.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "luxos-super-tap.h"

#define CLIENT(w) ((w) & ~0x1fffffUL)
#define CHECK_DELAY_MS 120
#define CLOSE_WAIT_MS 400
#define EDGE 6                  /* pixelu nad spodnim okrajem, ktere vysunou Dock */
#define EDGE_COALESCE_MS 15     /* pohyby mysi v tomto okne = jeden dotaz na polohu */
#define FLAG_CHECK_MS 5000      /* jak casto zjistit, jestli se Dock skryva */
#define HOTPLUG_DELAY_MS 1200   /* vyckat, nez se vystup ustali (EDID, dalsi udalosti) */

static Display *dpy;
static Window root;
static Atom a_pid, a_type, a_state, a_skip_taskbar, a_dock;
static Atom a_menu[3];

static Window popup;          /* aktualne otevrena nabidka (potomek rootu) */
static unsigned long popup_client; /* X klient (plugin), kteremu nabidka patri */

static struct {
    int active;
    long long due;
    Window old;
    unsigned long client;
} pending;

static long long replay_until;
static Window popup_at_press;   /* nabidka otevrena v okamziku stisku tlacitka */

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}

static int ignore_errors(Display *d, XErrorEvent *e)
{
    (void)d; (void)e;
    return 0;
}

static int get_atoms(Window w, Atom prop, Atom *out, int max)
{
    Atom type;
    int fmt, n = 0;
    unsigned long count, after;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, w, prop, 0, 32, False, XA_ATOM, &type, &fmt, &count, &after, &data) == Success && data) {
        for (unsigned long i = 0; i < count && n < max; i++)
            out[n++] = ((Atom *)data)[i];
        XFree(data);
    }
    return n;
}

static int has_atom(Window w, Atom prop, Atom want)
{
    Atom v[16];
    int n = get_atoms(w, prop, v, 16);
    for (int i = 0; i < n; i++)
        if (v[i] == want)
            return 1;
    return 0;
}

static long get_pid(Window w)
{
    Atom type;
    int fmt;
    unsigned long count, after;
    unsigned char *data = NULL;
    long pid = 0;
    if (XGetWindowProperty(dpy, w, a_pid, 0, 1, False, XA_CARDINAL, &type, &fmt, &count, &after, &data) == Success && data) {
        if (count)
            pid = (long)*(unsigned long *)data;
        XFree(data);
    }
    return pid;
}

/* Okno aplikace uvnitr ramecku spravce oken (nebo okno samotne) */
static Window find_client(Window w, int depth)
{
    if (get_pid(w))
        return w;
    if (depth <= 0)
        return None;
    Window r, p, *kids = NULL, found = None;
    unsigned int n;
    if (!XQueryTree(dpy, w, &r, &p, &kids, &n))
        return None;
    for (unsigned int i = 0; i < n && !found; i++)
        found = find_client(kids[i], depth - 1);
    if (kids)
        XFree(kids);
    return found;
}

static int is_panel_process(long pid)
{
    char path[64], comm[32] = "";
    snprintf(path, sizeof path, "/proc/%ld/comm", pid);
    FILE *f = fopen(path, "r");
    if (!f)
        return 0;
    if (!fgets(comm, sizeof comm, f))
        comm[0] = 0;
    fclose(f);
    comm[strcspn(comm, "\n")] = 0;
    return !strcmp(comm, "xfce4-panel") || !strcmp(comm, "wrapper-2.0");
}

/* Nabidka = menu bez spravce oken, nebo okno panelu mimo seznam oken (Whisker Menu, kalendar) */
static int is_popup(Window w)
{
    XWindowAttributes at;
    if (!XGetWindowAttributes(dpy, w, &at) || at.width < 24 || at.height < 24)
        return 0;
    if (at.override_redirect) {
        for (int i = 0; i < 3; i++)
            if (has_atom(w, a_type, a_menu[i]))
                return 1;
        return 0;
    }
    Window c = find_client(w, 2);
    return c && is_panel_process(get_pid(c)) && has_atom(c, a_state, a_skip_taskbar)
        && !has_atom(c, a_type, a_dock);
}

static Window popup_client_window(Window w)
{
    XWindowAttributes at;
    if (XGetWindowAttributes(dpy, w, &at) && at.override_redirect)
        return w;
    Window c = find_client(w, 2);
    return c ? c : w;
}

/* Je kurzor v horni liste? Vraci nejhlubsi okno pod nim (ikonu pluginu). */
static Window panel_window_at(void)
{
    Window r, child, top, deepest;
    int rx, ry, wx, wy;
    unsigned int mask;
    if (!XQueryPointer(dpy, root, &r, &top, &rx, &ry, &wx, &wy, &mask) || !top)
        return None;
    Window c = find_client(top, 2);
    if (!c || !has_atom(c, a_type, a_dock) || !is_panel_process(get_pid(c)))
        return None;
    deepest = top;
    while (XQueryPointer(dpy, deepest, &r, &child, &rx, &ry, &wx, &wy, &mask) && child)
        deepest = child;
    return deepest;
}

static void send_key(KeySym ks)
{
    KeyCode kc = XKeysymToKeycode(dpy, ks);
    XTestFakeKeyEvent(dpy, kc, True, CurrentTime);
    XTestFakeKeyEvent(dpy, kc, False, CurrentTime);
    XFlush(dpy);
}

static void handle_event(XEvent *ev);

static char autohide_flag[512];
static int autohide;            /* Dock se skryva -> sledovat pohyb mysi */
static char super_flag[512];    /* existuje = Super samotna Launchpad neotevira */
static int super_on = -1;       /* sledovat klavesy kvuli tuknuti na Super */
static struct super_tap tap;
static long long edge_due;      /* naplanovana kontrola polohy (0 = zadna) */
static long long flag_due;

static int rr_event_base = -1;
static long long hotplug_due;
static char outputs_last[1024];

static void select_xi(void)
{
    unsigned char bits[XIMaskLen(XI_LASTEVENT)] = {0};
    XISetMask(bits, XI_RawButtonPress);
    XISetMask(bits, XI_RawButtonRelease);
    if (autohide)
        XISetMask(bits, XI_RawMotion);
    if (super_on > 0) {
        XISetMask(bits, XI_RawKeyPress);
        XISetMask(bits, XI_RawKeyRelease);
    }
    XIEventMask mask = {XIAllMasterDevices, sizeof bits, bits};
    XISelectEvents(dpy, root, &mask, 1);
    XFlush(dpy);
}

static void check_flag(void)
{
    int on = access(autohide_flag, F_OK) == 0;
    int super = access(super_flag, F_OK) != 0;
    if (on != autohide || super != super_on) {
        autohide = on;
        if (super != super_on)
            memset(&tap, 0, sizeof tap);
        super_on = super;
        select_xi();
    }
    flag_due = now_ms() + FLAG_CHECK_MS;
}

/* Ukazatel tesne nad spodnim okrajem -> na okraj (vysunuti skryteho Docku) */
static void dock_edge(void)
{
    static long long checked;
    static int height;
    long long now = now_ms();
    Window r, c;
    int rx, ry, wx, wy, h;
    unsigned int mask;

    edge_due = 0;
    if (now - checked > 2000) {     /* DisplayHeight() je z doby pripojeni - po zmene rozliseni neplati */
        Window rr;
        int gx, gy;
        unsigned int gw, gh, gb, gd;
        if (XGetGeometry(dpy, root, &rr, &gx, &gy, &gw, &gh, &gb, &gd))
            height = (int)gh;
        checked = now;
    }
    if (!autohide || !XQueryPointer(dpy, root, &r, &c, &rx, &ry, &wx, &wy, &mask))
        return;
    if (mask & (Button1Mask | Button2Mask | Button3Mask))
        return;                     /* tazeni mysi nerusit */
    h = height ? height : DisplayHeight(dpy, DefaultScreen(dpy));
    if (ry >= h - EDGE && ry < h - 1) {
        XWarpPointer(dpy, None, root, 0, 0, 0, 0, rx, h - 1);
        XFlush(dpy);
    }
}

/* Seznam pripojenych vystupu ("eDP-1 HDMI-1 ") */
static void connected_outputs(char *buf, size_t n)
{
    size_t len = 0;
    buf[0] = 0;
    XRRScreenResources *res = XRRGetScreenResources(dpy, root);   /* znovu zjistit pripojeni */
    if (!res)
        return;
    for (int i = 0; i < res->noutput; i++) {
        XRROutputInfo *info = XRRGetOutputInfo(dpy, res, res->outputs[i]);
        if (!info)
            continue;
        if (info->connection == RR_Connected && len + strlen(info->name) + 2 < n)
            len += snprintf(buf + len, n - len, "%s ", info->name);
        XRRFreeOutputInfo(info);
    }
    XRRFreeScreenResources(res);
}

static void run_hotplug(void)
{
    char now[sizeof outputs_last];
    hotplug_due = 0;
    connected_outputs(now, sizeof now);
    if (!strcmp(now, outputs_last))
        return;                     /* jen zmena rezimu/rozlozeni, ne pripojeni */
    strcpy(outputs_last, now);
    if (fork() == 0) {
        setsid();
        execlp("luxos-displays", "luxos-displays", "auto", (char *)NULL);
        _exit(127);
    }
}

/* Bezi proces s timto jmenem pod nasim uzivatelem? */
static int own_process_running(const char *name)
{
    DIR *d = opendir("/proc");
    struct dirent *e;
    int found = 0;
    uid_t uid = getuid();
    if (!d)
        return 0;
    while (!found && (e = readdir(d))) {
        char path[300], comm[32] = "";
        struct stat st;
        if (e->d_name[0] < '1' || e->d_name[0] > '9')
            continue;
        snprintf(path, sizeof path, "/proc/%s/comm", e->d_name);
        if (stat(path, &st) || st.st_uid != uid)
            continue;
        FILE *f = fopen(path, "r");
        if (!f)
            continue;
        if (fgets(comm, sizeof comm, f)) {
            comm[strcspn(comm, "\n")] = 0;
            found = !strcmp(comm, name);
        }
        fclose(f);
    }
    closedir(d);
    return found;
}

/* Tuknuti na Super: otevrit (nebo zavrit) Launchpad */
static void super_launchpad(void)
{
    /* Grab klavesnice drzi nekdo jiny: zamcena obrazovka/sporic, nabidka, zaznam zkratky.
     * Vyjimka je otevreny Launchpad (rofi) - luxos-launchpad ho zavre jako Super+A. */
    int r = XGrabKeyboard(dpy, root, False, GrabModeAsync, GrabModeAsync, CurrentTime);
    if (r == GrabSuccess)
        XUngrabKeyboard(dpy, CurrentTime);
    XFlush(dpy);
    if (r != GrabSuccess && !own_process_running("rofi"))
        return;
    if (fork() == 0) {
        setsid();
        execlp("luxos-launchpad", "luxos-launchpad", (char *)NULL);
        _exit(127);
    }
}

static void super_key(XIRawEvent *re, int press)
{
    int kc = re->detail;
    KeySym ks = XkbKeycodeToKeysym(dpy, (KeyCode)kc, 0, 0);
    int is_super = ks == XK_Super_L || ks == XK_Super_R;
    if (press && is_super) {
        char keys[32];
        XQueryKeymap(dpy, keys);    /* skutecny stav ostatnich klaves (ztracena uvolneni) */
        super_tap_sync(&tap, keys);
    }
    if (super_tap_event(&tap, press ? TAP_KEY_PRESS : TAP_KEY_RELEASE, kc, is_super, now_ms()))
        super_launchpad();
}

/* Zpracovava udalosti az do zavreni nabidky nebo vyprseni casu */
static void wait_closed(Window w, int ms)
{
    long long end = now_ms() + ms;
    while (popup == w && now_ms() < end) {
        while (XPending(dpy) && popup == w) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            handle_event(&ev);
        }
        struct timespec ts = {0, 10 * 1000000};
        nanosleep(&ts, NULL);
    }
}

static void run_pending(void)
{
    pending.active = 0;
    if (popup && popup != pending.old)
        return;                 /* klik sam otevrel novou nabidku */
    if (pending.client == popup_client) {
        if (popup == pending.old) /* znovu stejna ikona: jen zavrit */
            send_key(XK_Escape);
        return;
    }
    if (popup == pending.old) {
        send_key(XK_Escape);
        wait_closed(pending.old, CLOSE_WAIT_MS);
        if (popup == pending.old)
            return;             /* nabidka se nezavrela, nic nevynucovat */
    }
    /* Zopakovat klik na nove ikone */
    replay_until = now_ms() + 300;
    XTestFakeButtonEvent(dpy, 1, True, CurrentTime);
    XTestFakeButtonEvent(dpy, 1, False, CurrentTime);
    XFlush(dpy);
}

static void handle_event(XEvent *ev)
{
    if (rr_event_base >= 0 && ev->type == rr_event_base + RRNotify) {
        if (((XRRNotifyEvent *)ev)->subtype == RRNotify_OutputChange)
            hotplug_due = now_ms() + HOTPLUG_DELAY_MS;
        return;
    }
    if (ev->type == MapNotify) {
        Window w = ev->xmap.window;
        if (is_popup(w)) {
            popup = w;
            popup_client = CLIENT(popup_client_window(w));
        }
    } else if (ev->type == UnmapNotify) {
        if (ev->xunmap.window == popup)
            popup = None;
    } else if (ev->type == DestroyNotify) {
        if (ev->xdestroywindow.window == popup)
            popup = None;
    } else if (ev->type == GenericEvent) {
        XGenericEventCookie *ck = &ev->xcookie;
        if (!XGetEventData(dpy, ck))
            return;
        XIRawEvent *re = ck->data;
        if (ck->evtype == XI_RawKeyPress || ck->evtype == XI_RawKeyRelease) {
            if (super_on > 0)
                super_key(re, ck->evtype == XI_RawKeyPress);
            XFreeEventData(dpy, ck);
            return;
        }
        if (ck->evtype == XI_RawButtonPress)
            super_tap_event(&tap, TAP_BUTTON, 0, 0, now_ms());   /* Super+klik/kolecko */
        if (ck->evtype == XI_RawMotion) {
            if (!edge_due)
                edge_due = now_ms() + EDGE_COALESCE_MS;
        } else if (re->detail == 1 && now_ms() >= replay_until) {
            /* GTK otevira nabidku uz pri stisku, proto rozhoduje stav pred nim */
            if (ck->evtype == XI_RawButtonPress) {
                popup_at_press = popup;
            } else if (popup_at_press && !pending.active) {
                Window w = panel_window_at();
                if (w) {
                    pending.active = 1;
                    pending.due = now_ms() + CHECK_DELAY_MS;
                    pending.old = popup_at_press;
                    pending.client = CLIENT(w);
                }
                popup_at_press = None;
            }
        }
        XFreeEventData(dpy, ck);
    }
}

int main(void)
{
    int xi_op, ev_base, err_base, major = 2, minor = 2;
    dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "luxos-menubar: cannot open display\n");
        return 1;
    }
    if (!XQueryExtension(dpy, "XInputExtension", &xi_op, &ev_base, &err_base)
        || XIQueryVersion(dpy, &major, &minor) != Success
        || !XTestQueryExtension(dpy, &ev_base, &err_base, &major, &minor)) {
        fprintf(stderr, "luxos-menubar: XInput 2.2 and XTest required\n");
        return 1;
    }
    XSetErrorHandler(ignore_errors);
    root = DefaultRootWindow(dpy);
    {
        const char *cfg = getenv("XDG_CONFIG_HOME");
        const char *home = getenv("HOME");
        if (cfg && *cfg)
            snprintf(autohide_flag, sizeof autohide_flag, "%s/luxos/dock-autohide", cfg);
        else
            snprintf(autohide_flag, sizeof autohide_flag, "%s/.config/luxos/dock-autohide", home ? home : "");
        if (cfg && *cfg)
            snprintf(super_flag, sizeof super_flag, "%s/luxos/super-launchpad-off", cfg);
        else
            snprintf(super_flag, sizeof super_flag, "%s/.config/luxos/super-launchpad-off", home ? home : "");
    }
    a_pid = XInternAtom(dpy, "_NET_WM_PID", False);
    a_type = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE", False);
    a_state = XInternAtom(dpy, "_NET_WM_STATE", False);
    a_skip_taskbar = XInternAtom(dpy, "_NET_WM_STATE_SKIP_TASKBAR", False);
    a_dock = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DOCK", False);
    a_menu[0] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_POPUP_MENU", False);
    a_menu[1] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU", False);
    a_menu[2] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_MENU", False);

    XSelectInput(dpy, root, SubstructureNotifyMask);
    check_flag();
    int rr_err;
    if (XRRQueryExtension(dpy, &rr_event_base, &rr_err)) {
        XRRSelectInput(dpy, root, RROutputChangeNotifyMask);
        connected_outputs(outputs_last, sizeof outputs_last);
    } else {
        rr_event_base = -1;
    }
    signal(SIGCHLD, SIG_IGN);       /* luxos-displays: bez zombie procesu */
    XFlush(dpy);

    int fd = ConnectionNumber(dpy);
    for (;;) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            handle_event(&ev);
        }
        long long now = now_ms();
        if (pending.active && now >= pending.due) {
            run_pending();
            continue;
        }
        if (edge_due && now >= edge_due)
            dock_edge();
        if (hotplug_due && now >= hotplug_due)
            run_hotplug();
        if (now >= flag_due)
            check_flag();

        /* nejblizsi naplanovana akce */
        long long due = flag_due;
        if (pending.active && pending.due < due)
            due = pending.due;
        if (edge_due && edge_due < due)
            due = edge_due;
        if (hotplug_due && hotplug_due < due)
            due = hotplug_due;
        long long left = due - now_ms();
        if (left < 0)
            left = 0;
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv = {left / 1000, (left % 1000) * 1000};
        if (select(fd + 1, &fds, NULL, NULL, &tv) < 0)
            return 1;
    }
}
