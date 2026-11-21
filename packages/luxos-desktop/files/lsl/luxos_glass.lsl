# LuxOS - okna aplikaci z matneho skla (jako prusvitne aplikace v macOS); programy nacitaji `load luxos_glass as glass`.
# Princip stejny jako luxos-widgets: X11/xfwm4 rozmazani neumi, proto se pod oknem kresli vyrez rozostrene
# tapety plochy (z xfconf, styl "priblizit"), pres nej mlecny zavoj, odlesk a svetla hrana.
#
#   call glass.setup(okno, True)      okno bez dekoraci s RGBA, sklem, tazenim (spravce oken: prichytavani,
#                                     jina plocha), zmenou velikosti za okraj a dvojklikem = maximalizace
#                                     (False = pevna velikost: bez tazeni okraju, dvojkliku a zeleneho tlacitka)
#   glass.lights(okno, zavrit)        semafor zavrit / minimalizovat / maximalizovat; zavrit(tlacitko) dela aplikace
#   call glass.set_dark(True|False)   tmave sklo se svetlym textem (podle motivu aplikace)
#   glass.CSS                         styly semaforu a tridy .lg-* (karta, pole, prepinac, tlacitko)
#   glass.panel_png(cesta, x, y, w, h, polomer, svetle)  stejna karta do PNG pro okna mimo GTK (Hledani v rofi)
#   call glass.panel(okno, box, polomer)  vyskakovaci panel (Ovladaci centrum) z materialu widgetu na plose:
#                                     pod box se kresli rozostrena tapeta se zavojem podle barvy textu motivu
#                                     (svetly text = tmave sklo); box dostane tridu lg-panel (CSS: bez pozadi)
#
# Tapeta se nacte jednou pro vsechna okna procesu a pri zmene v xfconf se prekresli. Potrebuje LSL >= 0.10.9.
load cairo, glib, gio, gtk
load luxos_glib as lglib
load luxos_gtk as lgtk

RADIUS = 16.0
EDGE = 8
BLUR_SIZE = 240
BLUR_RADIUS = 3

CSS = ("button.lg-light { min-width: 12px; min-height: 12px; padding: 0; margin: 0 4px 0 0; border-radius: 999px;"
    + " border: 1px solid rgba(0, 0, 0, 0.12); background-image: none; box-shadow: none; outline: none; }\n"
    + "button.lg-light label { font-size: 9px; font-weight: 800; color: transparent; margin-top: -1px; }\n"
    + "button.lg-light:hover label { color: rgba(60, 20, 10, 0.70); }\n"
    + "button.lg-close { background-color: #ff5f57; }\n"
    + "button.lg-min { background-color: #febc2e; }\n"
    + "button.lg-max { background-color: #28c840; }\n"
    + ".lg-window scrolledwindow, .lg-window viewport { background: transparent; border: none; }\n")

state = {"surface": 0, "map": [], "dark": False, "loaded": False, "watch": 0, "wins": {}, "press": [], "cursor": {}, "resize": {},
         "panel": 0, "panel_map": [], "panels": {}}
PANEL_SIZE = 96
EDGE_CURSORS = {}

function clamp(x, lo, hi):
    return max(lo, min(hi, x))
end

# ---- tapeta ---------------------------------------------------------------------------------

# Tapeta plochy z xfconf (vestaveny displej ma prednost pred HDMI, jako luxos-widgets)
function wallpaper_path(bus):
    props = None
    safe:
        props = gio.call_values(bus, "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf",
                                "GetAllProperties", ["xfce4-desktop", "/backdrop"], "(ss)", 3000)
    end
    if props == None or len(props) == 0 or type(props[0]) != "Dictionary":
        return ""
    end
    best = ""
    for key in sorted(props[0].keys()):
        if key.endswith("/workspace0/last-image"):
            value = String(props[0][key])
            if best == "" or key.find("monitorHDMI") < 0:
                best = value
            end
        end
    end
    return best
end

