#!/usr/bin/env python3
"""LuxOS - minimalni spravce XSETTINGS pro testy (misto xfsettingsd): vlastni vyber _XSETTINGS_S0
a vlastnost _XSETTINGS_SETTINGS s textovymi hodnotami, dokud nedostane SIGTERM.

  DISPLAY=:N xsettings_manager.py Gtk/Modules=luxos-scroll [Jmeno=hodnota ...]
Na stdout vypise "ready", az je vyber prevzaty.
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import ctypes
import signal
import struct
import sys
import time

x = ctypes.CDLL("libX11.so.6")
x.XOpenDisplay.restype = ctypes.c_void_p
x.XOpenDisplay.argtypes = [ctypes.c_char_p]
x.XDefaultRootWindow.restype = ctypes.c_ulong
x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x.XCreateSimpleWindow.restype = ctypes.c_ulong
x.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                  ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
x.XInternAtom.restype = ctypes.c_ulong
x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x.XSetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
x.XGetSelectionOwner.restype = ctypes.c_ulong
x.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                              ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
x.XFlush.argtypes = [ctypes.c_void_p]
x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]


class ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("l", ctypes.c_long * 5), ("pad", ctypes.c_long * 19)]


def pad(b):
    return b + b"\0" * ((4 - len(b) % 4) % 4)


def serialize(settings):
    out = b"\0\0\0\0" + struct.pack("<II", 1, len(settings))   # LSBFirst
    for name, value in settings:
        n, v = name.encode(), value.encode()
        out += struct.pack("<BBH", 1, 0, len(n)) + pad(n) + struct.pack("<II", 0, len(v)) + pad(v)
    return out


def main():
    settings = [a.split("=", 1) for a in sys.argv[1:]]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        sys.exit("cannot open display")
    root = x.XDefaultRootWindow(dpy)
    win = x.XCreateSimpleWindow(dpy, root, 0, 0, 1, 1, 0, 0, 0)
    sel = x.XInternAtom(dpy, b"_XSETTINGS_S0", 0)
    prop = x.XInternAtom(dpy, b"_XSETTINGS_SETTINGS", 0)
    data = serialize(settings)
    x.XChangeProperty(dpy, win, prop, prop, 8, 0, data, len(data))   # PropModeReplace
    x.XSetSelectionOwner(dpy, sel, win, 0)
    x.XSync(dpy, 0)
    if x.XGetSelectionOwner(dpy, sel) != win:
        sys.exit("selection not acquired")
    # MANAGER na korenove okno: bezici aplikace si nastaveni prectou znovu (novy spravce za behu)
    ev = ClientMessage()
    ev.type = 33                         # ClientMessage
    ev.window = root
    ev.message_type = x.XInternAtom(dpy, b"MANAGER", 0)
    ev.format = 32
    ev.l[0], ev.l[1], ev.l[2] = 0, sel, win
    x.XSendEvent(dpy, root, 0, 1 << 17, ctypes.byref(ev))    # StructureNotifyMask
    x.XSync(dpy, 0)
    print("ready", flush=True)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
