# LuxOS - Ovladaci centrum a Kalendar (luxos-hub) na Waylandu: plocha layer-shell pod tlacitkem listy.
# Lista (luxos-bar) pred spustenim luxos-cc-toggle zapise do $XDG_RUNTIME_DIR/luxos-popup-anchor pocatek
# sveho monitoru, stred tlacitka na nem, cas stisku od kompozitoru a cas zapisu (CLOCK_MONOTONIC v ms).
# Signal hubu nic nenese, proto soubor; plati jen cerstvy. Bez nej (klavesova zkratka, prikaz) vybere
# vystup kompozitor - ten s kurzorem.
#
#   popup.setup(okno, nazev)              pred prvnim zobrazenim: vrstva TOP
#   popup.place(okno, sirka, zarovnani)   monitor a okraj pred zobrazenim; zarovnani bez zapisu listy
#                                         "right" | "center"; vraci popis pro testy ("anchor 1280 1104")
#   popup.show(okno)                      zobrazit (po place); popup.focus_in(okno) z focus-in-event,
#   popup.focus_out(okno) z focus-out-event -> True = klik jinam, zavrit
#   popup.same_click(ztraceno_ms)         klik v liste, ktery oknu prave vzal fokus (a zavrel ho)?
#   popup.write_anchor(x, y, stred, cas)  lista tesne pred luxos-cc-toggle
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_layer as layer
load luxos_text as text

ANCHOR = "luxos-popup-anchor"
FRESH_MS = 2000
GAP = 6
EDGE = 8

function anchor_path():
    dir = env.get("XDG_RUNTIME_DIR", "")
    if dir == None or dir == "":
        dir = "/tmp"
    end
    return dir + "/" + ANCHOR
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

function setup(win, name):
    call layer.init_for_window(win)
    call layer.set_namespace(win, name)
    # TOP, ne OVERLAY: luxwm (jako sway) rozklada OVERLAY pred listou ve vrstve TOP, okno by ji prekrylo
    call layer.set_layer(win, layer.LAYER_TOP)
    call layer.set_margin(win, layer.EDGE_TOP, GAP)
    return 0
end

# Klavesnice: on demand, aby klik jinam (okno, plocha) oknu vzal fokus a tim ho zavrel. Po zobrazeni ji ale
# kompozitor nemusi dat (luxwm on demand plose fokus na mapovani neda, labwc ne, kdyz ma fokus okno), pak by
# nesel Esc: na chvili exclusive (fokus hned) a po jeho prijeti zpet on demand. luxwm fokus vrstve necha,
# labwc ho pri te zmene vrati oknu - takova ztrata fokusu neni klik jinam.
state = {}

function show(win):
    state[win] = {"focused": False, "released": 0}
    call layer.set_keyboard_mode(win, layer.KEYBOARD_ON_DEMAND)
    call gtk.widget_show(win)
    call glib.timeout_add_data(150, grab_if_unfocused, win)
    return 0
end

function grab_if_unfocused(win):
    if gtk.widget_get_visible(win) and not state[win]["focused"]:
        call layer.set_keyboard_mode(win, layer.KEYBOARD_EXCLUSIVE)
    end
    return False
end

function focus_in(win):
    state[win]["focused"] = True
    if layer.get_keyboard_mode(win) == layer.KEYBOARD_EXCLUSIVE:
        # zmena primo v obsluze fokusu by se v labwc potkala s prvnim snimkem (plocha zustala neviditelna)
        call glib.timeout_add_data(100, release_keyboard, win)
    end
    return 0
end

function release_keyboard(win):
    call layer.set_keyboard_mode(win, layer.KEYBOARD_ON_DEMAND)
    state[win]["released"] = glib.monotonic_time() // 1000
    return False
end

# Vzal oknu fokus klik jinam (zavrit)? Ne, kdyz fokus nemelo nebo ho kompozitor vratil pri zmene klavesnice.
function focus_out(win):
    s = state.get(win)
    if s == None or not s["focused"]:
        return False
    end
    s["focused"] = False
    return glib.monotonic_time() // 1000 - s["released"] > 150
end

function place(win, width, align):
    hit = read_anchor()
    if hit != None:
        geo = layer.monitor_geometry(hit[0])
        x = max(EDGE, min(hit[2] - width // 2, hit[1] - width - EDGE))
        call layer.set_monitor(win, hit[0])
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_LEFT])
        call layer.set_margin(win, layer.EDGE_LEFT, x)
        return "anchor " + String(geo[0]) + " " + String(geo[0] + x)
    end
    call layer.set_monitor(win, 0)
    if align == "center":
        call layer.set_anchors(win, [layer.EDGE_TOP])
    else:
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_RIGHT])
        call layer.set_margin(win, layer.EDGE_RIGHT, EDGE)
    end
    return "default " + align
end
