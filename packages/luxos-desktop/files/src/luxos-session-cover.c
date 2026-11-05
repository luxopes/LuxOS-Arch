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
 * pred startem relace): posledni snimek prihlasovaci obrazovky (jen ztmavena tapeta) s tenkym barem prubehu
 * jako pri startu systemu (Plymouth) na miste pole pro heslo zakryje skladani plochy. Jakmile je plocha (okno typu DESKTOP) opravdu
 * vykreslena (obsah jejiho presmerovaneho okna uz je obraz a nemeni se) a lista/Dock (DOCK) taky, okno se
 * behem ~0,28 s rozplyne do hotove plochy (pruhlednost pres kompozitor xfwm4) a skonci. Na nic neceka:
 * vstup (mys, klavesnice) jde skrz (prazdny vstupni tvar), nejdele po LOGIN_MAX_MS konci vzdy. Bez animace
 * (jen odkryti) pri zapnutem Sporici baterie (~/.config/luxos/powersaver) nebo vypnutych animacich (xsettings).
 *
 * Proc ne cerna (hlaseni ze skutecneho hardwaru, overeno v Xvfb + xfwm4 se snimanim obrazovky):
 *  - okno zakryti je v prekryti kompozitoru (Composite overlay window), ne na korenovem okne: xfwm4 okno pres
 *    celou obrazovku, ktere existovalo uz pred startem kompozitoru, casto vubec nevykreslil (jeho poradi
 *    oken se rozeslo se serverem, nepruhledne okno presmerovani zrusil a prekryti nechal nad nim) - pak
 *    byla videt cerna (koren bez tapety) a nevykreslena plocha nad zakrytim. V prekryti jsme nad vsim, co
 *    kompozitor kresli, a jeho start ani poradi oken nic nezmeni. Rozplynuti dela bezne pruhledne okno,
 *    ktere kompozitor sklada az nad hotovou plochu.
 *  - drive konec uz ~0,2 s po namapovani plochy a listy: xfdesktop tapetu nacita na pozadi, takze se
 *    odkryla cerna plocha. Ted se ceka na obraz plochy (s kompozitorem jde obsah okna precist i pod nami).
 *  - greeter tesne pred spustenim relace nechava snimek na obrazovce v okne, ktere server drzi i po jeho
 *    skonceni (FrameHold v luxos-greeter, _LUXOS_LOGIN_HOLD) - zadna mezera mezi koncem greeteru a startem
 *    zakryti. Prevezme ho --login (XKillClient), jine relace a pojistka v luxos-session ho uvolni (--release).
 *
 * Snimek ze serveru nemusi prezit: bez glamor (napr. QEMU bochs + llvmpipe) ovladac modesetting
 * "-background none" neumi. Proto greeter pred spustenim relace ulozi stejny snimek do sdilene slozky
 * LightDM (/var/lib/lightdm-data/<uzivatel>, LUXOS_LOGIN_FRAME_DIR pro testy): login-frame.raw (cela
 * obrazovka, nejvys 2 min stary, po nacteni se smaze) a login-frame-small.raw (mala rozmazana tapeta,
 * zustava). Je-li zachyceny snimek cerny, pouzije se login-frame.raw, jinak zvetsena rozmazana tapeta.
 * Format: "LUXFRAME1 <sirka> <vyska>\n" + sirka*vyska*4 bajtu BGRx (cairo RGB24 na little-endian).
 */
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/shape.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrandr.h>
#include <X11/extensions/Xrender.h>
#include <cairo/cairo-xlib-xrender.h>
#include <cairo/cairo-xlib.h>
#include <cairo/cairo.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <pthread.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/timerfd.h>
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

#define LOGIN_FADE_MS 280
#define LOGIN_FADE_STEPS 14
#define LOGIN_SCAN_MS 90         /* jak casto kontrolovat, zda je plocha vykreslena */
#define LOGIN_NOCM_SETTLE_MS 400 /* bez kompozitoru okna nejdou precist: plocha a lista namapovane + chvile */
#define LOGIN_WAIT_CM_MS 1500    /* bez kompozitoru jeste chvili pockat, zda nezacne (rozplynuti) */
#define LOGIN_PAINT_MAX_MS 4000  /* plocha namapovana, ale "nevykreslena" (napr. cerna barva pozadi) */
#define LOGIN_SOLID_MS 1200      /* jednobarevna plocha (barva misto tapety) stabilni tak dlouho = hotovo */
#define LOGIN_DOCK_MAX_MS 1500   /* skryty Dock (automaticke skryvani) nemusi nic vykreslit */
#define LOGIN_NO_WM_MS 3000      /* bez spravce oken (_NET_SUPPORTING_WM_CHECK) tak dlouho: relace se nespousti */
#define LOGIN_MAX_MS 10000       /* vzdy skoncit (relace bez listy, jine prostredi) */

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

static int x_errors;

static int ignore_errors(Display *d, XErrorEvent *e)
{
    (void)e;
    if (d == dpy)
        x_errors++;             /* jen hlavni spojeni (vlakno baru kresli do okna, ktere uz mohlo zaniknout) */
    return 0;                   /* okno ze seznamu mezitim zaniklo */
}

/* ---- posledni snimek greeteru drzeny serverem ---------------------------------------------------- */