# Zmenseninu rozmazat a mirne nasytit; mapa = [sirka, vyska, meritko, posun x, posun y] obrazku vuci monitoru
function load_wallpaper():
    if state["surface"] != 0:
        call cairo.surface_destroy(state["surface"])
        state["surface"] = 0
    end
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0:
        return 0
    end
    path = wallpaper_path(bus)
    if path == "" or not exists(path):
        return 0
    end
    pb = gtk.pixbuf_new_from_file_at_scale(path, BLUR_SIZE, BLUR_SIZE, True)
    if pb == 0:
        return 0
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    call gtk.pixbuf_blur(pb, BLUR_RADIUS)
    call gtk.pixbuf_saturate(pb, 1.18)
    state["surface"] = gtk.pixbuf_to_surface(pb)
    call glib.object_unref(pb)
    geo = gtk.monitor_geometry(0)
    mw = Float(max(1, geo[2]))
    mh = Float(max(1, geo[3]))
    sc = min(Float(pw) / mw, Float(ph) / mh)
    state["map"] = [pw, ph, sc, (Float(pw) - mw * sc) / 2.0 - Float(geo[0]) * sc, (Float(ph) - mh * sc) / 2.0 - Float(geo[1]) * sc]
    return 0
end

function redraw_all():
    for win in state["wins"].keys():
        call gtk.widget_queue_draw(win)
    end
    for win in state["panels"].keys():
        call gtk.widget_queue_draw(win)
    end
    return 0
end

function on_xfconf_changed(sender, path, interface, signal, values):
    if len(values) >= 2 and values[0] == "xfce4-desktop" and String(values[1]).endswith("last-image"):
        call lglib.timeout_add_data(300, reload_once, 0)
    end
    return 0
end

function reload_once(unused):
    call load_wallpaper()
    if len(state["panels"]) > 0:
        call load_panel_material()
    end
    call redraw_all()
    return False
end

# ---- material widgetu na plose (panely) -----------------------------------------------------
# Stejny material jako luxos-widgets.lsl: glass_surface je doslovna kopie (test hlida shodu),
# volba svetleho/tmaveho skla a vzorec zavoje stejne jako glass_style, jen barva textu je dana motivem.

function glass_surface(source, w, h):
    weights = [1.0, 4.0, 6.0, 4.0, 1.0]
    for axis in range(2):
        out = cairo.image_surface_create(cairo.FORMAT_RGB24, w, h)
        cr = cairo.create(out)
        for y in range(h):
            for x in range(w):
                rgb = [0.0, 0.0, 0.0]
                for k in range(5):
                    sx = x
                    sy = y
                    if axis == 0:
                        sx = Int(clamp(x + k - 2, 0, w - 1))
                    else:
                        sy = Int(clamp(y + k - 2, 0, h - 1))
                    end
                    px = cairo.image_surface_pixel(source, sx, sy)
                    rgb[0] = rgb[0] + Float((px >> 16) & 255) * weights[k] / 4080.0
                    rgb[1] = rgb[1] + Float((px >> 8) & 255) * weights[k] / 4080.0
                    rgb[2] = rgb[2] + Float(px & 255) * weights[k] / 4080.0
                end
                if axis == 1:
                    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                    rgb = [0.22 + (rgb[0] * 0.72 + lum * 0.28) * 0.72,
                           0.22 + (rgb[1] * 0.72 + lum * 0.28) * 0.72,
                           0.22 + (rgb[2] * 0.72 + lum * 0.28) * 0.72]
                end
                call cairo.set_source_rgb(cr, rgb[0], rgb[1], rgb[2])
                call cairo.rectangle(cr, x, y, 1, 1)
                call cairo.fill(cr)
            end
        end
        call cairo.destroy(cr)
        call cairo.surface_destroy(source)
        source = out
    end
    return source
end

