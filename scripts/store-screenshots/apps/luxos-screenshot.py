"""Snimek obrazovky: plovouci lista s vyberem vyrezu nad ukazkovym oknem, nabidka Volby a nahled po porizeni.

Lista je samostatny proces luxos-screenshot-ui (bez luxos-hub) prelozeny z LSL ze zdroju (jako PKGBUILD).
Snima se cela virtualni obrazovka (korenove okno), aby byla videt lista, vyber i okno pod nim; plochu
tvori tapeta LuxOS (luxos-branding) v okne typu plocha, ukazkove okno je Kalkulacka. Snimek
porizeny listou se ulozi do docasneho HOME (~/Pictures/Screenshots).
"""
import json
import os
import sys

DESK = r'''
import sys, gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gtk
w = Gtk.Window()
w.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
w.set_decorated(False)
w.move(0, 0)
w.set_default_size(1280, 800)
pb = GdkPixbuf.Pixbuf.new_from_file(sys.argv[1])
s = max(1280 / pb.get_width(), 800 / pb.get_height())
pb = pb.scale_simple(int(pb.get_width() * s + 1), int(pb.get_height() * s + 1), GdkPixbuf.InterpType.HYPER)
img = Gtk.Image.new_from_pixbuf(pb)
w.add(img)
w.connect("destroy", Gtk.main_quit)
w.show_all()
Gtk.main()
'''


def shots(s):
    ui = s.lslc("luxos-desktop/files/lsl/luxos-screenshot-ui.lsl")
    desk = os.path.join(s.tmp, "desk.py")
    with open(desk, "w", encoding="utf-8") as f:
        f.write(DESK)
    s.launch([sys.executable, desk, s.src("luxos-branding/files/wallpapers/luxos-sunrise.jpg")])
    s.sleep(1.5)
    calc = s.launch_python("luxos-desktop/files/bin/luxos-calculator")
    win = s.window(pid=calc.pid, size=None)
    s.type("1250*1.21=", win)
    x0, y0, w0, h0 = s.shell.frame(win)
    s.xdo("windowmove", win, (1280 - w0) // 2, 70)
    s.sleep(0.6)
    x, y, w, h = s.shell.frame(win)
    pad = 40
    sel = [x - pad, y - pad, w + 2 * pad, h + 2 * pad]
    s.write(".config/luxos/screenshot.json", json.dumps({"version": 2, "save_to": "screenshots", "timer": 0,
                                                         "pointer": False, "remember": True, "mode": "portion",
                                                         "selection": sel}))
    root = s.shell.Gdk.get_default_root_window().get_xid()
    env = {"LUXOS_SCREENSHOT_TEST_LOG": os.path.join(s.tmp, "shot.log")}
    s.launch([ui], env=env)
    s.sleep(2.0)
    s.capture("1", root)

    # 2: nabidka Volby (kam ulozit, casovac, ukazatel mysi, posledni vyber)
    s.click(800, 680, delay=1.0)
    s.capture("2", root)
    s.key("Escape", delay=0.6)

    # 3: Enter = porizeni snimku vyrezu, nahled vpravo dole s akcemi
    s.key("Return", delay=2.0)
    s.capture("3", root)