/* Greeter tesne pred spustenim relace prekryje obrazovku oknem se svym poslednim snimkem a na svem
 * druhem spojeni zapne XSetCloseDownMode(RetainPermanent): okno tak prezije konec greeteru (i na
 * serveru bez "-background none") a zmizi, az ho prevezme nase okno (XKillClient). Okno je v
 * _LUXOS_LOGIN_HOLD na korenovem okne; bere se jen okno override-redirect s nazvem luxos-login-hold. */
static Atom a_hold;

static Window held_window(void)
{
    Atom type;
    int fmt;
    unsigned long n = 0, rest;
    unsigned char *data = NULL;
    Window w = None;
    if (XGetWindowProperty(dpy, root, a_hold, 0, 1, False, XA_WINDOW, &type, &fmt, &n, &rest, &data) == Success && data) {
        if (type == XA_WINDOW && fmt == 32 && n == 1)
            w = (Window) * (unsigned long *)data;
        XFree(data);
    }
    if (w == None)
        return None;
    XWindowAttributes wa;
    char *name = NULL;
    int ok = XGetWindowAttributes(dpy, w, &wa) && wa.override_redirect && XFetchName(dpy, w, &name) && name
             && strcmp(name, "luxos-login-hold") == 0;
    if (name)
        XFree(name);
    return ok ? w : None;
}

static void release_held(Window w)
{
    if (w != None)
        XKillClient(dpy, w);        /* zrusi vsechny zdroje drzene po skoncenem greeteru */
    XDeleteProperty(dpy, root, a_hold);
    XSync(dpy, False);
}

/* --release: relace jina nez LuxOS/Xfce (60-luxos-login-cover.sh) - jen uvolnit snimek greeteru */
static int release_main(void)
{
    dpy = XOpenDisplay(NULL);
    if (!dpy)
        return 1;
    XSetErrorHandler(ignore_errors);
    root = DefaultRootWindow(dpy);
    a_hold = XInternAtom(dpy, "_LUXOS_LOGIN_HOLD", False);
    release_held(held_window());
    XCloseDisplay(dpy);
    return 0;
}

/* ---- plocha pripravena? ------------------------------------------------------------------------- */

static Atom a_clients, a_type, a_desktop, a_dock;

typedef struct {
    int desk, dock;              /* pocet oken plochy (DESKTOP) a list (DOCK) mezi okny spravce oken */
    int desk_image, desk_filled; /* kolik oken plochy ma obraz (ruzne pixely) / aspon neco nenuloveho */
    int dock_painted;
    unsigned long desk_sum;      /* kontrolni soucet obsahu plochy (stabilni = dokresleno) */
} Scan;

/* Obsah okna (s kompozitorem je presmerovane, XGetImage cte jeho vlastni pixmapu i pod nasim oknem):
 * podil nenulovych pixelu v peti radcich (nevykreslene okno ma pixmapu vyplnenou nulami), soucet a
 * zda jsou vsechny stejne (jednobarevne). -1 = okno neni zobrazene. */
static double window_painted(Window w, unsigned long *sum, int *uniform)
{
    XWindowAttributes wa;
    if (!XGetWindowAttributes(dpy, w, &wa) || wa.map_state != IsViewable || wa.width < 1 || wa.height < 1)
        return -1;
    /* Jen presmerovane okno ma vlastni obsah (jinak by se cetlo, co je na obrazovce - nase okno).
     * Presmerovane je okno nejvyssi urovne (ramecek spravce oken), XCompositeNameWindowPixmap jinde
     * skonci chybou BadMatch */
    Window top = w, parent = w, r, *kids = NULL;
    unsigned nk;
    for (int depth = 0; depth < 16 && parent != root; depth++) {
        top = parent;
        if (!XQueryTree(dpy, top, &r, &parent, &kids, &nk))
            return -1;
        if (kids)
            XFree(kids);
    }
    XSync(dpy, False);
    int errs = x_errors;
    Pixmap own = XCompositeNameWindowPixmap(dpy, top);
    XSync(dpy, False);
    if (x_errors != errs)
        return -1;
    XFreePixmap(dpy, own);
    long nz = 0, tot = 0;
    unsigned long h = 1469598103UL, first = 0;
    int uni = 1;
    /* Pet radku nejdriv na serveru do jedne male pixmapy a pak jedno XGetImage: s GPU (glamor) kazde
     * cteni obrazu ceka, az GPU dokresli vsechno rozpracovane, a cely X server (i nas bar) mezitim stoji */
    Pixmap rows = XCreatePixmap(dpy, root, (unsigned)wa.width, 5, (unsigned)wa.depth);
    XGCValues gv;
    gv.graphics_exposures = False;
    gv.subwindow_mode = IncludeInferiors;   /* jako XGetImage okna: i obsah podoken */
    GC gc = XCreateGC(dpy, rows, GCGraphicsExposures | GCSubwindowMode, &gv);
    for (int k = 1; k <= 5; k++)
        XCopyArea(dpy, w, rows, gc, 0, wa.height * k / 6, (unsigned)wa.width, 1, 0, k - 1);
    XImage *im = XGetImage(dpy, rows, 0, 0, (unsigned)wa.width, 5, AllPlanes, ZPixmap);
    XFreeGC(dpy, gc);
    XFreePixmap(dpy, rows);
    for (int k = 0; im && k < 5; k++) {
        for (int x = 0; x < wa.width; x += 3) {
            unsigned long p = XGetPixel(im, x, k);
            if (!tot)
                first = p;
            else if (p != first)
                uni = 0;
            tot++;
            nz += p != 0;
            h = (h ^ p) * 1099511628211UL;
        }
    }
    if (im)
        XDestroyImage(im);
    if (sum)
        *sum = h;
    if (uniform)
        *uniform = uni;
    return tot ? (double)nz / (double)tot : -1;
}

