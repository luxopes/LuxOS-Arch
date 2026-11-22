# LuxOS - Ovladaci centrum a Kalendar (luxos-hub) na Waylandu: plocha layer-shell pod tlacitkem listy.
# Lista (luxos-bar) pred spustenim luxos-cc-toggle zapise do $XDG_RUNTIME_DIR/luxos-popup-anchor pocatek
# sveho monitoru, stred tlacitka na nem, cas stisku od kompozitoru a cas zapisu (CLOCK_MONOTONIC v ms).
# Signal hubu nic nenese, proto soubor; plati jen cerstvy. Bez nej (klavesova zkratka, prikaz) vybere
# vystup kompozitor - ten s kurzorem.
#
#   popup.setup(okno, nazev)              pred prvnim zobrazenim: vrstva OVERLAY, klavesnice on demand
#   popup.setup_radius(okno, nazev, r)    totez s vlastnim zaoblenim karty (Ovladaci centrum One UI); kompozitor
#                                         ho cte z nazvu vrstvy, sklo popup.glass ho prevezme
#   popup.place(okno, sirka, zarovnani)   monitor a okraj pred zobrazenim; zarovnani bez zapisu listy
#                                         "right" | "center"; vraci popis pro testy ("anchor 1280 1104")
#   popup.show(okno)                      zobrazit (po place); popup.focus_in(okno) z focus-in-event,
#   popup.focus_out(okno) z focus-out-event -> True = klik jinam, zavrit
#   popup.same_click(ztraceno_ms)         klik v liste, ktery oknu prave vzal fokus (a zavrel ho)?
#   popup.write_anchor(x, y, stred, cas)  lista tesne pred luxos-cc-toggle
#   popup.glass(okno, karta)              karta okna ze skla z tapety jako verze 1.1.1 (luxos_glass.panel, luxos-glass.c):
#                                         vyrez rozostrene tapety pod oknem se zavojem podle barvy textu, kresli ho klient
#                                         (material.strip), takze je pruhledna i bez rozmazani v kompozitoru (pixman, VM);
#                                         poloha okna z popup.place, bez tapety plati material z CSS; zmena tapety
#                                         nebo rezimu (appearance.conf, appearance) sklo hned prekresli
#   popup.paint_glass(cr, karta, vystup, out_w, out_h, x, y)   totez pro okna listy (x, y = roh okna na vystupu)
#   popup.output_for(monitor)             nazev vystupu Waylandu pro monitor GDK (tapeta muze byt pro kazdy vystup)
#   popup.colors(predpona, tmavy)         @define-color predpona_bg/border/border_top/border_bottom/highlight/fg/dim/faint/
#                                         tile/tile_hover/bubble/trough/fill/accent z tokenu (material popup; rozmazani pod nim
#                                         kresli luxwm); popup.card(predpona) = CSS karty skla (okraj, odlesk, lesk)
load env
load luxos_glib, glib as glib
load gio
load luxos_gtk, gtk as gtk
load cairo
load luxos_layer as layer
load luxos_wl as wl
load luxos_text as text
load luxos_tokens as tokens
load luxos_material as material

ANCHOR = "luxos-popup-anchor"
WALLGLASS = "lx-wallglass"
FRESH_MS = 2000
GAP = 6
EDGE = 8

function runtime_file(name):
    dir = env.get("XDG_RUNTIME_DIR", "")
    if dir == None or dir == "":
        dir = "/tmp"
    end
    return dir + "/" + name
end

function anchor_path():
    return runtime_file(ANCHOR)
end

