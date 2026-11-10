#!/usr/bin/env python3
"""Zdroj presunuti souboru pro GUI test (jako okno Souboru): maly ctverec vlevo nahore nabizi text/uri-list.

    python3 dnd_source.py CESTA
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

path = sys.argv[1]
win = Gtk.Window(title="dnd-source")
win.set_default_size(160, 160)
win.move(0, 0)
box = Gtk.EventBox()
box.add(Gtk.Label(label="DRAG"))
win.add(box)
box.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY)
box.drag_source_add_uri_targets()


def on_get(widget, context, data, info, time):
    data.set_uris([GLib.filename_to_uri(path, None)])


box.connect("drag-data-get", on_get)
win.connect("destroy", Gtk.main_quit)
win.show_all()
print("ready", flush=True)
Gtk.main()
