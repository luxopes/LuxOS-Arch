"""LuxOS - okna aplikaci v Pythonu (GTK 3) z matneho skla, stejne jako aplikace v LSL (Hodiny).

Prevod files/lsl/luxos_glass.lsl (setup, lights, set_dark, CSS) se stejnymi cisly: pod oknem se
kresli vyrez rozostrene tapety plochy (xfconf xfce4-desktop, vestaveny displej ma prednost pred
HDMI), pres nej mlecny zavoj, odlesk a svetla hrana; okno je bez dekoraci spravce oken, se
zaoblenymi rohy, semaforem vlevo nahore, tazenim za prazdne misto, zmenou velikosti za okraj
a dvojklikem = maximalizace. Rozmazani tapety je presna kopie gtk.pixbuf_blur/pixbuf_saturate
ze standardni knihovny LSL (test tests/test_luxos_glass_py.py porovnava pixely s LSL).

    import sys; sys.path.insert(0, "/usr/lib/luxos/python")
    import luxos_glass as glass

    win = Gtk.Window(title="Moje aplikace")
    glass.setup(win, can_resize=True)
    glass.set_dark(glass.theme_is_dark())          # tmave sklo se svetlym textem
    bar = Gtk.Box()
    bar.pack_start(glass.lights(win, lambda b: win.close()), False, False, 0)
    glass.install_css()                              # semafor a pruhledne posuvne oblasti

Bez kompozitoru (bez pruhlednosti) se okno vykresli plnou barvou skla. Tapeta se nacita ve vlakne
(rozmazani v Pythonu trva desetiny sekundy) a do te doby je okno jen v barve skla.
"""
import math
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

import cairo  # noqa: E402

RADIUS = 16.0
EDGE = 8
BLUR_SIZE = 240
BLUR_RADIUS = 3
SATURATION = 1.18

CSS = ("button.lg-light { min-width: 12px; min-height: 12px; padding: 0; margin: 0 4px 0 0; border-radius: 999px;"
       " border: 1px solid rgba(0, 0, 0, 0.12); background-image: none; box-shadow: none; outline: none; }\n"
       "button.lg-light label { font-size: 9px; font-weight: 800; color: transparent; margin-top: -1px; }\n"
       "button.lg-light:hover label { color: rgba(60, 20, 10, 0.70); }\n"
       "button.lg-close { background-color: #ff5f57; }\n"
       "button.lg-min { background-color: #febc2e; }\n"
       "button.lg-max { background-color: #28c840; }\n"
       ".lg-window scrolledwindow, .lg-window viewport { background: transparent; border: none; }\n")

_state = {"surface": None, "map": None, "dark": False, "loading": False, "watch": 0, "wins": {}, "press": None,
          "css": False}

EDGE_CURSORS = {
    Gdk.WindowEdge.NORTH_WEST: "nw-resize", Gdk.WindowEdge.NORTH_EAST: "ne-resize",
    Gdk.WindowEdge.SOUTH_WEST: "sw-resize", Gdk.WindowEdge.SOUTH_EAST: "se-resize",
    Gdk.WindowEdge.WEST: "w-resize", Gdk.WindowEdge.EAST: "e-resize",
    Gdk.WindowEdge.NORTH: "n-resize", Gdk.WindowEdge.SOUTH: "s-resize",
}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---- rozmazani (presne jako stdlib LSL: cairo.blur_pixels, saturate_pixels) ------------------

def _box_pass(data, count, lines, step, line_step, channels, radius):
    """Jeden krabicovy pruchod po liniich: posuvny soucet s opakovanymi krajnimi pixely a delenim
    v pevne radove carce 2^24 (cairo.box_pass v LSL)."""
    window = radius * 2 + 1
    inverse = 16777216 // window
    last = count - 1
    lead = radius + 1
    reach = min(radius, last)
    tail = radius - last if radius > last else 0
    for line in range(lines):
        start = line * line_step
        for c in range(channels):
            sl = slice(start + c, start + c + count * step, step)
            vals = data[sl]
            s = vals[0] * lead + sum(vals[1:reach + 1]) + vals[last] * tail
            out = bytearray(count)
            for i in range(count):
                out[i] = (s * inverse + 8388608) >> 24
                gone = i - radius
                come = i + radius + 1
                s += vals[come if come <= last else last] - vals[gone if gone > 0 else 0]
            data[sl] = out


