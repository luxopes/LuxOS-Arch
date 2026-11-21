# lsl: link libXext.so.6 libX11.so.6
# LuxOS - Prohlidka LuxOS: kratky pruvodce systemem (kde je co), jako uvitani v macOS.
#
#   luxos-tour               okno pruvodce (Launchpad, Uvitani, O tomto pocitaci)
#   luxos-tour --first-run   prvni prihlaseni (luxos-session): jen pokud jeste nebezel
#   luxos-tour --page N      otevre rovnou N-tou stranku (od 1)
#
# Pri prvnim zobrazeni zapise ~/.config/luxos/tour-done, takze se sam spusti jen jednou. Jedna instance
# (GtkApplication cz.luxos.Tour): dalsi spusteni jen ukaze okno. Ilustrace kresli luxos_tour_draw.lsl.
# "Ukazat na obrazovce" zvyrazni skutecnou horni listu / Dock pruhlednym prekryvem - jen v relaci X11
# s kompozitorem a se zjistenou polohou, jinak se tlacitko nezobrazi.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo, pango
load math
load luxos_i18n as i18n
load luxos_text as text
load luxos_x11 as x11
load luxos_tour_draw as draw
load luxos_settings_ui as ui

CSS = ".tour-title { font-size: 24px; font-weight: 800; }\n.tour-body { font-size: 14px; opacity: 0.78; }\n.primary { border-radius: 999px; padding: 6px 24px; font-weight: 700; background-image: none;\n           background-color: #3d7bff; color: white; border: none; box-shadow: none; }\n.primary:hover { background-color: #5a8fff; }\n.primary:focus { box-shadow: 0 0 0 3px alpha(#3d7bff, 0.35); }\n.pill { border-radius: 999px; padding: 4px 16px; }\n.pill:checked { background-image: none; background-color: alpha(#3d7bff, 0.18); border-color: #3d7bff;\n                color: inherit; }\n.dot { min-width: 8px; min-height: 8px; padding: 0; margin: 0 3px; border-radius: 999px; border: none;\n       background-image: none; box-shadow: none; background-color: alpha(currentColor, 0.22); }\n.dot:hover { background-color: alpha(currentColor, 0.45); }\n.dot.active { background-color: #3d7bff; min-width: 22px; }\n.dot:focus { box-shadow: 0 0 0 2px alpha(#3d7bff, 0.5); }\n"
MARKER = glib.user_config_dir() + "/luxos/tour-done"
KEY_HOME = 65360
KEY_LEFT = 65361
KEY_RIGHT = 65363
KEY_PAGE_UP = 65365
KEY_PAGE_DOWN = 65366
KEY_END = 65367
KEY_ESCAPE = 65307

tour = {"window": 0, "stack": 0, "index": 0, "mode": "", "modes": {}, "areas": [], "dots": [], "next": 0, "back": 0,
        "skip": 0, "spots": {}, "spot": None, "start": 0, "syncing": False}
T = i18n.T

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

