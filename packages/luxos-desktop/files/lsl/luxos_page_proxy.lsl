# LuxOS - Nastaveni > Proxy: proxy server pro pripojeni k internetu (prace, skola), jako Proxy ve Windows.
#
# Uklada do GSettings org.gnome.system.proxy - cte ho GLib/GTK (glib-networking), Firefox ("pouzit systemove
# nastaveni") i Chromium, zmena plati hned. Programy v terminalu (curl, git, lux) ctou promenne http_proxy...:
# stranka je zapise do ~/.config/luxos/proxy.env a relace (luxos-wayland-session) je nacte pri prihlaseni.
# Rezimy: Vypnuto / Automaticky (adresa skriptu PAC; prazdna = najit v siti, WPAD) / Rucne (HTTP, HTTPS,
# SOCKS jako server:port, vyjimky oddelene carkou). Rucni udaje se ulozi tlacitkem Ulozit po kontrole.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui
load luxos_text as ltext

SCHEMA = "org.gnome.system.proxy"
DEFAULT_IGNORE = ["localhost", "127.0.0.0/8", "::1"]

app = {"gs": 0, "mode": 0, "auto": 0, "manual": 0, "pac": 0, "http": 0, "https": 0, "socks": 0, "ignore": 0,
       "note": 0, "loading": False}

# pismeno (ASCII), cislice nebo jeden ze znaku extra
function plain_char(ch, extra):
    code = ord(ch)
    if (code >= 48 and code <= 57) or (code >= 65 and code <= 90) or (code >= 97 and code <= 122):
        return True
    end
    return ch in extra
end

function child(name):
    return ui.gsettings(SCHEMA + "." + name, "/system/proxy/" + name + "/")
end

function env_path():
    return glib.user_config_dir() + "/luxos/proxy.env"
end

function note(text):
    call gtk.label_set_text(app["note"], text)
    call gtk.widget_set_visible(app["note"], text != "")
    return 0
end

# "server:port" -> ["server", port] nebo None; IPv6 v hranatych zavorkach; bez portu None
function parse_hostport(text):
    t = text.strip()
    for prefix in ["http://", "https://", "socks5://", "socks://"]:
        if t.lower().startswith(prefix):
            t = t[len(prefix):]
        end
    end
    t = t.rstrip("/")
    cut = ltext.rfind(t, ":")
    if cut <= 0:
        return None
    end
    host = t[0:cut]
    port = t[cut + 1:]
    if not ltext.is_digits(port) or Int(port) < 1 or Int(port) > 65535:
        return None
    end
    if host.startswith("[") and host.endswith("]"):
        host = host[1:len(host) - 1]
    end
    for ch in host:
        if not plain_char(ch, [".", "-", ":", "_"]):
            return None
        end
    end
    return [host, Int(port)]
end

function show_hostport(host, port):
    if host == "" or port == 0:
        return ""
    end
    if host.find(":") >= 0:
        return "[" + host + "]:" + String(port)
    end
    return host + ":" + String(port)
end

function url_host(host):
    if host.find(":") >= 0:
        return "[" + host + "]"
    end
    return host
end

function update_visibility():
    mode = ui.combo_active_id(app["mode"])
    call gtk.widget_set_visible(app["auto"], mode == "auto")
    call gtk.widget_set_visible(app["manual"], mode == "manual")
    return 0
end

# ~/.config/luxos/proxy.env pro programy v terminalu (rucni rezim); jinak se soubor smaze
function write_env(mode, http, https, socks, ignore):
    path = env_path()
    if mode != "manual" or (http == None and https == None and socks == None):
        call glib.unlink(path)
        return 0
    end
    lines = []
    if http != None:
        lines.append("http_proxy=http://" + url_host(http[0]) + ":" + String(http[1]) + "/")
    end
    secure = https if https != None else http
    if secure != None:
        lines.append("https_proxy=http://" + url_host(secure[0]) + ":" + String(secure[1]) + "/")
    end
    if socks != None:
        lines.append("all_proxy=socks5://" + url_host(socks[0]) + ":" + String(socks[1]))
    end
    if len(ignore) > 0:
        lines.append("no_proxy=" + ",".join(ignore))
    end
    upper = []
    for line in lines:
        cut = line.find("=")
        upper.append(line[0:cut].upper() + line[cut:])
    end
    call ui.touch(path)
    call glib.write_atomic(path, "\n".join(lines + upper) + "\n")
    return 0
end

function set_child(name, value):
    c = child(name)
    if c == 0:
        return 0
    end
    if value == None:
        call ui.gs_set_string(c, "host", "")
        call ui.gs_set_int(c, "port", 0)
    else:
        call ui.gs_set_string(c, "host", value[0])
        call ui.gs_set_int(c, "port", value[1])
    end
    return 0
end

function on_mode(unused, mode):
    call update_visibility()
    if app["loading"]:
        return 0
    end
    call note("")
    if mode == "none" or mode == "auto":
        call ui.gs_set_string(app["gs"], "mode", mode)
        call write_env(mode, None, None, None, [])
        call ui.gs_sync()
        call note(i18n.T("Saved. Apps use it right away; programs in the terminal after you log out."))
    end
    # rucni rezim se zapne az tlacitkem Ulozit (s kontrolou adres)
    return 0
end

function on_pac_changed(entry):
    if app["loading"]:
        return 0
    end
    url = gtk.entry_get_text(entry).strip()
    if url == "" or url.startswith("http://") or url.startswith("https://") or url.startswith("file://"):
        call ui.gs_set_string(app["gs"], "autoconfig-url", url)
        call ui.gs_sync()
    end
    return 0
end

