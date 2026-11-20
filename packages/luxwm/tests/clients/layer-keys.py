"""Testovaci plocha layer-shell (GTK 3 + gtk-layer-shell): vypisuje stisknute klavesy a zamereni.

  layer-keys.py [--layer background|bottom|top] [--mode on_demand|exclusive|none]
SIGUSR1 prepne interaktivitu klavesnice na none (luxcomp musi klavesnici vratit oknu).
"""
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
layers = {"background": GtkLayerShell.Layer.BACKGROUND, "bottom": GtkLayerShell.Layer.BOTTOM,
          "top": GtkLayerShell.Layer.TOP}
modes = {"on_demand": GtkLayerShell.KeyboardMode.ON_DEMAND, "exclusive": GtkLayerShell.KeyboardMode.EXCLUSIVE,
         "none": GtkLayerShell.KeyboardMode.NONE}


def say(text):
    print(text, flush=True)


win = Gtk.Window()
GtkLayerShell.init_for_window(win)
GtkLayerShell.set_layer(win, layers[args.get("--layer", "bottom")])
for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM):
    GtkLayerShell.set_anchor(win, edge, True)
GtkLayerShell.set_keyboard_mode(win, modes[args.get("--mode", "on_demand")])
win.connect("key-press-event", lambda w, e: say("key " + (Gdk.keyval_name(e.keyval) or "?")))
win.connect("focus-in-event", lambda *a: say("focus in"))
win.connect("focus-out-event", lambda *a: say("focus out"))
win.connect("map-event", lambda *a: say("mapped"))


def to_none():
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    say("mode none")
    return GLib.SOURCE_REMOVE


GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, to_none)
win.show_all()
Gtk.main()
