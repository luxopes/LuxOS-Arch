# LuxOS - horni lista na Waylandu (1.1.0): plocha layer-shell nahore na kazdem monitoru (vrstva TOP, kotva
# nahore/vlevo/vpravo, vyhradni zona), pozadi z matneho skla tapety (luxos_material). Nahrazuje xfce4-panel
# s pluginem luxos-bar.c, genmon skripty (hodiny, baterie, sit, nazev aplikace) a systray.
#
#   vlevo     logo LuxOS (nabidka systemu) a nazev aktivni aplikace (wlr-foreign-toplevel, stav activated)
#   uprostred hodiny jako luxos-clock (datum podle jazyka plochy), klik = kalendar
#   vpravo    oznamovaci oblast (StatusNotifierItem), rozlozeni klavesnice (z luxwm, klik = nabidka rozlozeni),
#             zvuk, Wi-Fi/sit, baterie,
#             zvonek s historii oznameni (luxos-notify) a Ovladaci centrum (luxos-cc-toggle)
#
# Pismo listy: v tmavem rezimu bile, ve svetlem podle tapety pod listou (kontrast WCAG s hysterezi,
# tokens.want_dark_ink jako luxos-bar.c); BAR_TEXT=white|dark v appearance.conf ho pevne nastavi. Pod bilym
# pismem na svetle tapete zavoj (scrim) - samostatna plocha na vrstve BOTTOM bez vstupu (DESKTOP_SCRIM=0 vypne).
# Vse na udalosti: okna, monitory a stav systemu chodi signaly (Wayland, D-Bus, pactl subscribe), jediny
# casovac jsou hodiny jednou za minutu.
#
# Ladeni a testy: LUXOS_BAR_TRACE=1 vypisuje udalosti na stdout, LUXOS_BAR_NOW="YYYY-MM-DD HH:MM" zastavi hodiny.
load env, cairo
load glib, gtk, gio
load luxos_glib as lglib
load luxos_gtk
load luxos_sys
load luxos_text as text
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_wl as wl
load luxos_tokens as tokens
load luxos_material as material
load luxos_bar_status as status
load luxos_bar_popup as popup
load luxos_hub_popup as hub_popup
load luxos_sni as sni

HEIGHT = tokens.BAR["height"]
DEFAULT_APPS = "/usr/share/applications"
RENAMED_APPS = "/var/lib/luxos/apps/applications"

# Kratke nazvy aplikaci, jejichz Name= je zbytecne dlouhe (luxos-appname-watch)
SHORT = {"thunar": "Files", "luxos-terminal": "Terminal", "xfce4-terminal": "Terminal", "luxos-text": "Text Editor",
    "xfce4-settings-manager": "Settings", "org.xfce.ristretto": "Image Viewer", "ristretto": "Image Viewer",
    "org.gnome.evince": "Document Viewer", "evince": "Document Viewer", "xfce4-taskmanager": "System Monitor",
    "luxos-calendar": "Calendar", "luxos-control-center": "Control Center", "luxos-whats-new": "What's New",
    "luxos-screenshot": "Screenshot"}

# Nabidka loga: [text, prikaz]; "" = oddelovac
MENU = [["About This Computer", ["luxos-about"]], ["Settings", ["luxos-settings"]], ["Launchpad", ["luxos-launchpad"]], "",
    # lista bezi jako uzivatelska sluzba mimo relaci logindu: relaci urcuje XDG_SESSION_ID z luxos-wayland-session
    ["Lock Screen", ["sh", "-c", "exec loginctl lock-session \"${XDG_SESSION_ID:-auto}\""]],
    ["Sign Out", ["sh", "-c", "exec loginctl terminate-session \"${XDG_SESSION_ID:-auto}\""]],
    ["Restart", ["systemctl", "reboot"]], ["Shut Down", ["systemctl", "poweroff"]]]

bars = []
ui = {"provider": 0, "app": "", "app_names": {}, "wm_classes": None, "clock": "", "clock_tip": "", "conf": {},
      "dark": False, "trace": env.get("LUXOS_BAR_TRACE", "") == "1", "menu": 0, "layout_menu": 0, "layout_items": [],
      "layout_names": [], "thumbs": {}}

function trace(message):
    if ui["trace"]:
        print message
    end
    return 0
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function real_time_us():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_get_real_time"))
    end
end

function monotonic_ms():
    return glib.monotonic_time() // 1000
end

# ---- nastaveni vzhledu ------------------------------------------------------------------------

function config_dir():
    return glib.user_config_dir() + "/luxos"
end

function read_conf():
    ui["conf"] = text.parse_kv(lglib.read_text(config_dir() + "/appearance.conf"))
    ui["dark"] = lglib.read_text(config_dir() + "/appearance").strip() == "dark"
    return 0
end

function conf(key, fallback):
    value = ui["conf"].get(key, fallback).strip()
    if len(value) >= 2 and (value[0] == "\"" or value[0] == "'"):
        value = value[1:-1]
    end
    return value
end

