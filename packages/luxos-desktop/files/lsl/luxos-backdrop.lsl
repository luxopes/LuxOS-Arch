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
# Ikony plochy (luxos_desk, jako xfdesktop styl 2 podle kanalu xfce4-desktop) na prvnim monitoru: ~/Desktop
# a pripojene vymenitelne disky; klik vybere, dvojklik otevre (GIO, vychozi aplikace), tazeni z prazdneho mista
# vybira obdelnikem, tazeni ikon je presune (polohy v ~/.config/luxos/desktop-icons), prave tlacitko nabidne
# Otevrit/Prejmenovat/Do Kose, klavesy sipky/Enter/Delete/F2/Escape (klavesnici plocha chce jen s vybranou
# ikonou), soubory pretazene ze spravce souboru (wl_data_device) se zkopiruji nebo presunou na Plochu.
# Ikony se kresli do vlastni vrstvy jen pri zmene; kazdy snimek je pak kopie tapety a teto vrstvy.
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
load luxos_automount as automount
load luxos_wl as wl
load luxos_material as material
load luxos_tokens as tokens
load luxos_desk as desk
load luxos_apps as apps
load luxos_xfconf as xfconf
load luxos_text as text

# G_USER_DIRECTORY_DESKTOP
DESKTOP_DIR = 0
CAIRO_FILTER_GOOD = 1
CAIRO_EXTEND_REPEAT = 1
# M_MMAP_THRESHOLD: velke obrazky vzdy mmap, po uvolneni hned zpet systemu (jinak by prah rostl
# s kazdym uvolnenym blokem a pixely by zustaly na halde)
M_MMAP_THRESHOLD = -3
# GdkEventMask: pohyb jen s drzenym levym tlacitkem (ukazatel bez tlacitka plochu nebudi), tlacitka, klavesy,
# vstup a odchod ukazatele
EVENTS = 32 | 256 | 512 | 1024 | 4096 | 8192
KEY_LEFT = 65361
KEY_UP = 65362
KEY_RIGHT = 65363
KEY_DOWN = 65364
KEY_RETURN = 65293
KEY_KP_ENTER = 65421
KEY_ESCAPE = 65307
KEY_DELETE = 65535
KEY_KP_DELETE = 65439
KEY_F2 = 65471
KEY_MENU = 65383
KEY_F10 = 65479
DRAG_START = 4.0
# GDK_ACTION_MOVE
ACTION_MOVE = 4

backdrops = []
# klic obrazku -> [cairo povrch, pocet vystupu, ktere ho kresli]
images = {}
ui = {"trace": env.get("LUXOS_BACKDROP_TRACE", "") == "1", "menu": 0, "menu_owner": None, "reload": 0, "names": 0}
# Ikony plochy: owner = plocha prvniho monitoru, layer = vrstva ikon [povrch, x, y] (prekresli se jen pri dirty),
# icons = sdilene ikony podle GIcon, press/drag/band = rozpracovane tazeni, pending = misto puszteni souboru
icons = {"owner": None, "conf": None, "items": [], "grid": None, "saved": {}, "selected": {}, "icons": {}, "layer": None,
         "dirty": True, "rescan": 0, "press": None, "drag": None, "band": None, "dark": False, "vm": 0, "dir": "",
         "editor": 0, "renaming": None, "pending": {}}

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
        if icons["owner"] == b:
            call layout_icons()
        end
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
    if icons["owner"] == b:
        call paint_icons(b, cr)
    end
    if key != b["drawn"]:
        b["drawn"] = key
        call trace("drawn " + b["output"] + " " + String(w) + "x" + String(h))
    end
    # pole prejmenovani (dite okna) kresli az vychozi obsluha
    return icons["editor"] == 0
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
         "scale": max(1, monitor_scale(monitor)), "key": "", "surface": 0, "drawn": "", "kbd": 0}
    call layer.init_for_window(win)
    # plocha sama material nema, jeji nabidka (xdg_popup) ano
    call layer.set_namespace(win, "luxos-backdrop@popups")
    if ui.get("menu_css", 0) == 0:
        call apply_menu_css()
    end
    call layer.set_layer(win, layer.LAYER_BACKGROUND)
    call layer.set_monitor(win, monitor)
    call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_BOTTOM, layer.EDGE_LEFT, layer.EDGE_RIGHT])
    # -1: cely vystup i pod vyhradnymi zonami listy a Docku
    call layer.set_exclusive_zone(win, -1)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_NONE)
    call gtk.widget_set_app_paintable(win, True)
    call gtk.widget_add_events(win, EVENTS)
    call lglib.connect_data(win, "draw", 1, on_draw, b)
    call lglib.connect_data(win, "button-press-event", 1, on_press, b)
    call lglib.connect_data(win, "motion-notify-event", 1, on_motion, b)
    call lglib.connect_data(win, "button-release-event", 1, on_release, b)
    call lglib.connect_data(win, "key-press-event", 1, on_key, b)
    call lglib.connect_data(win, "drag-data-received", 4, on_drop, b)
    call drop_target(win)
    # zaznam se neuvolnuje: GdkMonitor muze zit i po odpojeni a signal poslat pozdeji
    call lglib.connect_data(monitor, "notify::geometry", 1, on_monitor_changed, b)
    call lglib.connect_data(monitor, "notify::scale-factor", 1, on_monitor_changed, b)
    backdrops.append(b)
    call gtk.widget_show(win)
    call update_owner()
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
            call release(b["key"])
            b["key"] = ""
            call trace("backdrop removed " + b["output"])
            call update_owner()
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
    if b["scale"] != max(1, monitor_scale(monitor)) and icons["owner"] == b:
        call drop_icon_cache()
    end
    b["scale"] = max(1, monitor_scale(monitor))
    call schedule_names()
    call refresh(b)
    if icons["owner"] == b:
        call layout_icons()
    end
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
    if is_dark() != icons["dark"]:
        icons["dark"] = is_dark()
        call icons_changed()
    end
    call apply_menu_css()
    return False
