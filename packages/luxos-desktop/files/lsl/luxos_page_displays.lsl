# LuxOS - Nastaveni > Monitory (drive luxos-displays-settings; /usr/lib/luxos/luxos-displays-settings
# a /usr/bin/luxos-display-settings jsou odkazy na luxos-settings): usporadani pretazenim (prichyceni k hrane,
# bez mezer a prekryvu), hlavni monitor (bila lista: Dock, oznameni a okna z odpojenych monitoru), zrcadleni,
# rezim vice monitoru, rozliseni, frekvence, meritko vcetne zlomkoveho a otoceni. Kazda zmena se hned pouzije
# a do 15 s se musi potvrdit, jinak se vrati puvodni. Na X11 (xrandr) bez meritka, navic velikost textu
# (Xft/DPI v xsettings), rezim vice monitoru se pouzije hned skriptem luxos-displays (jako Super+P).
#
# Stranka sama monitory nemeni (na Waylandu nema pravo na wlr-output-management): stav cte z `luxos-displays get`
# a zmenu posila `luxos-displays try JSON`. Casovac vraceni bezi v pomocniku, takze se puvodni nastaveni vrati
# i kdyz okno spadne. Potvrzeni = SIGUSR1 pomocniku, vratit hned = SIGUSR2 (i pri odchodu ze stranky).
#
#   luxos-displays-settings --menu   rychla volba rezimu (Super+P): ctyri volby nad vsemi okny (layer-shell)
# Testy: page-state, select NAZEV [JSON], drag NAZEV DX DY [bar] [hold], text N, mirror 0|1, close, drawcheck TEXT.
load env, json, math
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_i18n as i18n
load luxos_luxwm as wm
load luxos_layer as layer
load luxos_primary as primary
load luxos_displays as dw
load luxos_xrandr as xr
load luxos_sys as lsys
load luxos_settings_ui as ui

HELPER = "/usr/lib/luxos/luxos-displays"
SCRIPT = "luxos-displays"
CSS = ".displays-error { color: #c0392b; }\n.displays-big-a { font-size: 18px; font-weight: 600; }\n.displays-small-a { font-size: 11px; font-weight: 600; }\n.text-size-value { font-size: 12px; font-weight: 600; opacity: 0.8; }\n"
MENU_CSS = ".osd { border-radius: 18px; padding: 18px; background-color: alpha(@theme_bg_color, 0.96); border: 1px solid alpha(currentColor, 0.15); }\n.osd-title { font-weight: 700; font-size: 15px; margin-bottom: 12px; }\n.osd button { border-radius: 12px; padding: 12px; min-width: 132px; }\n.osd button.current { background-image: none; background-color: alpha(@theme_selected_bg_color, 0.25); }\n.osd-label { font-size: 12px; }\n.osd label, .osd image { color: @theme_fg_color; }\n"
PAD = 18
SNAP_PX = 10
ROTATIONS = [[0, "Standard"], [1, "90°"], [2, "180°"], [3, "270°"]]
TEXT_LABELS = ["Smaller", "Default", "Large", "Larger", "Largest"]

D = {"window": 0, "outer": 0, "page": 0, "css": 0, "building": False, "busy": False, "data": None, "config": {},
     "primary": "", "mode": "extend", "widgets": {}, "area": 0, "drag": None, "view": None, "pid": 0,
     "output": "", "dialog": 0, "countdown": 0, "left": 0, "tick": 0, "message": "", "refresh": 0,
     "x11": False, "named": {}, "text_scale": 0, "text_value": 0, "text_timer": 0, "switch": 0, "wm": False}

function helper():
    value = env.get("LUXOS_DISPLAYS_HELPER", "")
    if value == "":
        return HELPER
    end
    return value
end

function seconds():
    value = 15
    safe:
        value = max(2, min(60, Int(env.get("LUXOS_DISPLAYS_CONFIRM_SECONDS", "15"))))
    end
    return value
end

function outputs():
    if D["data"] == None:
        return []
    end
    return D["data"]["outputs"]
end

function output(name):
    for o in outputs():
        if o["name"] == name:
            return o
        end
    end
    return None
end

function display_name(o):
    if o["internal"]:
        return i18n.T("Built-in Display")
    end
    model = dw.identity(o["name"], o["description"])
    if model == "":
        return o["name"]
    end
    same = 0
    for other in outputs():
        if dw.identity(other["name"], other["description"]) == model:
            same += 1
        end
    end
    if same > 1:
        return model + " (" + o["name"] + ")"
    end
    return model
end

# Kopie konfigurace (zmena se posila cela)
function config_copy():
    result = {}
    for name in D["config"].keys():
        result[name] = D["config"][name].copy()
    end
    return result
end

function rects():
    result = {}
    for name in D["config"].keys():
        c = D["config"][name]
        if c["enabled"]:
            s = dw.config_size(c)
            result[name] = [c["x"], c["y"], s[0], s[1]]
        end
    end
    return result
end

function mirrored():
    return dw.mirrored(rects().values())
end

# ---- stavebni prvky ----------------------------------------------------------------------------------

function hint(text):
    l = ui.label(text, "hint")
    call gtk.label_set_max_width_chars(l, 56)
    return l
end

# Rozbalovaci seznam: items = [[hodnota, text]..]; f(hodnota, data) po zmene uzivatelem; name pro testy
function named_combo(name, items, current, f, data):
    c = combo(items, current, f, data)
    D["named"][name] = c
    return c
