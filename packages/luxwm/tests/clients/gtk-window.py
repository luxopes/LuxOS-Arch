"""Testovaci okno GTK 3: s headerbarem (vlastni zahlavi, CSD) nebo bez (jako Thunar, chce zahlavi od kompozitoru).

  gtk-window.py --headerbar|--plain [--title T] [--size WxH] [--app-id ID] [--themed] [--compact] [--grow WxH] [--toggle]
                [--hide-cursor]
Stin a zaobleni klienta jsou vypnute (CSS), aby test videl jen to, co kresli kompozitor; obsah je jednobarevny.
--themed: vzhled z tematu (GTK_THEME), jako aplikace LuxOS: pozadi okna a 12 px pod zahlavim zacina
modry obdelnik (z nej test pozna vysku zahlavi); --compact = headerbar.compact (Kalkulacka);
--grow: za 1 s se okno samo zvetsi (aplikace podle obsahu).
--toggle: klik do okna prepne barvu obsahu zelena <-> modra (kontrola, ze se okno po vstupu prekresli).
--hide-cursor: kolecko mysi nad oknem skryje kurzor (jako aplikace, ktere ho pri posouvani nebo psani schovaji).
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

args = sys.argv[1:]
title = args[args.index("--title") + 1] if "--title" in args else "Window"
w, h = map(int, (args[args.index("--size") + 1] if "--size" in args else "400x300").split("x"))
if "--app-id" in args:
    GLib.set_prgname(args[args.index("--app-id") + 1])
themed = "--themed" in args
css = Gtk.CssProvider()
if themed:
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-decoration-layout", "close,minimize,maximize:")
    settings.set_property("gtk-font-name", "Inter 10")
    css.load_from_data(b".probe { background: #3060d0; }\n")
else:
    css.load_from_data(b"window, window.background { background: #20a040; }\n"
                       b"decoration { box-shadow: none; border-radius: 0; margin: 0; }\n"
                       b"headerbar { background: #20a040; border-radius: 0; box-shadow: none; border: none; }\n")
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
win = Gtk.Window(title=title)
if "--headerbar" in args:
    bar = Gtk.HeaderBar(title=title, show_close_button=True)
    if "--compact" in args:
        # bez mista pro podtitulek (jinak GTK chce 34 px), jako Kalkulacka s vlastnim titulkem
        bar.set_has_subtitle(False)
        bar.get_style_context().add_class("compact")
    win.set_titlebar(bar)
if themed:
    probe = Gtk.EventBox()
    probe.get_style_context().add_class("probe")
    probe.set_margin_top(12)
    probe.set_margin_start(12)
    probe.set_margin_end(12)
    probe.set_margin_bottom(12)
    win.add(probe)
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
if "--hide-cursor" in args:
    def hide(widget, event):
        widget.get_window().set_cursor(Gdk.Cursor.new_for_display(widget.get_display(), Gdk.CursorType.BLANK_CURSOR))
        print("hidden", flush=True)
        return False
    win.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    win.connect("scroll-event", hide)
win.show_all()
if "--grow" in args:
    gw, gh = map(int, args[args.index("--grow") + 1].split("x"))
    GLib.timeout_add(1000, lambda: win.resize(gw, gh) and False)
Gtk.main()
