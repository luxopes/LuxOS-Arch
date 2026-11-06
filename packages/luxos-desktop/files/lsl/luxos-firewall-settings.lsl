# LuxOS - Nastaveni > Firewall: zapnuti/vypnuti, co je povolene automaticky (LuxDrop, Steam, SSH ...),
# vlastni vyjimky ("jen tato sit" / "odkudkoli"), zarizeni Tailscale jako mistni sit a nedavno zablokovane
# programy s tlacitkem Povolit. Stav cte z `luxos-firewall status --json` (bez prav roota), zmeny dela
# `pkexec luxos-firewall ...` (heslo spravce, jednou za chvili - auth_admin_keep) a pak okno obnovi.
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_gio, gio as gio
load luxos_i18n as i18n

CLI = "/usr/bin/luxos-firewall"
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 10px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.65; }\n.status-on { color: #2e9d4f; font-weight: 600; }\n.status-off { color: #c0392b; font-weight: 600; }\n.error { color: #c0392b; }\n"

ui = {"window": 0, "scroll": 0, "outer": 0, "page": 0, "building": False, "busy": False, "buttons": {}, "combos": {},
      "switch": 0, "ts_switch": 0, "port": 0, "proto": 0, "from": 0, "message": "", "timer": 0}

function cli():
    value = env.get("LUXOS_FIREWALL_CLI", "")
    if value == None or value == "":
        return CLI
    end
    return value
end

function status():
    data = None
    safe:
        data = json.decode(capture(cli(), ["status", "--json"]))
    end
    if type(data) != "Dictionary":
        return {"enable": False, "active": False, "rules": [], "allow": [], "blocked": [], "missing": True}
    end
    return data
end

# ---- stavebni prvky (jako ostatni okna Nastaveni LuxOS) ---------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 52)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function group(page, title):
    call gtk.box_pack_start(page, label(title, "group-title"), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

function row(g, title, hint, widget):
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, ""), False, False, 0)
    if hint != "":
        call gtk.box_pack_start(texts, label(hint, "hint"), False, False, 0)
    end
    call gtk.box_pack_start(box, texts, True, True, 0)
    if widget != 0:
        call gtk.widget_set_valign(widget, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widget, False, False, 0)
    end
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    g["rows"] = g["rows"] + 1
    return box
end

function button(text, action, data):
    b = gtk.button_new(text)
    ui["buttons"][b] = {"action": action, "data": data}
    call gtk.connect(b, "clicked", on_button)
    return b
end

function proto_text(proto):
    return proto.upper()
end

function source_text(source):
    if source == "any":
        return i18n.T("Everywhere")
    end
    return i18n.T("This network only")
end

function rule_name(name):
    if name == "Printer sharing":
        return i18n.T("Printer sharing")
    end
    if name == "SSH":
        return i18n.T("SSH (remote login)")
    end
    return name
end

# ---- obsah okna -------------------------------------------------------------------------------------------