end

# Nabidka plochy: material menu od kompozitoru, barvy a polozky z tokenu
function apply_menu_css():
    text = tokens.menu_css(is_dark(), material.compositor_blur())
    if ui.get("menu_css", 0) == 0:
        ui["menu_css"] = gtk.css_load(text)
    else:
        call luxos_gtk.css_set(ui["menu_css"], text)
    end
    return 0
end

# ---- nabidka plochy ------------------------------------------------------------------------------

function on_press(b, event, widget):
    if icons["editor"] != 0:
        call finish_rename(True)
    end
    button = gtk.event_button(event)
    x = gtk.event_x(event)
    y = gtk.event_y(event)
    item = None
    if icons["owner"] == b:
        item = desk.item_at(icons["items"], icons["grid"], x, y)
    end
    if button == 3:
        if item != None:
            if not (item["key"] in icons["selected"]):
                call select([item])
            end
            call show_item_menu(b, item)
            return True
        end
        call select([])
        call show_menu(b)
        return True
    end
    if button != 1 or icons["owner"] != b:
        return False
    end
    if gtk.event_is_double_click(event):
        icons["press"] = None
        if item != None:
            call open_item(item)
        end
        return True
    end
    if item != None:
        if not (item["key"] in icons["selected"]):
            call select([item])
        end
        icons["press"] = [x, y, item]
    else:
        call select([])
        icons["band"] = [x, y, x, y]
    end
    return True
end

# Klavesy jdou do nabidky (xdg_popup) pres plochu, ktera ji otevrela: plocha bez ikon ma klavesnici jen po
# dobu nabidky (kompozitor bez grabu xdg_popup ji jinak nabidce neda).
function on_menu_closed(unused, menu):
    if ui["menu_owner"] != None:
        b = ui["menu_owner"]
        ui["menu_owner"] = None
        call update_keyboard(b)
    end
    return 0
end

# Plocha s ikonami uz klavesnici ma (na vyzadani, kliknutim): tak zustane. Bez ikon vyhradne jen po dobu nabidky.
function menu_keyboard(b):
    ui["menu_owner"] = b
    if b["kbd"] != layer.KEYBOARD_ON_DEMAND:
        b["kbd"] = layer.KEYBOARD_EXCLUSIVE
        call layer.set_keyboard_mode(b["win"], layer.KEYBOARD_EXCLUSIVE)
    end
    return 0
end

function menu_entries():
    entries = [["New Folder", "new-folder"], "", ["Change Wallpaper…", ["luxos-settings", "desktop"]]]
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
    call menu_keyboard(b)
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
    call lglib.spawn_app(action)
    return 0
end

