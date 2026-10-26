"""Testy prechodu po prihlaseni: luxos-session-cover --login (files/src/luxos-session-cover.c).

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_login_cover.py -v

Pod Xvfb: "posledni snimek prihlaseni" = bile korenove okno, plocha = cerne; plochu a listu napodobi dve okna typu
DESKTOP a DOCK v _NET_CLIENT_LIST (bez spravce oken a kompozitoru). Nikdy ne na skutecne obrazovce.
"""
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-session-cover.c")
XVFB = "xvfb-run" in os.environ.get("XAUTHORITY", "") or os.environ.get("LUXOS_TEST_X") == "1"

if XVFB:
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk


def pump(sec=0.0):
    end = time.monotonic() + sec
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


class X11:
    """Primo Xlib (ctypes): barva korenoveho okna a cteni pixelu obrazovky (vcetne oken)."""

    def __init__(self):
        x = ctypes.CDLL(ctypes.util.find_library("X11"))
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        for f in ("XDefaultRootWindow", "XWhitePixel", "XBlackPixel"):
            getattr(x, f).restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XWhitePixel.argtypes = x.XBlackPixel.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XSetWindowBackground.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        x.XClearWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XGetImage.restype = ctypes.c_void_p
        x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
        x.XGetPixel.restype = ctypes.c_ulong
        x.XGetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.x = x
        self.dpy = x.XOpenDisplay(None)
        self.root = x.XDefaultRootWindow(self.dpy)
        self.white = x.XWhitePixel(self.dpy, 0)
        self.black = x.XBlackPixel(self.dpy, 0)

    def set_root(self, pixel):
        self.x.XSetWindowBackground(self.dpy, self.root, pixel)
        self.x.XClearWindow(self.dpy, self.root)
        self.x.XSync(self.dpy, 0)

    def pixel(self, px=20, py=20):
        img = self.x.XGetImage(self.dpy, self.root, px, py, 1, 1, 0xffffffff, 2)   # ZPixmap
        return self.x.XGetPixel(img, 0, 0)


@unittest.skipUnless(XVFB, "needs xvfb-run")
@unittest.skipUnless(shutil.which("gcc"), "needs gcc")
class LoginCover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-login-cover-")
        cls.bin = os.path.join(cls.tmp, "luxos-session-cover")
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-o", cls.bin, SRC, "-lX11", "-lXfixes"], check=True)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=self.tmp)
        self.windows = []
        subprocess.run(["xprop", "-root", "-remove", "_NET_CLIENT_LIST"], check=False, stderr=subprocess.DEVNULL)
        self.X = X11()
        self.X.set_root(self.X.white)       # posledni snimek prihlasovaci obrazovky

    def tearDown(self):
        for w in self.windows:
            w.destroy()
        pump(0.05)

    def start(self):
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"))
        p = subprocess.Popen([self.bin, "--login"], env=env)
        t0 = time.monotonic()
        # okno se zobrazi - pak se "plocha" pod nim prekresli na modro
        pump(0.3)
        self.X.set_root(self.X.black)        # plocha se sklada pod zakrytim
        return p, t0

    def desktop_ready(self):
        ids = []
        for hint in (Gdk.WindowTypeHint.DESKTOP, Gdk.WindowTypeHint.DOCK):
            w = Gtk.Window()
            w.set_type_hint(hint)
            w.resize(10, 10)
            w.move(600, 400)
            w.show()
            self.windows.append(w)
            pump(0.05)
            ids.append(w.get_window().get_xid())
        root = Gdk.get_default_root_window()
        # spravce oken by je zapsal do _NET_CLIENT_LIST - tady rucne (xprop je soucasti xorg-xprop)
        subprocess.run(["xprop", "-root", "-f", "_NET_CLIENT_LIST", "32c", "-set", "_NET_CLIENT_LIST",
                        ",".join(str(i) for i in ids)], check=True)
        root.get_display().flush()

    def test_cover_holds_last_frame_until_desktop_ready(self):
        p, t0 = self.start()
        self.assertEqual(self.X.pixel(), self.X.white)        # skladani plochy je zakryte
        time.sleep(0.4)
        pump()
        self.assertIsNone(p.poll(), "cover ended before the desktop was ready")
        self.assertEqual(self.X.pixel(), self.X.white)
        self.desktop_ready()
        t_ready = time.monotonic()
        # bez kompozitoru: chvili ceka (na rozplynuti), pak odkryje - nejvys 200 + 1200 ms
        p.wait(5)
        took = time.monotonic() - t_ready
        self.assertLess(took, 1.8, took)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_power_saver_reveals_without_waiting(self):
        os.makedirs(os.path.join(self.home, ".config", "luxos"))
        open(os.path.join(self.home, ".config", "luxos", "powersaver"), "w").close()
        p, _t0 = self.start()
        self.assertEqual(self.X.pixel(), self.X.white)
        self.desktop_ready()
        t_ready = time.monotonic()
        p.wait(5)
        self.assertLess(time.monotonic() - t_ready, 0.6)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_always_ends(self):
        # relace bez listy: po LOGIN_MAX_MS konec
        p, t0 = self.start()
        p.wait(8)
        self.assertLess(time.monotonic() - t0, 6.0)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_desktop_already_running(self):
        self.desktop_ready()
        env = dict(os.environ, HOME=self.home)
        t0 = time.monotonic()
        self.assertEqual(subprocess.run([self.bin, "--login"], env=env, timeout=5).returncode, 0)
        self.assertLess(time.monotonic() - t0, 0.5)


if __name__ == "__main__":
    unittest.main()
