# LuxOS - Nastaveni > Firewall (drive luxos-firewall-settings): zapnuti/vypnuti, co je povolene automaticky
# (LuxDrop, Steam, SSH ...), vlastni vyjimky ("jen tato sit" / "odkudkoli"), zarizeni Tailscale jako mistni sit
# a nedavno zablokovane programy s tlacitkem Povolit. Stav cte z `luxos-firewall status --json` (bez prav roota)
# pri kazdem zobrazeni stranky, zmeny dela `pkexec luxos-firewall ...` (heslo spravce, jednou za chvili -
# auth_admin_keep) a pak stranku obnovi.
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_settings_ui as ui

CLI = "/usr/bin/luxos-firewall"
CSS = ".fw-on { color: #2e9d4f; font-weight: 600; }\n.fw-off { color: #c0392b; font-weight: 600; }\n.fw-error { color: #c0392b; }\n"

fw = {"outer": 0, "page": 0, "css": 0, "rows": {}, "building": False, "busy": False, "buttons": {},
      "combos": {}, "switch": 0, "ts_switch": 0, "port": 0, "proto": 0, "from": 0, "message": "", "timer": 0}

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

function button(text, action, data):
    b = gtk.button_new(text)
    fw["buttons"][b] = {"action": action, "data": data}
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

function build_content():
    fw["building"] = True
    fw["buttons"] = {}
    fw["combos"] = {}
    st = status()
    if fw["page"] != 0:
        call gtk.widget_destroy(fw["page"])
    end
    page = gtk.box_new(gtk.VERTICAL, 0)
    fw["page"] = page
    # stala vnejsi krabice ve ScrolledWindow (jeho Viewport zustava), obsah se jen vymeni
    call gtk.box_pack_start(fw["outer"], page, True, True, 0)

    if st.get("missing") == True:
        call gtk.box_pack_start(page, label(i18n.T("The LuxOS firewall is not installed (lux install luxos-firewall)."), "fw-error"), False, False, 12)
        call gtk.widget_show_all(page)
        fw["building"] = False
        return 0
    end

    g = ui.group(page, i18n.T("Firewall"))
    sw = gtk.switch_new()
    call gtk.switch_set_active(sw, st.get("enable") == True)
    call gtk.connect(sw, "state-set", on_switch)
    fw["switch"] = sw
    call ui.row(g, i18n.T("Firewall"), i18n.T("Blocks incoming connections from the network. Your apps can still use the internet, and apps listed below keep working."), sw)
    state_text = i18n.T("On - the computer is protected.")
    css = "fw-on"
    if st.get("enable") != True:
        state_text = i18n.T("Off - the computer accepts connections from the network.")
        css = "fw-off"
    elif st.get("active") != True:
        state_text = i18n.T("On, but the rules are not loaded - the network is open. Try turning the firewall off and on.")
        css = "fw-off"
    end
    status_box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(status_box, "row")
    call gtk.widget_add_class(status_box, "row-sep")
    call gtk.box_pack_start(status_box, label(state_text, css), True, True, 0)
    call gtk.box_pack_start(g["box"], status_box, False, False, 0)
    if fw["message"] != "":
        call gtk.box_pack_start(page, label(fw["message"], "fw-error"), False, False, 6)
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
    g = ui.group(page, i18n.T("Allowed automatically"))
    if len(names) == 0:
        call ui.row(g, i18n.T("Nothing"), "", 0)
    end
    for name in names:
        call ui.row(g, rule_name(name), source_text(sources[name]) + " - " + ", ".join(ports[name]), 0)
    end

    g = ui.group(page, i18n.T("Your exceptions"))
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
        fw["combos"][combo] = item
        call gtk.connect(combo, "changed", on_from_changed)
        call gtk.box_pack_start(box, combo, False, False, 0)
        call gtk.box_pack_start(box, button(i18n.T("Remove"), "deny", item), False, False, 0)
        call ui.row(g, title, "", box)
    end
    # nova vyjimka
    add = gtk.box_new(gtk.HORIZONTAL, 6)
    entry = gtk.entry_new()
    call gtk.entry_set_placeholder_text(entry, i18n.T("Port, e.g. 8080"))
    call gtk.entry_set_width_chars(entry, 12)
    fw["port"] = entry
    proto = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(proto, "tcp", "TCP")
    call gtk.combo_box_text_append(proto, "udp", "UDP")
    call gtk.combo_box_text_append(proto, "both", i18n.T("TCP and UDP"))
    call gtk.combo_box_set_active(proto, 0)
    fw["proto"] = proto
    source = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(source, "lan", i18n.T("This network only"))
    call gtk.combo_box_text_append(source, "any", i18n.T("Everywhere"))
    call gtk.combo_box_set_active(source, 0)
    fw["from"] = source
    call gtk.box_pack_start(add, entry, False, False, 0)
    call gtk.box_pack_start(add, proto, False, False, 0)
    call gtk.box_pack_start(add, source, False, False, 0)
    call gtk.box_pack_start(add, button(i18n.T("Allow"), "add", None), False, False, 0)
    add_row = ui.row(g, i18n.T("Allow a port"), i18n.T("\"This network only\" means devices on your Wi-Fi or cable network, not the internet."), 0)
    call gtk.box_set_spacing(add_row, 8)
    call gtk.widget_set_margins(add, 14, 14, 0, 12)
    call gtk.box_pack_start(g["box"], add, False, False, 0)

    # Tailscale (jen kdyz je nainstalovany - pravidlo Tailscale v automatickych)
    if "Tailscale" in names or st.get("trust_tailscale") == True:
        g = ui.group(page, "Tailscale")
        ts = gtk.switch_new()
        call gtk.switch_set_active(ts, st.get("trust_tailscale") == True)
        call gtk.connect(ts, "state-set", on_tailscale)
        fw["ts_switch"] = ts
        call ui.row(g, i18n.T("Treat Tailscale devices as this network"), i18n.T("LuxDrop and exceptions for this network also accept connections from your Tailscale devices."), ts)
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
        g = ui.group(page, i18n.T("Recently blocked"))
        for b in blocked:
            key = String(b["port"]) + "/" + String(b.get("proto", ""))
            title = String(b.get("app", "")) + " - " + String(b["port"]) + "/" + proto_text(String(b.get("proto", "")))
            hint = i18n.TF("Connection from %s", [String(b.get("src", ""))])
            call ui.row(g, title, hint, button(i18n.T("Allow"), "allow-blocked", b))
        end
    end

    call gtk.box_pack_start(page, label(i18n.T("Something stopped working on the network? Allow it here, or run \"luxos-firewall allow PORT\" in Terminal."), "hint"), False, False, 16)
    call gtk.widget_show_all(page)
    if fw["busy"]:
        call gtk.widget_set_sensitive(page, False)
    end
    fw["building"] = False
    return 0
