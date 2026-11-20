# LuxOS - plocha relace na Waylandu (1.1.0): tapeta jako plocha layer-shell na vrstve BACKGROUND na kazdem
# monitoru (sleduje pripojeni a odpojeni) a nabidka plochy na pravem tlacitku. Nahrazuje xfdesktop (tapeta)
# a luxos-desktop-menu.c; widgety jsou dal samostatny luxos-widgets (na Waylandu plochy na vrstve BOTTOM).
# Jmeno luxos-backdrop: "luxos-desktop" je nazev balicku a luxos-desktop-menu modul GTK pro xfdesktop.
#
# Nastaveni v ~/.config/luxos/appearance.conf (zapisuje luxos-appearance wallpaper, zmena se projevi hned):
#   WALLPAPER=/cesta, WALLPAPER_<VYSTUP>=/cesta     tapeta, pro jeden vystup (WALLPAPER_HDMI_A_1); jinak
#                                                  vychozi tapeta LuxOS podle rezimu (~/.config/luxos/appearance)
#   WALLPAPER_MODE=fill|fit|center|tile            (i WALLPAPER_MODE_<VYSTUP>), vychozi fill jako xfdesktop "zoomed"
#   WALLPAPER_COLOR=#rrggbb                        barva bez tapety a okraju u fit/center
#
# Tapeta se dekoduje a zmensi (cairo, filtr GOOD) jen pri zmene nastaveni nebo velikosti vystupu; hotovy
# obrazek ma kazda velikost vystupu jednou (stejne monitory ho sdileji) a kresleni snimku je jen kopie.
# Puvodni pixely se hned uvolni: 4K tapeta neni v pameti ani jednou navic. Zadny casovac - jen udalosti.
#
# Ladeni a testy: LUXOS_BACKDROP_TRACE=1 vypisuje udalosti na stdout.
load env, cairo
load glib, gtk, gio
load luxos_glib as lglib
load luxos_gtk
load luxos_sys
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_wl as wl
load luxos_material as material

# G_USER_DIRECTORY_DESKTOP
DESKTOP_DIR = 0
CAIRO_FILTER_GOOD = 1
CAIRO_EXTEND_REPEAT = 1
# M_MMAP_THRESHOLD: velke obrazky vzdy mmap, po uvolneni hned zpet systemu (jinak by prah rostl
# s kazdym uvolnenym blokem a pixely by zustaly na halde)
M_MMAP_THRESHOLD = -3

backdrops = []
# klic obrazku -> [cairo povrch, pocet vystupu, ktere ho kresli]
images = {}
ui = {"trace": env.get("LUXOS_BACKDROP_TRACE", "") == "1", "menu": 0, "menu_owner": None, "reload": 0, "names": 0}

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

function monotonic_ms():
    return glib.monotonic_time() // 1000
end

function config_dir():
    return glib.user_config_dir() + "/luxos"
end

# ---- obrazky tapety -----------------------------------------------------------------------------

function load_pixbuf(path):
    if path == "":
        return 0
    end
    pb = gtk.pixbuf_new_from_file(path)
    if pb == 0:
        return 0
    end
    unsafe:
        # fotka z telefonu: otoceni podle EXIF (bez otoceni vrati tentyz pixbuf s novou referenci)
        turned = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_apply_embedded_orientation"), ptr(pb))
    end
    call glib.object_unref(pb)
    return turned
end

# Obrazek w x h pixelu zarizeni; scale = meritko vystupu (center a tile zachovaji velikost v bodech)
function render(path, mode, color, w, h, scale):
    surface = cairo.image_surface_create(cairo.FORMAT_RGB24, w, h)
    cr = cairo.create(surface)
    call cairo.set_source_rgb(cr, color[0], color[1], color[2])
    call cairo.paint(cr)
    pb = load_pixbuf(path)
    if pb != 0:
        iw = Float(gtk.pixbuf_get_width(pb))
        ih = Float(gtk.pixbuf_get_height(pb))
        k = Float(scale)
        if mode == "fill":
            k = max(Float(w) / iw, Float(h) / ih)
        elif mode == "fit":
            k = min(Float(w) / iw, Float(h) / ih)
        end
        if mode == "tile":
            call cairo.scale(cr, k, k)
        else:
            call cairo.translate(cr, (Float(w) - iw * k) / 2.0, (Float(h) - ih * k) / 2.0)
            call cairo.scale(cr, k, k)
            call cairo.rectangle(cr, 0.0, 0.0, iw, ih)
            call cairo.clip(cr)
        end
        call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        unsafe:
            source = __lsl_qbe_call1(__lsl_symbol("cairo_get_source"), ptr(cr))
            call __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_filter"), source, CAIRO_FILTER_GOOD)
            if mode == "tile":
                call __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_extend"), source, CAIRO_EXTEND_REPEAT)
            end
        end
        call cairo.paint(cr)
        call glib.object_unref(pb)
    end
    call cairo.destroy(cr)
    call cairo.surface_flush(surface)
    return surface