# [nejtmavsi jas, nejvyssi RMS energie] vyrezu (cast glass_style z luxos-widgets.lsl)
function glass_extremes(surface, sx, sy, sw, sh):
    pw = cairo.image_surface_get_width(surface)
    ph = cairo.image_surface_get_height(surface)
    lo = 1.0
    hi = 0.0
    for y in range(Int(max(0, sy)), Int(min(ph - 1, sy + sh + 1)) + 1):
        for x in range(Int(max(0, sx)), Int(min(pw - 1, sx + sw + 1)) + 1):
            px = cairo.image_surface_pixel(surface, x, y)
            r = Float((px >> 16) & 255) / 255.0
            g = Float((px >> 8) & 255) / 255.0
            b = Float(px & 255) / 255.0
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            energy = 0.2126 * r * r + 0.7152 * g * g + 0.0722 * b * b
            peak = 1.0
            for step in range(6):
                peak = (peak + energy / peak) / 2.0
            end
            lo = min(lo, lum)
            hi = max(hi, peak)
        end
    end
    return [lo, hi]
end

# Zavoj pro danou barvu textu: svetle sklo (tmavy text) bily, tmave sklo (bily text) cerny
function glass_veil(extremes, light):
    if light:
        return clamp((0.64 - extremes[0]) / max(0.001, 1.0 - extremes[0]), 0.0, 1.0)
    end
    return clamp(1.0 - 0.37 / max(0.001, extremes[1]), 0.0, 1.0)
end

function load_panel_material():
    if state["panel"] != 0:
        call cairo.surface_destroy(state["panel"])
        state["panel"] = 0
    end
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0:
        return 0
    end
    path = wallpaper_path(bus)
    if path == "" or not exists(path):
        return 0
    end
    pb = gtk.pixbuf_new_from_file_at_scale(path, PANEL_SIZE, PANEL_SIZE, True)
    if pb == 0:
        return 0
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    surface = cairo.image_surface_create(cairo.FORMAT_RGB24, pw, ph)
    cr = cairo.create(surface)
    call cairo.set_source_rgb(cr, 0.15, 0.17, 0.21)
    call cairo.paint(cr)
    call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call glib.object_unref(pb)
    geo = gtk.monitor_geometry(0)
    mw = Float(max(1, geo[2]))
    mh = Float(max(1, geo[3]))
    sc = min(Float(pw) / mw, Float(ph) / mh)
    state["panel"] = glass_surface(surface, pw, ph)
    state["panel_map"] = [pw, ph, sc, (Float(pw) - mw * sc) / 2.0 - Float(geo[0]) * sc, (Float(ph) - mh * sc) / 2.0 - Float(geo[1]) * sc]
    return 0
end

# Karta skla (x, y, w, h v souradnicich cr; screen_x/y = jeji roh na obrazovce): podklad, vyrez
# tapety, zavoj pro danou barvu textu (light = tmavy text), odlesk - jako on_card_draw widgetu
function paint_panel(cr, x, y, w, h, radius, screen_x, screen_y, light):
    m = state["panel_map"]
    sx = clamp(m[3] + Float(screen_x) * m[2], 0.5, Float(m[0]) - 0.5 - w * m[2])
    sy = clamp(m[4] + Float(screen_y) * m[2], 0.5, Float(m[1]) - 0.5 - h * m[2])
    veil = glass_veil(glass_extremes(state["panel"], sx, sy, w * m[2], h * m[2]), light)
    call cairo.save(cr)
    call cairo.rounded_rectangle(cr, x, y, w, h, radius)
    call cairo.clip(cr)
    call cairo.set_source_rgba(cr, 0.92, 0.94, 0.98, 0.86)
    call cairo.paint(cr)
    call cairo.save(cr)
    call cairo.translate(cr, x, y)
    call cairo.scale(cr, 1.0 / m[2], 1.0 / m[2])
    call cairo.set_source_surface(cr, state["panel"], -sx, -sy)
    call cairo.paint(cr)
    call cairo.restore(cr)
    v = 0.0
    if light:
        v = 1.0
    end
    call cairo.set_source_rgba(cr, v, v, v, veil)
    call cairo.paint(cr)
    sheen = cairo.pattern_create_linear(x, y, x + w * 0.35, y + h)
    call cairo.pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, 0.08)
    call cairo.pattern_add_color_stop_rgba(sheen, 1.0, 1.0, 1.0, 1.0, 0.0)
    call cairo.set_source(cr, sheen)
    call cairo.paint(cr)
    call cairo.pattern_destroy(sheen)
    call cairo.restore(cr)
    return 0
end

