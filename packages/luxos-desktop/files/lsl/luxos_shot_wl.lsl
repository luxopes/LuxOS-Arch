# LuxOS Snimek obrazovky na Waylandu (1.1.0): cestu bere luxos-screenshot-ui, kdyz GDK bezi na Waylandu.
# Zadne volani X11: obraz jde pres ext-image-copy-capture (luxos_wl), schranka pres ext-data-control.
#
#   shot_wl.main(argv)    jeden pozadavek (prepinace luxos-screenshot), vraci kod ukonceni
#
# --screen ulozi vsechny vystupy jako jeden obrazek podle rozlozeni (jako korenove okno na X11), --region
# jeho vyrez. --portion a --window: nejdriv zmrazeny snimek vsech vystupu, nad nim plochy layer-shell
# OVERLAY (jedna na vystup, klavesnice jen pro ne): tazenim vyrez, mezernik prepne na vyber okna, Esc
# zrusi, prave tlacitko taky. Okno se vybira ze seznamu: ext-foreign-toplevel-list polohu oken nedava a
# snimek okna je jeho vlastni obsah (ext-foreign-toplevel-image-capture-source), ne vyrez obrazovky.
# Ctrl pri dokonceni vyberu nebo --clipboard = obrazek do schranky; proces ho drzi, dokud schranku
# neprevezme nekdo jiny.
#
# Zkratky dava luxwm.conf (exec luxos-screenshot ...), program zadne klavesy globalne nezabira. Snimek,
# seznam oken i schranka jsou privilegovane: skutecny program (/usr/lib/luxos/luxos-screenshot-ui) musi
# byt v /usr/share/luxwm/privileged.conf. Lista s rezimy (bez prepinacu) je zatim vyber vyrezu, nahravani
# a plovouci nahled po snimku na Waylandu zatim nejsou.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_sys
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_wl as wl
load luxos_shot_base as base
load luxos_shot as shot

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

S = {"args": None, "opts": None, "code": 0, "frames": [], "mode": "portion", "window_capture": 0,
     "holding": False, "running": False, "finished": False, "listen": -1, "listen_source": 0, "token": 0,
     "to_clip": False}
OV = {"wins": [], "sel": None, "drag": None, "windows": [], "hover": -1, "pick": 0, "shown": False}

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
    if token == S["token"] and not S["finished"] and (S["window_capture"] != 0 or not OV["shown"]):
        call failed("no answer from the compositor")
    end
    return False
end

# Vsechny vystupy zachyceny: hned ulozit (cela obrazovka, --region), jinak vyber nad zmrazenym snimkem
function frozen():
    a = S["args"]
    if a["action"] == "screen" or a["region"] != None:
        call deliver(compose(a["region"]))
        return 0
    end
    mode = "portion"
    if a["action"] == "window":
        mode = "window"
    end
    call ov_open(mode)
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

function reset(mode):
    S["mode"] = mode
    OV["sel"] = None
    OV["drag"] = None
    OV["hover"] = -1
    OV["pick"] = 0
    OV["windows"] = []
    if mode == "window":
        call load_windows()
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
        call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK + gtk.KEY_PRESS_MASK)
        call gtk.connect_data(win, "draw", 1, on_draw, f)
        call gtk.connect_data(win, "button-press-event", 1, on_press, f)
        call gtk.connect_data(win, "button-release-event", 1, on_release, f)
        call gtk.connect_data(win, "motion-notify-event", 1, on_motion, f)
        call gtk.connect_data(win, "key-press-event", 1, on_key, f)
        call gtk.widget_show_all(win)
        call gtk.widget_set_cursor(win, cursor_name())
        f["win"] = win
        OV["wins"].append(win)
    end
    return 0
end

