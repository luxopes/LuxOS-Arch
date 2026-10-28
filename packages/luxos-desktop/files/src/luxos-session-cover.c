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
 * pred startem relace): posledni snimek prihlasovaci obrazovky (jen ztmavena tapeta) s malym tocicim se
 * koleckem na miste pole pro heslo zakryje skladani plochy. Jakmile je plocha (okno typu DESKTOP) opravdu
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
#include <cairo/cairo-xlib.h>
#include <cairo/cairo.h>
#include <errno.h>
#include <math.h>
#include <poll.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
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

#define LOGIN_FADE_MS 280
#define LOGIN_FADE_STEPS 14
#define LOGIN_FRAME_MS 33        /* kolecko ~30 snimku/s, jen male misto na obrazovce */
#define LOGIN_SCAN_MS 90         /* jak casto kontrolovat, zda je plocha vykreslena */
#define LOGIN_NOCM_SETTLE_MS 400 /* bez kompozitoru okna nejdou precist: plocha a lista namapovane + chvile */
#define LOGIN_WAIT_CM_MS 1500    /* bez kompozitoru jeste chvili pockat, zda nezacne (rozplynuti) */
#define LOGIN_PAINT_MAX_MS 4000  /* plocha namapovana, ale "nevykreslena" (napr. cerna barva pozadi) */
#define LOGIN_SOLID_MS 1200      /* jednobarevna plocha (barva misto tapety) stabilni tak dlouho = hotovo */
#define LOGIN_DOCK_MAX_MS 1500   /* skryty Dock (automaticke skryvani) nemusi nic vykreslit */
#define LOGIN_MAX_MS 15000       /* vzdy skoncit (relace bez listy, jine prostredi) */

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

static int ignore_errors(Display *d, XErrorEvent *e)
{
    (void)d;
    (void)e;
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
    long nz = 0, tot = 0;
    unsigned long h = 1469598103UL, first = 0;
    int uni = 1;
    for (int k = 1; k <= 5; k++) {
        XImage *im = XGetImage(dpy, w, 0, wa.height * k / 6, (unsigned)wa.width, 1, AllPlanes, ZPixmap);
        if (!im)
            continue;
        for (int x = 0; x < wa.width; x += 3) {
            unsigned long p = XGetPixel(im, x, 0);
            if (!tot)
                first = p;
            else if (p != first)
                uni = 0;
            tot++;
            nz += p != 0;
            h = (h ^ p) * 1099511628211UL;
        }
        XDestroyImage(im);
    }
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

/* ---- kolecko (nacitani) ------------------------------------------------------------------------- */

typedef struct {
    int x, y, size;
    double u;
    Pixmap back;                /* pozadi z obrazku + kolecko, pak jednim kopirovanim do okna */
    GC gc;
    cairo_surface_t *cs;
} Spinner;

/* Misto pole pro heslo (pod avatarem) na hlavnim monitoru - stejne rozmery jako luxos-greeter */
static void spinner_init(Spinner *s, Visual *vis, int depth, int sw, int sh)
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
    s->u = u < 0.55 ? 0.55 : u;
    s->size = (int)(48 * s->u + 0.5);
    s->x = mx + mw / 2 - s->size / 2;
    s->y = my + mh - (int)(204 * s->u + 0.5) - s->size / 2;
    s->back = XCreatePixmap(dpy, root, (unsigned)s->size, (unsigned)s->size, (unsigned)depth);
    s->gc = XCreateGC(dpy, s->back, 0, NULL);
    s->cs = cairo_xlib_surface_create(dpy, s->back, vis, s->size, s->size);
}

