# LuxOS Control Center - rychle nastaveni z horni listy (jako v macOS); prepis luxos-control-center do LSL.
# Dlazdice: Wi-Fi (+ odkaz na QR kod site), Bluetooth, Nerusit, Tmavy rezim, Sporic dat, Sporic baterie; posuvniky jasu a hlasitosti;
# stav baterie; prave hrajici hudba (MPRIS). Okno se zavre pri ztrate fokusu nebo klavesou Esc.
#
#   call cc.create()      skryte okno se styly podle motivu (pouziva luxos-hub i samostatny program)
#   call cc.toggle()      ukaze/skryje okno (klik v liste)
#   cc.panel_text()       vystup pro plugin genmon (--panel)
# Stav drzi slovnik `cc` (zadne tridy: obsluhy signalu jsou funkce modulu s vazanymi daty).
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_mpris as mpris
load luxos_text as text

CSS = ("window.cc { background: transparent; }\n"
    + ".cc-box { background-color: @cc_bg; border-radius: 18px; border: 1px solid @cc_border; padding: 12px; color: @cc_fg; }\n"
    + ".tile { background-color: @cc_tile; border-radius: 14px; padding: 10px 12px; border: none; box-shadow: none; background-image: none; color: @cc_fg; }\n"
    + ".tile:hover { background-color: @cc_tile_hover; }\n"
    + ".tile .bubble { background-color: @cc_bubble; border-radius: 999px; min-width: 30px; min-height: 30px; color: @cc_fg; }\n"
    + ".tile.on .bubble { background-color: #3d7bff; color: white; }\n"
    + ".tile .title { font-weight: 600; font-size: 12px; }\n"
    + ".tile .sub { font-size: 11px; color: @cc_dim; }\n"
    + ".tile:disabled { opacity: 0.45; }\n"
    + ".section { background-color: @cc_tile; border-radius: 14px; padding: 10px 12px; }\n"
    + ".section .title { font-weight: 600; font-size: 12px; }\n"
    + ".section .sub { font-size: 11px; color: @cc_dim; }\n"
    + ".cc-box scale trough { min-height: 22px; border-radius: 11px; background-color: @cc_trough; border: none; }\n"
    + ".cc-box scale highlight { border-radius: 11px; background-color: @cc_fill; border: none; min-height: 22px; }\n"
    + ".cc-box scale slider { min-width: 22px; min-height: 22px; margin: 0; border-radius: 11px; background-color: white; border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.35); }\n"
    + ".footer { background: none; border: none; box-shadow: none; color: @cc_fg; padding: 4px 6px; font-size: 12px; border-radius: 8px; }\n"
    + ".footer:hover { background-color: @cc_tile; }\n"
    + "button.plain { padding: 0; border: none; background: none; box-shadow: none; }\n"
    + ".art { border-radius: 9px; min-width: 42px; min-height: 42px; color: white; background-image: linear-gradient(135deg, #ff5f6d, #c445ff); }\n"
    + "button.media { padding: 4px; border: none; background: none; box-shadow: none; color: @cc_fg; border-radius: 999px; min-width: 30px; min-height: 30px; }\n"
    + "button.media:hover { background-color: @cc_tile_hover; }\n"
    + ".avatar { border-radius: 999px; min-width: 34px; min-height: 34px; font-weight: 800; color: white; background-image: linear-gradient(135deg, #3d7bff, #8b4dff); }\n")

DARK = ("@define-color cc_bg rgba(32, 33, 52, 0.86); @define-color cc_border rgba(255, 255, 255, 0.14);\n"
    + "@define-color cc_fg #f4f4fa; @define-color cc_dim rgba(244, 244, 250, 0.6);\n"
    + "@define-color cc_tile rgba(255, 255, 255, 0.08); @define-color cc_tile_hover rgba(255, 255, 255, 0.13);\n"
    + "@define-color cc_bubble rgba(255, 255, 255, 0.14); @define-color cc_trough rgba(255, 255, 255, 0.14);\n"
    + "@define-color cc_fill rgba(255, 255, 255, 0.85);\n")

LIGHT = ("@define-color cc_bg rgba(246, 247, 252, 0.88); @define-color cc_border rgba(0, 0, 0, 0.10);\n"
    + "@define-color cc_fg #1d1d2b; @define-color cc_dim rgba(29, 29, 43, 0.58);\n"
    + "@define-color cc_tile rgba(0, 0, 0, 0.05); @define-color cc_tile_hover rgba(0, 0, 0, 0.09);\n"
    + "@define-color cc_bubble rgba(0, 0, 0, 0.08); @define-color cc_trough rgba(0, 0, 0, 0.10);\n"
    + "@define-color cc_fill #ffffff;\n")

cc = {}            # stav okna (widgety a priznaky)
created = False

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function soft_brightness_path():
    return config_dir() + "/brightness"
end

function panel_text():
    return "<icon>luxos-control-center-symbolic</icon><iconclick>luxos-cc-toggle</iconclick><tool>" + i18n.T("Control Center") + "</tool>"
end

# ---- stav systemu --------------------------------------------------------------------------------

