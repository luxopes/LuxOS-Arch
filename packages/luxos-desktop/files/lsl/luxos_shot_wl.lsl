# LuxOS Snimek obrazovky na Waylandu (1.1.0): cestu bere luxos-screenshot-ui, kdyz GDK bezi na Waylandu.
# Zadne volani X11: obraz jde pres ext-image-copy-capture (luxos_wl), schranka pres ext-data-control.
#
#   shot_wl.main(argv)    jeden pozadavek (prepinace luxos-screenshot), vraci kod ukonceni
#
# --screen ulozi vsechny vystupy jako jeden obrazek podle rozlozeni (jako korenove okno na X11), --region
# jeho vyrez. --portion a --window: nejdriv zmrazeny snimek vsech vystupu, nad nim plochy layer-shell
# OVERLAY (jedna na vystup, klavesnice jen pro ne): tazenim vyrez, mezernik prepne na vyber okna, Esc
# zrusi, prave tlacitko taky. LuxWM poskytne ramy oken pres IPC pro prime oznaceni a zachyceni okna.
# Bez teto podpory zustava seznam a ext-foreign-toplevel-image-capture-source.
# Ctrl pri dokonceni vyberu nebo --clipboard = obrazek do schranky; proces ho drzi, dokud schranku
# neprevezme nekdo jiny.
#
# Zkratky dava luxwm.conf (exec luxos-screenshot ...), program zadne klavesy globalne nezabira. Snimek,
# seznam oken i schranka jsou privilegovane: skutecny program (/usr/lib/luxos/luxos-screenshot-ui) musi
# byt v /usr/share/luxwm/privileged.conf. GTK lista sdili styl a ikony s X11, vcetne popisku, voleb
# a upravitelneho vyrezu. Rychle zkratky zobrazuji jen vyber. Nahravani zatim neni dostupne.
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_sys
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_wl as wl
load luxos_shot_base as base
load luxos_shot as shot
load luxos_text as text
load luxos_luxwm as wm
load luxos_gio, gio as gio

SIGINT = 2
SIGTERM = 15
KEY_ESCAPE = 65307
KEY_RETURN = 65293
KEY_KP_ENTER = 65421
KEY_SPACE = 32
KEY_UP = 65362
KEY_DOWN = 65364
ACCENT = [0.24, 0.48, 1.0]
CAPTURE_MS = 5000
CHOOSER_W = 440
ROW = 34
MAX_ROWS = 14
# Widgety pouzivaji stejne CSS, ikony a rozmery jako X11 varianta.
W = {}
TB = {"hovered": "", "ctrl": False}
TH = {"open": False, "full": 0, "small": 0, "path": "", "copied": False, "video": False, "menu": False, "dragging": False, "timer": 0}

S = {"args": None, "opts": None, "code": 0, "frames": [], "mode": "portion", "window_capture": 0,
     "holding": False, "running": False, "finished": False, "listen": -1, "listen_source": 0, "token": 0,
     "to_clip": False, "toolbar": False, "busy": False, "provider": 0, "menu": 0, "active": True}
OV = {"wins": [], "sel": None, "drag": None, "windows": [], "hover": -1, "pick": 0, "shown": False, "boxes": [], "spatial": False}

function T(value):
    return i18n.T(value)
end

# ---- zmrazeny snimek vystupu --------------------------------------------------------------------------------

# Logicka plocha vystupu v rozlozeni; sirka a vyska z wl_output jsou pixely rezimu
function logical(output):
    g = wl.output_geometry(output)
    scale = max(1, wl.output_scale(output))
    return [g[0], g[1], g[2] // scale, g[3] // scale]
end

function capture_outputs():
    for output in wl.outputs():
        c = wl.capture_output(output, S["opts"]["pointer"])
        if c == 0:
            return False
        end
        S["frames"].append({"output": output, "geo": logical(output), "capture": c, "img": 0, "w": 0, "h": 0})
    end
    return len(S["frames"]) > 0
end

function frame_scale(frame):
    return Float(frame["w"]) / Float(max(1, frame["geo"][2]))
end

function bounds():
    x0 = 0
    y0 = 0
    x1 = 0
    y1 = 0
    first = True
    for f in S["frames"]:
        g = f["geo"]
        if first or g[0] < x0:
            x0 = g[0]
        end
        if first or g[1] < y0:
            y0 = g[1]
        end
        if first or g[0] + g[2] > x1:
            x1 = g[0] + g[2]
        end
        if first or g[1] + g[3] > y1:
            y1 = g[1] + g[3]
        end
        first = False
    end
    return [x0, y0, x1 - x0, y1 - y0]
end

# Obrazek vyrezu rect (logicke souradnice rozlozeni, None = vse) ze zmrazenych vystupu v pixelech
# nejjemnejsiho vystupu; 0 kdyz vyrez nic nepokryva
function compose(rect):
    b = bounds()
    r = b
    if rect != None:
        r = base.clamp_rect([rect[0] - b[0], rect[1] - b[1], rect[2], rect[3]], b[2], b[3])
        if r == None:
            return 0
        end
        r = [r[0] + b[0], r[1] + b[1], r[2], r[3]]
    end
    scale = 1.0
    for f in S["frames"]:
        scale = max(scale, frame_scale(f))
    end
    out = cairo.image_surface_create(cairo.FORMAT_ARGB32, Int(r[2] * scale + 0.5), Int(r[3] * scale + 0.5))
    cr = cairo.create(out)
    for f in S["frames"]:
        g = f["geo"]
        call cairo.save(cr)
        call cairo.translate(cr, (g[0] - r[0]) * scale, (g[1] - r[1]) * scale)
        call cairo.scale(cr, scale / frame_scale(f), scale / frame_scale(f))
        call cairo.set_source_surface(cr, f["img"], 0, 0)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    call cairo.destroy(cr)
    return out
end

function free_frames():
    for f in S["frames"]:
        if f["img"] != 0:
            call cairo.surface_destroy(f["img"])
            f["img"] = 0
        end
        if f["capture"] != 0:
            call wl.capture_free(f["capture"])
        end
    end
    S["frames"] = []
    return 0
end

# ---- udalosti Waylandu --------------------------------------------------------------------------------------

function frame_of(capture):
    for f in S["frames"]:
        if f["capture"] == capture:
            return f
        end
    end
    return None
end

function on_event(kind, handle, a, b):
    if kind == wl.CAPTURE_READY:
        if handle == S["window_capture"]:
            S["window_capture"] = 0
            img = wl.capture_surface(handle, a, b)
            call wl.capture_free(handle)
            call deliver(img)
            return 0
        end
        f = frame_of(handle)
        if f == None:
            return 0
        end
        f["img"] = wl.capture_surface(handle, a, b)
        f["w"] = a
        f["h"] = b
        call wl.capture_free(handle)
        f["capture"] = 0
        if f["img"] == 0:
            call failed("unsupported pixel format")
            return 0
        end
        for other in S["frames"]:
            if other["img"] == 0:
                return 0
            end
        end
        call frozen()
    elif kind == wl.CAPTURE_FAILED:
        if handle == S["window_capture"] or frame_of(handle) != None:
            call failed("capture failed (" + String(a) + ")")
        end
    elif kind == wl.CLIPBOARD_CANCELLED:
        # schranku prevzal jiny program: obrazek uz drzet netreba
        if S["holding"]:
            S["holding"] = False
            call quit()
        end
    elif kind == wl.DISCONNECTED:
        S["holding"] = False
        S["code"] = 1
        call quit()
    end
    return 0
end

function capture_timeout(token):
    if token == S["token"] and not S["finished"] and (S["window_capture"] != 0 or S["busy"] or not OV["shown"]):
        call failed("no answer from the compositor")
    end
    return False
end

# Vsechny vystupy zachyceny: hned ulozit (cela obrazovka, --region), jinak vyber nad zmrazenym snimkem
function frozen():
    S["token"] = S["token"] + 1
    if S["busy"]:
        call deliver(compose(S["capture_rect"]))
        return 0
    end
    a = S["args"]
    if a["action"] == "screen" or a["region"] != None:
        call deliver(compose(a["region"]))
        return 0
    end
    mode = "portion"
    if a["action"] == "window":
        mode = "window"
    end
    if S["toolbar"]:
        mode = S["opts"]["mode"]
        if mode.startswith("rec_"):
            mode = "portion"
        end
    end
    call ov_open(mode)
    if S["toolbar"]:
        call show_toolbar()
    end
    return 0
end

# ---- prekryv ------------------------------------------------------------------------------------------------

function monitor_for(geo):
    screens = layer.monitors()
    for m in screens:
        g = layer.monitor_geometry(m)
        if g[0] == geo[0] and g[1] == geo[1]:
            return m
        end
    end
    return 0
end

# LuxWM poskytuje ramy oken pres privilegovane IPC. Jine kompozitory zustavaji u seznamu.
function wm_event(event):
    return 0
end

function windows_reply(reply):
    if S["finished"] or type(reply) != "Dictionary" or not reply.get("ok", False):
        return 0
    end
    boxes = []
    spatial = True
    for item in reply.get("windows", []):
        if "frame" not in item:
            spatial = False
            break
        end
        r = item["frame"]
        if not item.get("minimized", False) and len(r) == 4 and r[2] > 0 and r[3] > 0:
            boxes.append(r)
            call shot.tlog("window-box " + json.encode([item.get("title", ""), r]))
        end
    end
    OV["boxes"] = boxes
    OV["spatial"] = spatial
    call shot.tlog("spatial " + String(spatial))
    call redraw()
    return 0
end

function window_at(px, py):
    for index in range(len(OV["boxes"])):
        r = OV["boxes"][index]
        if px >= r[0] and px < r[0] + r[2] and py >= r[1] and py < r[1] + r[3]:
            return index
        end
    end
    return -1
end

function pick_spatial(index, ctrl):
    if index < 0 or index >= len(OV["boxes"]):
        return 0
    end
    call begin_capture(OV["boxes"][index], ctrl)
    return 0
end

function reset(mode):
    S["mode"] = mode
    OV["sel"] = None
    OV["drag"] = None
    OV["hover"] = -1
    OV["pick"] = 0
    OV["windows"] = []
    if mode == "window":
        call load_windows()
    elif mode == "portion" and S["toolbar"]:
        b = bounds()
        sel = S["opts"]["selection"]
        if S["opts"]["remember"] and sel != None:
            r = base.clamp_rect([sel[0] - b[0], sel[1] - b[1], sel[2], sel[3]], b[2], b[3])
            if r != None:
                OV["sel"] = [r[0] + b[0], r[1] + b[1], r[2], r[3]]
            end
        end
        if OV["sel"] == None:
            OV["sel"] = [b[0] + b[2] // 4, b[1] + b[3] // 4, b[2] // 2, b[3] // 2]
        end
    end
    return 0
end

function ov_open(mode):
    call reset(mode)
    for f in S["frames"]:
        win = gtk.window_new("luxos-screenshot")
        call layer.init_for_window(win)
        call layer.set_namespace(win, "luxos-screenshot")
        call layer.set_layer(win, layer.LAYER_OVERLAY)
        call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_BOTTOM, layer.EDGE_LEFT, layer.EDGE_RIGHT])
        call layer.set_exclusive_zone(win, -1)
        call layer.set_keyboard_mode(win, layer.KEYBOARD_EXCLUSIVE)
        m = monitor_for(f["geo"])
        if m != 0:
            call layer.set_monitor(win, m)
        end
        call gtk.widget_set_app_paintable(win, True)
        call gtk.widget_set_rgba_visual(win)
        call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK + gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK)
        call gtk.connect_data(win, "draw", 1, on_draw, f)
        call gtk.connect_data(win, "button-press-event", 1, on_press, f)
        call gtk.connect_data(win, "button-release-event", 1, on_release, f)
        call gtk.connect_data(win, "motion-notify-event", 1, on_motion, f)
        call gtk.connect_data(win, "key-press-event", 1, on_key, f)
        call gtk.connect_data(win, "key-release-event", 1, on_key_release, 0)
        call gtk.widget_show_all(win)
        call gtk.widget_set_cursor(win, cursor_name())
        f["win"] = win
        OV["wins"].append(win)
    end
    return 0