def blur_pixels(data, width, height, stride, channels, radius):
    if radius <= 0 or width <= 0 or height <= 0 or channels not in (3, 4):
        return
    part = min((radius + 2) // 3, 32767)
    for _round in range(3):
        _box_pass(data, width, height, channels, stride, channels, part)
        _box_pass(data, height, width, stride, channels, channels, part)


def _premultiply(data, width, height, stride):
    for y in range(height):
        for p in range(y * stride, y * stride + width * 4, 4):
            a = data[p + 3]
            if a != 255:
                for k in range(3):
                    data[p + k] = (data[p + k] * a + 127) // 255


def _unpremultiply(data, width, height, stride):
    for y in range(height):
        for p in range(y * stride, y * stride + width * 4, 4):
            a = data[p + 3]
            if a == 0:
                data[p] = data[p + 1] = data[p + 2] = 0
            elif a != 255:
                half = a >> 1
                for k in range(3):
                    data[p + k] = min((data[p + k] * 255 + half) // a, 255)


def saturate_pixels(data, width, height, stride, channels, factor):
    f = int(_clamp(float(factor), 0.0, 256.0) * 256.0)
    for y in range(height):
        for p in range(y * stride, y * stride + width * channels, channels):
            r, g, b = data[p], data[p + 1], data[p + 2]
            luma = (r * 77 + g * 150 + b * 29) >> 8
            data[p] = _clamp(luma + (((r - luma) * f) >> 8), 0, 255)
            data[p + 1] = _clamp(luma + (((g - luma) * f) >> 8), 0, 255)
            data[p + 2] = _clamp(luma + (((b - luma) * f) >> 8), 0, 255)


def blurred_pixbuf(path, size=BLUR_SIZE, radius=BLUR_RADIUS, saturation=SATURATION):
    """Zmensenina tapety rozmazana a nasycena jako v LSL (gtk.pixbuf_blur + pixbuf_saturate)."""
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
    w, h, st, ch = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
    data = bytearray(pb.get_pixels())
    if ch == 4:
        _premultiply(data, w, h, st)
    blur_pixels(data, w, h, st, ch, radius)
    if ch == 4:
        _unpremultiply(data, w, h, st)
    saturate_pixels(data, w, h, st, ch, saturation)
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB, ch == 4, 8, w, h, st)


# ---- tapeta ---------------------------------------------------------------------------------

def wallpaper_path(bus=None):
    """Tapeta plochy z xfconf (vestaveny displej ma prednost pred HDMI, jako luxos-widgets)."""
    try:
        bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        props = bus.call_sync("org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", "GetAllProperties",
                              GLib.Variant("(ss)", ("xfce4-desktop", "/backdrop")), None, 0, 3000, None).unpack()[0]
    except GLib.Error:
        return ""
    best = ""
    for key in sorted(props):
        if key.endswith("/workspace0/last-image"):
            if best == "" or "monitorHDMI" not in key:
                best = str(props[key])
    return best


def _monitor_geometry():
    display = Gdk.Display.get_default()
    monitor = display.get_monitor(0) if display else None
    if monitor is None:
        return 0, 0, 1, 1
    g = monitor.get_geometry()
    return g.x, g.y, g.width, g.height


def _load_wallpaper():
    if _state["loading"]:
        return
    _state["loading"] = True
    geo = _monitor_geometry()

    def work():
        path = wallpaper_path()
        pb = None
        if path:
            try:
                pb = blurred_pixbuf(path)
            except (GLib.Error, OSError):
                pb = None
        GLib.idle_add(_loaded, pb, geo)

    threading.Thread(target=work, daemon=True).start()


def _loaded(pb, geo):
    _state["loading"] = False
    if pb is None:
        _state["surface"] = _state["map"] = None
    else:
        pw, ph = pb.get_width(), pb.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.paint()
        surface.flush()
        mw, mh = float(max(1, geo[2])), float(max(1, geo[3]))
        sc = min(pw / mw, ph / mh)
        _state["surface"] = surface
        _state["map"] = (pw, ph, sc, (pw - mw * sc) / 2.0 - geo[0] * sc, (ph - mh * sc) / 2.0 - geo[1] * sc)
    _redraw_all()
    return False


def _redraw_all():
    for win in list(_state["wins"]):
        win.queue_draw()


def _on_xfconf(conn, sender, path, iface, signal, params):
    channel, prop = params.unpack()[:2]
    if channel == "xfce4-desktop" and str(prop).endswith("last-image"):
        GLib.timeout_add(300, lambda: _load_wallpaper() or False)


def _ensure_loaded():
    if _state["watch"]:
        return
    _load_wallpaper()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        _state["watch"] = bus.signal_subscribe(None, "org.xfce.Xfconf", "PropertyChanged", "/org/xfce/Xfconf", None,
                                               0, _on_xfconf)
    except GLib.Error:
        _state["watch"] = -1


# ---- kresleni -------------------------------------------------------------------------------

def _rounded(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2.0, 0.0)
    cr.arc(x + w - r, y + h - r, r, 0.0, math.pi / 2.0)
    cr.arc(x + r, y + h - r, r, math.pi / 2.0, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3.0 * math.pi / 2.0)
    cr.close_path()


def _corner(win):
    return 0.0 if win.is_maximized() else RADIUS


def _on_draw(win, cr):
    """Podklad pred detmi okna: sklo, zavoj, odlesk a okraj (GTK pak kresli obsah)."""
    w, h = float(win.get_allocated_width()), float(win.get_allocated_height())
    r = _corner(win)
    dark = _state["dark"]
    cr.save()
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    _rounded(cr, 0, 0, w, h, r)
    cr.clip()
    if dark:
        cr.set_source_rgba(0.13, 0.14, 0.17, 0.94)
    else:
        cr.set_source_rgba(0.95, 0.95, 0.97, 0.94)
    cr.paint()
    if _state["surface"] is not None:
        m = _state["map"]
        x, y = win.get_position()
        sx = _clamp(m[3] + x * m[2], 0.5, m[0] - 0.5 - w * m[2])
        sy = _clamp(m[4] + y * m[2], 0.5, m[1] - 0.5 - h * m[2])
        cr.save()
        cr.scale(1.0 / m[2], 1.0 / m[2])
        cr.set_source_surface(_state["surface"], -sx, -sy)
        cr.paint()
        cr.restore()
    # mlecny zavoj: svetly pro tmavy text, tmavy pro bily text
    if dark:
        cr.set_source_rgba(0.06, 0.07, 0.10, 0.52)
    else:
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.42)
    cr.paint()
    sheen = cairo.LinearGradient(0, 0, w * 0.45, h)
    sheen.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.14)
    sheen.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
    cr.set_source(sheen)
    cr.paint()
    cr.restore()
    if r > 0.0:
        cr.set_line_width(1.0)
        _rounded(cr, 0.5, 0.5, w - 1.0, h - 1.0, r - 0.5)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.18)
        cr.stroke()
        top = 0.30 if dark else 0.75
        edge = cairo.LinearGradient(0, 0, 0, h)
        edge.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, top)
        edge.add_color_stop_rgba(0.25, 1.0, 1.0, 1.0, top * 0.3)
        edge.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, top * 0.15)
        _rounded(cr, 1.5, 1.5, w - 3.0, h - 3.0, r - 1.5)
        cr.set_source(edge)
        cr.stroke()
    return False


