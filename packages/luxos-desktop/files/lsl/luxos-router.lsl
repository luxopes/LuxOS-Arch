# LuxOS - Sprava site (Router): udaje o siti, webova sprava routeru primo v aplikaci, zarizeni v domaci siti
# a rychle nastroje (ping, DNS, verejna adresa, rychlost). Drive Python (bin/luxos-router).
#
# Webova sprava bezi ve WebKitGTK (webkit2gtk-4.1); knihovna se nacte az pri prvnim otevreni karty Router
# (luxos_webkit.lsl) - prehled ji nepotrebuje. Pravidla (luxos_netadmin.lan_policy):
# - otevrou se jen adresy v domaci siti (privatni IP, vychozi brana, jmena prekladana jen na privatni adresy);
#   odkaz jinam otevre bezny prohlizec, presmerovani jinam se jen ohlasi,
# - vlastni (nedoveryhodny) certifikat HTTPS lze po vyslovnem potvrzeni povolit jen pro adresu vychozi brany
#   a jen do zavreni aplikace,
# - docasna relace (ephemeral): zadne cookies, mezipamet ani hesla na disku, prihlaseni HTTP Basic resi vlastni
#   dialog bez ukladani.
#
# Testy: LUXOS_ROUTER_PAGE=router|devices otevre rovnou kartu, LUXOS_IP, LUXOS_NMCLI, LUXOS_PING, LUXOS_CURL,
# LUXOS_GETENT (falesne programy), LUXOS_ROUTER_PORT, LUXOS_OUI_FILE, LUXOS_WEBKIT_LIB, LUXOS_TEST_CONTROL.
load env, json, process
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_netadmin as na
load luxos_settings_ui as sui
load luxos_testctl as testctl
load luxos_webkit as wk

CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 9px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.6; }\n.value { opacity: 0.8; }\n.ok { color: #1f9d55; }\n.bad { color: #d64545; }\n.hero-title { font-size: 20px; font-weight: 700; }\n.toolbar-box { padding: 6px 8px; border-bottom: 1px solid alpha(currentColor, 0.1); }\n"
ICON_BUTTON = 4
SCAN_WORKERS = 48

ui = {"window": 0, "info": {}, "tools": [], "devices": [], "opened": [], "test": False, "view": 0, "ctx": 0,
    "router_built": False, "allowed_hosts": {}, "https": False, "tls_allowed": [], "info_uri": "", "tls_dialog": 0,
    "scan": None}

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

function app_name():
    # cesky "Sprava site"; "Router" je zaroven nazev karty a zarizeni
    name = i18n.T("Router (app name)")
    if name == "Router (app name)":
        return "Router"
    end
    return name
end

function tool_cmd(name, default):
    return env.get(name, default)
end

# Vystup ip/nmcli/ping se cte podle anglickych slov ("yes"), cesky by psaly "ano"
function c_locale(argv):
    return ["env", "LC_ALL=C"] + argv
end

# Synchronne (prehled pri startu, jako drive): stdout pri kodu 0, jinak ""
function run_sync(argv):
    result = None
    safe:
        result = process.capture_result(glib.find_program_in_path("env"), c_locale(argv)[1:])
    end
    if result == None or not result["ok"]:
        return ""
    end
    return result["stdout"]
end

function open_in_browser(uri):
    if ui["test"]:
        # testy nikdy nespousti skutecny prohlizec
        ui["opened"].append(uri)
        return 0
    end
    if not glib.launch_uri(uri):
        call glib.spawn_quiet(["xdg-open", uri])
    end
    return 0
end

function label(text, xalign, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, xalign)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

# ---- udaje o siti -----------------------------------------------------------------------------------------

function network_info():
    ip = tool_cmd("LUXOS_IP", "ip")
    routes = na.parse_routes(run_sync([ip, "-j", "-4", "route", "show", "default"]))
    if len(routes) == 0:
        routes = na.parse_routes(run_sync([ip, "-4", "route", "show", "default"]))
    end
    info = {"gateway": "", "dev": "", "connection": "", "type": "", "ssid": "", "ip4": [], "ip6": [], "dns": [],
        "hwaddr": "", "gateway6": ""}
    if len(routes) > 0:
        info["gateway"] = routes[0]["gateway"]
        info["dev"] = routes[0]["dev"]
    end
    nmcli = tool_cmd("LUXOS_NMCLI", "nmcli")
    if info["dev"] != "":
        dev = na.parse_device_show(run_sync([nmcli, "-t", "device", "show", info["dev"]]))
        for k in ["connection", "type", "ip4", "ip6", "dns", "hwaddr"]:
            info[k] = dev[k]
        end
        if dev["type"] == "wifi":
            info["ssid"] = na.parse_wifi_ssid(run_sync([nmcli, "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "ifname", info["dev"], "--rescan", "no"]))
            if info["ssid"] == "":
                info["ssid"] = dev["connection"]
            end
        end
    end
    if len(info["dns"]) == 0:
        info["dns"] = na.parse_resolv_conf(glib.read_text("/etc/resolv.conf"))
    end
    routes6 = na.parse_routes(run_sync([ip, "-j", "-6", "route", "show", "default"]))
    if len(routes6) > 0:
        info["gateway6"] = routes6[0]["gateway"]
    end
    return info
end

# ---- skupiny radku ---------------------------------------------------------------------------------------

function group(page, title):
    call gtk.box_pack_start(page, label(title, 0.0, "group-title"), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

function row(g, title, widget, hint):
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, 0.0, ""), False, False, 0)
    if hint != "":
        h = label(hint, 0.0, "hint")
        call gtk.label_set_line_wrap(h, True)
        call gtk.label_set_max_width_chars(h, 50)
        call gtk.box_pack_start(texts, h, False, False, 0)
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

function value_row(g, title, value):
    l = label(value if value != "" else "—", 1.0, "value")
    call gtk.label_set_selectable(l, True)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 40)
    call row(g, title, l, "")
    return l
end

# ---- nastroje (tlacitko a vysledek vedle, vysledek z procesu na pozadi) ------------------------------------------

function tool(text, kind, arg, offline):
    box = gtk.box_new(gtk.HORIZONTAL, 10)
    t = {"box": box, "kind": kind, "arg": arg, "result": label("", 1.0, ""), "spinner": gtk.spinner_new(),
        "button": gtk.button_new(text), "job": 0}
    call gtk.label_set_line_wrap(t["result"], True)
    call gtk.label_set_max_width_chars(t["result"], 34)
    call gtk.box_pack_start(box, t["result"], False, False, 0)
    call gtk.box_pack_start(box, t["spinner"], False, False, 0)
    call gtk.box_pack_start(box, t["button"], False, False, 0)
    call gtk.connect_data(t["button"], "clicked", 0, on_tool, t)
    if offline != "":
        # bez site by nastroj jen selhal: tlacitko neaktivni a vedle vysvetleni
        call gtk.widget_set_sensitive(t["button"], False)
        call gtk.widget_set_tooltip(t["button"], offline)
        call gtk.label_set_text(t["result"], offline)
        call gtk.widget_add_class(t["result"], "hint")
    end
    ui["tools"].append(t)
    return box
end

function on_tool(t, button):
    call gtk.widget_set_sensitive(t["button"], False)
    call gtk.spinner_set(t["spinner"], True)
    call gtk.label_set_text(t["result"], "")
    t["job"] += 1
    job = [t, t["job"]]
    if t["kind"] == "ping":
        call ping(t["arg"], 4, 2, on_ping_done, job)
    elif t["kind"] == "dns":
        job.append(glib.monotonic_time())
        call glib.spawn_capture([tool_cmd("LUXOS_GETENT", "getent"), "ahosts", na.DNS_TEST_NAME], on_dns_done, job)
    elif t["kind"] == "public":
        job.append(0)
        call public_ip_next(job)
    elif t["kind"] == "speed":
        call glib.spawn_capture([tool_cmd("LUXOS_CURL", "curl"), "-s", "-o", "/dev/null", "-A", "LuxOS", "--max-time", "30",
            "-w", "%{size_download} %{time_total}", na.SPEED_URL], on_speed_done, job)
    end
    return 0
end

function tool_finished(t, text, good):
    call gtk.spinner_set(t["spinner"], False)
    call gtk.widget_set_sensitive(t["button"], True)
    call gtk.widget_remove_class(t["result"], "ok")
    call gtk.widget_remove_class(t["result"], "bad")
    call gtk.widget_add_class(t["result"], "ok" if good else "bad")
    call gtk.label_set_text(t["result"], text)
    return 0
end

function ping(host, count, timeout, handler, data):
    # pojistka jako drive timeout procesu: count * (timeout + 1) + 5 s
    argv = c_locale(["timeout", String(count * (timeout + 1) + 5), tool_cmd("LUXOS_PING", "ping"), "-n", "-c", String(count), "-W", String(timeout), host])
    if glib.spawn_capture(argv, handler, data) == 0:
        call handler(data, "", -1)
    end
    return 0
end

function on_ping_done(job, output, status):
    res = na.parse_ping(output)
    if res["sent"] == 0:
        call tool_finished(job[0], i18n.T("Could not run ping"), False)
    elif res["received"] == 0:
        call tool_finished(job[0], i18n.T("No reply"), False)
    else:
        loss = 100 - Int(100.0 * res["received"] / res["sent"] + 0.5)
        text = i18n.T("Replies")
        if res["avg"] != None:
            text = i18n.TF("%s ms", [i18n.decimal(na.fixed1(res["avg"]))])
        end
        if loss > 0:
            text += " · " + i18n.TF("%d %% lost", [loss])
        end
        call tool_finished(job[0], text, loss < 50)
    end
    return 0
end

function on_dns_done(job, output, status):
    ms = (glib.monotonic_time() - job[2]) // 1000
    if status != 0 or len(na.parse_hosts(output)) == 0:
        call tool_finished(job[0], i18n.T("Name lookup failed"), False)
    else:
        call tool_finished(job[0], i18n.TF("Works (%s ms)", [String(ms)]), True)
    end
    return 0
end

# Verejna adresa: sluzby postupne, prvni platna adresa (jen na vyzadani uzivatele)
function public_ip_next(job):
    if job[2] >= len(na.PUBLIC_IP_URLS):
        call tool_finished(job[0], i18n.T("Not available"), False)
        return 0
    end
    url = na.PUBLIC_IP_URLS[job[2]]
    job[2] += 1
    if glib.spawn_capture([tool_cmd("LUXOS_CURL", "curl"), "-fsS", "-A", "LuxOS", "--max-time", "8", url], on_public_ip, job) == 0:
        call public_ip_next(job)
    end
    return 0
end

function on_public_ip(job, output, status):
    text = output[:100].strip()
    if status == 0 and na.is_ip(text):
        call tool_finished(job[0], text, True)
    else:
        call public_ip_next(job)
    end
    return 0
end

# Odhad rychlosti stahovani z bajtu a doby, kterou hlasi curl (i po vyprseni casu)
function on_speed_done(job, output, status):
    parts = output.strip().split(" ")
    mbit = -1.0
    if len(parts) == 2:
        safe:
            got = Float(parts[0])
            dt = Float(parts[1])
            if got >= 100000.0 and dt > 0.0:
                mbit = got * 8.0 / dt / 1000000.0
            end
        end
    end
    if mbit < 0.0:
        call tool_finished(job[0], i18n.T("Measurement failed"), False)
    else:
        call tool_finished(job[0], i18n.TF("%s Mbit/s", [i18n.decimal(na.fixed1(mbit))]), True)
    end
    return 0
end

# ---- prehled ---------------------------------------------------------------------------------------------

function load_info():
    ui["info"] = network_info()
    call build_overview()
    return 0
end

function build_overview():
    child = gtk.bin_get_child(ui["overview"])
    if child != 0:
        call gtk.widget_destroy(child)
    end
    ui["tools"] = []
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 10, 22)
    call gtk.container_add(ui["overview"], page)
    info = ui["info"]
    gw = info["gateway"]
    head = gtk.box_new(gtk.HORIZONTAL, 14)
    icon = gtk.image_new_from_icon_name("luxos-router", gtk.ICON_DIALOG)
    call gtk.image_set_pixel_size(icon, 56)
    call gtk.box_pack_start(head, icon, False, False, 0)
    titles = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(titles, gtk.ALIGN_CENTER)
    title = info["ssid"]
    if title == "":
        title = info["connection"]
    end
    if title == "":
        title = i18n.T("Not connected")
    end
    t = label(title, 0.0, "hero-title")
    call gtk.widget_set_name(t, "hero-title")
    call gtk.box_pack_start(titles, t, False, False, 0)
    sub = label(i18n.TF("Router: %s", [gw]) if gw != "" else i18n.T("No router (default gateway) found."), 0.0, "hint")
    call gtk.widget_set_name(sub, "hero-sub")
    call gtk.box_pack_start(titles, sub, False, False, 0)
    call gtk.box_pack_start(head, titles, True, True, 0)
    refresh = gtk.button_new_from_icon_name("view-refresh-symbolic", ICON_BUTTON)
    call gtk.widget_set_tooltip(refresh, i18n.T("Refresh"))
    call gtk.widget_set_valign(refresh, gtk.ALIGN_CENTER)
    call gtk.connect_data(refresh, "clicked", 0, on_refresh, 0)
    call gtk.box_pack_end(head, refresh, False, False, 0)
    if gw != "":
        open_btn = gtk.button_new(i18n.T("Open Router Settings"))
        call gtk.widget_set_valign(open_btn, gtk.ALIGN_CENTER)
        call gtk.widget_add_class(open_btn, "suggested-action")
        call gtk.connect_data(open_btn, "clicked", 0, on_open_router, 0)
        call gtk.box_pack_end(head, open_btn, False, False, 0)
    end
    call gtk.box_pack_start(page, head, False, False, 6)

    g = group(page, i18n.T("Network"))
    kind = info["type"]
    if kind == "wifi":
        kind = i18n.T("Wi-Fi")
    elif kind == "ethernet":
        kind = i18n.T("Ethernet (cable)")
    end
    call value_row(g, i18n.T("Connection"), " · ".join([x for x in [info["connection"], kind] if x != ""]))
    if info["ssid"] != "":
        call value_row(g, i18n.T("Wi-Fi network"), info["ssid"])
    end
    call value_row(g, i18n.T("Interface"), info["dev"])
    call value_row(g, i18n.T("IP address"), ", ".join(info["ip4"]))
    call value_row(g, i18n.T("Router (gateway)"), gw)
    if info["gateway6"] != "":
        call value_row(g, i18n.T("IPv6 gateway"), info["gateway6"])
    end
    call value_row(g, i18n.T("DNS servers"), ", ".join(info["dns"]))
    call value_row(g, i18n.T("MAC address"), info["hwaddr"])
    # bez pripojeni (zadna vychozi brana) nastroje nemaji smysl - tlacitka neaktivni s vysvetlenim
    offline = ""
    if gw == "" and info["gateway6"] == "":
        offline = i18n.T("Not connected to a network")
    end
    call row(g, i18n.T("Public IP address"), tool(i18n.T("Show"), "public", "", offline), i18n.T("Asks an internet service (ipify.org) for the address your network is seen from."))

    g = group(page, i18n.T("Quick Tests"))
    if gw != "":
        call row(g, i18n.T("Ping router"), tool(i18n.T("Test"), "ping", gw, ""), "")
    end
    call row(g, i18n.T("Ping internet"), tool(i18n.T("Test"), "ping", na.INTERNET_HOST, offline), i18n.TF("Sends 4 packets to %s.", [na.INTERNET_HOST]))
    call row(g, i18n.T("Name lookup (DNS)"), tool(i18n.T("Test"), "dns", "", offline), i18n.TF("Looks up %s using your DNS servers.", [na.DNS_TEST_NAME]))
    call row(g, i18n.T("Download speed"), tool(i18n.T("Measure"), "speed", "", offline), i18n.T("Estimate: downloads 10 MB from speed.cloudflare.com."))
    call gtk.widget_show_all(page)
    return 0
end

function on_refresh(unused, b):
    call load_info()
    return 0
end

function on_open_router(unused, b):
    call gtk.stack_set_visible_child_name(ui["stack"], "router")
    return 0
end

# ---- zarizeni -----------------------------------------------------------------------------------------------

function build_devices():
    box = gtk.box_new(gtk.VERTICAL, 0)
    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(bar, "toolbar-box")
    ui["dev_status"] = label("", 0.0, "hint")
    call gtk.widget_set_name(ui["dev_status"], "dev-status")
    ui["dev_spinner"] = gtk.spinner_new()
    refresh = gtk.button_new(i18n.T("Refresh"))
    call gtk.connect_data(refresh, "clicked", 0, on_refresh_devices, 0)
    ui["scan_btn"] = gtk.button_new(i18n.T("Search Network"))
    call gtk.widget_set_tooltip(ui["scan_btn"], i18n.T("Briefly contacts every address in your home network so that devices which were quiet also appear."))
    call gtk.connect_data(ui["scan_btn"], "clicked", 0, on_scan, 0)
    call gtk.box_pack_start(bar, ui["dev_status"], True, True, 4)
    call gtk.box_pack_end(bar, ui["scan_btn"], False, False, 0)
    call gtk.box_pack_end(bar, refresh, False, False, 0)
    call gtk.box_pack_end(bar, ui["dev_spinner"], False, False, 0)
    call gtk.box_pack_start(box, bar, False, False, 0)
    # adresa, nazev/vyrobce, MAC, stav, poradi (razeni sloupce Adresa)
    unsafe:
        store = __lsl_qbe_call6(__lsl_symbol("gtk_list_store_new"), 5, 64, 64, 64, 64, 24)
        tree = __lsl_qbe_call1(__lsl_symbol("gtk_tree_view_new_with_model"), store)
    end
    ui["store"] = store
    titles = [i18n.T("Address"), i18n.T("Device"), i18n.T("MAC address"), i18n.T("State")]
    for i in range(4):
        unsafe:
            renderer = __lsl_qbe_call0(__lsl_symbol("gtk_cell_renderer_text_new"))
            col = __lsl_qbe_call5(__lsl_symbol("gtk_tree_view_column_new_with_attributes"), cstr(titles[i]), renderer, cstr("text"), ptr(i), 0)
            call __lsl_qbe_call2(__lsl_symbol("gtk_tree_view_column_set_resizable"), col, 1)
            call __lsl_qbe_call2(__lsl_symbol("gtk_tree_view_column_set_sort_column_id"), col, ptr(4 if i == 0 else i))
            if i == 1:
                call __lsl_qbe_call2(__lsl_symbol("gtk_tree_view_column_set_expand"), col, 1)
            end
            call __lsl_qbe_call2(__lsl_symbol("gtk_tree_view_append_column"), tree, col)
        end
    end
    sc = gtk.scrolled_window_new()
    call gtk.container_add(sc, tree)
    call gtk.box_pack_start(box, sc, True, True, 0)
    return box
end

function on_refresh_devices(unused, b):
    call refresh_devices()
    return 0
end

# ip neigh, pak vyrobci z mistniho souboru OUI (grep -F, soubor se necte do pameti)
function refresh_devices():
    argv = [tool_cmd("LUXOS_IP", "ip"), "-j", "neigh", "show"]
    if ui["info"]["dev"] != "":
        argv = argv + ["dev", ui["info"]["dev"]]
    end
    call gtk.spinner_set(ui["dev_spinner"], True)
    job = {"info": ui["info"]}
    if glib.spawn_capture(c_locale(argv), on_neigh, job) == 0:
        call on_neigh(job, "", -1)
    end
    return 0
end

function on_neigh(job, output, status):
    job["neigh"] = na.parse_neigh(output)
    macs = [n["mac"] for n in job["neigh"]]
    if job["info"]["hwaddr"] != "":
        macs.append(job["info"]["hwaddr"].lower())
    end
    job["macs"] = macs
    patterns = na.oui_patterns(macs)
    oui = ""
    for path in env.get("LUXOS_OUI_FILE", ":".join(na.OUI_FILES)).split(":"):
        if oui == "" and path != "" and len(glib.stat(path)) > 0:
            oui = path
        end
    end
    if len(patterns) == 0 or oui == "":
        call show_devices(job, "", 0)
        return 0
    end
    argv = ["grep", "-F"]
    for p in patterns:
        argv = argv + ["-e", p]
    end
    if glib.spawn_capture(argv + [oui], show_devices, job) == 0:
        call show_devices(job, "", 0)
    end
    return 0
end

function show_devices(job, oui_text, status):
    call gtk.spinner_set(ui["dev_spinner"], False)
    vendors = na.oui_parse(oui_text, job["macs"])
    info = job["info"]
    states = {"REACHABLE": i18n.T("Active"), "STALE": i18n.T("Seen recently"), "DELAY": i18n.T("Active"),
        "PROBE": i18n.T("Checking"), "PERMANENT": i18n.T("Fixed")}
    rows = List(job["neigh"])
    if len(info["ip4"]) > 0:
        rows.append({"ip": info["ip4"][0].split("/")[0], "mac": info["hwaddr"].lower(), "state": "SELF"})
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gtk_list_store_clear"), ptr(ui["store"]))
    end
    ui["devices"] = []
    for i in range(len(rows)):
        n = rows[i]
        name = vendors.get(n["mac"], "")
        if name == "" and na.is_random_mac(n["mac"]):
            name = i18n.T("Private address (random MAC)")
        end
        if n["ip"] == info["gateway"]:
            name = i18n.T("Router") + (" – " + name if name != "" else "")
        end
        if n["state"] == "SELF":
            name = i18n.T("This computer") + (" – " + name if name != "" else "")
        end
        state = states.get(n["state"], n["state"].capitalize())
        if n["state"] == "SELF":
            state = i18n.T("This computer")
        end
        cells = [n["ip"], name, n["mac"], state]
        ui["devices"].append(cells)
        unsafe:
            it = __lsl_byte_zeros(32)
            iter = glib.data(it)
            call __lsl_qbe_call2(__lsl_symbol("gtk_list_store_append"), ptr(ui["store"]), iter)
            for c in range(4):
                call __lsl_qbe_call5(__lsl_symbol("gtk_list_store_set"), ptr(ui["store"]), iter, ptr(c), cstr(cells[c]), -1)
            end
            call __lsl_qbe_call5(__lsl_symbol("gtk_list_store_set"), ptr(ui["store"]), iter, 4, ptr(i), -1)
        end
    end
    call gtk.label_set_text(ui["dev_status"], i18n.TF("%d devices", [len(rows)]))
    return 0
end

# Probuzeni tichych zarizeni: jeden ping na kazdou adresu site, nejvys 48 najednou
function on_scan(unused, b):
    addrs = ui["info"]["ip4"]
    targets = []
    if len(addrs) > 0:
        targets = na.scan_targets(addrs[0])
    end
    if len(targets) == 0:
        return 0
    end
    call gtk.widget_set_sensitive(ui["scan_btn"], False)
    call gtk.spinner_set(ui["dev_spinner"], True)
    call gtk.label_set_text(ui["dev_status"], i18n.TF("Searching %d addresses…", [len(targets)]))
    ui["scan"] = {"queue": targets, "next": 0, "running": 0}
    for i in range(min(SCAN_WORKERS, len(targets))):
        call scan_next(ui["scan"])
    end
    return 0
end

function scan_next(scan):
    if scan["next"] >= len(scan["queue"]):
        if scan["running"] == 0:
            ui["scan"] = None
            call gtk.widget_set_sensitive(ui["scan_btn"], True)
            call refresh_devices()
        end
        return 0
    end
    host = scan["queue"][scan["next"]]
    scan["next"] += 1
    scan["running"] += 1
    call ping(host, 1, 1, on_scan_ping, scan)
    return 0
end

function on_scan_ping(scan, output, status):
    scan["running"] -= 1
    call scan_next(scan)
    return 0
end

# ---- webova sprava routeru ------------------------------------------------------------------------------------

function gateway():
    return ui["info"]["gateway"]
end

function router_url(https):
    return na.router_url(gateway(), https, env.get("LUXOS_ROUTER_PORT", ""))
end

function icon_button(icon, tip, handler):
    b = gtk.button_new_from_icon_name(icon, ICON_BUTTON)
    call gtk.widget_set_tooltip(b, tip)
    call gtk.connect_data(b, "clicked", 0, handler, 0)
    return b
end

# Karta se stavi az pri prvnim zobrazeni (WebKit jen kdyz je potreba)
function ensure_router():
    if ui["router_built"]:
        return 0
    end
    ui["router_built"] = True
    page = ui["router_page"]
    if not wk.available():
        box = gtk.box_new(gtk.VERTICAL, 12)
        call gtk.widget_set_valign(box, gtk.ALIGN_CENTER)
        call gtk.widget_set_margin(box, 30)
        l = gtk.label_new(i18n.T("The built-in web view (WebKitGTK) is not available. The router settings will open in your web browser."))
        call gtk.label_set_line_wrap(l, True)
        call gtk.widget_set_name(l, "no-webkit")
        b = gtk.button_new(i18n.T("Open in Browser"))
        call gtk.widget_set_halign(b, gtk.ALIGN_CENTER)
        call gtk.connect_data(b, "clicked", 0, on_browser_router, 0)
        call gtk.box_pack_start(box, l, False, False, 0)
        call gtk.box_pack_start(box, b, False, False, 0)
        call gtk.box_pack_start(page, box, True, True, 0)
        call gtk.widget_show_all(page)
        return 0
    end
    bar = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_add_class(bar, "toolbar-box")
    ui["back"] = icon_button("go-previous-symbolic", i18n.T("Back"), on_back)
    reload = icon_button("view-refresh-symbolic", i18n.T("Reload"), on_reload)
    proto = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(proto, "http", "HTTP")
    call gtk.combo_box_text_append(proto, "https", "HTTPS")
    call sui.combo_set_active_id(proto, "http")
    call gtk.widget_set_tooltip(proto, i18n.T("Connect to the router with HTTP or HTTPS"))
    call gtk.connect_data(proto, "changed", 0, on_proto, 0)
    ui["proto"] = proto
    ui["lock"] = gtk.image_new()
    ui["address"] = gtk.label_new("")
    call gtk.label_set_xalign(ui["address"], 0.0)
    call gtk.label_set_ellipsize(ui["address"], 3)
    call gtk.label_set_selectable(ui["address"], True)
    call gtk.widget_set_name(ui["address"], "address")
    browser = gtk.button_new(i18n.T("Open in Browser"))
    call gtk.connect_data(browser, "clicked", 0, on_browser_current, 0)
    for w in [ui["back"], reload, proto]:
        call gtk.box_pack_start(bar, w, False, False, 0)
    end
    call gtk.box_pack_start(bar, ui["lock"], False, False, 4)
    call gtk.box_pack_start(bar, ui["address"], True, True, 0)
    call gtk.box_pack_end(bar, browser, False, False, 0)
    call gtk.box_pack_start(page, bar, False, False, 0)

    unsafe:
        infobar = __lsl_qbe_call0(__lsl_symbol("gtk_info_bar_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_show_close_button"), infobar, 1)
        call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_revealed"), infobar, 0)
        content = __lsl_qbe_call1(__lsl_symbol("gtk_info_bar_get_content_area"), infobar)
        ui["info_button"] = __lsl_qbe_call3(__lsl_symbol("gtk_info_bar_add_button"), infobar, cstr(i18n.T("Open in Browser")), 1)
    end
    ui["infobar"] = infobar
    ui["info_label"] = gtk.label_new("")
    call gtk.label_set_xalign(ui["info_label"], 0.0)
    call gtk.label_set_line_wrap(ui["info_label"], True)
    call gtk.widget_set_name(ui["info_label"], "info-label")
    call gtk.container_add(content, ui["info_label"])
    call gtk.connect_data(infobar, "response", 1, on_info_response, 0)
    call gtk.box_pack_start(page, infobar, False, False, 0)

    ctx = wk.ephemeral_context()
    ui["ctx"] = ctx
    call gtk.connect_data(ctx, "download-started", 1, on_download, 0)
    view = wk.view_new(ctx)
    ui["view"] = view
    call gtk.connect_data(view, "decide-policy", 2, on_policy, 0)
    call gtk.connect_data(view, "load-failed-with-tls-errors", 3, on_tls, 0)
    call gtk.connect_data(view, "load-failed", 3, on_failed, 0)
    call gtk.connect_data(view, "authenticate", 1, on_auth, 0)
    call gtk.connect_data(view, "load-changed", 1, on_load_changed, 0)
    call gtk.box_pack_start(page, view, True, True, 0)
    call gtk.widget_show_all(page)
    call load_router(None)
    return 0
end

function on_back(unused, b):
    call wk.go_back(ui["view"])
    return 0
end

function on_reload(unused, b):
    call wk.reload(ui["view"])
    return 0
end

function on_browser_router(unused, b):
    call open_in_browser(router_url(False))
    return 0
end

function on_browser_current(unused, b):
    uri = wk.uri(ui["view"])
    if uri == "":
        uri = router_url(False)
    end
    call open_in_browser(uri)
    return 0
end

function load_router(https):
    if ui["view"] == 0:
        return 0
    end
    if https != None:
        ui["https"] = https
        call sui.combo_set_active_id(ui["proto"], "https" if https else "http")
    end
    url = router_url(ui["https"])
    if url == "":
        call wk.load_html(ui["view"], "<html><body style='font-family:sans-serif;padding:40px'>" + glib.markup_escape(i18n.T("Not connected to a network.")) + "</body></html>")
        return 0
    end
    call wk.load_uri(ui["view"], url)
    return 0
end

function on_proto(unused, combo):
    https = sui.combo_active_id(combo) == "https"
    if https != ui["https"]:
        ui["https"] = https
        call load_router(None)
    end
    return 0
end

# ---- informacni lista ----

function notify(text, uri, kind):
    call gtk.label_set_text(ui["info_label"], text)
    ui["info_uri"] = uri
    call gtk.widget_set_visible(ui["info_button"], uri != "")
    unsafe:
        # GTK_MESSAGE_INFO 0, WARNING 1, ERROR 3
        call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_message_type"), ptr(ui["infobar"]), ptr(kind))
        call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_revealed"), ptr(ui["infobar"]), 1)
    end
    return 0
end

function info_revealed():
    if ui["view"] == 0:
        return False
    end
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_info_bar_get_revealed"), ptr(ui["infobar"]))) != 0
    end
end

function on_info_response(unused, response, bar):
    if response == 1 and ui["info_uri"] != "":
        call open_in_browser(ui["info_uri"])
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_revealed"), ptr(bar), 0)
    end
    return 0
end

# ---- pravidla navigace ----

function leave(uri, user):
    if user:
        call open_in_browser(uri)
        call notify(i18n.T("The link leads outside your home network, so it was opened in your web browser."), "", 0)
    else:
        call notify(i18n.TF("The page wanted to open an address outside your home network: %s", [na.url_host(uri)]), uri, 1)
    end
    return 0
end

# Jmeno (fritz.box): povolit jen kdyz se preklada vyhradne do domaci site (getent = systemovy resolver)
function resolve(uri, user):
    job = [uri, user, na.url_host(uri)]
    if glib.spawn_capture([tool_cmd("LUXOS_GETENT", "getent"), "ahosts", job[2]], on_resolved, job) == 0:
        call on_resolved(job, "", -1)
    end
    return 0
end

function on_resolved(job, output, status):
    ok = status == 0 and na.all_lan(na.parse_hosts(output), gateway())
    ui["allowed_hosts"][job[2]] = ok
    if ui["view"] == 0:
        return 0
    end
    if ok:
        call wk.load_uri(ui["view"], job[0])
    else:
        call leave(job[0], job[1])
    end
    return 0
end

function on_policy(unused, decision, kind, view):
    if kind == wk.RESPONSE:
        if wk.response_needs_download(decision):
            call wk.decide(decision, "download")
            return True
        end
        return False
    end
    nav = wk.navigation(decision)
    uri = nav[0]
    user = nav[1] or kind == wk.NEW_WINDOW_ACTION
    policy = na.lan_policy(uri, gateway())
    host = na.url_host(uri)
    if policy == "resolve" and host in ui["allowed_hosts"]:
        policy = "allow" if ui["allowed_hosts"][host] else "external"
    end
    if policy == "allow":
        if kind == wk.NEW_WINDOW_ACTION:
            call wk.decide(decision, "ignore")
            call wk.load_uri(view, uri)
        else:
            call wk.decide(decision, "use")
        end
        return True
    end
    call wk.decide(decision, "ignore")
    if policy == "external":
        call leave(uri, user)
    elif policy == "resolve":
        call resolve(uri, user)
    end
    return True
end

# ---- certifikaty a prihlaseni ----

function on_tls(unused, uri_ptr, cert, errors, view):
    uri = glib.from_c(uri_ptr)
    return tls_failed(uri, cert)
end

function tls_failed(uri, cert):
    host = na.url_host(uri)
    if not na.tls_exception_allowed(uri, gateway()):
        call notify(i18n.TF("The connection to %s is not secure (untrusted certificate). Only your router's own address can be allowed.", [host]), "", 3)
        return True
    end
    unsafe:
        # GTK_DIALOG_MODAL, GTK_MESSAGE_WARNING, GTK_BUTTONS_NONE
        dlg = __lsl_qbe_call6(__lsl_symbol("gtk_message_dialog_new"), ptr(ui["window"]), 1, 1, 0, cstr("%s"), cstr(i18n.T("The router uses its own security certificate")))
        call __lsl_qbe_call3(__lsl_symbol("gtk_message_dialog_format_secondary_text"), dlg, cstr("%s"), cstr(i18n.TF("Routers usually have a self-signed certificate that cannot be verified. Continue only if %s is your router. The exception applies to this address only, until you close the app.", [host])))
    end
    call gtk.dialog_add_button(dlg, i18n.T("Cancel"), -6)
    go = gtk.dialog_add_button(dlg, i18n.T("Continue"), -5)
    call gtk.widget_add_class(go, "destructive-action")
    call gtk.dialog_set_default_response(dlg, -6)
    ui["tls_dialog"] = dlg
    response = gtk.dialog_run(dlg)
    call gtk.widget_destroy(dlg)
    ui["tls_dialog"] = 0
    if response == -5:
        call wk.allow_certificate(ui["ctx"], cert, host)
        if not (host in ui["tls_allowed"]):
            ui["tls_allowed"].append(host)
        end
        call wk.load_uri(ui["view"], uri)
    else:
        call load_router(False)
    end
    return True
end

function on_failed(unused, event, uri_ptr, error, view):
    e = wk.error_info(error)
    if e["policy"] and e["code"] == wk.POLICY_INTERRUPTED:
        return True
    end
    if e["network"] and e["code"] == wk.NETWORK_CANCELLED:
        return True
    end
    if na.url_host(glib.from_c(uri_ptr)) == gateway().lower() and not ui["https"]:
        call notify(i18n.T("The router does not answer over HTTP. Try HTTPS."), "", 1)
    else:
        call notify(i18n.TF("The page could not be loaded: %s", [e["message"]]), "", 1)
    end
    return False
end

function on_auth(unused, request, view):
    if wk.auth_is_proxy(request):
        return False
    end
    dlg = gtk.dialog_new()
    call gtk.window_set_title(dlg, i18n.T("Sign In"))
    call gtk.window_set_transient_for(dlg, ui["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.dialog_add_button(dlg, i18n.T("Cancel"), -6)
    ok = gtk.dialog_add_button(dlg, i18n.T("Sign In"), -5)
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.dialog_set_default_response(dlg, -5)
    box = gtk.dialog_get_content_area(dlg)
    call gtk.container_set_border_width(box, 16)
    call gtk.box_set_spacing(box, 8)
    msg = gtk.label_new(i18n.TF("%s asks for a user name and password. They are not saved.", [wk.auth_host(request)]))
    call gtk.label_set_line_wrap(msg, True)
    call gtk.label_set_xalign(msg, 0.0)
    call gtk.label_set_max_width_chars(msg, 44)
    call gtk.box_pack_start(box, msg, False, False, 0)
    user = gtk.entry_new()
    call gtk.entry_set_placeholder_text(user, i18n.T("User name"))
    call gtk.entry_set_activates_default(user, True)
    pw = gtk.entry_new()
    call gtk.entry_set_placeholder_text(pw, i18n.T("Password"))
    call gtk.entry_set_visibility(pw, False)
    call gtk.entry_set_activates_default(pw, True)
    unsafe:
        # GTK_INPUT_PURPOSE_PASSWORD
        call __lsl_qbe_call2(__lsl_symbol("gtk_entry_set_input_purpose"), ptr(pw), 8)
    end
    call gtk.box_pack_start(box, user, False, False, 0)
    call gtk.box_pack_start(box, pw, False, False, 0)
    call gtk.widget_show_all(box)
    response = gtk.dialog_run(dlg)
    u = gtk.entry_get_text(user)
    p = gtk.entry_get_text(pw)
    call gtk.widget_destroy(dlg)
    if response == -5:
        call wk.authenticate(request, u, p)
    else:
        call wk.auth_cancel(request)
    end
    return True
end

function on_load_changed(unused, event, view):
    uri = wk.uri(view)
    call gtk.label_set_text(ui["address"], uri)
    call gtk.widget_set_sensitive(ui["back"], wk.can_go_back(view))
    secure = uri.startswith("https://")
    icon = "channel-insecure-symbolic"
    tip = i18n.T("Unencrypted connection (HTTP) inside your home network")
    if secure and na.url_host(uri) in ui["tls_allowed"]:
        icon = "dialog-warning-symbolic"
        tip = i18n.T("Encrypted connection, certificate allowed by you")
    elif secure:
        icon = "channel-secure-symbolic"
        tip = i18n.T("Encrypted connection (HTTPS)")
    end
    call gtk.image_set_from_icon_name(ui["lock"], icon, ICON_BUTTON)
    call gtk.widget_set_tooltip(ui["lock"], tip)
    if (uri.startswith("http://") or secure) and na.url_host(uri) == gateway().lower():
        ui["https"] = secure
        call sui.combo_set_active_id(ui["proto"], "https" if secure else "http")
    end
    if event == wk.LOAD_COMMITTED:
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gtk_info_bar_set_revealed"), ptr(ui["infobar"]), 0)
        end
    end
    return 0
end

# ---- stahovani (zaloha nastaveni routeru) ----

function on_download(unused, download, ctx):
    call gtk.connect_data(download, "decide-destination", 1, on_destination, 0)
    call gtk.connect_data(download, "finished", 0, on_download_finished, 0)
    return 0
end

function basename(path):
    parts = path.split("/")
    return parts[len(parts) - 1]
end

function on_destination(unused, suggested_ptr, download):
    # G_USER_DIRECTORY_DOWNLOAD
    folder = glib.user_special_dir(2)
    if folder == "":
        folder = env.get("HOME", "/tmp") + "/Downloads"
    end
    call glib.mkdir_p(folder)
    name = basename(glib.from_c(suggested_ptr)).lstrip(".")
    if name == "":
        name = "download"
    end
    base = name
    ext = ""
    dot = len(name) - 1
    while dot > 0 and name[dot] != ".":
        dot -= 1
    end
    if dot > 0:
        base = name[:dot]
        ext = name[dot:]
    end
    path = folder + "/" + name
    n = 1
    while len(glib.stat(path)) > 0:
        path = folder + "/" + base + " (" + String(n) + ")" + ext
        n += 1
    end
    unsafe:
        file_uri = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_to_uri"), cstr(path), 0, 0))
    end
    call wk.download_set_destination(download, file_uri)
    return True
end

function on_download_finished(unused, download):
    unsafe:
        path = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_from_uri"), cstr(wk.download_destination(download)), 0, 0))
    end
    call notify(i18n.TF("Saved to Downloads: %s", [basename(path)]), "", 0)
    return 0
end

# ---- okno -----------------------------------------------------------------------------------------------------

function on_page(unused, pspec, stack):
    name = gtk.stack_get_visible_child_name(stack)
    if name == "router":
        call ensure_router()
    elif name == "devices":
        call refresh_devices()
    end
    return 0
end

function build():
    window = sui.window(app_name(), "luxos-router", 980, 720, 600, 420)
    ui["window"] = window
    call gtk.window_set_wmclass(window, "luxos-router", "luxos-router")
    stack = gtk.stack_new(True)
    ui["stack"] = stack
    unsafe:
        switcher = __lsl_qbe_call0(__lsl_symbol("gtk_stack_switcher_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_stack_switcher_set_stack"), switcher, ptr(stack))
        call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_custom_title"), __lsl_qbe_call1(__lsl_symbol("gtk_window_get_titlebar"), ptr(window)), switcher)
    end
    ui["overview"] = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(ui["overview"], gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    ui["router_page"] = gtk.box_new(gtk.VERTICAL, 0)
    pages = [[ui["overview"], "overview", i18n.T("Overview")], [ui["router_page"], "router", i18n.T("Router")],
        [build_devices(), "devices", i18n.T("Devices")]]
    for p in pages:
        unsafe:
            call __lsl_qbe_call4(__lsl_symbol("gtk_stack_add_titled"), ptr(stack), ptr(p[0]), cstr(p[1]), cstr(p[2]))
        end
    end
    call gtk.connect_data(stack, "notify::visible-child-name", 1, on_page, 0)
    call gtk.container_add(window, stack)
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
    call load_info()
end

function on_destroy(unused, window):
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ----------------------------------------------------------------------------

function test_state():
    view = ui["view"]
    s = {"page": gtk.stack_get_visible_child_name(ui["stack"]), "view": view != 0,
        "tools": [gtk.label_get_text(t["result"]) for t in ui["tools"]],
        "tool_sensitive": [gtk.widget_get_sensitive(t["button"]) for t in ui["tools"]],
        "devices": ui["devices"], "scan_sensitive": gtk.widget_get_sensitive(ui["scan_btn"]),
        "opened": ui["opened"], "tls_allowed": ui["tls_allowed"], "tls_dialog": ui["tls_dialog"] != 0,
        "info": info_revealed(), "info_uri": ui["info_uri"], "size": gtk.window_get_size(ui["window"])}
    unsafe:
        cells = __lsl_byte_zeros(8)
        call __lsl_qbe_call3(__lsl_symbol("gtk_widget_get_size_request"), ptr(ui["window"]), glib.data(cells), glib.data(cells) + 4)
        s["min"] = [__lsl_qbe_s32(__lsl_qbe_load32(glib.data(cells))), __lsl_qbe_s32(__lsl_qbe_load32(glib.data(cells) + 4))]
    end
    if view != 0:
        s["ephemeral"] = wk.is_ephemeral(ui["ctx"])
        s["uri"] = wk.uri(view)
        s["title"] = wk.title(view)
        s["loading"] = wk.is_loading(view)
        s["info_text"] = gtk.label_get_text(ui["info_label"])
        s["proto"] = sui.combo_active_id(ui["proto"])
    end
    return s
end

function on_test(command, rest):
    if command == "state":
        print "state " + json.encode(test_state())
    elif command == "page":
        call gtk.stack_set_visible_child_name(ui["stack"], rest)
    elif command == "tool":
        call gtk.button_clicked(ui["tools"][Int(rest)]["button"])
    elif command == "load":
        call wk.load_uri(ui["view"], rest)
    elif command == "js":
        call wk.run_script(ui["view"], rest)
    elif command == "tls":
        # certifikat jineho zarizeni nez brany: jen oznameni, zadny dialog
        call tls_failed(rest, 0)
    elif command == "close":
        call gtk.window_close(ui["window"])
    end
end

# ---- start ---------------------------------------------------------------------------------------------------

call glib.set_prgname("luxos-router")
call glib.set_application_name(app_name())
call gtk.init()
call gtk.css_load(CSS)
ui["test"] = env.get("LUXOS_TEST_CONTROL", "") == "1"
call build()
call gtk.widget_show_all(ui["window"])
start_page = env.get("LUXOS_ROUTER_PAGE", "")
if start_page == "router" or start_page == "devices":
    call gtk.stack_set_visible_child_name(ui["stack"], start_page)
end
call testctl.start(on_test)
call gtk.main()