# [titulek, text, akce]; akce = [popisek, prikaz] | [popisek, "spot:bar|dock"] | ["mode", "mode"]
function pages():
    return [[T("Welcome to LuxOS"), T("This short tour shows you where everything is. It takes about a minute – you can skip it anytime and open it again from Launchpad as LuxOS Tour."), []],
        [T("The Menu Bar"), T("The LuxOS logo opens the system menu with About This Computer, Settings, sleep and shut down. Next to it is the name of the active app and icons of your open windows – click one to switch to it. On the right: keyboard layout, network, sound, battery with the time left, Control Center for quick settings, notifications and the calendar."),
         [[T("Show on Screen"), "spot:bar"], [T("Open Control Center"), ["luxos-cc-toggle"]]]],
        [T("The Dock"), T("Your favourite apps are at the bottom of the screen. Click an icon to open the app – a dot below it means the app is running. Drag apps from Launchpad to the Dock, drag them out to remove them."),
         [[T("Show on Screen"), "spot:dock"]]],
        [T("Launchpad and Search"), T("Tap the Super key (or press Super + A) to open Launchpad with all your apps. Super + Space searches apps, files and windows. Type a question instead and LuxAI will answer it – Ctrl + Enter always asks LuxAI."),
         [[T("Open Launchpad"), ["luxos-launchpad"]], [T("Open Search"), ["luxos-search"]]]],
        [T("Files and Safe"), T("Files (Super + E) keeps your documents, downloads and pictures. The Safe is an encrypted folder for private things – it locks itself when you log out, lock the screen or the computer goes to sleep."),
         [[T("Open Files"), ["thunar"]], [T("Open Safe"), ["luxos-safe"]]]],
        [T("Installing Apps"), T("LuxOS Store offers apps sorted into categories with one-click installs and updates. In the Terminal (Super + T) the lux command does the same: lux install, lux search, lux update."),
         [[T("Open LuxOS Store"), ["luxos-store"]], [T("Open Terminal"), ["luxos-terminal"]]]],
        [T("Light, Dark or Auto"), T("Choose how LuxOS looks. Auto switches between light and dark at sunrise and sunset. Wallpaper, Dock and much more are in Settings (Super + ,)."),
         [["mode", "mode"], [T("Open Settings"), ["luxos-settings", "appearance"]]]],
        [T("Share and Print"), T("LuxDrop sends files to computers and phones nearby – it also works with the LocalSend app. Printers & Scanners finds devices on your network or USB by itself: just plug in and print."),
         [[T("Open LuxDrop"), ["luxdrop"]], [T("Printers & Scanners"), ["luxos-printers"]]]],
        [T("Help and Shortcuts"), T("Found a bug or have an idea? Feedback sends it straight to the author of LuxOS. All keyboard shortcuts are listed in Keyboard Shortcuts. Enjoy LuxOS!"),
         [[T("Keyboard Shortcuts"), ["luxos-shortcuts"]], [T("Send Feedback…"), ["luxos-feedback"]]]]]
end

function have(cmd):
    return glib.find_program_in_path(cmd) != ""
end

# ---- skutecna horni lista a Dock (relace X11) -------------------------------------------------------------------

# Okno Docku je siroke a vysoke kvuli zvetsovani ikon; viditelny Dock = vstupni tvar okna (ShapeInput = 2)
function input_shape(window):
    unsafe:
        cells = __lsl_byte_zeros(16)
        base = __lsl_qbe_load64(__lsl_address(cells) + 24)
        rects = __lsl_qbe_call5(__lsl_symbol("XShapeGetRectangles"), x11.xdisplay(), ptr(window), 2, base, base + 8)
        n = __lsl_qbe_s32(__lsl_qbe_load32(base))
        if rects == 0 or n < 1:
            return []
        end
        x0 = 100000
        y0 = 100000
        x1 = -100000
        y1 = -100000
        for i in range(n):
            r = rects + i * 8
            x = __lsl_qbe_s16(__lsl_qbe_load16(r))
            y = __lsl_qbe_s16(__lsl_qbe_load16(r + 2))
            x0 = min(x0, x)
            y0 = min(y0, y)
            x1 = max(x1, x + __lsl_qbe_load16(r + 4))
            y1 = max(y1, y + __lsl_qbe_load16(r + 6))
        end
        call __lsl_qbe_call1(__lsl_symbol("XFree"), rects)
        return [x0, y0, x1 - x0, y1 - y0]
    end
end

function top_windows():
    out = []
    unsafe:
        cells = __lsl_byte_zeros(32)
        base = __lsl_qbe_load64(__lsl_address(cells) + 24)
        if __lsl_qbe_call6(__lsl_symbol("XQueryTree"), x11.xdisplay(), x11.root_xid(), base, base + 8, base + 16, base + 24) == 0:
            return out
        end
        children = __lsl_qbe_load64(base + 16)
        count = __lsl_qbe_load32(base + 24)
        for i in range(count):
            out.append(__lsl_qbe_load64(children + i * 8))
        end
        if children != 0:
            call __lsl_qbe_call1(__lsl_symbol("XFree"), children)
        end
    end
    return out
end

function plank_rect(g, scale):
    found = None
    call x11.trap_push()
    for window in top_windows():
        cls = x11.wm_class(window)
        if (cls[0] + " " + cls[1]).lower().find("plank") >= 0:
            geo = x11.client_geometry(window)
            if len(geo) == 4:
                x = Float(geo[0]) / scale
                y = Float(geo[1]) / scale
                w = Float(geo[2]) / scale
                h = Float(geo[3]) / scale
                if h >= 24.0 and w >= 48.0 and y + h > Float(g[1]) + Float(g[3]) * 0.6:
                    shape = input_shape(window)
                    if len(shape) == 4 and shape[2] >= 48 and shape[3] >= 24:
                        x = x + Float(shape[0]) / scale
                        y = y + Float(shape[1]) / scale
                        w = Float(shape[2]) / scale
                        h = Float(shape[3]) / scale
                    end
                    found = [x, y, w, h]
                end
            end
        end
    end
    call x11.trap_pop()
    return found
