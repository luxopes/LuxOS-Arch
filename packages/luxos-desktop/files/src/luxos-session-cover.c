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
 *
 * luxos-session-cover --login - prechod po prihlaseni (spousti /etc/X11/xinit/xinitrc.d/60-luxos-login-cover.sh
 * pred startem relace): okno pres celou obrazovku s poslednim snimkem prihlasovaci obrazovky (greeter pred
 * spustenim relace ukaze jen tapetu, X server snimek po skonceni greeteru drzi - "X -background none")
 * zakryje skladani plochy. Jakmile je plocha (okno typu DESKTOP) i lista (DOCK) a probehne kresleni, okno
 * se behem ~0,28 s rozplyne (pruhlednost pres kompozitor xfwm4) a skonci. Na nic neceka: vstup (mys,
 * klavesnice) jde skrz (prazdny vstupni tvar), nejdele po LOGIN_MAX_MS konci vzdy. Bez animace (jen
 * odkryti) pri zapnutem Sporici baterie (~/.config/luxos/powersaver) nebo vypnutych animacich (xsettings).
 *
 * Snimek ze serveru nemusi prezit: bez glamor (napr. QEMU bochs + llvmpipe) ovladac modesetting
 * "-background none" neumi, korenove okno se po skonceni greeteru vybarvi cerne. Proto greeter pred
 * spustenim relace ulozi stejny snimek do sdilene slozky LightDM (/var/lib/lightdm-data/<uzivatel>,
 * LUXOS_LOGIN_FRAME_DIR pro testy): login-frame.raw (cela obrazovka, nejvys 2 min stary, po nacteni se
 * smaze) a login-frame-small.raw (mala rozmazana tapeta, zustava). Je-li zachyceny snimek cerny, pouzije
 * se login-frame.raw, jinak zvetsena rozmazana tapeta; cerna jen kdyz neni nic.
 * Format: "LUXFRAME1 <sirka> <vyska>\n" + sirka*vyska*4 bajtu BGRx (cairo RGB24 na little-endian).
 */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/shape.h>
#include <X11/Xutil.h>
#include <errno.h>
#include <poll.h>
#include <pwd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

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

static int logout_main(void)
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

/* ---- prechod po prihlaseni --------------------------------------------------------------------- */

#define LOGIN_SETTLE_MS 200      /* plocha a lista jsou namapovane: chvile na prvni vykresleni */
#define LOGIN_FADE_MS 280
#define LOGIN_FADE_STEPS 14
#define LOGIN_WAIT_CM_MS 1200    /* po pripraveni plochy jeste chvili pockat na kompozitor (rozplynuti) */
#define LOGIN_MAX_MS 5000        /* vzdy skoncit (relace bez listy, jine prostredi) */

static long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

/* Soubor (male nastaveni) obsahuje text */
static int file_contains(const char *path, const char *needle)
{
    static char buf[65536];
    FILE *f = fopen(path, "r");
    if (!f)
        return 0;
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    return strstr(buf, needle) != NULL;
}

/* Sporic baterie nebo vypnute animace GTK = bez rozplynuti (jen odkryti) */
static int motion_allowed(void)
{
    char base[4096], path[4200];
    const char *xdg = getenv("XDG_CONFIG_HOME"), *home = getenv("HOME");
    if (xdg && *xdg)
        snprintf(base, sizeof base, "%s", xdg);
    else if (home && *home)
        snprintf(base, sizeof base, "%s/.config", home);
    else
        return 1;
    snprintf(path, sizeof path, "%s/luxos/powersaver", base);
    if (access(path, F_OK) == 0)
        return 0;
    snprintf(path, sizeof path, "%s/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml", base);
    return !file_contains(path, "name=\"EnableAnimations\" type=\"bool\" value=\"false\"");
}

static Atom a_clients, a_type, a_desktop, a_dock;