# Nova slozka na Plose ("Nova slozka", "Nova slozka 2", ...): s ikonami vybrana a hned k prejmenovani,
# bez nich (styl ikon 0) Plocha ve spravci souboru
function new_folder():
    desktop = desktop_dir()
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
    if icons["owner"] != None and icons["conf"]["enabled"] and desktop == icons["dir"]:
        call rescan(0)
        for item in icons["items"]:
            if item["path"] == path:
                call select([item])
                call start_rename(item)
            end
        end
        return 0
    end
    unsafe:
        uri = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_to_uri"), __lsl_address(desktop) + 16, 0, 0))
    end
    call lglib.launch_uri(uri)
    return 0
end

# ---- ikony plochy ----------------------------------------------------------------------------------

function desktop_dir():
    path = lglib.user_special_dir(DESKTOP_DIR)
    if path == "":
        path = glib.home_dir() + "/Desktop"
    end
    return path
end

function is_dark():
    return lglib.read_text(config_dir() + "/appearance").strip() == "dark"
end

# Ikony jen na plose prvniho monitoru (xfdesktop: hlavni monitor)
function update_owner():
    owner = None
    if len(backdrops) > 0:
        owner = backdrops[0]
    end
    if owner == icons["owner"]:
        return 0
    end
    old = icons["owner"]
    icons["owner"] = owner
    call drop_icon_cache()
    if old != None and old["monitor"] != 0:
        call update_keyboard(old)
        call gtk.widget_queue_draw(old["win"])
    end
    if owner != None and icons["conf"] != None:
        call layout_icons()
    end
    return 0
end

function icons_changed():
    icons["dirty"] = True
    if icons["owner"] != None:
        call gtk.widget_queue_draw(icons["owner"]["win"])
    end
    return 0
end

function drop_icon_cache():
    for k in icons["icons"]:
        if icons["icons"][k] != 0:
            call cairo.surface_destroy(icons["icons"][k])
        end
    end
    icons["icons"] = {}
    call drop_layer()
    icons["dirty"] = True
    return 0
end

function drop_layer():
    if icons["layer"] != None:
        call cairo.surface_destroy(icons["layer"][0])
        icons["layer"] = None
    end
    return 0
end

function icon_for(item):
    key = desk.icon_key(item)
    if key in icons["icons"]:
        return icons["icons"][key]
    end
    surface = apps.icon_gicon(item["gicon"], icons["grid"]["icon"], icons["owner"]["scale"])
    if surface == 0:
        surface = apps.icon_named("text-x-generic", icons["grid"]["icon"], icons["owner"]["scale"])
    end
    if surface != 0:
        # kresli se v pixelech zarizeni (desk.draw_item meri sirku obrazku)
        call material.set_device_scale(surface, 1)
    end
    icons["icons"][key] = surface
    return surface
end

function layout_icons():
    b = icons["owner"]
    if b == None or icons["conf"] == None:
        return 0
    end
    icons["grid"] = desk.grid(icons["conf"], b["w"], b["h"])
    call desk.place(icons["items"], icons["grid"], placement())
    call trace_icons()
    call icons_changed()
    return 0
end

# ulozene polohy + misto puszteni u souboru, ktere se prave kopiruji
function placement():
    out = {}
    for k in icons["saved"]:
        out[k] = icons["saved"][k]
    end
    for k in icons["pending"]:
        out[k] = icons["pending"][k]
    end
    return out
end

function trace_icons():
    if not ui["trace"]:
        return 0
    end
    parts = []
    for item in icons["items"]:
        parts.append(item["key"] + "@" + String(item["col"]) + "," + String(item["row"]))
    end
    call trace("icons " + String(len(parts)) + " " + " | ".join(parts))
    return 0
end

function removable(mount):
    unsafe:
        if __lsl_qbe_icall1(__lsl_symbol("g_mount_is_shadowed"), ptr(mount)) & 255 != 0:
            return False
        end
        if __lsl_qbe_icall1(__lsl_symbol("g_mount_can_eject"), ptr(mount)) & 255 != 0:
            return True
        end
        drive = __lsl_qbe_call1(__lsl_symbol("g_mount_get_drive"), ptr(mount))
        if drive == 0:
            return False
        end
        yes = __lsl_qbe_icall1(__lsl_symbol("g_drive_is_removable"), drive) & 255
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), drive)
        return yes != 0
    end
end

