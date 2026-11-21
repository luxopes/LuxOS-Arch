# LuxOS - Monitory na Waylandu (/usr/lib/luxos/luxos-displays-settings, /usr/bin/luxos-display-settings je odkaz sem;
# na X11 preda Monitorum v Pythonu, /usr/lib/luxos/luxos-display-settings-x11):
# usporadani pretazenim (prichyceni k hrane, bez mezer a prekryvu), hlavni monitor (bila lista: Dock, oznameni
# a okna z odpojenych monitoru), zrcadleni, rezim vice monitoru, rozliseni, frekvence, meritko vcetne
# zlomkoveho a otoceni. Kazda zmena se hned pouzije a do 15 s se musi potvrdit, jinak se vrati puvodni.
#
# Okno samo monitory nemeni (nema pravo na wlr-output-management): stav cte z `luxos-displays get` a zmenu
# posila `luxos-displays try JSON`. Casovac vraceni bezi v pomocniku, takze se puvodni nastaveni vrati
# i kdyz okno spadne. Potvrzeni = SIGUSR1 pomocniku, vratit hned = SIGUSR2.
#
#   luxos-displays-settings          okno
#   luxos-displays-settings --menu   rychla volba rezimu (Super+P): ctyri volby nad vsemi okny (layer-shell)
load env, json, math
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_i18n as i18n
load luxos_luxwm as wm
load luxos_layer as layer
load luxos_primary as primary
load luxos_displays as dw

HELPER = "/usr/lib/luxos/luxos-displays"
X11_SETTINGS = "/usr/lib/luxos/luxos-display-settings-x11"
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 10px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.65; }\n.error { color: #c0392b; }\n.osd { border-radius: 18px; padding: 18px; background-color: alpha(@theme_bg_color, 0.96); border: 1px solid alpha(currentColor, 0.15); }\n.osd-title { font-weight: 700; font-size: 15px; margin-bottom: 12px; }\n.osd button { border-radius: 12px; padding: 12px; min-width: 132px; }\n.osd button.current { background-image: none; background-color: alpha(@theme_selected_bg_color, 0.25); }\n.osd-label { font-size: 12px; }\n.osd label, .osd image { color: @theme_fg_color; }\n"
PAD = 18
SNAP_PX = 10
ROTATIONS = [[0, "Standard"], [1, "90°"], [2, "180°"], [3, "270°"]]

ui = {"window": 0, "outer": 0, "page": 0, "building": False, "busy": False, "data": None, "config": {},
      "primary": "", "mode": "extend", "widgets": {}, "area": 0, "drag": None, "view": None, "pid": 0,
      "output": "", "dialog": 0, "countdown": 0, "left": 0, "tick": 0, "message": "", "refresh": 0}

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
    if ui["data"] == None:
        return []
    end
    return ui["data"]["outputs"]
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
    for name in ui["config"].keys():
        result[name] = ui["config"][name].copy()
    end
    return result
end

function rects():
    result = {}
    for name in ui["config"].keys():
        c = ui["config"][name]
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

# ---- stavebni prvky (jako ostatni okna Nastaveni LuxOS) ------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 56)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function group(page, title):
    call gtk.box_pack_start(page, label(title, "group-title"), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

function row(g, title, hint, widget):
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, ""), False, False, 0)
    if hint != "":
        call gtk.box_pack_start(texts, label(hint, "hint"), False, False, 0)
    end
    call gtk.box_pack_start(box, texts, True, True, 0)
    if widget != 0:
        call gtk.widget_set_valign(widget, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widget, False, False, 0)
    end
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    g["rows"] = g["rows"] + 1
    return box
end

# Rozbalovaci seznam: items = [[hodnota, text]..]; f(hodnota, data) po zmene uzivatelem
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
    ui["widgets"][c] = {"items": items, "f": f, "data": data}
    call gtk.connect(c, "changed", on_combo)
    return c
end