/* Plocha (DESKTOP) a lista nebo dock (DOCK) uz jsou mezi okny spravce oken */
static int desktop_ready(void)
{
    Atom type;
    int fmt, desk = 0, dock = 0;
    unsigned long n = 0, rest;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, root, a_clients, 0, 4096, False, AnyPropertyType, &type, &fmt, &n, &rest, &data) != Success
        || !data)
        return 0;
    Window *w = (Window *)data;
    for (unsigned long i = 0; i < n && !(desk && dock); i++) {
        unsigned char *t = NULL;
        unsigned long tn = 0;
        if (XGetWindowProperty(dpy, w[i], a_type, 0, 8, False, XA_ATOM, &type, &fmt, &tn, &rest, &t) == Success && t) {
            Atom *at = (Atom *)t;
            for (unsigned long j = 0; j < tn; j++) {
                if (at[j] == a_desktop)
                    desk = 1;
                else if (at[j] == a_dock)
                    dock = 1;
            }
            XFree(t);
        }
    }
    XFree(data);
    return desk && dock;
}

#define FRAME_MAX_AGE_S 120      /* starsi login-frame.raw je z jineho prihlaseni */
#define FRAME_MAX_SIDE 16384

/* Vzorek tri radku snimku: vsechno cerne = server snimek neudrzel */
static int frame_is_black(Drawable d, unsigned w, unsigned h)
{
    for (unsigned k = 1; k <= 3; k++) {
        XImage *im = XGetImage(dpy, d, 0, (int)(h * k / 4), w, 1, AllPlanes, ZPixmap);
        if (!im)
            continue;
        for (unsigned x = 0; x < w; x += 5) {
            if (XGetPixel(im, (int)x, 0) & 0xffffffUL) {
                XDestroyImage(im);
                return 0;
            }
        }
        XDestroyImage(im);
    }
    return 1;
}

/* Nacte snimek greeteru -> pixely BGRx (malloc), rozmery v *fw, *fh; NULL pri chybe */
static unsigned char *read_frame(const char *path, unsigned *fw, unsigned *fh)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    unsigned w = 0, h = 0;
    unsigned char *px = NULL;
    if (fscanf(f, "LUXFRAME1 %u %u", &w, &h) == 2 && fgetc(f) == '\n' && w && h
        && w <= FRAME_MAX_SIDE && h <= FRAME_MAX_SIDE) {
        size_t n = (size_t)w * h * 4;
        px = malloc(n);
        if (px && fread(px, 1, n, f) != n) {
            free(px);
            px = NULL;
        }
    }
    fclose(f);
    *fw = w;
    *fh = h;
    return px;
}

/* Bilinearni zvetseni/zmenseni BGRx na w x h (mala rozmazana tapeta, jine rozliseni) */
static unsigned char *scale_frame(const unsigned char *src, unsigned sw, unsigned sh, unsigned w, unsigned h)
{
    unsigned char *dst = malloc((size_t)w * h * 4);
    if (!dst)
        return NULL;
    for (unsigned y = 0; y < h; y++) {
        double fy = ((double)y + 0.5) * sh / h - 0.5;
        if (fy < 0)
            fy = 0;
        unsigned y0 = (unsigned)fy, y1 = y0 + 1 < sh ? y0 + 1 : y0;
        double ty = fy - y0;
        unsigned char *out = dst + (size_t)y * w * 4;
        for (unsigned x = 0; x < w; x++) {
            double fx = ((double)x + 0.5) * sw / w - 0.5;
            if (fx < 0)
                fx = 0;
            unsigned x0 = (unsigned)fx, x1 = x0 + 1 < sw ? x0 + 1 : x0;
            double tx = fx - x0;
            const unsigned char *a = src + ((size_t)y0 * sw + x0) * 4, *b = src + ((size_t)y0 * sw + x1) * 4;
            const unsigned char *c = src + ((size_t)y1 * sw + x0) * 4, *e = src + ((size_t)y1 * sw + x1) * 4;
            for (int ch = 0; ch < 3; ch++) {
                double top = a[ch] + (b[ch] - a[ch]) * tx, bottom = c[ch] + (e[ch] - c[ch]) * tx;
                out[x * 4 + ch] = (unsigned char)(top + (bottom - top) * ty + 0.5);
            }
            out[x * 4 + 3] = 0xff;
        }
    }
    return dst;
}

