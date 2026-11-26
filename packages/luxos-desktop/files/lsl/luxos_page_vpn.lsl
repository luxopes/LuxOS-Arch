# LuxOS - Nastaveni > VPN: pripojeni VPN z NetworkManageru (WireGuard a OpenVPN).
#
# - seznam pripojeni typu wireguard a vpn (nmcli connection show), prepinac = connection up/down (asynchronne),
# - Pridat VPN…: soubor od poskytovatele (.conf = WireGuard, vestaveny v NetworkManageru; .ovpn = OpenVPN,
#   balicek networkmanager-openvpn) -> nmcli connection import,
# - OpenVPN se jmenem a heslem: v Wayland relaci LuxOS nebezi agent pro hesla (nm-applet), proto stranka
#   heslo vyzada sama a preda ho pres passwd-file (soubor 0600 v XDG_RUNTIME_DIR, po pripojeni smazany) -
#   nikdy v argumentech programu. Heslo se neuklada; jmeno ano (vpn.user-name).
# - Odebrat: dvoukrokove (Odebrat -> Opravdu odebrat).
# nmcli bezi s LC_ALL=C a stderr do vystupu (chybu stranka ukaze). Testy: falesny nmcli v PATH,
# LUXOS_UI_TEST "vpn-import CESTA" (misto okna pro vyber souboru).
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui

app = {"page": 0, "host": 0, "list": 0, "note": 0, "login": 0, "login_title": 0, "user": 0, "password": 0,
       "connect": 0, "login_inner": 0, "login_uuid": "", "pending": "", "confirm": "", "conns": [], "busy": {}, "alive": False}

function openvpn_available():
    return glib.file_test("/usr/lib/NetworkManager/VPN/nm-openvpn-service.name") or glib.file_test("/etc/NetworkManager/VPN/nm-openvpn-service.name")
end

function nm(args, handler, bound):
    argv = ["sh", "-c", "LC_ALL=C exec \"$@\" 2>&1", "nmcli", "nmcli"] + args
    call glib.spawn_capture(argv, handler, bound)
    return 0
end

# nmcli -t: pole oddelena ":", dvojtecka ve jmenu je "\:"
function split_t(line):
    out = []
    cur = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur = cur + line[i + 1]
            i += 2
        elif ch == ":":
            out.append(cur)
            cur = ""
            i += 1
        else:
            cur = cur + ch
            i += 1
        end
    end
    out.append(cur)
    return out
end

# posledni neprazdny radek vystupu nmcli bez "Error: "
function message(output):
    last = ""
    for line in output.split("\n"):
        if line.strip() != "" and not line.strip().startswith("Hint:"):
            last = line.strip()
        end
    end
    if last.startswith("Error: "):
        last = last[7:]
    end
    return last
end

function note(text):
    if app["note"] != 0:
        call gtk.label_set_text(app["note"], text)
        call gtk.widget_set_visible(app["note"], text != "")
    end
    return 0
end

# ---- seznam ----------------------------------------------------------------------------------------------

function load():
    call nm(["-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"], on_list, 0)
    return 0
end

function on_list(unused, output, status):
    if not app["alive"]:
        return 0
    end
    conns = []
    for line in output.split("\n"):
        f = split_t(line)
        if len(f) >= 4 and (f[2] == "wireguard" or f[2] == "vpn"):
            conns.append({"name": f[0], "uuid": f[1], "type": f[2], "active": f[3] == "yes", "password": False,
                          "user": ""})
        end
    end
    app["conns"] = conns
    call fill_list()
    # OpenVPN: potrebuje jmeno a heslo? (vpn.data connection-type = password | password-tls)
    for c in conns:
        if c["type"] == "vpn":
            call nm(["-g", "vpn.data,vpn.user-name", "connection", "show", c["uuid"]], on_vpn_data, c)
        end
    end
    return 0
end

function on_vpn_data(c, output, status):
    data = output.replace("\\,", ",")
    c["password"] = data.find("connection-type = password") >= 0
    lines = output.strip().split("\n")
    if len(lines) >= 2:
        c["user"] = lines[len(lines) - 1].strip()
    end
    m = data.find("username = ")
    if c["user"] == "" and m >= 0:
        c["user"] = data[m + 11:].split(",")[0].strip()
    end
    return 0
end

function kind_label(c):
    if c["type"] == "wireguard":
        return "WireGuard"
    end
    return "OpenVPN"
end