# [[nazev, uri, gicon]..]; volajici uvolni gicon (desk.scan si bere vlastni odkaz)
function mounts():
    out = []
    if icons["vm"] == 0:
        return out
    end
    unsafe:
        list = __lsl_qbe_call1(__lsl_symbol("g_volume_monitor_get_mounts"), ptr(icons["vm"]))
    end
    node = list
    while node != 0:
        unsafe:
            mount = __lsl_qbe_load64(node)
            if removable(mount):
                name = glib.take_c(__lsl_qbe_call1(__lsl_symbol("g_mount_get_name"), mount))
                root = __lsl_qbe_call1(__lsl_symbol("g_mount_get_root"), mount)
                uri = glib.take_c(__lsl_qbe_call1(__lsl_symbol("g_file_get_uri"), root))
                call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), root)
                out.append([name, uri, __lsl_qbe_call1(__lsl_symbol("g_mount_get_icon"), mount)])
            end
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), mount)
            node = __lsl_qbe_load64(node + 8)
        end
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), list)
    end
    return out
end

function rescan(unused):
    icons["rescan"] = 0
    found = mounts()
    items = desk.scan(icons["dir"], icons["conf"], found)
    for m in found:
        call glib.object_unref(m[2])
    end
    call desk.free_items(icons["items"])
    icons["items"] = items
    # vyber jen z polozek, ktere jeste jsou; misto puszteni plati jen do objeveni souboru
    keep = {}
    for item in items:
        if item["key"] in icons["selected"]:
            keep[item["key"]] = True
        end
        if item["key"] in icons["pending"]:
            icons["saved"][item["key"]] = icons["pending"].pop(item["key"])
        end
    end
    icons["selected"] = keep
    # ikony nepouzivane zadnou polozkou pryc
    used = {}
    for item in items:
        used[desk.icon_key(item)] = True
    end
    for k in List(icons["icons"].keys()):
        if not (k in used):
            if icons["icons"][k] != 0:
                call cairo.surface_destroy(icons["icons"][k])
            end
            call icons["icons"].pop(k)
        end
    end
    call layout_icons()
    if icons["owner"] != None:
        call update_keyboard(icons["owner"])
    end
    return False
end

# Plocha se meni po davkach (kopirovani vic souboru, rename): jedno nacteni za 30 ms
function schedule_rescan():
    if icons["rescan"] == 0:
        icons["rescan"] = lglib.timeout_add_data(30, rescan, 0)
    end
    return 0
end

function on_desktop_changed(path, event, other):
    # G_FILE_MONITOR_EVENT_CHANGED 0 (obsah souboru) ikonu nemeni
    if event != 0:
        call schedule_rescan()
    end
    return 0
end

function on_mounts_changed(unused, mount):
    return schedule_rescan()
end

function on_settings_changed(path, event, other):
    conf = desk.settings()
    if conf != icons["conf"]:
        icons["conf"] = conf
        call drop_icon_cache()
        call schedule_rescan()
    end
    return 0
end

function icons_start():
    icons["conf"] = desk.settings()
    icons["dir"] = desktop_dir()
    icons["saved"] = desk.load_positions()
    icons["dark"] = is_dark()
    unsafe:
        icons["vm"] = __lsl_qbe_call0(__lsl_symbol("g_volume_monitor_get"))
    end
    for signal in ["mount-added", "mount-removed", "mount-changed"]:
        call lglib.connect_data(icons["vm"], signal, 1, on_mounts_changed, 0)
    end
    call gio.file_monitor(icons["dir"], on_desktop_changed)
    call lglib.mkdir_p(glib.user_config_dir() + "/xfce4/xfconf/xfce-perchannel-xml")
    call gio.file_monitor(xfconf.user_path("xfce4-desktop"), on_settings_changed)
    call rescan(0)
    return 0
end

# ---- vrstva ikon ----

function dragged(item):
    return icons["drag"] != None and item["key"] in icons["selected"]
end

# Vrstva jen pres obsazene bunky (par ikon = par desitek kB, ne cely monitor)
function render_layer(b):
    call drop_layer()
    icons["dirty"] = False
    g = icons["grid"]
    shown = []
    for item in icons["items"]:
        if not dragged(item):
            shown.append(item)
        end
    end
    if len(shown) == 0:
        return 0
    end
    c0 = g["cols"]
    r0 = g["rows"]
    c1 = 0
    r1 = 0
    for item in shown:
        c0 = min(c0, item["col"])
        r0 = min(r0, item["row"])
        c1 = max(c1, item["col"] + 1)
        r1 = max(r1, item["row"] + 1)
    end
    origin = desk.cell_rect(g, c0, r0)
    w = (c1 - c0) * g["cell_w"]
    h = (r1 - r0) * g["cell_h"]
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, w * b["scale"], h * b["scale"])
    call material.set_device_scale(surface, b["scale"])
    cr = cairo.create(surface)
    for item in shown:
        cell = desk.cell_rect(g, item["col"], item["row"])
        call desk.draw_item(cr, item, g, cell[0] - origin[0], cell[1] - origin[1], item["key"] in icons["selected"],
                            icons["dark"], icon_for(item))
    end
    call cairo.destroy(cr)
    call cairo.surface_flush(surface)
    icons["layer"] = [surface, origin[0], origin[1]]
    return 0