end

function image_key(b):
    path = material.wallpaper_path(b["output"])
    stamp = ""
    if path != "":
        stamp = String(lglib.stat(path))
    end
    return String([path, stamp, material.wallpaper_mode(b["output"]), material.wallpaper_color(), b["w"] * b["scale"],
                   b["h"] * b["scale"], b["scale"]])
end

function acquire(b, key):
    hit = images.get(key)
    if hit == None:
        start = monotonic_ms()
        path = material.wallpaper_path(b["output"])
        mode = material.wallpaper_mode(b["output"])
        surface = render(path, mode, material.wallpaper_color(), b["w"] * b["scale"], b["h"] * b["scale"], b["scale"])
        hit = [surface, 0]
        images[key] = hit
        call trace("rendered " + b["output"] + " " + String(b["w"]) + "x" + String(b["h"]) + "@" + String(b["scale"]) + " "
                   + mode + " " + path + " " + String(monotonic_ms() - start) + " ms")
    end
    hit[1] = hit[1] + 1
    return hit[0]
end

function release(key):
    hit = images.get(key)
    if hit == None:
        return 0
    end
    hit[1] = hit[1] - 1
    if hit[1] <= 0:
        call cairo.surface_destroy(hit[0])
        call images.pop(key)
        unsafe:
            call __lsl_qbe_icall1(__lsl_symbol("malloc_trim"), 0)
        end
    end
    return 0
end

# ---- plochy na monitorech --------------------------------------------------------------------------

# Obrazek se pripravi az pri kresleni: prvni snimek plochy je rovnou tapeta a stara tapeta zustava
# videt, dokud neni nova hotova (zadne bliknuti cerne).
function on_draw(b, cr, widget):
    w = gtk.widget_get_allocated_width(widget)
    h = gtk.widget_get_allocated_height(widget)
    if w > 1 and h > 1 and (w != b["w"] or h != b["h"]):
        b["w"] = w
        b["h"] = h
    end
    key = image_key(b)
    if key != b["key"]:
        surface = acquire(b, key)
        call release(b["key"])
        b["key"] = key
        b["surface"] = surface
    end
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.scale(cr, 1.0 / Float(b["scale"]), 1.0 / Float(b["scale"]))
    call cairo.set_source_surface(cr, b["surface"], 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.restore(cr)
    if key != b["drawn"]:
        b["drawn"] = key
        call trace("drawn " + b["output"] + " " + String(w) + "x" + String(h))
    end
    return True
end

function refresh(b):
    if image_key(b) != b["key"]:
        call gtk.widget_queue_draw(b["win"])
    end
    return 0
end

function monitor_scale(monitor):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gdk_monitor_get_scale_factor"), ptr(monitor))
    end
end

# Nazev vystupu (HEADLESS-1, eDP-1) pro WALLPAPER_<VYSTUP> podle polohy z xdg-output
function output_for(monitor):
    geo = layer.monitor_geometry(monitor)
    name = wl.output_name_at(geo[0], geo[1])
    if name == "":
        return "monitor-" + String(geo[0]) + "-" + String(geo[1])
    end
    return name
end

function add_backdrop(monitor):
    for b in backdrops:
        if b["monitor"] == monitor:
            return b
        end
    end
    geo = layer.monitor_geometry(monitor)
    win = gtk.window_new("luxos-backdrop")
    b = {"win": win, "monitor": monitor, "output": output_for(monitor), "w": geo[2], "h": geo[3],
         "scale": max(1, monitor_scale(monitor)), "key": "", "surface": 0, "drawn": "", "handlers": []}
    call layer.init_for_window(win)
    call layer.set_namespace(win, "luxos-backdrop")
    call layer.set_layer(win, layer.LAYER_BACKGROUND)
    call layer.set_monitor(win, monitor)
    call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_BOTTOM, layer.EDGE_LEFT, layer.EDGE_RIGHT])
    # -1: cely vystup i pod vyhradnymi zonami listy a Docku
    call layer.set_exclusive_zone(win, -1)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
    call gtk.widget_set_app_paintable(win, True)
    # GDK_BUTTON_PRESS_MASK
    call gtk.widget_add_events(win, 256)
    b["handlers"].append(lglib.connect_data(win, "draw", 1, on_draw, b))
    b["handlers"].append(lglib.connect_data(win, "button-press-event", 1, on_press, b))
    # zaznam se neuvolnuje: GdkMonitor muze zit i po odpojeni a signal poslat pozdeji
    call lglib.connect_data(monitor, "notify::geometry", 1, on_monitor_changed, b)
    call lglib.connect_data(monitor, "notify::scale-factor", 1, on_monitor_changed, b)
    backdrops.append(b)
    call gtk.widget_show(win)
    call trace("backdrop added " + b["output"] + " " + String(geo[2]) + "x" + String(geo[3]))
    return b