function write_anchor(x, y, center, pressed):
    line = String(x) + " " + String(y) + " " + String(center) + " " + String(pressed & 0xffffffff) + " " + String(glib.monotonic_time() // 1000)
    safe:
        call glib.write_atomic(anchor_path(), line + "\n")
    end
    return 0
end

# [x, y, stred, stisk] z cerstveho zapisu listy, jinak None
function anchor_values():
    values = []
    for word in glib.read_text(anchor_path()).strip().split(" "):
        number = text.to_int(word, None)
        if number == None:
            return None
        end
        values.append(number)
    end
    if len(values) != 5:
        return None
    end
    age = glib.monotonic_time() // 1000 - values[4]
    if age < 0 or age > FRESH_MS:
        return None
    end
    return values
end

# Stisk tlacitka v liste byl drive nez ztrata fokusu okna = tentyz klik (cas udalosti je CLOCK_MONOTONIC
# v ms, wlroots); dalsi klik prijde az po ni
function same_click(lost):
    values = anchor_values()
    return lost > 0 and values != None and values[3] <= (lost & 0xffffffff) + 2
end

# [monitor, sirka monitoru, stred tlacitka] z cerstveho zapisu listy, jinak None
function read_anchor():
    values = anchor_values()
    if values == None:
        return None
    end
    for monitor in layer.monitors():
        geo = layer.monitor_geometry(monitor)
        if geo[0] == values[0] and geo[1] == values[1]:
            return [monitor, geo[2], values[2]]
        end
    end
    return None
end

# Nazev vystupu Waylandu (HEADLESS-1, eDP-1) pro monitor GDK podle polohy z wlr-output-management (wl_output
# polohu neposila, xdg-output knihovna nema)
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

# ---- sklo z tapety pod kartou ------------------------------------------------------------------

# okno -> {"box", "monitor", "align" ("left" | "right" | "center"), "x"}
glassy = {}

function scale_of(widget):
    unsafe:
        return max(1, __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_scale_factor"), __lsl_unbox_int(widget))))
    end
end

# Svetle sklo pod tmavym textem (jako luxos_glass.on_panel_draw: jas barvy textu karty)
function dark_text(box):
    fg = gtk.widget_get_color(box, 0)
    return 0.2126 * fg[0] + 0.7152 * fg[1] + 0.0722 * fg[2] <= 0.5
end

# Karta ze skla do cr pod obsah okna; False = neni tapeta (plati material z CSS)
function paint_glass(cr, box, output, out_w, out_h, x, y):
    return paint_glass_radius(cr, box, output, out_w, out_h, x, y, tokens.radius_of("popup"))
end

function paint_glass_radius(cr, box, output, out_w, out_h, x, y, radius):
    a = gtk.widget_get_allocation(box)
    ink = 0
    if dark_text(box):
        ink = 1
    end
    hit = material.strip(output, out_w, out_h, x + a[0], y + a[1], a[2], a[3], radius, ink, scale_of(box))
    call gtk.widget_set_class(box, WALLGLASS, hit != None)
    if hit == None:
        return False
    end
    call cairo.set_source_surface(cr, hit[0], Float(a[0]), Float(a[1]))
    call cairo.paint(cr)
    return True
end

function glass(win, box):
    glassy[win] = {"box": box, "monitor": None, "align": "right", "x": 0, "radius": radii.get(win, tokens.radius_of("popup"))}
    call gtk.connect_data(win, "draw", 1, on_glass_draw, win)
    call watch_wallpaper()
    return 0
end

# luxos-appearance pri prepnuti rezimu prepise WALLPAPER v appearance.conf; material si soubor pamatuje,
# takze bez zahozeni by karta zustala ze skla stare tapety (hnede sklo nad modrou tmavou tapetou)
watch = {"on": False, "pending": 0}

function watch_wallpaper():
    if watch["on"]:
        return 0
    end
    watch["on"] = True
    dir = glib.user_config_dir() + "/luxos"
    safe:
        call gio.file_monitor(dir + "/appearance.conf", on_appearance_changed)
        call gio.file_monitor(dir + "/appearance", on_appearance_changed)
    end
    return 0
end

function on_appearance_changed(path, event, other):
    # G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT 1, DELETED 2, CREATED 3, RENAMED 8, MOVED_IN 9
    if event != 1 and event != 2 and event != 3 and event != 8 and event != 9:
        return 0
    end
    # rezim a tapeta se zapisuji tesne po sobe: jedno prekresleni
    if watch["pending"] == 0:
        watch["pending"] = glib.timeout_add_data(20, on_wallpaper_changed, 0)
    end
    return 0
end

function on_wallpaper_changed(unused):
    watch["pending"] = 0
    call material.reload()
    for win in glassy.keys():
        call gtk.widget_queue_draw(win)
    end
    return False
end

# Monitor GDK, na kterem okno je (0 = zatim nevi)
function window_monitor(win):
    unsafe:
        window = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), __lsl_unbox_int(win))
        if window == 0:
            return 0
        end
        return __lsl_qbe_call2(__lsl_symbol("gdk_display_get_monitor_at_window"), __lsl_qbe_call1(__lsl_symbol("gdk_window_get_display"), window), window)
    end
end

