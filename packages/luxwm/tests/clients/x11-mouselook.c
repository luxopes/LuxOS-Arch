/*
 * X11 hra s rozhlizenim mysi pro luxwm pod XWayland (test_luxwm_gaming.py), jako Wine/Proton a SDL hry:
 * po prvnim vstupu ukazatele do okna XGrabPointer s confine_to = okno a skryty kurzor (XFixes),
 * Xwayland pak zamkne ukazatel Waylandu (pointer-constraints) a pohyb bere z relative-pointer.
 * Po kazdem pohybu vraci kurzor doprostred (XWarpPointer). Vypisuje "mapped", "grab RESULT"
 * a "delta DX DY" (posun od stredu okna) za kazdy MotionNotify.
 *
 *   x11-mouselook [--title JMENO] [--fullscreen]   (--fullscreen: _NET_WM_STATE_FULLSCREEN uz pred namapovanim)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xfixes.h>

#define W 400
#define H 300

int
main(int argc, char **argv)
{
	const char *title = "xgame";
	int fullscreen = 0;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--title") && i + 1 < argc) {
			title = argv[++i];
		} else if (!strcmp(argv[i], "--fullscreen")) {
			fullscreen = 1;
		}
	}
	Display *dpy = XOpenDisplay(NULL);
	if (!dpy) {
		fprintf(stderr, "x11-mouselook: no display\n");
		return 1;
	}
	Window win = XCreateSimpleWindow(dpy, DefaultRootWindow(dpy), 0, 0, W, H, 0, 0,
		BlackPixel(dpy, DefaultScreen(dpy)));
	XStoreName(dpy, win, title);
	XClassHint class = { (char *)title, "X11Mouselook" };
	XSetClassHint(dpy, win, &class);
	if (fullscreen) {
		Atom state = XInternAtom(dpy, "_NET_WM_STATE", False);
		Atom fs = XInternAtom(dpy, "_NET_WM_STATE_FULLSCREEN", False);
		XChangeProperty(dpy, win, state, XA_ATOM, 32, PropModeReplace, (unsigned char *)&fs, 1);
	}
	XSelectInput(dpy, win, StructureNotifyMask | PointerMotionMask | EnterWindowMask | ButtonPressMask);
	XMapWindow(dpy, win);
	int grabbed = 0;
	for (;;) {
		XEvent e;
		XNextEvent(dpy, &e);
		if (e.type == MapNotify) {
			printf("mapped\n");
		} else if ((e.type == EnterNotify || e.type == ButtonPress) && !grabbed) {
			int r = XGrabPointer(dpy, win, True, PointerMotionMask | ButtonPressMask, GrabModeAsync,
				GrabModeAsync, win, None, CurrentTime);
			XFixesHideCursor(dpy, win);
			XWarpPointer(dpy, None, win, 0, 0, 0, 0, W / 2, H / 2);
			XSync(dpy, False);
			grabbed = r == GrabSuccess;
			printf("grab %d\n", r);
		} else if (e.type == MotionNotify && grabbed) {
			int dx = e.xmotion.x - W / 2, dy = e.xmotion.y - H / 2;
			if (dx || dy) {
				printf("delta %d %d\n", dx, dy);
				XWarpPointer(dpy, None, win, 0, 0, 0, 0, W / 2, H / 2);
			}
		}
		fflush(stdout);
	}
}