function bar_css():
    white = tokens.css_color(tokens.COLORS["on_glass"])
    dark = tokens.css_color(tokens.COLORS["on_glass_light"])
    plain = " background: none; background-image: none; border: none; box-shadow: none; outline: none;"
    return (tokens.gtk3_css(ui["dark"])
        + "window.luxos-bar { background: transparent; }\n"
        + ".luxos-bar label { font-size: " + String(tokens.FONT["body"]) + "px; }\n"
        + ".luxos-bar .lb-app { font-weight: " + String(tokens.WEIGHT["bold"]) + "; }\n"
        + ".luxos-bar .lb-clock { font-weight: " + String(tokens.WEIGHT["bold"]) + "; }\n"
        + ".luxos-bar button.lb {" + plain + " padding: 0 5px; margin: 3px 1px; min-height: 0; min-width: 0; border-radius: "
        + String(tokens.RADIUS["menu_item"]) + "px; }\n"
        + ".luxos-bar .lb-badge { font-size: 10px; font-weight: " + String(tokens.WEIGHT["bold"]) + "; border: 1.5px solid; border-radius: 4px;"
        + " padding: 0 3px; }\n"
        + ".luxos-bar.ink-white label, .luxos-bar.ink-white image { color: " + white + "; }\n"
        + ".luxos-bar.ink-white label { text-shadow: 0 1px 2px rgba(0, 0, 0, 0.30); }\n"
        + ".luxos-bar.ink-white image { -gtk-icon-shadow: 0 1px 2px rgba(0, 0, 0, 0.30); }\n"
        + ".luxos-bar.ink-white .lb-badge { border-color: " + white + "; }\n"
        + ".luxos-bar.ink-white button.lb:hover, .luxos-bar.ink-white button.lb.open { background-color: rgba(255, 255, 255, 0.20); }\n"
        + ".luxos-bar.ink-dark label, .luxos-bar.ink-dark image { color: " + dark + "; }\n"
        + ".luxos-bar.ink-dark .lb-badge { border-color: " + dark + "; }\n"
        + ".luxos-bar.ink-dark button.lb:hover, .luxos-bar.ink-dark button.lb.open { background-color: rgba(0, 0, 0, 0.09); }\n")
end

function apply_css():
    css = bar_css()
    if ui["provider"] == 0:
        ui["provider"] = gtk.css_load(css)
    else:
        call luxos_gtk.css_set(ui["provider"], css)
    end
    return 0
end

# Zmena appearance.conf nebo rezimu (luxos-appearance): nova tapeta, CSS a pismo bez restartu
function on_conf_changed(path, event, other):
    # G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT 1, DELETED 2, CREATED 3, MOVED_IN 9, RENAMED 8
    if event != 1 and event != 2 and event != 3 and event != 8 and event != 9:
        return 0
    end
    call read_conf()
    call material.reload()
    ui["thumbs"] = {}
    call apply_css()
    call popup.set_dark(ui["dark"])
    for bar in bars:
        call place_clock(bar)
        call refresh_look(bar)
    end
    return 0
end

# ---- tapeta pod listou: pismo a zavoj -----------------------------------------------------------

# Zmensenina tapety (bez rozostreni) a jeji mapa na vystup jako material.map_for (vyplni, prebytek orizne)
function thumb(path):
    key = path + "|" + String(lglib.stat(path))
    hit = ui["thumbs"].get(key)
    if hit != None:
        return hit
    end
    pb = gtk.pixbuf_new_from_file_at_scale(path, 256, 256, True)
    if pb == 0:
        return None
    end
    w = gtk.pixbuf_get_width(pb)
    h = gtk.pixbuf_get_height(pb)
    surface = cairo.image_surface_create(cairo.FORMAT_RGB24, w, h)
    cr = cairo.create(surface)
    call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call glib.object_unref(pb)
    hit = [cairo.surface_to_intarray(surface), w, h]
    call cairo.surface_destroy(surface)
    ui["thumbs"] = {key: hit}
    return hit
end

# Prumerny linearni jas pasu 0..band px nahore na vystupu out_w x out_h; ton [r, g, b, a] se primicha v sRGB
# (luxos-bar.c white_contrast)
function top_lum(th, out_w, out_h, band, tint):
    IntArray(pixels) = th[0]
    pw = Float(th[1])
    ph = Float(th[2])
    sc = min(pw / Float(max(1, out_w)), ph / Float(max(1, out_h)))
    ox = (pw - Float(out_w) * sc) / 2.0
    oy = (ph - Float(out_h) * sc) / 2.0
    x0 = Int(ox)
    x1 = max(x0 + 1, Int(ox + Float(out_w) * sc))
    y0 = Int(oy)
    y1 = max(y0 + 1, Int(oy + Float(band) * sc + 0.5))
    a = Float(tint[3])
    total = 0.0
    count = 0
    for y in range(y0, min(y1, th[2])):
        for x in range(x0, min(x1, th[1])):
            px = pixels[y * th[1] + x]
            r = Float((px >> 16) & 255) * (1.0 - a) + tint[0] * 255.0 * a
            g = Float((px >> 8) & 255) * (1.0 - a) + tint[1] * 255.0 * a
            b = Float(px & 255) * (1.0 - a) + tint[2] * 255.0 * a
            total = total + tokens.luminance(Int(r + 0.5), Int(g + 0.5), Int(b + 0.5))
            count = count + 1
        end
    end
    return total / Float(max(1, count))
