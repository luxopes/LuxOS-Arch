# LuxOS - Nastaveni > Plocha a Dock: spousteci obrazovka, tapeta, widgety, Dock a horni lista (svetly/tmavy
# vzhled je na strance Vzhled). Nahrazuje xfdesktop-settings (viz /usr/lib/luxos/override-bin). Tapeta
# a pruhlednost jdou pres luxos-appearance (umi X11 i Wayland). Dock: na X11 GSettings Planku, na Waylandu ~/.config/luxos/dock.conf
# (luxos-dock ho sleduje). Tapeta na X11 z xfconf (xfdesktop), na Waylandu z appearance.conf.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load gio
load luxos_i18n as i18n
load luxos_text as text
load luxos_dock_model as dockmodel
load luxos_settings_ui as ui

WALL_DIRS = ["/usr/share/backgrounds/luxos", "~/Pictures/Wallpapers"]
THUMB_W = 150
THUMB_H = 94
DOCK_SCHEMA = "net.launchpad.plank.dock.settings"
DOCK_PATH = "/net/launchpad/plank/docks/dock1/"
SPLASHES = [["blue", "Blue"], ["purple", "Purple"], ["orange", "Orange"], ["green", "Green"], ["light", "White"]]

home = glib.home_dir()
config = glib.user_config_dir() + "/luxos"
PREFS = config + "/appearance.conf"
WIDGETS_CONF = config + "/widgets.conf"
DOCK_CONF = config + "/dock.conf"
THUMB_DIR = glib.user_cache_dir() + "/luxos/wallpaper-thumbs"

app = {"window": 0, "splashes": {}, "splash_current": "", "splash_busy": False, "spinner": 0,
       "splash_label": 0, "thumbs": {}, "queue": [], "widgets": 0, "dock": 0, "zoom_size": 0}

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

function read_prefs():
    prefs = {"BAR_OPACITY": "62", "DOCK_OPACITY": "", "DESKTOP_SCRIM": "1", "BAR_STYLE": "classic", "BAR_CLOCK": "right"}
    kv = ui.read_kv(PREFS)
    for key in prefs.keys():
        if key in kv:
            prefs[key] = kv[key]
        end
    end
    return prefs
end

function number(value, fallback):
    if text.is_digits(value):
        return Int(value)
    end
    return fallback
end

function on_off(on, yes, no):
    if on:
        return yes
    end
    return no
end

function mark(buttons, key):
    for k in buttons.keys():
        call gtk.widget_set_class(buttons[k], "current", k == key)
    end
    return 0
end

function choice_button(content, caption):
    b = gtk.button_new_empty()
    call gtk.widget_add_class(b, "mode")
    inner = gtk.box_new(gtk.VERTICAL, 6)
    if content != 0:
        call gtk.box_pack_start(inner, content, False, False, 0)
    end
    call gtk.box_pack_start(inner, gtk.label_new(caption), False, False, 0)
    call gtk.container_add(b, inner)
    return b
end

# ---- Spousteci obrazovka (Plymouth, luxos-splash z luxos-branding) -----------------------------------------

function build_boot_screen(page):
    if not exists("/usr/bin/luxos-splash"):
        return 0
    end
    g = ui.group(page, i18n.T("Boot Screen"))
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(box, 12, 12, 12, 4)
    call gtk.widget_set_halign(box, gtk.ALIGN_START)
    current = ui.run(["luxos-splash", "get"])
    for item in SPLASHES:
        image = 0
        pix = gtk.pixbuf_new_from_file_at_scale("/usr/share/luxos/splash/" + item[0] + ".png", 104, 58, True)
        if pix != 0:
            image = gtk.image_new_from_pixbuf(pix)
            call glib.object_unref(pix)
        end
        b = choice_button(image, i18n.T(item[1]))
        call glib.connect_data(b, "clicked", 0, on_splash, item[0])
        app["splashes"][item[0]] = b
        call gtk.box_pack_start(box, b, False, False, 0)
    end
    call mark(app["splashes"], current)
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    status = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(status, 14, 14, 0, 10)
    spinner = ui.spinner_new()
    # skryty mimo prubeh zmeny: jinak odsazuje popisek oproti ostatnim napovedam
    call gtk.widget_set_no_show_all(spinner, True)
    l = ui.label(i18n.T("Shown while the computer starts. A change rebuilds the boot image, which takes about a minute."), "hint")
    call gtk.box_pack_start(status, spinner, False, False, 0)
    call gtk.box_pack_start(status, l, True, True, 0)
    call gtk.box_pack_start(g["box"], status, False, False, 0)
    app["spinner"] = spinner
    app["splash_label"] = l
    app["splash_current"] = current
    return 0
