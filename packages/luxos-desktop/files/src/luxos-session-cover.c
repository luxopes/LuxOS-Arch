/*
 * luxos-session-cover - pri odhlaseni, restartu a vypnuti zakryje obrazovku cernou.
 *
 * Konec relace ukoncuje programy postupne: kompozitor (xfwm4) skonci drive nez okna, ta pak na
 * okamzik maji kolem sebe cerne pruhy (misto stinu a zaoblenych rohu). luxos-hub program spusti,
 * jakmile xfce4-session zacne odhlasovat (stav SHUTDOWN - programy se jeste mohou ptat na ulozeni
 * dokumentu, proto se zatim nic nezobrazi). Pak:
 *   - SIGUSR1 (stav SHUTDOWNPHASE2, programy dostanou pokyn skoncit): obrazovka se behem ~0,15 s
 *     zatmi (pruhlednost _NET_WM_WINDOW_OPACITY, dokud bezi kompozitor)
 *   - kompozitor skoncil (vlastnik vyberu _NET_WM_CM_Sn, XFixes): cerna okamzite
 *   - SIGTERM (odhlaseni zruseno): konec bez zakryti
 * Cerne okno bez spravce oken se drzi navrchu, dokud neskonci X server.
 */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define FADE_MS 150
#define STEPS 6
#define POLL_MS 100

static volatile sig_atomic_t go;

static void on_usr1(int sig)
{
    (void)sig;
    go = 1;
}

static void sleep_ms(int ms)
{
    struct timespec ts = {ms / 1000, (ms % 1000) * 1000000L};
    nanosleep(&ts, NULL);
}

static Display *dpy;
static Window root, win;
static Atom a_opacity, a_cm;
static int shown;

static void set_opacity(unsigned long v)
{
    XChangeProperty(dpy, win, a_opacity, XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&v, 1);
}

/* fade=1: zatmeni pres kompozitor; jinak hned cerna */
static void show(int fade)
{
    if (shown == 2)
        return;
    if (fade && !shown && XGetSelectionOwner(dpy, a_cm) != None) {
        shown = 1;
        set_opacity(0);
        XMapRaised(dpy, win);
        XFlush(dpy);
        for (int i = 1; i < STEPS; i++) {
            sleep_ms(FADE_MS / STEPS);
            if (XGetSelectionOwner(dpy, a_cm) == None)
                break;          /* kompozitor skoncil uprostred - dal uz jen cerna */
            set_opacity(0xffffffffUL / STEPS * (unsigned long)i);
            XRaiseWindow(dpy, win);
            XFlush(dpy);
        }
    }
    /* Uplne nepruhledne: bez vlastnosti je okno cerne i bez kompozitoru */
    XDeleteProperty(dpy, win, a_opacity);
    XMapRaised(dpy, win);
    XFlush(dpy);
    shown = 2;
}

int main(void)
{
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_usr1;
    sigaction(SIGUSR1, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    dpy = XOpenDisplay(NULL);
    if (!dpy)
        return 1;
    int scr = DefaultScreen(dpy), xf_event, xf_error;
    root = RootWindow(dpy, scr);
    XWindowAttributes ra;
    XGetWindowAttributes(dpy, root, &ra);

    XSetWindowAttributes a;
    a.override_redirect = True;
    a.background_pixel = BlackPixel(dpy, scr);
    win = XCreateWindow(dpy, root, 0, 0, (unsigned)ra.width, (unsigned)ra.height, 0, CopyFromParent,
                        InputOutput, CopyFromParent, CWOverrideRedirect | CWBackPixel, &a);
    XStoreName(dpy, win, "luxos-session-cover");
    a_opacity = XInternAtom(dpy, "_NET_WM_WINDOW_OPACITY", False);
    char cm[32];
    snprintf(cm, sizeof cm, "_NET_WM_CM_S%d", scr);
    a_cm = XInternAtom(dpy, cm, False);

    /* Prazdny kurzor nad cernou plochou */
    static char none[8];
    Pixmap pm = XCreateBitmapFromData(dpy, win, none, 8, 8);
    XColor black;
    memset(&black, 0, sizeof black);
    XDefineCursor(dpy, win, XCreatePixmapCursor(dpy, pm, pm, &black, &black, 0, 0));

    int fixes = XFixesQueryExtension(dpy, &xf_event, &xf_error);
    int had_cm = XGetSelectionOwner(dpy, a_cm) != None;
    if (fixes)
        XFixesSelectSelectionInput(dpy, root, a_cm, XFixesSetSelectionOwnerNotifyMask
                                   | XFixesSelectionWindowDestroyNotifyMask | XFixesSelectionClientCloseNotifyMask);
    XFlush(dpy);

    struct pollfd pfd = {ConnectionNumber(dpy), POLLIN, 0};
    for (;;) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            if (fixes && ev.type == xf_event + XFixesSelectionNotify && had_cm
                && XGetSelectionOwner(dpy, a_cm) == None)
                show(0);        /* kompozitor skoncil */
        }
        if (go && shown != 2)
            show(1);
        if (shown) {
            XRaiseWindow(dpy, win);
            XFlush(dpy);
        }
        if (poll(&pfd, 1, POLL_MS) < 0 && errno != EINTR)
            break;
        if (pfd.revents & (POLLHUP | POLLERR))
            break;
    }
    return 0;
}