/* Okna plochy a list; s pixels=1 i jejich obsah (jen s kompozitorem - jinak by se cetlo nase okno) */
static void scan(Scan *s, int pixels)
{
    memset(s, 0, sizeof *s);
    Atom type;
    int fmt;
    unsigned long n = 0, rest;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, root, a_clients, 0, 4096, False, AnyPropertyType, &type, &fmt, &n, &rest, &data) != Success
        || !data)
        return;
    Window *w = (Window *)data;
    for (unsigned long i = 0; i < n; i++) {
        unsigned char *t = NULL;
        unsigned long tn = 0;
        int desk = 0, dock = 0;
        if (XGetWindowProperty(dpy, w[i], a_type, 0, 8, False, XA_ATOM, &type, &fmt, &tn, &rest, &t) == Success && t) {
            Atom *at = (Atom *)t;
            for (unsigned long j = 0; j < tn; j++) {
                desk |= at[j] == a_desktop;
                dock |= at[j] == a_dock;
            }
            XFree(t);
        }
        if (!desk && !dock)
            continue;
        s->desk += desk;
        s->dock += dock;
        if (!pixels)
            continue;
        unsigned long sum = 0;
        int uni = 1;
        double p = window_painted(w[i], &sum, &uni);
        if (desk) {
            s->desk_sum = s->desk_sum * 31 + sum;
            s->desk_filled += p >= 0.5;
            s->desk_image += p >= 0.5 && !uni;
        } else {
            s->dock_painted += p > 0;
        }
    }
    XFree(data);
}

/* ---- prubeh nacitani (stejny bar jako pri startu systemu) --------------------------------------- */

/* Tenky zaobleny bar jako v Plymouth (luxos-branding/files/plymouth: draha 220x6 bodu, svetla vypln, ktera
 * plynule dobiha k cili) na miste pole pro heslo - i pri startu systemu je pole hesla (LUKS) na miste
 * baru. Start systemu konci plnym barem, prihlaseni ukazuje stejny bar, ktery se plni podle skutecneho
 * postupu relace (spravce oken, plocha a lista v seznamu oken, plocha vykreslena, hotovo) a mezi fazemi
 * se pomalu sune dal, takze nikdy nestoji.
 *
 * Proc se drive kolecko trhalo (skutecny hardware, Ryzen 5 5500U): kreslilo se ve stejne smycce, ktera
 * kontroluje plochu - kazda kontrola (kazdych 90 ms a po kazde zmene seznamu oken) dela desitky
 * synchronnich dotazu na X server (XGetWindowProperty, XQueryTree, XSync, XGetImage) a X server je pri
 * startu relace zahlceny (xfwm4 + kompozitor, panel, Dock, hub, xfdesktop), takze kontrola trvala
 * desitky ms a snimky vypadly; nice(+2) proti procesum relace na vsech jadrech k tomu ubral cas
 * procesoru. Ted:
 *  - kresli samostatne vlakno s vlastnim spojenim na X server, ktere nikdy neceka na odpoved serveru
 *    (zadne XSync ani dotazy, jen XFlush), kontrola plochy v hlavnim vlakne kresleni nezdrzi
 *  - takt timerfd (CLOCK_MONOTONIC, 60 Hz), poloha vyplne podle skutecneho casu: vypadly snimek jen
 *    preskoci mezikrok, animace se nezpomali
 *  - draha (s vyrezem snimku pod ni) a vypln jsou predem pripravene pixmapy na serveru: snimek = jedno
 *    male kopirovani, jedno skladani XRender (vypln oriznuta tvarem drahy, posun o zlomky bodu) a
 *    kopirovani 220x6 bodu do okna; zadne cairo za behu, zadne prenosy obrazu
 *  - bez nice: bezna priorita jako ostatni procesy relace */

#define BAR_W 220
#define BAR_H 6
#define BAR_PERIOD_NS 16666667L    /* 60 Hz */
#define BAR_FADE_IN_MS 250
#define BAR_TAU_MS 300.0           /* jak rychle vypln dobiha k cili (Plymouth: 8 % rozdilu za snimek) */
#define BAR_FINISH_TAU_MS 70.0     /* hotovo: rychle do konce (Plymouth "luxos-finish") */
#define BAR_CREEP_MS 2500.0        /* v kazde fazi se pomalu blizi k dalsi (nikdy nestoji) */
#define BAR_STAGES 5               /* start, spravce oken, plocha a lista, plocha vykreslena, hotovo */
#define BAR_LOG_MAX 4096

static const double bar_level[BAR_STAGES] = {0.04, 0.30, 0.55, 0.80, 1.0};