end

function on_splash(key, button):
    if app["splash_busy"] or key == app["splash_current"]:
        return 0
    end
    app["splash_busy"] = True
    call mark(app["splashes"], key)
    for k in app["splashes"].keys():
        call gtk.widget_set_sensitive(app["splashes"][k], False)
    end
    call gtk.widget_show(app["spinner"])
    call ui.spinner_run(app["spinner"], True)
    call gtk.label_set_text(app["splash_label"], i18n.T("Applying the boot screen…"))
    # stderr pkexec i luxos-splash do vystupu: posledni radek se ukaze jako duvod chyby
    argv = ["sh", "-c", "exec pkexec /usr/bin/luxos-splash set \"$0\" 2>&1", key]
    if glib.spawn_capture(argv, on_splash_done, key) == 0:
        call splash_done(key, 1, "")
    end
    return 0
end

function on_splash_done(key, output, status):
    code = 1
    if status & 127 == 0:
        code = (status >> 8) & 255
    end
    return splash_done(key, code, output)
end

function splash_done(key, code, output):
    app["splash_busy"] = False
    call ui.spinner_run(app["spinner"], False)
    call gtk.widget_hide(app["spinner"])
    for k in app["splashes"].keys():
        call gtk.widget_set_sensitive(app["splashes"][k], True)
    end
    if code == 0:
        app["splash_current"] = key
        call gtk.label_set_text(app["splash_label"], i18n.T("The new boot screen will be shown at the next start."))
        return 0
    end
    call mark(app["splashes"], app["splash_current"])
    if code == 126 or code == 127:
        # pkexec: overeni zruseno nebo zamitnuto
        call gtk.label_set_text(app["splash_label"], i18n.T("Change cancelled."))
        return 0
    end
    lines = [line for line in output.strip().split("\n") if line.strip() != ""]
    message = i18n.T("Could not change the boot screen.")
    if len(lines) > 0:
        message = message + " (" + lines[len(lines) - 1].strip() + ")"
    end
    call gtk.label_set_text(app["splash_label"], message)
    return 0
end

# ---- Tapeta ------------------------------------------------------------------------------------------------

function unquote(value):
    v = value.strip()
    if len(v) >= 2 and (v[0] == "\"" or v[0] == "'") and v[len(v) - 1] == v[0]:
        return v[1:len(v) - 1]
    end
    return v
end

function current_wallpaper():
    if wayland():
        path = unquote(ui.read_kv(PREFS).get("WALLPAPER", ""))
        if path == "":
            mode = "light"
            if glib.read_text(config + "/appearance").strip() == "dark":
                mode = "dark"
            end
            path = "/usr/share/backgrounds/luxos/luxos-" + mode + ".jpg"
        end
    else:
        prop = ""
        for p in ui.run(["xfconf-query", "-c", "xfce4-desktop", "-l"]).split("\n"):
            if prop == "" and p.endswith("/workspace0/last-image"):
                prop = p.strip()
            end
        end
        if prop == "":
            return ""
        end
        path = ui.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop])
    end
    if path == "":
        return ""
    end
    return glib.realpath(path)
end

function is_picture(name):
    low = name.lower()
    return low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".png") or low.endswith(".webp")
end

