# LuxOS - Nastaveni > Oznameni (drive xfce4-notifyd-config): Nerusit, jak dlouho zustane bublina, zvuky,
# historie v liste a ktere aplikace smi ukazovat bubliny.
# Wayland: ~/.config/luxos/notifications.conf, ktery luxos-notify sleduje a zmenu hned pouzije; aplikace, ktere
# uz neco oznamily, zapisuje luxos-notify do ~/.local/share/luxos/notification-apps.
# Relace X11: kanal xfconf xfce4-notifyd pres xfconf-query (stejne volby, xfce4-notifyd je cte za behu).
# Upozorneni na letni/zimni cas (TIME_CHANGE, luxos-hub) je v notifications.conf v obou relacich.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_text as text
load luxos_settings_ui as ui

CH = "xfce4-notifyd"
DEFAULT_SECONDS = 6
DEFAULT_HISTORY = 100

app = {"conf": {}}

function conf_path():
    return glib.user_config_dir() + "/luxos/notifications.conf"
end

function apps_path():
    return glib.user_data_dir() + "/luxos/notification-apps"
end

function number(value, default):
    if text.is_digits(value):
        return Int(value)
    end
    return default
end

# ---- kanal xfce4-notifyd (X11) ----------------------------------------------------------------------------------

function xf_get(prop, default):
    value = ui.run(["xfconf-query", "-c", CH, "-p", prop])
    if value == "":
        return default
    end
    return value
end

function xf_set(prop, kind, value):
    return ui.run(["xfconf-query", "-c", CH, "-p", prop, "-n", "-t", kind, "-s", String(value)])
end

# Pole vypise xfconf-query jako "Value is an array with N items:", prazdny radek a polozky po radcich
function xf_list(prop):
    out = ui.run(["xfconf-query", "-c", CH, "-p", prop])
    lines = out.split("\n")
    if len(lines) > 0 and lines[0].startswith("Value is an array"):
        lines = lines[1:]
    end
    return [line.strip() for line in lines if line.strip() != ""]
end

function xf_set_list(prop, items):
    if len(items) == 0:
        return ui.run(["xfconf-query", "-c", CH, "-p", prop, "-r"])
    end
    argv = ["xfconf-query", "-c", CH, "-p", prop, "-n", "-a"]
    for item in items:
        argv = argv + ["-t", "string", "-s", item]
    end
    return ui.run(argv)
end

# ---- jednotne cteni a zapis voleb -------------------------------------------------------------------------------

function dnd():
    if ui.wayland():
        return app["conf"].get("DO_NOT_DISTURB", "") == "true"
    end
    return xf_get("/do-not-disturb", "false") == "true"
end

function banner_seconds():
    if ui.wayland():
        return number(app["conf"].get("BANNER_SECONDS", ""), DEFAULT_SECONDS)
    end
    return number(xf_get("/expire-timeout", ""), DEFAULT_SECONDS)
end

function sounds():
    if ui.wayland():
        return app["conf"].get("SOUNDS", "1") != "0"
    end
    return xf_get("/mute-sounds", "false") != "true"
end

function history():
    if ui.wayland():
        return app["conf"].get("HISTORY", "1") != "0"
    end
    return xf_get("/notification-log", "true") == "true"
end

function history_size():
    if ui.wayland():
        return number(app["conf"].get("HISTORY_SIZE", ""), DEFAULT_HISTORY)
    end
    return number(xf_get("/log-max-size", ""), DEFAULT_HISTORY)
end

function muted():
    if ui.wayland():
        return [a for a in app["conf"].get("MUTED_APPS", "").split(";") if a != ""]
    end
    return xf_list("/applications/muted_applications")
end

function known_apps():
    names = []
    if ui.wayland():
        names = [a.strip() for a in glib.read_text(apps_path()).split("\n") if a.strip() != ""]
    else:
        names = xf_list("/applications/known_applications")
    end
    for name in muted():
        if not (name in names):
            names.append(name)
        end
    end
    return [k[k.find("\t") + 1:] for k in sorted([n.lower() + "\t" + n for n in names])]
end

function conf_set(key, value):
    app["conf"][key] = value
    return ui.write_kv(conf_path(), key, value)