end

# Bile nebo tmave pismo a sila zavoje pro listu podle tapety jejiho vystupu
function decide_look(bar):
    forced = conf("BAR_TEXT", "")
    path = material.wallpaper_path(bar["output"])
    th = None
    if path != "":
        th = thumb(path)
    end
    dark_ink = False
    if not ui["dark"]:
        if forced == "dark":
            dark_ink = True
        elif forced != "white" and th != None:
            # tapeta sama (bez kouroveho tonu listy z X11: pod pismem je sklo se zavojem); prahy INK odpovidaji
            # namerenym tapetam (bila ~1,0, bezova ~1,2, Citrus ~1,5, Sunrise ~2,4)
            c = tokens.white_contrast(top_lum(th, bar["out_w"], bar["out_h"], HEIGHT, [0.0, 0.0, 0.0, 0.0]))
            dark_ink = tokens.want_dark_ink(c, bar["dark_ink"])
        end
    end
    scrim = 0.0
    if not dark_ink and th != None and conf("DESKTOP_SCRIM", "1") != "0":
        scrim = tokens.scrim_strength(top_lum(th, bar["out_w"], bar["out_h"], tokens.INK["scrim_height"], [0.0, 0.0, 0.0, 0.0]))
        if scrim < 0.01:
            scrim = 0.0
        end
    end
    changed = dark_ink != bar["dark_ink"] or bar["scrim"] != scrim
    bar["dark_ink"] = dark_ink
    bar["scrim"] = scrim
    if changed or bar["traced"] == False:
        bar["traced"] = True
        ink = "white"
        if dark_ink:
            ink = "dark"
        end
        call trace("look " + bar["output"] + " ink=" + ink + " scrim=" + String(Int(scrim * 100.0)))
    end
    return 0
end

function refresh_look(bar):
    call decide_look(bar)
    call luxos_gtk.widget_set_class(bar["win"], "ink-dark", bar["dark_ink"])
    call luxos_gtk.widget_set_class(bar["win"], "ink-white", not bar["dark_ink"])
    call update_scrim(bar)
    call gtk.widget_queue_draw(bar["win"])
    return 0
end

# Zavoj: 1 nahore, do ztracena na scrim_height (tokens.scrim_profile), nejvys scrim_max x sila
function paint_scrim(cr, strength, height):
    if strength <= 0.0:
        return 0
    end
    top = tokens.INK["scrim_max"] * strength
    pattern = cairo.pattern_create_linear(0.0, 0.0, 0.0, Float(tokens.INK["scrim_height"]))
    for i in range(9):
        t = Float(i) / 8.0
        call cairo.pattern_add_color_stop_rgba(pattern, t, 0.0, 0.0, 0.0, top * tokens.scrim_profile(t))
    end
    call cairo.set_source(cr, pattern)
    call cairo.rectangle(cr, 0.0, 0.0, 100000.0, Float(height))
    call cairo.fill(cr)
    call cairo.pattern_destroy(pattern)
    return 0
end

function on_bar_draw(bar, cr, widget):
    w = gtk.widget_get_allocated_width(widget)
    ink = 0
    if bar["dark_ink"]:
        ink = 1
    end
    hit = material.strip(bar["output"], bar["out_w"], bar["out_h"], 0, 0, w, HEIGHT, 0, ink, bar["scale"])
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    if hit != None:
        call cairo.set_source_surface(cr, hit[0], 0.0, 0.0)
    else:
        # bez tapety ton listy jako luxos-bar.c (svetly / tmavy, BAR_OPACITY)
        t = tokens.BAR["tint_light"]
        if not bar["dark_ink"]:
            t = tokens.BAR["tint_dark"]
        end
        call cairo.set_source_rgba(cr, t[0], t[1], t[2], Float(tokens.BAR["opacity"]) / 100.0)
    end
    call cairo.paint(cr)
    call cairo.restore(cr)
    call paint_scrim(cr, bar["scrim"], HEIGHT)
    if not bar["drawn"]:
        bar["drawn"] = True
        call trace("drawn " + bar["output"] + " " + String(w) + "x" + String(HEIGHT))
    end
    return False
end

function on_scrim_draw(bar, cr, widget):
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    call paint_scrim(cr, bar["scrim"], tokens.INK["scrim_height"])
    return False
end

# Kliky na zavoj jdou na plochu pod nim (prazdna vstupni oblast)
function on_scrim_realize(bar, widget):
    call luxos_gtk.widget_input_rect(widget, 0, 0, 0, 0)
    return 0
end

