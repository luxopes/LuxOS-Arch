/*
 * X11 aplikace pro test oken sandboxu na Waylandu (test_wayland.py): okno 360x220 s nazvem "X11 Sandbox App"
 * na 40,30 obrazovky X serveru sandboxu, vypisuje "mapped", "key KOD", "button" a "size W H" (zmena velikosti
 * okna zvenku). Klavesa r (X kod 27) zmeni velikost okna na 420x260. Konci po 30 s.
 */
#include <stdio.h>
#include <sys/select.h>
#include <time.h>
#include <X11/Xlib.h>

int
main(void)
{
	Display *d = XOpenDisplay(NULL);
	if (!d) {
		printf("no-display\n");
		return 2;
	}
	Window w = XCreateSimpleWindow(d, DefaultRootWindow(d), 40, 30, 360, 220, 0, 0, 0x30c060);
	XSelectInput(d, w, KeyPressMask | ButtonPressMask | ExposureMask | StructureNotifyMask);
	XStoreName(d, w, "X11 Sandbox App");
	int width = 360, height = 220;
	XMapWindow(d, w);
	/* bez spravce oken X: zamereni klavesnice primo na okno (jinak jde vstup korenu) */
	time_t end = time(NULL) + 30;
	while (time(NULL) < end) {
		while (XPending(d)) {
			XEvent e;
			XNextEvent(d, &e);
			if (e.type == MapNotify) {
				XSetInputFocus(d, w, RevertToParent, CurrentTime);
				printf("mapped\n");
			} else if (e.type == ConfigureNotify) {
				if (e.xconfigure.width != width || e.xconfigure.height != height) {
					width = e.xconfigure.width;
					height = e.xconfigure.height;
					printf("size %d %d\n", width, height);
				}
			} else if (e.type == KeyPress) {
				printf("key %u\n", e.xkey.keycode);
				if (e.xkey.keycode == 27) {
					XResizeWindow(d, w, 420, 260);
				}
			} else if (e.type == ButtonPress) {
				printf("button\n");
			}
			fflush(stdout);
		}
		int fd = ConnectionNumber(d);
		fd_set set;
		FD_ZERO(&set);
		FD_SET(fd, &set);
		struct timeval tv = { 0, 100000 };
		select(fd + 1, &set, NULL, NULL, &tv);
	}
	XCloseDisplay(d);
	return 0;
}