end

function paint_icons(b, cr):
    if icons["grid"] == None:
        return 0
    end
    if icons["dirty"]:
        call render_layer(b)
        call trace("icons drawn")
    end
    if icons["layer"] != None:
        call cairo.set_source_surface(cr, icons["layer"][0], Float(icons["layer"][1]), Float(icons["layer"][2]))
        call cairo.paint(cr)
    end
    drag = icons["drag"]
    if drag != None:
        g = icons["grid"]
        for item in icons["items"]:
            if dragged(item):
                cell = desk.cell_rect(g, item["col"], item["row"])
                call desk.draw_item(cr, item, g, cell[0] + Int(drag[0]), cell[1] + Int(drag[1]), True, icons["dark"], icon_for(item))
            end
        end
    end
    band = icons["band"]
    if band != None:
        r = band_rect(band)
        sel = tokens_selection()
        call cairo.rectangle(cr, r[0] + 0.5, r[1] + 0.5, r[2], r[3])
        call cairo.set_source_rgba(cr, sel[0], sel[1], sel[2], 0.18)
        call cairo.fill_preserve(cr)
        call cairo.set_source_rgba(cr, sel[0], sel[1], sel[2], 0.75)
        call cairo.set_line_width(cr, 1.0)
        call cairo.stroke(cr)
    end
    return 0
end

function tokens_selection():
    c = tokens.COLORS["accent"]
    return [Float(c[0]) / 255.0, Float(c[1]) / 255.0, Float(c[2]) / 255.0]
end

function band_rect(band):
    return [min(band[0], band[2]), min(band[1], band[3]), max(band[0], band[2]) - min(band[0], band[2]),
            max(band[1], band[3]) - min(band[1], band[3])]
end

# ---- vyber, klavesnice ----

function select(items):
    chosen = {}
    for item in items:
        chosen[item["key"]] = True
    end
    if chosen == icons["selected"]:
        return 0
    end
    icons["selected"] = chosen
    keys = List(chosen.keys())
    call trace("selected " + ",".join(sorted(keys)))
    call icons_changed()
    if icons["owner"] != None:
        call update_keyboard(icons["owner"])
    end
    return 0
end

# Plocha s ikonami ma klavesnici na vyzadani: kliknuti na ikonu (nebo prave tlacitko pro Novou slozku) ji plose
# da, kliknuti do okna nebo nove okno ji luxcomp vrati oknu. Bez ikon klavesnici nepotrebuje.
function update_keyboard(b):
    if ui["menu_owner"] == b or icons["editor"] != 0:
        return 0
    end
    mode = layer.KEYBOARD_NONE
    if icons["owner"] == b and icons["conf"]["enabled"]:
        mode = layer.KEYBOARD_ON_DEMAND
    end
    if b["kbd"] != mode:
        b["kbd"] = mode
        call layer.set_keyboard_mode(b["win"], mode)
        call layer.try_force_commit(b["win"])
        call trace("keyboard " + String(mode))
    end
    return 0
end

function selected_items():
    out = []
    for item in icons["items"]:
        if item["key"] in icons["selected"]:
            out.append(item)
        end
    end
    return out
end

# nejblizsi ikona ve smeru sipky (v mrizce), jinak vyber zustava
function neighbour(item, dx, dy):
    best = None
    best_d = 0
    for other in icons["items"]:
        ax = other["col"] - item["col"]
        ay = other["row"] - item["row"]
        along = ax * dx + ay * dy
        if along <= 0:
            continue
        end
        across = abs(ax * dy) + abs(ay * dx)
        d = along * 100 + across
        if best == None or d < best_d:
            best = other
            best_d = d
        end
    end
    return best
end

