"""Testovaci okno GTK 3: s headerbarem (vlastni zahlavi, CSD) nebo bez (jako Thunar, chce zahlavi od kompozitoru).

  gtk-window.py --headerbar|--plain [--title T] [--size WxH] [--toggle]
--toggle: klik do okna prepne barvu obsahu zelena <-> modra (kontrola, ze se okno po vstupu prekresli).
Stin a zaobleni klienta jsou vypnute (CSS), aby test videl jen to, co kresli kompozitor; obsah je jednobarevny.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

args = sys.argv[1:]
title = args[args.index("--title") + 1] if "--title" in args else "Window"
w, h = map(int, (args[args.index("--size") + 1] if "--size" in args else "400x300").split("x"))
css = Gtk.CssProvider()
css.load_from_data(b"window, window.background { background: #20a040; }\n"
                   b"decoration { box-shadow: none; border-radius: 0; margin: 0; }\n"
                   b"headerbar { background: #20a040; border-radius: 0; box-shadow: none; border: none; }\n")
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
win = Gtk.Window(title=title)
if "--headerbar" in args:
    bar = Gtk.HeaderBar(title=title, show_close_button=True)
    win.set_titlebar(bar)
win.set_default_size(w, h)
win.connect("destroy", Gtk.main_quit)
win.connect("map-event", lambda *a: print("mapped", flush=True))
clicks = 0


def paint(area, cr):
    r, g, b = (0x20, 0x40, 0xa0) if clicks % 2 else (0x20, 0xa0, 0x40)
    cr.set_source_rgb(r / 255, g / 255, b / 255)
    cr.paint()


def toggle(widget, event):
    global clicks
    clicks += 1
    area.queue_draw()
    print("click", flush=True)
    return True


if "--toggle" in args:
    area = Gtk.DrawingArea()
    area.connect("draw", paint)
    win.add(area)
    win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    win.connect("button-press-event", toggle)
win.show_all()
Gtk.main()
