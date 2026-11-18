/* LuxOS Sandbox - sonda X11 pro test nedůvěryhodného spojení (tests/test_x11_untrusted.py).
 *
 * Režimy, vždy jen na virtuální obrazovce testu (Xvfb, Xephyr nad ním):
 *
 *   x11-probe victim
 *       Důvěryhodný klient: okno "luxos-victim" se vstupním fokusem; na stdout vypíše
 *       "WID 0x..." a "HELD <keycode>" a přes XTest drží stisknutou klávesu (jako by uživatel
 *       právě psal). Do zavření stdin sbírá události okna a nakonec vypíše
 *       "GOT send_event=<n> xtest=<n>": kolik syntetických (XSendEvent) a kolik podvržených
 *       skutečných stisků (XTest od útočníka, klávesa F12) okno dostalo.
 *
 *   x11-probe attack --victim 0xWID --result-fd N -displayfd M ...
 *       Útočník = klient na straně hostitele, kterého spouští luxos-sandbox místo Xephyru
 *       (stejné prostředí, stejné omezení, stejný soubor autorizace). Zkusí odposlech kláves
 *       (XQueryKeymap, XSelectInput na cizí okno, XGrabKeyboard, RECORD, XInput2 raw události),
 *       snímek (XGetImage okna oběti i kořenového okna) a vkládání (XSendEvent, XTest).
 *       Výsledek jako řádky "NAZEV OK|DENIED ..." zapíše do FD --result-fd. Pak se chová jako
 *       Xephyr pro luxos-sandbox: otevře soket /tmp/.X11-unix/X<n>, n zapíše do -displayfd
 *       a čeká na ukončení.
 *
 *   x11-probe pixel WID X Y
 *       Barva jednoho bodu okna (kontrola, že Xephyr kreslí).
 *
 *   x11-probe listen
 *       Aplikace v okně sandboxu: okno přes celou obrazovku, vypisuje stisknuté klávesy
 *       (kontrola, že okno sandboxu s nedůvěryhodným spojením dál funguje).
 *
 * Sestavení: gcc -O2 -o x11-probe x11-probe.c -lX11 -lXext -lXtst -lXi
 */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <X11/extensions/XTest.h>
#include <X11/extensions/XInput2.h>
#include <X11/extensions/record.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>

static int last_error;
static int on_error(Display *d, XErrorEvent *e) { (void)d; last_error = e->error_code ? e->error_code : 1; return 0; }

static int victim(void)
{
    Display *d = XOpenDisplay(NULL);
    if (!d) { puts("OPENFAIL"); return 2; }
    XSetErrorHandler(on_error);
    Window w = XCreateSimpleWindow(d, DefaultRootWindow(d), 10, 10, 300, 200, 0, 0, 0xffffff);
    XStoreName(d, w, "luxos-victim");
    XSelectInput(d, w, KeyPressMask | KeyReleaseMask | ExposureMask | FocusChangeMask);
    XMapRaised(d, w);
    XSync(d, False);
    for (int i = 0; i < 100; i++) {   /* Xvfb bez správce oken: mapování je okamžité, fokus nastavíme sami */
        XWindowAttributes a;
        XGetWindowAttributes(d, w, &a);
        if (a.map_state == IsViewable) break;
        usleep(20000);
    }
    XSetInputFocus(d, w, RevertToParent, CurrentTime);
    /* trochu kresby, ať je co snímat */
    GC gc = XCreateGC(d, w, 0, NULL);
    XSetForeground(d, gc, 0xff0000);
    XFillRectangle(d, w, gc, 0, 0, 300, 200);
    XSync(d, False);
    int held = XKeysymToKeycode(d, XK_a);
    int f12 = XKeysymToKeycode(d, XK_F12);
    int typed = XKeysymToKeycode(d, XK_c);
    XTestFakeKeyEvent(d, held, True, CurrentTime);   /* uživatel "píše" */
    XSync(d, False);
    printf("WID 0x%lx\nHELD %d\n", (unsigned long)w, held);
    fflush(stdout);
    int sent = 0, xtest = 0;
    struct pollfd p[2] = {{0, POLLIN, 0}, {ConnectionNumber(d), POLLIN, 0}};
    for (;;) {
        while (XPending(d)) {
            XEvent ev;
            XNextEvent(d, &ev);
            if (ev.type == KeyPress) {
                if (ev.xkey.send_event) sent++;
                else if ((int)ev.xkey.keycode == f12) xtest++;
            }
        }
        if (poll(p, 2, 50) < 0) break;
        XTestFakeKeyEvent(d, typed, True, CurrentTime);    /* uživatel dál píše */
        XTestFakeKeyEvent(d, typed, False, CurrentTime);
        XFlush(d);
        if (p[0].revents) {
            char b[64];
            if (read(0, b, sizeof b) <= 0) break;
        }
    }
    while (XPending(d)) {
        XEvent ev;
        XNextEvent(d, &ev);
        if (ev.type == KeyPress) {
            if (ev.xkey.send_event) sent++;
            else if ((int)ev.xkey.keycode == f12) xtest++;
        }
    }
    XTestFakeKeyEvent(d, held, False, CurrentTime);
    XSync(d, False);
    printf("GOT send_event=%d xtest=%d\n", sent, xtest);
    return 0;
}