function on_save(unused):
    fields = [["http", i18n.T("Web proxy (HTTP)")], ["https", i18n.T("Secure web proxy (HTTPS)")],
              ["socks", i18n.T("SOCKS proxy")]]
    values = {}
    for f in fields:
        value = gtk.entry_get_text(app[f[0]]).strip()
        if value == "":
            values[f[0]] = None
        else:
            hp = parse_hostport(value)
            if hp == None:
                call note(i18n.T("%s: enter server:port, for example proxy.example.com:8080.").replace("%s", f[1]))
                return 0
            end
            values[f[0]] = hp
        end
    end
    if values["http"] == None and values["https"] == None and values["socks"] == None:
        call note(i18n.T("Enter at least one proxy server."))
        return 0
    end
    ignore = []
    for part in gtk.entry_get_text(app["ignore"]).replace(";", ",").split(","):
        item = part.strip()
        if item != "":
            for ch in item:
                if not plain_char(ch, [".", "-", ":", "_", "*", "/", "[", "]"]):
                    call note(i18n.T("Exceptions: use names or addresses separated by commas."))
                    return 0
                end
            end
            ignore.append(item)
        end
    end
    call set_child("http", values["http"])
    # HTTPS prazdne = stejny server jako HTTP (jako "pouzit pro vsechny protokoly")
    call set_child("https", values["https"] if values["https"] != None else values["http"])
    call set_child("socks", values["socks"])
    call ui.gs_set_strv(app["gs"], "ignore-hosts", ignore)
    call ui.gs_set_string(app["gs"], "mode", "manual")
    call ui.gs_sync()
    call write_env("manual", values["http"], values["https"], values["socks"], ignore)
    call note(i18n.T("Saved. Apps use it right away; programs in the terminal after you log out."))
    return 0
end

function load():
    app["loading"] = True
    gs = app["gs"]
    mode = ui.gs_get_string(gs, "mode")
    if not (mode in ["none", "auto", "manual"]):
        mode = "none"
    end
    call ui.combo_set_active_id(app["mode"], mode)
    call gtk.entry_set_text(app["pac"], ui.gs_get_string(gs, "autoconfig-url"))
    for name in ["http", "https", "socks"]:
        c = child(name)
        if c != 0:
            call gtk.entry_set_text(app[name], show_hostport(ui.gs_get_string(c, "host"), ui.gs_get_int(c, "port")))
        end
    end
    call gtk.entry_set_text(app["ignore"], ", ".join(ui.gs_get_strv(gs, "ignore-hosts")))
    call update_visibility()
    app["loading"] = False
    return 0
end

function entry(placeholder):
    e = gtk.entry_new()
    call gtk.entry_set_placeholder_text(e, placeholder)
    call gtk.entry_set_width_chars(e, 26)
    return e
end

function build(host):
    page = ui.page_box()
    app["gs"] = ui.gsettings(SCHEMA, "/system/proxy/")
    if app["gs"] == 0:
        call gtk.box_pack_start(page, ui.label(i18n.T("Proxy settings are not available (gsettings-desktop-schemas is missing)."), ""), False, False, 6)
        return page
    end
    g = ui.group(page, i18n.T("Proxy"))
    modes = [["none", i18n.T("Off")], ["auto", i18n.T("Automatic")], ["manual", i18n.T("Manual")]]
    app["mode"] = ui.combo(modes, "none", "", on_mode, 0)
    call ui.row(g, i18n.T("Use a proxy server"), i18n.T("Only when your work or school network requires it."), app["mode"])

    app["auto"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_no_show_all(app["auto"], True)
    call gtk.box_pack_start(page, app["auto"], False, False, 0)
    ga = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(ga, "group")
    call gtk.box_pack_start(app["auto"], ga, False, False, 6)
    app["pac"] = entry("http://wpad/wpad.dat")
    call gtk.connect(app["pac"], "changed", on_pac_changed)
    call ui.row({"box": ga, "rows": 0}, i18n.T("Setup script address"), i18n.T("Leave empty to find it on the network automatically."), app["pac"])

    app["manual"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_no_show_all(app["manual"], True)
    call gtk.box_pack_start(page, app["manual"], False, False, 0)
    gm = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(gm, "group")
    call gtk.box_pack_start(app["manual"], gm, False, False, 6)
    m = {"box": gm, "rows": 0}
    app["http"] = entry("proxy.example.com:8080")
    call ui.row(m, i18n.T("Web proxy (HTTP)"), "", app["http"])
    app["https"] = entry(i18n.T("Same as HTTP"))
    call ui.row(m, i18n.T("Secure web proxy (HTTPS)"), "", app["https"])
    app["socks"] = entry("")
    call ui.row(m, i18n.T("SOCKS proxy"), i18n.T("Optional."), app["socks"])
    app["ignore"] = entry(", ".join(DEFAULT_IGNORE))
    call ui.row(m, i18n.T("Don't use the proxy for"), i18n.T("Names or addresses separated by commas, for example *.local."), app["ignore"])
    save = gtk.button_new(i18n.T("Save"))
    call gtk.widget_add_class(save, "suggested-action")
    call gtk.connect(save, "clicked", on_save)
    call ui.row(m, "", "", save)

    app["note"] = ui.label("", "hint")
    call gtk.widget_set_no_show_all(app["note"], True)
    call gtk.box_pack_start(page, app["note"], False, False, 6)
    # krabice s no_show_all: obsah ukazat ted, viditelnost krabic ridi rezim
    call gtk.widget_show_all(ga)
    call gtk.widget_show_all(gm)
    call load()
    if gtk.entry_get_text(app["ignore"]) == "":
        call gtk.entry_set_text(app["ignore"], ", ".join(DEFAULT_IGNORE))
    end
    return page
end

function test(command, rest):
    return False
end