function build():
    ui["building"] = True
    ui["buttons"] = {}
    ui["combos"] = {}
    st = status()
    if ui["page"] != 0:
        call gtk.widget_destroy(ui["page"])
    end
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 6, 22)
    ui["page"] = page
    # stala vnejsi krabice ve ScrolledWindow (jeho Viewport zustava), obsah se jen vymeni
    call gtk.box_pack_start(ui["outer"], page, True, True, 0)

    if st.get("missing") == True:
        call gtk.box_pack_start(page, label(i18n.T("The LuxOS firewall is not installed (lux install luxos-firewall)."), "error"), False, False, 12)
        call gtk.widget_show_all(page)
        ui["building"] = False
        return 0
    end

    g = group(page, i18n.T("Firewall"))
    sw = gtk.switch_new()
    call gtk.switch_set_active(sw, st.get("enable") == True)
    call gtk.connect(sw, "state-set", on_switch)
    ui["switch"] = sw
    call row(g, i18n.T("Firewall"), i18n.T("Blocks incoming connections from the network. Your apps can still use the internet, and apps listed below keep working."), sw)
    state_text = i18n.T("On - the computer is protected.")
    css = "status-on"
    if st.get("enable") != True:
        state_text = i18n.T("Off - the computer accepts connections from the network.")
        css = "status-off"
    elif st.get("active") != True:
        state_text = i18n.T("On, but the rules are not loaded - the network is open. Try turning the firewall off and on.")
        css = "status-off"
    end
    status_box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(status_box, "row")
    call gtk.widget_add_class(status_box, "row-sep")
    call gtk.box_pack_start(status_box, label(state_text, css), True, True, 0)
    call gtk.box_pack_start(g["box"], status_box, False, False, 0)
    if ui["message"] != "":
        call gtk.box_pack_start(page, label(ui["message"], "error"), False, False, 6)
    end

    # automaticka pravidla seskupena podle aplikace
    names = []
    ports = {}
    sources = {}
    for r in st.get("rules", []):
        name = String(r.get("name", ""))
        if not (name in names):
            names.append(name)
            ports[name] = []
        end
        ports[name].append(String(r.get("port", "")) + "/" + proto_text(String(r.get("proto", ""))))
        sources[name] = String(r.get("from", "lan"))
    end
    g = group(page, i18n.T("Allowed automatically"))
    if len(names) == 0:
        call row(g, i18n.T("Nothing"), "", 0)
    end
    for name in names:
        call row(g, rule_name(name), source_text(sources[name]) + " - " + ", ".join(ports[name]), 0)
    end

    g = group(page, i18n.T("Your exceptions"))
    for item in st.get("allow", []):
        title = String(item.get("port", "")) + "/" + proto_text(String(item.get("proto", "")))
        if item.get("app", "") != "":
            title = String(item["app"]) + " - " + title
        end
        box = gtk.box_new(gtk.HORIZONTAL, 6)
        combo = gtk.combo_box_text_new()
        call gtk.combo_box_text_append(combo, "lan", i18n.T("This network only"))
        call gtk.combo_box_text_append(combo, "any", i18n.T("Everywhere"))
        if item.get("from") == "any":
            call gtk.combo_box_set_active(combo, 1)
        else:
            call gtk.combo_box_set_active(combo, 0)
        end
        ui["combos"][combo] = item
        call gtk.connect(combo, "changed", on_from_changed)
        call gtk.box_pack_start(box, combo, False, False, 0)
        call gtk.box_pack_start(box, button(i18n.T("Remove"), "deny", item), False, False, 0)
        call row(g, title, "", box)
    end
    # nova vyjimka
    add = gtk.box_new(gtk.HORIZONTAL, 6)
    entry = gtk.entry_new()
    call gtk.entry_set_placeholder_text(entry, i18n.T("Port, e.g. 8080"))
    call gtk.entry_set_width_chars(entry, 12)
    ui["port"] = entry
    proto = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(proto, "tcp", "TCP")
    call gtk.combo_box_text_append(proto, "udp", "UDP")
    call gtk.combo_box_text_append(proto, "both", i18n.T("TCP and UDP"))
    call gtk.combo_box_set_active(proto, 0)
    ui["proto"] = proto
    source = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(source, "lan", i18n.T("This network only"))
    call gtk.combo_box_text_append(source, "any", i18n.T("Everywhere"))
    call gtk.combo_box_set_active(source, 0)
    ui["from"] = source
    call gtk.box_pack_start(add, entry, False, False, 0)
    call gtk.box_pack_start(add, proto, False, False, 0)
    call gtk.box_pack_start(add, source, False, False, 0)
    call gtk.box_pack_start(add, button(i18n.T("Allow"), "add", None), False, False, 0)
    add_row = row(g, i18n.T("Allow a port"), i18n.T("\"This network only\" means devices on your Wi-Fi or cable network, not the internet."), 0)
    call gtk.box_set_spacing(add_row, 8)
    call gtk.widget_set_margins(add, 14, 14, 0, 12)
    call gtk.box_pack_start(g["box"], add, False, False, 0)

    # Tailscale (jen kdyz je nainstalovany - pravidlo Tailscale v automatickych)
    if "Tailscale" in names or st.get("trust_tailscale") == True:
        g = group(page, "Tailscale")
        ts = gtk.switch_new()
        call gtk.switch_set_active(ts, st.get("trust_tailscale") == True)
        call gtk.connect(ts, "state-set", on_tailscale)
        ui["ts_switch"] = ts
        call row(g, i18n.T("Treat Tailscale devices as this network"), i18n.T("LuxDrop and exceptions for this network also accept connections from your Tailscale devices."), ts)
    end

    # nedavno zablokovane bez tech, ktere uz jsou povolene (vyjimka nebo automaticke pravidlo)
    allowed = {}
    for item in st.get("allow", []) + st.get("rules", []):
        allowed[String(item.get("port", "")) + "/" + String(item.get("proto", ""))] = True
    end
    blocked = []
    for b in st.get("blocked", []):
        if type(b) == "Dictionary" and type(b.get("port")) == "Int" and not ((String(b["port"]) + "/" + String(b.get("proto", ""))) in allowed):
            blocked.append(b)
        end
    end
    if len(blocked) > 0:
        g = group(page, i18n.T("Recently blocked"))
        for b in blocked:
            key = String(b["port"]) + "/" + String(b.get("proto", ""))
            title = String(b.get("app", "")) + " - " + String(b["port"]) + "/" + proto_text(String(b.get("proto", "")))
            hint = i18n.TF("Connection from %s", [String(b.get("src", ""))])
            call row(g, title, hint, button(i18n.T("Allow"), "allow-blocked", b))
        end
    end

    call gtk.box_pack_start(page, label(i18n.T("Something stopped working on the network? Allow it here, or run \"luxos-firewall allow PORT\" in Terminal."), "hint"), False, False, 16)
    call gtk.widget_show_all(page)
    if ui["busy"]:
        call gtk.widget_set_sensitive(page, False)
    end
    ui["building"] = False
    return 0