/* Aplikace uvnitř okna sandboxu (Xephyr): modré okno přes celou obrazovku se vstupním fokusem;
 * vypíše "READY" a pak "KEY <keysym>" za každý stisk, dokud se nezavře stdin. */
static int listen_keys(void)
{
    Display *d = XOpenDisplay(NULL);
    if (!d) { puts("OPENFAIL"); return 2; }
    int sw = DisplayWidth(d, 0), sh = DisplayHeight(d, 0);
    Window w = XCreateSimpleWindow(d, DefaultRootWindow(d), 0, 0, sw, sh, 0, 0, 0x0000ff);
    XSelectInput(d, w, KeyPressMask | ExposureMask);
    XMapRaised(d, w);
    XSync(d, False);
    for (int i = 0; i < 100; i++) {
        XWindowAttributes a;
        XGetWindowAttributes(d, w, &a);
        if (a.map_state == IsViewable) break;
        usleep(20000);
    }
    XSetInputFocus(d, w, RevertToParent, CurrentTime);
    XClearWindow(d, w);
    XSync(d, False);
    puts("READY");
    fflush(stdout);
    struct pollfd p[2] = {{0, POLLIN, 0}, {ConnectionNumber(d), POLLIN, 0}};
    for (;;) {
        while (XPending(d)) {
            XEvent ev;
            XNextEvent(d, &ev);
            if (ev.type == KeyPress) {
                KeySym ks = XLookupKeysym(&ev.xkey, 0);
                printf("KEY %s\n", ks ? XKeysymToString(ks) : "?");
                fflush(stdout);
            }
        }
        if (poll(p, 2, 200) < 0) break;
        if (p[0].revents) {
            char b[64];
            if (read(0, b, sizeof b) <= 0) break;
        }
    }
    return 0;
}

static FILE *out;

/* kolik stisků kláves klient dostane za ms milisekund */
static int count_keys(Display *d, int ms)
{
    int n = 0;
    for (int t = 0; t < ms; t += 20) {
        XSync(d, False);
        while (XPending(d)) {
            XEvent ev;
            XNextEvent(d, &ev);
            if (ev.type == KeyPress) n++;
        }
        usleep(20000);
    }
    return n;
}
static void res(const char *name, int ok, const char *detail)
{
    fprintf(out, "%s %s %s\n", name, ok ? "OK" : "DENIED", detail ? detail : "");
    fflush(out);
}