end

function ov_close():
    for key in ["toolbar", "caption", "countdown", "options_menu", "dialog"]:
        if key in W and W[key] != 0:
            call gtk.widget_hide(W[key])
        end
    end
    for win in OV["wins"]:
        call gtk.widget_destroy(win)
    end
    OV["wins"] = []
    return 0
end

function cursor_name():
    if S["mode"] == "portion":
        return "crosshair"
    end
    return "default"
end

function set_mode(mode):
    call reset(mode)
    S["opts"]["mode"] = mode
    call save_options()
    call toolbar_sync()
    for win in OV["wins"]:
        call gtk.widget_set_cursor(win, cursor_name())
    end
    call redraw()
    call shot.tlog("overlay " + mode + " windows=" + String(len(OV["windows"])))
    return 0
end

function redraw():
    for win in OV["wins"]:
        call gtk.widget_queue_draw(win)
    end
    return 0
end

function load_windows():
    for t in wl.list_toplevels():
        call shot.tlog("row " + String(len(OV["windows"])) + " " + wl.toplevel_app_id(t) + "|" + wl.toplevel_title(t))
        OV["windows"].append(t)
        if len(OV["windows"]) == MAX_ROWS:
            break
        end
    end
    return 0
end

function window_label(t):
    title = wl.toplevel_title(t)
    app = wl.toplevel_app_id(t)
    if title == "":
        title = app
    elif app != "" and app != title:
        title = title + " — " + app
    end
    if len(title) > 56:
        title = title[0:55] + "…"
    end
    return title
end

function is_first(f):
    return f["output"] == S["frames"][0]["output"]
end

