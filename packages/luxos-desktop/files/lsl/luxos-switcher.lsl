# LuxOS - Alt+Tab prepinac oken na Waylandu (1.1.0). Stejny vzhled jako X11 (xfwm4 tabwin s cycle_preview):
# okno #xfwm-tabwin ze stylu luxos-gtk3.css v tematu (zaobleny poloprusvitny panel, tlacitka s vybranou
# polozkou :checked, tucny nazev okna dole) a v kazdem tlacitku nahled obsahu okna 256 px s ikonou aplikace
# dole uprostred. Rozmery a zmensovani mrizky jako xfwm4 tabwin.c (computeTabwinData, getClientIcon).
# Nahled = grim -T podle identifikatoru okna z luxwm (ext-foreign-toplevel); minimalizovane okno ma
# jen ikonu, stejne jako na X11. Ovlada se z luxwm: eventy "cycle" pres IPC (start/step/end); klik na
# polozku posle luxwm "cycle_pick".
# Program bezi stale jako sluzba (luxos-switcher.service); okno se jen ukazuje a skryva.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_layer as layer
load luxos_apps as apps
load luxos_luxwm as wm
load luxos_sys

# xfwm4 tabwin.c a -XfwmTabwinWidget-* v luxos-gtk3.css
ICON_SIZE = 96
PREVIEW_SIZE = 256
ICON_BORDER = 5
MAX_RATIO = 0.8
STATE_CHECKED = 2048
GRIM = "/usr/bin/grim"
SHOW_WAIT_MS = 120
# zaobleni oken (luxcomp deco.c theme.radius)
WINDOW_RADIUS = 12.0

S = {"visible": False, "items": [], "pos": 0, "win": 0, "vbox": 0, "grid": 0, "label": 0, "buttons": [],
     "size": PREVIEW_SIZE, "preview": True, "icons": {}, "shots": {}, "busy": {}, "dir": "",
     "wanted": [], "pending": 0, "waiting": False, "timer": 0}

function app_icon(app_id, size, scale):
    key = app_id + "@" + String(size) + "x" + String(scale)
    cached = S["icons"].get(key, None)
    if cached != None:
        return cached
    end
    surface = 0
    info = apps.match(app_id)
    if info != 0:
        surface = apps.own_icon(info, size, scale)
    end
    if surface == 0 and app_id != "":
        surface = apps.icon_named(app_id.lower(), size, scale)
    end
    if surface == 0:
        surface = apps.icon_named("application-x-executable", size, scale)
    end
    S["icons"][key] = surface
    return surface
end

function paint_surface(cr, surface, x, y):
    if surface == 0:
        return 0
    end
    call cairo.set_source_surface(cr, surface, x, y)
    call cairo.paint(cr)
    return 0
end

