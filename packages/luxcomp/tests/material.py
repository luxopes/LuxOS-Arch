# Klienti pro test materialu luxcomp (blur.sh), jen CSS (bez pycairo): plocha layer-shell s tonovanim
# jako vyskakovaci okno LuxOS a okno s kontrastnimi pruhy, na kterych je rozmazani videt
#   material.py layer NAMESPACE W H     plocha vpravo nahore, tonovani rgba(246,247,252,0.72), polomer 16
#   material.py stripes W H             okno s cerno-bilymi svislymi pruhy 4 px
import sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, GtkLayerShell

CSS = b"""
window.layer { background: transparent; }
.card { background-color: rgba(246, 247, 252, 0.72); border-radius: 16px; color: #1d1d2b; font: 600 15px sans; }
window.stripes { background-image: repeating-linear-gradient(90deg, black 0px, black 4px, white 4px, white 8px); }
"""

win = Gtk.Window()
mode = sys.argv[1]
if mode == "layer":
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, sys.argv[2])
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
    GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
    GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
    GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, 40)
    GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, 200)
    win.set_visual(win.get_screen().get_rgba_visual())
    win.get_style_context().add_class("layer")
    card = Gtk.Box()
    card.get_style_context().add_class("card")
    label = Gtk.Label(label="Control Center")
    label.set_valign(Gtk.Align.START)
    label.set_margin_top(20)
    label.set_margin_start(20)
    card.pack_start(label, False, False, 0)
    win.add(card)
    size = (int(sys.argv[3]), int(sys.argv[4]))
else:
    win.set_title("stripes")
    win.get_style_context().add_class("stripes")
    size = (int(sys.argv[2]), int(sys.argv[3]))
provider = Gtk.CssProvider()
provider.load_from_data(CSS)
Gtk.StyleContext.add_provider_for_screen(win.get_screen(), provider, 800)
win.set_size_request(*size)
win.show_all()
Gtk.main()