function on_combo(c):
    if ui["building"] or c not in ui["widgets"]:
        return 0
    end
    w = ui["widgets"][c]
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

# ---- obsah okna ----------------------------------------------------------------------------------------

function build():
    ui["building"] = True
    ui["widgets"] = {}
    ui["area"] = 0
    if ui["page"] != 0:
        call gtk.widget_destroy(ui["page"])
    end
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 6, 22)
    ui["page"] = page
    call gtk.box_pack_start(ui["outer"], page, True, True, 0)
    outs = outputs()
    if len(outs) == 0:
        call gtk.box_pack_start(page, label(i18n.T("No displays found. Display settings need a Wayland session with LuxOS."), "hint"), False, False, 24)
    elif len(outs) > 1:
        call build_arrangement(page)
        g = group(page, i18n.T("Multiple Displays"))
        modes = [["extend", i18n.T("Extend - use both screens")], ["mirror", i18n.T("Mirror - same picture on both")],
                 ["external", i18n.T("Only external screen")], ["internal", i18n.T("Only this computer's screen")]]
        call row(g, i18n.T("Use as"), i18n.T("You can also switch with Super+P."), combo(modes, ui["mode"], on_mode, None))
    else:
        call build_arrangement(page)
    end
    if ui["message"] != "":
        call gtk.box_pack_start(page, label(ui["message"], "error"), False, False, 8)
    end
    for o in outs:
        call build_output(page, o)
    end
    call gtk.widget_show_all(page)
    if ui["busy"]:
        call gtk.widget_set_sensitive(page, False)
    end
    ui["building"] = False
    return 0
end