end

# ---- zmeny (pkexec luxos-firewall ...) ----------------------------------------------------------------------

function run_cli(args):
    if fw["busy"]:
        return 0
    end
    # chybovy vystup pkexec/luxos-firewall do zpravy v okne
    argv = ["/bin/sh", "-c", "exec pkexec \"$0\" \"$@\" 2>&1", cli()]
    argv.extend(args)
    fw["busy"] = True
    fw["message"] = ""
    call gtk.widget_set_sensitive(fw["page"], False)
    if glib.spawn_capture(argv, on_done, args) == 0:
        fw["busy"] = False
        fw["message"] = i18n.T("pkexec could not be started.")
        call rebuild()
    end
    return 0
end

function on_done(args, output, status):
    fw["busy"] = False
    code = status // 256
    # 126 = zruseno v dialogu hesla, 127 = neovereno: jen obnovit stav
    if status != 0 and code != 126 and code != 127:
        fw["message"] = i18n.T("The change could not be made.") + " " + output.strip()
    end
    call rebuild()
    return 0
end

function on_switch(state, sw):
    if fw["building"]:
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
    if fw["building"]:
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
    if fw["building"] or combo not in fw["combos"]:
        return 0
    end
    item = fw["combos"][combo]
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
    if b not in fw["buttons"]:
        return 0
    end
    info = fw["buttons"][b]
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
        port = gtk.entry_get_text(fw["port"]).strip()
        if port == "":
            return 0
        end
        spec = port
        protos = ["tcp", "udp", "both"]
        p = protos[max(0, gtk.combo_box_get_active(fw["proto"]))]
        if p != "both":
            spec = port + "/" + p
        end
        source = "lan"
        if gtk.combo_box_get_active(fw["from"]) == 1:
            source = "any"
        end
        call run_cli(["allow", spec, "--from", source])
    end
    return 0
end

# Nove zablokovany program (requests.json od luxos-firewall-watch): obnovit seznam, pokud uzivatel nic nepise
function on_requests(path, event, other):
    name = path
    if event == gio.FILE_RENAMED:
        name = other
    end
    if not name.endswith("/requests.json") or fw["timer"] != 0:
        return 0
    end
    fw["timer"] = glib.timeout_add(700, refresh)
    return 0
end

function refresh():
    fw["timer"] = 0
    if not fw["busy"] and (fw["port"] == 0 or gtk.entry_get_text(fw["port"]) == ""):
        call rebuild()
    end
    return False
end

# Radky stranky (testy: switch RADEK = on) patri strance i pri obnove, kdyz je zrovna zobrazena jina stranka
function rebuild():
    saved = ui.state["rows"]
    ui.state["rows"] = fw["rows"]
    call build_content()
    ui.state["rows"] = saved
    return 0
end

# ---- stranka v okne Nastaveni -------------------------------------------------------------------------------------

function build(host):
    if fw["css"] == 0:
        fw["css"] = gtk.css_load(CSS)
        safe:
            call gio.file_monitor("/run/luxos-firewall", on_requests)
        end
    end
    fw["rows"] = ui.state["rows"]
    # stala vnejsi krabice, obsah se pri obnove jen vymeni; naplni ho show
    fw["outer"] = ui.page_box()
    fw["page"] = 0
    return fw["outer"]
end

# Stav firewallu se mohl zmenit jinde (luxos-firewall v Terminalu, upozorneni luxos-hub): pri kazdem zobrazeni znovu
function show(host):
    if not fw["busy"]:
        call rebuild()
    end
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1, luxos-settings preda prikazy, ktere nezna) -----------------------------------

function test(command, rest):
    if command == "fw-port" and fw["port"] != 0:
        # testctl "entry" pise do prvniho pole okna, tim je hledani v postrannim panelu
        call gtk.entry_set_text(fw["port"], rest)
    elif command == "fw-refresh":
        call refresh()
    else:
        return False
    end
    return True
end