function on_glass_draw(win, cr, widget):
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.restore(cr)
    info = glassy.get(win)
    if info == None or info["monitor"] == None:
        return False
    end
    # bez zapisu listy (klavesova zkratka) vybral vystup kompozitor: monitor 0 neni GdkMonitor
    monitor = info["monitor"]
    if monitor == 0:
        monitor = window_monitor(win)
        if monitor == 0:
            return False
        end
    end
    geo = layer.monitor_geometry(monitor)
    w = gtk.widget_get_allocated_width(win)
    x = info["x"]
    if info["align"] == "right":
        x = geo[2] - w - EDGE
    elif info["align"] == "center":
        x = (geo[2] - w) // 2
    end
    # pod vyhradnou zonou listy
    call paint_glass_radius(cr, info["box"], output_for(monitor), geo[2], geo[3], x, tokens.BAR["height"] + GAP, info["radius"])
    return False
end

function glass_place(win, monitor, align, x):
    info = glassy.get(win)
    if info != None:
        info["monitor"] = monitor
        info["align"] = align
        info["x"] = x
    end
    return 0
end

# okno -> zaobleni karty, kdyz neni jako ostatni vyskakovaci okna
radii = {}

function setup(win, name):
    return setup_radius(win, name, tokens.radius_of("popup"))
end

function setup_radius(win, name, radius):
    radii[win] = radius
    call layer.init_for_window(win)
    call layer.set_namespace(win, name + "@popup:" + String(radius))
    call layer.set_layer(win, layer.LAYER_OVERLAY)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_ON_DEMAND)
    call layer.set_margin(win, layer.EDGE_TOP, GAP)
    return 0
end

# Klavesnice on demand: luxwm ji vrstve nad okny da hned po zobrazeni (Esc), klik jinam (okno, plocha) ji
# vezme a tim okno zavre. Ztrata fokusu se pocita, jen kdyz ho okno melo.
focused = {}

function colors(prefix, dark):
    # okraj karty skla jako vyskakovaci okna listy (tokens .lx-popup)
    values = {"bg": tokens.material("popup", dark, material.compositor_blur()), "border": tokens.COLORS["card_edge"],
              "border_top": tokens.COLORS["card_edge_top"], "border_bottom": tokens.COLORS["card_edge_bottom"],
              "highlight": tokens.COLORS["card_inset"], "fg": tokens.color("fg", dark), "dim": tokens.color("fg_secondary", dark),
              "faint": tokens.with_alpha(tokens.color("fg", dark), 0.28), "tile": tokens.color("tile", dark),
              "tile_hover": tokens.color("tile_hover", dark), "bubble": tokens.color("bubble", dark),
              "trough": tokens.color("trough", dark), "fill": tokens.color("fill", dark), "accent": tokens.COLORS["accent"]}
    out = ""
    for name in sorted(values.keys()):
        out = out + "@define-color " + prefix + "_" + name + " " + tokens.css_color(values[name]) + ";\n"
    end
    return out
end

function card(prefix):
    return ("border: 1px solid @" + prefix + "_border; border-top-color: @" + prefix + "_border_top; border-bottom-color: @" + prefix
        + "_border_bottom; box-shadow: inset 0 1px @" + prefix + "_highlight; background-image: " + tokens.SHEEN + ";")
end

function show(win):
    focused[win] = False
    call gtk.widget_show(win)
    return 0
end

function focus_in(win):
    focused[win] = True
    return 0
end

# Vzal oknu fokus klik jinam (zavrit)?
function focus_out(win):
    had = focused.get(win, False)
    focused[win] = False
    return had
end

function place(win, width, align):
    hit = read_anchor()
    if hit != None:
        geo = layer.monitor_geometry(hit[0])
        x = max(EDGE, min(hit[2] - width // 2, hit[1] - width - EDGE))
        call layer.set_monitor(win, hit[0])
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_LEFT])
        call layer.set_margin(win, layer.EDGE_LEFT, x)
        call glass_place(win, hit[0], "left", x)
        return "anchor " + String(geo[0]) + " " + String(geo[0] + x)
    end
    call layer.set_monitor(win, 0)
    # vystup vybere kompozitor; sklo z tapety prvniho monitoru (monitor 0 by GDK shodil v monitor_geometry)
    monitors = layer.monitors()
    call glass_place(win, monitors[0] if len(monitors) > 0 else None, align, 0)
    if align == "center":
        call layer.set_anchors(win, [layer.EDGE_TOP])
    else:
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_RIGHT])
        call layer.set_margin(win, layer.EDGE_RIGHT, EDGE)
    end
    return "default " + align
end
