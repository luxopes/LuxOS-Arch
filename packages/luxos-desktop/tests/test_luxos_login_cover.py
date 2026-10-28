"""Testy prechodu po prihlaseni: luxos-session-cover --login (files/src/luxos-session-cover.c).

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_login_cover.py -v

Pod Xvfb: "posledni snimek prihlaseni" = bile korenove okno, plocha = cerne; plochu a listu napodobi dve okna typu
DESKTOP a DOCK v _NET_CLIENT_LIST (bez spravce oken a kompozitoru). Nikdy ne na skutecne obrazovce.
Server bez "-background none" (QEMU bochs + llvmpipe) = cerne korenove okno uz pri startu: pak snimek ze
souboru greeteru (login-frame.raw), jinak rozmazana tapeta (login-frame-small.raw).
"""
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "src", "luxos-session-cover.c")
GREETER = os.path.join(HERE, "..", "..", "luxos-greeter", "files", "luxos-greeter")
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
        subprocess.run(["gcc", "-O2", "-Wall", "-Werror", "-o", cls.bin, SRC, "-lX11", "-lXfixes", "-lXcomposite",
                        "-lXrandr", "-lcairo", "-lm"], check=True)

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=self.tmp)
        self.frames = os.path.join(self.home, "lightdm-data")
        os.makedirs(self.frames)
        self.windows = []
        subprocess.run(["xprop", "-root", "-remove", "_NET_CLIENT_LIST"], check=False, stderr=subprocess.DEVNULL)
        self.X = X11()
        self.X.set_root(self.X.white)       # posledni snimek prihlasovaci obrazovky

    def tearDown(self):
        for w in self.windows:
            w.destroy()
        pump(0.05)

    def frame(self, name, w, h, bgrx, age=0):
        """Soubor snimku greeteru: hlavicka + w*h pixelu BGRx."""
        path = os.path.join(self.frames, name)
        with open(path, "wb") as f:
            f.write(b"LUXFRAME1 %d %d\n" % (w, h) + bytes(bgrx) * (w * h))
        if age:
            t = time.time() - age
            os.utime(path, (t, t))
        return path

    def screen_size(self):
        return Gdk.Screen.get_default().get_width(), Gdk.Screen.get_default().get_height()

    def start(self, lost=False):
        """lost=True: server snimek neudrzel (korenove okno uz je cerne)."""
        if lost:
            self.X.set_root(self.X.black)
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                   LUXOS_LOGIN_FRAME_DIR=self.frames)
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
        # bez kompozitoru: chvili ceka (na rozplynuti), pak odkryje - nejvys 400 + 1500 ms
        p.wait(5)
        took = time.monotonic() - t_ready
        self.assertLess(took, 2.4, took)
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
        self.assertLess(time.monotonic() - t_ready, 0.8)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_always_ends(self):
        # relace bez listy: po LOGIN_MAX_MS (15 s) konec
        p, t0 = self.start()
        p.wait(18)
        self.assertLess(time.monotonic() - t0, 16.5)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def finish(self, p):
        self.desktop_ready()
        p.wait(5)
        pump(0.1)
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_lost_frame_restored_from_greeter_file(self):
        w, h = self.screen_size()
        path = self.frame("login-frame.raw", w, h, (0x30, 0x20, 0x10, 0xff))     # B G R x
        p, _t0 = self.start(lost=True)
        self.assertEqual(self.X.pixel(), 0x102030)            # snimek greeteru, ne cerna
        self.assertEqual(self.X.pixel(w - 3, h - 3), 0x102030)
        self.assertFalse(os.path.exists(path))                # jednorazovy soubor smazan
        self.finish(p)

    def test_lost_frame_falls_back_to_blurred_wallpaper(self):
        self.frame("login-frame-small.raw", 4, 3, (0x00, 0x80, 0x00, 0xff))
        p, _t0 = self.start(lost=True)
        self.assertEqual(self.X.pixel(), 0x008000)            # zvetsena mala tapeta
        self.assertTrue(os.path.exists(os.path.join(self.frames, "login-frame-small.raw")))
        self.finish(p)

    def test_stale_or_wrong_frame_not_used(self):
        w, h = self.screen_size()
        stale = self.frame("login-frame.raw", w, h, (0xff, 0, 0, 0xff), age=600)   # z drivejsiho prihlaseni
        self.frame("login-frame-small.raw", 2, 2, (0, 0, 0xff, 0xff))
        p, _t0 = self.start(lost=True)
        self.assertEqual(self.X.pixel(), 0xff0000)            # mala tapeta (cervena), ne stary snimek
        self.assertFalse(os.path.exists(stale))
        self.finish(p)
        # poskozeny soubor: zadna nahrada, zustane puvodni chovani
        with open(os.path.join(self.frames, "login-frame-small.raw"), "wb") as f:
            f.write(b"LUXFRAME1 100 100\n" + b"\0" * 10)
        p, _t0 = self.start(lost=True)
        self.assertEqual(self.X.pixel(), self.X.black)
        self.finish(p)

    def test_kept_server_frame_wins_and_file_removed(self):
        w, h = self.screen_size()
        path = self.frame("login-frame.raw", w, h, (0x30, 0x20, 0x10, 0xff))
        p, _t0 = self.start()
        self.assertEqual(self.X.pixel(), self.X.white)        # server snimek udrzel - presny obraz
        self.assertFalse(os.path.exists(path))
        self.finish(p)

    def hold(self):
        """Greeter nechá snímek na obrazovce i po svém skončení (FrameHold, RetainPermanent)."""
        w, h = self.screen_size()
        code = ("import sys\nfrom importlib.machinery import SourceFileLoader\n"
                "g = SourceFileLoader('luxos_greeter', sys.argv[1]).load_module()\n"
                "sys.exit(0 if g.FrameHold().hold(int(sys.argv[2]), int(sys.argv[3])) else 1)\n")
        subprocess.run([sys.executable, "-c", code, GREETER, str(w), str(h)], check=True)
        self.X.set_root(self.X.black)          # server bez "-background none": koren po greeteru cerny

    def held_prop(self):
        return subprocess.run(["xprop", "-root", "_LUXOS_LOGIN_HOLD"], capture_output=True, text=True).stdout

    def test_greeter_held_frame_bridges_to_cover(self):
        self.hold()
        self.assertIn("window id", self.held_prop())
        self.assertEqual(self.X.pixel(), self.X.white)        # snímek greeteru přežil jeho konec
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                   LUXOS_LOGIN_FRAME_DIR=self.frames)
        p = subprocess.Popen([self.bin, "--login"], env=env)
        pump(0.4)
        self.assertNotIn("window id", self.held_prop())       # převzato a uvolněno
        self.assertEqual(self.X.pixel(), self.X.white)        # zakrytí ukazuje stejný snímek, ne černou
        self.finish(p)

    def test_release_for_other_sessions(self):
        self.hold()
        self.assertEqual(self.X.pixel(), self.X.white)
        self.assertEqual(subprocess.run([self.bin, "--release"], timeout=5).returncode, 0)
        pump(0.1)
        self.assertNotIn("window id", self.held_prop())
        self.assertEqual(self.X.pixel(), self.X.black)

    def test_desktop_already_running(self):
        self.desktop_ready()
        env = dict(os.environ, HOME=self.home)
        t0 = time.monotonic()
        self.assertEqual(subprocess.run([self.bin, "--login"], env=env, timeout=5).returncode, 0)
        self.assertLess(time.monotonic() - t0, 0.5)


if __name__ == "__main__":
    unittest.main()