function build_arrangement(page):
    outs = outputs()
    g = group(page, i18n.T("Arrangement"))
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, -1, 190)
    call gtk.widget_set_margins(area, 10, 10, 6, 0)
    call gtk.widget_add_events(area, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    call gtk.connect(area, "draw", on_draw)
    call gtk.connect(area, "button-press-event", on_press)
    call gtk.connect(area, "motion-notify-event", on_motion)
    call gtk.connect(area, "button-release-event", on_release)
    ui["area"] = area
    call gtk.box_pack_start(g["box"], area, False, False, 0)
    if len(outs) < 2:
        g["rows"] = 1
        return 0
    end
    text = i18n.T("Drag the displays to arrange them. Drag the white bar to another display to move the menu bar and Dock there.")
    if mirrored():
        text = i18n.T("The displays show the same picture. Turn off mirroring to arrange them.")
    elif len(rects()) < 2:
        text = i18n.T("Only one display is in use. Choose Extend under Multiple Displays to arrange them.")
    end
    hint = label(text, "hint")
    call gtk.widget_set_margins(hint, 14, 14, 0, 8)
    call gtk.box_pack_start(g["box"], hint, False, False, 0)
    g["rows"] = 1
    items = []
    for o in outs:
        if ui["config"][o["name"]]["enabled"]:
            items.append([o["name"], display_name(o)])
        end
    end
    main = combo(items, ui["primary"], on_main, None)
    call gtk.widget_set_sensitive(main, len(items) > 1)
    call row(g, i18n.T("Main display"), i18n.T("The menu bar and Dock appear on the main display."), main)
    sw = gtk.switch_new()
    call gtk.switch_set_active(sw, mirrored())
    call gtk.connect(sw, "state-set", on_mirror)
    call row(g, i18n.T("Mirror displays"), i18n.T("Show the same picture on all displays."), sw)
    return 0
end

function build_output(page, o):
    g = group(page, display_name(o))
    c = ui["config"][o["name"]]
    if not c["enabled"]:
        call row(g, i18n.T("This display is turned off."), i18n.T("Turn it on with Super+P or under Multiple Displays."), 0)
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
    call row(g, i18n.T("Resolution"), i18n.T("A lower resolution makes everything larger; the recommended one is the sharpest."),
             combo(items, [c["width"], c["height"]], on_resolution, o["name"]))
    rates = dw.refreshes(o, c["width"], c["height"])
    if len(rates) > 0 and rates[len(rates) - 1] > 0:
        items = []
        for r in rates:
            items.insert(0, [r, rate_text(r)])
        end
        call row(g, i18n.T("Refresh rate"), "", combo(items, c["refresh"], on_refresh, o["name"]))
    end
    items = []
    for s in dw.SCALES:
        items.append([s, String(s // 10) + " %"])
    end
    if c["scale"] not in dw.SCALES:
        items.append([c["scale"], String(c["scale"] // 10) + " %"])
    end
    call row(g, i18n.T("Scale"), i18n.T("Makes text, windows and the menu bar larger on this display. 125-175 % suits sharp laptop screens."),
             combo(items, c["scale"], on_scale, o["name"]))
    items = []
    for r in ROTATIONS:
        items.append([r[0], i18n.T(r[1])])
    end
    call row(g, i18n.T("Rotation"), "", combo(items, c["transform"], on_rotation, o["name"]))
    return 0
end

# ---- usporadani (kresleni a tazeni) ----------------------------------------------------------------

function compute_view():
    r = rects()
    if len(r) == 0 or ui["area"] == 0:
        return None
    end
    w = gtk.widget_get_allocated_width(ui["area"])
    h = gtk.widget_get_allocated_height(ui["area"])
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
    view = ui["view"]
    if view == None:
        view = compute_view()
    end
    if view == None:
        return [None, False]
    end
    r = rects()
    names = [ui["primary"]] + [n for n in sorted(r.keys()) if n != ui["primary"]]
    for name in names:
        if name not in r:
            continue
        end
        v = to_view(r[name], view)
        if x >= v[0] and x <= v[0] + v[2] and y >= v[1] and y <= v[1] + v[3]:
            return [name, name == ui["primary"] and y <= v[1] + 16]
        end
    end
    return [None, False]
end

function editable():
    return len(rects()) > 1 and not mirrored() and not ui["busy"]
end

function on_press(event, area):
    if not editable() or gtk.event_button(event) != 1:
        return False
    end
    found = hit(gtk.event_x(event), gtk.event_y(event))
    if found[0] == None:
        return False
    end
    ui["drag"] = {"name": found[0], "bar": found[1], "x0": gtk.event_x(event), "y0": gtk.event_y(event),
                  "view": ui["view"] if ui["view"] != None else compute_view(), "dx": 0.0, "dy": 0.0}
    return True
end

function on_motion(event, area):
    d = ui["drag"]
    if d == None:
        if editable():
            name = hit(gtk.event_x(event), gtk.event_y(event))[0]
            call gtk.widget_set_cursor(area, "grab" if name != None else "")
        end
        return False
    end
    d["dx"] = gtk.event_x(event) - d["x0"]
    d["dy"] = gtk.event_y(event) - d["y0"]
    call gtk.widget_queue_draw(area)
    return True
end

# Kam monitor po pusteni dopadne: {nazev: [x, y]}
function proposal(d):
    r = rects()
    v = r[d["name"]]
    px = math.round(v[0] + d["dx"] / d["view"][0])
    py = math.round(v[1] + d["dy"] / d["view"][0])
    return dw.drop(r, d["name"], px, py, ui["primary"], math.round(SNAP_PX / d["view"][0]))
end

function on_release(event, area):
    d = ui["drag"]
    if d == None or gtk.event_button(event) != 1:
        return False
    end
    ui["drag"] = None
    call gtk.widget_queue_draw(area)
    if abs(d["dx"]) <= 3 and abs(d["dy"]) <= 3:
        return True
    end
    if d["bar"]:
        # lista pretazena na jiny monitor = novy hlavni monitor
        x = gtk.event_x(event)
        y = gtk.event_y(event)
        r = rects()
        for name in r.keys():
            v = to_view(r[name], d["view"])
            if name != ui["primary"] and x >= v[0] and x <= v[0] + v[2] and y >= v[1] and y <= v[1] + v[3]:
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
        ui["config"] = config
        call try_config(config, ui["primary"], False)
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
    d = ui["drag"]
    view = d["view"] if d != None else compute_view()
    ui["view"] = view
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
            ref = dw.drop_anchor(r, name, ui["primary"])
            sx = r[ref][0] - pos[ref][0]
            sy = r[ref][1] - pos[ref][1]
            call draw_display(cr, to_view([pos[name][0] + sx, pos[name][1] + sy, r[name][2], r[name][3]], view), "", False, fg, 1.0, True)
            call draw_display(cr, [v[0] + d["dx"], v[1] + d["dy"], v[2], v[3]], text, name == ui["primary"], fg, 0.8, False)
            continue
        end
        call draw_display(cr, v, text, name == ui["primary"] and not (d != None and d["bar"]), fg, 1.0, False)
    end
    if d != None and d["bar"] and ui["primary"] in r:
        v = to_view(r[ui["primary"]], view)
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
    if ui["building"]:
        return False
    end
    if state != 0:
        call try_request({"mode": "mirror"})
    else:
        call try_request({"mode": "extend"})
    end
    return False
end

function on_mode(mode, data):
    call try_request({"mode": mode})
end

function change(name, field_values):
    config = config_copy()
    config[name].update(field_values)
    call try_config(dw.resettle(config, ui["primary"]), ui["primary"], mirrored())
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

# Zkusebni pouziti pres pomocnika; "applied" = zeptat se, konec procesu = obnovit okno
function try_request(request):
    if ui["busy"]:
        return 0
    end
    ui["message"] = ""
    ui["busy"] = True
    ui["output"] = ""
    call gtk.widget_set_sensitive(ui["page"], False)
    ui["pid"] = glib.spawn_stream([helper(), "try", "-s", String(seconds()), json.encode(request)], on_try_output, None)
    if ui["pid"] == 0:
        ui["busy"] = False
        ui["message"] = i18n.T("The display could not use this setting.")
        call refresh()
    end
    return 0
end

function on_try_output(data, chunk):
    if chunk == "":
        ui["pid"] = 0
        ui["busy"] = False
        call close_dialog()
        if ui["output"].find("applied") < 0:
            ui["message"] = i18n.T("The display could not use this setting.") + " " + i18n.T("The previous settings were restored.")
        end
        call refresh()
        return 0
    end
    ui["output"] = ui["output"] + chunk
    if chunk.find("applied") >= 0:
        call open_dialog()
    end
    return 0
end

# "Ponechat nastaveni?" s odpoctem (odpocet je jen ukazatel, vraceni hlida pomocnik)
function open_dialog():
    dlg = gtk.window_new(i18n.T("Displays"))
    call gtk.window_set_transient_for(dlg, ui["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_resizable(dlg, False)
    call gtk.window_set_position(dlg, 4)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_margins(box, 20, 20, 18, 16)
    title = gtk.label_new("")
    call gtk.label_set_markup(title, "<b>" + glib.markup_escape(i18n.T("Keep these display settings?")) + "</b>")
    call gtk.label_set_xalign(title, 0)
    call gtk.box_pack_start(box, title, False, False, 0)
    ui["left"] = seconds()
    ui["countdown"] = label("", "")
    call gtk.box_pack_start(box, ui["countdown"], False, False, 0)
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
    ui["dialog"] = dlg
    call update_countdown()
    ui["tick"] = glib.timeout_add(1000, on_tick)
    call gtk.widget_show_all(dlg)
    call gtk.widget_grab_focus(revert)
    return 0
end

function update_countdown():
    call gtk.label_set_text(ui["countdown"], i18n.TF("The previous settings will be restored in %d seconds.", [max(0, ui["left"])]))
end

function on_tick():
    ui["left"] = ui["left"] - 1
    if ui["dialog"] == 0:
        ui["tick"] = 0
        return False
    end
    call update_countdown()
    return True
end

function close_dialog():
    if ui["tick"] != 0:
        call glib.source_remove(ui["tick"])
        ui["tick"] = 0
    end
    if ui["dialog"] != 0:
        dlg = ui["dialog"]
        ui["dialog"] = 0
        call gtk.widget_destroy(dlg)
    end
end

function signal_helper(signum):
    if ui["pid"] != 0:
        call glib.kill(ui["pid"], signum)
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
    ui["dialog"] = 0
    return False
end

# ---- stav ----------------------------------------------------------------------------------------------

function refresh():
    if ui["refresh"] != 0:
        call glib.source_remove(ui["refresh"])
        ui["refresh"] = 0
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
        ui["data"] = None
        ui["config"] = {}
    else:
        ui["data"] = state
        ui["primary"] = state["primary"]
        ui["mode"] = state["mode"]
        config = {}
        for o in state["outputs"]:
            if o["enabled"] and o["width"] > 0:
                config[o["name"]] = {"enabled": True, "width": o["width"], "height": o["height"], "refresh": o["refresh"],
                                     "x": o["x"], "y": o["y"], "transform": o["transform"], "scale": o["scale"]}
            else:
                config[o["name"]] = {"enabled": False}
            end
        end
        ui["config"] = config
    end
    if not ui["busy"]:
        call build()
    end
    return 0
end

# Pripojeny nebo odpojeny monitor (luxwm): obnovit, pokud zrovna nic nezkousime
function on_wm(event):
    if event.get("event") == "output" and not ui["busy"] and ui["refresh"] == 0:
        ui["refresh"] = glib.timeout_add(400, refresh)
    end
    return 0
end

function on_delete(event, window):
    # zavreni behem zkousky: nepotvrzene nastaveni vratit hned
    call signal_helper(12)
    call gtk.main_quit()
    return False
end

# ---- rychla volba rezimu (Super+P) --------------------------------------------------------------------

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
    if pid > 0 and glib.readlink("/proc/" + String(pid) + "/exe") == glib.readlink("/proc/self/exe"):
        call glib.kill(pid, 10)
        return True
    end
    call glib.write_atomic(path, String(glib.getpid()) + chr(10))
    return False
end

function run_menu():
    if not layer.is_wayland() or not layer.is_supported():
        print "luxos-displays-settings: the quick switcher needs a Wayland compositor with layer-shell"
        exit(2)
    end
    if menu_running():
        exit(0)
    end
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

# ---- start ---------------------------------------------------------------------------------------------

# spousteni jmenem (Launchpad, Ovladaci centrum, nabidka plochy) na Waylandu bez Pythonu, na X11 aplikace v Pythonu
display = env.get("WAYLAND_DISPLAY", "")
if display == None or display == "":
    call glib.exec([X11_SETTINGS] + args[1:])
    call glib.report("luxos-display-settings: cannot run " + X11_SETTINGS + chr(10))
    exit(127)
end
call glib.set_prgname("luxos-displays-settings")
call gtk.init()
call gtk.css_load(CSS)
if len(args) > 1 and args[1] == "--menu":
    call run_menu()
    exit(0)
end
window = gtk.window_new(i18n.T("Displays"))
ui["window"] = window
call gtk.window_set_wmclass(window, "luxos-displays-settings", "luxos-displays-settings")
call gtk.window_set_icon_list(window, "luxos-displays")
call gtk.window_set_default_size(window, 640, 680)
scroll = gtk.scrolled_window_new()
call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
outer = gtk.box_new(gtk.VERTICAL, 0)
ui["outer"] = outer
call gtk.container_add(scroll, outer)
call gtk.container_add(window, scroll)
call gtk.connect(window, "delete-event", on_delete)
call wm.connect(on_wm)
call wm.subscribe(["output"])
call refresh()
call gtk.widget_show_all(window)
call gtk.main()