/* Tenky svetly kruh a po nem obihajici jasny oblouk (otacka ~0,9 s, delka oblouku se jemne meni) */
static void spinner_draw(Spinner *s, Window target, Pixmap bg, double t, double alpha)
{
    XCopyArea(dpy, bg, s->back, s->gc, s->x, s->y, (unsigned)s->size, (unsigned)s->size, 0, 0);
    if (alpha > 0) {
        cairo_t *cr = cairo_create(s->cs);
        double c = s->size / 2.0, r = 14 * s->u, lw = 3 * s->u;
        double a0 = t * 2 * M_PI / 0.9;
        double len = M_PI * (0.45 + 0.35 * (0.5 + 0.5 * sin(t * 2 * M_PI / 1.8)));
        cairo_set_line_width(cr, lw);
        cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
        cairo_arc(cr, c, c, r, 0, 2 * M_PI);
        cairo_set_source_rgba(cr, 1, 1, 1, 0.22 * alpha);
        cairo_stroke(cr);
        cairo_arc(cr, c, c + 0.8 * s->u, r, a0, a0 + len);            /* jemny stin */
        cairo_set_source_rgba(cr, 0, 0, 0, 0.16 * alpha);
        cairo_stroke(cr);
        cairo_arc(cr, c, c, r, a0, a0 + len);
        cairo_set_source_rgba(cr, 1, 1, 1, 0.95 * alpha);
        cairo_stroke(cr);
        cairo_destroy(cr);
        cairo_surface_flush(s->cs);
    }
    XCopyArea(dpy, s->back, target, s->gc, 0, 0, (unsigned)s->size, (unsigned)s->size, s->x, s->y);
}

static void spinner_free(Spinner *s)
{
    cairo_surface_destroy(s->cs);
    XFreeGC(dpy, s->gc);
    XFreePixmap(dpy, s->back);
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
    Window held = held_window();
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
    restore_frame(snap, ra.visual, ra.depth, w, h, frame_is_black(snap, w, h));

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
    Spinner sp;
    spinner_init(&sp, ra.visual, ra.depth, (int)w, (int)h);
    int motion = motion_allowed();
    long start = now_ms(), listed_at = 0, ready_at = 0, last_scan = 0, image_at = 0, solid_at = 0;
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
        }
        if (raise) {
            XRaiseWindow(dpy, win);
            XFlush(dpy);
        }
        long t = now_ms();
        if (t - start >= LOGIN_MAX_MS) {
            dbg(t - start, "timeout");
            break;
        }
        if (!ready_at && (check || t - last_scan >= LOGIN_SCAN_MS)) {
            int have_cm = XGetSelectionOwner(dpy, a_cm) != None;
            scan(&sc, have_cm);
            last_scan = t;
            check = 0;
            if (sc.desk && sc.dock && !listed_at)
                listed_at = t;
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
        if (ready_at)
            break;
        double since = (double)(t - start);
        spinner_draw(&sp, win, snap, since / 1000.0, since >= 250 ? 1.0 : since / 250.0);
        XFlush(dpy);
        if (poll(&pfd, 1, LOGIN_FRAME_MS) < 0 && errno != EINTR)
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
            for (int i = 0; i < 4; i++) {
                double tt = (double)(now_ms() - start) / 1000.0;
                spinner_draw(&sp, fader, snap, tt, 1.0);
                spinner_draw(&sp, win, snap, tt, 1.0);
                XSync(dpy, False);
                sleep_ms(LOGIN_FRAME_MS);
            }
            XDestroyWindow(dpy, win);
            XCompositeReleaseOverlayWindow(dpy, root);
            cow = None;
            win = fader;
        }
        for (int i = LOGIN_FADE_STEPS - 1; i > 0; i--) {
            double p = (double)i / LOGIN_FADE_STEPS;
            set_opacity((unsigned long)(0xffffffffUL * (p * p)));   /* rychle odkryti, jemny konec */
            XRaiseWindow(dpy, win);
            spinner_draw(&sp, win, snap, (double)(now_ms() - start) / 1000.0, 1.0);
            XFlush(dpy);
            sleep_ms(LOGIN_FADE_MS / LOGIN_FADE_STEPS);
            if (XGetSelectionOwner(dpy, a_cm) == None)
                break;
        }
        dbg(now_ms() - start, "faded in %ld ms", now_ms() - f0);
    }
    spinner_free(&sp);
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