# Podklad pred detmi okna: karta skla pod boxem panelu (jako on_card_draw widgetu)
function on_panel_draw(cr, win):
    info = state["panels"].get(win)
    if info == None:
        return False
    end
    box = info[0]
    a = gtk.widget_get_allocation(box)
    w = Float(a[2])
    h = Float(a[3])
    if state["panel"] == 0 or w < 2.0 or h < 2.0 or not gtk.screen_is_composited():
        call gtk.widget_set_class(box, "lg-panel", False)
        return False
    end
    fg = gtk.widget_get_color(box, 0)
    light = 0.2126 * fg[0] + 0.7152 * fg[1] + 0.0722 * fg[2] <= 0.5
    pos = gtk.window_get_position(win)
    call paint_panel(cr, Float(a[0]), Float(a[1]), w, h, info[1], pos[0] + a[0], pos[1] + a[1], light)
    call gtk.widget_set_class(box, "lg-panel", True)
    return False
end

# Karta skla pro obdelnik obrazovky do PNG (pozadi oken mimo GTK, napr. Hledani v rofi);
# radius 0 = rohy orizne program, ktery obrazek kresli. Vraci True, kdyz je tapeta.
function panel_png(path, x, y, w, h, radius, light):
    if state["panel"] == 0:
        call load_panel_material()
    end
    if state["panel"] == 0:
        return False
    end
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.create(surface)
    call paint_panel(cr, 0.0, 0.0, Float(w), Float(h), Float(radius), x, y, light)
    call cairo.destroy(cr)
    call cairo.surface_write_to_png(surface, path)
    call cairo.surface_destroy(surface)
    return True
end

function on_panel_configure(event, win):
    call gtk.widget_queue_draw(win)
    return False
end

function panel(win, box, radius):
    if not state["loaded"]:
        call ensure_loaded()
    end
    if state["panel"] == 0:
        call load_panel_material()
    end
    state["panels"][win] = [box, Float(radius)]
    call gtk.connect(win, "draw", on_panel_draw)
    call gtk.connect(win, "configure-event", on_panel_configure)
    return 0
end

function ensure_loaded():
    if state["loaded"]:
        return 0
    end
    state["loaded"] = True
    call load_wallpaper()
    safe:
        bus = gio.session_bus()
        state["watch"] = gio.subscribe_values(bus, "", "org.xfce.Xfconf", "PropertyChanged", "/org/xfce/Xfconf", on_xfconf_changed)
    end
    return 0
end

function set_dark(dark):
    if state["dark"] != dark:
        state["dark"] = dark
        call redraw_all()
    end
    return 0
end

# ---- kresleni -------------------------------------------------------------------------------

# Rohy jen u volneho okna; maximalizovane je hranate
function corner(win):
    if gtk.window_is_maximized(win):
        return 0.0
    end
    return RADIUS
end