static int attack(Window victim_w, int held)
{
    Display *d = XOpenDisplay(NULL);
    if (!d) { res("CONNECT", 0, "cannot open display"); return 0; }
    res("CONNECT", 1, DisplayString(d));
    XSetErrorHandler(on_error);
    Window root = DefaultRootWindow(d);
    int n = 0;
    char **ext = XListExtensions(d, &n);
    char buf[2048] = "";
    for (int i = 0; i < n; i++) { strncat(buf, ext[i], sizeof buf - strlen(buf) - 2); strcat(buf, ","); }
    fprintf(out, "EXTENSIONS %s\n", buf);

    /* (a) odposlech: stav klávesnice */
    char keys[32] = {0};
    last_error = 0;
    XQueryKeymap(d, keys);
    XSync(d, False);
    int down = held > 0 && (keys[held / 8] & (1 << (held % 8)));
    char det[128];
    snprintf(det, sizeof det, "held-key-visible=%d error=%d", down ? 1 : 0, last_error);
    res("QUERYKEYMAP", down && !last_error, det);

    /* (a) události cizího okna */
    last_error = 0;
    XSelectInput(d, victim_w, KeyPressMask | KeyReleaseMask);
    XSync(d, False);
    int e1 = last_error, got = count_keys(d, 600);
    snprintf(det, sizeof det, "keys=%d error=%d", got, e1);
    res("SELECTINPUT_VICTIM", got > 0, det);
    XSelectInput(d, victim_w, NoEventMask);
    XSync(d, False);

    /* (a) uchopení klávesnice (vše napsané by šlo útočníkovi) */
    Window own = XCreateSimpleWindow(d, root, 0, 0, 1, 1, 0, 0, 0);
    XMapWindow(d, own);
    XSync(d, False);
    last_error = 0;
    XSelectInput(d, own, KeyPressMask);
    int g = XGrabKeyboard(d, own, False, GrabModeAsync, GrabModeAsync, CurrentTime);
    XSync(d, False);
    e1 = last_error;
    got = g == GrabSuccess ? count_keys(d, 600) : 0;
    snprintf(det, sizeof det, "status=%d keys=%d error=%d", g, got, e1);
    res("GRABKEYBOARD", got > 0, det);
    if (g == GrabSuccess) XUngrabKeyboard(d, CurrentTime);
    XSync(d, False);

    /* (a) RECORD - záznam vstupu všech klientů */
    int maj, mnr, ok = 0;
    last_error = 0;
    if (XRecordQueryVersion(d, &maj, &mnr)) {
        XRecordRange *r = XRecordAllocRange();
        r->device_events.first = KeyPress;
        r->device_events.last = KeyRelease;
        XRecordClientSpec cs = XRecordAllClients;
        XRecordContext ctx = XRecordCreateContext(d, 0, &cs, 1, &r, 1);
        XSync(d, False);
        ok = ctx && !last_error;
    }
    snprintf(det, sizeof det, "error=%d", last_error);
    res("RECORD", ok, det);

    /* (a) XInput2 raw události na kořenovém okně */
    int xi_op, ev, er;
    ok = 0;
    last_error = 0;
    if (XQueryExtension(d, "XInputExtension", &xi_op, &ev, &er)) {
        int xmaj = 2, xmin = 2;
        if (XIQueryVersion(d, &xmaj, &xmin) == Success) {
            unsigned char m[XIMaskLen(XI_LASTEVENT)] = {0};
            XIEventMask em = {XIAllMasterDevices, sizeof m, m};
            XISetMask(m, XI_RawKeyPress);
            XISetMask(m, XI_RawKeyRelease);
            XISelectEvents(d, root, &em, 1);
            XSync(d, False);
            ok = !last_error;
        }
    }
    snprintf(det, sizeof det, "error=%d", last_error);
    res("XI2_RAWKEYS", ok, det);

    /* (b) snímek okna oběti a celé obrazovky */
    last_error = 0;
    XImage *im = XGetImage(d, victim_w, 0, 0, 50, 50, AllPlanes, ZPixmap);
    XSync(d, False);
    snprintf(det, sizeof det, "pixel=%06lx error=%d", im ? XGetPixel(im, 5, 5) & 0xffffff : 0, last_error);
    res("GETIMAGE_VICTIM", im != NULL && !last_error, det);
    if (im) XDestroyImage(im);
    last_error = 0;
    im = XGetImage(d, root, 10, 10, 50, 50, AllPlanes, ZPixmap);
    XSync(d, False);
    snprintf(det, sizeof det, "pixel=%06lx error=%d", im ? XGetPixel(im, 5, 5) & 0xffffff : 0, last_error);
    res("GETIMAGE_ROOT", im != NULL && !last_error, det);
    if (im) XDestroyImage(im);

    /* (c) vkládání: XSendEvent (výsledek ověří oběť) a XTest */
    XEvent k;
    memset(&k, 0, sizeof k);
    k.xkey.type = KeyPress;
    k.xkey.display = d;
    k.xkey.window = victim_w;
    k.xkey.root = root;
    k.xkey.same_screen = True;
    k.xkey.keycode = XKeysymToKeycode(d, XK_b);
    last_error = 0;
    Status st = XSendEvent(d, victim_w, True, KeyPressMask, &k);
    XSync(d, False);
    snprintf(det, sizeof det, "status=%d error=%d", st, last_error);
    res("SENDEVENT_CALL", st && !last_error, det);
    ok = 0;
    last_error = 0;
    int a1, a2, a3, a4;
    if (XTestQueryExtension(d, &a1, &a2, &a3, &a4)) {
        int f12 = XKeysymToKeycode(d, XK_F12);
        XTestFakeKeyEvent(d, f12, True, CurrentTime);
        XTestFakeKeyEvent(d, f12, False, CurrentTime);
        XSync(d, False);
        ok = !last_error;
    }
    snprintf(det, sizeof det, "error=%d", last_error);
    res("XTEST_CALL", ok, det);
    XCloseDisplay(d);
    fprintf(out, "DONE\n");
    fflush(out);
    return 0;
}