# Uzivatel prihlaseneho uctu LuxAI nebo None (cte jen soubor, bez site)
function account_user():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    raw = glib.read_text(base + "/luxai/account.json")
    if raw == "":
        return None
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        data = None
    end
    if data == None or type(data) != "Dictionary":
        return None
    end
    token = data.get("sessionToken")
    if token == None or token == "":
        return None
    end
    user = data.get("user")
    if user == None or type(user) != "Dictionary":
        return {}
    end
    return user
end

# Adapter BlueZ pres D-Bus (bez bluetoothctl, ktery bez sluzby visi sekundy): [on nebo None, text]
function bluetooth_state():
    result = [None, i18n.T("Not available")]
    try:
        bus = gio.system_bus()
        if gio.name_has_owner(bus, "org.bluez", 500):
            on = gio.get_property_value(bus, "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered") == True
            if on:
                result = [True, i18n.T("On")]
            else:
                result = [False, i18n.T("Off")]
            end
        end
    else:
        result = [None, i18n.T("Not available")]
    end
    return result
end

# Sporic dat/baterie: priznakovy soubor v ~/.config/luxos (bez spousteni skriptu)
function flag_state(name):
    return exists(config_dir() + "/" + name)
end

function dark_state():
    return glib.read_text(config_dir() + "/appearance").strip() == "dark"
end

function power_supply_dir():
    base = env.get("LUXOS_POWER_SUPPLY", "")
    if base == None or base == "":
        return "/sys/class/power_supply"
    end
    return base
end

function read_int(path):
    return text.to_int(glib.read_text(path), None)
end

# [kapacita %, stav, minuty do vybiti/nabiti nebo None] nebo None - stejny odhad jako luxos-battery
function battery():
    base = power_supply_dir()
    for name in glib.list_dir(base):
        if name.startswith("BAT"):
            cap = read_int(base + "/" + name + "/capacity")
            status = glib.read_text(base + "/" + name + "/status").strip()
            if cap == None or status == "":
                return None
            end
            return [cap, status, battery_minutes(base + "/" + name, status)]
        end
    end
    return None
end

function battery_minutes(bat, status):
    values = read_triplet(bat, "energy_now", "energy_full", "power_now")
    if values == None:
        values = read_triplet(bat, "charge_now", "charge_full", "current_now")
    end
    if values == None or values[2] <= 0:
        return None
    end
    now = values[0]
    full = values[1]
    rate = values[2]
    mins = 0
    if status == "Discharging":
        mins = now * 60 // rate
    elif status == "Charging" and full > now:
        mins = (full - now) * 60 // rate
    else:
        return None
    end
    if mins > 0 and mins < 6000:
        return mins
    end
    return None
end

function read_triplet(bat, a, b, c):
    out = []
    for name in [a, b, c]:
        value = read_int(bat + "/" + name)
        if value == None:
            return None
        end
        out.append(abs(value))
    end
    return out
end