# Obsah tlacitka jako getClientIcon na X11: nahled vycentrovany v ctverci, mala ikona dole uprostred
function on_preview_draw(index, cr, area):
    if index >= len(S["items"]):
        return False
    end
    item = S["items"][index]
    size = S["size"]
    scale = gtk.widget_scale_factor(area)
    app_id = item.get("app_id", "")
    if not S["preview"]:
        call paint_surface(cr, app_icon(app_id, size, scale), 0.0, 0.0)
        return False
    end
    shot = S["shots"].get(item.get("capture", ""), 0)
    if shot != 0:
        pw = Float(gtk.pixbuf_get_width(shot)) / Float(scale)
        ph = Float(gtk.pixbuf_get_height(shot)) / Float(scale)
        call cairo.save(cr)
        call cairo.translate(cr, Float(Int((Float(size) - pw) / 2.0)), Float(Int((Float(size) - ph) / 2.0)))
        # snimek z kompozitoru je bez alfy (pruhledne rohy okna s vlastnim zahlavim by byly cerne):
        # zaobleni jako okno na obrazovce, zmensene v pomeru nahledu
        radius = WINDOW_RADIUS
        if item.get("w", 0) > 0:
            radius = WINDOW_RADIUS * pw / Float(item["w"])
        end
        call cairo.rounded_rectangle(cr, 0.0, 0.0, pw, ph, min(radius, min(pw, ph) / 2.0))
        call cairo.clip(cr)
        call cairo.scale(cr, 1.0 / Float(scale), 1.0 / Float(scale))
        call gtk.cairo_set_source_pixbuf(cr, shot, 0.0, 0.0)
        call cairo.paint(cr)
        call cairo.restore(cr)
    else:
        # bez obsahu okna (minimalizovane, nahled se jeste nacita) ikona aplikace pres cely ctverec
        call paint_surface(cr, app_icon(app_id, size, scale), 0.0, 0.0)
        return False
    end
    small = min(size // 4, 48)
    call paint_surface(cr, app_icon(app_id, small, scale), Float((size - small) // 2), Float(size - small))
    return False
end

# Pozadi a ramecek panelu z CSS #xfwm-tabwin (tabwin_draw na X11 se slozenim)
function on_win_draw(cr, win):
    w = gtk.widget_get_allocated_width(win)
    h = gtk.widget_get_allocated_height(win)
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_CLEAR)
    call cairo.paint(cr)
    call cairo.restore(cr)
    unsafe:
        ctx = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_style_context"), ptr(win))
        call __lsl_qbe_call6(__lsl_symbol("gtk_render_background"), ctx, ptr(cr), 0.0, 0.0, Float(w), Float(h))
        call __lsl_qbe_call6(__lsl_symbol("gtk_render_frame"), ctx, ptr(cr), 0.0, 0.0, Float(w), Float(h))
    end
    return False
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

# ---- nahledy (grim -T) ----------------------------------------------------------------------------------

function on_shot_done(state, pid, status):
    capture = state[0]
    path = state[1]
    S["busy"][capture] = False
    S["pending"] = max(0, S["pending"] - 1)
    if status == 0 and capture in S["wanted"]:
        scale = gtk.widget_scale_factor(S["win"])
        box = S["size"] * scale
        shot = gtk.pixbuf_new_from_file_at_scale(path, box, box, True)
        if shot != 0:
            old = S["shots"].get(capture, 0)
            if old != 0:
                call glib.object_unref(old)
            end
            S["shots"][capture] = shot
            for button in S["buttons"]:
                call gtk.widget_queue_draw(button)
            end
        end
    end
    call glib.unlink(path)
    if S["pending"] == 0 and S["waiting"]:
        call show_now(0)
    end
    return 0
end

function request_shots():
    if S["dir"] == "":
        S["dir"] = glib.user_runtime_dir() + "/luxos-switcher"
        call glib.mkdir_p(S["dir"])
    end
    scale = gtk.widget_scale_factor(S["win"])
    wanted = []
    for item in S["items"]:
        capture = item.get("capture", "")
        if capture != "":
            wanted.append(capture)
        end
    end
    S["wanted"] = wanted
    # nahledy oken, ktera uz v seznamu nejsou, pryc
    stale = []
    for capture in S["shots"].keys():
        if capture not in wanted:
            stale.append(capture)
        end
    end
    for capture in stale:
        call glib.object_unref(S["shots"][capture])
        call S["shots"].pop(capture)
    end
    if not S["preview"]:
        return 0
    end
    for item in S["items"]:
        capture = item.get("capture", "")
        if capture == "" or S["busy"].get(capture, False):
            continue
        end
        # snimek rovnou ve velikosti ctverce nahledu: rychle kodovani i nacteni (kompozitor snima okno
        # v logickych pixelech w x h, vetsi nez 1 by jen rozmazane zvetsoval)
        side = max(item.get("w", 0), item.get("h", 0))
        factor = 1.0
        if side > 0:
            factor = min(1.0, Float(S["size"] * scale) / Float(side))
        end
        path = S["dir"] + "/" + capture + ".png"
        pid = glib.spawn_watched_data(["/usr/bin/timeout", "2", GRIM, "-T", capture, "-s", String(factor), "-l", "0", path],
                                      on_shot_done, [capture, path])
        if pid != 0:
            S["busy"][capture] = True
            S["pending"] += 1
        end
    end
    return 0
end

# ---- mrizka ---------------------------------------------------------------------------------------------

function label_height():
    pref = gtk.widget_get_preferred_height(S["label"])
    return max(pref[1], 1)
end

# computeTabwinData: nahledy 256 px, kdyz se nevejdou, polovicni; pod 96 px uz jen ikony 96 px
function compute_layout(count):
    mon = [0, 0, 1280, 800]
    monitors = layer.monitors()
    if len(monitors) > 0:
        mon = layer.monitor_geometry(monitors[0])
    end
    label_h = label_height()
    size = PREVIEW_SIZE
    preview = True
    request = size + label_h + 2 * ICON_BORDER
    cols = max(1, Int(Float(mon[2]) * MAX_RATIO / Float(request)))
    rows = (count + cols - 1) // cols
    while Float(request * rows + label_h) > Float(mon[3]) * MAX_RATIO:
        size = size // 2
        if preview and size <= ICON_SIZE:
            preview = False
            size = ICON_SIZE
        end
        request = size + label_h + 2 * ICON_BORDER
        cols = max(1, Int(Float(mon[2]) * MAX_RATIO / Float(request)))
        rows = (count + cols - 1) // cols
        if size < 8:
            size = 8
            break
        end
    end
    S["size"] = size
    S["preview"] = preview
    return [cols, request]
end

function same_windows(items):
    if len(items) != len(S["items"]):
        return False
    end
    index = 0
    while index < len(items):
        if items[index].get("id", 0) != S["items"][index].get("id", 0):
            return False
        end
        index += 1
    end
    return True
end

# Mys jako tabwin v xfwm4: najeti ukaze nazev okna pod mysi, klik ho vybere a prepinani ukonci (luxwm
# prikaz cycle_pick; okno se zameri az tam, jako po pusteni Alt)
function title_of(pos):
    if pos < 0 or pos >= len(S["items"]):
        return ""
    end
    title = S["items"][pos].get("title", "")
    return title if title != "" else S["items"][pos].get("app_id", "")
end

function on_button_enter(index, event, button):
    call gtk.label_set_text(S["label"], title_of(index))
    return False
end

function on_button_leave(index, event, button):
    call gtk.label_set_text(S["label"], title_of(S["pos"]))
    return False
end

function on_pick_reply(reply):
    return 0
end

function on_button_clicked(index, button):
    if index < len(S["items"]):
        call wm.request({"cmd": "cycle_pick", "window": S["items"][index].get("id", 0)}, on_pick_reply)
    end
    return 0
end

function rebuild():
    if S["grid"] != 0:
        call gtk.widget_destroy(S["grid"])
        S["grid"] = 0
    end
    S["buttons"] = []
    layout = compute_layout(len(S["items"]))
    cols = layout[0]
    request = layout[1]
    grid = gtk.grid_new()
    call gtk.grid_set_row_homogeneous(grid, True)
    call gtk.grid_set_row_spacing(grid, 4)
    call gtk.grid_set_column_homogeneous(grid, True)
    call gtk.grid_set_column_spacing(grid, 4)
    index = 0
    for item in S["items"]:
        button = gtk.button_new_empty()
        call gtk.button_set_relief(button, gtk.RELIEF_NONE)
        call gtk.widget_set_can_focus(button, False)
        call gtk.widget_set_size_request(button, request, request)
        call gtk.connect_data(button, "clicked", 0, on_button_clicked, index)
        call gtk.connect_data(button, "enter-notify-event", 1, on_button_enter, index)
        call gtk.connect_data(button, "leave-notify-event", 1, on_button_leave, index)
        box = gtk.box_new(1, 0)
        area = gtk.drawing_area_new()
        call gtk.widget_set_size_request(area, S["size"], S["size"])
        call gtk.widget_set_halign(area, gtk.ALIGN_CENTER)
        call gtk.widget_set_valign(area, gtk.ALIGN_END)
        call gtk.connect_data(area, "draw", 1, on_preview_draw, index)
        call gtk.box_pack_start(box, area, True, True, 0)
        # popisek tridy okna v tlacitku CSS skryva (font-size 1px), drzi ale vysku jako na X11
        call gtk.box_pack_start(box, gtk.label_new(""), True, True, 0)
        call gtk.container_add(button, box)
        call gtk.grid_attach(grid, button, index % cols, index // cols, 1, 1)
        S["buttons"].append(button)
        index += 1
    end
    call gtk.box_pack_start(S["vbox"], grid, True, True, 0)
    S["grid"] = grid
    call gtk.widget_show_all(grid)
    return 0
end

function select(pos):
    index = 0
    for button in S["buttons"]:
        if index == pos:
            call gtk.widget_set_state_flags(button, STATE_CHECKED, False)
        else:
            call gtk.widget_unset_state_flags(button, STATE_CHECKED)
        end
        index += 1
    end
    call gtk.label_set_text(S["label"], title_of(pos))
    return 0
end

function stop_timer():
    if S["timer"] != 0:
        call glib.source_remove(S["timer"])
        S["timer"] = 0
    end
    return 0
end

function show_now(unused):
    S["timer"] = 0
    S["waiting"] = False
    if not S["visible"]:
        S["visible"] = True
        call gtk.widget_show_all(S["win"])
    end
    return False
end

# Panel az s nahledy (nejdele SHOW_WAIT_MS), at neprobliknou ikony; rychle tuknuti Alt+Tab ho neukaze vubec
function show_switcher():
    if S["visible"] or S["waiting"]:
        return 0
    end
    if S["pending"] == 0:
        return show_now(0)
    end
    S["waiting"] = True
    S["timer"] = glib.timeout_add_data(SHOW_WAIT_MS, show_now, 0)
    return 0
end

function hide_switcher():
    call stop_timer()
    S["waiting"] = False
    if not S["visible"]:
        return 0
    end
    S["visible"] = False
    call gtk.widget_hide(S["win"])
    return 0
end

function on_wm_event(event):
    if event.get("event", "") != "cycle":
        return 0
    end
    action = event.get("action", "")
    if action == "start" or action == "step":
        items = event.get("items", [])
        if len(items) == 0:
            return 0
        end
        changed = action == "start" or S["grid"] == 0 or not same_windows(items)
        S["items"] = items
        S["pos"] = event.get("pos", 0)
        if changed:
            call rebuild()
            call request_shots()
            # okno se zmensi na novou mrizku (layer-shell bez kotev = stred vystupu)
            call gtk.window_resize(S["win"], 1, 1)
        end
        call select(S["pos"])
        call show_switcher()
    elif action == "end":
        call hide_switcher()
    end
    return 0
end

# ---- start -------------------------------------------------------------------------------------------

call glib.setlocale()
unsafe:
    call __lsl_qbe_icall2(__lsl_symbol("gtk_init_check"), 0, 0)
end

if not layer.is_wayland() or not layer.is_supported():
    call luxos_sys.eprint("luxos-switcher: needs a Wayland compositor with layer-shell")
    call exit(2)
end

win = gtk.window_new("luxos-switcher")
call layer.init_for_window(win)
call layer.set_namespace(win, "luxos-switcher")
call layer.set_layer(win, layer.LAYER_OVERLAY)
call layer.set_exclusive_zone(win, -1)
call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
call gtk.widget_set_name(win, "xfwm-tabwin")
call gtk.widget_set_app_paintable(win, True)
call gtk.widget_set_rgba_visual(win)
# okraj = zaobleni + ramecek + padding z CSS, jako tabwinCreate na X11 (22 + 1 + 0)
call gtk.container_set_border_width(win, 23)
call gtk.connect(win, "draw", on_win_draw)
vbox = gtk.box_new(1, 3)
call gtk.container_add(win, vbox)
label = gtk.label_new("")
call gtk.label_set_justify(label, 2)
call gtk.label_set_ellipsize(label, gtk.ELLIPSIZE_END)
call gtk.box_pack_end(vbox, label, True, True, 0)
S["win"] = win
S["vbox"] = vbox
S["label"] = label
call wm.connect(on_wm_event)
call wm.subscribe(["cycle"])
call gtk.main()
