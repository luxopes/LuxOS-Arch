#!/usr/bin/env python3
"""LuxOS - oznameni (xfce4-notifyd z [luxos]): pod otevrenym popupem horni listy, klik ukaze cele
oznameni, krizek pri najeti mysi.

    env -u DISPLAY xvfb-run -a -s "-screen 0 1280x800x24" dbus-run-session -- \\
        python3 -m unittest packages/luxos-desktop/tests/test_notifyd_popups.py -v

Spousti skutecny xfce4-notifyd (LUXOS_NOTIFYD = sestaveni packages/xfce4-notifyd) na soukrome sbernici
s docasnym HOME. Falesna okna Ovladaciho centra (WM_CLASS luxos-control-center) a rofi (override-redirect)
kresli maly pomocny program GTK. Jen pod xvfb-run; bez upraveneho notifyd se preskoci.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
XDG = os.path.normpath(os.path.join(HERE, "..", "files", "xdg"))
NOTIFYD = os.environ.get("LUXOS_NOTIFYD") or "/usr/lib/xfce4/notifyd/xfce4-notifyd"
PATCHED = os.path.exists(NOTIFYD) and b"luxos-close" in open(NOTIFYD, "rb").read()
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
TOOLS = all(shutil.which(t) for t in ("xdotool", "notify-send", "gdbus"))

POPUP = r'''
import sys, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk
name, klass, kind = sys.argv[1:4]
x, y, w, h = map(int, sys.argv[4:8])
win = Gtk.Window(type=Gtk.WindowType.POPUP if kind == "popup" else Gtk.WindowType.TOPLEVEL)
win.set_wmclass(name, klass)
win.set_size_request(w, h)
win.move(x, y)
if kind == "dialog":
    win.set_decorated(False)
    win.set_type_hint(Gdk.WindowTypeHint.DIALOG)
elif kind == "tooltip":
    win.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
win.show_all()
Gtk.main()
'''


def xdo(*args):
    return subprocess.run(["xdotool", *map(str, args)], capture_output=True, text=True, timeout=10).stdout


@unittest.skipUnless(PATCHED and UNDER_XVFB and TOOLS, "needs xfce4-notifyd from [luxos] (LUXOS_NOTIFYD), xvfb-run, xdotool")
class NotifydPopups(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-notifyd-popups-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.env = dict(os.environ, HOME=self.t, XDG_CONFIG_HOME=os.path.join(self.t, ".config"),
                        XDG_DATA_HOME=os.path.join(self.t, ".local", "share"), XDG_CACHE_HOME=os.path.join(self.t, ".cache"),
                        XDG_CONFIG_DIRS=XDG + ":/etc/xdg", GTK_USE_PORTAL="0", NO_AT_BRIDGE="1")
        self.procs = []
        self.notifyd = self.spawn([NOTIFYD])
        for _ in range(100):
            r = subprocess.run(["gdbus", "call", "--session", "-d", "org.freedesktop.DBus", "-o", "/org/freedesktop/DBus",
                                "-m", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.Notifications"],
                               capture_output=True, text=True, env=self.env)
            if "true" in r.stdout:
                break
            time.sleep(0.05)

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()

    def spawn(self, argv, stdout=subprocess.DEVNULL):
        p = subprocess.Popen(argv, env=self.env, stdout=stdout, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def notify(self, *args):
        subprocess.run(["notify-send", "-t", "60000", *args], env=self.env, check=True, timeout=10)
        time.sleep(0.8)

    def visible(self):
        return xdo("search", "--onlyvisible", "--class", "xfce4-notifyd").split()

    def wait(self, cond, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def popup(self, name, klass, kind, x, y, w, h):
        p = self.spawn([sys.executable, "-c", POPUP, name, klass, kind, str(x), str(y), str(w), str(h)])
        time.sleep(1.0)
        return p

    def close_popup(self, p):
        p.terminate()
        p.wait(5)

    def test_hidden_under_control_center_and_back(self):
        self.notify("First", "Body")
        self.assertEqual(len(self.visible()), 1)
        cc = self.popup("luxos-control-center", "Luxos-control-center", "dialog", 880, 0, 400, 420)
        self.assertTrue(self.wait(lambda: not self.visible()), "notification above Control Center")
        self.notify("Second", "Arrived while Control Center is open")
        self.assertEqual(self.visible(), [])
        self.close_popup(cc)
        self.assertTrue(self.wait(lambda: len(self.visible()) == 2), self.visible())

    def test_rofi_overlap_only(self):
        self.notify("First", "Body")
        far = self.popup("rofi", "Rofi", "popup", 20, 500, 300, 200)
        self.assertEqual(len(self.visible()), 1)              # nic neprekryva
        self.close_popup(far)
        near = self.popup("rofi", "Rofi", "popup", 700, 0, 580, 300)
        self.assertTrue(self.wait(lambda: not self.visible()))
        self.close_popup(near)
        self.assertTrue(self.wait(lambda: len(self.visible()) == 1))

    def test_panel_menu_but_not_tooltip_or_other_app(self):
        self.notify("First", "Body")
        tip = self.popup("xfce4-panel", "Xfce4-panel", "tooltip", 880, 0, 400, 300)
        self.assertEqual(len(self.visible()), 1)
        self.close_popup(tip)
        app = self.popup("firefox", "Firefox", "dialog", 700, 0, 580, 400)
        self.assertEqual(len(self.visible()), 1)
        self.close_popup(app)
        menu = self.popup("wrapper-2.0", "Wrapper-2.0", "popup", 880, 0, 400, 300)
        self.assertTrue(self.wait(lambda: not self.visible()))
        self.close_popup(menu)
        self.assertTrue(self.wait(lambda: len(self.visible()) == 1))

    def geometry(self, win):
        g = dict(ln.split("=", 1) for ln in xdo("getwindowgeometry", "--shell", win).split() if "=" in ln)
        return int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"])

    def test_click_expands_then_default_action(self):
        body = " ".join("Sentence number %d makes this message long enough to be cut." % i for i in range(8))
        out = os.path.join(self.t, "action")
        with open(out, "w") as f:
            waiter = self.spawn(["notify-send", "-t", "60000", "-A", "default=Open", "--wait", "Mail", body], stdout=f)
        time.sleep(1.0)
        win = self.visible()[0]
        x, y, w, h = self.geometry(win)
        xdo("mousemove", x + w // 2, y + 30)
        time.sleep(0.3)
        xdo("click", 1)
        self.assertTrue(self.wait(lambda: self.geometry(win)[3] > h), "first click did not expand")
        self.assertEqual(len(self.visible()), 1)
        x, y, w, h = self.geometry(win)
        xdo("mousemove", x + w // 2, y + 30)
        time.sleep(0.2)
        xdo("click", 1)
        waiter.wait(5)
        with open(out) as f:
            self.assertEqual(f.read().split(), ["default"])
        self.assertTrue(self.wait(lambda: not self.visible()))

    def test_close_button_on_hover(self):
        out = os.path.join(self.t, "action")
        with open(out, "w") as f:
            waiter = self.spawn(["notify-send", "-t", "60000", "-A", "default=Open", "--wait", "Closable", "Text"], stdout=f)
        time.sleep(1.0)
        x, y, w, h = self.geometry(self.visible()[0])
        xdo("mousemove", x + w // 2, y + h // 2)
        time.sleep(0.2)
        xdo("mousemove", x + 13, y + 13)
        time.sleep(0.3)
        xdo("click", 1)
        waiter.wait(5)
        self.assertTrue(self.wait(lambda: not self.visible()))
        with open(out) as f:
            self.assertEqual(f.read().split(), [])          # zavreni bez akce


if __name__ == "__main__":
    unittest.main()