typedef struct {
    int x, y, w, h;
    Pixmap snap;                /* snimek obrazovky (pozadi okna), vlastni ho hlavni vlakno */
    VisualID visual;            /* Visual* plati jen pro spojeni, ktere ho vratilo */
    int depth;
    pthread_t thread;
    int running;
    pthread_mutex_t lock;       /* chrani nasledujici sdilene hodnoty */
    Window targets[2];          /* kam kreslit (okno v prekryti, pri predani i pruhledne okno) */
    int ntargets;
    long stage_at[BAR_STAGES];  /* kdy faze zacala (ms od startu), 0 = jeste ne */
    long start;
    int quit;
    int log_fd;                 /* LUXOS_COVER_FRAMELOG: casy snimku (mereni trhani) */
    int bench;                  /* LUXOS_COVER_BENCH: vypln stale v pohybu (jen testy) */
} Bar;

/* Misto pole pro heslo (pod avatarem) na hlavnim monitoru - stejne rozmery jako luxos-greeter */
static void bar_geometry(Bar *b, int sw, int sh)
{
    int mx = 0, my = 0, mw = sw, mh = sh, ev, er, n = 0;
    if (XRRQueryExtension(dpy, &ev, &er)) {
        XRRMonitorInfo *m = XRRGetMonitors(dpy, root, True, &n);
        if (m && n > 0) {
            int k = 0;
            for (int i = 0; i < n; i++)
                if (m[i].primary)
                    k = i;
            mx = m[k].x, my = m[k].y, mw = m[k].width, mh = m[k].height;
        }
        if (m)
            XRRFreeMonitors(m);
    }
    double u = mh / 1080.0;
    if (u < 0.55)
        u = 0.55;
    /* Plymouth kresli bar v logickych bodech (220x6, na HiDPI dvojnasobek) - stejne */
    int k = (int)(mh / 1080.0 + 0.5);
    if (k < 1)
        k = 1;
    b->w = BAR_W * k;
    b->h = BAR_H * k;
    b->x = mx + mw / 2 - b->w / 2;
    b->y = my + mh - (int)(204 * u + 0.5) - b->h / 2;
}

/* Postup relace (hlavni vlakno): faze 1..4, t = ms od startu */
static void bar_stage(Bar *b, int stage, long t)
{
    pthread_mutex_lock(&b->lock);
    for (int i = 1; i <= stage && i < BAR_STAGES; i++)
        if (!b->stage_at[i])
            b->stage_at[i] = t > 0 ? t : 1;
    pthread_mutex_unlock(&b->lock);
}

static void bar_targets(Bar *b, Window a, Window c)
{
    pthread_mutex_lock(&b->lock);
    b->targets[0] = a;
    b->targets[1] = c;
    b->ntargets = c != None ? 2 : 1;
    pthread_mutex_unlock(&b->lock);
}

/* Cil vyplne v case t (ms od startu): uroven posledni dosazene faze a pomale priblizovani k dalsi */
static double bar_goal(const long *stage_at, long t, int *last)
{
    int k = 0;
    for (int i = 1; i < BAR_STAGES; i++)
        if (stage_at[i] && stage_at[i] <= t)
            k = i;
    *last = k;
    if (k == BAR_STAGES - 1)
        return 1.0;
    long since = t - (k ? stage_at[k] : 0);
    double a = bar_level[k], next = bar_level[k + 1];
    return a + (next - a) * 0.85 * (1.0 - exp(-(double)since / BAR_CREEP_MS));
}

/* Zaobleny obdelnik (pulkruhy na koncich) jako rounded() v make-variants.py */
static void rounded_path(cairo_t *cr, double w, double h)
{
    double r = h / 2;
    cairo_new_path(cr);
    cairo_arc(cr, w - r, r, r, -M_PI / 2, M_PI / 2);
    cairo_arc(cr, r, r, r, M_PI / 2, 3 * M_PI / 2);
    cairo_close_path(cr);
}

/* Pixmapa ARGB32 nebo A8 vyplnena zaoblenym obdelnikem dane barvy (jednou pri startu) */
static Picture rounded_picture(Display *d, Pixmap p, int a8, int w, int h, double r, double g, double bl, double a)
{
    XRenderPictFormat *f = XRenderFindStandardFormat(d, a8 ? PictStandardA8 : PictStandardARGB32);
    cairo_surface_t *cs = cairo_xlib_surface_create_with_xrender_format(d, p, DefaultScreenOfDisplay(d), f, w, h);
    cairo_t *cr = cairo_create(cs);
    cairo_set_operator(cr, CAIRO_OPERATOR_SOURCE);
    cairo_set_source_rgba(cr, 0, 0, 0, 0);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
    rounded_path(cr, w, h);
    cairo_set_source_rgba(cr, r, g, bl, a);
    cairo_fill(cr);
    cairo_destroy(cr);
    cairo_surface_flush(cs);
    cairo_surface_destroy(cs);
    return XRenderCreatePicture(d, p, f, 0, NULL);
}