# Vyber okna je uprostred prvniho vystupu: [x, y, w, h] v souradnicich jeho plochy
function chooser_rect(f):
    g = f["geo"]
    rows = max(1, len(OV["windows"]))
    h = 48 + rows * ROW + 10
    w = min(CHOOSER_W, g[2] - 32)
    return [(g[2] - w) // 2, (g[3] - h) // 2, w, h]
end

function chooser_row(f, px, py):
    if not is_first(f) or len(OV["windows"]) == 0:
        return -1
    end
    r = chooser_rect(f)
    if px < r[0] or px >= r[0] + r[2]:
        return -1
    end
    row = Int(py - r[1] - 48) // ROW
    if py < r[1] + 48 or row >= len(OV["windows"]):
        return -1
    end
    return row
end

function label_at(cr, text, x, y, size, bold):
    weight = cairo.FONT_WEIGHT_NORMAL
    if bold:
        weight = cairo.FONT_WEIGHT_BOLD
    end
    call cairo.select_font_face(cr, "Inter", cairo.FONT_SLANT_NORMAL, weight)
    call cairo.set_font_size(cr, size)
    call cairo.move_to(cr, x, y)
    call cairo.show_text(cr, text)
    return 0
end

# ---- stejna GTK lista jako na X11, umistena pomoci layer-shell -----------------------------------------------

function popup_new(radius):
    win = gtk.window_new("luxos-screenshot")
    call layer.init_for_window(win)
    call layer.set_namespace(win, "luxos-screenshot")
    call layer.set_layer(win, layer.LAYER_OVERLAY)
    call layer.set_exclusive_zone(win, -1)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
    call gtk.widget_add_class(win, "lx-shot")
    call gtk.widget_set_app_paintable(win, True)
    call gtk.widget_set_rgba_visual(win)
    return win
end

function theme_changed(bound, pspec, settings):
    call gtk.css_set(S["provider"], shot.colors(shot.is_dark(), False) + shot.CSS)
    return 0
end

function build_ui():
    if S["provider"] != 0:
        return 0
    end
    S["provider"] = gtk.css_load(shot.colors(shot.is_dark(), False) + shot.CSS)
    settings = gtk.settings_get_default()
    call gtk.connect_data(settings, "notify::gtk-theme-name", 1, theme_changed, 0)
    call gtk.connect_data(settings, "notify::gtk-application-prefer-dark-theme", 1, theme_changed, 0)
    call build_caption()
    call build_toolbar()
    call build_options_menu()
    call build_thumb()
    call layer.set_keyboard_mode(W["thumb"], layer.KEYBOARD_ON_DEMAND)
    call gtk.connect_data(W["thumb"], "key-press-event", 1, on_thumb_key, 0)
    return 0
end

function build_caption():
    win = popup_new(9)
    box = gtk.box_new(gtk.HORIZONTAL, 7)
    call gtk.widget_add_class(box, "caption")
    for key in ["name", "key", "hint"]:
        lab = gtk.label_new("")
        call gtk.widget_add_class(lab, key)
        call gtk.box_pack_start(box, lab, False, False, 0)
        W["cap_" + key] = lab
    end
    call gtk.container_add(win, box)
    call gtk.widget_show_all(box)
    W["caption"] = win
    return 0
end

function build_toolbar():
    win = popup_new(18)
    bar = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_add_class(bar, "bar")
    call gtk.container_add(win, bar)
    W["bar"] = bar
    close = tool_new(bar, "close", 22, 22)
    call gtk.widget_add_class(close, "close")
    call sep_new(bar)
    W["modes"] = {}
    for mode in ["screen", "window", "portion", "", "rec_screen", "rec_portion"]:
        if mode == "":
            call sep_new(bar)
            continue
        end
        W["modes"][mode] = tool_new(bar, mode, 40, 26)
    end
    call sep_new(bar)
    opt = gtk.button_new_empty()
    call gtk.widget_set_can_focus(opt, False)
    ob = gtk.box_new(gtk.HORIZONTAL, 3)
    call gtk.box_pack_start(ob, gtk.label_new(T("Options")), False, False, 0)
    call gtk.box_pack_start(ob, gtk.image_new_from_icon_name("pan-down-symbolic", gtk.ICON_MENU), False, False, 0)
    call gtk.container_add(opt, ob)
    call gtk.connect_data(opt, "clicked", 0, on_tool_clicked, "options")
    call gtk.box_pack_start(bar, opt, False, False, 0)
    call hoverable(opt, "options")
    W["options"] = opt
    cap_button = gtk.button_new(T("Capture"))
    call gtk.widget_set_can_focus(cap_button, False)
    call gtk.widget_add_class(cap_button, "capture")
    call gtk.connect_data(cap_button, "clicked", 0, on_tool_clicked, "capture")
    call gtk.box_pack_start(bar, cap_button, False, False, 0)
    call hoverable(cap_button, "capture")
    W["capture"] = cap_button
    call gtk.widget_add_events(win, gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK)
    call gtk.connect_data(win, "key-press-event", 1, on_key, None)
    call gtk.connect_data(win, "key-release-event", 1, on_key_release, 0)
    call gtk.widget_show_all(bar)
    W["toolbar"] = win
    return 0
end

function tool_new(bar, key, w, h):
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.container_add(button, shot.icon_new(key, w, h))
    call gtk.connect_data(button, "clicked", 0, on_tool_clicked, key)
    call gtk.box_pack_start(bar, button, False, False, 0)
    call hoverable(button, key)
    return button
end

function sep_new(bar):
    s = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(s, "sep")
    call gtk.box_pack_start(bar, s, False, False, 0)
    return s
end

function hoverable(button, key):
    names = {"close": "Close", "options": "Options", "capture": "Capture"}
    if key in names:
        call gtk.accessible_name(button, T(names[key]))
    else:
        call gtk.accessible_name(button, shot.mode_name(key))
    end
    call gtk.connect_data(button, "enter-notify-event", 1, on_hover_enter, key)
    call gtk.connect_data(button, "leave-notify-event", 1, on_hover_leave, key)
    return 0
end

function on_hover_enter(key, event, button):
    TB["hovered"] = key
    call update_caption()
    return False
end

function on_hover_leave(key, event, button):
    TB["hovered"] = ""
    call update_caption()
    return False
end

function build_options_menu():
    menu = gtk.menu_new()
    W["opt_radio"] = []
    call menu_header(menu, T("Save to"))
    group = 0
    for pair in [["screenshots", "Screenshots"], ["desktop", "Desktop"], ["pictures", "Pictures"], ["clipboard", "Clipboard"]]:
        group = menu_radio(menu, group, T(pair[1]), "save_to", pair[0])
    end
    # Napoveda pod Schrankou: kopie jednoho snimku bez zmeny volby
    hint = gtk.menu_item_markup("<small>" + glib.markup_escape(T("Hold Ctrl to copy to the clipboard")) + "</small>")
    call gtk.widget_set_sensitive(hint, False)
    call gtk.menu_append(menu, hint)
    W["opt_other_radio"] = menu_radio(menu, group, "", "save_to", "other")
    other = gtk.menu_item_new(T("Other…"))
    call gtk.connect_data(other, "activate", 0, on_other_folder, 0)
    call gtk.menu_append(menu, other)
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    call menu_header(menu, T("Timer"))
    group = 0
    for pair in [[0, "None"], [5, "5 Seconds"], [10, "10 Seconds"]]:
        group = menu_radio(menu, group, T(pair[1]), "timer", pair[0])
    end
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    call menu_header(menu, T("Options"))
    W["opt_checks"] = []
    for pair in [["pointer", "Show Mouse Pointer"], ["remember", "Remember Last Selection"]]:
        item = gtk.check_menu_item_new(T(pair[1]))
        call gtk.connect_data(item, "toggled", 0, on_opt_check, pair[0])
        call gtk.menu_append(menu, item)
        W["opt_checks"].append([item, pair[0]])
    end
    call gtk.widget_show_all(menu)
    call gtk.menu_attach(menu, W["options"])
    call gtk.connect_data(menu, "hide", 0, on_options_hidden, 0)
    W["options_menu"] = menu
    return 0
end

function menu_header(menu, label):
    item = gtk.menu_item_new(label)
    call gtk.widget_set_sensitive(item, False)
    call gtk.menu_append(menu, item)
    return item
end

function menu_radio(menu, group, label, key, value):
    item = gtk.radio_menu_item_new(group, label)
    call gtk.connect_data(item, "toggled", 0, on_opt_radio, [key, value])
    call gtk.menu_append(menu, item)
    W["opt_radio"].append([item, key, value])
    return item
end

function options_popup():
    o = S["opts"]
    S["menu_sync"] = True
    for entry in W["opt_radio"]:
        call gtk.check_menu_item_set_active(entry[0], o[entry[1]] == entry[2])
    end
    for entry in W["opt_checks"]:
        call gtk.check_menu_item_set_active(entry[0], o[entry[1]])
    end
    other = W["opt_other_radio"]
    if o["other_dir"] != "":
        name = base.basename(text.rstrip_chars(o["other_dir"], "/"))
        if name == "":
            name = o["other_dir"]
        end
        call gtk.menu_item_set_label(other, name)
        call gtk.widget_show(other)
    else:
        call gtk.widget_hide(other)
    end
    S["menu_sync"] = False
    S["menu"] = W["options_menu"]
    call gtk.menu_popup_above(W["options_menu"], W["options"])
    return 0
end

function on_opt_radio(pair, item):
    if S.get("menu_sync", False) or not S["active"]:
        return 0
    end
    if gtk.check_menu_item_get_active(item):
        call set_opt(pair[0], pair[1])
    end
    return 0
end

function on_opt_check(key, item):
    if S.get("menu_sync", False) or not S["active"]:
        return 0
    end
    call set_opt(key, gtk.check_menu_item_get_active(item))
    return 0
end

function on_tool_clicked(key, button):
    if S["busy"] or S["finished"]:
        return 0
    end
    if key == "close":
        call finish(0)
    elif key == "options":
        call options_popup()
    elif key == "capture":
        call capture_now(TB["ctrl"])
    else:
        call set_mode(key)
    end
    return 0
end

function on_options_hidden(bound, menu):
    S["menu"] = 0
    return 0
end

function save_options():
    return base.save_options(S["opts"], base.options_path())
end

function set_opt(key, value):
    S["opts"][key] = value
    call save_options()
    call update_caption()
    return 0
end

function on_other_folder(bound, item):
    call glib.idle_add_data(choose_folder, 0)
    return 0
end

function choose_folder(bound):
    call ui_visible(False)
    dlg = gtk.file_chooser_new(T("Choose a Folder"), gtk.FILE_CHOOSER_SELECT_FOLDER)
    call gtk.dialog_add_button(dlg, T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(dlg, T("Choose"), gtk.RESPONSE_OK)
    if S["opts"]["other_dir"] != "":
        call gtk.file_chooser_set_folder(dlg, S["opts"]["other_dir"])
    end
    call gtk.connect_data(dlg, "response", 1, folder_response, 0)
    W["dialog"] = dlg
    call gtk.widget_show(dlg)
    return False
end

function folder_response(bound, response, dlg):
    if gtk.s32(response) == gtk.RESPONSE_OK:
        S["opts"]["other_dir"] = gtk.file_chooser_get_filename(dlg)
        call set_opt("save_to", "other")
    end
    call gtk.widget_destroy(dlg)
    W["dialog"] = 0
    if not S["finished"]:
        call ui_visible(True)
    end
    return 0
end

function ui_visible(visible):
    for win in OV["wins"]:
        call gtk.widget_set_visible(win, visible)
    end
    if S["toolbar"]:
        for key in ["toolbar", "caption"]:
            call gtk.widget_set_visible(W[key], visible)
        end
    end
    return 0
end

function update_caption():
    if not S["toolbar"] or "caption" not in W:
        return 0
    end
    key = TB["hovered"]
    if key == "":
        key = S["mode"]
    end
    name = ""
    accel = ""
    hint = ""
    if key == "close":
        name = T("Close")
        accel = "Esc"
    elif key == "options":
        names = {"screenshots": "Screenshots", "desktop": "Desktop", "pictures": "Pictures", "clipboard": "Clipboard", "other": "Other…"}
        name = i18n.TF("Save to: %s", [T(names[S["opts"]["save_to"]])])
    elif key.startswith("rec_"):
        name = shot.mode_name(key)
        hint = T("Screen recording is not available on Wayland yet.")
    else:
        if key == "capture":
            key = S["mode"]
            accel = "Enter"
            hint = T("Hold Ctrl to copy to the clipboard")
        end
        name = shot.mode_name(key)
        if key == "window":
            hint = T("Click a window to capture it")
        end
    end
    call gtk.label_set_text(W["cap_name"], name)
    call gtk.label_set_text(W["cap_key"], accel)
    call gtk.label_set_text(W["cap_hint"], hint)
    call gtk.widget_set_visible(W["cap_key"], accel != "")
    call gtk.widget_set_visible(W["cap_hint"], hint != "")
    call gtk.window_resize(W["caption"], 1, 1)
    return 0
end

function toolbar_sync():
    if not S["toolbar"]:
        return 0
    end
    for mode in W["modes"].keys():
        call gtk.widget_set_class(W["modes"][mode], "active", mode == S["mode"])
        # Zachovat rozlozeni X11; backend videa zatim neni implementovan.
        call gtk.widget_set_sensitive(W["modes"][mode], not mode.startswith("rec_"))
        if mode.startswith("rec_"):
            call gtk.widget_set_tooltip(W["modes"][mode], T("Screen recording is not available on Wayland yet."))
        end
    end
    call gtk.widget_set_sensitive(W["capture"], S["mode"] != "window" and not S["busy"])
    label = T("Capture")
    if TB["ctrl"]:
        label = T("Copy")
    end
    call gtk.button_set_label(W["capture"], label)
    call update_caption()
    return 0
end

function show_toolbar():
    call build_ui()
    f = S["frames"][0]
    m = monitor_for(f["geo"])
    margin = max(90, f["geo"][3] // 10)
    for key in ["toolbar", "caption"]:
        if m != 0:
            call layer.set_monitor(W[key], m)
        end
        call layer.set_anchors(W[key], [layer.EDGE_BOTTOM])
    end
    size = shot.preferred_size(W["toolbar"])
    call layer.set_margin(W["toolbar"], layer.EDGE_BOTTOM, margin)
    call layer.set_margin(W["caption"], layer.EDGE_BOTTOM, margin + size[1] + 6)
    call toolbar_sync()
    call gtk.widget_show(W["toolbar"])
    call gtk.widget_show(W["caption"])
    call shot.tlog("toolbar " + String((f["geo"][2] - size[0]) // 2) + " " + String(f["geo"][3] - margin - size[1]) + " " + String(size[0]) + " " + String(size[1]))
    return 0
end

function on_key_release(bound, event, win):
    key = gtk.event_key_keyval(event)
    if key == 65507 or key == 65508:
        TB["ctrl"] = False
        call toolbar_sync()
    end
    return False
end

# Lista potvrzuje vyber az tlacitkem/Enter; rychla zkratka stale zachyti pri pusteni mysi.
function capture_now(ctrl):
    if S["busy"] or S["finished"]:
        return 0
    end
    S["to_clip"] = ctrl
    if S["mode"] == "window":
        if OV["spatial"]:
            call pick_spatial(OV["pick"], ctrl)
            return 0
        end
        if len(OV["windows"]) > 0:
            call pick_window(OV["pick"], ctrl)
        end
        return 0
    end
    rect = None
    if S["mode"] == "portion":
        rect = norm_sel()
        if rect == None or rect[2] < 3 or rect[3] < 3:
            return 0
        end
        if S["opts"]["remember"]:
            S["opts"]["selection"] = rect
            call save_options()
        end
    end
    call begin_capture(rect, ctrl)
    return 0
end

function begin_capture(rect, ctrl):
    S["to_clip"] = ctrl
    if not S["toolbar"]:
        call deliver(compose(rect))
        return 0
    end
    S["busy"] = True
    S["capture_rect"] = rect
    S["count"] = S["opts"]["timer"]
    call ui_visible(False)
    call free_frames()
    if S["count"] > 0:
        call countdown_tick(0)
    else:
        call glib.timeout_add_data(base.HIDE_DELAY, capture_fresh, 0)
    end
    return 0
end

function countdown_tick(bound):
    if S["finished"]:
        return False
    end
    if S["count"] <= 0:
        call gtk.widget_hide(W["countdown"])
        call glib.timeout_add_data(base.HIDE_DELAY, capture_fresh, 0)
        return False
    end
    if "countdown" not in W:
        win = popup_new(22)
        box = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(box, "count")
        W["count_label"] = gtk.label_new("")
        call gtk.container_add(box, W["count_label"])
        call gtk.container_add(win, box)
        call gtk.widget_show_all(box)
        W["countdown"] = win
        call layer.set_keyboard_mode(win, layer.KEYBOARD_EXCLUSIVE)
        call gtk.connect_data(win, "key-press-event", 1, on_key, None)
    end
    call shot.tlog("countdown " + String(S["count"]))
    call gtk.label_set_text(W["count_label"], String(S["count"]))
    call gtk.widget_show(W["countdown"])
    S["count"] = S["count"] - 1
    call glib.timeout_add_data(1000, countdown_tick, 0)
    return False
end

function capture_fresh(bound):
    if S["finished"]:
        return False
    end
    S["token"] = S["token"] + 1
    if not capture_outputs():
        call failed("no output to capture")
    else:
        call glib.timeout_add_data(CAPTURE_MS, capture_timeout, S["token"])
    end
    return False
end

function draw_chooser(cr, f):
    r = chooser_rect(f)
    x = Float(r[0])
    y = Float(r[1])
    call cairo.rounded_rectangle(cr, x, y, r[2], r[3], 14.0)
    call cairo.set_source_rgba(cr, 0.125, 0.13, 0.2, 0.94)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    call label_at(cr, T("Choose a window to capture"), x + 16.0, y + 30.0, 14.0, True)
    if len(OV["windows"]) == 0:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.7)
        call label_at(cr, T("No windows"), x + 16.0, y + 48.0 + 22.0, 13.0, False)
        return 0
    end
    index = 0
    while index < len(OV["windows"]):
        ry = y + 48.0 + index * ROW
        if index == OV["hover"] or (OV["hover"] < 0 and index == OV["pick"]):
            call cairo.rounded_rectangle(cr, x + 8.0, ry, r[2] - 16.0, ROW - 2.0, 8.0)
            call cairo.set_source_rgba(cr, ACCENT[0], ACCENT[1], ACCENT[2], 0.55)
            call cairo.fill(cr)
        end
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
        call label_at(cr, window_label(OV["windows"][index]), x + 18.0, ry + 21.0, 13.0, False)
        index += 1
    end
    return 0
end

function draw_selection(cr, f, w, h):
    g = f["geo"]
    call gtk.cairo_set_fill_rule(cr, 1)
    call cairo.rectangle(cr, 0, 0, w, h)
    sel = norm_sel()
    if sel != None:
        call cairo.rectangle(cr, sel[0] - g[0], sel[1] - g[1], sel[2], sel[3])
    end
    shade = 0.38
    if S["toolbar"]:
        shade = 0.22
    end
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, shade)
    call cairo.fill(cr)
    if sel == None:
        return 0
    end
    x = Float(sel[0] - g[0])
    y = Float(sel[1] - g[1])
    call cairo.set_line_width(cr, 1.0)
    call cairo.rectangle(cr, x + 0.5, y + 0.5, max(0.0, sel[2] - 1.0), max(0.0, sel[3] - 1.0))
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    call cairo.stroke(cr)
    if S["toolbar"]:
        for hd in shot.handles(sel):
            call cairo.new_path(cr)
            call cairo.arc(cr, hd[0] - g[0], hd[1] - g[1], 4.5, 0.0, 6.2832)
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
            call cairo.fill_preserve(cr)
            call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.35)
            call cairo.stroke(cr)
        end
    end
    label = String(sel[2]) + " × " + String(sel[3])
    call cairo.select_font_face(cr, "Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    call cairo.set_font_size(cr, 12.0)
    ext = cairo.text_extents(cr, label)
    bw = ext[2] + 16.0
    bx = min(max(4.0, x + (sel[2] - bw) / 2.0), w - bw - 4.0)
    by = y + sel[3] + 10.0
    if by + 22.0 > h:
        by = max(4.0, y + sel[3] - 32.0)
    end
    call cairo.rounded_rectangle(cr, bx, by, bw, 22.0, 6.0)
    call cairo.set_source_rgba(cr, 0.1, 0.1, 0.14, 0.82)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
    call cairo.move_to(cr, bx + 8.0 - ext[0], by + 11.0 - ext[1] - ext[3] / 2.0)
    call cairo.show_text(cr, label)
    return 0
end

function on_draw(f, cr, win):
    w = gtk.widget_get_allocated_width(win)
    h = gtk.widget_get_allocated_height(win)
    if S["toolbar"]:
        call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
        call cairo.paint(cr)
        call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    else:
        if f["img"] == 0:
            return True
        end
        call cairo.save(cr)
        call cairo.scale(cr, 1.0 / frame_scale(f), 1.0 / frame_scale(f))
        call cairo.set_source_surface(cr, f["img"], 0, 0)
        call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    if S["mode"] == "window" and OV["spatial"]:
        if OV["hover"] >= 0 and OV["hover"] < len(OV["boxes"]):
            r = OV["boxes"][OV["hover"]]
            call cairo.rectangle(cr, r[0] - f["geo"][0], r[1] - f["geo"][1], r[2], r[3])
            call cairo.set_source_rgba(cr, ACCENT[0], ACCENT[1], ACCENT[2], 0.28)
            call cairo.fill(cr)
        end
    elif S["mode"] == "window":
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
        call cairo.paint(cr)
        if is_first(f):
            call draw_chooser(cr, f)
        end
    elif S["mode"] != "screen":
        call draw_selection(cr, f, w, h)
    end
    if not OV["shown"] and is_first(f):
        OV["shown"] = True
        call shot.tlog("overlay " + S["mode"] + " windows=" + String(len(OV["windows"])) + " size=" + String(w) + "x" + String(h))
    end
    return True
end

function norm_sel():
    sel = OV["sel"]
    if sel == None:
        return None
    end
    x = sel[0]
    y = sel[1]
    w = sel[2]
    h = sel[3]
    if w < 0:
        x = x + w
        w = -w
    end
    if h < 0:
        y = y + h
        h = -h
    end
    b = bounds()
    r = base.clamp_rect([x - b[0], y - b[1], w, h], b[2], b[3])
    if r == None:
        return None
    end
    return [r[0] + b[0], r[1] + b[1], r[2], r[3]]
end

function on_press(f, event, win):
    if S["finished"] or S["busy"]:
        return True
    end
    button = gtk.event_button(event)
    if button == 3:
        call finish(0)
        return True
    end
    if button != 1:
        return True
    end
    px = Int(gtk.event_x(event))
    py = Int(gtk.event_y(event))
    if S["mode"] == "window":
        if OV["spatial"]:
            call pick_spatial(window_at(f["geo"][0] + px, f["geo"][1] + py), gtk.event_button_state(event) & gtk.CONTROL_MASK != 0)
            return True
        end
        row = chooser_row(f, px, py)
        if row >= 0:
            call pick_window(row, gtk.event_button_state(event) & gtk.CONTROL_MASK != 0)
        end
        return True
    end
    if S["mode"] == "screen":
        return True
    end
    gx = f["geo"][0] + px
    gy = f["geo"][1] + py
    kind = ""
    r = norm_sel()
    if S["toolbar"] and r != None:
        for hd in shot.handles(r):
            if abs(gx - hd[0]) <= shot.HANDLE and abs(gy - hd[1]) <= shot.HANDLE:
                kind = hd[2]
                break
            end
        end
        if kind == "" and gx >= r[0] and gx < r[0] + r[2] and gy >= r[1] and gy < r[1] + r[3]:
            kind = "move"
        end
    end
    OV["drag_kind"] = kind
    OV["drag_rect"] = r
    OV["drag"] = [gx, gy]
    if kind != "":
        return True
    end
    OV["sel"] = [gx, gy, 0, 0]
    call redraw()
    return True
end

function drag_selection(gx, gy):
    if S["toolbar"] and OV.get("drag_kind", "") != "":
        r = OV["drag_rect"]
        b = bounds()
        dx = gx - OV["drag"][0]
        dy = gy - OV["drag"][1]
        kind = OV["drag_kind"]
        if kind == "move":
            OV["sel"] = [max(b[0], min(b[0] + b[2] - r[2], r[0] + dx)), max(b[1], min(b[1] + b[3] - r[3], r[1] + dy)), r[2], r[3]]
        else:
            x0 = r[0]
            y0 = r[1]
            x1 = x0 + r[2]
            y1 = y0 + r[3]
            if "w" in kind:
                x0 = max(b[0], min(x1 - 3, x0 + dx))
            elif "e" in kind:
                x1 = min(b[0] + b[2], max(x0 + 3, x1 + dx))
            end
            if "n" in kind:
                y0 = max(b[1], min(y1 - 3, y0 + dy))
            elif "s" in kind:
                y1 = min(b[1] + b[3], max(y0 + 3, y1 + dy))
            end
            OV["sel"] = [x0, y0, x1 - x0, y1 - y0]
        end
        return 0
    end
    OV["sel"] = [OV["drag"][0], OV["drag"][1], gx - OV["drag"][0], gy - OV["drag"][1]]
    return 0
end

function on_motion(f, event, win):
    px = Int(gtk.event_x(event))
    py = Int(gtk.event_y(event))
    if S["mode"] == "window":
        row = chooser_row(f, px, py)
        if OV["spatial"]:
            row = window_at(f["geo"][0] + px, f["geo"][1] + py)
        end
        if row != OV["hover"]:
            OV["hover"] = row
            call redraw()
        end
        return True
    end
    if OV["drag"] == None:
        return True
    end
    call drag_selection(f["geo"][0] + px, f["geo"][1] + py)
    call redraw()
    return True
end

function on_release(f, event, win):
    if gtk.event_button(event) != 1 or OV["drag"] == None or S["finished"]:
        return True
    end
    OV["drag"] = None
    sel = norm_sel()
    if sel == None or sel[2] < 3 or sel[3] < 3:
        OV["sel"] = None
        call redraw()
        return True
    end
    S["to_clip"] = gtk.event_button_state(event) & gtk.CONTROL_MASK != 0
    call shot.tlog("selected " + String(sel[0]) + " " + String(sel[1]) + " " + String(sel[2]) + " " + String(sel[3]))
    if S["toolbar"]:
        if S["opts"]["remember"]:
            S["opts"]["selection"] = sel
            call save_options()
        end
        call redraw()
    else:
        call deliver(compose(sel))
    end
    return True
end

function on_key(f, event, win):
    key = gtk.event_key_keyval(event)
    if S["menu"] != 0:
        return False
    end
    if key == KEY_ESCAPE:
        call finish(0)
    elif S["busy"]:
        return True
    elif key == 65507 or key == 65508:
        TB["ctrl"] = True
        call toolbar_sync()
    elif key == KEY_RETURN or key == KEY_KP_ENTER:
        call capture_now(gtk.event_key_state(event) & gtk.CONTROL_MASK != 0)
    elif key == 49 and OV["drag"] == None:
        call set_mode("screen")
    elif key == 50 and OV["drag"] == None:
        call set_mode("window")
    elif key == 51 and OV["drag"] == None:
        call set_mode("portion")
    elif key == KEY_SPACE and OV["drag"] == None:
        if S["mode"] == "window":
            call set_mode("portion")
        elif S["mode"] == "screen":
            call set_mode("portion")
        else:
            call set_mode("window")
        end
    elif S["mode"] == "window" and OV["spatial"]:
        if (key == KEY_DOWN or key == KEY_UP) and len(OV["boxes"]) > 0:
            step = 1
            if key == KEY_UP:
                step = -1
            end
            OV["pick"] = (OV["pick"] + step + len(OV["boxes"])) % len(OV["boxes"])
            OV["hover"] = OV["pick"]
            call redraw()
        end
    elif S["mode"] == "window" and len(OV["windows"]) > 0:
        if key == KEY_DOWN or key == KEY_UP:
            step = 1
            if key == KEY_UP:
                step = -1
            end
            OV["pick"] = (OV["pick"] + step + len(OV["windows"])) % len(OV["windows"])
            OV["hover"] = -1
            call redraw()
        elif key == KEY_RETURN or key == KEY_KP_ENTER:
            call pick_window(OV["pick"], gtk.event_key_state(event) & gtk.CONTROL_MASK != 0)
        end
    end
    return True
end

function pick_window(row, ctrl):
    t = OV["windows"][row]
    S["to_clip"] = ctrl
    call shot.tlog("window " + wl.toplevel_app_id(t) + "|" + wl.toplevel_title(t))
    call ov_close()
    if wl.has("ext_foreign_toplevel_image_capture_source_manager_v1") == 0:
        call failed("the compositor cannot capture single windows")
        return 0
    end
    S["window_capture"] = wl.capture_toplevel(t, S["opts"]["pointer"])
    if S["window_capture"] == 0:
        call failed("the window is gone")
        return 0
    end
    # vlastni lhuta (lhuta zmrazeneho snimku uz neplati)
    S["token"] = S["token"] + 1
    call glib.timeout_add_data(CAPTURE_MS, capture_timeout, S["token"])
    return 0
end

# ---- nahled: stejne rozlozeni a akce jako na X11 ------------------------------------------------------------

function build_thumb():
    win = popup_new(12)
    card = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(card, "thumb")
    img = gtk.drawing_area_new()
    call gtk.widget_set_valign(img, gtk.ALIGN_CENTER)
    call gtk.widget_add_events(img, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK)
    call gtk.connect_data(img, "draw", 1, on_thumb_draw, 0)
    call gtk.connect_data(img, "button-release-event", 1, on_thumb_click, 0)
    call gtk.connect_data(img, "drag-data-get", 4, on_drag_get, 0)
    call gtk.connect_data(img, "drag-begin", 1, on_drag_begin, 0)
    call gtk.connect_data(img, "drag-end", 1, on_drag_end, 0)
    call gtk.box_pack_start(card, img, False, False, 0)
    W["thumb_image"] = img
    col = gtk.box_new(gtk.VERTICAL, 1)
    call gtk.widget_set_valign(col, gtk.ALIGN_CENTER)
    st = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_margins(st, 7, 0, 0, 3)
    call gtk.box_pack_start(st, gtk.image_new_from_icon_name("object-select-symbolic", gtk.ICON_MENU), False, False, 0)
    lab = gtk.label_new(T("Copied to Clipboard"))
    call gtk.label_set_xalign(lab, 0)
    call gtk.widget_add_class(lab, "status")
    call gtk.box_pack_start(st, lab, False, False, 0)
    call gtk.box_pack_start(col, st, False, False, 0)
    W["thumb_status"] = st
    W["thumb_buttons"] = {}
    for item in [["copy", "edit-copy-symbolic", "Copy"], ["reveal", "folder-open-symbolic", "Show in Files"], ["save_as", "document-save-as-symbolic", "Save As…"], ["delete", "user-trash-symbolic", "Delete"], ["close", "window-close-symbolic", "Close"]]:
        b = gtk.button_new_empty()
        call gtk.widget_set_can_focus(b, False)
        bx = gtk.box_new(gtk.HORIZONTAL, 7)
        image = gtk.image_new_from_icon_name(item[1], gtk.ICON_MENU)
        blab = gtk.label_new(T(item[2]))
        call gtk.label_set_xalign(blab, 0)
        call gtk.box_pack_start(bx, image, False, False, 0)
        call gtk.box_pack_start(bx, blab, True, True, 0)
        call gtk.container_add(b, bx)
        call gtk.connect_data(b, "clicked", 0, on_thumb_button, item[0])
        call gtk.box_pack_start(col, b, False, False, 0)
        W["thumb_buttons"][item[0]] = [b, image, blab]
    end
    call gtk.box_pack_start(card, col, False, False, 0)
    call gtk.container_add(win, card)
    call gtk.widget_show_all(card)
    call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.ENTER_NOTIFY_MASK + gtk.LEAVE_NOTIFY_MASK)
    call gtk.connect_data(win, "button-press-event", 1, on_thumb_press, 0)
    call gtk.connect_data(win, "enter-notify-event", 1, on_thumb_enter, 0)
    call gtk.connect_data(win, "leave-notify-event", 1, on_thumb_leave, 0)
    W["thumb"] = win
    # Nabidka praveho tlacitka
    menu = gtk.menu_new()
    W["thumb_items"] = {}
    for item in [["open", "Open"], ["copy", "Copy"], ["reveal", "Show in Files"], ["save_as", "Save As…"], ["delete", "Delete"], ["sep", ""], ["close", "Close"]]:
        if item[0] == "sep":
            mi = gtk.separator_menu_item_new()
        else:
            mi = gtk.menu_item_new(T(item[1]))
            call gtk.connect_data(mi, "activate", 0, on_thumb_menu_item, item[0])
        end
        call gtk.menu_append(menu, mi)
        call gtk.widget_show(mi)
        W["thumb_items"][item[0]] = mi
    end
    call gtk.menu_attach(menu, win)
    call gtk.connect_data(menu, "hide", 0, on_thumb_menu_hidden, 0)
    W["thumb_menu"] = menu
    return 0
end

function thumb_actions():
    acts = []
    if not TH["video"] and not TH["copied"]:
        acts.append("copy")
    end
    if TH["path"] != "":
        acts.append("reveal")
    end
    acts.append("save_as")
    if TH["path"] != "":
        acts.append("delete")
    end
    acts.append("close")
    return acts
end

function on_thumb_draw(bound, cr, area):
    if TH["small"] == 0:
        return False
    end
    w = Float(gtk.widget_get_allocated_width(area))
    h = Float(gtk.widget_get_allocated_height(area))
    pw = gtk.pixbuf_get_width(TH["small"])
    ph = gtk.pixbuf_get_height(TH["small"])
    call cairo.rounded_rectangle(cr, 0.0, 0.0, w, h, 7.0)
    call cairo.clip(cr)
    call gtk.cairo_set_source_pixbuf(cr, TH["small"], (w - pw) / 2.0, (h - ph) / 2.0)
    call cairo.paint(cr)
    call cairo.reset_clip(cr)
    call cairo.rounded_rectangle(cr, 0.5, 0.5, w - 1.0, h - 1.0, 7.0)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.16)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    return False
end

function on_drag_get(bound, context, selection, info, time, widget):
    if TH["path"] != "":
        call gtk.selection_set_uri(selection, glib.filename_to_uri(TH["path"]))
    elif TH["full"] != 0:
        call gtk.selection_set_pixbuf(selection, TH["full"])
    end
    return 0
end

function on_drag_begin(bound, context, widget):
    TH["dragging"] = True
    call thumb_stop_timer()
    return 0
end

function on_drag_end(bound, context, widget):
    if TH["open"]:
        call thumb_finish()
    end
    return 0
end

function on_thumb_click(bound, event, area):
    if gtk.event_button(event) == 1 and not TH["dragging"] and TH["open"]:
        if TH["path"] != "":
            call shot.open_uri(glib.filename_to_uri(TH["path"]))
            call thumb_finish()
        end
        return True
    end
    return False
end

function on_thumb_press(bound, event, win):
    if gtk.event_button(event) == 3 and TH["open"]:
        call thumb_menu_popup()
        return True
    end
    return False
end

function thumb_menu_popup():
    items = W["thumb_items"]
    acts = thumb_actions()
    call gtk.widget_set_visible(items["open"], TH["path"] != "")
    for key in ["copy", "reveal", "save_as", "delete", "close"]:
        call gtk.widget_set_visible(items[key], key in acts)
    end
    call thumb_stop_timer()
    TH["menu"] = True
    S["menu"] = W["thumb_menu"]
    call gtk.menu_popup_at_pointer(W["thumb_menu"])
    return 0
end

function on_thumb_menu_hidden(bound, menu):
    TH["menu"] = False
    if S["menu"] == W["thumb_menu"]:
        S["menu"] = 0
    end
    if TH["open"]:
        call thumb_start_timer()
    end
    return 0
end

function on_thumb_enter(bound, event, win):
    call thumb_stop_timer()
    return False
end

function on_thumb_leave(bound, event, win):
    # presun na tlacitko neni odchod
    if gtk.event_crossing_detail(event) != gtk.NOTIFY_INFERIOR and not TH["menu"]:
        call thumb_start_timer()
    end
    return False
end

function on_thumb_button(key, button):
    call thumb_act(key)
    return 0
end

function on_thumb_key(bound, event, win):
    if gtk.event_key_keyval(event) == KEY_ESCAPE:
        call thumb_finish()
        return True
    end
    return False
end

function on_thumb_menu_item(key, item):
    call glib.idle_add_data(thumb_act_idle, key)
    return 0
end

function thumb_act_idle(key):
    if TH["open"]:
        call thumb_act(key)
    end
    return False
end

function thumb_start_timer():
    TH["timer"] = TH["timer"] + 1
    if TH["open"]:
        call glib.timeout_add_data(base.THUMB_TIME, thumb_timeout, TH["timer"])
    end
    return 0
end

function thumb_stop_timer():
    TH["timer"] = TH["timer"] + 1
    return 0
end

function thumb_timeout(token):
    if TH["open"] and token == TH["timer"]:
        call thumb_finish()
    end
    return False
end

function show_thumb(img, path, copied):
    if S["args"]["no_thumb"]:
        return 0
    end
    pb = gtk.surface_to_pixbuf(img, cairo.image_surface_get_width(img), cairo.image_surface_get_height(img))
    if pb == 0:
        return 0
    end
    call build_ui()
    TH["full"] = pb
    TH["path"] = path
    TH["copied"] = copied
    TH["open"] = True
    w = gtk.pixbuf_get_width(pb)
    h = gtk.pixbuf_get_height(pb)
    scale = min(200.0 / w, 140.0 / h, 1.0)
    TH["small"] = gtk.pixbuf_scale(pb, Int(w * scale), Int(h * scale))
    call gtk.widget_set_size_request(W["thumb_image"], gtk.pixbuf_get_width(TH["small"]), gtk.pixbuf_get_height(TH["small"]))
    call gtk.widget_set_visible(W["thumb_status"], copied)
    acts = thumb_actions()
    for key in W["thumb_buttons"].keys():
        call gtk.widget_set_visible(W["thumb_buttons"][key][0], key in acts)
    end
    call gtk.drag_source_setup(W["thumb_image"], path != "", TH["small"])
    call layer.set_anchors(W["thumb"], [layer.EDGE_BOTTOM, layer.EDGE_RIGHT])
    call layer.set_margin(W["thumb"], layer.EDGE_RIGHT, 24)
    call layer.set_margin(W["thumb"], layer.EDGE_BOTTOM, 96)
    call gtk.widget_show(W["thumb"])
    call shot.tlog("thumb " + text.join(acts, ","))
    call thumb_start_timer()
    return 0
end

function thumb_finish():
    if not TH["open"]:
        return 0
    end
    TH["open"] = False
    call thumb_stop_timer()
    call gtk.menu_popdown(W["thumb_menu"])
    call gtk.widget_hide(W["thumb"])
    call gtk.object_unref(TH["small"])
    call gtk.object_unref(TH["full"])
    TH["small"] = 0
    TH["full"] = 0
    call quit()
    return 0
end

function copy_preview():
    tmp = base.runtime_dir() + "/.luxos-screenshot-clip-" + String(glib.getpid()) + ".png"
    ok = gtk.pixbuf_save_png(TH["full"], tmp) == "" and wl.clipboard_set_file("image/png", tmp)
    call luxos_sys.unlink(tmp)
    if ok:
        S["holding"] = True
    else:
        call shot.notify(T("The screenshot could not be copied to the clipboard."))
    end
    return ok
end

function thumb_act(key):
    if not TH["open"]:
        return 0
    end
    if key == "copy":
        if copy_preview():
            copy = W["thumb_buttons"]["copy"]
            call gtk.image_set_from_icon_name(copy[1], "object-select-symbolic", gtk.ICON_MENU)
            call gtk.label_set_text(copy[2], T("Copied"))
        end
        call thumb_start_timer()
    elif key == "open":
        call shot.open_uri(glib.filename_to_uri(TH["path"]))
        call thumb_finish()
    elif key == "reveal":
        call thumb_stop_timer()
        call gtk.widget_hide(W["thumb"])
        try:
            bus = gio.session_bus()
            call gio.call_async(bus, "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1", "ShowItems", [[glib.filename_to_uri(TH["path"])], ""], "(ass)", 8000, reveal_reply, TH["path"])
        else:
            call reveal_reply(TH["path"], None, "no session bus")
        end
    elif key == "delete":
        if shot.trash(TH["path"]):
            call thumb_finish()
        end
    elif key == "save_as":
        call thumb_stop_timer()
        call gtk.widget_hide(W["thumb"])
        dlg = gtk.file_chooser_new(T("Save Screenshot"), gtk.FILE_CHOOSER_SAVE)
        call gtk.dialog_add_button(dlg, T("Cancel"), gtk.RESPONSE_CANCEL)
        call gtk.dialog_add_button(dlg, T("Save"), gtk.RESPONSE_OK)
        call gtk.file_chooser_set_overwrite_confirm(dlg, True)
        name = base.basename(TH["path"])
        if name == "":
            name = base.file_name(shot.now_fields(), False)
        end
        call gtk.file_chooser_set_name(dlg, name)
        call gtk.connect_data(dlg, "response", 1, save_response, 0)
        W["dialog"] = dlg
        call gtk.widget_show(dlg)
    elif key == "close":
        call thumb_finish()
    end
    return 0
end

function reveal_reply(path, values, error):
    if error != "":
        call shot.open_uri(glib.filename_to_uri(base.dirname(path)))
    end
    call thumb_finish()
    return 0
end

function save_response(bound, response, dlg):
    if gtk.s32(response) == gtk.RESPONSE_OK:
        path = gtk.file_chooser_get_filename(dlg)
        err = shot.write_copy(TH["full"], TH["path"], path, False)
        if err != "":
            call shot.notify(T("The screenshot could not be saved.") + " " + err)
        end
    end
    call gtk.widget_destroy(dlg)
    W["dialog"] = 0
    if TH["open"]:
        call gtk.widget_show(W["thumb"])
        call thumb_start_timer()
    end
    return 0
end

# ---- vysledek -----------------------------------------------------------------------------------------------

function deliver(img):
    if img == 0:
        call failed("empty selection")
        return 0
    end
    a = S["args"]
    folder = None
    if not a["clipboard"]:
        folder = shot.save_dir(S["opts"], False, a["output"])
    end
    if S["to_clip"] or folder == None:
        tmp = base.runtime_dir() + "/.luxos-screenshot-clip-" + String(glib.getpid()) + ".png"
        ok = cairo.surface_write_to_png(img, tmp) == 0 and wl.clipboard_set_file("image/png", tmp)
        call luxos_sys.unlink(tmp)
        if not ok:
            call cairo.surface_destroy(img)
            call shot.notify(T("The screenshot could not be copied to the clipboard."))
            call finish(1)
            return 0
        end
        call shot.tlog("clipboard")
        S["holding"] = True
        call show_thumb(img, "", True)
        call cairo.surface_destroy(img)
        call finish(0)
        return 0
    end
    call luxos_sys.mkdir_p(folder)
    path = base.unique_path(folder, base.file_name(shot.now_fields(), False))
    status = cairo.surface_write_to_png(img, path)
    if status != 0:
        call cairo.surface_destroy(img)
        call shot.notify(T("The screenshot could not be saved.") + " " + path)
        call finish(1)
        return 0
    end
    call show_thumb(img, path, False)
    call cairo.surface_destroy(img)
    call shot.tlog("saved " + path)
    call luxos_sys.out(path + "\n")
    call finish(0)
    return 0
end

function failed(reason):
    call shot.log(reason)
    call shot.notify(T("The screenshot could not be taken."))
    call finish(1)
    return 0
end

# Konec relace; drzeny obrazek ve schrance nechava proces bezet do CLIPBOARD_CANCELLED
function finish(code):
    if S["finished"]:
        return 0
    end
    S["finished"] = True
    S["active"] = False
    S["code"] = code
    S["token"] = S["token"] + 1
    call ov_close()
    call free_frames()
    call shot.tlog("end " + String(code))
    call quit()
    return 0
end

function quit():
    if TH["open"]:
        return 0
    end
    # drzeni schranky neni vyber: dalsi spusteni uz patri novemu procesu
    if S["listen"] >= 0:
        call glib.source_remove(S["listen_source"])
        call luxos_sys.close(S["listen"])
        S["listen"] = -1
    end
    if S["holding"] or not S["running"]:
        return 0
    end
    S["running"] = False
    call gtk.main_quit()
    return 0
end

function on_signal():
    S["holding"] = False
    call thumb_finish()
    call finish(0)
    call quit()
    return True
end

# ---- dalsi spusteni (stejna zkratka zavre vyber) -------------------------------------------------------------

function on_listen(fd, handle, condition):
    while True:
        conn = luxos_sys.unix_accept(fd)
        if conn < 0:
            break
        end
        if luxos_sys.peer_uid(conn) == luxos_sys.getuid():
            call luxos_sys.send_text(conn, "ok\n")
            call luxos_sys.send_text(conn, "exit 0\n")
            call luxos_sys.close(conn)
            call thumb_finish()
            call finish(0)
            return False
        end
        call luxos_sys.close(conn)
    end
    return True
end

# ---- hlavni ------------------------------------------------------------------------------------------------

function main(argv):
    a = base.parse_args(argv, luxos_sys.cwd())
    if "error" in a:
        call eprint(a["error"])
        return 1
    end
    if a["close"] or a["stop"]:
        return 0
    end
    if a["action"].startswith("rec_"):
        call shot.notify(T("Screen recording is not available on Wayland yet."))
        return 1
    end
    S["args"] = a
    S["toolbar"] = a["action"] == "toolbar"
    S["opts"] = base.load_options(base.options_path())
    S["listen"] = luxos_sys.unix_listen(base.socket_name())
    if S["listen"] < 0:
        # uz bezi jiny vyber: preda se mu (zavre ho), jako druha zkratka na X11
        code = base.client_run(argv, 3000)
        if code >= 0:
            return code
        end
    else:
        S["listen_source"] = glib.fd_add_data(S["listen"], 1, on_listen, S["listen"])[0]
    end
    call glib.unix_signal_add(SIGTERM, on_signal)
    call glib.unix_signal_add(SIGINT, on_signal)
    call wl.on_event(on_event)
    if not wl.attach(layer.wl_display()):
        call shot.log("libluxos-wl is missing")
        call shot.notify(T("The screenshot could not be taken."))
        return 1
    end
    # bez allowlistu luxwm privilegovane globaly vubec neukaze
    if wl.has("ext_image_copy_capture_manager_v1") == 0 or wl.has("ext_output_image_capture_source_manager_v1") == 0:
        call shot.log("the compositor does not allow screen capture for this program (privileged.conf)")
        call shot.notify(T("The screenshot could not be taken."))
        return 1
    end
    if wm.connect(wm_event):
        call wm.request({"cmd": "list_windows"}, windows_reply)
    end
    if not capture_outputs():
        call failed("no output to capture")
        return S["code"]
    end
    call glib.timeout_add_data(CAPTURE_MS, capture_timeout, S["token"])
    S["running"] = True
    call gtk.main()
    return S["code"]
end