end

# Poloha horni listy a Docku {"bar": [x, y, w, h], "dock": ...} v logickych px hlavniho monitoru
function screen_rects():
    rects = {}
    if wayland():
        return rects
    end
    g = gtk.primary_monitor_info()
    wa = gtk.primary_monitor_workarea()
    # horni lista si rezervuje okraj obrazovky
    if wa[1] - g[1] >= 14 and wa[1] - g[1] <= 80:
        rects["bar"] = [Float(g[0]), Float(g[1]), Float(g[2]), Float(wa[1] - g[1])]
    end
    dock = plank_rect(g, Float(gtk.root_scale()))
    if dock != None:
        rects["dock"] = dock
    end
    return rects
end

# Pruhledny prekryv pres monitor, ktery kliky propousti; dvakrat pulzuje kolem oblasti
function spotlight(rect, label):
    if tour["spot"] != None:
        call gtk.widget_destroy(tour["spot"]["window"])
    end
    g = gtk.primary_monitor_info()
    w = gtk.window_new_popup()
    call gtk.window_set_rgba(w)
    call gtk.window_set_keep_above(w, True)
    call gtk.window_move(w, g[0], g[1])
    call gtk.window_set_default_size(w, g[2], g[3])
    spot = {"window": w, "rect": rect, "label": label, "t": 0.0, "g": g}
    tour["spot"] = spot
    call glib.connect_data(w, "draw", 1, draw_spot, spot)
    call gtk.widget_show_all(w)
    call gtk.widget_input_rect(w, 0, 0, 0, 0)
    call glib.timeout_add_data(30, spot_tick, spot)
    return 0
end

function spot_tick(spot):
    spot["t"] = spot["t"] + 0.03
    if spot["t"] >= 2.8:
        call gtk.widget_destroy(spot["window"])
        if tour["spot"] == spot:
            tour["spot"] = None
        end
        return False
    end
    call gtk.widget_queue_draw(spot["window"])
    return True
end

function draw_spot(spot, cr, widget):
    g = spot["g"]
    t = spot["t"]
    call cairo.set_operator(cr, 1)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.set_operator(cr, 2)
    fade = min(1.0, t / 0.25, (2.8 - t) / 0.4)
    pulse = 0.5 + 0.5 * math.sin(t * 2.0 * draw.PI / 1.2)
    r = spot["rect"]
    x = r[0] - Float(g[0])
    y = r[1] - Float(g[1])
    w = r[2]
    h = r[3]
    m = 3.0 + 5.0 * pulse
    # ztlumit zbytek obrazovky
    call cairo.rectangle(cr, 0.0, 0.0, Float(g[2]), Float(g[3]))
    call draw.rrect(cr, x - m, y - m, w + 2.0 * m, h + 2.0 * m, 12.0)
    call gtk.cairo_set_fill_rule(cr, 1)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.28 * fade)
    call cairo.fill(cr)
    for item in [[14.0, 0.12], [8.0, 0.22], [3.0, 1.0]]:
        call draw.rrect(cr, x - m, y - m, w + 2.0 * m, h + 2.0 * m, 12.0)
        call cairo.set_source_rgba(cr, draw.ACCENT[0], draw.ACCENT[1], draw.ACCENT[2], item[1] * fade)
        call cairo.set_line_width(cr, item[0])
        call cairo.stroke(cr)
    end
    # popisek pod/nad oblasti
    lay = pango.cairo_create_layout(cr)
    call pango.layout_set_font(lay, "Sans Bold 14px")
    call pango.layout_set_text(lay, spot["label"])
    size = pango.layout_get_pixel_size(lay)
    tw = Float(size[0])
    th = Float(size[1])
    lx = min(max(x + w / 2.0 - tw / 2.0 - 14.0, 12.0), Float(g[2]) - tw - 40.0)
    ly = y - m - th - 26.0
    if y < Float(g[3]) / 2.0:
        ly = y + h + m + 14.0
    end
    call draw.rrect(cr, lx, ly, tw + 28.0, th + 12.0, (th + 12.0) / 2.0)
    call cairo.set_source_rgba(cr, draw.ACCENT[0], draw.ACCENT[1], draw.ACCENT[2], 0.95 * fade)
    call cairo.fill(cr)
    call cairo.move_to(cr, lx + 14.0, ly + 6.0)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, fade)
    call pango.cairo_show_layout(cr, lay)
    call pango.layout_unref(lay)
    return False
