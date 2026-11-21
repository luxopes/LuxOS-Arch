# LuxOS - Sporic a zamek: kdy se spusti setric obrazovky, jaky a kdy chtit heslo.
# Relace X11: kanal xfconf xfce4-screensaver pres xfconf-query (sluzbu setrice dal pouziva xfce4-screensaver).
# Wayland: setric neni, zamyka luxos-lock-session podle stejneho kanalu (necinnost = /saver/idle-activation/delay
# + /lock/saver-activation/delay); xfconfd tam nebezi, okno cte a zapisuje primo soubor kanalu (luxos_xfconf),
# zmenu luxos-lock-session hned nacte.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_text as text
load luxos_xfconf as xfconf
load luxos_settings_ui as ui

CH = "xfce4-screensaver"
SAVER = "/usr/lib/xfce4-screensaver/luxos"
FPRINT_SERVICE = "/usr/share/dbus-1/system-services/net.reactivated.Fprint.service"
# id tematu xfce4-screensaver (screensavers-<soubor .desktop>) -> styl luxos-screensaver
THEMES = [["screensavers-luxos-wallpaper", "desktop", "Desktop wallpaper and clock"],
    ["screensavers-luxos", "wallpapers", "LuxOS - wallpapers and clock"],
    ["screensavers-luxos-analog", "analog", "LuxOS wallpapers with a clock"],
    ["screensavers-luxos-clock", "clock", "Clock"],
    ["screensavers-luxos-aurora", "aurora", "Aurora"],
    ["screensavers-luxos-photos", "photos", "Photos"],
    ["screensavers-luxos-logo", "logo", "Floating Logo"],
    ["blank", "blank", "Black screen"]]
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 10px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.6; }\n"

app = {"kind": 0, "conf": {}}

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

# ---- kanal xfce4-screensaver ------------------------------------------------------------------------------------

function conf_get(prop, default):
    if wayland():
        return app["conf"].get(prop, default)
    end
    value = ui.run(["xfconf-query", "-c", CH, "-p", prop])
    if value == "":
        return default
    end
    return value
end

function conf_set(prop, kind, value):
    if wayland():
        return xfconf.write(CH, {prop: [kind, String(value)]})
    end
    return ui.run(["xfconf-query", "-c", CH, "-p", prop, "-n", "-t", kind, "-s", String(value)])
end

function minutes(value, default):
    if text.is_digits(value):
        return Int(value)
    end
    return default
end

function minute_options(first):
    return [[0, i18n.T(first)], [1, i18n.T("1 minute")], [2, i18n.T("2 minutes")], [5, i18n.T("5 minutes")],
            [10, i18n.T("10 minutes")], [15, i18n.T("15 minutes")], [30, i18n.T("30 minutes")], [60, i18n.T("1 hour")]]
end

# ---- relace X11: setric a heslo po spusteni setrice ------------------------------------------------------------

function build_x11(page):
    g = ui.group(page, i18n.T("Screen saver"))
    idle_on = conf_get("/saver/idle-activation/enabled", "true") == "true"
    delay = "0"
    if idle_on:
        delay = conf_get("/saver/idle-activation/delay", "10")
    end
    call ui.row(g, i18n.T("Start after inactivity of"), "", ui.combo(minute_options("Never"), delay, i18n.T("%d min").replace("%d", "%s"), on_start_x11, 0))
    current = "blank"
    if conf_get("/saver/mode", "0") == "2":
        themes = [line.strip() for line in conf_get("/saver/themes/list", "").split("\n") if line.strip() != ""]
        current = "screensavers-luxos-wallpaper"
        if len(themes) > 0:
            current = themes[len(themes) - 1]
        end
    end
    kind = ui.combo([[t[0], i18n.T(t[2])] for t in THEMES], current, "", on_kind_x11, 0)
    app["kind"] = kind
    preview = gtk.button_new(i18n.T("Preview"))
    call gtk.connect(preview, "clicked", on_preview)
    box = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.box_pack_start(box, kind, False, False, 0)
    call gtk.box_pack_start(box, preview, False, False, 0)
    call ui.row(g, i18n.T("Screen saver"), "", box)

    g = ui.group(page, i18n.T("Lock"))
    lock_on = conf_get("/lock/enabled", "true") == "true" and conf_get("/lock/saver-activation/enabled", "true") == "true"
    lock_delay = "never"
    if lock_on:
        lock_delay = conf_get("/lock/saver-activation/delay", "0")
    end
    options = [[0, i18n.T("Immediately")], [1, i18n.T("After 1 minute")], [5, i18n.T("After 5 minutes")],
               [15, i18n.T("After 15 minutes")], ["never", i18n.T("Never")]]
    call ui.row(g, i18n.T("Require password after the screen saver starts"), i18n.T("The screen saver protects your computer while you are away."),
                ui.combo(options, lock_delay, i18n.T("%d min").replace("%d", "%s"), on_require_x11, 0))
    return g
end