function update_scrim(bar):
    if bar["scrim"] <= 0.0:
        if bar["scrim_win"] != 0:
            call gtk.widget_hide(bar["scrim_win"])
        end
        return 0
    end
    win = bar["scrim_win"]
    if win == 0:
        win = gtk.window_new("luxos-bar-scrim")
        call layer.init_for_window(win)
        call layer.set_namespace(win, "luxos-bar-scrim")
        call layer.set_layer(win, layer.LAYER_BOTTOM)
        call layer.set_monitor(win, bar["monitor"])
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_LEFT, layer.EDGE_RIGHT])
        # -1: az k hornimu okraji, pod vyhradnou zonou listy
        call layer.set_exclusive_zone(win, -1)
        call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
        call gtk.widget_set_size_request(win, -1, tokens.INK["scrim_height"])
        call luxos_gtk.window_set_rgba(win)
        call gtk.widget_add_class(win, "luxos-bar")
        call connect(bar, win, "draw", 1, on_scrim_draw, bar)
        call connect(bar, win, "realize", 0, on_scrim_realize, bar)
        bar["scrim_win"] = win
    end
    call gtk.widget_show(win)
    call gtk.widget_queue_draw(win)
    return 0
end

# ---- listy na monitorech ------------------------------------------------------------------------

# Nazev vystupu Waylandu (HEADLESS-1, eDP-1) pro monitor GDK podle polohy z wlr-output-management (wl_output
# polohu neposila, xdg-output knihovna nema); tapeta muze byt pro kazdy vystup
function output_for(monitor):
    geo = layer.monitor_geometry(monitor)
    if wl.available():
        for h in wl.heads():
            info = wl.head_info(h)
            if info[2] and info[3] == geo[0] and info[4] == geo[1]:
                return info[0]
            end
        end
        names = wl.outputs()
        if len(names) == 1:
            return wl.output_name(names[0])
        end
    end
    model = layer.monitor_model(monitor)
    if model == None:
        return ""
    end
    return model
end

# Obsluha signalu patrici liste: zaznamy se uvolni s listou (odpojeni monitoru)
function connect(bar, instance, signal, nargs, handler, bound):
    bar["handlers"].append(lglib.connect_data(instance, signal, nargs, handler, bound))
    return 0
end

function bar_button(bar, child, tooltip, on_click, kind):
    b = gtk.button_new_empty()
    call gtk.widget_add_class(b, "lb")
    call gtk.widget_set_can_focus(b, False)
    call gtk.container_add(b, child)
    if tooltip != "":
        call gtk.widget_set_tooltip(b, tooltip)
    end
    call connect(bar, b, "button-press-event", 1, on_click, kind)
    return b
end

function icon(name):
    image = gtk.image_new_from_icon_name(name, 1)
    call gtk.image_set_pixel_size(image, 16)
    return image
end

function icon_item(bar, kind, icon_name, tooltip, side):
    image = icon(icon_name)
    b = bar_button(bar, image, tooltip, on_item_press, kind)
    bar["items"][kind] = [b, image, 0]
    call gtk.box_pack_start(side, b, False, False, 0)
    return b
end

function build_bar(bar):
    win = bar["win"]
    box = gtk.box_new(0, 0)
    call gtk.widget_set_margins(box, 0, 4, 0, 0)
    left = gtk.box_new(0, 0)
    right = gtk.box_new(0, 0)
    call icon_item(bar, "menu", "luxos-logo-symbolic", "", left)
    app = gtk.label_new(ui["app"])
    call gtk.widget_add_class(app, "lb-app")
    call gtk.label_set_ellipsize(app, 3)
    call gtk.label_set_max_width_chars(app, 40)
    call gtk.widget_set_margins(app, 0, 6, 0, 0)
    call gtk.box_pack_start(left, app, False, False, 0)
    bar["app"] = app
    clock = gtk.label_new(ui["clock"])
    call gtk.widget_add_class(clock, "lb-clock")
    b = bar_button(bar, clock, ui["clock_tip"], on_item_press, "calendar")
    bar["items"]["calendar"] = [b, clock, 0]
    bar["clock"] = clock
    tray = gtk.box_new(0, 0)
    call gtk.box_pack_start(right, tray, False, False, 0)
    bar["tray"] = tray
    badge = gtk.label_new("")
    call gtk.widget_add_class(badge, "lb-badge")
    kb = bar_button(bar, badge, "", on_item_press, "keyboard")
    bar["items"]["keyboard"] = [kb, badge, 0]
    if ui["trace"]:
        call gtk.connect(kb, "size-allocate", on_badge_allocate)
    end
    call gtk.box_pack_start(right, kb, False, False, 0)
    # poradi jako lista na X11: klavesnice, sit, zvuk, baterie, Hledani, Ovladaci centrum, oznameni, hodiny
    call icon_item(bar, "network", "network-wireless-signal-excellent-symbolic", i18n.T("Wi-Fi"), right)
    call icon_item(bar, "sound", "audio-volume-high-symbolic", i18n.T("Sound"), right)
    battery = gtk.box_new(0, 3)
    bat_icon = icon("battery-level-100-symbolic")
    bat_label = gtk.label_new("")
    call gtk.box_pack_start(battery, bat_icon, False, False, 0)
    call gtk.box_pack_start(battery, bat_label, False, False, 0)
    bb = bar_button(bar, battery, "", on_item_press, "battery")
    bar["items"]["battery"] = [bb, bat_icon, bat_label]
    call gtk.box_pack_start(right, bb, False, False, 0)
    call icon_item(bar, "search", "luxos-search-symbolic", i18n.T("Search"), right)
    call icon_item(bar, "control-center", "luxos-control-center-symbolic", i18n.T("Control Center"), right)
    call icon_item(bar, "notifications", "notification-symbolic", i18n.T("Notifications"), right)
    call connect(bar, bar["items"]["sound"][0], "scroll-event", 1, on_sound_scroll, 0)
    call gtk.widget_add_events(bar["items"]["sound"][0], 2097152 + 8388608)
    call gtk.box_pack_start(box, left, False, False, 0)
    call gtk.box_pack_end(box, right, False, False, 0)
    bar["box"] = box
    bar["right"] = right
    bar["clock_center"] = None
    call place_clock(bar)
    call gtk.container_add(win, box)
    return 0