function fmt_minutes(mins):
    if mins >= 60:
        return String(mins // 60) + " h " + String(mins % 60) + " min"
    end
    return String(mins) + " min"
end

# Cesta k podsviceni (notebook) nebo ""
function backlight():
    base = env.get("LUXOS_BACKLIGHT", "")
    if base == None or base == "":
        base = "/sys/class/backlight"
    end
    names = glib.list_dir(base)
    if len(names) == 0:
        return ""
    end
    return base + "/" + names[0]
end

# Jas v procentech: podsviceni, jinak softwarovy jas monitoru (xrandr); None kdyz nejde zjistit
function brightness():
    bl = backlight()
    if bl != "":
        value = read_int(bl + "/brightness")
        maximum = read_int(bl + "/max_brightness")
        if value == None or maximum == None or maximum == 0:
            return None
        end
        return Int(Float(value * 100) / Float(maximum) + 0.5)
    end
    soft = read_int(soft_brightness_path())
    if soft == None:
        return 100
    end
    return soft
end

# ---- stavba UI --------------------------------------------------------------------------------------

function label(text_value, class_name, xalign):
    lab = gtk.label_new(text_value)
    call gtk.label_set_xalign(lab, xalign)
    if class_name != "":
        call gtk.widget_add_class(lab, class_name)
    end
    return lab
end

# Dlazdice: {button, image, title, sub, action}
function tile_new(icon, title, action):
    tile = {"action": action}
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.widget_add_class(button, "tile")
    box = gtk.box_new(gtk.HORIZONTAL, 10)
    bubble = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_halign(bubble, gtk.ALIGN_CENTER)
    call gtk.widget_set_valign(bubble, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(bubble, "bubble")
    image = gtk.image_new_from_icon_name(icon, gtk.ICON_MENU)
    call gtk.widget_set_hexpand(image, True)
    call gtk.widget_set_vexpand(image, True)
    call gtk.box_pack_start(bubble, image, True, True, 0)
    call gtk.box_pack_start(box, bubble, False, False, 0)
    column = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(column, gtk.ALIGN_CENTER)
    # pevna sirka: delsi preklady ("Sporic baterie") se zkrati, okno se nerozsiri za okraj
    title_label = label(title, "title", 0)
    call gtk.label_set_ellipsize(title_label, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(title_label, 12)
    call gtk.widget_set_tooltip(title_label, title)
    sub = label("", "sub", 0)
    call gtk.label_set_ellipsize(sub, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(sub, 12)
    call gtk.box_pack_start(column, title_label, False, False, 0)
    call gtk.box_pack_start(column, sub, False, False, 0)
    call gtk.box_pack_start(box, column, True, True, 0)
    call gtk.container_add(button, box)
    tile["button"] = button
    tile["image"] = image
    tile["title"] = title_label
    tile["sub"] = sub
    call gtk.connect_data(button, "clicked", 0, on_tile_clicked, tile)
    return tile
end

function on_tile_clicked(tile, button):
    action = tile["action"]
    call action()
    return 0
end

# on: True/False/None (None = vypnuto), sub: text nebo None (beze zmeny)
function tile_set_state(tile, on, sub):
    call gtk.widget_set_class(tile["button"], "on", on == True)
    if sub != None:
        call gtk.label_set_text(tile["sub"], sub)
    end
    return 0
end

function tile_is_on(tile):
    return gtk.widget_has_class(tile["button"], "on")
end

# Posuvnik s ikonou: {box, scale, icon, lock, on_change, on_icon}
function slider_new(title, icon, on_change, on_icon):
    row = {"lock": False, "on_change": on_change, "on_icon": on_icon}
    box = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_add_class(box, "section")
    call gtk.box_pack_start(box, label(title, "title", 0), False, False, 0)
    line = gtk.box_new(gtk.HORIZONTAL, 8)
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.button_set_relief(button, gtk.RELIEF_NONE)
    image = gtk.image_new_from_icon_name(icon, gtk.ICON_MENU)
    call gtk.container_add(button, image)
    call gtk.connect_data(button, "clicked", 0, on_slider_icon, row)
    scale = gtk.scale_new_with_range(gtk.HORIZONTAL, 0, 100, 1)
    call gtk.scale_set_draw_value(scale, False)
    call gtk.widget_set_hexpand(scale, True)
    call gtk.connect_data(scale, "value-changed", 0, on_slider_changed, row)
    call gtk.box_pack_start(line, button, False, False, 0)
    call gtk.box_pack_start(line, scale, True, True, 0)
    call gtk.box_pack_start(box, line, False, False, 0)
    row["box"] = box
    row["scale"] = scale
    row["icon"] = image
    return row
end

function on_slider_icon(row, button):
    handler = row["on_icon"]
    if handler != None:
        call handler()
    end
    return 0
end

function on_slider_changed(row, scale):
    if row["lock"]:
        return 0
    end
    handler = row["on_change"]
    call handler(gtk.range_get_value(scale))
    return 0
end

function slider_set_value(row, value):
    row["lock"] = True
    call gtk.range_set_value(row["scale"], value)
    row["lock"] = False
    return 0
end

function footer_button(box, title, command):
    button = gtk.button_new(title)
    call gtk.widget_set_can_focus(button, False)
    call gtk.widget_add_class(button, "footer")
    call gtk.connect_data(button, "clicked", 0, on_launch_clicked, command)
    call gtk.box_pack_start(box, button, False, False, 0)
    return button
end

# Spusti program a zavre okno
function on_launch_clicked(command, button):
    call glib.spawn_quiet([command])
    call close()
    return 0
end

function media_button(box, name, icon, size):
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.widget_set_valign(button, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(button, "media")
    call gtk.container_add(button, gtk.image_new_from_icon_name(icon, size))
    call gtk.connect_data(button, "clicked", 0, on_media_clicked, name)
    call gtk.box_pack_start(box, button, False, False, 0)
    return button
end

function on_media_clicked(name, button):
    # Ikona se prepne hned po kliknuti (hlidac stav zmeni lokalne), prehravac ji pak potvrdi signalem
    if cc["player"] != None and cc["mpris"]:
        call mpris.send(cc["player"], name)
    end
    return 0
end

function css_text():
    name = gtk.settings_theme_name().lower()
    if name.find("dark") >= 0:
        return DARK + CSS
    end
    return LIGHT + CSS
end

# Svetly/tmavy rezim se muze prepnout za behu (automaticky podle slunce)
function on_theme_changed(pspec, settings):
    call gtk.css_set(cc["provider"], css_text())
    return 0
end

# Skryte okno Ovladaciho centra se styly podle motivu
function create():
    global created
    if created:
        return 0
    end
    created = True
    cc["provider"] = gtk.css_load(css_text())
    # Profilova fotka (~/.face) jako pozadi kolecka profilu - vlastni styl, meni se jen s fotkou
    cc["face_provider"] = gtk.css_load("")
    cc["face_key"] = ""
    call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme_changed)
    cc["player"] = None
    cc["media_art"] = None
    cc["media_dirty"] = True
    cc["timer"] = 0
    cc["placed"] = [0, 0]
    cc["pending"] = {}
    cc["mpris"] = False
    cc["muted"] = False
    cc["test_log"] = env.get("LUXOS_CC_TEST_LOG", "")
    if cc["test_log"] == None:
        cc["test_log"] = ""
    end

    win = gtk.window_new(i18n.T("Control Center"))
    cc["win"] = win
    call gtk.widget_add_class(win, "cc")
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_stick(win)
    call gtk.window_set_rgba(win)
    # vlastni WM_CLASS i ve sdilenem procesu luxos-hub
    call gtk.window_set_wmclass(win, "luxos-control-center", "Luxos-control-center")

    outer = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_add_class(outer, "cc-box")
    call gtk.widget_set_size_request(outer, 340, -1)
    call gtk.container_add(win, outer)

    # Profil: ucet LuxAI (~/.config/luxai/account.json), klik otevre Ucet LuxAI
    prof = gtk.button_new_empty()
    call gtk.widget_set_can_focus(prof, False)
    call gtk.button_set_relief(prof, gtk.RELIEF_NONE)
    call gtk.widget_add_class(prof, "plain")
    pbox = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(pbox, "section")
    avatar = gtk.label_new("")
    call gtk.widget_add_class(avatar, "avatar")
    cc["p_avatar"] = avatar
    ptext = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(ptext, gtk.ALIGN_CENTER)
    cc["p_title"] = label("", "title", 0)
    cc["p_sub"] = label("", "sub", 0)
    call gtk.box_pack_start(ptext, cc["p_title"], False, False, 0)
    call gtk.box_pack_start(ptext, cc["p_sub"], False, False, 0)
    call gtk.box_pack_start(pbox, avatar, False, False, 0)
    call gtk.box_pack_start(pbox, ptext, True, True, 0)
    call gtk.box_pack_end(pbox, gtk.image_new_from_icon_name("go-next-symbolic", gtk.ICON_MENU), False, False, 0)
    call gtk.container_add(prof, pbox)
    call gtk.connect_data(prof, "clicked", 0, on_launch_clicked, "luxos-account")
    call gtk.box_pack_start(outer, prof, False, False, 0)

    grid = gtk.grid_new()
    call gtk.grid_set_row_spacing(grid, 8)
    call gtk.grid_set_column_spacing(grid, 8)
    call gtk.grid_set_column_homogeneous(grid, True)
    cc["t_wifi"] = tile_new("network-wireless-symbolic", i18n.T("Wi-Fi"), toggle_wifi)
    cc["t_bt"] = tile_new("bluetooth-active-symbolic", i18n.T("Bluetooth"), toggle_bt)
    cc["t_dnd"] = tile_new("notifications-disabled-symbolic", i18n.T("Do Not Disturb"), toggle_dnd)
    cc["t_dark"] = tile_new("weather-clear-night-symbolic", i18n.T("Dark Mode"), toggle_dark)
    cc["t_data"] = tile_new("network-cellular-signal-good-symbolic", i18n.T("Data Saver"), toggle_data)
    cc["t_power"] = tile_new("battery-level-50-symbolic", i18n.T("Battery Saver"), toggle_power)
    tiles = [cc["t_wifi"], cc["t_bt"], cc["t_dnd"], cc["t_dark"], cc["t_data"], cc["t_power"]]
    index = 0
    while index < 6:
        tile = tiles[index]
        call gtk.grid_attach(grid, tile["button"], index % 2, index // 2, 1, 1)
        index += 1
    end
    call gtk.box_pack_start(outer, grid, False, False, 0)

    # QR kod Wi-Fi: pripojeno = sdilet sit (luxos-wifi-qr), Wi-Fi zapnuta bez site = naskenovat kod
    wifi_qr = gtk.button_new(i18n.T("Share Wi-Fi with QR Code…"))
    call gtk.widget_set_can_focus(wifi_qr, False)
    call gtk.widget_add_class(wifi_qr, "footer")
    call gtk.widget_set_halign(wifi_qr, gtk.ALIGN_START)
    call gtk.connect(wifi_qr, "clicked", on_wifi_qr_clicked)
    call gtk.widget_set_no_show_all(wifi_qr, True)
    cc["wifi_qr"] = wifi_qr
    cc["wifi_qr_scan"] = False
    cc["wifi_signin"] = False
    cc["wifi_qr_mode"] = ""
    call gtk.box_pack_start(outer, wifi_qr, False, False, 0)

    # Klik na ikonu jasu otevre Monitory (rozliseni, velikost textu)
    cc["s_bright"] = slider_new(i18n.T("Display"), "display-brightness-symbolic", set_brightness, open_displays)
    call gtk.box_pack_start(outer, cc["s_bright"]["box"], False, False, 0)
    cc["s_vol"] = slider_new(i18n.T("Sound"), "audio-volume-high-symbolic", set_volume, toggle_mute)
    call gtk.box_pack_start(outer, cc["s_vol"]["box"], False, False, 0)

    # Prave hrajici hudba (MPRIS: Firefox, Spotify, VLC, mpv...) - jen kdyz nejaky prehravac bezi
    media = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(media, "section")
    cc["media_box"] = media
    cc["m_art"] = gtk.image_new()
    art_wrap = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_valign(art_wrap, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(art_wrap, "art")
    call gtk.box_pack_start(art_wrap, cc["m_art"], True, True, 0)
    call gtk.box_pack_start(media, art_wrap, False, False, 0)
    mtext = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(mtext, gtk.ALIGN_CENTER)
    cc["m_title"] = label("", "title", 0)
    call gtk.label_set_ellipsize(cc["m_title"], gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(cc["m_title"], 18)
    cc["m_artist"] = label("", "sub", 0)
    call gtk.label_set_ellipsize(cc["m_artist"], gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(cc["m_artist"], 18)
    call gtk.box_pack_start(mtext, cc["m_title"], False, False, 0)
    call gtk.box_pack_start(mtext, cc["m_artist"], False, False, 0)
    call gtk.box_pack_start(media, mtext, True, True, 0)
    cc["m_prev"] = media_button(media, "Previous", "media-skip-backward-symbolic", gtk.ICON_MENU)
    cc["m_play"] = media_button(media, "PlayPause", "media-playback-start-symbolic", gtk.ICON_LARGE_TOOLBAR)
    cc["m_next"] = media_button(media, "Next", "media-skip-forward-symbolic", gtk.ICON_MENU)
    call gtk.widget_set_no_show_all(media, True)
    call gtk.box_pack_start(outer, media, False, False, 0)
    try:
        call mpris.init(gio.session_bus())
        cc["mpris"] = True
        call mpris.connect(on_media_changed)
    else:
        call eprint("luxos-control-center: media: " + String(last_error()))
    end

    bat_box = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(bat_box, "section")
    bat_button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(bat_button, False)
    call gtk.button_set_relief(bat_button, gtk.RELIEF_NONE)
    call gtk.widget_add_class(bat_button, "plain")
    call gtk.connect_data(bat_button, "clicked", 0, on_launch_clicked, "luxos-power")
    cc["bat_icon"] = gtk.image_new_from_icon_name("battery-level-50-symbolic", gtk.ICON_LARGE_TOOLBAR)
    bat_text = gtk.box_new(gtk.VERTICAL, 0)
    cc["bat_title"] = label("", "title", 0)
    cc["bat_sub"] = label("", "sub", 0)
    call gtk.box_pack_start(bat_text, cc["bat_title"], False, False, 0)
    call gtk.box_pack_start(bat_text, cc["bat_sub"], False, False, 0)
    call gtk.box_pack_start(bat_box, cc["bat_icon"], False, False, 0)
    call gtk.box_pack_start(bat_box, bat_text, True, True, 0)
    call gtk.box_pack_end(bat_box, gtk.image_new_from_icon_name("go-next-symbolic", gtk.ICON_MENU), False, False, 0)
    call gtk.container_add(bat_button, bat_box)
    cc["bat_wrap"] = bat_button
    call gtk.box_pack_start(outer, bat_button, False, False, 0)

    footer = gtk.box_new(gtk.HORIZONTAL, 4)
    call footer_button(footer, i18n.T("Desktop & Dock…"), "luxos-settings")
    call footer_button(footer, i18n.T("Battery…"), "luxos-power")
    call footer_button(footer, i18n.T("All Settings…"), "xfce4-settings-manager")
    call gtk.box_pack_start(outer, footer, False, False, 0)

    call gtk.connect(win, "focus-out-event", on_focus_out)
    call gtk.connect(win, "key-press-event", on_key)
    call gtk.connect(win, "realize", on_realize)
    call gtk.connect(win, "configure-event", on_configure)
    # Na pozadi: zavreni okno jen skryje, dalsi klik v liste ho hned ukaze (SIGUSR1)
    call gtk.connect(win, "delete-event", on_delete)
    call refresh_fast()
    call refresh_slow()
    return 0
end

function log_test(message):
    if cc["test_log"] != "":
        call appendfile(cc["test_log"], message + "\n")
    end
    return 0
end

function is_visible():
    if not created:
        return False
    end
    return gtk.widget_get_visible(cc["win"])
end

function toggle():
    if not created:
        call create()
    end
    if gtk.widget_get_visible(cc["win"]):
        call close()
        return 0
    end
    call refresh_fast()
    if cc["media_dirty"]:
        call apply_media()
    end
    call gtk.widget_show_all(cc["win"])
    call place()
    stamp = gtk.get_current_event_time()
    if stamp == 0:
        stamp = gtk.CURRENT_TIME
    end
    call gtk.window_present_with_time(cc["win"], stamp)
    # udaje ze sluzeb (nmcli, pactl, xfconf-query) az po zobrazeni okna: spousteni procesu nebrzdi
    # prvni vykresleni (Python je mel ve vlakne)
    call glib.idle_add(refresh_slow_once)
    if cc["timer"] == 0:
        cc["timer"] = glib.timeout_add_seconds(3, periodic)
    end
    call log_test("shown")
    return 0
end

function refresh_slow_once():
    call refresh_slow()
    return False
end

function close():
    call gtk.widget_hide(cc["win"])
    call log_test("hidden")
    return 0
end

# umisteni vpravo pod horni listou na monitoru s kurzorem
function place():
    pointer = gtk.pointer_position()
    geo = gtk.monitor_at_point_workarea(pointer[0], pointer[1])
    size = gtk.window_get_size(cc["win"])
    w = size[0]
    h = size[1]
    # cele okno vzdy na monitoru (i kdyz po zobrazeni zmeni velikost - viz on_size)
    x = max(geo[0] + 4, geo[0] + geo[2] - w - 8)
    y = geo[1] + 6
    if y + h > geo[1] + geo[3] - 4:
        y = max(geo[1], geo[1] + geo[3] - h - 4)
    end
    call gtk.window_move(cc["win"], x, y)
    cc["placed"] = [w, h]
    return 0
end

function on_realize(window):
    call place()
    return 0
end

function on_configure(event, window):
    call glib.idle_add(on_size)
    return False
end

# obsah (baterie, prehravani, delsi texty) zmenil velikost okna: znovu umistit
function on_size():
    if gtk.widget_get_visible(cc["win"]) and gtk.window_get_size(cc["win"]) != cc["placed"]:
        call place()
    end
    return False
end

function on_focus_out(event, window):
    # testy pod Xvfb bez spravce oken: okno by se po zobrazeni hned zavrelo
    if env.get("LUXOS_HUB_NO_AUTOHIDE", "") == "1":
        return False
    end
    call glib.timeout_add(120, close_if_unfocused)
    return False
end

# is_active() zustava po kliknuti na plochu (xfdesktop drzi grab) chybne True,
# proto rozhoduje i skutecne aktivni okno podle spravce oken (_NET_ACTIVE_WINDOW)
function close_if_unfocused():
    active = gtk.screen_active_window()
    own = gtk.widget_get_window(cc["win"])
    if not gtk.window_is_active(cc["win"]) or (active != 0 and active != own):
        call close()
    end
    if active != 0:
        call glib.object_unref(active)
    end
    return False
end

function on_key(event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        call close()
        return True
    end
    return False
end

function on_delete(event, window):
    call close()
    return True
end

# ---- obnova stavu ------------------------------------------------------------------------------------

function on_off(on):
    if on:
        return i18n.T("On")
    end
    return i18n.T("Off")
end

# Profilova fotka uctu (~/.face z luxos-profile-picture) misto pismena; styl se meni jen po zmene souboru
function face_update():
    path = glib.home_dir() + "/.face"
    st = glib.stat(path)
    key = ""
    if len(st) > 0 and st[0] > 0:
        key = path + ":" + String(st[1])
    end
    if key == cc["face_key"]:
        return 0
    end
    cc["face_key"] = key
    css = ""
    if key != "":
        uri = "file://" + path.replace("%", "%25").replace(" ", "%20").replace("\"", "%22")
        css = ".avatar.photo { background-image: url(\"" + uri + "\"); background-size: cover; background-position: center; color: transparent; }\n"
    end
    call gtk.css_set(cc["face_provider"], css)
    call gtk.widget_set_class(cc["p_avatar"], "photo", key != "")
    if key != "":
        call log_test("photo")
    end
    return 0
end

# Okamzite udaje (soubory v ~/.config a /sys) - bez spousteni programu
function refresh_fast():
    user = account_user()
    name = ""
    if user != None:
        name = text_value(user.get("displayName"))
        if name == "":
            name = text_value(user.get("email"))
        end
    end
    initial = "✦"
    if name != "":
        initial = name[0:1].upper()
    end
    call gtk.label_set_text(cc["p_avatar"], initial)
    call face_update()
    if user != None:
        call gtk.label_set_text(cc["p_title"], name)
        call gtk.label_set_text(cc["p_sub"], i18n.T("LuxAI Account"))
    else:
        call gtk.label_set_text(cc["p_title"], i18n.T("Sign in to LuxAI"))
        call gtk.label_set_text(cc["p_sub"], i18n.T("AI in LuxAI, Lux Code and LSL IDE"))
    end
    dark = dark_state()
    call tile_set_state(cc["t_dark"], dark, on_off(dark))
    data = flag_state("datasaver")
    call tile_set_state(cc["t_data"], data, on_off(data))
    power = flag_state("powersaver")
    call tile_set_state(cc["t_power"], power, on_off(power))
    b = brightness()
    if b != None:
        call slider_set_value(cc["s_bright"], b)
    end
    bat = battery()
    call gtk.widget_set_no_show_all(cc["bat_wrap"], bat == None)
    call gtk.widget_set_visible(cc["bat_wrap"], bat != None)
    if bat != None:
        cap = bat[0]
        status = bat[1]
        mins = bat[2]
        level = min(100, (cap + 5) // 10 * 10)
        icon = "battery-level-" + String(level)
        if status == "Charging":
            icon = icon + "-charging"
        end
        call gtk.image_set_from_icon_name(cc["bat_icon"], icon + "-symbolic", gtk.ICON_LARGE_TOOLBAR)
        call gtk.label_set_text(cc["bat_title"], i18n.T("Battery") + "  " + String(cap) + " %")
        sub = i18n.T("Fully charged")
        if status == "Charging":
            sub = i18n.T("Charging")
        elif status == "Discharging":
            sub = i18n.T("On battery")
        end
        if mins != None:
            if status == "Discharging":
                sub = sub + " · " + i18n.TF("%s remaining", [fmt_minutes(mins)])
            else:
                sub = sub + " · " + i18n.TF("%s until full", [fmt_minutes(mins)])
            end
        end
        call gtk.label_set_text(cc["bat_sub"], sub)
    end
    return 0
end

function text_value(value):
    if value == None:
        return ""
    end
    return String(value)
end

# Udaje ze sluzeb (sit, Bluetooth, zvuk, oznameni) - asynchronne, bez blokovani okna
function refresh_slow():
    call glib.spawn_capture(["nmcli", "radio", "wifi"], on_wifi_radio, 0)
    bt = bluetooth_state()
    call tile_set_state(cc["t_bt"], bt[0], bt[1])
    call glib.spawn_capture(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb"], on_dnd, 0)
    call glib.spawn_capture(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], on_volume, 0)
    return 0
end

function on_wifi_radio(unused, output, status):
    if status != 0:
        call tile_set_state(cc["t_wifi"], None, "")
        call set_wifi_qr("")
        return 0
    end
    on = output.strip() == "enabled"
    call glib.spawn_capture(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"], on_wifi_list, on)
    return 0
end

# Odkaz pod dlazdicemi: "share"/"scan" (QR kod Wi-Fi), "signin" (sit bez internetu - prihlaseni
# do site s portalem rucne, kdyz se okno neotevrelo samo) nebo "" (skryty)
function set_wifi_qr(mode):
    button = cc["wifi_qr"]
    if mode != cc["wifi_qr_mode"]:
        call log_test("wifi-qr:" + mode)
        cc["wifi_qr_mode"] = mode
    end
    if mode == "":
        call gtk.widget_set_visible(button, False)
        return 0
    end
    cc["wifi_qr_scan"] = mode == "scan"
    cc["wifi_signin"] = mode == "signin"
    if mode == "signin":
        call gtk.button_set_label(button, i18n.T("Sign In to Network…"))
    elif mode == "scan":
        call gtk.button_set_label(button, i18n.T("Join Wi-Fi with QR Code…"))
    else:
        call gtk.button_set_label(button, i18n.T("Share Wi-Fi with QR Code…"))
    end
    call gtk.widget_set_visible(button, True)
    return 0
end

function on_wifi_qr_clicked(button):
    if cc["wifi_signin"]:
        call log_test("network sign-in")
        call glib.spawn_quiet(["luxos-network-login"])
    elif cc["wifi_qr_scan"]:
        call log_test("wifi-qr scan")
        call glib.spawn_quiet(["luxos-wifi-qr", "--scan"])
    else:
        call log_test("wifi-qr share")
        call glib.spawn_quiet(["luxos-wifi-qr"])
    end
    call close()
    return 0
end

function on_wifi_list(on, output, status):
    ssid = ""
    if status == 0:
        for line in output.split("\n"):
            if line.startswith("yes:"):
                ssid = line[4:]
                break
            end
        end
    end
    if not on:
        call tile_set_state(cc["t_wifi"], False, i18n.T("Off"))
        call set_wifi_qr("")
        return 0
    end
    if ssid != "":
        call tile_set_state(cc["t_wifi"], True, ssid)
        call set_wifi_qr("share")
        call glib.spawn_capture(["nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_connectivity, 0)
        return 0
    end
    call glib.spawn_capture(["nmcli", "-t", "-f", "TYPE,STATE", "device"], on_wifi_devices, 0)
    return 0
end

# Pripojeno, ale bez internetu (omezene / portal): misto sdileni nabidnout prihlaseni do site
function on_connectivity(unused, output, status):
    state = output.strip()
    if status == 0 and (state == "portal" or state == "limited"):
        call set_wifi_qr("signin")
    end
    return 0
end

function on_wifi_devices(unused, output, status):
    wired = ""
    if status == 0:
        wired = output
    end
    if wired.find("ethernet:connected") >= 0:
        call tile_set_state(cc["t_wifi"], True, i18n.T("Ethernet"))
        call set_wifi_qr("")
    else:
        call tile_set_state(cc["t_wifi"], True, i18n.T("Not connected"))
        call set_wifi_qr("scan")
    end
    return 0
end

function on_dnd(unused, output, status):
    on = status == 0 and output.strip() == "true"
    call tile_set_state(cc["t_dnd"], on, on_off(on))
    return 0
end

function on_volume(unused, output, status):
    if status != 0 or output.strip() == "":
        return 0
    end
    level = parse_percent(output)
    call glib.spawn_capture(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], on_mute, level)
    return 0
end

# Prvni cislo s % v textu ("Volume: front-left: 65536 / 100% / 0,00 dB")
function parse_percent(output):
    index = 0
    n = len(output)
    while index < n:
        if output[index] == "%":
            start = index
            while start > 0 and text.is_digit(output[start - 1]):
                start -= 1
            end
            if start < index:
                return Int(output[start:index])
            end
        end
        index += 1
    end
    return 0
end

function on_mute(level, output, status):
    muted = status == 0 and output.strip().endswith("yes")
    cc["muted"] = muted
    call slider_set_value(cc["s_vol"], level)
    icon = "audio-volume-high-symbolic"
    if muted:
        icon = "audio-volume-muted-symbolic"
    end
    call gtk.image_set_from_icon_name(cc["s_vol"]["icon"], icon, gtk.ICON_MENU)
    return 0
end

# Obnova jen pri zobrazenem okne (skryte okno na pozadi se zbytecne nebudi)
function periodic():
    if gtk.widget_get_visible(cc["win"]):
        call refresh_slow()
        return True
    end
    cc["timer"] = 0
    return False
end

# ---- hudba a video (MPRIS): udalosti, zadne dotazovani -------------------------------------------

function on_media_changed():
    if gtk.widget_get_visible(cc["win"]):
        call apply_media()
    else:
        cc["media_dirty"] = True     # skryte okno: obalku apod. nacist az pri zobrazeni
    end
    return 0
end

function apply_media():
    cc["media_dirty"] = False
    media = None
    if cc["mpris"]:
        media = mpris.current()
    end
    if media == None:
        cc["player"] = None
        call gtk.widget_set_no_show_all(cc["media_box"], True)
        call gtk.widget_hide(cc["media_box"])
        return 0
    end
    cc["player"] = media["bus"]
    title = media["title"]
    if title == "":
        title = media["app"]
    end
    call gtk.label_set_text(cc["m_title"], title)
    artist = media["artist"]
    if artist == "" and media["title"] != "":
        artist = media["app"]
    end
    call gtk.label_set_text(cc["m_artist"], artist)
    call set_play_icon(media["playing"])
    call gtk.widget_set_sensitive(cc["m_next"], media["can_next"])
    call gtk.widget_set_sensitive(cc["m_prev"], media["can_prev"])
    art = media["art"]
    if art != cc["media_art"]:
        cc["media_art"] = art
        pixbuf = 0
        if art.startswith("file://"):
            path = glib.filename_from_uri(art)
            if path != "":
                pixbuf = gtk.pixbuf_new_from_file_at_scale(path, 42, 42, True)
            end
        end
        if pixbuf != 0:
            call gtk.image_set_from_pixbuf(cc["m_art"], pixbuf)
            call glib.object_unref(pixbuf)
        else:
            call gtk.image_set_from_icon_name(cc["m_art"], "audio-x-generic-symbolic", gtk.ICON_LARGE_TOOLBAR)
        end
    end
    if not gtk.widget_get_visible(cc["media_box"]):
        call gtk.widget_set_no_show_all(cc["media_box"], False)
        call gtk.widget_show_all(cc["media_box"])
    end
    return 0
end

function set_play_icon(playing):
    icon = "media-playback-start-symbolic"
    if playing:
        icon = "media-playback-pause-symbolic"
    end
    call gtk.image_set_from_icon_name(gtk.bin_get_child(cc["m_play"]), icon, gtk.ICON_LARGE_TOOLBAR)
    return 0
end

# ---- akce ----------------------------------------------------------------------------------------------

function toggle_wifi():
    call glib.spawn_capture(["nmcli", "radio", "wifi"], on_toggle_wifi_state, 0)
    return 0
end

function on_toggle_wifi_state(unused, output, status):
    target = "on"
    if status == 0 and output.strip() == "enabled":
        target = "off"
    end
    call glib.spawn_watched_data(["nmcli", "radio", "wifi", target], on_command_done_slow, 0)
    return 0
end

function on_command_done_slow(unused, pid, status):
    call refresh_slow()
    return 0
end

# Okno Bluetooth: zapnuti, sparovana zarizeni i pripojeni noveho
function toggle_bt():
    call glib.spawn_quiet(["luxos-bluetooth"])
    call close()
    return 0
end

function toggle_dnd():
    on = not tile_is_on(cc["t_dnd"])
    call tile_set_state(cc["t_dnd"], on, on_off(on))
    value = "false"
    if on:
        value = "true"
    end
    call glib.spawn_quiet(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb", "-n", "-t", "bool", "-s", value])
    return 0
end

function toggle_dark():
    call glib.spawn_quiet(["luxos-appearance", "toggle"])
    call close()
    return 0
end

function toggle_data():
    return toggle_flag(cc["t_data"], "datasaver", "luxos-datasaver")
end

function toggle_power():
    return toggle_flag(cc["t_power"], "powersaver", "luxos-powersaver")
end

# Dlazdice se prepne hned, prikaz (sit, systemova cast, monitor) dobehne na pozadi
function toggle_flag(tile, flag, command):
    on = not flag_state(flag)
    call tile_set_state(tile, on, on_off(on))
    mode = "off"
    if on:
        mode = "on"
    end
    pid = glib.spawn_watched_data([command, mode], on_flag_done, 0)
    if pid == 0:
        call refresh_fast()
    end
    return 0
end

function on_flag_done(unused, pid, status):
    call refresh_fast()
    return 0
end

function set_volume(value):
    call glib.spawn_quiet(["pactl", "set-sink-volume", "@DEFAULT_SINK@", String(value) + "%"])
    # posunuti ztlumeneho zvuku ho zapne (jako v macOS) - jinak by posuvnik "nefungoval"
    if cc["muted"]:
        cc["muted"] = False
        call glib.spawn_quiet(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        call gtk.image_set_from_icon_name(cc["s_vol"]["icon"], "audio-volume-high-symbolic", gtk.ICON_MENU)
    end
    return 0
end

function toggle_mute():
    call glib.spawn_watched_data(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], on_command_done_slow, 0)
    return 0
end

function open_displays():
    call glib.spawn_quiet(["luxos-display-settings"])
    call close()
    return 0
end

function set_brightness(value):
    v = max(value, 10)
    if backlight() != "":
        call glib.spawn_quiet(["brightnessctl", "-q", "set", String(v) + "%"])
        return 0
    end
    # Monitor bez podsviceni (stolni pocitac, VM): softwarovy jas vsech vystupu
    call glib.mkdir_p(config_dir())
    call writefile(soft_brightness_path(), String(v))
    call glib.spawn_quiet(["luxos-displays", "brightness", String(v)])
    return 0
end