static void *bar_thread(void *arg)
{
    Bar *b = arg;
    Display *d = XOpenDisplay(NULL);
    if (!d)
        return NULL;
    int w = b->w, h = b->h;
    Window r = DefaultRootWindow(d);
    XGCValues gv;
    gv.graphics_exposures = False;  /* jinak po kazdem XCopyArea udalost NoExpose */
    GC gc = XCreateGC(d, r, GCGraphicsExposures, &gv);
    XVisualInfo vt, *vi;
    int nvi = 0;
    vt.visualid = b->visual;
    vi = XGetVisualInfo(d, VisualIDMask, &vt, &nvi);
    XRenderPictFormat *vf = vi && nvi ? XRenderFindVisualFormat(d, vi->visual) : NULL;
    if (vi)
        XFree(vi);
    if (!vf) {
        XCloseDisplay(d);
        return NULL;            /* bez XRender jen snimek bez baru */
    }

    /* Pozadi: vyrez snimku pod barem + draha (tlumena bila jako kruh drive - snimek je ztmavena tapeta) */
    Pixmap base = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, (unsigned)b->depth);
    XCopyArea(d, b->snap, base, gc, b->x, b->y, (unsigned)w, (unsigned)h, 0, 0);
    Pixmap trackp = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, 32);
    Pixmap fillp = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, 32);
    Pixmap maskp = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, 8);
    Picture track = rounded_picture(d, trackp, 0, w, h, 1, 1, 1, 0.22);
    Picture fill = rounded_picture(d, fillp, 0, w, h, 0xee / 255.0, 0xf4 / 255.0, 1.0, 0.95);   /* bar-fill */
    Picture mask = rounded_picture(d, maskp, 1, w, h, 0, 0, 0, 1);                             /* tvar drahy */
    Picture basep = XRenderCreatePicture(d, base, vf, 0, NULL);
    XRenderComposite(d, PictOpOver, track, None, basep, 0, 0, 0, 0, 0, 0, (unsigned)w, (unsigned)h);
    XRenderSetPictureFilter(d, fill, FilterBilinear, NULL, 0);     /* posun o zlomky bodu */

    /* Zadni buffery: hotovy snimek baru, pri prvnim zobrazeni jeste prolnuti se snimkem */
    Pixmap back = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, (unsigned)b->depth);
    Pixmap back2 = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, (unsigned)b->depth);
    Picture backp = XRenderCreatePicture(d, back, vf, 0, NULL), back2p = XRenderCreatePicture(d, back2, vf, 0, NULL);
    XRenderColor half = {0, 0, 0, 0};
    Picture fade = XRenderCreateSolidFill(d, &half);
    XFlush(d);

    int tfd = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC);
    struct itimerspec its = {{0, BAR_PERIOD_NS}, {0, BAR_PERIOD_NS}};
    if (tfd >= 0)
        timerfd_settime(tfd, 0, &its, NULL);
    static long logbuf[BAR_LOG_MAX];
    int nlog = 0;
    double shown = 0;
    long prev = -1;
    for (;;) {
        pthread_mutex_lock(&b->lock);
        int quit = b->quit, nt = b->ntargets;
        Window tg[2] = {b->targets[0], b->targets[1]};
        long st[BAR_STAGES];
        memcpy(st, b->stage_at, sizeof st);
        pthread_mutex_unlock(&b->lock);
        if (quit)
            break;
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        long tus = ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
        long t = tus / 1000L - b->start;
        if (nlog < BAR_LOG_MAX && b->log_fd >= 0)
            logbuf[nlog++] = tus;

        /* Poloha z hodin: exponencialni dobihani k cili podle skutecne uplynule doby (vypadly snimek =
         * stejny vysledek, jen bez mezikroku) */
        int last;
        double goal = bar_goal(st, t, &last);
        long dt = prev < 0 ? 0 : t - prev;
        prev = t;
        double tau = last == BAR_STAGES - 1 ? BAR_FINISH_TAU_MS : BAR_TAU_MS;
        if (goal > shown)
            shown += (goal - shown) * (1.0 - exp(-(double)dt / tau));
        double fw = shown * w;
        if (b->bench)               /* mereni trhani: vypln stale bezi tam a zpet (kazdy snimek je jiny) */
            fw = h + (w - h) * fabs(fmod(t / 2000.0, 2.0) - 1.0);
        if (fw < h)
            fw = h;                 /* aspon kulaty zacatek */
        double alpha = t >= BAR_FADE_IN_MS ? 1.0 : (double)(t < 0 ? 0 : t) / BAR_FADE_IN_MS;

        XCopyArea(d, base, back, gc, 0, 0, (unsigned)w, (unsigned)h, 0, 0);
        /* vypln posunuta doleva o (w - fw): jeji kulaty konec je v miste postupu, levy konec orizne tvar
         * drahy (maska) */
        XTransform tr = {{{XDoubleToFixed(1), 0, XDoubleToFixed(w - fw)},
                          {0, XDoubleToFixed(1), 0},
                          {0, 0, XDoubleToFixed(1)}}};
        XRenderSetPictureTransform(d, fill, &tr);
        XRenderComposite(d, PictOpOver, fill, mask, backp, 0, 0, 0, 0, 0, 0, (unsigned)w, (unsigned)h);
        Pixmap out = back;
        if (alpha < 1) {
            XCopyArea(d, b->snap, back2, gc, b->x, b->y, (unsigned)w, (unsigned)h, 0, 0);
            XRenderColor c = {0, 0, 0, (unsigned short)(alpha * 0xffff)};
            XRenderFreePicture(d, fade);
            fade = XRenderCreateSolidFill(d, &c);
            XRenderComposite(d, PictOpOver, backp, fade, back2p, 0, 0, 0, 0, 0, 0, (unsigned)w, (unsigned)h);
            out = back2;
        }
        for (int i = 0; i < nt; i++)
            XCopyArea(d, out, tg[i], gc, 0, 0, (unsigned)w, (unsigned)h, b->x, b->y);
        XFlush(d);

        uint64_t n;
        if (tfd < 0 || (read(tfd, &n, sizeof n) < 0 && errno != EINTR))
            sleep_ms(16);
    }
    if (b->log_fd >= 0) {
        char line[32];
        for (int i = 0; i < nlog; i++) {
            int n = snprintf(line, sizeof line, "%ld\n", logbuf[i]);
            if (write(b->log_fd, line, (size_t)n) < 0)
                break;
        }
    }
    if (tfd >= 0)
        close(tfd);
    Picture pics[] = {track, fill, mask, basep, backp, back2p, fade};
    for (unsigned i = 0; i < sizeof pics / sizeof *pics; i++)
        XRenderFreePicture(d, pics[i]);
    Pixmap pms[] = {trackp, fillp, maskp, base, back, back2};
    for (unsigned i = 0; i < sizeof pms / sizeof *pms; i++)
        XFreePixmap(d, pms[i]);
    XFreeGC(d, gc);
    XSync(d, False);
    XCloseDisplay(d);
    return NULL;
}