end

# Hodiny vpravo jako na X11; BAR_CLOCK=center v appearance.conf je da na stred cele listy, ne mezi levou
# a pravou cast (luxos-bar.c bod 1). Zmena nastaveni hodiny presune bez restartu listy.
function place_clock(bar):
    center = ui["conf"].get("BAR_CLOCK", "") == "center"
    if bar["clock_center"] == center:
        return 0
    end
    b = bar["items"]["calendar"][0]
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_object_ref"), ptr(b))
        if bar["clock_center"] == True:
            call __lsl_qbe_call2(__lsl_symbol("gtk_box_set_center_widget"), ptr(bar["box"]), 0)
        elif bar["clock_center"] == False:
            call __lsl_qbe_call2(__lsl_symbol("gtk_container_remove"), ptr(bar["right"]), ptr(b))
        end
        if center:
            call __lsl_qbe_call2(__lsl_symbol("gtk_box_set_center_widget"), ptr(bar["box"]), ptr(b))
        else:
            call gtk.box_pack_start(bar["right"], b, False, False, 0)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(b))
    end
    bar["clock_center"] = center
    return 0
end

function add_bar(monitor):
    for bar in bars:
        if bar["monitor"] == monitor:
            return bar
        end
    end
    geo = layer.monitor_geometry(monitor)
    win = gtk.window_new("luxos-bar")
    bar = {"win": win, "monitor": monitor, "output": output_for(monitor), "out_w": geo[2], "out_h": geo[3],
           "scale": max(1, monitor_scale(monitor)), "dark_ink": False, "scrim": 0.0, "scrim_win": 0, "items": {},
           "drawn": False, "traced": False, "handlers": []}
    call layer.init_for_window(win)
    call layer.set_namespace(win, "luxos-bar")
    call layer.set_layer(win, layer.LAYER_TOP)
    call layer.set_monitor(win, monitor)
    call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_LEFT, layer.EDGE_RIGHT])
    call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
    call layer.auto_exclusive_zone_enable(win)
    call gtk.widget_set_size_request(win, -1, HEIGHT)
    call luxos_gtk.window_set_rgba(win)
    call gtk.widget_add_class(win, "luxos-bar")
    call build_bar(bar)
    call connect(bar, win, "draw", 1, on_bar_draw, bar)
    # zaznam se neuvolnuje: GdkMonitor muze zit i po odpojeni (reference GDK) a signal poslat pozdeji
    call lglib.connect_data(monitor, "notify::geometry", 1, on_monitor_changed, bar)
    bars.append(bar)
    call refresh_look(bar)
    call gtk.widget_show_all(win)
    call apply_status(bar)
    call sni.attach(bar["tray"])
    call trace("bar added " + bar["output"] + " " + String(geo[2]) + "x" + String(geo[3]))
    return bar
end

function monitor_scale(monitor):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gdk_monitor_get_scale_factor"), ptr(monitor))
    end
end

function remove_bar(monitor):
    for bar in List(bars):
        if bar["monitor"] == monitor:
            call bars.remove(bar)
            call popup.close_all()
            call sni.detach(bar["tray"])
            if bar["scrim_win"] != 0:
                call gtk.widget_destroy(bar["scrim_win"])
            end
            call gtk.widget_destroy(bar["win"])
            call material.forget_output(bar["output"])
            for id in bar["handlers"]:
                call lglib.release(id)
            end
            call trace("bar removed " + bar["output"])
        end
    end
    return 0
end

function on_monitor_added(monitor, display):
    call add_bar(monitor)
    return 0
end

function on_monitor_removed(monitor, display):
    call remove_bar(monitor)
    return 0
end

# Zmena rozliseni nebo meritka monitoru: jiny vyrez tapety
function on_monitor_changed(bar, pspec, monitor):
    if bar not in bars:
        return 0
    end
    geo = layer.monitor_geometry(monitor)
    bar["out_w"] = geo[2]
    bar["out_h"] = geo[3]
    bar["scale"] = max(1, monitor_scale(monitor))
    call refresh_look(bar)
    return 0
end

# ---- nazev aktivni aplikace ---------------------------------------------------------------------