end

function on_dnd(unused, on):
    if ui.wayland():
        return conf_set("DO_NOT_DISTURB", "true" if on else "false")
    end
    return xf_set("/do-not-disturb", "bool", "true" if on else "false")
end

function on_banner(unused, value):
    seconds = number(value, DEFAULT_SECONDS)
    if ui.wayland():
        return conf_set("BANNER_SECONDS", String(seconds))
    end
    call xf_set("/expire-timeout-enabled", "bool", "true")
    return xf_set("/expire-timeout", "int", seconds)
end

function on_sounds(unused, on):
    if ui.wayland():
        return conf_set("SOUNDS", "1" if on else "0")
    end
    return xf_set("/mute-sounds", "bool", "false" if on else "true")
end

function on_history(unused, on):
    call gtk.widget_set_sensitive(app["size"], on)
    if ui.wayland():
        return conf_set("HISTORY", "1" if on else "0")
    end
    return xf_set("/notification-log", "bool", "true" if on else "false")
end

function on_history_size(unused, value):
    size = number(value, DEFAULT_HISTORY)
    if ui.wayland():
        return conf_set("HISTORY_SIZE", String(size))
    end
    call xf_set("/log-max-size-enabled", "bool", "true")
    return xf_set("/log-max-size", "uint", size)
end

function on_app(name, allowed):
    names = [a for a in muted() if a != name]
    if not allowed:
        names.append(name)
    end
    if ui.wayland():
        return conf_set("MUTED_APPS", ";".join(names))
    end
    return xf_set_list("/applications/muted_applications", names)
end

function on_timechange(unused, on):
    return ui.write_kv(conf_path(), "TIME_CHANGE", "1" if on else "0")
end

# ---- stranka ----------------------------------------------------------------------------------------------------

function build(host):
    if ui.wayland():
        app["conf"] = ui.read_kv(conf_path())
    end
    page = ui.page_box()

    g = ui.group(page, i18n.T("Notifications"))
    call ui.row(g, i18n.T("Do Not Disturb"), i18n.T("Banners stay hidden, except urgent ones. Notifications still go to the list in the menu bar."),
                ui.switch(dnd(), on_dnd, 0))
    options = [[3, i18n.T("3 seconds")], [5, i18n.T("5 seconds")], [6, i18n.T("6 seconds")],
               [10, i18n.T("10 seconds")], [15, i18n.T("15 seconds")], [30, i18n.T("30 seconds")]]
    call ui.row(g, i18n.T("Show banners for"), i18n.T("Apps can ask for a different time; urgent notifications stay until you close them."),
                ui.combo(options, String(banner_seconds()), i18n.T("%d seconds").replace("%d", "%s"), on_banner, 0))
    call ui.row(g, i18n.T("Play sounds"), "", ui.switch(sounds(), on_sounds, 0))

    g = ui.group(page, i18n.T("History"))
    keep = history()
    sizes = [[n, String(n)] for n in [20, 50, 100, 200, 500]]
    app["size"] = ui.combo(sizes, String(history_size()), "%s", on_history_size, 0)
    call ui.row(g, i18n.T("Keep notifications in the menu bar"), i18n.T("Missed notifications and reminders wait in the list until you read them."),
                ui.switch(keep, on_history, 0))
    call ui.row(g, i18n.T("Number of notifications to keep"), "", app["size"])
    call gtk.widget_set_sensitive(app["size"], keep)

    g = ui.group(page, i18n.T("Applications"))
    names = known_apps()
    off = muted()
    if len(names) == 0:
        call ui.row(g, i18n.T("Apps appear here after they send a notification."), "", 0)
    end
    for name in names:
        call ui.row(g, name, "", ui.switch(not (name in off), on_app, name))
    end

    # upozorneni luxos-hub (luxos_timechange.lsl); jen kde se cas meni
    g = ui.group(page, i18n.T("Reminders"))
    call ui.row(g, i18n.T("Notify about summer and winter time"), i18n.T("In the evening before the clocks change and in the morning after."),
                ui.switch(ui.read_kv(conf_path()).get("TIME_CHANGE", "") != "0", on_timechange, 0))
    return page
end

function test(command, rest):
    return False
end