function on_key(b, event, widget):
    if icons["owner"] != b:
        return False
    end
    key = gtk.event_key_keyval(event)
    if icons["editor"] != 0:
        if key == KEY_ESCAPE:
            call finish_rename(False)
            return True
        end
        # ostatni klavesy do pole
        return False
    end
    chosen = selected_items()
    if len(chosen) == 0:
        return False
    end
    moves = {KEY_LEFT: [-1, 0], KEY_RIGHT: [1, 0], KEY_UP: [0, -1], KEY_DOWN: [0, 1]}
    if key in moves:
        next = neighbour(chosen[0], moves[key][0], moves[key][1])
        if next != None:
            call select([next])
        end
    elif key == KEY_RETURN or key == KEY_KP_ENTER:
        for item in chosen:
            call open_item(item)
        end
    elif key == KEY_DELETE or key == KEY_KP_DELETE:
        call trash_items(chosen)
    elif key == KEY_F2:
        call start_rename(chosen[0])
    elif key == KEY_ESCAPE:
        call select([])
    elif key == KEY_MENU or key == KEY_F10:
        call show_item_menu(b, chosen[0])
    else:
        return False
    end
    return True
end

# ---- tazeni ----

function damage(b, r):
    unsafe:
        call __lsl_qbe_call5(__lsl_symbol("gtk_widget_queue_draw_area"), ptr(b["win"]), ptr(Int(r[0]) - 2), ptr(Int(r[1]) - 2),
                             ptr(Int(r[2]) + 4), ptr(Int(r[3]) + 4))
    end
    return 0
end

# obdelnik vybranych ikon posunutych o dx, dy (prekresleni jen tam)
function drag_rect(dx, dy):
    g = icons["grid"]
    x0 = 1000000
    y0 = 1000000
    x1 = -1000000
    y1 = -1000000
    for item in selected_items():
        cell = desk.cell_rect(g, item["col"], item["row"])
        x0 = min(x0, cell[0])
        y0 = min(y0, cell[1])
        x1 = max(x1, cell[0] + cell[2])
        y1 = max(y1, cell[1] + cell[3])
    end
    return [Float(x0) + dx, Float(y0) + dy, Float(x1 - x0), Float(y1 - y0)]
end

function on_motion(b, event, widget):
    if icons["owner"] != b:
        return False
    end
    x = gtk.event_x(event)
    y = gtk.event_y(event)
    press = icons["press"]
    if press != None and icons["drag"] == None and abs(x - press[0]) + abs(y - press[1]) >= DRAG_START:
        icons["drag"] = [0.0, 0.0]
        call icons_changed()
    end
    if icons["drag"] != None:
        old = drag_rect(icons["drag"][0], icons["drag"][1])
        icons["drag"] = [x - press[0], y - press[1]]
        call damage(b, old)
        call damage(b, drag_rect(icons["drag"][0], icons["drag"][1]))
        return True
    end
    band = icons["band"]
    if band != None:
        old = band_rect(band)
        band[2] = x
        band[3] = y
        call damage(b, old)
        call damage(b, band_rect(band))
        call select(desk.in_rect(icons["items"], icons["grid"], band_rect(band)))
        return True
    end
    return False
end

function occupied(col, row, skip):
    for item in icons["items"]:
        if item["col"] == col and item["row"] == row and not (item["key"] in skip):
            return True
        end
    end
    return False
end

# Pusteni: vybrane ikony o stejny pocet bunek; obsazena nebo mimo mrizku -> nejblizsi volna bunka
function drop_items(dx, dy):
    g = icons["grid"]
    press = icons["press"]
    anchor = press[2]
    cell = desk.cell_rect(g, anchor["col"], anchor["row"])
    target = desk.cell_at(g, Float(cell[0]) + Float(g["cell_w"]) / 2.0 + dx, Float(cell[1]) + Float(g["cell_h"]) / 2.0 + dy)
    dc = target[0] - anchor["col"]
    dr = target[1] - anchor["row"]
    moving = selected_items()
    skip = {}
    for item in moving:
        skip[item["key"]] = True
    end
    taken = {}
    for item in moving:
        col = item["col"] + dc
        row = item["row"] + dr
        if col < 0 or row < 0 or col >= g["cols"] or row >= g["rows"] or occupied(col, row, skip) or (String(col) + "," + String(row)) in taken:
            free = nearest_free(col, row, skip, taken)
            col = free[0]
            row = free[1]
        end
        taken[String(col) + "," + String(row)] = True
        item["col"] = col
        item["row"] = row
        call trace("moved " + item["key"] + " " + String(col) + "," + String(row))
    end
    call desk.save_positions(icons["items"], icons["saved"])
    return 0
end