# Radky skupiny [Desktop Entry] souboru .desktop -> slovnik
function desktop_entry(path):
    result = {}
    inside = False
    for line in lglib.read_text(path).split("\n"):
        if line.startswith("["):
            inside = line.strip() == "[Desktop Entry]"
            continue
        end
        cut = line.find("=")
        if inside and cut > 0:
            key = line[0:cut].strip()
            if key not in result:
                result[key] = line[cut + 1:].strip()
            end
        end
    end
    return result
end

function apps_dirs():
    data = env.get("XDG_DATA_HOME", "")
    if data == "":
        data = glib.home_dir() + "/.local/share"
    end
    return [data + "/applications", DEFAULT_APPS]
end

# StartupWMClass -> soubor; jen kdyz app_id neodpovida nazvu souboru (aplikace X11 pres XWayland, stare GTK)
function wm_class_index():
    if ui["wm_classes"] == None:
        index = {}
        for dir in apps_dirs():
            for name in lglib.list_dir(dir):
                if name.endswith(".desktop"):
                    wm = desktop_entry(dir + "/" + name).get("StartupWMClass", "")
                    if wm != "" and wm.lower() not in index:
                        index[wm.lower()] = dir + "/" + name
                    end
                end
            end
        end
        ui["wm_classes"] = index
    end
    return ui["wm_classes"]
end

function desktop_file(app_id):
    for dir in apps_dirs():
        if exists(dir + "/" + app_id + ".desktop"):
            return dir + "/" + app_id + ".desktop"
        end
    end
    return wm_class_index().get(app_id.lower(), "")
end

function app_name(app_id):
    hit = ui["app_names"].get(app_id)
    if hit != None:
        return hit
    end
    name = ""
    short = SHORT.get(app_id.lower())
    if short != None:
        name = i18n.T(short)
    else:
        path = desktop_file(app_id)
        if path != "":
            # prejmenovane aplikace LuxOS (luxos-apps-sync) maji prednost
            base = path[text.rfind(path, "/") + 1:]
            if exists(RENAMED_APPS + "/" + base):
                path = RENAMED_APPS + "/" + base
            end
            entry = desktop_entry(path)
            lang = i18n.lang()
            locale = env.get("LANG", "").split(".")[0]
            for key in ["Name[" + locale + "]", "Name[" + lang + "]", "Name"]:
                if name == "":
                    name = entry.get(key, "")
                end
            end
        end
    end
    if name == "":
        name = app_id
    end
    ui["app_names"][app_id] = name
    return name
end

function update_app():
    name = ""
    if wl.available():
        for t in wl.toplevels():
            if (wl.toplevel_state(t) & wl.STATE_ACTIVATED) != 0:
                app_id = wl.toplevel_app_id(t)
                if app_id != "":
                    name = app_name(app_id)
                end
                break
            end
        end
    end
    if name == "":
        name = i18n.T("Desktop")
    end
    if name == ui["app"]:
        return 0
    end
    ui["app"] = name
    for bar in bars:
        call gtk.label_set_text(bar["app"], name)
    end
    call trace("app " + name)
    return 0
end

function on_wl(kind, handle, a, b):
    if kind == wl.TOPLEVEL_NEW or kind == wl.TOPLEVEL_CHANGED or kind == wl.TOPLEVEL_CLOSED:
        call update_app()
    elif kind == wl.OUTPUT_NEW or kind == wl.HEAD_NEW or kind == wl.HEAD_CHANGED:
        # vystup Waylandu muze prijit az po monitoru GDK: nazev pro tapetu doplnit
        for bar in bars:
            name = output_for(bar["monitor"])
            if name != bar["output"]:
                bar["output"] = name
                call refresh_look(bar)
            end
        end
    end
    return 0
end

# ---- hodiny ----------------------------------------------------------------------------------------

function clock_parts():
    fixed = env.get("LUXOS_BAR_NOW", "")
    if fixed != "":
        d = fixed.split(" ")[0].split("-")
        y = Int(d[0])
        m = Int(d[1])
        day = Int(d[2])
        return [y, m, day, glib.weekday(y, m, day) - 1, fixed.split(" ")[1]]
    end
    p = luxos_sys.strftime_local("%Y %-m %-d %u %H:%M").split(" ")
    return [Int(p[0]), Int(p[1]), Int(p[2]), Int(p[3]) - 1, p[4]]
end

function update_clock():
    p = clock_parts()
    now = i18n.weekday_short(p[3]) + " " + i18n.format_date(p[0], p[1], p[2], p[3], "short") + "  " + p[4]
    tip = i18n.format_date(p[0], p[1], p[2], p[3], "year")
    if now == ui["clock"]:
        return 0
    end
    ui["clock"] = now
    ui["clock_tip"] = tip
    for bar in bars:
        call gtk.label_set_text(bar["clock"], now)
        call gtk.widget_set_tooltip(bar["items"]["calendar"][0], tip)
    end
    return 0
end