end

# ---- zmeny (pkexec luxos-firewall ...) ----------------------------------------------------------------------

function run_cli(args):
    if ui["busy"]:
        return 0
    end
    # chybovy vystup pkexec/luxos-firewall do zpravy v okne
    argv = ["/bin/sh", "-c", "exec pkexec \"$0\" \"$@\" 2>&1", cli()]
    argv.extend(args)
    ui["busy"] = True
    ui["message"] = ""
    call gtk.widget_set_sensitive(ui["page"], False)
    if glib.spawn_capture(argv, on_done, args) == 0:
        ui["busy"] = False
        ui["message"] = i18n.T("pkexec could not be started.")
        call build()
    end
    return 0
end

function on_done(args, output, status):
    ui["busy"] = False
    code = status // 256
    # 126 = zruseno v dialogu hesla, 127 = neovereno: jen obnovit stav
    if status != 0 and code != 126 and code != 127:
        ui["message"] = i18n.T("The change could not be made.") + " " + output.strip()
    end
    call build()
    return 0
end

function on_switch(state, sw):
    if ui["building"]:
        return False
    end
    if state != 0:
        call run_cli(["on"])
    else:
        call run_cli(["off"])
    end
    return False
end

function on_tailscale(state, sw):
    if ui["building"]:
        return False
    end
    if state != 0:
        call run_cli(["tailscale", "on"])
    else:
        call run_cli(["tailscale", "off"])
    end
    return False
end

function on_from_changed(combo):
    if ui["building"] or combo not in ui["combos"]:
        return 0
    end
    item = ui["combos"][combo]
    source = "lan"
    if gtk.combo_box_get_active(combo) == 1:
        source = "any"
    end
    args = ["allow", String(item["port"]) + "/" + String(item["proto"]), "--from", source]
    if item.get("app", "") != "":
        args.extend(["--app", String(item["app"])])
    end
    call run_cli(args)
    return 0
end

function on_button(b):
    if b not in ui["buttons"]:
        return 0
    end
    info = ui["buttons"][b]
    action = info["action"]
    data = info["data"]
    if action == "deny":
        call run_cli(["deny", String(data["port"]) + "/" + String(data["proto"])])
    elif action == "allow-blocked":
        args = ["allow", String(data["port"]) + "/" + String(data.get("proto", "tcp")), "--from", "lan"]
        app = String(data.get("app", ""))
        if app != "" and app != "unknown":
            args.extend(["--app", app])
        end
        call run_cli(args)
    elif action == "add":
        port = gtk.entry_get_text(ui["port"]).strip()
        if port == "":
            return 0
        end
        spec = port
        protos = ["tcp", "udp", "both"]
        p = protos[max(0, gtk.combo_box_get_active(ui["proto"]))]
        if p != "both":
            spec = port + "/" + p
        end
        source = "lan"
        if gtk.combo_box_get_active(ui["from"]) == 1:
            source = "any"
        end
        call run_cli(["allow", spec, "--from", source])
    end
    return 0
end

# Nove zablokovany program (requests.json od luxos-firewall-watch): obnovit seznam, pokud uzivatel nic nepise
function on_requests(path, event, other):
    name = path
    if other != "":
        name = other
    end
    if not name.endswith("/requests.json") or ui["timer"] != 0:
        return 0
    end
    ui["timer"] = glib.timeout_add(700, refresh)
    return 0
end

function refresh():
    ui["timer"] = 0
    if not ui["busy"] and (ui["port"] == 0 or gtk.entry_get_text(ui["port"]) == ""):
        call build()
    end
    return False
end

function on_delete(event, window):
    call gtk.main_quit()
    return False
end

call glib.set_prgname("luxos-firewall-settings")
call gtk.init()
call gtk.css_load(CSS)
window = gtk.window_new(i18n.T("Firewall"))
ui["window"] = window
call gtk.window_set_wmclass(window, "luxos-firewall-settings", "luxos-firewall-settings")
call gtk.window_set_icon_list(window, "firewall")
call gtk.window_set_default_size(window, 600, 640)
scroll = gtk.scrolled_window_new()
call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
ui["scroll"] = scroll
outer = gtk.box_new(gtk.VERTICAL, 0)
ui["outer"] = outer
call gtk.container_add(scroll, outer)
call gtk.container_add(window, scroll)
call build()
call gtk.connect(window, "delete-event", on_delete)
safe:
    call gio.file_monitor("/run/luxos-firewall", on_requests)
end
call gtk.widget_show_all(window)
call gtk.main()