function nearest_free(col, row, skip, taken):
    g = icons["grid"]
    best = [0, 0]
    best_d = -1
    for c in range(g["cols"]):
        for r in range(g["rows"]):
            if occupied(c, r, skip) or (String(c) + "," + String(r)) in taken:
                continue
            end
            d = (c - col) * (c - col) + (r - row) * (r - row)
            if best_d < 0 or d < best_d:
                best = [c, r]
                best_d = d
            end
        end
    end
    return best
end

function on_release(b, event, widget):
    if icons["owner"] != b or gtk.event_button(event) != 1:
        return False
    end
    if icons["drag"] != None:
        drag = icons["drag"]
        call drop_items(drag[0], drag[1])
        icons["drag"] = None
        call trace_icons()
        call icons_changed()
    elif icons["band"] != None:
        r = band_rect(icons["band"])
        icons["band"] = None
        call damage(b, r)
    elif icons["press"] != None:
        call select([icons["press"][2]])
    end
    icons["press"] = None
    return True
end

# ---- akce ----

function open_item(item):
    call trace("open " + item["key"])
    if item["kind"] == "app":
        return apps.launch(item["app"])
    end
    return apps.launch_uri(item["uri"])
end

function trash_items(items):
    for item in items:
        if item["path"] != "":
            call trace("trash " + item["key"] + " " + lglib.trash_file(item["path"]))
        end
    end
    call schedule_rescan()
    return 0
end

function eject(item):
    call trace("run gio mount -e " + item["uri"])
    call lglib.spawn_quiet(["gio", "mount", "-e", item["uri"]])
    return 0
end

function show_item_menu(b, item):
    menu = luxos_gtk.menu_new()
    entries = [["Open", "open"]]
    if item["kind"] == "mount":
        entries.append(["Eject", "eject"])
    elif item["path"] != "":
        if item["kind"] != "app":
            entries.append(["Rename…", "rename"])
        end
        entries.append("")
        entries.append(["Move to Trash", "trash"])
    end
    for entry in entries:
        if entry == "":
            call luxos_gtk.menu_append(menu, luxos_gtk.separator_menu_item_new())
            continue
        end
        mi = luxos_gtk.menu_item_new(i18n.T(entry[0]))
        call lglib.connect_data(mi, "activate", 0, on_item_action, [entry[1], item])
        call luxos_gtk.menu_append(menu, mi)
    end
    call gtk.widget_show_all(menu)
    call lglib.connect_data(menu, "deactivate", 0, on_menu_closed, 0)
    # nabidka se zahodi po zavreni (dalsi otevreni postavi novou pro jinou polozku)
    call lglib.connect_data(menu, "selection-done", 0, on_item_menu_done, menu)
    call menu_keyboard(b)
    call luxos_gtk.menu_popup_at_pointer(menu)
    call trace("item menu " + item["key"])
    return 0
end

function on_item_menu_done(menu, widget):
    call lglib.idle_add_data(destroy_later, menu)
    return 0
end

function destroy_later(widget):
    call gtk.widget_destroy(widget)
    return False
end

function on_item_action(pair, mi):
    action = pair[0]
    item = pair[1]
    if action == "open":
        for chosen in selected_items():
            call open_item(chosen)
        end
    elif action == "rename":
        call start_rename(item)
    elif action == "trash":
        call trash_items(selected_items())
    elif action == "eject":
        call eject(item)
    end
    return 0
end

# ---- prejmenovani: pole pres popisek ikony (GtkEntry v GtkFixed, jako xfdesktop) ----