# Podklad pred detmi okna: sklo, zavoj, odlesk a okraj (False = GTK pak kresli obsah)
function on_draw(cr, win):
    w = Float(gtk.widget_get_allocated_width(win))
    h = Float(gtk.widget_get_allocated_height(win))
    r = corner(win)
    dark = state["dark"]
    call cairo.save(cr)
    call cairo.set_operator(cr, 1)
    call cairo.set_source_rgba(cr, 0, 0, 0, 0)
    call cairo.paint(cr)
    call cairo.set_operator(cr, 2)
    call cairo.rounded_rectangle(cr, 0, 0, w, h, r)
    call cairo.clip(cr)
    if dark:
        call cairo.set_source_rgba(cr, 0.13, 0.14, 0.17, 0.94)
    else:
        call cairo.set_source_rgba(cr, 0.95, 0.95, 0.97, 0.94)
    end
    call cairo.paint(cr)
    if state["surface"] != 0:
        m = state["map"]
        pos = gtk.window_get_position(win)
        sx = clamp(m[3] + Float(pos[0]) * m[2], 0.5, Float(m[0]) - 0.5 - w * m[2])
        sy = clamp(m[4] + Float(pos[1]) * m[2], 0.5, Float(m[1]) - 0.5 - h * m[2])
        call cairo.save(cr)
        call cairo.scale(cr, 1.0 / m[2], 1.0 / m[2])
        call cairo.set_source_surface(cr, state["surface"], -sx, -sy)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    # mlecny zavoj: svetly pro tmavy text, tmavy pro bily text
    if dark:
        call cairo.set_source_rgba(cr, 0.06, 0.07, 0.10, 0.52)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.42)
    end
    call cairo.paint(cr)
    sheen = cairo.pattern_create_linear(0, 0, w * 0.45, h)
    call cairo.pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, 0.14)
    call cairo.pattern_add_color_stop_rgba(sheen, 1.0, 1.0, 1.0, 1.0, 0.0)
    call cairo.set_source(cr, sheen)
    call cairo.paint(cr)
    call cairo.pattern_destroy(sheen)
    call cairo.restore(cr)
    if r > 0.0:
        call cairo.set_line_width(cr, 1.0)
        call cairo.rounded_rectangle(cr, 0.5, 0.5, w - 1.0, h - 1.0, r - 0.5)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.18)
        call cairo.stroke(cr)
        edge = cairo.pattern_create_linear(0, 0, 0, h)
        top = 0.75
        if dark:
            top = 0.30
        end
        call cairo.pattern_add_color_stop_rgba(edge, 0.0, 1.0, 1.0, 1.0, top)
        call cairo.pattern_add_color_stop_rgba(edge, 0.25, 1.0, 1.0, 1.0, top * 0.3)
        call cairo.pattern_add_color_stop_rgba(edge, 1.0, 1.0, 1.0, 1.0, top * 0.15)
        call cairo.rounded_rectangle(cr, 1.5, 1.5, w - 3.0, h - 3.0, r - 1.5)
        call cairo.set_source(cr, edge)
        call cairo.stroke(cr)
        call cairo.pattern_destroy(edge)
    end
    return False
end

# Tvar okna se zaoblenymi rohy (bez kompozitoru by rohy zcernaly); vyrez tapety se pri presunu posune
function on_configure(event, win):
    size = gtk.window_get_size(win)
    key = [size[0], size[1], corner(win)]
    if state["wins"].get(win) != key:
        state["wins"][win] = key
        call gtk.widget_shape_rounded(win, size[0], size[1], key[2])
    end
    call gtk.widget_queue_draw(win)
    return False
end

function on_window_state(event, win):
    change = gtk.event_window_state(event)
    if (change[0] & gtk.WINDOW_STATE_MAXIMIZED) != 0:
        state["wins"][win] = []
        call on_configure(event, win)
    end
    return False
end

# ---- presun a zmena velikosti (spravce oken) ------------------------------------------------

# Hrana pod mysi (pas EDGE px, v rozich podel zaobleni), -1 = vnitrek okna
function edge_at(win, x, y):
    if gtk.window_is_maximized(win) or not resizable(win):
        return -1
    end
    size = gtk.window_get_size(win)
    w = Float(size[0])
    h = Float(size[1])
    e = Float(EDGE)
    left = x < e
    right = x >= w - e
    top = y < e
    bottom = y >= h - e
    cz = RADIUS + e
    near_l = x < cz
    near_r = x >= w - cz
    near_t = y < cz
    near_b = y >= h - cz
    if (top or left) and near_t and near_l:
        return gtk.EDGE_NORTH_WEST
    elif (top or right) and near_t and near_r:
        return gtk.EDGE_NORTH_EAST
    elif (bottom or left) and near_b and near_l:
        return gtk.EDGE_SOUTH_WEST
    elif (bottom or right) and near_b and near_r:
        return gtk.EDGE_SOUTH_EAST
    elif left:
        return gtk.EDGE_WEST
    elif right:
        return gtk.EDGE_EAST
    elif top:
        return gtk.EDGE_NORTH
    elif bottom:
        return gtk.EDGE_SOUTH
    end
    return -1
end

function toggle_maximize(win):
    if gtk.window_is_maximized(win):
        call gtk.window_unmaximize(win)
    else:
        call gtk.window_maximize(win)
    end
    return 0
end

