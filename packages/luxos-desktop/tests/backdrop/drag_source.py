#!/usr/bin/env python3
"""Zdroj tazeni misto spravce souboru (jen testy): okno GTK 3, ktere nabizi text/uri-list zadanych souboru.

    drag_source.py SOUBOR...      vypise "ready", po skonceni tazeni "dragged"
"""
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

uris = [Path(p).resolve().as_uri() for p in sys.argv[1:]]
win = Gtk.Window(title="Drag")
win.set_default_size(200, 120)
box = Gtk.EventBox()
box.add(Gtk.Label(label="drag me"))
win.add(box)
box.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
box.connect("drag-data-get", lambda w, ctx, data, info, time: data.set_uris(uris))
box.connect("drag-end", lambda *a: print("dragged", flush=True))
win.connect("destroy", Gtk.main_quit)
win.connect("map-event", lambda *a: print("ready", flush=True))
win.show_all()
Gtk.main()
