#!/usr/bin/env python3
"""LuxOS - ostra ikona okna pro Alt+Tab.

  luxos_wm_icon.py OKNO INSTANCE TRIDA      (spousti luxos-appname-watch jednou pro kazde okno)

GTK3 posila spravci oken ikonu z tematu jen v nabizenych velikostech; u ikon jen ve SVG (scalable)
napevno 48 px. Alt+Tab LuxOS kresli ikony 96 px (luxos-gtk3.css, #xfwm-tabwin), xfwm4 je zvetsil
a byly rozmazane (Soubory, Ovladace, Pruvodce, Baterie...). Kdyz okno nema ikonu aspon 96 px,
pridaji se do _NET_WM_ICON velikosti 128 a 192 z ikony aplikace (soubor .desktop, tema ikon).
Puvodni velikosti zustavaji.
"""
import ctypes
import ctypes.util
import os
import sys

WANT = 96            # velikost ikony v Alt+Tab
SIZES = (128, 192)   # pridane velikosti (192 = 96 pri dvojnasobnem meritku)

XA_CARDINAL = 6
PROP_MODE_REPLACE = 0


def x11():
    lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XInternAtom.restype = ctypes.c_ulong
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    lib.XFree.argtypes = [ctypes.c_void_p]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    return lib


def read_icons(lib, dpy, win, atom):
    """_NET_WM_ICON -> seznam hodnot (sirka, vyska, ARGB...); None = okno neexistuje."""
    rtype, rfmt = ctypes.c_ulong(), ctypes.c_int()
    n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    if lib.XGetWindowProperty(dpy, win, atom, 0, 1 << 24, 0, XA_CARDINAL, ctypes.byref(rtype),
                              ctypes.byref(rfmt), ctypes.byref(n), ctypes.byref(after),
                              ctypes.byref(data)) != 0:
        return None
    if not data.value:
        return []
    try:
        if rfmt.value != 32:
            return []
        # format 32 vraci Xlib jako pole long (8 bajtu na x86_64), platne jsou dolni 4 bajty
        arr = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
        return [arr[i] & 0xFFFFFFFF for i in range(n.value)]
    finally:
        lib.XFree(data)


def largest(values):
    best, i = 0, 0
    while i + 1 < len(values):
        w, h = values[i], values[i + 1]
        if w <= 0 or h <= 0 or i + 2 + w * h > len(values):
            break
        best = max(best, min(w, h))
        i += 2 + w * h
    return best


def find_app(instance, cls):
    from gi.repository import Gio
    names = [n.lower() for n in (instance, cls) if n]
    apps = Gio.AppInfo.get_all()
    for app in apps:   # StartupWMClass ma prednost (stejne jako luxos-appname-watch)
        wmc = (app.get_startup_wm_class() or "").lower() if hasattr(app, "get_startup_wm_class") else ""
        if wmc and wmc in names:
            return app
    for app in apps:
        stem = (app.get_id() or "")[:-len(".desktop")].lower()
        if stem in names or any(stem.endswith("." + n) for n in names):
            return app
    return None


def icon_values(gicon):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    theme = Gtk.IconTheme.get_default()
    out = []
    for size in SIZES:
        info = theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE)
        if info is None:
            return []
        pb = info.load_icon()
        if pb.get_width() != size or pb.get_height() != size:
            from gi.repository import GdkPixbuf
            pb = pb.scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
        if not pb.get_has_alpha():
            pb = pb.add_alpha(False, 0, 0, 0)
        px, stride = pb.get_pixels(), pb.get_rowstride()
        out += [size, size]
        for y in range(size):
            row = y * stride
            for x in range(size):
                r, g, b, a = px[row + x * 4:row + x * 4 + 4]
                out.append((a << 24) | (r << 16) | (g << 8) | b)
    return out


def main(argv):
    if len(argv) < 2:
        print("usage: luxos_wm_icon.py WINDOW INSTANCE CLASS  (used by luxos-appname-watch)", file=sys.stderr)
        return 2
    win = int(argv[1], 0)
    instance = argv[2] if len(argv) > 2 else ""
    cls = argv[3] if len(argv) > 3 else ""
    lib = x11()
    dpy = lib.XOpenDisplay(None)
    if not dpy:
        return 1
    # okno mezitim zavrene: chyba X jen ignorovat (vychozi obsluha by proces ukoncila)
    handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda _d, _e: 0)
    lib.XSetErrorHandler(handler)
    try:
        atom = lib.XInternAtom(dpy, b"_NET_WM_ICON", 0)
        current = read_icons(lib, dpy, win, atom)
        if current is None or largest(current) >= WANT:
            return 0
        app = find_app(instance, cls)
        gicon = app.get_icon() if app else None
        if gicon is None:
            return 0
        values = icon_values(gicon)
        if not values:
            return 0
        values = current + values
        arr = (ctypes.c_ulong * len(values))(*values)
        lib.XChangeProperty(dpy, win, atom, XA_CARDINAL, 32, PROP_MODE_REPLACE, arr, len(values))
        lib.XFlush(dpy)
    finally:
        lib.XCloseDisplay(dpy)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("GDK_BACKEND", "x11")
    sys.exit(main(sys.argv))