end

# ---- okno -------------------------------------------------------------------------------------------------------

function is_dark():
    c = gtk.widget_get_color(tour["window"], 0)
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.5
end

function on_draw(index, cr, area):
    w = Float(gtk.widget_get_allocated_width(area))
    h = Float(gtk.widget_get_allocated_height(area))
    s = min(w / draw.VW, h / draw.VH)
    call cairo.translate(cr, (w - draw.VW * s) / 2.0, 0.0)
    call cairo.scale(cr, s, s)
    call draw.rrect(cr, 0.0, 0.0, draw.VW, draw.VH, 18.0)
    call cairo.clip(cr)
    call draw.draw_page(draw.painter(cr, area, is_dark()), index, tour["mode"])
    return False
end

# Rezim pod bodem v souradnicich okna nahledu - stejne prepocty jako on_draw
function appearance_at(area, x, y):
    w = Float(gtk.widget_get_allocated_width(area))
    h = Float(gtk.widget_get_allocated_height(area))
    s = min(w / draw.VW, h / draw.VH)
    if s <= 0.0:
        return ""
    end
    return draw.appearance_hit((x - (w - draw.VW * s) / 2.0) / s, y / s)
end

function on_appearance_click(event, area):
    key = appearance_at(area, gtk.event_x(event), gtk.event_y(event))
    if gtk.event_button(event) != 1 or key == "" or not (key in tour["modes"]):
        return False
    end
    call gtk.toggle_button_set_active(tour["modes"][key], True)
    return True
end

function on_appearance_motion(event, area):
    if appearance_at(area, gtk.event_x(event), gtk.event_y(event)) != "":
        call gtk.widget_set_cursor(area, "pointer")
    else:
        call gtk.widget_set_cursor(area, 0)
    end
    return False
end

function on_mode(key, button):
    if not gtk.toggle_button_get_active(button) or key == tour["mode"]:
        return 0
    end
    tour["mode"] = key
    call ui.launch(["luxos-appearance", key])
    for a in tour["areas"]:
        call gtk.widget_queue_draw(a)
    end
    return 0
end

function on_launch(argv, button):
    return ui.launch(argv)
end

function on_spot(item, button):
    rect = screen_rects().get(item[0], tour["spots"].get(item[0], None))
    if rect != None:
        call spotlight(rect, item[1])
    end
    return 0
end

function action_button(label):
    b = gtk.button_new(label)
    call gtk.widget_add_class(b, "pill")
    return b
end