static void bar_start(Bar *b, Pixmap snap, Visual *vis, int depth, int sw, int sh, Window target, long start)
{
    memset(b, 0, sizeof *b);
    bar_geometry(b, sw, sh);
    b->snap = snap;
    b->visual = XVisualIDFromVisual(vis);
    b->depth = depth;
    b->start = start;
    b->targets[0] = target;
    b->ntargets = 1;
    b->log_fd = -1;
    const char *log = getenv("LUXOS_COVER_FRAMELOG");
    if (log && *log)
        b->log_fd = open(log, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    b->bench = getenv("LUXOS_COVER_BENCH") != NULL;
    pthread_mutex_init(&b->lock, NULL);
    XSync(dpy, False);          /* snimek a okno musi na serveru existovat pred prvnim kreslenim */
    b->running = pthread_create(&b->thread, NULL, bar_thread, b) == 0;
}

static void bar_stop(Bar *b)
{
    if (b->running) {
        pthread_mutex_lock(&b->lock);
        b->quit = 1;
        pthread_mutex_unlock(&b->lock);
        pthread_join(b->thread, NULL);
        b->running = 0;
    }
    if (b->log_fd >= 0)
        close(b->log_fd);
    b->log_fd = -1;
    pthread_mutex_destroy(&b->lock);
}

static int login_debug;

static void dbg(long t, const char *fmt, ...)
{
    if (!login_debug)
        return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "%6ld ", t);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

/* Prazdny vstupni tvar: mys a klavesnice jdou skrz */
static void no_input(Window w)
{
    int xf_event, xf_error;
    if (XFixesQueryExtension(dpy, &xf_event, &xf_error)) {
        XserverRegion empty = XFixesCreateRegion(dpy, NULL, 0);
        XFixesSetWindowShapeRegion(dpy, w, ShapeInput, 0, 0, empty);
        XFixesDestroyRegion(dpy, empty);
    }
}

/* Okno s obrazkem pres celou obrazovku, mys a klavesnice jdou skrz (prechod nikdy neblokuje praci) */
static Window cover_window(Window parent, Pixmap bg, Visual *vis, int depth, unsigned w, unsigned h, int translucent)
{
    XSetWindowAttributes a;
    a.override_redirect = True;
    a.background_pixmap = bg;
    Window cw = XCreateWindow(dpy, parent, 0, 0, w, h, 0, depth, InputOutput, vis, CWOverrideRedirect | CWBackPixmap, &a);
    XStoreName(dpy, cw, "luxos-login-cover");
    no_input(cw);
    if (translucent) {
        /* nepatrne mene nez nepruhledne: kompozitor ho skladat musi (rozplynuti), obraz je stejny */
        unsigned long v = 0xfffffffeUL;
        XChangeProperty(dpy, cw, a_opacity, XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&v, 1);
    }
    return cw;
}

static int login_main(void)
{
    /* Bar kresli druhe vlakno s vlastnim spojenim (globalni stav Xlib musi byt pro vlakna pripraveny).
     * Bezna priorita (drive nice +2): bar je maly, ale nesmi cekat na procesor za procesy relace */
    XInitThreads();
    dpy = XOpenDisplay(NULL);
    if (!dpy)
        return 1;
    login_debug = getenv("LUXOS_COVER_DEBUG") != NULL;
    XSetErrorHandler(ignore_errors);
    int scr = DefaultScreen(dpy);
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
    a_hold = XInternAtom(dpy, "_LUXOS_LOGIN_HOLD", False);
    /* Jen jedno zakryti: skript xinitrc.d nacita /etc/lightdm/Xsession a pak znovu startxfce4
     * (/etc/xdg/xfce4/xinitrc). Dve zakryti v prekryti kompozitoru se navzajem zvedala nad sebe (kazde
     * reaguje na ConfigureNotify toho druheho), druhe meli ve snimku zamrzle kolecko prvniho a obe kreslila
     * a kontrolovala plochu - dvojnasobna prace X serveru a trhani. Vlastnik vyberu _LUXOS_LOGIN_COVER =
     * bezici zakryti; posledni nastaveni vyhrava, takze i pri soubehu zustane jen jedno. */
    Atom a_single = XInternAtom(dpy, "_LUXOS_LOGIN_COVER", False);
    if (XGetSelectionOwner(dpy, a_single) != None) {
        dbg(0, "another cover is running");
        return 0;
    }
    Window owner = XCreateSimpleWindow(dpy, root, -10, -10, 1, 1, 0, 0, 0);
    XSetSelectionOwner(dpy, a_single, owner, CurrentTime);
    if (XGetSelectionOwner(dpy, a_single) != owner) {
        dbg(0, "another cover is running");
        return 0;
    }
    Window held = held_window();
    if (login_debug) {
        Atom type;
        int fmt;
        unsigned long n = 0, rest;
        unsigned char *data = NULL;
        unsigned long v = 0;
        if (XGetWindowProperty(dpy, root, a_hold, 0, 1, False, AnyPropertyType, &type, &fmt, &n, &rest, &data) == Success
            && data) {
            if (n == 1 && fmt == 32)
                v = *(unsigned long *)data;
            XFree(data);
        }
        dbg(0, "greeter frame property=%lx (n=%lu) usable=%lx", v, n, held);
    }
    Scan sc;
    scan(&sc, 0);
    if (sc.desk && sc.dock) {
        release_held(held);
        return 0;               /* plocha uz bezi (napr. druhe spusteni) */
    }

    /* Posledni snimek obrazovky (konec prihlaseni, pripadne okno drzene po greeteru) jako pozadi okna:
     * kopie na serveru, bez prenosu obrazu */
    unsigned w = (unsigned)ra.width, h = (unsigned)ra.height;
    Pixmap snap = XCreatePixmap(dpy, root, w, h, (unsigned)ra.depth);
    XGCValues gv;
    gv.subwindow_mode = IncludeInferiors;
    GC gc = XCreateGC(dpy, root, GCSubwindowMode, &gv);
    XCopyArea(dpy, root, snap, gc, 0, 0, w, h, 0, 0);
    XFreeGC(dpy, gc);
    int black = frame_is_black(snap, w, h);
    int restored = restore_frame(snap, ra.visual, ra.depth, w, h, black);
    dbg(0, "screen black=%d restored-from-file=%d", black, restored);

    /* Okno uvnitr prekryti kompozitoru (Composite overlay window): je nad vsemi okny i nad tim, co kresli
     * kompozitor (xfwm4 kresli do sveho okna v prekryti, my jsme nad nim), a kompozitor ho nesklada - start
     * kompozitoru, jeho poradi oken ani nevykreslene okno plochy nic nezmeni. Okno pres celou obrazovku
     * primo na korenovem okne xfwm4 pri startu kompozitoru casto nevykreslil (cerna obrazovka: pruhledne
     * okno vynechal, nepruhledne presmerovani zrusil, ale prekryti nechal nad nim). Bez Composite jako
     * drive okno na korenovem okne. */
    int c_ev, c_err;
    Window cow = None;
    if (XCompositeQueryExtension(dpy, &c_ev, &c_err)) {
        cow = XCompositeGetOverlayWindow(dpy, root);
        no_input(cow);          /* prekryti bez kompozitoru by jinak bralo mys */
    }
    Window parent = cow != None ? cow : root;
    win = cover_window(parent, snap, ra.visual, ra.depth, w, h, 0);
    if (cow == None)
        set_opacity(0xfffffffeUL);
    XMapRaised(dpy, win);
    XSync(dpy, False);
    /* Nase okno uz je na obrazovce (pozadi kresli server hned pri namapovani) - snimek greeteru uvolnit */
    if (held != None)
        release_held(held);
    /* Kompozitor si v prekryti mapuje sve okno, bez Composite se lista, Dock a plocha mapuji nad nas:
     * hned zpet navrch (ne az pri dalsim kole smycky) */
    XSelectInput(dpy, root, PropertyChangeMask | (cow == None ? SubstructureNotifyMask : 0));
    if (cow != None)
        XSelectInput(dpy, cow, SubstructureNotifyMask);
    int motion = motion_allowed();
    long start = now_ms(), listed_at = 0, ready_at = 0, last_scan = 0, image_at = 0, solid_at = 0;
    Bar bar;
    bar_start(&bar, snap, ra.visual, ra.depth, (int)w, (int)h, win, start);
    Atom a_wm = XInternAtom(dpy, "_NET_SUPPORTING_WM_CHECK", False);
    int wm_seen = 0;
    unsigned long last_sum = 0;
    int check = 1;
    dbg(0, "start held=%lx motion=%d", held, motion);
    struct pollfd pfd = {ConnectionNumber(dpy), POLLIN, 0};
    for (;;) {
        int raise = 0;
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            if (ev.type == PropertyNotify && ev.xproperty.atom == a_clients)
                check = 1;
            else if (ev.type == MapNotify && ev.xmap.window != win)
                raise = 1;
            else if (ev.type == ConfigureNotify && ev.xconfigure.window != win)
                raise = 1;
            else if (ev.type == PropertyNotify && ev.xproperty.atom == a_wm)
                wm_seen = 1;
        }
        if (wm_seen)
            bar_stage(&bar, 1, now_ms() - start);
        if (raise) {
            XRaiseWindow(dpy, win);
            XFlush(dpy);
        }
        long t = now_ms();
        if (t - start >= LOGIN_MAX_MS) {
            dbg(t - start, "timeout");
            break;
        }
        if (!wm_seen && !listed_at && t - start >= LOGIN_NO_WM_MS) {
            unsigned char *d = NULL;
            Atom type;
            int fmt;
            unsigned long n = 0, rest;
            if (XGetWindowProperty(dpy, root, a_wm, 0, 1, False, AnyPropertyType, &type, &fmt, &n, &rest, &d) == Success && d)
                XFree(d);
            wm_seen = n > 0;
            if (!wm_seen) {
                dbg(t - start, "no window manager - giving up");
                break;
            }
        }
        if (!ready_at && (check || t - last_scan >= LOGIN_SCAN_MS)) {
            int have_cm = XGetSelectionOwner(dpy, a_cm) != None;
            scan(&sc, have_cm);
            last_scan = t;
            check = 0;
            if (sc.desk && sc.dock && !listed_at) {
                listed_at = t;
                bar_stage(&bar, 2, t - start);
            }
            if (listed_at && have_cm) {
                /* plocha s obrazem, ktery se uz nemeni (dokreslena tapeta), a vykreslena lista */
                int stable = sc.desk_sum == last_sum;
                if (sc.desk_image == sc.desk && stable && !image_at)
                    image_at = t;
                if (sc.desk_filled == sc.desk && stable) {
                    if (!solid_at)
                        solid_at = t;
                } else {
                    solid_at = 0;
                }
                if (!stable)
                    image_at = 0;
                int desk_ok = image_at || (solid_at && t - solid_at >= LOGIN_SOLID_MS)
                              || t - listed_at >= LOGIN_PAINT_MAX_MS;
                int dock_ok = sc.dock_painted == sc.dock || (sc.dock_painted && t - listed_at >= LOGIN_DOCK_MAX_MS)
                              || t - listed_at >= LOGIN_PAINT_MAX_MS;
                dbg(t - start, "cm desk=%d image=%d filled=%d stable=%d dock=%d/%d", sc.desk, sc.desk_image,
                    sc.desk_filled, stable, sc.dock_painted, sc.dock);
                if (desk_ok)
                    bar_stage(&bar, 3, t - start);
                if (desk_ok && dock_ok)
                    ready_at = t;
            } else if (listed_at && t - listed_at >= LOGIN_NOCM_SETTLE_MS
                       && (!motion || t - listed_at >= LOGIN_NOCM_SETTLE_MS + LOGIN_WAIT_CM_MS)) {
                dbg(t - start, "ready without compositor");
                ready_at = t;
            }
            last_sum = sc.desk_sum;
            if (ready_at)
                dbg(t - start, "ready");
        }
        if (ready_at) {
            bar_stage(&bar, 4, ready_at - start);   /* bar dobehne do konce behem rozplynuti */
            break;
        }
        /* bar kresli vlastni vlakno - tady jen udalosti a dalsi kontrola plochy */
        long wait = LOGIN_SCAN_MS - (now_ms() - last_scan);
        if (poll(&pfd, 1, (int)(wait < 1 ? 1 : wait)) < 0 && errno != EINTR)
            return 0;
        if (pfd.revents & (POLLHUP | POLLERR))
            return 0;
    }

    if (motion && XGetSelectionOwner(dpy, a_cm) != None) {
        /* Rozplynuti: pod nasim oknem se namapuje bezne (pruhledne) okno se stejnym obrazem, ktere kompozitor
         * sklada nad hotovou plochu; az ho ma vykreslene (par snimku), okno v prekryti zmizi a rozplyne
         * se to pruhledne */
        long f0 = now_ms();
        if (cow != None) {
            Window fader = cover_window(root, snap, ra.visual, ra.depth, w, h, 1);
            XMapRaised(dpy, fader);
            XSync(dpy, False);
            /* bar se kresli do obou oken, nez kompozitor pruhledne okno slozi (par snimku) */
            bar_targets(&bar, fader, win);
            sleep_ms(4 * 17);
            bar_targets(&bar, fader, None);
            XDestroyWindow(dpy, win);
            XCompositeReleaseOverlayWindow(dpy, root);
            cow = None;
            win = fader;
        }
        for (int i = LOGIN_FADE_STEPS - 1; i > 0; i--) {
            double p = (double)i / LOGIN_FADE_STEPS;
            set_opacity((unsigned long)(0xffffffffUL * (p * p)));   /* rychle odkryti, jemny konec */
            XRaiseWindow(dpy, win);
            XFlush(dpy);
            sleep_ms(LOGIN_FADE_MS / LOGIN_FADE_STEPS);
            if (XGetSelectionOwner(dpy, a_cm) == None)
                break;
        }
        dbg(now_ms() - start, "faded in %ld ms", now_ms() - f0);
    }
    bar_stop(&bar);
    XDestroyWindow(dpy, win);
    if (cow != None)
        XCompositeReleaseOverlayWindow(dpy, root);
    XFreePixmap(dpy, snap);
    XCloseDisplay(dpy);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "--login") == 0)
        return login_main();
    if (argc > 1 && strcmp(argv[1], "--release") == 0)
        return release_main();
    return logout_main();
}