function ov_close():
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
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
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
    call cairo.save(cr)
    call cairo.scale(cr, 1.0 / frame_scale(f), 1.0 / frame_scale(f))
    call cairo.set_source_surface(cr, f["img"], 0, 0)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.paint(cr)
    call cairo.restore(cr)
    if S["mode"] == "window":
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
        call cairo.paint(cr)
        if is_first(f):
            call draw_chooser(cr, f)
        end
    else:
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
    return [x, y, w, h]
end

function on_press(f, event, win):
    if S["finished"]:
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
        row = chooser_row(f, px, py)
        if row >= 0:
            call pick_window(row, gtk.event_button_state(event) & gtk.CONTROL_MASK != 0)
        end
        return True
    end
    gx = f["geo"][0] + px
    gy = f["geo"][1] + py
    OV["drag"] = [gx, gy]
    OV["sel"] = [gx, gy, 0, 0]
    call redraw()
    return True
end

function on_motion(f, event, win):
    px = Int(gtk.event_x(event))
    py = Int(gtk.event_y(event))
    if S["mode"] == "window":
        row = chooser_row(f, px, py)
        if row != OV["hover"]:
            OV["hover"] = row
            call redraw()
        end
        return True
    end
    if OV["drag"] == None:
        return True
    end
    # pri tazeni chodi udalosti dal do plochy, kde tazeni zacalo (i mimo ni): souradnice vuci ni
    OV["sel"] = [OV["drag"][0], OV["drag"][1], f["geo"][0] + px - OV["drag"][0], f["geo"][1] + py - OV["drag"][1]]
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
    call ov_close()
    call deliver(compose(sel))
    return True
end

function on_key(f, event, win):
    key = gtk.event_key_keyval(event)
    if key == KEY_ESCAPE:
        call finish(0)
    elif key == KEY_SPACE and OV["drag"] == None:
        if S["mode"] == "window":
            call set_mode("portion")
        else:
            call set_mode("window")
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

# ---- vysledek -----------------------------------------------------------------------------------------------

function deliver(img):
    if img == 0:
        call failed("empty selection")
        return 0
    end
    a = S["args"]
    folder = None
    if a["clipboard"]:
        if a["output"] != "":
            folder = a["output"]
        end
    else:
        folder = shot.save_dir(S["opts"], False, a["output"])
    end
    if S["to_clip"] or folder == None:
        tmp = base.runtime_dir() + "/.luxos-screenshot-clip-" + String(glib.getpid()) + ".png"
        ok = cairo.surface_write_to_png(img, tmp) == 0 and wl.clipboard_set_file("image/png", tmp)
        call luxos_sys.unlink(tmp)
        call cairo.surface_destroy(img)
        if not ok:
            call shot.notify(T("The screenshot could not be copied to the clipboard."))
            call finish(1)
            return 0
        end
        call shot.tlog("clipboard")
        S["holding"] = True
        call finish(0)
        return 0
    end
    call luxos_sys.mkdir_p(folder)
    path = base.unique_path(folder, base.file_name(shot.now_fields(), False))
    status = cairo.surface_write_to_png(img, path)
    call cairo.surface_destroy(img)
    if status != 0:
        call shot.notify(T("The screenshot could not be saved.") + " " + path)
        call finish(1)
        return 0
    end
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
    S["code"] = code
    S["token"] = S["token"] + 1
    call ov_close()
    call free_frames()
    # drzeni schranky neni vyber: dalsi spusteni uz patri novemu procesu
    if S["listen"] >= 0:
        call glib.source_remove(S["listen_source"])
        call luxos_sys.close(S["listen"])
        S["listen"] = -1
    end
    call shot.tlog("end " + String(code))
    call quit()
    return 0
end

function quit():
    if S["holding"] or not S["running"]:
        return 0
    end
    S["running"] = False
    call gtk.main_quit()
    return 0
end

function on_signal():
    S["holding"] = False
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
    if not capture_outputs():
        call failed("no output to capture")
        return S["code"]
    end
    call glib.timeout_add_data(CAPTURE_MS, capture_timeout, S["token"])
    S["running"] = True
    call gtk.main()
    return S["code"]
end