function start_rename(item):
    b = icons["owner"]
    if b == None or item["path"] == "" or item["kind"] == "app" or icons["editor"] != 0:
        return 0
    end
    g = icons["grid"]
    cell = desk.cell_rect(g, item["col"], item["row"])
    if b.get("fixed", 0) == 0:
        unsafe:
            b["fixed"] = __lsl_qbe_call0(__lsl_symbol("gtk_fixed_new"))
        end
        call gtk.container_add(b["win"], b["fixed"])
        call gtk.widget_show(b["fixed"])
    end
    entry = gtk.entry_new()
    call gtk.entry_set_text(entry, item["name"])
    width = max(g["cell_w"] + 60, 180)
    x = max(4, min(b["w"] - width - 4, cell[0] + g["cell_w"] // 2 - width // 2))
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("gtk_widget_set_size_request"), ptr(entry), ptr(width), -1)
        call __lsl_qbe_call4(__lsl_symbol("gtk_fixed_put"), ptr(b["fixed"]), ptr(entry), ptr(x), ptr(cell[1] + 6 + g["icon"] + 2))
    end
    icons["editor"] = entry
    icons["renaming"] = item
    call lglib.connect_data(entry, "activate", 0, on_rename_activate, 0)
    call gtk.widget_show(entry)
    # jmeno bez pripony vybrane (jako Thunar): psani ho nahradi
    name = String(item["name"])
    stem = len(name)
    dot = text.rfind(name, ".")
    if dot > 0 and item["kind"] != "dir":
        stem = dot
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gtk_widget_grab_focus"), ptr(entry))
        call __lsl_qbe_call3(__lsl_symbol("gtk_editable_select_region"), ptr(entry), 0, ptr(stem))
    end
    call trace("rename " + item["key"])
    return 0
end

function on_rename_activate(unused, entry):
    return finish_rename(True)
end

# apply = Enter nebo kliknuti jinam; Escape zahodi
function finish_rename(apply):
    entry = icons["editor"]
    if entry == 0:
        return 0
    end
    item = icons["renaming"]
    name = String(gtk.entry_get_text(entry)).strip()
    icons["editor"] = 0
    icons["renaming"] = None
    call lglib.idle_add_data(destroy_later, entry)
    if apply and name != "" and name != item["name"] and name.find("/") < 0 and name != "." and name != "..":
        target = icons["dir"] + "/" + name
        if luxos_sys.lexists(target):
            call trace("rename exists " + name)
        elif lglib.rename(item["path"], target):
            # poloha a vyber jdou s ikonou
            icons["saved"][name] = [item["col"], item["row"]]
            if item["key"] in icons["saved"]:
                call icons["saved"].pop(item["key"])
            end
            call desk.save_positions([], icons["saved"])
            icons["selected"] = {name: True}
            call trace("renamed " + item["key"] + " -> " + name)
            call schedule_rescan()
        end
    end
    if icons["owner"] != None:
        call update_keyboard(icons["owner"])
    end
    return 0
end

# ---- soubory ze spravce souboru (wl_data_device) ----

function drop_target(win):
    unsafe:
        target = __lsl_qbe_call3(__lsl_symbol("gtk_target_entry_new"), glib.cstr("text/uri-list"), 0, 0)
        # GTK_DEST_DEFAULT_MOTION 1 | DROP 4 (bez zvyrazneni celeho monitoru), akce COPY | MOVE
        call __lsl_qbe_call5(__lsl_symbol("gtk_drag_dest_set"), ptr(win), 5, target, 1, 6)
        call __lsl_qbe_call1(__lsl_symbol("gtk_target_entry_free"), target)
    end
    return 0
end

function on_drop(b, context, x, y, data):
    if icons["owner"] != b:
        return 0
    end
    uris = []
    unsafe:
        px = __lsl_qbe_s32(ptr(x))
        py = __lsl_qbe_s32(ptr(y))
        list = __lsl_qbe_call1(__lsl_symbol("gtk_selection_data_get_uris"), ptr(data))
        action = __lsl_qbe_icall1(__lsl_symbol("gdk_drag_context_get_selected_action"), ptr(context))
    end
    if list == 0:
        return 0
    end
    i = 0
    while True:
        unsafe:
            at = __lsl_qbe_load64(list + i * 8)
        end
        if at == 0:
            break
        end
        uris.append(glib.from_c(at))
        i += 1
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_strfreev"), list)
    end
    mine = glib.filename_to_uri(icons["dir"]) + "/"
    sources = []
    for uri in uris:
        # soubor z Plochy na Plochu: jen poloha (to resi tazeni ikon), nic nekopirovat
        if uri.startswith(mine) and uri[len(mine):].find("/") < 0:
            continue
        end
        sources.append(uri)
    end
    if len(sources) == 0:
        return 0
    end
    # prvni soubor na misto puszteni
    first = sources[0].rstrip("/")
    name = glib.filename_from_uri(first)
    if name == "":
        name = first
    end
    name = String(name)
    name = name[text.rfind(name, "/") + 1:]
    if icons["grid"] != None:
        icons["pending"][name] = desk.cell_at(icons["grid"], Float(px), Float(py))
    end
    verb = "copy"
    if action == ACTION_MOVE:
        verb = "move"
    end
    call trace("drop " + verb + " " + String(len(sources)))
    call lglib.spawn_quiet(["gio", verb, "--"] + sources + [glib.filename_to_uri(icons["dir"])])
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
call material.grayscale_text()
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
call icons_start()
# vymenitelne disky po zasunuti (na X11 thunar-volman); plocha bezi v kazde relaci na Waylandu
call automount.start()
call trace("ready")
call gtk.main()