def _shape(win, width, height, radius):
    """Tvar okna se zaoblenymi rohy (bez kompozitoru by rohy zcernaly)."""
    surface = cairo.ImageSurface(cairo.FORMAT_A1, max(1, width), max(1, height))
    cr = cairo.Context(surface)
    _rounded(cr, 0, 0, max(1, width), max(1, height), radius)
    cr.fill()
    win.shape_combine_region(Gdk.cairo_region_create_from_surface(surface))


def _on_configure(win, _event):
    w, h = win.get_size()
    key = (w, h, _corner(win))
    if _state["wins"].get(win) != key:
        _state["wins"][win] = key
        _shape(win, w, h, key[2])
    win.queue_draw()
    return False


def _on_window_state(win, event):
    if event.changed_mask & Gdk.WindowState.MAXIMIZED:
        _state["wins"][win] = None
        _on_configure(win, event)
    return False


# ---- presun a zmena velikosti (spravce oken) ------------------------------------------------

def _edge_at(win, x, y):
    """Hrana pod mysi (pas EDGE px, v rozich podel zaobleni), None = vnitrek okna."""
    if win.is_maximized() or not win.get_resizable():
        return None
    w, h = (float(v) for v in win.get_size())
    e = float(EDGE)
    left, right, top, bottom = x < e, x >= w - e, y < e, y >= h - e
    cz = RADIUS + e
    near_l, near_r, near_t, near_b = x < cz, x >= w - cz, y < cz, y >= h - cz
    if (top or left) and near_t and near_l:
        return Gdk.WindowEdge.NORTH_WEST
    if (top or right) and near_t and near_r:
        return Gdk.WindowEdge.NORTH_EAST
    if (bottom or left) and near_b and near_l:
        return Gdk.WindowEdge.SOUTH_WEST
    if (bottom or right) and near_b and near_r:
        return Gdk.WindowEdge.SOUTH_EAST
    if left:
        return Gdk.WindowEdge.WEST
    if right:
        return Gdk.WindowEdge.EAST
    if top:
        return Gdk.WindowEdge.NORTH
    if bottom:
        return Gdk.WindowEdge.SOUTH
    return None


