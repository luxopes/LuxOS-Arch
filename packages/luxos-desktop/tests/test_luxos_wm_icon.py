#!/usr/bin/env python3
"""LuxOS - ostra ikona okna pro Alt+Tab (luxos-wm-icon v LSL, spousti luxos-appname-watch) ve vlastnim Xvfb.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_wm_icon.py -v

Okna vytvari test pres Xlib (ctypes) s WM_CLASS a malou _NET_WM_ICON; aplikace a ikona jsou ve vlastnim
XDG_DATA_DIRS. Zapis ikony v aplikacich v Pythonu (luxos_wm_icon.py) testuje luxos-i18n/tests.
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
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-wm-icon-test-")
XA_CARDINAL, XA_STRING = 6, 31
RED = 0xFFFF0000


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Xlib:
    def __init__(self, display):
        self.lib = lib = ctypes.cdll.LoadLibrary("libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XCreateSimpleWindow.restype = ctypes.c_ulong
        lib.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 4 + [ctypes.c_uint] + [ctypes.c_ulong] * 2
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
            ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.dpy = lib.XOpenDisplay(display.encode())
        assert self.dpy, "Xvfb"
        self.icon = lib.XInternAtom(self.dpy, b"_NET_WM_ICON", 0)

    def window(self, instance, cls, icon):
        lib = self.lib
        win = lib.XCreateSimpleWindow(self.dpy, lib.XDefaultRootWindow(self.dpy), 0, 0, 100, 100, 0, 0, 0)
        wmclass = instance.encode() + b"\0" + cls.encode() + b"\0"
        lib.XChangeProperty(self.dpy, win, lib.XInternAtom(self.dpy, b"WM_CLASS", 0), XA_STRING, 8, 0,
                            wmclass, len(wmclass))
        if icon:
            arr = (ctypes.c_ulong * len(icon))(*icon)
            lib.XChangeProperty(self.dpy, win, self.icon, XA_CARDINAL, 32, 0, arr, len(icon))
        lib.XSync(self.dpy, 0)
        return win

    def icons(self, win):
        lib = self.lib
        rtype, rfmt = ctypes.c_ulong(), ctypes.c_int()
        n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        lib.XSync(self.dpy, 0)
        lib.XGetWindowProperty(self.dpy, win, self.icon, 0, 1 << 24, 0, XA_CARDINAL, ctypes.byref(rtype),
                               ctypes.byref(rfmt), ctypes.byref(n), ctypes.byref(after), ctypes.byref(data))
        if not data.value:
            return []
        arr = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
        out = [arr[i] & 0xFFFFFFFF for i in range(n.value)]
        lib.XFree(data)
        return out

    def close(self):
        self.lib.XCloseDisplay(self.dpy)


def sizes(values):
    out, i = [], 0
    while i + 1 < len(values):
        w, h = values[i], values[i + 1]
        out.append((w, h, values[i + 2:i + 2 + w * h]))
        i += 2 + w * h
    return out


def small_icon(size=48, color=0xFF00FF00):
    return [size, size] + [color] * (size * size)


class WmIcon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = lsl_app.build("luxos-wm-icon", TMP)
        cls.xvfb = lsl_app.Xvfb()
        cls.x = Xlib(cls.xvfb.display)
        share = os.path.join(TMP, "share")
        apps = os.path.join(share, "applications")
        os.makedirs(apps)
        for name, extra in (("luxos-test-app", "StartupWMClass=LuxTest\n"), ("org.example.Viewer", ""),
                            ("luxos-no-icon", "")):
            icon = "luxos-missing-icon" if name == "luxos-no-icon" else "luxos-test-icon"
            with open(os.path.join(apps, name + ".desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=true\nIcon=%s\n%s" % (name, icon, extra))
        # ikona jen ve velikosti 256 px (cervena, polovina vpravo modra): zmensi se na 128 a 192
        icons = os.path.join(share, "icons", "hicolor", "256x256", "apps")
        os.makedirs(icons)
        shutil.copy("/usr/share/icons/hicolor/index.theme", os.path.join(share, "icons", "hicolor"))
        code = ("import sys, gi; gi.require_version('GdkPixbuf', '2.0'); from gi.repository import GdkPixbuf\n"
                "pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 256, 256); pb.fill(0xff0000ff)\n"
                "pb.new_subpixbuf(128, 0, 128, 256).fill(0x0000ffff)\n"
                "pb.savev(sys.argv[1], 'png', [], [])\n")
        subprocess.run([sys.executable, "-c", code, os.path.join(icons, "luxos-test-icon.png")], check=True, timeout=30)
        cls.env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "XAUTHORITY")}
        cls.env.update(DISPLAY=cls.xvfb.display, XDG_DATA_DIRS=share + ":/usr/share",
                       XDG_DATA_HOME=os.path.join(TMP, "home-share"), HOME=TMP)

    @classmethod
    def tearDownClass(cls):
        cls.x.close()
        cls.xvfb.stop()

    def run_icon(self, *args):
        r = subprocess.run([self.bin] + [str(a) for a in args], env=self.env, capture_output=True, text=True,
                           timeout=30)
        return r

    def test_small_icon_gets_128_and_192(self):
        before = small_icon()
        win = self.x.window("luxtest", "LuxTest", before)
        t0 = time.monotonic()
        r = self.run_icon(hex(win), "luxtest", "LuxTest")
        took = time.monotonic() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        got = sizes(self.x.icons(win))
        self.assertEqual([(w, h) for w, h, _ in got], [(48, 48), (128, 128), (192, 192)])
        self.assertEqual(self.x.icons(win)[:len(before)], before)          # puvodni velikost zustala
        for w, _h, px in got[1:]:
            self.assertEqual(len(px), w * w)
            self.assertEqual(px[(w // 2) * w + w // 4], RED)                # ARGB: cervena vlevo
            self.assertEqual(px[(w // 2) * w + 3 * w // 4], 0xFF0000FF)     # modra vpravo
        self.assertLess(took, 5)

    def test_big_icon_left_alone(self):
        before = small_icon(96)
        win = self.x.window("luxtest", "LuxTest", before)
        self.assertEqual(self.run_icon(win, "luxtest", "LuxTest").returncode, 0)
        self.assertEqual(self.x.icons(win), before)

    def test_window_without_icon(self):
        win = self.x.window("luxtest", "LuxTest", None)
        self.assertEqual(self.run_icon(hex(win), "luxtest", "LuxTest").returncode, 0)
        self.assertEqual([(w, h) for w, h, _ in sizes(self.x.icons(win))], [(128, 128), (192, 192)])

    def test_desktop_id_and_reverse_dns(self):
        win = self.x.window("luxos-test-app", "Whatever", small_icon())
        self.run_icon(hex(win), "luxos-test-app", "Whatever")
        self.assertEqual(len(sizes(self.x.icons(win))), 3)
        win = self.x.window("viewer", "Viewer", small_icon())
        self.run_icon(hex(win), "viewer", "Viewer")
        self.assertEqual(len(sizes(self.x.icons(win))), 3)

    def test_unknown_app_or_missing_icon(self):
        for inst, cls in (("nothing-here", "NothingHere"), ("luxos-no-icon", "luxos-no-icon")):
            before = small_icon()
            win = self.x.window(inst, cls, before)
            self.assertEqual(self.run_icon(hex(win), inst, cls).returncode, 0)
            self.assertEqual(self.x.icons(win), before)

    def test_closed_window_and_usage(self):
        r = self.run_icon("0x7ffffff0", "luxtest", "LuxTest")      # okno neexistuje: chyba X jen ignorovat
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.run_icon().returncode, 2)


if __name__ == "__main__":
    unittest.main()