# Jednorazovy casovac na zacatek dalsi minuty (po probuzeni hned znovu, viz status.on_resume)
function schedule_clock():
    if ui.get("clock_timer", 0) != 0:
        call glib.source_remove(ui["clock_timer"])
    end
    left = 60000 - (real_time_us() // 1000) % 60000 + 20
    ui["clock_timer"] = lglib.timeout_add_data(left, on_clock_tick, 0)
    return 0
end

function on_clock_tick(unused):
    ui["clock_timer"] = 0
    call update_clock()
    call schedule_clock()
    return False
end

# ---- stav systemu --------------------------------------------------------------------------------

function set_item(bar, kind, icon_name, tooltip, visible):
    item = bar["items"][kind]
    call gtk.widget_set_visible(item[0], visible)
    if icon_name != "":
        call gtk.image_set_from_icon_name(item[1], icon_name, 1)
    end
    call gtk.widget_set_tooltip(item[0], tooltip)
    return 0
end

function apply_status(bar):
    s = status.state
    net = s["network"]
    call set_item(bar, "network", net["icon"], net["tip"], net["icon"] != "")
    snd = s["sound"]
    call set_item(bar, "sound", snd["icon"], snd["tip"], snd["icon"] != "")
    bat = s["battery"]
    call set_item(bar, "battery", bat["icon"], bat["tip"], bat["icon"] != "")
    call gtk.label_set_text(bar["items"]["battery"][2], bat["text"])
    notes = s["notifications"]
    call gtk.image_set_from_icon_name(bar["items"]["notifications"][1], notes["icon"], 1)
    kb = s["keyboard"]
    call gtk.label_set_text(bar["items"]["keyboard"][1], kb["short"])
    call gtk.widget_set_visible(bar["items"]["keyboard"][0], kb["short"] != "")
    call gtk.widget_set_tooltip(bar["items"]["keyboard"][0], kb["tip"])
    return 0
end

function on_status(kind):
    for bar in bars:
        call apply_status(bar)
    end
    call trace("status " + kind + " " + status.summary(kind))
    if kind == "resume":
        call update_clock()
        call schedule_clock()
    end
    return 0
end

# ---- kliky ------------------------------------------------------------------------------------------

function plain_press(event):
    unsafe:
        # GdkEventButton.type: GDK_BUTTON_PRESS 4
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_unbox_int(event))) == 4
    end
end

function bar_of(widget):
    win = gtk.widget_get_toplevel(widget)
    for bar in bars:
        if bar["win"] == win:
            return bar
        end
    end
    return None
end

function show_menu(widget):
    if ui["menu"] == 0:
        menu = luxos_gtk.menu_new()
        for entry in MENU:
            if entry == "":
                call luxos_gtk.menu_append(menu, luxos_gtk.separator_menu_item_new())
                continue
            end
            item = luxos_gtk.menu_item_new(i18n.T(entry[0]))
            call lglib.connect_data(item, "activate", 0, on_menu_item, entry[1])
            call luxos_gtk.menu_append(menu, item)
        end
        call gtk.widget_show_all(menu)
        ui["menu"] = menu
    end
    unsafe:
        # GDK_GRAVITY_SOUTH_WEST 7 / NORTH_WEST 1: pod tlacitkem (xdg_popup nad plochou listy)
        call __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), ptr(ui["menu"]), ptr(widget), 7, 1, 0)
    end
    return 0
end

function on_menu_item(argv, item):
    call glib.spawn_quiet(argv)
    return 0
end

# Nabidka rozlozeni pod odznakem: aktivni zaskrtnute, klik prepne (luxwm), dole nastaveni. Stavi se znovu
# jen pri jinem seznamu rozlozeni (zaznamy signalu se neuvolnuji).
function show_layouts(widget):
    kb = status.state["keyboard"]
    if ui["layout_menu"] == 0 or ui["layout_names"] != kb["names"]:
        if ui["layout_menu"] != 0:
            call gtk.widget_destroy(ui["layout_menu"])
        end
        menu = luxos_gtk.menu_new()
        items = []
        for i in range(len(kb["names"])):
            item = luxos_gtk.check_menu_item_new(kb["names"][i])
            call lglib.connect_data(item, "activate", 0, on_layout_item, i)
            call luxos_gtk.menu_append(menu, item)
            items.append(item)
        end
        if len(items) > 0:
            call luxos_gtk.menu_append(menu, luxos_gtk.separator_menu_item_new())
        end
        settings = luxos_gtk.menu_item_new(i18n.T("Keyboard Settings…"))
        call lglib.connect_data(settings, "activate", 0, on_menu_item, ["luxos-keyboard"])
        call luxos_gtk.menu_append(menu, settings)
        call gtk.widget_show_all(menu)
        ui["layout_menu"] = menu
        ui["layout_items"] = items
        ui["layout_names"] = [name for name in kb["names"]]
    end
    # set_active posle "activate"; on_layout_item prepina jen na neaktivni rozlozeni, takze nic nespusti
    for i in range(len(ui["layout_items"])):
        call luxos_gtk.check_menu_item_set_active(ui["layout_items"][i], i == kb["current"])
    end
    call trace("layout menu " + String(len(ui["layout_items"])))
    unsafe:
        call __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), ptr(ui["layout_menu"]), ptr(widget), 7, 1, 0)
    end
    return 0
