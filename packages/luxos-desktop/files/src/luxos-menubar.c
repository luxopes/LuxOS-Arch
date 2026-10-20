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
 *
 * Navic: pri automaticky skryvanem Docku (~/.config/luxos/dock-autohide)
 * dotahne ukazatel z poslednich EDGE pixelu obrazovky na samotny okraj -
 * Plank se jinak vysune jen na uplne poslednim radku.
 */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XInput2.h>
#include <X11/extensions/XTest.h>
#include <X11/keysym.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

#define CLIENT(w) ((w) & ~0x1fffffUL)
#define CHECK_DELAY_MS 120
#define CLOSE_WAIT_MS 400
#define EDGE 6                  /* pixelu nad spodnim okrajem, ktere vysunou Dock */

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

/* Ukazatel tesne nad spodnim okrajem -> na okraj (vysunuti skryteho Docku) */
static void dock_edge(void)
{
    static long long checked;
    static int enabled;
    long long now = now_ms();
    Window r, c;
    int rx, ry, wx, wy, h;
    unsigned int mask;

    static int height;
    if (now - checked > 2000) {     /* priznak a vysku obrazovky staci kontrolovat obcas */
        Window rr;
        int gx, gy;
        unsigned int gw, gh, gb, gd;
        enabled = access(autohide_flag, F_OK) == 0;
        /* DisplayHeight() je z doby pripojeni - po zmene rozliseni (monitor, xrandr) neplati */
        if (XGetGeometry(dpy, root, &rr, &gx, &gy, &gw, &gh, &gb, &gd))
            height = (int)gh;
        checked = now;
    }
    if (!enabled || !XQueryPointer(dpy, root, &r, &c, &rx, &ry, &wx, &wy, &mask))
        return;
    if (mask & (Button1Mask | Button2Mask | Button3Mask))
        return;                     /* tazeni mysi nerusit */
    h = height ? height : DisplayHeight(dpy, DefaultScreen(dpy));
    if (ry >= h - EDGE && ry < h - 1) {
        XWarpPointer(dpy, None, root, 0, 0, 0, 0, rx, h - 1);
        XFlush(dpy);
    }
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
        if (ck->evtype == XI_RawMotion) {
            dock_edge();
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
    unsigned char bits[XIMaskLen(XI_LASTEVENT)] = {0};
    XISetMask(bits, XI_RawButtonPress);
    XISetMask(bits, XI_RawButtonRelease);
    XISetMask(bits, XI_RawMotion);
    XIEventMask mask = {XIAllMasterDevices, sizeof bits, bits};
    XISelectEvents(dpy, root, &mask, 1);
    XFlush(dpy);

    int fd = ConnectionNumber(dpy);
    for (;;) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            handle_event(&ev);
        }
        if (pending.active && now_ms() >= pending.due) {
            run_pending();
            continue;
        }
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv, *tvp = NULL;
        if (pending.active) {
            long long left = pending.due - now_ms();
            if (left < 0)
                left = 0;
            tv.tv_sec = left / 1000;
            tv.tv_usec = (left % 1000) * 1000;
            tvp = &tv;
        }
        if (select(fd + 1, &fds, NULL, NULL, tvp) < 0)
            return 1;
    }
}