function build_wallpaper(page, prefs):
    g = ui.group(page, i18n.T("Wallpaper"))
    current = current_wallpaper()
    flow = ui.flow_box(4, 6)
    call gtk.widget_set_margins(flow, 10, 10, 10, 10)
    seen = []
    for folder in WALL_DIRS:
        folder = folder.replace("~", home)
        for name in glib.list_dir(folder):
            real = glib.realpath(folder + "/" + name)
            if real != "" and is_picture(name) and not (real in seen):
                seen.append(real)
                call add_thumb(flow, real, real == current)
            end
        end
    end
    call gtk.box_pack_start(g["box"], flow, False, False, 0)
    choose = gtk.button_new(i18n.T("Choose…"))
    call gtk.connect(choose, "clicked", on_choose)
    call ui.row(g, i18n.T("Your own picture"), "", choose)
    # ztmaveni velmi svetle tapety pod listou a kolem widgetu (luxos-bar, luxos-widgets)
    scrim = ui.switch(prefs["DESKTOP_SCRIM"] != "0", on_appearance_switch, ["desktop-scrim", "on", "off"])
    call ui.row(g, i18n.T("Darken bright wallpaper under the menu bar and widgets"),
                i18n.T("On a very bright wallpaper the area under the menu bar and around widgets gets a soft shade, so white text stays readable."), scrim)
end

function thumb_title(path):
    name = path[text.rfind(path, "/") + 1:]
    dot = text.rfind(name, ".")
    if dot > 0:
        name = name[0:dot]
    end
    words = []
    for word in name.replace("luxos-", "").replace("-", " ").split(" "):
        if word != "":
            words.append(word[0:1].upper() + word[1:].lower())
        end
    end
    return " ".join(words)
end

function add_thumb(flow, path, current):
    b = gtk.button_new_empty()
    call gtk.widget_add_class(b, "thumb")
    call gtk.widget_set_class(b, "current", current)
    # obrazek az po zobrazeni okna (jeden nahled na volny cyklus smycky)
    image = gtk.image_new()
    call gtk.widget_set_size_request(image, THUMB_W, THUMB_H)
    call gtk.container_add(b, image)
    if len(app["queue"]) == 0:
        call glib.idle_add(load_thumbs)
    end
    app["queue"].append([image, path, b])
    call gtk.widget_set_tooltip(b, thumb_title(path))
    call glib.connect_data(b, "clicked", 0, on_thumb, path)
    app["thumbs"][path] = b
    call gtk.container_add(flow, b)
end

# Dekodovani velkeho JPEG trva desitky ms: nahled se uklada do cache (PNG 150x94 se nacte hned)
function wallpaper_thumb(path):
    st = glib.stat(path)
    if len(st) == 0:
        return 0
    end
    cache = THUMB_DIR + "/" + ui.sha1(path + ":" + String(st[1]) + ":" + String(st[0])) + ".png"
    if exists(cache):
        pix = gtk.pixbuf_new_from_file(cache)
        if pix != 0:
            return pix
        end
    end
    pix = gtk.pixbuf_new_from_file_at_scale(path, THUMB_W, THUMB_H, False)
    if pix == 0:
        return 0
    end
    call glib.mkdir_p(THUMB_DIR)
    tmp = cache + ".tmp"
    if gtk.pixbuf_save_png(pix, tmp) == "":
        call glib.rename(tmp, cache)
    end
    return pix
end

function load_thumbs():
    if len(app["queue"]) == 0:
        return False
    end
    item = app["queue"].pop(0)
    pix = wallpaper_thumb(item[1])
    if pix != 0:
        call gtk.image_set_from_pixbuf(item[0], pix)
        call glib.object_unref(pix)
    else:
        # nelze nacist (poskozeny soubor)
        call app["thumbs"].pop(item[1])
        call gtk.widget_destroy(item[2])
    end
    return len(app["queue"]) > 0
end

function set_wallpaper(path):
    call mark(app["thumbs"], path)
    call ui.launch(["luxos-appearance", "wallpaper", path])
    return 0
end

function on_thumb(path, button):
    return set_wallpaper(path)
