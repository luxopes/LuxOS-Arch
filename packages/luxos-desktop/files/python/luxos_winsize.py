"""LuxOS - velikost oken Nastaveni podle obrazovky.

Okna mela pevnou vychozi vysku (720-760 px obsahu + ~45 px HeaderBar), takze na obrazovce 1366x768
nebo 1280x800 (bez horni listy a Docku jeste mene) presahovala dolni okraj a tlacitka dole nebyla
videt. Naopak sla zmensit na ~200 px s nepouzitelnym obsahem.

  fit(win, width, height, min_width=None, min_height=None)
      vychozi velikost nejvys do pracovni plochy monitoru (bez listy a Docku), rozumne minimum
  fit_content(win, scroll, width, max_height=None)
      okno podle obsahu (zadna prazdna plocha dole): ScrolledWindow prevezme prirozenou vysku obsahu,
      nejvys do pracovni plochy - zbytek se posouva
  max_content_height(win=None)    kolik obsahu (bez HeaderBar) se vejde na obrazovku

Rozmery z set_default_size jsou bez HeaderBar (CSD) - proto se od pracovni plochy odecita TITLEBAR.
"""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

TITLEBAR = 56        # HeaderBar okna LuxOS (46 px, s tlacitky ~55 px); po zobrazeni se pouzije skutecna vyska
MARGIN = 16          # okno nema byt nalepene na okraje pracovni plochy
MIN_WIDTH = 360
MIN_HEIGHT = 360


def workarea(win=None):
    """Gdk.Rectangle pracovni plochy monitoru okna (jinak hlavniho/prvniho); None bez obrazovky."""
    display = Gdk.Display.get_default()
    if display is None:
        return None
    monitor = None
    gdkwin = win.get_window() if win is not None else None
    if gdkwin is not None:
        monitor = display.get_monitor_at_window(gdkwin)
    if monitor is None:
        monitor = display.get_primary_monitor()
    if monitor is None and display.get_n_monitors():
        monitor = display.get_monitor(0)
    return monitor.get_workarea() if monitor is not None else None


def max_content_height(win=None):
    wa = workarea(win)
    if wa is None:
        return None
    return max(MIN_HEIGHT, wa.height - TITLEBAR - MARGIN)


def max_width(win=None):
    wa = workarea(win)
    if wa is None:
        return None
    return max(MIN_WIDTH, wa.width - 2 * MARGIN)


def fit(win, width, height, min_width=None, min_height=None):
    """Vychozi velikost (width x height obsahu) zmensena na pracovni plochu; minimum min_width x min_height
    (nejvys vychozi velikost). Vraci pouzitou velikost (sirka, vyska)."""
    w, h = width, height
    cap_w, cap_h = max_width(win), max_content_height(win)
    if cap_w is not None:
        w = min(w, cap_w)
    if cap_h is not None and h > 0:
        h = min(h, cap_h)
    win.set_default_size(w, h)
    mw = min(min_width or MIN_WIDTH, w) if w > 0 else (min_width or MIN_WIDTH)
    mh = min(min_height or MIN_HEIGHT, h) if h > 0 else (min_height or MIN_HEIGHT)
    if cap_h is not None:
        mh = min(mh, cap_h)
    geom = Gdk.Geometry()
    geom.min_width, geom.min_height = mw, mh
    win.set_geometry_hints(None, geom, Gdk.WindowHints.MIN_SIZE)
    win.connect("map", _cap_on_map)
    return w, h


def titlebar_height(win):
    bar = win.get_titlebar()
    if bar is None or not bar.get_visible():
        return 0
    return max(bar.get_allocated_height(), bar.get_preferred_height()[1])


def _cap_on_map(win):
    """Po zobrazeni: skutecna vyska HeaderBar (s tlacitky vyssi nez odhad) - okno nesmi presahnout plochu."""
    wa = workarea(win)
    if wa is None:
        return
    cap = wa.height - titlebar_height(win) - MARGIN
    w, h = win.get_size()
    if h > cap > 0:
        win.resize(w, cap)


def fit_content(win, scroll, width, max_height=None, min_height=None):
    """Okno tak vysoke jako obsah (bez prazdne plochy dole), nejvys pracovni plocha nebo max_height;
    vic obsahu se posouva ve scroll (Gtk.ScrolledWindow)."""
    cap = max_content_height(win)
    if max_height:
        cap = min(cap, max_height) if cap else max_height
    scroll.set_propagate_natural_height(True)
    if cap:
        scroll.set_max_content_height(cap)
    if min_height:
        scroll.set_min_content_height(min(min_height, cap) if cap else min_height)
    w = min(width, max_width(win) or width)
    win.set_default_size(w, -1)
    return w
