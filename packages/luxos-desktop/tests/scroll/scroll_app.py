#!/usr/bin/env python3
"""LuxOS - testovaci aplikace pro posouvani: okno s GtkScrolledWindow (dlouhy seznam) a volitelne
VteTerminal. Kazdou zmenu polohy zapise do LOG jako radek "cas_ms hodnota" (monotonni cas), na
STDOUT vypise "ready X Y W H" (poloha obsahu na obrazovce).

  scroll_app.py LOG [list|vte|nested|handler]
"""
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

log = open(sys.argv[1], "w", buffering=1)
mode = sys.argv[2] if len(sys.argv) > 2 else "list"

win = Gtk.Window(title="scroll test")
win.set_default_size(600, 500)
win.move(0, 0)
sw = Gtk.ScrolledWindow()
sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
target = sw

if mode == "vte":
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte  # noqa: E402
    term = Vte.Terminal()
    term.set_scrollback_lines(10000)
    if os.environ.get("VTE_PIXELS") == "1":
        term.set_scroll_unit_is_pixels(True)
        term.set_enable_fallback_scrolling(False)
    sw.add(term)
    # 2000 radku textu do historie
    term.feed(("".join(f"line {i}\r\n" for i in range(2000))).encode())
else:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for i in range(400):
        lbl = Gtk.Label(label=f"Row {i}")
        lbl.set_size_request(-1, 30)
        if mode == "nested" and i == 3:
            inner = Gtk.ScrolledWindow()
            inner.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            for j in range(60):
                row.pack_start(Gtk.Label(label=f"Col {j} "), False, False, 0)
            inner.add(row)
            inner.set_size_request(-1, 400)
            box.pack_start(inner, False, False, 0)
            continue
        box.pack_start(lbl, False, False, 0)
    if mode == "handler":
        # aplikace s vlastni obsluhou kolecka (napr. zoom): udalost nesmi dostat animace
        box_events = Gtk.EventBox()
        box_events.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        box_events.add(box)
        counter = {"n": 0}

        def on_scroll(w, e):
            counter["n"] += 1
            log.write(f"handler {counter['n']}\n")
            return True
        box_events.connect("scroll-event", on_scroll)
        sw.add(box_events)
    else:
        sw.add(box)

adj = sw.get_vadjustment()


def changed(a):
    log.write(f"{time.monotonic() * 1000:.1f} {a.get_value():.2f}\n")


adj.connect("value-changed", changed)
win.add(sw)
win.connect("destroy", Gtk.main_quit)
win.show_all()


def report():
    gw = sw.get_window()
    if gw is None:
        return True
    _, x, y = gw.get_origin()
    a = sw.get_allocation()
    print(f"ready {x + a.x} {y + a.y} {a.width} {a.height} {adj.get_upper():.0f} {adj.get_page_size():.0f}", flush=True)
    return False


GLib.timeout_add(500, report)
Gtk.main()