end

function on_choose(button):
    path = ui.choose_picture(app["window"], i18n.T("Choose a picture"), i18n.T("Pictures"))
    if path != "":
        call set_wallpaper(path)
    end
    return 0
end

function on_appearance_switch(args, on):
    call ui.launch(["luxos-appearance", args[0], on_off(on, args[1], args[2])])
    return 0
end

# ---- Widgety na plose (luxos-widgets) -----------------------------------------------------------------------

function widgets_on():
    return ui.read_kv(WIDGETS_CONF).get("ENABLED", "") == "1"
end

function build_widgets(page):
    if glib.find_program_in_path("luxos-widgets") == "":
        return 0
    end
    g = ui.group(page, i18n.T("Widgets"))
    app["widgets"] = ui.switch(widgets_on(), on_widgets, 0)
    call ui.row(g, i18n.T("Show widgets on the desktop"),
                i18n.T("Clock & Weather, System Health, Now Playing and Calendar cards on the desktop."), app["widgets"])
    edit = gtk.button_new(i18n.T("Edit Widgets…"))
    call glib.connect_data(edit, "clicked", 0, on_launch, ["luxos-widgets", "settings"])
    call ui.row(g, i18n.T("Choose and arrange widgets"),
                i18n.T("You can also right-click a widget or the desktop and choose Edit Widgets…"), edit)
    # vypnuti/zapnuti z galerie nebo z nabidky widgetu: vypinac sleduje widgets.conf
    call glib.mkdir_p(config)
    safe:
        call gio.file_monitor(config, on_config_changed)
    end
    return 0
end

function on_widgets(unused, on):
    call ui.launch(["luxos-widgets", on_off(on, "on", "off")])
    return 0
end

function on_config_changed(file, event, other):
    if file.endswith("/widgets.conf") and app["widgets"] != 0:
        call ui.switch_set(app["widgets"], widgets_on())
    end
    return 0
end

function on_launch(argv, button):
    return ui.launch(argv)
end

# ---- Dock --------------------------------------------------------------------------------------------------
# Na Waylandu luxos-dock: jen dole, zvetseni = ZOOM nad 100 (100 = vypnuto), HIDE autohide/dodge

function dock_conf():
    return dockmodel.parse_conf(glib.read_text(DOCK_CONF))
end

function dock_set(key, value):
    return ui.write_kv(DOCK_CONF, key, value)
end

function build_dock(page, prefs):
    wl = wayland()
    d = 0
    if not wl:
        d = ui.gsettings(DOCK_SCHEMA, DOCK_PATH)
        if d == 0:
            return 0
        end
    end
    app["dock"] = d
    if wl:
        conf = dock_conf()
        autohide = conf["hide"] == "autohide"
        size = conf["icon_size"]
        zoom_on = conf["zoom"] > 100
        zoom = conf["zoom"]
        if not zoom_on:
            zoom = 150
        end
    else:
        autohide = ui.gs_get_string(d, "hide-mode") == "auto"
        size = ui.gs_get_int(d, "icon-size")
        zoom_on = ui.gs_get_bool(d, "zoom-enabled")
        zoom = ui.gs_get_int(d, "zoom-percent")
    end
    g = ui.group(page, i18n.T("Dock"))
    call ui.row(g, i18n.T("Automatically hide and show the Dock"),
                i18n.T("The Dock appears when you move the pointer to the bottom edge."), ui.switch(autohide, on_autohide, 0))
    call ui.row(g, i18n.T("Size"), "", ui.slider(32, 80, size, 220, on_dock_size, 0))
    call ui.row(g, i18n.T("Magnification"), "", ui.switch(zoom_on, on_zoom, 0))
    zoom_size = ui.slider(110, 200, zoom, 220, on_zoom_size, 0)
    call ui.row(g, i18n.T("Magnification size"), "", zoom_size)
    # velikost zvetseni jen se zapnutym zvetsovanim (jako v macOS)
    call gtk.widget_set_sensitive(zoom_size, zoom_on)
    app["zoom_size"] = zoom_size
    if not wl:
        position = ui.gs_get_string(d, "position")
        if not (position in ["bottom", "left", "right"]):
            position = "bottom"
        end
        pos = ui.combo([["bottom", i18n.T("Bottom")], ["left", i18n.T("Left")], ["right", i18n.T("Right")]], position, "", on_position, 0)
        call ui.row(g, i18n.T("Position on screen"), "", pos)
    end
    call ui.row(g, i18n.T("Dock opacity"), "", ui.slider(0, 100, number(prefs["DOCK_OPACITY"], 75), 220, on_opacity, "dock-opacity"))
    return 0
