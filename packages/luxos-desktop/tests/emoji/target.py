#!/usr/bin/env python3
"""Cilove okno pro testy Emoji a symbolu (test_luxos_emoji.py) - jen pod Xvfb.

    target.py WM_CLASS OUT_FILE [--paste-keys ctrl-v|ctrl-shift-v|shift-insert]

Okno s jednim polem GtkEntry a vlastnim WM_CLASS (napr. "Navigator"/"firefox" jako zastupny Firefox).
Obsah pole se po kazde zmene zapise do OUT_FILE. --paste-keys: pole vklada JEN touto zkratkou (ostatni
zkratky vlozeni zahodi), at test overi, ze picker poslal spravnou zkratku podle WM_CLASS (terminal
Ctrl+Shift+V, xterm Shift+Insert z PRIMARY). Pri startu se zapise "ready <xid>".
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk  # noqa: E402,F401

klass, out = sys.argv[1], sys.argv[2]
paste_keys = None
if "--paste-keys" in sys.argv:
    paste_keys = sys.argv[sys.argv.index("--paste-keys") + 1]

GLib.set_prgname(klass.lower())
win = Gtk.Window(title="Emoji target " + klass)
win.set_wmclass(klass.lower(), klass)
entry = Gtk.Entry()
entry.set_text("")
win.add(entry)
win.set_default_size(420, 60)
win.move(80, 80)


def write(*_):
    with open(out, "w", encoding="utf-8") as f:
        f.write(entry.get_text())


def on_key(widget, event):
    if paste_keys is None:
        return False
    mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
    key = Gdk.keyval_to_lower(event.keyval)
    ctrl = Gdk.ModifierType.CONTROL_MASK
    shift = Gdk.ModifierType.SHIFT_MASK
    combos = {
        "ctrl-v": (key == Gdk.KEY_v and mods == ctrl),
        "ctrl-shift-v": (key == Gdk.KEY_v and mods == ctrl | shift),
        "shift-insert": (key == Gdk.KEY_Insert and mods == shift),
    }
    for name, hit in combos.items():
        if hit:
            if name != paste_keys:
                with open(out + ".wrong", "a") as f:
                    f.write(name + "\n")
                return True
            # terminal: Ctrl+Shift+V vklada schranku, xterm Shift+Insert vyber PRIMARY
            selection = Gdk.SELECTION_PRIMARY if name == "shift-insert" else Gdk.SELECTION_CLIPBOARD
            text = Gtk.Clipboard.get(selection).wait_for_text() or ""
            entry.insert_text(text, entry.get_position())
            entry.set_position(entry.get_position() + len(text))
            return True
    return False


entry.connect("changed", write)
entry.connect("key-press-event", on_key)
win.connect("destroy", Gtk.main_quit)
win.show_all()


def ready():
    with open(out + ".ready", "w") as f:
        f.write("ready %d\n" % win.get_window().get_xid())
    return False


GLib.timeout_add(200, ready)
Gtk.main()