/* Pixely BGRx do pixmapy (jen TrueColor 24/32 bitu s beznymi maskami) */
static int put_frame(Pixmap p, Visual *vis, int depth, unsigned char *px, unsigned w, unsigned h)
{
    if ((depth != 24 && depth != 32) || vis->red_mask != 0xff0000UL || vis->green_mask != 0xff00UL
        || vis->blue_mask != 0xffUL)
        return 0;
    XImage *im = XCreateImage(dpy, vis, (unsigned)depth, ZPixmap, 0, (char *)px, w, h, 32, (int)(w * 4));
    if (!im)
        return 0;
    im->byte_order = LSBFirst;      /* soubor je vzdy little-endian BGRx */
    GC gc = XCreateGC(dpy, p, 0, NULL);
    XPutImage(dpy, p, gc, im, 0, 0, 0, 0, w, h);
    XFreeGC(dpy, gc);
    im->data = NULL;                /* pixely uvolni volajici */
    XDestroyImage(im);
    return 1;
}

static void frame_path(char *out, size_t size, const char *name)
{
    const char *dir = getenv("LUXOS_LOGIN_FRAME_DIR");
    if (dir && *dir) {
        snprintf(out, size, "%s/%s", dir, name);
        return;
    }
    struct passwd *pw = getpwuid(getuid());
    snprintf(out, size, "/var/lib/lightdm-data/%s/%s", pw ? pw->pw_name : "-", name);
}

/* Snimek ze serveru je cerny: snimek greeteru, jinak rozmazana tapeta. 1 = pixmapa nahrazena */
static int restore_frame(Pixmap snap, Visual *vis, int depth, unsigned w, unsigned h, int black)
{
    char path[4300];
    unsigned fw, fh;
    unsigned char *px = NULL;
    struct stat st;
    frame_path(path, sizeof path, "login-frame.raw");
    if (stat(path, &st) == 0) {
        if (black && time(NULL) - st.st_mtime <= FRAME_MAX_AGE_S && time(NULL) - st.st_mtime >= -5)
            px = read_frame(path, &fw, &fh);
        unlink(path);               /* jednorazovy (~8 MB): pristi prihlaseni ulozi novy */
    }
    if (!black)
        return 0;
    if (!px) {
        frame_path(path, sizeof path, "login-frame-small.raw");
        px = read_frame(path, &fw, &fh);
    }
    if (!px)
        return 0;
    if (fw != w || fh != h) {
        unsigned char *scaled = scale_frame(px, fw, fh, w, h);
        free(px);
        px = scaled;
        if (!px)
            return 0;
    }
    int ok = put_frame(snap, vis, depth, px, w, h);
    free(px);
    return ok;
}

static int ignore_errors(Display *d, XErrorEvent *e)
{
    (void)d;
    (void)e;
    return 0;                   /* okno ze seznamu mezitim zaniklo */
}

