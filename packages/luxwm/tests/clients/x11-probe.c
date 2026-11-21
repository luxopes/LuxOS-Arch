/*
 * Testovaci X11 klient pro luxwm pod XWayland: bile hlavni okno "xmain" (--title jine jmeno), volitelne
 * dialog "xdialog" (WM_TRANSIENT_FOR) a pevna velikost (WM_NORMAL_HINTS min = max). Vypisuje "mapped JMENO",
 * "key JMENO KEYSYM" pro kazdy stisk (i autorepeat X serveru) a "closed JMENO" pro WM_DELETE_WINDOW; se
 * zavrenim hlavniho okna skonci. Vlastni kurzor nema, okna ukazuji kurzor korenoveho okna.
 *
 *   x11-probe [--dialog] [--fixed WxH] [--title JMENO]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

static Display *dpy;
static Atom wm_delete;

static Window
make(const char *name, int w, int h, int fixed)
{
	Window win = XCreateSimpleWindow(dpy, DefaultRootWindow(dpy), 0, 0, w, h, 0, 0,
		WhitePixel(dpy, DefaultScreen(dpy)));
	XStoreName(dpy, win, name);
	XClassHint class = { (char *)name, "X11Probe" };
	XSetClassHint(dpy, win, &class);
	XSizeHints *hints = XAllocSizeHints();
	hints->flags = PSize;
	hints->width = w;
	hints->height = h;
	if (fixed) {
		hints->flags |= PMinSize | PMaxSize;
		hints->min_width = hints->max_width = w;
		hints->min_height = hints->max_height = h;
	}
	XSetWMNormalHints(dpy, win, hints);
	XFree(hints);
	XSetWMProtocols(dpy, win, &wm_delete, 1);
	XSelectInput(dpy, win, KeyPressMask | StructureNotifyMask);
	return win;
}

int
main(int argc, char **argv)
{
	int dialog = 0, fixed = 0, w = 400, h = 300;
	const char *title = "xmain";
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--dialog")) {
			dialog = 1;
		} else if (!strcmp(argv[i], "--fixed") && i + 1 < argc) {
			fixed = sscanf(argv[++i], "%dx%d", &w, &h) == 2;
		} else if (!strcmp(argv[i], "--title") && i + 1 < argc) {
			title = argv[++i];
		}
	}
	dpy = XOpenDisplay(NULL);
	if (!dpy) {
		fprintf(stderr, "x11-probe: no display\n");
		return 1;
	}
	wm_delete = XInternAtom(dpy, "WM_DELETE_WINDOW", False);
	Window main_win = make(title, w, h, fixed);
	XMapWindow(dpy, main_win);
	Window dlg = 0;
	if (dialog) {
		dlg = make("xdialog", 240, 160, 0);
		XSetTransientForHint(dpy, dlg, main_win);
		XMapWindow(dpy, dlg);
	}
	setvbuf(stdout, NULL, _IOLBF, 0);
	for (;;) {
		XEvent e;
		XNextEvent(dpy, &e);
		const char *name = e.xany.window == main_win ? title : "xdialog";
		if (e.type == MapNotify) {
			printf("mapped %s\n", name);
		} else if (e.type == KeyPress) {
			KeySym sym = XLookupKeysym(&e.xkey, 0);
			const char *s = XKeysymToString(sym);
			printf("key %s %s\n", name, s ? s : "?");
		} else if (e.type == ClientMessage && (Atom)e.xclient.data.l[0] == wm_delete) {
			printf("closed %s\n", name);
			if (e.xany.window == main_win) {
				break;
			}
			XDestroyWindow(dpy, dlg);
			XFlush(dpy);
		}
	}
	XCloseDisplay(dpy);
	return 0;
}
