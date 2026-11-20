# Testovaci lista (layer-shell, horni vrstva, exkluzivni zona 30 px) - jen pro testy luxcomp
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, GtkLayerShell

w = Gtk.Window()
GtkLayerShell.init_for_window(w)
GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP)
for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
    GtkLayerShell.set_anchor(w, e, True)
GtkLayerShell.auto_exclusive_zone_enable(w)
label = Gtk.Label(label="  LuxOS test bar (layer-shell top)")
label.set_xalign(0)
w.add(label)
w.set_size_request(-1, 30)
css = Gtk.CssProvider()
css.load_from_data(b"window { background: rgba(250,250,250,0.92); } label { color: #222; font: 600 11pt Inter; }")
Gtk.StyleContext.add_provider_for_screen(w.get_screen(), css, 800)
w.show_all()
Gtk.main()