function build_page(index, page):
    box = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_margins(box, 24, 24, 24, 10)
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, -1, Int(draw.VH) + 36)
    call gtk.widget_set_vexpand(area, True)
    call glib.connect_data(area, "draw", 1, on_draw, index)
    if index == 6 and have("luxos-appearance"):
        # nahledy Svetly/Tmavy/Auto jdou vybrat i kliknutim, ne jen tlacitky pod nimi
        call gtk.widget_add_events(area, gtk.BUTTON_PRESS_MASK + gtk.POINTER_MOTION_MASK + gtk.LEAVE_NOTIFY_MASK)
        call gtk.connect(area, "button-press-event", on_appearance_click)
        call gtk.connect(area, "motion-notify-event", on_appearance_motion)
    end
    tour["areas"].append(area)
    call gtk.box_pack_start(box, area, True, True, 0)
    title = gtk.label_new(page[0])
    call gtk.label_set_line_wrap(title, True)
    call gtk.label_set_justify(title, 2)
    call gtk.widget_set_margins(title, 0, 0, 8, 0)
    call gtk.widget_add_class(title, "tour-title")
    call gtk.box_pack_start(box, title, False, False, 0)
    body = gtk.label_new(page[1])
    call gtk.label_set_line_wrap(body, True)
    call gtk.label_set_justify(body, 2)
    call gtk.label_set_max_width_chars(body, 72)
    call gtk.widget_add_class(body, "tour-body")
    call gtk.box_pack_start(box, body, False, False, 0)
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_halign(row, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(row, 0, 0, 4, 0)
    for action in page[2]:
        if action[1] == "mode":
            group = gtk.box_new(gtk.HORIZONTAL, 6)
            first = 0
            for item in [["light", T("Light")], ["dark", T("Dark")], ["auto", T("Auto")]]:
                rb = ui.radio_button(first)
                if first == 0:
                    first = rb
                end
                call gtk.container_add(rb, gtk.label_new(item[1]))
                call gtk.widget_add_class(rb, "pill")
                call gtk.toggle_button_set_active(rb, item[0] == tour["mode"])
                call glib.connect_data(rb, "toggled", 0, on_mode, item[0])
                tour["modes"][item[0]] = rb
                call gtk.box_pack_start(group, rb, False, False, 0)
            end
            if have("luxos-appearance"):
                call gtk.box_pack_start(row, group, False, False, 0)
            end
        elif type(action[1]) == "String":
            which = action[1][5:]
            if which in tour["spots"]:
                b = action_button(action[0])
                call glib.connect_data(b, "clicked", 0, on_spot, [which, page[0]])
                call gtk.box_pack_start(row, b, False, False, 0)
            end
        elif have(action[1][0]):
            b = action_button(action[0])
            call glib.connect_data(b, "clicked", 0, on_launch, action[1])
            call gtk.box_pack_start(row, b, False, False, 0)
        end
    end
    call gtk.box_pack_start(box, row, False, False, 0)
    return box
end

function stack_add(stack, child, name):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), ptr(stack), ptr(child), cstr(name))
    end
end

# GTK_STACK_TRANSITION_TYPE_NONE 0, SLIDE_RIGHT 2, SLIDE_LEFT 3
function go(i, animate):
    if i < 0 or i >= len(tour["dots"]):
        return 0
    end
    transition = 0
    if animate:
        transition = 3 if i > tour["index"] else 2
    end
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("gtk_stack_set_visible_child_full"), ptr(tour["stack"]), cstr(String(i)), ptr(transition))
    end
    tour["index"] = i
    last = i == len(tour["dots"]) - 1
    call gtk.widget_set_visible(tour["back"], i > 0)
    call gtk.widget_set_visible(tour["skip"], not last)
    call gtk.button_set_label(tour["next"], T("Get Started") if last else T("Continue"))
    for k in range(len(tour["dots"])):
        call gtk.widget_set_class(tour["dots"][k], "active", k == i)
    end
    return gtk.widget_grab_focus(tour["next"])
end

function step(d):
    if d > 0 and tour["index"] == len(tour["dots"]) - 1:
        return gtk.window_close(tour["window"])
    end
    return go(tour["index"] + d, True)
end

function on_next(button):
    return step(1)
end

function on_back(button):
    return step(-1)
end

function on_skip(button):
    return gtk.window_close(tour["window"])
end

function on_dot(index, button):
    return go(index, True)
end

function focus_is_radio():
    unsafe:
        focus = __lsl_qbe_call1(__lsl_symbol("gtk_window_get_focus"), ptr(tour["window"]))
    end
    return focus != 0 and ui.is_a(focus, "GtkRadioButton")
end

function on_key(event, window):
    k = gtk.event_key_keyval(event)
    # sipky v prepinaci Svetly/Tmavy/Auto patri prepinaci, ne strankovani
    if (k == KEY_LEFT or k == KEY_RIGHT) and focus_is_radio():
        return False
    end
    if k == KEY_RIGHT or k == KEY_PAGE_DOWN:
        call step(1)
    elif k == KEY_LEFT or k == KEY_PAGE_UP:
        call step(-1)
    elif k == KEY_HOME:
        call go(0, True)
    elif k == KEY_END:
        call go(len(tour["dots"]) - 1, True)
    elif k == KEY_ESCAPE:
        call gtk.window_close(tour["window"])
    else:
        return False
    end
    return True
end

function on_style(window):
    for a in tour["areas"]:
        call gtk.widget_queue_draw(a)
    end
    return 0
end

