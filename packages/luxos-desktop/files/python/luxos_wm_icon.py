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


WINDOW_SIZES = (16, 24, 32, 48, 64, 128, 256)


def window_pixbufs(icon_name, sizes=WINDOW_SIZES):
    """Ikona aplikace ve velikostech 16-256 px, kazda zmensena z nejvetsi (512 px PNG / SVG) filtrem HYPER."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib, Gtk
    try:
        src = Gtk.IconTheme.get_default().load_icon(icon_name, 512, 0)
    except GLib.Error:
        return []
    if src is None:
        return []
    out = []
    for size in sizes:
        pb = src if src.get_width() == size else src.scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
        if not pb.get_has_alpha():
            pb = pb.add_alpha(False, 0, 0, 0)
        out.append(pb)
    return out


def _argb(pb):
    """Pixbuf RGBA -> hodnoty ARGB pro _NET_WM_ICON (sirka, vyska, pixely)."""
    import array
    w, h, stride = pb.get_width(), pb.get_height(), pb.get_rowstride()
    px = pb.get_pixels()
    if stride != w * 4:
        px = b"".join(px[y * stride:y * stride + w * 4] for y in range(h))
    bgra = bytearray(len(px))
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = px[2::4], px[1::4], px[0::4], px[3::4]
    return [w, h] + array.array("I", bytes(bgra)).tolist()


def _write_net_wm_icon(win, pixbufs):
    """Cely seznam do _NET_WM_ICON primo pres Xlib: GDK posle jen to, co se vejde do jednoho
    pozadavku X bez BIG-REQUESTS, a 256 px vynecha (Alt+Tab ji pak zvetsuje rozmazane)."""
    gw = win.get_window()
    if gw is None or type(gw).__name__ != "X11Window":
        return
    values = []
    for pb in pixbufs:
        values += _argb(pb)
    lib = x11()
    dpy = lib.XOpenDisplay(None)
    if not dpy:
        return
    handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda _d, _e: 0)
    lib.XSetErrorHandler(handler)
    try:
        atom = lib.XInternAtom(dpy, b"_NET_WM_ICON", 0)
        arr = (ctypes.c_ulong * len(values))(*values)
        lib.XChangeProperty(dpy, gw.get_xid(), atom, XA_CARDINAL, 32, PROP_MODE_REPLACE, arr, len(values))
        lib.XFlush(dpy)
    finally:
        lib.XCloseDisplay(dpy)


def set_window_icons(win, icon_name):
    """Ostra ikona okna (Dock, Alt+Tab) ve velikostech 16-256 px; bez ikony v tematu jen nazev ikony."""
    pixbufs = window_pixbufs(icon_name)
    if not pixbufs:
        win.set_icon_name(icon_name)
        return
    win.set_icon_list(pixbufs)
    try:
        import gi
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11  # noqa: F401  (typ X11Window pro get_xid)
    except (ImportError, ValueError):
        return
    if win.get_realized():
        _write_net_wm_icon(win, pixbufs)
    win.connect_after("realize", lambda w: _write_net_wm_icon(w, pixbufs))


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