end

# Poloha odznaku pro testy (klik na nabidku rozlozeni)
function on_badge_allocate(allocation, widget):
    a = gtk.widget_get_allocation(widget)
    if a[2] <= 1:
        return 0
    end
    unsafe:
        xy = __lsl_byte_zeros(8)
        base = lglib.data(xy)
        call __lsl_qbe_call6(__lsl_symbol("gtk_widget_translate_coordinates"), ptr(widget), ptr(gtk.widget_get_toplevel(widget)), 0, 0, base, base + 4)
        x = __lsl_qbe_s32(__lsl_qbe_load32(base))
    end
    call trace("badge keyboard " + String(x) + " " + String(a[2]))
    return 0
end

function on_layout_item(index, item):
    # zaskrtnuti nastavi i program (set_active), prepina jen klik na neaktivni rozlozeni
    if index != status.state["keyboard"]["current"] and luxos_gtk.check_menu_item_get_active(item):
        call trace("layout switch " + String(index))
        call status.switch_layout(index)
    end
    return 0
end

function on_item_press(kind, event, widget):
    # jen prvni stisk: rychly druhy klik posle navic GDK_2BUTTON_PRESS (prepnuti by se vratilo)
    if gtk.event_button(event) != 1 or plain_press(event) == False:
        return True
    end
    bar = bar_of(widget)
    if bar == None:
        return False
    end
    if kind == "menu":
        call popup.close_all()
        call show_menu(widget)
    elif kind == "control-center" or kind == "battery":
        call popup.close_all()
        call open_hub(bar, widget, gtk.event_time(event), "luxos-cc-toggle")
    elif kind == "calendar":
        call popup.close_all()
        call open_hub(bar, widget, gtk.event_time(event), "luxos-calendar-toggle")
    elif kind == "keyboard":
        call popup.close_all()
        call show_layouts(widget)
    elif kind == "search":
        call popup.close_all()
        call glib.spawn_quiet(["luxos-search"])
    elif kind == "network" and status.state["network"]["portal"]:
        call popup.close_all()
        call glib.spawn_quiet(["luxos-network-login"])
    else:
        name = kind
        if kind == "network":
            name = "wifi"
        end
        a = gtk.widget_get_allocation(widget)
        call popup.toggle(name, bar["monitor"], bar["output"], bar["out_w"], bar["out_h"], bar["scale"], a[0] + a[2] // 2,
                          widget, gtk.event_time(event))
    end
    return True
end

# Ovladaci centrum a Kalendar bezi v luxos-hub a signal nic nenese: monitor listy a stred tlacitka mu preda soubor
function open_hub(bar, widget, pressed, toggle):
    a = gtk.widget_get_allocation(widget)
    geo = layer.monitor_geometry(bar["monitor"])
    call hub_popup.write_anchor(geo[0], geo[1], a[0] + a[2] // 2, pressed)
    call trace(toggle + " " + String(geo[0]) + " " + String(a[0] + a[2] // 2))
    call glib.spawn_quiet([toggle])
    return 0
end

function on_sound_scroll(unused, event, widget):
    d = gtk.event_scroll_direction(event)
    if d == 0:
        call status.change_volume(5)
    elif d == 1:
        call status.change_volume(-5)
    elif d == 4:
        deltas = gtk.event_scroll_deltas(event)
        if deltas[1] < 0.0:
            call status.change_volume(5)
        elif deltas[1] > 0.0:
            call status.change_volume(-5)
        end
    end
    return True
end

# ---- start -------------------------------------------------------------------------------------------

function gtk_ready():
    unsafe:
        return __lsl_qbe_icall2(__lsl_symbol("gtk_init_check"), 0, 0) != 0
    end
end

call glib.setlocale()
if not gtk_ready() or not layer.is_wayland() or not layer.is_supported():
    # kod 2: systemd ji znovu nespousti (luxos-bar.service RestartPreventExitStatus)
    call luxos_sys.eprint("luxos-bar: needs a Wayland compositor with layer-shell")
    call exit(2)
end
call read_conf()
call apply_css()
# jedno spojeni: protokoly luxos_wl na soketu GDK (udalosti rozesila GDK)
if wl.on_event(on_wl):
    if wl.attach(layer.wl_display()):
        # globaly, pak udalosti vazanych objektu (nazvy vystupu)
        call wl.roundtrip()
        call wl.roundtrip()
    end
end
call update_clock()
call popup.init(ui["dark"], trace)
call status.start(on_status)
call sni.start(trace)
display = layer.default_display()
for monitor in layer.monitors():
    call add_bar(monitor)
end
call glib.signal_connect(display, "monitor-added", on_monitor_added, 1)
call glib.signal_connect(display, "monitor-removed", on_monitor_removed, 1)
call update_app()
call schedule_clock()
call gio.file_monitor(config_dir() + "/appearance.conf", on_conf_changed)
call gio.file_monitor(config_dir() + "/appearance", on_conf_changed)
call trace("ready")
call gtk.main()