def toggle_maximize(win):
    if win.is_maximized():
        win.unmaximize()
    else:
        win.maximize()


def _on_press(win, event):
    """Stisk na prazdnem miste okna (ovladaci prvky udalost vyridi samy)."""
    if event.button != 1:
        return False
    if event.type == Gdk.EventType._2BUTTON_PRESS:
        _state["press"] = None
        if win.get_resizable():
            toggle_maximize(win)
        return True
    if event.type != Gdk.EventType.BUTTON_PRESS:
        return True
    edge = _edge_at(win, event.x, event.y)
    if edge is not None:
        win.begin_resize_drag(edge, event.button, int(event.x_root), int(event.y_root), event.time)
        return True
    # presun az po pohybu o par pixelu: okamzite predani spravci oken by spolklo druhy klik dvojkliku
    _state["press"] = (win, event.x_root, event.y_root, event.button, event.time)
    return True


def _on_release(win, _event):
    _state["press"] = None
    return False


def _on_motion(win, event):
    p = _state["press"]
    if p is not None and p[0] is win:
        if abs(event.x_root - p[1]) + abs(event.y_root - p[2]) >= 5.0:
            _state["press"] = None
            win.begin_move_drag(p[3], int(p[1]), int(p[2]), p[4])
        return True
    name = EDGE_CURSORS.get(_edge_at(win, event.x, event.y), "")
    gdk_win = win.get_window()
    if gdk_win is not None and getattr(win, "_lg_cursor", None) != name:
        win._lg_cursor = name
        gdk_win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), name) if name else None)
    return False


# ---- verejne --------------------------------------------------------------------------------

def theme_is_dark(widget=None):
    """Tmavy rezim LuxOS: motiv GTK *-Dark nebo prefer-dark (jako theme_is_dark v Hodinach)."""
    settings = widget.get_settings() if widget is not None else Gtk.Settings.get_default()
    if settings is None:
        return False
    name = (settings.get_property("gtk-theme-name") or "").lower()
    return "dark" in name or bool(settings.get_property("gtk-application-prefer-dark-theme"))


def set_dark(dark):
    """Tmave sklo se svetlym textem (podle motivu aplikace)."""
    if _state["dark"] != bool(dark):
        _state["dark"] = bool(dark)
        _redraw_all()


def install_css(screen=None):
    """Styly semaforu a pruhlednych posuvnych oblasti (jednou pro proces)."""
    if _state["css"]:
        return
    screen = screen or Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _state["css"] = True


def setup(win, can_resize=True):
    """Okno bez dekoraci s RGBA, sklem, tazenim, zmenou velikosti za okraj a dvojklikem = maximalizace
    (can_resize=False: pevna velikost bez tazeni okraju, dvojkliku a zeleneho tlacitka)."""
    _ensure_loaded()
    _state["wins"][win] = None
    win.set_resizable(can_resize)
    win.get_style_context().add_class("lg-window")
    win.set_decorated(False)
    screen = win.get_screen()
    if screen.is_composited() and screen.get_rgba_visual() is not None:
        win.set_visual(screen.get_rgba_visual())
    win.set_app_paintable(True)
    win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                   | Gdk.EventMask.POINTER_MOTION_MASK)
    win.connect("draw", _on_draw)
    win.connect("configure-event", _on_configure)
    win.connect("window-state-event", _on_window_state)
    win.connect("button-press-event", _on_press)
    win.connect("button-release-event", _on_release)
    win.connect("motion-notify-event", _on_motion)
    win.connect("destroy", forget)
    install_css(screen)


def forget(win):
    """Okno zmizelo: uz ho neprekreslovat."""
    _state["wins"].pop(win, None)


def _light(kind, glyph, handler):
    b = Gtk.Button(label=glyph, can_focus=False, valign=Gtk.Align.CENTER)
    ctx = b.get_style_context()
    ctx.add_class("lg-light")
    ctx.add_class(kind)
    b.connect("clicked", handler)
    return b


def lights(win, on_close):
    """Semafor vlevo nahore; bez zmeny velikosti okna jen zavrit a minimalizovat."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER)
    box.pack_start(_light("lg-close", "×", on_close), False, False, 0)
    box.pack_start(_light("lg-min", "−", lambda b: b.get_toplevel().iconify()), False, False, 0)
    if win.get_resizable():
        box.pack_start(_light("lg-max", "+", lambda b: toggle_maximize(b.get_toplevel())), False, False, 0)
    return box
