#!/usr/bin/env python3
"""LuxOS - ostra ikona okna aplikaci v Pythonu (Dock, Alt+Tab): set_window_icons(okno, nazev ikony).

Ikona 16-256 px zmensena z nejvetsi velikosti v tematu a cely seznam zapsany do _NET_WM_ICON primo pres
Xlib (GDK posle jen to, co se vejde do jednoho pozadavku X). Pouzivaji ji Obchod, Lux Guard a Pocasi;
ikony cizich oken pro Alt+Tab doplnuje /usr/lib/luxos/luxos-wm-icon (LSL, luxos-desktop).
"""
import ctypes
import ctypes.util

XA_CARDINAL = 6
PROP_MODE_REPLACE = 0


def x11():
    lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XInternAtom.restype = ctypes.c_ulong
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    lib.XSetErrorHandler.restype = ctypes.c_void_p
    return lib


# Obsluha chyb X, ktera chyby jen ignoruje. Xlib ji drzi globalne pro cely proces (i pro spojeni GDK),
# proto musi objekt ctypes zit po celou dobu behu programu - uvolnena funkce by pri pristi chybe X
# v aplikaci GTK zpusobila pad.
_IGNORE_X_ERRORS = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda _d, _e: 0)

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
    # Jen po dobu zapisu: puvodni obsluhu (GDK) pak vratit, jinak by aplikace prisla o hlaseni chyb X
    previous = lib.XSetErrorHandler(_IGNORE_X_ERRORS)
    try:
        atom = lib.XInternAtom(dpy, b"_NET_WM_ICON", 0)
        arr = (ctypes.c_ulong * len(values))(*values)
        lib.XChangeProperty(dpy, gw.get_xid(), atom, XA_CARDINAL, 32, PROP_MODE_REPLACE, arr, len(values))
        lib.XFlush(dpy)
    finally:
        lib.XCloseDisplay(dpy)
        lib.XSetErrorHandler(previous)


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