end

function remove_backdrop(monitor):
    for b in List(backdrops):
        if b["monitor"] == monitor:
            call backdrops.remove(b)
            b["monitor"] = 0
            if ui["menu_owner"] == b:
                ui["menu_owner"] = None
                call luxos_gtk.menu_popdown(ui["menu"])
            end
            call gtk.widget_destroy(b["win"])
            for id in b["handlers"]:
                call lglib.release(id)
            end
            call release(b["key"])
            b["key"] = ""
            call trace("backdrop removed " + b["output"])
        end
    end
    return 0
end

function on_monitor_added(monitor, display):
    call add_backdrop(monitor)
    call schedule_names()
    return 0
end

function on_monitor_removed(monitor, display):
    call remove_backdrop(monitor)
    return 0
end

function on_monitor_changed(b, pspec, monitor):
    if b["monitor"] == 0:
        return 0
    end
    geo = layer.monitor_geometry(monitor)
    b["w"] = geo[2]
    b["h"] = geo[3]
    b["scale"] = max(1, monitor_scale(monitor))
    call schedule_names()
    call refresh(b)
    return 0
end

# Udalosti GDK a xdg-output stejneho vystupu chodi v jednom kole v libovolnem poradi: nazvy az po nem
function schedule_names():
    if ui["names"] == 0:
        ui["names"] = lglib.idle_add_data(update_names, 0)
    end
    return 0
end

function update_names(unused):
    ui["names"] = 0
    for b in backdrops:
        name = output_for(b["monitor"])
        if name != b["output"]:
            b["output"] = name
            call trace("output " + name)
            call refresh(b)
        end
    end
    return False
end

function on_wl(kind, handle, a, b):
    if kind == wl.OUTPUT_NEW:
        call schedule_names()
    end
    return 0
end

# ---- nastaveni ---------------------------------------------------------------------------------

# luxos-appearance prepisuje soubor najednou (rename); vic udalosti tesne po sobe = jedno nacteni
function on_conf_changed(path, event, other):
    # G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT 1, DELETED 2, CREATED 3, RENAMED 8, MOVED_IN 9
    if event != 1 and event != 2 and event != 3 and event != 8 and event != 9:
        return 0
    end
    if ui["reload"] == 0:
        ui["reload"] = lglib.timeout_add_data(20, reload_conf, 0)
    end
    return 0
end

function reload_conf(unused):
    ui["reload"] = 0
    call material.reload()
    call trace("reload")
    for b in backdrops:
        call refresh(b)
    end
    return False
end

# ---- nabidka plochy ------------------------------------------------------------------------------

function on_press(b, event, widget):
    if gtk.event_button(event) != 3:
        return False
    end
    call show_menu(b)
    return True
end