/* Náhrada Xephyru pro luxos-sandbox: soket displeje, číslo do -displayfd, čekání na ukončení. */
static volatile sig_atomic_t stop_flag;
static void on_term(int s) { (void)s; stop_flag = 1; }

static void pretend_server(int displayfd)
{
    struct sigaction sa_term = {.sa_handler = on_term};
    sigaction(SIGTERM, &sa_term, NULL);
    if (displayfd < 0) return;
    mkdir("/tmp/.X11-unix", 01777);
    for (int num = 900; num < 999; num++) {
        struct sockaddr_un sa = {.sun_family = AF_UNIX};
        snprintf(sa.sun_path, sizeof sa.sun_path, "/tmp/.X11-unix/X%d", num);
        int s = socket(AF_UNIX, SOCK_STREAM, 0);
        if (bind(s, (struct sockaddr *)&sa, sizeof sa) == 0 && listen(s, 1) == 0) {
            dprintf(displayfd, "%d\n", num);
            close(displayfd);
            while (!stop_flag) pause();
            unlink(sa.sun_path);
            return;
        }
        close(s);
    }
}

int main(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "victim")) return victim();
    if (argc > 1 && !strcmp(argv[1], "listen")) return listen_keys();
    if (argc > 4 && !strcmp(argv[1], "pixel")) {   /* pixel WID X Y - barva bodu okna (důvěryhodný klient) */
        Display *d = XOpenDisplay(NULL);
        if (!d) return 2;
        XImage *im = XGetImage(d, strtoul(argv[2], NULL, 0), atoi(argv[3]), atoi(argv[4]), 1, 1, AllPlanes, ZPixmap);
        if (!im) return 1;
        printf("%06lx\n", XGetPixel(im, 0, 0) & 0xffffff);
        return 0;
    }
    if (argc < 2 || strcmp(argv[1], "attack")) {
        fprintf(stderr, "usage: x11-probe victim | attack --victim WID --result-fd N [-displayfd M ...]\n");
        return 2;
    }
    Window w = 0;
    int rfd = -1, dfd = -1, held = -1;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--victim") && i + 1 < argc) w = strtoul(argv[++i], NULL, 0);
        else if (!strcmp(argv[i], "--held") && i + 1 < argc) held = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--result-fd") && i + 1 < argc) rfd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-displayfd") && i + 1 < argc) dfd = atoi(argv[++i]);
    }
    out = rfd >= 0 ? fdopen(rfd, "w") : stdout;
    if (!out) return 2;
    attack(w, held);
    fclose(out);
    pretend_server(dfd);
    return 0;
}