# Stisk na prazdnem miste okna (ovladaci prvky udalost vyridi samy)
function on_press(event, win):
    if gtk.event_button(event) != 1:
        return False
    end
    if gtk.event_is_double_click(event):
        state["press"] = []
        if resizable(win):
            call toggle_maximize(win)
        end
        return True
    end
    edge = edge_at(win, gtk.event_x(event), gtk.event_y(event))
    if edge >= 0:
        call gtk.window_resize_from_event(win, edge, event)
        return True
    end
    # presun az po pohybu o par pixelu: okamzite predani spravci oken by spolklo druhy klik dvojkliku
    coords = gtk.event_root_coords(event)
    state["press"] = [win, coords[0], coords[1], gtk.event_button(event), gtk.event_time(event)]
    return True
end

function on_release(event, win):
    state["press"] = []
    return False
end

function on_motion(event, win):
    p = state["press"]
    if len(p) == 5 and p[0] == win:
        coords = gtk.event_root_coords(event)
        if abs(coords[0] - p[1]) + abs(coords[1] - p[2]) >= 5.0:
            state["press"] = []
            call gtk.window_begin_move_drag(win, p[3], p[1], p[2], p[4])
        end
        return True
    end
    name = EDGE_CURSORS.get(edge_at(win, gtk.event_x(event), gtk.event_y(event)), "")
    if name != state["cursor"].get(win, ""):
        state["cursor"][win] = name
        call gtk.widget_set_cursor(win, name)
    end
    return False
end

# ---- verejne --------------------------------------------------------------------------------

function resizable(win):
    return state["resize"].get(win, False)
end

function setup(win, can_resize):
    if len(EDGE_CURSORS) == 0:
        EDGE_CURSORS[gtk.EDGE_NORTH_WEST] = "nw-resize"
        EDGE_CURSORS[gtk.EDGE_NORTH_EAST] = "ne-resize"
        EDGE_CURSORS[gtk.EDGE_SOUTH_WEST] = "sw-resize"
        EDGE_CURSORS[gtk.EDGE_SOUTH_EAST] = "se-resize"
        EDGE_CURSORS[gtk.EDGE_WEST] = "w-resize"
        EDGE_CURSORS[gtk.EDGE_EAST] = "e-resize"
        EDGE_CURSORS[gtk.EDGE_NORTH] = "n-resize"
        EDGE_CURSORS[gtk.EDGE_SOUTH] = "s-resize"
    end
    call ensure_loaded()
    state["wins"][win] = []
    state["resize"][win] = can_resize
    call gtk.window_set_resizable(win, can_resize)
    call gtk.widget_add_class(win, "lg-window")
    call lgtk.window_set_undecorated(win)
    call gtk.window_set_rgba(win)
    call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    call gtk.connect(win, "draw", on_draw)
    call gtk.connect(win, "configure-event", on_configure)
    call gtk.connect(win, "window-state-event", on_window_state)
    call gtk.connect(win, "button-press-event", on_press)
    call gtk.connect(win, "button-release-event", on_release)
    call gtk.connect(win, "motion-notify-event", on_motion)
    return 0
end

# Okno zmizelo (widget_destroy): uz ho neprekreslovat
function forget(win):
    for d in [state["wins"], state["resize"], state["cursor"]]:
        if win in d:
            call d.pop(win)
        end
    end
    return 0
end

function on_min(button):
    call gtk.window_iconify(gtk.widget_get_toplevel(button))
    return 0
end

function on_max(button):
    return toggle_maximize(gtk.widget_get_toplevel(button))
end

function light(kind, glyph, handler):
    b = gtk.button_new(glyph)
    call gtk.widget_add_class(b, "lg-light")
    call gtk.widget_add_class(b, kind)
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
    call gtk.connect(b, "clicked", handler)
    return b
end

# Semafor vlevo nahore; bez zmeny velikosti okna jen zavrit a minimalizovat
function lights(win, on_close):
    box = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_set_valign(box, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(box, light("lg-close", "×", on_close), False, False, 0)
    call gtk.box_pack_start(box, light("lg-min", "−", on_min), False, False, 0)
    if resizable(win):
        call gtk.box_pack_start(box, light("lg-max", "+", on_max), False, False, 0)
    end
    return box
end