static int login_main(void)
{
    dpy = XOpenDisplay(NULL);
    if (!dpy)
        return 1;
    XSetErrorHandler(ignore_errors);
    int scr = DefaultScreen(dpy), xf_event, xf_error;
    root = RootWindow(dpy, scr);
    XWindowAttributes ra;
    XGetWindowAttributes(dpy, root, &ra);
    a_opacity = XInternAtom(dpy, "_NET_WM_WINDOW_OPACITY", False);
    char cm[32];
    snprintf(cm, sizeof cm, "_NET_WM_CM_S%d", scr);
    a_cm = XInternAtom(dpy, cm, False);
    a_clients = XInternAtom(dpy, "_NET_CLIENT_LIST", False);
    a_type = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE", False);
    a_desktop = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DESKTOP", False);
    a_dock = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DOCK", False);
    if (desktop_ready())
        return 0;               /* plocha uz bezi (napr. druhe spusteni) */

    /* Posledni snimek obrazovky (konec prihlaseni) jako pozadi okna: kopie na serveru, bez prenosu obrazu */
    unsigned w = (unsigned)ra.width, h = (unsigned)ra.height;
    Pixmap snap = XCreatePixmap(dpy, root, w, h, (unsigned)ra.depth);
    XGCValues gv;
    gv.subwindow_mode = IncludeInferiors;
    GC gc = XCreateGC(dpy, root, GCSubwindowMode, &gv);
    XCopyArea(dpy, root, snap, gc, 0, 0, w, h, 0, 0);
    XFreeGC(dpy, gc);
    restore_frame(snap, ra.visual, ra.depth, w, h, frame_is_black(snap, w, h));

    XSetWindowAttributes a;
    a.override_redirect = True;
    a.background_pixmap = snap;
    win = XCreateWindow(dpy, root, 0, 0, w, h, 0, ra.depth, InputOutput, ra.visual,
                        CWOverrideRedirect | CWBackPixmap, &a);
    XStoreName(dpy, win, "luxos-login-cover");
    /* Mys a klavesnice jdou skrz: prechod nikdy neblokuje praci */
    if (XFixesQueryExtension(dpy, &xf_event, &xf_error)) {
        XserverRegion empty = XFixesCreateRegion(dpy, NULL, 0);
        XFixesSetWindowShapeRegion(dpy, win, ShapeInput, 0, 0, empty);
        XFixesDestroyRegion(dpy, empty);
    }
    /* Nepatrne mene nez nepruhledne: kompozitor (xfwm4 unredirect_overlays) jinak okno pres celou
     * obrazovku muze vynechat (bez rozplynuti); obraz je stejny */
    set_opacity(0xfffffffeUL);
    XMapRaised(dpy, win);
    XSelectInput(dpy, root, PropertyChangeMask);
    XFlush(dpy);

    int motion = motion_allowed(), check = 1;
    long start = now_ms(), ready_at = 0;
    struct pollfd pfd = {ConnectionNumber(dpy), POLLIN, 0};
    for (;;) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            if (ev.type == PropertyNotify && ev.xproperty.atom == a_clients)
                check = 1;
        }
        long t = now_ms();
        if (check && !ready_at && desktop_ready())
            ready_at = t;
        check = 0;
        if (t - start >= LOGIN_MAX_MS)
            break;
        if (ready_at && t - ready_at >= LOGIN_SETTLE_MS
            && (!motion || XGetSelectionOwner(dpy, a_cm) != None || t - ready_at >= LOGIN_SETTLE_MS + LOGIN_WAIT_CM_MS))
            break;
        XRaiseWindow(dpy, win);     /* lista a plocha se mapuji nad nas - drzet navrchu */
        XFlush(dpy);
        if (poll(&pfd, 1, 40) < 0 && errno != EINTR)
            return 0;
        if (pfd.revents & (POLLHUP | POLLERR))
            return 0;
    }

    if (motion && XGetSelectionOwner(dpy, a_cm) != None) {
        for (int i = LOGIN_FADE_STEPS - 1; i > 0; i--) {
            double p = (double)i / LOGIN_FADE_STEPS;
            set_opacity((unsigned long)(0xffffffffUL * (p * p)));   /* rychle odkryti, jemny konec */
            XRaiseWindow(dpy, win);
            XFlush(dpy);
            sleep_ms(LOGIN_FADE_MS / LOGIN_FADE_STEPS);
            if (XGetSelectionOwner(dpy, a_cm) == None)
                break;
        }
    }
    XDestroyWindow(dpy, win);
    XFreePixmap(dpy, snap);
    XCloseDisplay(dpy);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "--login") == 0)
        return login_main();
    return logout_main();
}