function on_start_x11(unused, value):
    m = minutes(value, 0)
    call conf_set("/saver/idle-activation/enabled", "bool", "true" if m > 0 else "false")
    if m > 0:
        call conf_set("/saver/idle-activation/delay", "int", m)
    end
    return 0
end

function on_kind_x11(unused, theme):
    if theme != "" and theme != "blank":
        call ui.run(["xfconf-query", "-c", CH, "-p", "/saver/themes/list", "-n", "-a", "-t", "string", "-s", theme])
        return conf_set("/saver/mode", "int", 2)
    end
    return conf_set("/saver/mode", "int", 0)
end

# Nahled vzdy toho, co je prave vybrane (i cerne obrazovky)
function on_preview(button):
    style = "blank"
    for t in THEMES:
        if t[0] == ui.combo_active_id(app["kind"]):
            style = t[1]
        end
    end
    return ui.launch([SAVER, "--window", "--style", style])
end

function on_require_x11(unused, value):
    if value == "never":
        return conf_set("/lock/saver-activation/enabled", "bool", "false")
    end
    call conf_set("/lock/enabled", "bool", "true")
    call conf_set("/lock/saver-activation/enabled", "bool", "true")
    return conf_set("/lock/saver-activation/delay", "int", value)
end

# ---- Wayland: zamek po necinnosti (luxos-lock-session) -----------------------------------------------------------

function idle_lock_minutes():
    c = app["conf"]
    if c.get("/saver/idle-activation/enabled", "true") == "false" or c.get("/lock/enabled", "true") == "false" or c.get("/lock/saver-activation/enabled", "true") == "false":
        return 0
    end
    return minutes(c.get("/saver/idle-activation/delay", ""), 10) + minutes(c.get("/lock/saver-activation/delay", ""), 0)
end

function build_wayland(page):
    g = ui.group(page, i18n.T("Lock"))
    combo = ui.combo(minute_options("Never"), String(idle_lock_minutes()), i18n.T("%d min").replace("%d", "%s"), on_idle_lock, 0)
    call ui.row(g, i18n.T("Lock the screen after inactivity of"), "", combo)
    return g
end

# Jedna hodnota misto setrice + zpozdeni hesla: necinnost = cas zamceni, heslo hned
function on_idle_lock(unused, value):
    m = minutes(value, 0)
    if m == 0:
        return xfconf.write(CH, {"/saver/idle-activation/enabled": ["bool", "false"]})
    end
    return xfconf.write(CH, {"/saver/idle-activation/enabled": ["bool", "true"], "/saver/idle-activation/delay": ["int", String(m)],
                             "/lock/enabled": ["bool", "true"], "/lock/saver-activation/enabled": ["bool", "true"],
                             "/lock/saver-activation/delay": ["int", "0"]})
end

# ---- spolecne ------------------------------------------------------------------------------------------------------

function on_sleep(unused, on):
    return conf_set("/lock/sleep-activation", "bool", "true" if on else "false")
end

function on_launch(argv, button):
    return ui.launch(argv)
end

function on_destroy(window):
    call gtk.main_quit()
    return 0
end

function main():
    call glib.set_prgname("luxos-lock-settings")
    call gtk.init()
    call gtk.css_load(CSS)
    if wayland():
        app["conf"] = xfconf.channel(CH)
    end
    ui.state["hint_chars"] = 46
    # vyska podle obsahu (drive 520 px s prazdnou plochou dole)
    window = ui.window(i18n.T("Screen Saver & Lock"), "preferences-desktop-screensaver", 560, -1, 0, 0)
    call gtk.window_set_wmclass(window, "luxos-lock-settings", "luxos-lock-settings")
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 6, 22)
    call gtk.container_add(window, page)
    g = None
    if wayland():
        g = build_wayland(page)
    else:
        g = build_x11(page)
    end
    call ui.row(g, i18n.T("Lock when the computer goes to sleep"), "", ui.switch(conf_get("/lock/sleep-activation", "true") == "true", on_sleep, 0))
    # otisk prstu jen s nainstalovanym fprintd (luxos-drivers ho pridava pri nalezene ctecce)
    if exists(env.get("LUXOS_FPRINT_SERVICE", FPRINT_SERVICE)):
        fp = gtk.button_new(i18n.T("Set Up…"))
        call glib.connect_data(fp, "clicked", 0, on_launch, ["luxos-fingerprint"])
        call ui.row(g, i18n.T("Fingerprint Login"), i18n.T("Unlock and log in with your fingerprint instead of the password."), fp)
    end
    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bottom, 0, 0, 16, 0)
    now = gtk.button_new(i18n.T("Lock Now"))
    lock = ["xflock4"]
    if wayland():
        # luxos-lock-session zamyka na signal Lock relace v logind
        lock = ["loginctl", "lock-session"]
    end
    call glib.connect_data(now, "clicked", 0, on_launch, lock)
    call gtk.box_pack_start(bottom, now, False, False, 0)
    call gtk.box_pack_start(page, bottom, False, False, 0)
    call gtk.connect(window, "destroy", on_destroy)
    call gtk.widget_show_all(window)
    call gtk.main()
end

call main()
