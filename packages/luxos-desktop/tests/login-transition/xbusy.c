/* Zatez X serveru pro frame-bench.sh: porad dokola snimek cele obrazovky, XPutImage a vyplne do vlastni
 * pixmapy (jako programy, ktere se pri startu relace vykresluji). Jen na soukromem Xvfb. */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
int main(void)
{
    Display *d = XOpenDisplay(NULL);
    if (!d)
        return 1;
    int s = DefaultScreen(d);
    Window r = RootWindow(d, s);
    int w = DisplayWidth(d, s), h = DisplayHeight(d, s);
    Pixmap p = XCreatePixmap(d, r, (unsigned)w, (unsigned)h, (unsigned)DefaultDepth(d, s));
    GC gc = XCreateGC(d, p, 0, 0);
    for (;;) {
        XImage *im = XGetImage(d, r, 0, 0, (unsigned)w, (unsigned)h, AllPlanes, ZPixmap);
        if (im) {
            XPutImage(d, p, gc, im, 0, 0, 0, 0, (unsigned)w, (unsigned)h);
            XDestroyImage(im);
        }
        for (int i = 0; i < 50; i++) {
            XSetForeground(d, gc, (unsigned long)i * 12345);
            XFillRectangle(d, p, gc, i, i, (unsigned)(w - 2 * i), (unsigned)(h - 2 * i));
        }
        XSync(d, False);
    }
}