function fill_list():
    g = app["list"]
    for child in gtk.container_get_children(g["box"]):
        call gtk.widget_destroy(child)
    end
    g["rows"] = 0
    if len(app["conns"]) == 0:
        call ui.row(g, i18n.T("No VPN yet"), i18n.T("Add the file you got from your VPN provider or your work."), 0)
    end
    for c in app["conns"]:
        box = gtk.box_new(gtk.HORIZONTAL, 8)
        if app["confirm"] == c["uuid"]:
            remove = gtk.button_new(i18n.T("Really Remove"))
            call gtk.widget_add_class(remove, "destructive-action")
        else:
            remove = gtk.button_new(i18n.T("Remove"))
        end
        call glib.connect_data(remove, "clicked", 0, on_remove, c)
        sw = ui.switch(c["active"], on_toggle, c)
        call gtk.widget_set_sensitive(sw, not app["busy"].get(c["uuid"], False))
        call gtk.box_pack_start(box, remove, False, False, 0)
        call gtk.box_pack_start(box, sw, False, False, 0)
        hint = kind_label(c)
        if c["active"]:
            hint = hint + " · " + i18n.T("Connected")
        elif app["busy"].get(c["uuid"], False):
            hint = hint + " · " + i18n.T("Connecting…")
        end
        call ui.row(g, c["name"], hint, box)
        # prepinac pro testy pod jmenem pripojeni (radek ma krabicku s tlacitkem)
        ui.state["rows"][c["name"]] = sw
    end
    call gtk.widget_show_all(g["box"])
    return 0
end

# ---- pripojeni ---------------------------------------------------------------------------------------------

function on_refresh_soon():
    if app["alive"]:
        call fill_list()
    end
    return False
end

# seznam znovu az po navratu z obsluhy signalu prepinace (ten se pri prekresleni seznamu nici)
function refresh_soon():
    call glib.timeout_add(1, on_refresh_soon)
    return 0
end

function on_toggle(c, on):
    call note("")
    if not on:
        app["busy"][c["uuid"]] = True
        call nm(["connection", "down", c["uuid"]], on_done, c)
        return 0
    end
    if c["password"]:
        call ask_login(c)
        return 0
    end
    app["busy"][c["uuid"]] = True
    call refresh_soon()
    call nm(["connection", "up", c["uuid"]], on_done, c)
    return 0
end

function on_done(c, output, status):
    app["busy"][c["uuid"]] = False
    if app["pending"] != "":
        call glib.unlink(app["pending"])
        app["pending"] = ""
    end
    if status != 0 and app["alive"]:
        text = message(output)
        # "No valid secrets", "Secrets were required, but not provided"
        if text.lower().find("secrets") >= 0 and c["type"] == "vpn":
            c["password"] = True
            call ask_login(c)
            text = i18n.T("This VPN needs a user name and password.")
        end
        call note(i18n.T("Could not connect: %s").replace("%s", text))
    end
    call load()
    return 0
end

function ask_login(c):
    app["login_uuid"] = c["uuid"]
    call gtk.label_set_text(app["login_title"], i18n.T("Sign in to %s").replace("%s", c["name"]))
    call gtk.entry_set_text(app["user"], c["user"])
    call gtk.entry_set_text(app["password"], "")
    # show_all na krabici s no_show_all nic neukaze: ukazat obsah a pak ji samotnou
    call gtk.widget_show_all(app["login_inner"])
    call gtk.widget_show(app["login_title"])
    call gtk.widget_set_visible(app["login"], True)
    call gtk.widget_grab_focus(app["password"] if c["user"] != "" else app["user"])
    call refresh_soon()
    return 0
end

function find_conn(uuid):
    for c in app["conns"]:
        if c["uuid"] == uuid:
            return c
        end
    end
    return None
end

function on_connect(unused):
    c = find_conn(app.get("login_uuid", ""))
    if c == None:
        return 0
    end
    user = gtk.entry_get_text(app["user"]).strip()
    password = gtk.entry_get_text(app["password"])
    if user == "" or password == "":
        call note(i18n.T("Enter the user name and password."))
        return 0
    end
    if user.find(",") >= 0 or user.find("=") >= 0 or user.find("\\") >= 0:
        call note(i18n.T("The user name cannot contain a comma, = or a backslash."))
        return 0
    end
    if password.find("\n") >= 0:
        call note(i18n.T("The password cannot contain a line break."))
        return 0
    end
    call gtk.widget_set_visible(app["login"], False)
    call gtk.entry_set_text(app["password"], "")
    app["busy"][c["uuid"]] = True
    c["user"] = user
    call refresh_soon()
    call nm(["connection", "modify", c["uuid"], "+vpn.data", "username=" + user, "vpn.user-name", user],
            on_user_saved, [c, password])
    return 0
end

function on_user_saved(job, output, status):
    c = job[0]
    path = glib.user_runtime_dir() + "/luxos-vpn-" + c["uuid"]
    if not ui.write_private(path, "vpn.secrets.password:" + job[1] + "\n"):
        app["busy"][c["uuid"]] = False
        call note(i18n.T("Could not connect: %s").replace("%s", "passwd-file"))
        return 0
    end
    app["pending"] = path
    call nm(["connection", "up", c["uuid"], "passwd-file", path], on_done, c)
    return 0
end

function on_cancel_login(unused):
    call gtk.entry_set_text(app["password"], "")
    call gtk.widget_set_visible(app["login"], False)
    call refresh_soon()
    return 0
end

# ---- pridani a odebrani -------------------------------------------------------------------------------------

