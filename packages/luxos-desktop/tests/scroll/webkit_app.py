#!/usr/bin/env python3
"""LuxOS - testovaci okno WebKitGTK (jako Posta): dlouha stranka, kazdou zmenu window.scrollY zapise do
LOG jako "cas_ms hodnota"; na STDOUT "ready X Y W H" az po nacteni stranky.

  webkit_app.py LOG
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
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

log = open(sys.argv[1], "w", buffering=1)
HTML = ("<html><body style='margin:0'>" + "".join(f"<p style='height:30px;margin:0'>Row {i}</p>" for i in range(600))
        + "<script>addEventListener('scroll', () => { document.title = String(scrollY); });</script></body></html>")

win = Gtk.Window(title="webkit test")
win.set_default_size(600, 500)
win.move(0, 0)
view = WebKit2.WebView()
win.add(view)
win.connect("destroy", Gtk.main_quit)


def on_title(v, p):
    t = v.get_title()
    if t and t.replace(".", "").isdigit():
        log.write(f"{time.monotonic() * 1000:.1f} {float(t):.2f}\n")


def on_load(v, event):
    if event == WebKit2.LoadEvent.FINISHED:
        GLib.timeout_add(800, report)


def report():
    gw = view.get_window()
    _, x, y = gw.get_origin()
    a = view.get_allocation()
    print(f"ready {x + a.x} {y + a.y} {a.width} {a.height}", flush=True)
    return False


view.connect("notify::title", on_title)
view.connect("load-changed", on_load)
view.load_html(HTML, "file:///")
win.show_all()
Gtk.main()