end

# Skryvani Docku (oba rezimy Dock skryvaji, luxos-menubar ho vysune i kousek nad okrajem)
function on_autohide(unused, on):
    if wayland():
        call dock_set("HIDE", on_off(on, "autohide", "dodge"))
        return 0
    end
    call ui.gs_set_string(app["dock"], "hide-mode", on_off(on, "auto", "window-dodge"))
    call ui.touch(config + "/dock-autohide")
    return 0
end

function on_dock_size(unused, value):
    if wayland():
        return dock_set("ICON_SIZE", String(value))
    end
    return ui.gs_set_int(app["dock"], "icon-size", value)
end

function on_zoom(unused, on):
    call gtk.widget_set_sensitive(app["zoom_size"], on)
    if wayland():
        zoom = "100"
        if on:
            zoom = String(Int(gtk.range_get_value(app["zoom_size"]) + 0.5))
        end
        return dock_set("ZOOM", zoom)
    end
    return ui.gs_set_bool(app["dock"], "zoom-enabled", on)
end

function on_zoom_size(unused, value):
    if wayland():
        return dock_set("ZOOM", String(value))
    end
    return ui.gs_set_int(app["dock"], "zoom-percent", value)
end

function on_position(unused, value):
    return ui.gs_set_string(app["dock"], "position", value)
end

function on_opacity(what, value):
    return ui.launch(["luxos-appearance", what, String(value)])
end

# ---- Horni lista -------------------------------------------------------------------------------------------

function build_bar(page, prefs):
    g = ui.group(page, i18n.T("Menu Bar"))
    call ui.row(g, i18n.T("Menu bar opacity"), "", ui.slider(0, 100, number(prefs["BAR_OPACITY"], 62), 220, on_opacity, "bar-opacity"))
    call ui.row(g, i18n.T("Clock in the middle"), "", ui.switch(prefs["BAR_CLOCK"] == "center", on_appearance_switch, ["bar-clock", "center", "right"]))
    call ui.row(g, i18n.T("Rounded corners"), "", ui.switch(prefs["BAR_STYLE"] == "rounded", on_appearance_switch, ["bar-style", "rounded", "classic"]))
end

# ---- stranka ----------------------------------------------------------------------------------------------

# Odchod ze stranky: zapis Docku do dconf je asynchronni
function leave(host):
    call ui.gs_sync()
    return 0
end

function build(host):
    app["window"] = host["window"]
    prefs = read_prefs()
    page = ui.page_box()
    call build_boot_screen(page)
    call build_wallpaper(page, prefs)
    call build_widgets(page)
    call build_dock(page, prefs)
    call build_bar(page, prefs)
    if not wayland():
        # Xfce: jen v relaci X11
        more = gtk.box_new(gtk.HORIZONTAL, 8)
        call gtk.widget_set_margins(more, 0, 0, 18, 0)
        for link in [["Advanced Desktop Settings…", ["/usr/bin/xfdesktop-settings"]], ["Menu Bar Items…", ["xfce4-panel", "--preferences"]]]:
            b = gtk.button_new(i18n.T(link[0]))
            call glib.connect_data(b, "clicked", 0, on_launch, link[1])
            call gtk.box_pack_start(more, b, False, False, 0)
        end
        call gtk.box_pack_start(page, more, False, False, 0)
    end
    return page
end