# Klavesy jdou do nabidky (xdg_popup) pres plochu, ktera ji otevrela: klavesnice jen po dobu nabidky.
# Trvale "na vyzadani" by po kliknuti na plochu labwc 0.20 uz nevratil fokus oknu.
function on_menu_closed(unused, menu):
    if ui["menu_owner"] != None:
        call layer.set_keyboard_mode(ui["menu_owner"]["win"], layer.KEYBOARD_NONE)
        ui["menu_owner"] = None
    end
    return 0
end

function menu_entries():
    entries = [["New Folder", "new-folder"], "", ["Change Wallpaper…", ["luxos-settings"]]]
    if glib.find_program_in_path("luxos-widgets") != "":
        entries.append(["Edit Widgets…", ["luxos-widgets", "settings"]])
    end
    entries.append(["Displays…", ["luxos-display-settings"]])
    return entries
end

function show_menu(b):
    if ui["menu"] == 0:
        menu = luxos_gtk.menu_new()
        for entry in menu_entries():
            if entry == "":
                call luxos_gtk.menu_append(menu, luxos_gtk.separator_menu_item_new())
                continue
            end
            item = luxos_gtk.menu_item_new(i18n.T(entry[0]))
            call lglib.connect_data(item, "activate", 0, on_menu_item, entry[1])
            call luxos_gtk.menu_append(menu, item)
        end
        call gtk.widget_show_all(menu)
        call lglib.connect_data(menu, "deactivate", 0, on_menu_closed, 0)
        ui["menu"] = menu
    end
    ui["menu_owner"] = b
    call layer.set_keyboard_mode(b["win"], layer.KEYBOARD_EXCLUSIVE)
    call luxos_gtk.menu_popup_at_pointer(ui["menu"])
    call trace("menu")
    return 0
end

function on_menu_item(action, item):
    if action == "new-folder":
        call new_folder()
        return 0
    end
    call trace("run " + " ".join(action))
    call lglib.spawn_quiet(action)
    return 0
end

# Nova slozka na Plose ("Nova slozka", "Nova slozka 2", ...) a Plocha ve spravci souboru: ikony plochy
# zatim nejsou, slozku jde hned prejmenovat tam
function new_folder():
    desktop = lglib.user_special_dir(DESKTOP_DIR)
    if desktop == "":
        desktop = glib.home_dir() + "/Desktop"
    end
    call lglib.mkdir_p(desktop)
    base = desktop + "/" + i18n.T("New Folder")
    path = base
    n = 2
    while exists(path):
        path = base + " " + String(n)
        n += 1
    end
    call lglib.mkdir_p(path)
    call trace("folder " + path)
    unsafe:
        uri = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_to_uri"), __lsl_address(desktop) + 16, 0, 0))
    end
    call lglib.launch_uri(uri)
    return 0
end

# ---- start -------------------------------------------------------------------------------------------

function gtk_ready():
    unsafe:
        return __lsl_qbe_icall2(__lsl_symbol("gtk_init_check"), 0, 0) != 0
    end
end

unsafe:
    call __lsl_qbe_icall2(__lsl_symbol("mallopt"), M_MMAP_THRESHOLD, 1048576)
end
call glib.setlocale()
if not gtk_ready() or not layer.is_wayland() or not layer.is_supported():
    # kod 2: systemd ji znovu nespousti (luxos-backdrop.service RestartPreventExitStatus)
    call luxos_sys.eprint("luxos-backdrop: needs a Wayland compositor with layer-shell")
    call exit(2)
end
# Jen vystupy: bez zwlr_output_manager_v1 (wlroots 0.20.2 pada na assert pri zapnuti vystupu, kdyz ho
# nekdo drzi) a bez spravy oken, schranky a dalsich protokolu, ktere plocha nepotrebuje
if wl.on_event(on_wl):
    call wl.bind_only(["wl_output", "zxdg_output_manager_v1"])
    if wl.attach(layer.wl_display()):
        call wl.roundtrip()
        call wl.roundtrip()
    end
end
display = layer.default_display()
for monitor in layer.monitors():
    call add_backdrop(monitor)
end
call glib.signal_connect(display, "monitor-added", on_monitor_added, 1)
call glib.signal_connect(display, "monitor-removed", on_monitor_removed, 1)
call lglib.mkdir_p(config_dir())
call gio.file_monitor(config_dir() + "/appearance.conf", on_conf_changed)
call gio.file_monitor(config_dir() + "/appearance", on_conf_changed)
call trace("ready")
call gtk.main()