function build_window(app):
    unsafe:
        window = __lsl_qbe_call1(__lsl_symbol("gtk_application_window_new"), ptr(app))
    end
    tour["window"] = window
    call gtk.window_set_title(window, T("LuxOS Tour"))
    call gtk.window_set_default_size(window, 780, -1)
    call gtk.window_set_position(window, 1)
    call gtk.window_set_icon_list(window, "luxos-tour")
    call gtk.window_set_wmclass(window, "luxos-tour", "luxos-tour")
    call ui.header_bar(window, T("LuxOS Tour"))
    tour["mode"] = ui.run(["luxos-appearance", "mode"])
    # bez kompozitoru by prekryv nebyl pruhledny; bez zjistene polohy neni co ukazat
    if gtk.screen_is_composited():
        tour["spots"] = screen_rects()
    end
    data = pages()
    root = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(window, root)
    unsafe:
        stack = __lsl_qbe_call0(__lsl_symbol("gtk_stack_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_stack_set_transition_duration"), stack, 260)
    end
    tour["stack"] = stack
    call gtk.widget_set_vexpand(stack, True)
    call gtk.box_pack_start(root, stack, True, True, 0)
    for i in range(len(data)):
        call stack_add(stack, build_page(i, data[i]), String(i))
    end
    call gtk.box_pack_start(root, gtk.separator_new(gtk.HORIZONTAL), False, False, 0)
    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bar, 18, 18, 14, 14)
    skip = gtk.button_new(T("Skip Tour"))
    call gtk.button_set_relief(skip, gtk.RELIEF_NONE)
    call gtk.connect(skip, "clicked", on_skip)
    tour["skip"] = skip
    call gtk.box_pack_start(bar, skip, False, False, 0)
    dots = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_halign(dots, gtk.ALIGN_CENTER)
    call gtk.widget_set_valign(dots, gtk.ALIGN_CENTER)
    for i in range(len(data)):
        d = gtk.button_new_empty()
        call gtk.widget_set_valign(d, gtk.ALIGN_CENTER)
        call gtk.widget_set_tooltip(d, data[i][0])
        call gtk.widget_add_class(d, "dot")
        call glib.connect_data(d, "clicked", 0, on_dot, i)
        call gtk.box_pack_start(dots, d, False, False, 0)
        tour["dots"].append(d)
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_box_set_center_widget"), ptr(bar), ptr(dots))
    end
    next_button = gtk.button_new(T("Continue"))
    call gtk.widget_set_can_default(next_button, True)
    call gtk.widget_add_class(next_button, "primary")
    call gtk.connect(next_button, "clicked", on_next)
    back = gtk.button_new(T("Back"))
    call gtk.widget_add_class(back, "pill")
    call gtk.connect(back, "clicked", on_back)
    tour["next"] = next_button
    tour["back"] = back
    call gtk.box_pack_end(bar, next_button, False, False, 0)
    call gtk.box_pack_end(bar, back, False, False, 0)
    call gtk.box_pack_start(root, bar, False, False, 0)
    call gtk.connect(window, "key-press-event", on_key)
    call gtk.connect(window, "style-updated", on_style)
    call gtk.widget_show_all(window)
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gtk_widget_grab_default"), ptr(next_button))
    end
    call go(max(0, min(tour["start"], len(data) - 1)), False)
    call ui.attach_test(window)
    return window
end

function on_activate(app):
    if tour["window"] != 0:
        return gtk.window_present(tour["window"])
    end
    call gtk.css_load(CSS)
    call build_window(app)
    # jen jednou, i kdyz se relace ukonci uprostred prohlidky
    call ui.touch(MARKER)
    return 0
end

function main():
    if "--first-run" in args and exists(MARKER):
        return 0
    end
    for i in range(len(args) - 1):
        if args[i] == "--page" and text.is_digits(args[i + 1]):
            tour["start"] = Int(args[i + 1]) - 1
        end
    end
    call glib.set_prgname("luxos-tour")
    call glib.set_application_name(T("LuxOS Tour"))
    unsafe:
        app = __lsl_qbe_call2(__lsl_symbol("gtk_application_new"), cstr("cz.luxos.Tour"), 0)
    end
    call gtk.connect(app, "activate", on_activate)
    unsafe:
        status = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("g_application_run"), app, 0, 0))
    end
    return status
end

exit(main())