function import_file(path):
    call note("")
    lower = path.lower()
    kind = ""
    if lower.endswith(".conf"):
        kind = "wireguard"
    elif lower.endswith(".ovpn"):
        kind = "openvpn"
        if not openvpn_available():
            call note(i18n.T("OpenVPN support is not installed (package networkmanager-openvpn)."))
            return 0
        end
    else:
        call note(i18n.T("Choose a WireGuard (.conf) or OpenVPN (.ovpn) file."))
        return 0
    end
    call nm(["connection", "import", "type", kind, "file", path], on_imported, kind)
    return 0
end

# "Connection 'wg0' (UUID) successfully added." -> UUID
function imported_uuid(output):
    a = output.find("(")
    b = output.find(")")
    if a < 0 or b <= a:
        return ""
    end
    return output[a + 1:b]
end

# NetworkManager pripojeni po importu hned zapne a zapina ho pri kazdem startu (WireGuard s AllowedIPs
# 0.0.0.0/0 by bez ptani presmeroval veskery provoz): VPN se zapina jen prepinacem v seznamu
function on_imported(kind, output, status):
    if status != 0:
        call note(i18n.T("The file could not be added: %s").replace("%s", message(output)))
        call load()
        return 0
    end
    call note(i18n.T("VPN added. Turn it on in the list."))
    uuid = imported_uuid(output)
    if uuid == "":
        call load()
        return 0
    end
    call nm(["connection", "modify", uuid, "connection.autoconnect", "no"], on_autoconnect_off, uuid)
    return 0
end

function on_autoconnect_off(uuid, output, status):
    call nm(["connection", "down", uuid], on_imported_down, uuid)
    return 0
end

function on_imported_down(uuid, output, status):
    call load()
    return 0
end

function on_add(unused):
    path = ui.choose_file(gtk.widget_get_toplevel(app["page"]), i18n.T("Add VPN"), i18n.T("VPN settings"),
                          ["*.conf", "*.ovpn", "*.CONF", "*.OVPN"])
    if path != "":
        call import_file(path)
    end
    return 0
end

function on_remove(c, button):
    if app["confirm"] != c["uuid"]:
        app["confirm"] = c["uuid"]
        call refresh_soon()
        return 0
    end
    app["confirm"] = ""
    call nm(["connection", "delete", c["uuid"]], on_removed, c)
    return 0
end

function on_removed(c, output, status):
    if status != 0:
        call note(message(output))
    end
    call load()
    return 0
end

# ---- stranka ----------------------------------------------------------------------------------------------

function build(host):
    page = ui.page_box()
    app["page"] = page
    app["alive"] = True
    app["list"] = ui.group(page, "VPN")

    app["login"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_no_show_all(app["login"], True)
    call gtk.box_pack_start(page, app["login"], False, False, 0)
    app["login_title"] = ui.label("", "group-title")
    call gtk.box_pack_start(app["login"], app["login_title"], False, False, 0)
    lg = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(lg, "group")
    call gtk.box_pack_start(app["login"], lg, False, False, 0)
    app["login_inner"] = lg
    g = {"box": lg, "rows": 0}
    app["user"] = gtk.entry_new()
    call gtk.entry_set_width_chars(app["user"], 22)
    call ui.row(g, i18n.T("User name"), "", app["user"])
    app["password"] = gtk.entry_new()
    call gtk.entry_set_visibility(app["password"], False)
    call gtk.entry_set_width_chars(app["password"], 22)
    call ui.row(g, i18n.T("Password"), i18n.T("Used only for this connection, not saved."), app["password"])
    buttons = gtk.box_new(gtk.HORIZONTAL, 8)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.connect(cancel, "clicked", on_cancel_login)
    app["connect"] = gtk.button_new(i18n.T("Connect"))
    call gtk.widget_add_class(app["connect"], "suggested-action")
    call gtk.connect(app["connect"], "clicked", on_connect)
    call gtk.connect(app["password"], "activate", on_connect)
    call gtk.box_pack_start(buttons, cancel, False, False, 0)
    call gtk.box_pack_start(buttons, app["connect"], False, False, 0)
    call ui.row(g, "", "", buttons)

    app["note"] = ui.label("", "")
    call gtk.widget_set_no_show_all(app["note"], True)
    call gtk.box_pack_start(page, app["note"], False, False, 6)

    g2 = ui.group(page, i18n.T("Add"))
    add = gtk.button_new(i18n.T("Add VPN…"))
    call gtk.connect(add, "clicked", on_add)
    hint = i18n.T("WireGuard (.conf) or OpenVPN (.ovpn) file from your provider.")
    call ui.row(g2, i18n.T("From a file"), hint, add)
    call load()
    return page
end

function show(host):
    app["alive"] = True
    if app["page"] != 0:
        call load()
    end
    return 0
end

function leave(host):
    app["alive"] = False
    return 0
end

function test(command, rest):
    if command == "vpn-import":
        call import_file(rest)
        return True
    end
    return False
end