end

function combo(items, current, f, data):
    c = gtk.combo_box_text_new()
    active = -1
    for i in range(len(items)):
        call gtk.combo_box_text_append(c, String(i), items[i][1])
        if items[i][0] == current:
            active = i
        end
    end
    if active >= 0:
        call gtk.combo_box_set_active(c, active)
    end
    D["widgets"][c] = {"items": items, "f": f, "data": data}
    call gtk.connect(c, "changed", on_combo)
    return c
end

function on_combo(c):
    if D["building"] or c not in D["widgets"]:
        return 0
    end
    w = D["widgets"][c]
    i = gtk.combo_box_get_active(c)
    if i >= 0 and i < len(w["items"]):
        call w["f"](w["items"][i][0], w["data"])
    end
    return 0
end

function rate_text(mhz):
    if mhz % 1000 == 0:
        return String(mhz // 1000) + " Hz"
    end
    return String(mhz // 1000) + "." + String(mhz % 1000 // 10 + 100)[1:] + " Hz"
end

# ---- obsah stranky -------------------------------------------------------------------------------------

function fill():
    D["building"] = True
    D["widgets"] = {}
    D["named"] = {}
    D["area"] = 0
    D["switch"] = 0
    D["text_scale"] = 0
    if D["page"] != 0:
        call gtk.widget_destroy(D["page"])
    end
    page = ui.page_box()
    D["page"] = page
    call gtk.box_pack_start(D["outer"], page, True, True, 0)
    outs = outputs()
    if len(outs) == 0:
        text = i18n.T("No displays found. Display settings need a Wayland session with LuxOS.")
        if D["x11"]:
            text = i18n.T("No displays found. Display settings need an X11 session.")
        end
        call gtk.box_pack_start(page, hint(text), False, False, 24)
    elif len(outs) > 1:
        call build_arrangement(page)
        g = ui.group(page, i18n.T("Multiple Displays"))
        modes = [["extend", i18n.T("Extend - use both screens")], ["mirror", i18n.T("Mirror - same picture on both")],
                 ["external", i18n.T("Only external screen")], ["internal", i18n.T("Only this computer's screen")]]
        call ui.row(g, i18n.T("Use as"), i18n.T("You can also switch with Super+P."), named_combo("mode", modes, D["mode"], on_mode, None))
    else:
        call build_arrangement(page)
    end
    if D["message"] != "":
        call gtk.box_pack_start(page, ui.label(D["message"], "displays-error"), False, False, 8)
    end
    for o in outs:
        if D["x11"]:
            call build_output_x11(page, o)
        else:
            call build_output(page, o)
        end
    end
    if D["x11"]:
        call build_text_size(page)
    end
    call gtk.widget_show_all(page)
    if D["busy"]:
        call gtk.widget_set_sensitive(page, False)
    end
    D["building"] = False
    return 0
end

function build_arrangement(page):
    outs = outputs()
    g = ui.group(page, i18n.T("Arrangement"))
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, -1, 190)
    call gtk.widget_set_margins(area, 10, 10, 6, 0)
    call gtk.widget_add_events(area, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    call gtk.connect(area, "draw", on_draw)
    call gtk.connect(area, "button-press-event", on_press)
    call gtk.connect(area, "motion-notify-event", on_motion)
    call gtk.connect(area, "button-release-event", on_release)
    D["area"] = area
    call gtk.box_pack_start(g["box"], area, False, False, 0)
    g["rows"] = 1
    if len(outs) < 2:
        return 0
    end
    text = i18n.T("Drag the displays to arrange them. Drag the white bar to another display to move the menu bar and Dock there.")
    if mirrored():
        text = i18n.T("The displays show the same picture. Turn off mirroring to arrange them.")
    elif len(rects()) < 2:
        text = i18n.T("Only one display is in use. Choose Extend under Multiple Displays to arrange them.")
    end
    note = hint(text)
    call gtk.widget_set_margins(note, 16, 16, 0, 8)
    call gtk.box_pack_start(g["box"], note, False, False, 0)
    items = []
    for o in outs:
        if D["config"][o["name"]]["enabled"]:
            items.append([o["name"], display_name(o)])
        end
    end
    main = named_combo("main", items, D["primary"], on_main, None)
    call gtk.widget_set_sensitive(main, len(items) > 1 and not (D["x11"] and mirrored()))
    call ui.row(g, i18n.T("Main display"), i18n.T("The menu bar and Dock appear on the main display."), main)
    sw = gtk.switch_new()
    D["switch"] = sw
    call gtk.switch_set_active(sw, mirrored())
    call gtk.connect(sw, "state-set", on_mirror)
    call ui.row(g, i18n.T("Mirror displays"), i18n.T("Show the same picture on all displays."), sw)
    return 0
end

function build_output(page, o):
    g = ui.group(page, display_name(o))
    c = D["config"][o["name"]]
    if not c["enabled"]:
        call ui.row(g, i18n.T("This display is turned off."), i18n.T("Turn it on with Super+P or under Multiple Displays."), 0)
        return 0
    end
    pref = o["preferred"]
    items = []
    for size in dw.resolutions(o):
        text = String(size[0]) + " × " + String(size[1])
        if size[0] == pref[0] and size[1] == pref[1]:
            text = i18n.TF("%s (Recommended)", [text])
        end
        items.append([size, text])
    end
    if [c["width"], c["height"]] not in [i[0] for i in items]:
        items.insert(0, [[c["width"], c["height"]], String(c["width"]) + " × " + String(c["height"])])
    end
    call ui.row(g, i18n.T("Resolution"), i18n.T("A lower resolution makes everything larger; the recommended one is the sharpest."),
                named_combo("res:" + o["name"], items, [c["width"], c["height"]], on_resolution, o["name"]))
    rates = dw.refreshes(o, c["width"], c["height"])
    if len(rates) > 0 and rates[len(rates) - 1] > 0:
        items = []
        for r in rates:
            items.insert(0, [r, rate_text(r)])
        end
        call ui.row(g, i18n.T("Refresh rate"), "", named_combo("rate:" + o["name"], items, c["refresh"], on_refresh, o["name"]))
    end
    items = []
    for s in dw.SCALES:
        items.append([s, String(s // 10) + " %"])
    end
    if c["scale"] not in dw.SCALES:
        items.append([c["scale"], String(c["scale"] // 10) + " %"])
    end
    call ui.row(g, i18n.T("Scale"), i18n.T("Makes text, windows and the menu bar larger on this display. 125-175 % suits sharp laptop screens."),
                named_combo("scale:" + o["name"], items, c["scale"], on_scale, o["name"]))
    items = []
    for r in ROTATIONS:
        items.append([r[0], i18n.T(r[1])])
    end
    call ui.row(g, i18n.T("Rotation"), "", named_combo("rot:" + o["name"], items, c["transform"], on_rotation, o["name"]))
    return 0
end

# X11: rezimy xrandr podle nazvu (prokladane jen aktualni), frekvence jak je pise xrandr, otoceni, ktera vystup umi
function build_output_x11(page, o):
    g = ui.group(page, display_name(o))
    if not o["enabled"]:
        call ui.row(g, i18n.T("This display is turned off."), i18n.T("Turn it on with Super+P or under Multiple Displays."), 0)
        return 0
    end
    items = []
    for c in o["choices"]:
        items.append([c[0], i18n.TF("%s (Recommended)", [c[1]]) if c[2] else c[1]])
    end
    call ui.row(g, i18n.T("Resolution"), i18n.T("A lower resolution makes everything larger; the recommended one is the sharpest."),
                named_combo("res:" + o["name"], items, o["current"], on_x11_resolution, o["name"]))
    if len(o["rates"]) > 0:
        call ui.row(g, i18n.T("Refresh rate"), "", named_combo("rate:" + o["name"], o["rates"], o["rate"], on_x11_rate, o["name"]))
    end
    items = [[r[0], i18n.T(r[1])] for r in o["rotations"]]
    call ui.row(g, i18n.T("Rotation"), "", named_combo("rot:" + o["name"], items, o["rotation"], on_x11_rotation, o["name"]))
    return 0
end

function on_x11_resolution(mode, name):
    o = output(name)
    call try_request({"output": name, "mode": mode, "rate": None, "rotate": o["rotation"]})
end

function on_x11_rate(rate, name):
    o = output(name)
    call try_request({"output": name, "mode": o["current"], "rate": rate, "rotate": o["rotation"]})
end

function on_x11_rotation(rotation, name):
    o = output(name)
    call try_request({"output": name, "mode": o["current"], "rate": o["rate"], "rotate": rotation})
end

# Velikost textu (Xft/DPI v xsettings; xfsettingsd ji hned rozesle vsem aplikacim)
function build_text_size(page):
    g = ui.group(page, i18n.T("Text Size"))
    scale = gtk.scale_new_with_range(gtk.HORIZONTAL, 0, len(xr.TEXT_SIZES) - 1, 1)
    call gtk.scale_set_draw_value(scale, False)
    call gtk.widget_set_hexpand(scale, True)
    # znacky bez popisku: GTK krajni popisky posouva dovnitr, vybranou velikost ukazuje popisek pod posuvnikem
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_range_set_round_digits"), glib.ptr(scale), 0)
        for i in range(len(TEXT_LABELS)):
            call __lsl_qbe_call4(__lsl_symbol("gtk_scale_add_mark"), glib.ptr(scale), Float(i), 3, 0)
        end
    end
    value = 1
    if type(D["data"].get("text_size")) == "Int":
        value = D["data"]["text_size"]
    end
    call gtk.range_set_value(scale, Float(value))
    D["text_scale"] = scale
    D["text_value"] = gtk.label_new("")
    call gtk.widget_add_class(D["text_value"], "text-size-value")
    call gtk.widget_set_margins(D["text_value"], 0, 0, 0, 2)
    box = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_margins(box, 16, 16, 10, 0)
    small = gtk.label_new("A")
    call gtk.widget_add_class(small, "displays-small-a")
    big = gtk.label_new("A")
    call gtk.widget_add_class(big, "displays-big-a")
    call gtk.box_pack_start(box, small, False, False, 0)
    call gtk.box_pack_start(box, scale, True, True, 0)
    call gtk.box_pack_start(box, big, False, False, 0)
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    call gtk.box_pack_start(g["box"], D["text_value"], False, False, 0)
    call show_text_value()
    note = hint(i18n.T("Changes the size of text in the menu bar, window titles and apps. Some apps need to be reopened."))
    call gtk.widget_set_margins(note, 16, 16, 0, 10)
    call gtk.box_pack_start(g["box"], note, False, False, 0)
    call gtk.connect(scale, "value-changed", on_text_size)
    return 0
end

function text_index():
    return max(0, min(len(TEXT_LABELS) - 1, math.round(gtk.range_get_value(D["text_scale"]))))
end

function show_text_value():
    call gtk.label_set_text(D["text_value"], i18n.T(TEXT_LABELS[text_index()]))
end

function on_text_size(scale):
    call show_text_value()
    if D["building"]:
        return 0
    end
    # zmena DPI prekresli vsechny aplikace - az po kratke pauze
    if D["text_timer"] != 0:
        call glib.source_remove(D["text_timer"])
    end
    D["text_timer"] = glib.timeout_add(350, apply_text_size)
    return 0
end

function apply_text_size():
    D["text_timer"] = 0
    call xr.set_text_size(text_index())
    return False
end

# ---- usporadani (kresleni a tazeni) ----------------------------------------------------------------

function compute_view():
    r = rects()
    if len(r) == 0 or D["area"] == 0:
        return None
    end
    w = gtk.widget_get_allocated_width(D["area"])
    h = gtk.widget_get_allocated_height(D["area"])
    x0 = min([v[0] for v in r.values()])
    y0 = min([v[1] for v in r.values()])
    x1 = max([v[0] + v[2] for v in r.values()])
    y1 = max([v[1] + v[3] for v in r.values()])
    # rezerva kolem, aby se dal monitor pretahnout na kteroukoli stranu
    mw = 0.0
    mh = 0.0
    if len(r) > 1 and not mirrored():
        mw = max([v[2] for v in r.values()]) * 0.6
        mh = max([v[3] for v in r.values()]) * 0.6
    end
    scale = min((w - 2 * PAD) / max(1.0, (x1 - x0) + 2 * mw), (h - 2 * PAD) / max(1.0, (y1 - y0) + 2 * mh))
    return [scale, (w - (x1 - x0) * scale) / 2, (h - (y1 - y0) * scale) / 2, x0, y0]
end

function to_view(r, view):
    return [view[1] + (r[0] - view[3]) * view[0], view[2] + (r[1] - view[4]) * view[0], r[2] * view[0], r[3] * view[0]]
end

function hit(x, y):
    view = D["view"]
    if view == None:
        view = compute_view()
    end
    if view == None:
        return [None, False]
    end
    r = rects()
    names = [D["primary"]] + [n for n in sorted(r.keys()) if n != D["primary"]]
    for name in names:
        if name not in r:
            continue
        end
        v = to_view(r[name], view)
        if x >= v[0] and x <= v[0] + v[2] and y >= v[1] and y <= v[1] + v[3]:
            return [name, name == D["primary"] and y <= v[1] + 16]
        end
    end
    return [None, False]
end

function editable():
    return len(rects()) > 1 and not mirrored() and not D["busy"]
end

function on_press(event, area):
    if gtk.event_button(event) != 1:
        return False
    end
    return press_at(gtk.event_x(event), gtk.event_y(event))
end

function press_at(x, y):
    if not editable():
        return False
    end
    found = hit(x, y)
    if found[0] == None:
        return False
    end
    D["drag"] = {"name": found[0], "bar": found[1], "x0": x, "y0": y,
                 "view": D["view"] if D["view"] != None else compute_view(), "dx": 0.0, "dy": 0.0}
    return True
end

function on_motion(event, area):
    if D["drag"] == None:
        if editable():
            name = hit(gtk.event_x(event), gtk.event_y(event))[0]
            call gtk.widget_set_cursor(area, "grab" if name != None else "")
        end
        return False
    end
    return motion_at(gtk.event_x(event), gtk.event_y(event))
end

function motion_at(x, y):
    d = D["drag"]
    d["dx"] = x - d["x0"]
    d["dy"] = y - d["y0"]
    call gtk.widget_queue_draw(D["area"])
    return True
end

# Kam monitor po pusteni dopadne: {nazev: [x, y]}
function proposal(d):
    r = rects()
    v = r[d["name"]]
    px = math.round(v[0] + d["dx"] / d["view"][0])
    py = math.round(v[1] + d["dy"] / d["view"][0])
    return dw.drop(r, d["name"], px, py, D["primary"], math.round(SNAP_PX / d["view"][0]))
end

function on_release(event, area):
    if D["drag"] == None or gtk.event_button(event) != 1:
        return False
    end
    return release_at(gtk.event_x(event), gtk.event_y(event))
end

function release_at(x, y):
    d = D["drag"]
    D["drag"] = None
    call gtk.widget_queue_draw(D["area"])
    if abs(d["dx"]) <= 3 and abs(d["dy"]) <= 3:
        return True
    end
    if d["bar"]:
        # lista pretazena na jiny monitor = novy hlavni monitor
        r = rects()
        for name in r.keys():
            v = to_view(r[name], d["view"])
            if name != D["primary"] and x >= v[0] and x <= v[0] + v[2] and y >= v[1] and y <= v[1] + v[3]:
                call try_config(config_copy(), name, False)
            end
        end
        return True
    end
    pos = proposal(d)
    r = rects()
    current = {}
    for name in r.keys():
        current[name] = [r[name][0], r[name][1]]
    end
    if pos != dw.normalize(current):
        config = config_copy()
        for name in pos.keys():
            config[name]["x"] = pos[name][0]
            config[name]["y"] = pos[name][1]
        end
        # hned ukazat novy stav (do potvrzeni nebo vraceni)
        D["config"] = config
        call try_config(config, D["primary"], False)
    end
    return True
end

function ellipsize(cr, text, width):
    if cairo.text_extents(cr, text)[4] <= width:
        return text
    end
    while len(text) > 0 and cairo.text_extents(cr, text + "…")[4] > width:
        text = text[:len(text) - 1]
    end
    if len(text) == 0:
        return ""
    end
    return text + "…"
end

function draw_display(cr, v, text, primary, fg, alpha, outline):
    call cairo.rounded_rectangle(cr, v[0] + 2, v[1] + 2, max(1.0, v[2] - 4), max(1.0, v[3] - 4), 7)
    if outline:
        call cairo.set_source_rgba(cr, 0.24, 0.48, 1.0, 0.9)
        call cairo.set_dash(cr, [5, 4], 0)
        call cairo.set_line_width(cr, 2)
        call cairo.stroke(cr)
        call cairo.set_dash(cr, [], 0)
        return 0
    end
    call cairo.set_source_rgba(cr, 0.24, 0.48, 1.0, alpha)
    call cairo.fill_preserve(cr)
    call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.35)
    call cairo.set_line_width(cr, 1)
    call cairo.stroke(cr)
    if primary:
        # horni lista na hlavnim monitoru
        call cairo.set_source_rgba(cr, 1, 1, 1, 0.85)
        call cairo.rounded_rectangle(cr, v[0] + 6, v[1] + 6, max(4.0, v[2] - 12), 5, 2)
        call cairo.fill(cr)
    end
    call cairo.set_source_rgba(cr, 1, 1, 1, alpha)
    call cairo.select_font_face(cr, "Inter", 0, 1)
    call cairo.set_font_size(cr, 12)
    text = ellipsize(cr, text, max(0.0, v[2] - 12))
    ext = cairo.text_extents(cr, text)
    call cairo.move_to(cr, v[0] + (v[2] - ext[4]) / 2, v[1] + v[3] / 2 + 4)
    call cairo.show_text(cr, text)
    return 0
end

function on_draw(cr, area):
    r = rects()
    if len(r) == 0:
        return False
    end
    d = D["drag"]
    view = d["view"] if d != None else compute_view()
    D["view"] = view
    fg = gtk.widget_get_color(area, 0)
    if mirrored():
        names = [display_name(output(n)) for n in sorted(r.keys())]
        call draw_display(cr, to_view(r.values()[0], view), " = ".join(names), True, fg, 1.0, False)
        return False
    end
    moving = d["name"] if d != None and not d["bar"] else None
    for name in [n for n in sorted(r.keys()) if n != moving] + ([moving] if moving != None else []):
        v = to_view(r[name], view)
        text = display_name(output(name))
        if name == moving:
            pos = proposal(d)
            ref = dw.drop_anchor(r, name, D["primary"])
            sx = r[ref][0] - pos[ref][0]
            sy = r[ref][1] - pos[ref][1]
            call draw_display(cr, to_view([pos[name][0] + sx, pos[name][1] + sy, r[name][2], r[name][3]], view), "", False, fg, 1.0, True)
            call draw_display(cr, [v[0] + d["dx"], v[1] + d["dy"], v[2], v[3]], text, name == D["primary"], fg, 0.8, False)
            continue
        end
        call draw_display(cr, v, text, name == D["primary"] and not (d != None and d["bar"]), fg, 1.0, False)
    end
    if d != None and d["bar"] and D["primary"] in r:
        v = to_view(r[D["primary"]], view)
        call cairo.set_source_rgba(cr, 1, 1, 1, 0.9)
        call cairo.rounded_rectangle(cr, v[0] + 6 + d["dx"], v[1] + 6 + d["dy"], max(4.0, v[2] - 12), 5, 2)
        call cairo.fill(cr)
    end
    return False
end

# ---- zmeny -------------------------------------------------------------------------------------------

function on_main(name, data):
    call try_config(config_copy(), name, False)
end

function on_mirror(state, sw):
    if D["building"]:
        return False
    end
    if D["x11"]:
        # X11: zrcadleni je soucast rozlozeni sady (vypnuti vrati ulozene polohy)
        call try_request({"mirror": state != 0, "primary": D["primary"]})
    elif state != 0:
        call try_request({"mode": "mirror"})
    else:
        call try_request({"mode": "extend"})
    end
    return False
end

function on_mode(mode, data):
    if not D["x11"]:
        call try_request({"mode": mode})
        return 0
    end
    # X11: rezim hned skriptem luxos-displays (jako Super+P), bez potvrzovani
    if D["busy"]:
        return 0
    end
    D["busy"] = True
    call gtk.widget_set_sensitive(D["page"], False)
    if glib.spawn_capture([SCRIPT, mode], on_mode_done, None) == 0:
        call on_mode_done(None, "", 1)
    end
    return 0
end

function on_mode_done(data, text, status):
    D["busy"] = False
    call refresh()
    return 0
end

function change(name, field_values):
    config = config_copy()
    config[name].update(field_values)
    call try_config(dw.resettle(config, D["primary"]), D["primary"], mirrored())
end

function on_resolution(size, name):
    o = output(name)
    call change(name, {"width": size[0], "height": size[1], "refresh": dw.best_refresh(o, size[0], size[1])})
end

function on_refresh(rate, name):
    call change(name, {"refresh": rate})
end

function on_scale(scale, name):
    call change(name, {"scale": scale})
end

function on_rotation(transform, name):
    call change(name, {"transform": transform})
end

function try_config(config, primary, mirror):
    call try_request({"config": config, "primary": primary, "mirror": mirror})
end

# Zkusebni pouziti pres pomocnika; "applied" = zeptat se, konec procesu = obnovit stranku
function try_request(request):
    if D["busy"]:
        return 0
    end
    D["message"] = ""
    D["busy"] = True
    D["output"] = ""
    call gtk.widget_set_sensitive(D["page"], False)
    D["pid"] = glib.spawn_stream([helper(), "try", "-s", String(seconds()), json.encode(request)], on_try_output, None)
    if D["pid"] == 0:
        D["busy"] = False
        D["message"] = i18n.T("The display could not use this setting.")
        call refresh()
    end
    return 0
end

function on_try_output(data, chunk):
    if chunk == "":
        D["pid"] = 0
        D["busy"] = False
        call close_dialog()
        if D["output"].find("applied") < 0:
            D["message"] = i18n.T("The display could not use this setting.") + " " + i18n.T("The previous settings were restored.")
        end
        call refresh()
        return 0
    end
    D["output"] = D["output"] + chunk
    if chunk.find("applied") >= 0 and D["dialog"] == 0 and D["outer"] != 0:
        call open_dialog()
    end
    return 0
end

# "Ponechat nastaveni?" s odpoctem (odpocet je jen ukazatel, vraceni hlida pomocnik)
function open_dialog():
    dlg = gtk.window_new(i18n.T("Displays"))
    call gtk.window_set_transient_for(dlg, D["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_resizable(dlg, False)
    call gtk.window_set_position(dlg, 4)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_margins(box, 20, 20, 18, 16)
    title = gtk.label_new("")
    call gtk.label_set_markup(title, "<b>" + glib.markup_escape(i18n.T("Keep these display settings?")) + "</b>")
    call gtk.label_set_xalign(title, 0)
    call gtk.box_pack_start(box, title, False, False, 0)
    D["left"] = seconds()
    D["countdown"] = ui.label("", "")
    call gtk.label_set_max_width_chars(D["countdown"], 56)
    call gtk.box_pack_start(box, D["countdown"], False, False, 0)
    buttons = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_END)
    revert = gtk.button_new(i18n.T("Revert"))
    keep = gtk.button_new(i18n.T("Keep Changes"))
    call gtk.widget_add_class(keep, "suggested-action")
    call gtk.connect(revert, "clicked", on_revert_clicked)
    call gtk.connect(keep, "clicked", on_keep_clicked)
    call gtk.box_pack_start(buttons, revert, False, False, 0)
    call gtk.box_pack_start(buttons, keep, False, False, 0)
    call gtk.box_pack_start(box, buttons, False, False, 6)
    call gtk.container_add(dlg, box)
    call gtk.connect(dlg, "delete-event", on_dialog_delete)
    D["dialog"] = dlg
    call update_countdown()
    D["tick"] = glib.timeout_add(1000, on_tick)
    call gtk.widget_show_all(dlg)
    call gtk.widget_grab_focus(revert)
    return 0
end

function update_countdown():
    call gtk.label_set_text(D["countdown"], i18n.TF("The previous settings will be restored in %d seconds.", [max(0, D["left"])]))
end

function on_tick():
    D["left"] = D["left"] - 1
    if D["dialog"] == 0:
        D["tick"] = 0
        return False
    end
    call update_countdown()
    return True
end

function close_dialog():
    if D["tick"] != 0:
        call glib.source_remove(D["tick"])
        D["tick"] = 0
    end
    if D["dialog"] != 0:
        dlg = D["dialog"]
        D["dialog"] = 0
        call gtk.widget_destroy(dlg)
    end
end

function signal_helper(signum):
    if D["pid"] != 0:
        call glib.kill(D["pid"], signum)
    end
end

function on_keep_clicked(button):
    call signal_helper(10)
    call close_dialog()
    return 0
end

function on_revert_clicked(button):
    call signal_helper(12)
    call close_dialog()
    return 0
end

function on_dialog_delete(event, dlg):
    call signal_helper(12)
    D["dialog"] = 0
    return False
end

# ---- stav ----------------------------------------------------------------------------------------------

function refresh():
    if D["refresh"] != 0:
        call glib.source_remove(D["refresh"])
        D["refresh"] = 0
    end
    call glib.spawn_capture([helper(), "get"], on_state, None)
    return False
end

function on_state(data, text, status):
    state = None
    safe:
        state = json.decode(text)
    end
    if type(state) != "Dictionary" or type(state.get("outputs")) != "List":
        D["data"] = None
        D["config"] = {}
    else:
        D["data"] = state
        D["x11"] = state.get("x11") == True
        D["primary"] = state["primary"]
        D["mode"] = state["mode"]
        config = {}
        for o in state["outputs"]:
            if o["enabled"] and o["width"] > 0:
                config[o["name"]] = {"enabled": True, "width": o["width"], "height": o["height"], "refresh": o["refresh"],
                                     "x": o["x"], "y": o["y"], "transform": o["transform"], "scale": o["scale"]}
            else:
                config[o["name"]] = {"enabled": False}
            end
        end
        D["config"] = config
    end
    if not D["busy"]:
        call fill()
    end
    return 0
end

# Pripojeny nebo odpojeny monitor (luxwm): obnovit, pokud zrovna nic nezkousime
function on_wm(event):
    if event.get("event") == "output" and D["outer"] != 0 and not D["busy"] and D["refresh"] == 0:
        D["refresh"] = glib.timeout_add(400, refresh)
    end
    return 0
end

# ---- hooky stranky -------------------------------------------------------------------------------------

function build(host):
    D["window"] = host["window"]
    if D["css"] == 0:
        D["css"] = gtk.css_load(CSS)
    end
    outer = ui.page_box()
    D["outer"] = outer
    D["page"] = 0
    if host["wayland"] and not D["wm"]:
        D["wm"] = True
        call wm.listen(on_wm)
        call wm.subscribe(["output"])
    end
    return outer
end

function show(host):
    if not D["busy"]:
        call refresh()
    end
    return 0
end

# Odchod ze stranky nebo zavreni okna: nepotvrzene nastaveni vratit hned, rozpracovanou velikost textu pouzit
function leave(host):
    call signal_helper(12)
    call close_dialog()
    if D["text_timer"] != 0:
        call glib.source_remove(D["text_timer"])
        call apply_text_size()
    end
    if D["refresh"] != 0:
        call glib.source_remove(D["refresh"])
        D["refresh"] = 0
    end
    return 0
end

function cli(args):
    if "--menu" in args:
        return run_menu()
    end
    return None
end

# ---- rizeni z testu (luxos-settings preda nezname prikazy) -----------------------------------------------

function test_state():
    combos = {}
    for name in D["named"].keys():
        c = D["named"][name]
        w = D["widgets"][c]
        i = gtk.combo_box_get_active(c)
        combos[name] = {"values": [it[0] for it in w["items"]], "labels": [it[1] for it in w["items"]],
                        "active": w["items"][i][0] if i >= 0 else None, "sensitive": gtk.widget_get_sensitive(c)}
    end
    text = None
    if D["text_scale"] != 0:
        text = [text_index(), gtk.label_get_text(D["text_value"])]
    end
    return {"x11": D["x11"], "busy": D["busy"], "dialog": D["dialog"] != 0, "message": D["message"],
            "primary": D["primary"], "mode": D["mode"], "rects": rects(), "mirrored": mirrored(),
            "editable": len(rects()) > 1 and not mirrored(), "combos": combos, "text": text,
            "switch": gtk.switch_get_active(D["switch"]) if D["switch"] != 0 else None,
            "page_sensitive": gtk.widget_get_sensitive(D["page"]) if D["page"] != 0 else False,
            "loaded": D["page"] != 0, "size": gtk.window_get_size(D["window"])}
end

# drag NAZEV DX DY [bar]: pretazeni o DX, DY pixelu plochy (stred obdelniku, nebo bila lista)
function test_drag(rest):
    parts = rest.split(" ")
    view = compute_view()
    r = rects()[parts[0]]
    v = to_view(r, view)
    x = v[0] + v[2] / 2
    y = v[1] + v[3] / 2
    if len(parts) > 3 and parts[3] == "bar":
        y = v[1] + 8
    end
    dx = Float(parts[1]) * view[0]
    dy = Float(parts[2]) * view[0]
    if not press_at(x, y):
        call lsys.out("drag refused\n")
        return 0
    end
    call motion_at(x + dx / 2, y + dy / 2)
    call motion_at(x + dx, y + dy)
    if len(parts) > 3 and parts[len(parts) - 1] == "hold":
        return 0
    end
    call release_at(x + dx, y + dy)
    return 0
end

function test(command, rest):
    if command == "page-state":
        call lsys.out("state " + json.encode(test_state()) + "\n")
    elif command == "select":
        # select NAZEV [JSON_HODNOTA]: polozka rozbalovaciho seznamu jako vyber uzivatelem
        cut = rest.find(" ")
        c = D["named"].get(rest[:cut])
        value = json.decode(rest[cut + 1:])[0]
        if c != None:
            items = D["widgets"][c]["items"]
            for i in range(len(items)):
                if items[i][0] == value:
                    call gtk.combo_box_set_active(c, i)
                end
            end
        end
    elif command == "drag":
        call test_drag(rest)
    elif command == "text":
        call gtk.range_set_value(D["text_scale"], Float(Int(rest)))
    elif command == "mirror":
        call gtk.switch_set_active(D["switch"], rest == "1")
    elif command == "close":
        # jako krizek spravce oken: nejvyssi okno (potvrzovaci dialog, jinak okno Nastaveni)
        call gtk.window_close(D["dialog"] if D["dialog"] != 0 else D["window"])
    elif command == "drawcheck":
        # drawcheck NAZEV: nahled monitoru 100x70 na plose 400x160; pocet pixelu mimo jeho obdelnik
        surface = cairo.image_surface_create(0, 400, 160)
        cr = cairo.create(surface)
        call draw_display(cr, [150, 40, 100, 70], rest, True, [0.1, 0.1, 0.1], 1.0, False)
        call cairo.surface_flush(surface)
        outside = 0
        for y in range(160):
            for x in range(400):
                if (x < 150 or x >= 250 or y < 40 or y >= 110) and cairo.image_surface_pixel(surface, x, y) != 0:
                    outside += 1
                end
            end
        end
        call cairo.destroy(cr)
        call cairo.surface_destroy(surface)
        call lsys.out("outside " + String(outside) + "\n")
    else:
        return False
    end
    return True
end

# ---- rychla volba rezimu (Super+P, luxos-displays menu) ---------------------------------------------------

MENU = [["extend", "Extend - use both screens", "luxos-display-extend-symbolic"],
        ["mirror", "Mirror - same picture on both", "luxos-display-mirror-symbolic"],
        ["external", "Only external screen", "luxos-display-external-symbolic"],
        ["internal", "Only this computer's screen", "computer-symbolic"]]
menu = {"window": 0, "buttons": [], "pidfile": "", "sel": 0}

function menu_choose(button):
    for i in range(len(menu["buttons"])):
        if menu["buttons"][i] == button:
            call glib.spawn([helper(), MENU[i][0]])
        end
    end
    call gtk.main_quit()
    return 0
end

function menu_key(event, window):
    if gtk.event_key_name(event) == "Escape":
        call gtk.main_quit()
        return True
    end
    return False
end

# Druhe Super+P pri otevrene volbe: dalsi rezim (jako Win+P)
function menu_next():
    call gtk.widget_grab_focus(menu["buttons"][(menu["sel"] + 1) % len(menu["buttons"])])
    return True
end

function menu_focus(event, button):
    menu["sel"] = menu["buttons"].index(button)
    return False
end

function menu_state(data, text, status):
    state = None
    safe:
        state = json.decode(text)
    end
    if type(state) != "Dictionary":
        return 0
    end
    for i in range(len(MENU)):
        if MENU[i][0] == state.get("mode"):
            call gtk.widget_add_class(menu["buttons"][i], "current")
            call gtk.widget_grab_focus(menu["buttons"][i])
        end
    end
    return 0
end

function menu_running():
    path = glib.user_runtime_dir() + "/luxos-displays-menu.pid"
    menu["pidfile"] = path
    pid = 0
    safe:
        pid = Int(glib.read_text(path).strip())
    end
    if pid > 0 and glib.readlink("/proc/" + String(pid) + "/exe") == glib.readlink("/proc/self/exe") and lsys.same_session(pid):
        call glib.kill(pid, 10)
        return True
    end
    call glib.write_atomic(path, String(glib.getpid()) + chr(10))
    return False
end

function run_menu():
    call glib.set_prgname("luxos-displays-menu")
    call gtk.init()
    if not layer.is_wayland() or not layer.is_supported():
        print "luxos-displays-settings: the quick switcher needs a Wayland compositor with layer-shell"
        return 2
    end
    if menu_running():
        return 0
    end
    call gtk.css_load(MENU_CSS)
    win = gtk.window_new(i18n.T("Screens"))
    menu["window"] = win
    call gtk.window_set_rgba(win)
    call layer.init_for_window(win)
    call layer.set_namespace(win, "luxos-displays-menu")
    call layer.set_layer(win, layer.LAYER_OVERLAY)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_EXCLUSIVE)
    card = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(card, "osd")
    title = gtk.label_new(i18n.T("Screens"))
    call gtk.widget_add_class(title, "osd-title")
    call gtk.box_pack_start(card, title, False, False, 0)
    row_box = gtk.box_new(gtk.HORIZONTAL, 10)
    for item in MENU:
        b = gtk.button_new_empty()
        call gtk.button_set_relief(b, 2)
        content = gtk.box_new(gtk.VERTICAL, 8)
        icon = gtk.image_new_from_icon_name(item[2], 6)
        call gtk.image_set_pixel_size(icon, 48)
        call gtk.box_pack_start(content, icon, False, False, 0)
        text = gtk.label_new(i18n.T(item[1]))
        call gtk.label_set_line_wrap(text, True)
        call gtk.label_set_max_width_chars(text, 14)
        call gtk.label_set_justify(text, 2)
        call gtk.widget_add_class(text, "osd-label")
        call gtk.box_pack_start(content, text, False, False, 0)
        call gtk.container_add(b, content)
        call gtk.connect(b, "clicked", menu_choose)
        call gtk.connect(b, "focus-in-event", menu_focus)
        menu["buttons"].append(b)
        call gtk.box_pack_start(row_box, b, False, False, 0)
    end
    call gtk.box_pack_start(card, row_box, False, False, 0)
    call gtk.container_add(win, card)
    call gtk.connect(win, "key-press-event", menu_key)
    call gtk.connect(win, "destroy", on_menu_destroy)
    call glib.unix_signal_add(10, menu_next)
    call glib.spawn_capture([helper(), "get"], menu_state, None)
    call gtk.widget_grab_focus(menu["buttons"][0])
    # na hlavnim monitoru luxwm; bez luxwm (nebo kdyz neodpovi) tam, kde ho umisti kompozitor
    call primary.follow(on_menu_primary)
    call glib.timeout_add(150, menu_show)
    call gtk.main()
    call glib.unlink(menu["pidfile"])
    return 0
end

function on_menu_primary(monitor):
    call layer.set_monitor(menu["window"], monitor)
    return menu_show()
end

function menu_show():
    if not gtk.widget_get_visible(menu["window"]):
        call gtk.widget_show_all(menu["window"])
    end
    return False
end

function on_menu_destroy(window):
    call gtk.main_quit()
    return 0
end
