# LuxOS - Nastaveni > Otevrit po prihlaseni (drive karta Automaticke spousteni v xfce4-session-settings).
# Polozky podle specifikace XDG autostart: ~/.config/autostart ma prednost pred XDG_CONFIG_DIRS (/etc/xdg/autostart),
# vybrane jako v luxos-wayland-session (Hidden, OnlyShowIn/NotShowIn proti LuxOS, na X11 proti XFCE, TryExec).
# Vypnuti = kopie polozky v ~/.config/autostart s Hidden=true (a X-GNOME-Autostart-enabled=false), kterou ctou obe
# relace (luxos-wayland-session i xfce4-session); zapnuti totez s Hidden=false. Pridana aplikace je kopie jejiho
# .desktop v ~/.config/autostart, odebrat jde jen takovou vlastni polozku.
# Soucasti relace (systemove polozky NoDisplay=true nebo s id z PLUMBING: Dock, zamek, Lux Guard, xfsettingsd,
# xfce4-notifyd, agenti) se neukazuji - jejich vypnuti by rozbilo relaci nebo ochranu; zbytecne programy LuxOS
# vypina samo (Hidden=true v balicku).
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui

PLUMBING = ["luxos-", "xfce", "xfsettingsd", "at-spi", "gnome-keyring", "polkit", "xdg-user-dirs", "pulseaudio",
            "pipewire", "geoclue"]

app = {"list": 0, "window": 0, "add": 0}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

function user_dir():
    return glib.user_config_dir() + "/autostart"
end

function system_dirs():
    out = []
    for d in env.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":"):
        if d != "":
            out.append(d + "/autostart")
        end
    end
    if len(out) == 0:
        out.append("/etc/xdg/autostart")
    end
    return out
end

# Plocha relace pro OnlyShowIn/NotShowIn: Wayland "LuxOS", X11 "XFCE" (jako XDG_CURRENT_DESKTOP relace)
function desktop():
    if ui.wayland():
        return "LuxOS"
    end
    return "XFCE"
end

# Klice skupiny [Desktop Entry]
function entry(path):
    out = {}
    group = ""
    for raw in glib.read_text(path).split("\n"):
        line = raw.strip()
        if line.startswith("["):
            group = line
        elif group == "[Desktop Entry]":
            cut = line.find("=")
            if cut > 0:
                out[line[0:cut].strip()] = line[cut + 1:].strip()
            end
        end
    end
    return out
end

function local_name(e):
    lang = env.get("LC_ALL", "")
    if lang == "":
        lang = env.get("LC_MESSAGES", "")
    end
    if lang == "":
        lang = env.get("LANG", "")
    end
    lang = lang.split(".")[0]
    for key in ["Name[" + lang + "]", "Name[" + lang.split("_")[0] + "]", "Name"]:
        if e.get(key, "") != "":
            return e[key]
        end
    end
    return ""
end

function listed(value, name):
    return (";" + value + ";").find(";" + name + ";") >= 0
end

function plumbing(id):
    for prefix in PLUMBING:
        if id.startswith(prefix):
            return True
        end
    end
    return False
end

function program_exists(name):
    if name.startswith("/"):
        return exists(name)
    end
    return glib.find_program_in_path(name) != ""
end

# Polozky pro tuto relaci: [{id, path, name, enabled, user, system}], podle nazvu
function items():
    seen = {}
    system = {}
    for d in system_dirs():
        for f in glib.list_dir(d):
            if f.endswith(".desktop") and not (f in system):
                system[f] = d + "/" + f
            end
        end
    end
    for d in [user_dir()] + system_dirs():
        for f in glib.list_dir(d):
            if f.endswith(".desktop") and not (f in seen):
                seen[f] = d + "/" + f
            end
        end
    end
    keyed = {}
    for id in seen.keys():
        path = seen[id]
        e = entry(path)
        if e.get("Exec", "") == "":
            continue
        end
        if e.get("OnlyShowIn", "") != "" and not listed(e["OnlyShowIn"], desktop()):
            continue
        end
        if listed(e.get("NotShowIn", ""), desktop()):
            continue
        end
        if e.get("TryExec", "") != "" and not program_exists(e["TryExec"]):
            continue
        end
        in_system = id in system
        if in_system and (entry(system[id]).get("NoDisplay", "") == "true" or plumbing(id)):
            continue
        end
        name = local_name(e)
        if name == "":
            name = id
        end
        enabled = e.get("Hidden", "") != "true" and e.get("X-GNOME-Autostart-enabled", "") != "false"
        keyed[name.lower() + "\t" + id] = {"id": id, "path": path, "name": name, "enabled": enabled,
                                           "user": path.startswith(user_dir() + "/"), "system": in_system}
    end
    return [keyed[k] for k in sorted(keyed.keys())]
end

# Text .desktop s nastavenymi klici ve skupine [Desktop Entry] (ostatni radky a skupiny beze zmeny)
function with_keys(content, values):
    out = []
    group = ""
    done = False
    for line in content.split("\n"):
        if line.strip().startswith("["):
            if group == "[Desktop Entry]" and not done:
                out = out + [k + "=" + values[k] for k in values.keys()]
                done = True
            end
            group = line.strip()
        elif group == "[Desktop Entry]":
            cut = line.find("=")
            if cut > 0 and line[0:cut].strip() in values:
                continue
            end
        end
        out.append(line)
    end
    while len(out) > 0 and out[len(out) - 1] == "":
        call out.pop()
    end
    if not done:
        if group != "[Desktop Entry]":
            out.append("[Desktop Entry]")
        end
        out = out + [k + "=" + values[k] for k in values.keys()]
    end
    return "\n".join(out) + "\n"
end

function set_enabled(item, on):
    call glib.mkdir_p(user_dir())
    values = {"Hidden": "false" if on else "true", "X-GNOME-Autostart-enabled": "true" if on else "false"}
    return glib.write_atomic(user_dir() + "/" + item["id"], with_keys(glib.read_text(item["path"]), values))
end

function find_item(id):
    for item in items():
        if item["id"] == id:
            return item
        end
    end
    return None
end

function on_toggle(id, on):
    item = find_item(id)
    if item != None:
        call set_enabled(item, on)
    end
    return 0
end

function remove(id):
    item = find_item(id)
    if item == None or item["system"] or not item["user"]:
        return False
    end
    call glib.unlink(item["path"])
    call refresh()
    return True
end

function on_remove(id, button):
    return remove(id)
end

# ---- pridani aplikace -------------------------------------------------------------------------------------------

function info_id(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_id"), ptr(info)))
    end
end

function info_name(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_display_name"), ptr(info)))
    end
end

# [[id, nazev]] aplikaci z nabidky (g_app_info_should_show), podle nazvu
function installed_apps():
    keyed = {}
    unsafe:
        list = __lsl_qbe_call0(__lsl_symbol("g_app_info_get_all"))
        node = list
        while node != 0:
            info = __lsl_qbe_load64(node)
            if __lsl_qbe_icall1(__lsl_symbol("g_app_info_should_show"), info) != 0:
                id = info_id(info)
                name = info_name(info)
                if id != "" and id.endswith(".desktop"):
                    keyed[name.lower() + "\t" + id] = [id, name]
                end
            end
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), info)
            node = __lsl_qbe_load64(node + 8)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), list)
    end
    return [keyed[k] for k in sorted(keyed.keys())]
end

function app_file(id):
    unsafe:
        info = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_new"), cstr(id))
        if info == 0:
            return ""
        end
        path = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_filename"), info))
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), info)
        return path
    end
end

function add(id):
    path = app_file(id)
    if path == "":
        return False
    end
    call glib.mkdir_p(user_dir())
    # vlastni kopie: v nabidce skryta neni potreba, spusteni po prihlaseni ano
    call glib.write_atomic(user_dir() + "/" + id, with_keys(glib.read_text(path), {"Hidden": "false", "X-GNOME-Autostart-enabled": "true"}))
    call refresh()
    return True
end

function on_add(unused, button):
    id = ui.combo_active_id(app["add"])
    if id != "" and id != "-":
        call add(id)
    end
    return 0
end

# ---- stranka ----------------------------------------------------------------------------------------------------

function fill(box):
    g = ui.group(box, i18n.T("Open at Login"))
    all = items()
    if len(all) == 0:
        call ui.row(g, i18n.T("No apps open at login."), "", 0)
    end
    for item in all:
        controls = gtk.box_new(gtk.HORIZONTAL, 8)
        if item["user"] and not item["system"]:
            b = gtk.button_new(i18n.T("Remove"))
            call glib.connect_data(b, "clicked", 0, on_remove, item["id"])
            call gtk.box_pack_start(controls, b, False, False, 0)
        end
        sw = ui.switch(item["enabled"], on_toggle, item["id"])
        call gtk.box_pack_start(controls, sw, False, False, 0)
        call ui.row(g, item["name"], "", controls)
        # testctl ("switch NAZEV = on") hleda ovladac radku podle titulku, ne box s tlacitkem
        ui.state["rows"][item["name"]] = sw
    end
    options = [["-", i18n.T("Choose an app…")]] + [a for a in installed_apps() if not (a[0] in [i["id"] for i in all])]
    app["add"] = ui.combo(options, "-", "", on_pick, 0)
    add_button = gtk.button_new(i18n.T("Add"))
    call glib.connect_data(add_button, "clicked", 0, on_add, 0)
    controls = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(controls, app["add"], False, False, 0)
    call gtk.box_pack_start(controls, add_button, False, False, 0)
    g = ui.group(box, i18n.T("Add an App"))
    call ui.row(g, i18n.T("App"), i18n.T("These apps open each time you log in."), controls)
    ui.state["rows"][i18n.T("App")] = app["add"]
    return 0
end

function on_pick(unused, id):
    return 0
end

function refresh():
    for child in gtk.container_get_children(app["list"]):
        call gtk.widget_destroy(child)
    end
    call fill(app["list"])
    call gtk.widget_show_all(app["list"])
    return 0
end

function build(host):
    app["window"] = host["window"]
    page = ui.page_box()
    app["list"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.box_pack_start(page, app["list"], False, False, 0)
    call fill(app["list"])
    return page
end

# remove ID: tlacitko Odebrat vlastni polozky (popisek je u vsech stejny)
function test(command, rest):
    if command == "remove":
        return remove(rest.strip())
    end
    return False
end
