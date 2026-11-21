# LuxOS - Nastaveni > Wi-Fi (drive luxos-wifi-qr): sdileni pripojene site QR kodem a pripojeni k siti z QR kodu kamerou.
#
#   luxos-wifi-qr            stranka s QR kodem aktualni site Wi-Fi (telefon se pripoji naskenovanim)
#   luxos-wifi-qr --scan     naskenovat QR kod site kamerou a pripojit se (luxos-camera --scan-wifi), bez okna
#
# Heslo cte z NetworkManageru (nmcli --show-secrets). Systemova pripojeni muze NetworkManager bez overeni
# nevydat - pak tlacitko "Zobrazit heslo" pozada o heslo spravce (pkexec nmcli). Heslo se nikam nevypisuje.
# Testy: LUXOS_NMCLI (falesny nmcli), LUXOS_PKEXEC, LUXOS_ZXING_LIB, LUXOS_CAMERA_TEST, LUXOS_VIDEO_DEV_DIR.
load env, cairo, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_qr as qr
load luxos_sys as sys
load luxos_settings_ui as ui

QUIET = 4          # okraj QR kodu v modulech (norma: 4)
CSS = ".wifi-page .qr-card { background-color: white; border-radius: 18px; padding: 14px;\n           box-shadow: 0 2px 10px alpha(black, 0.18); }\n.wifi-page .ssid { font-size: 20px; font-weight: 800; }\n.wifi-page .dim { opacity: 0.65; }\n.wifi-page .state-title { font-size: 18px; font-weight: 800; }\n.wifi-page .suggested-action { border-radius: 999px; padding: 6px 22px; font-weight: 700; }\n.wifi-page .pill { border-radius: 999px; padding: 4px 16px; }\n.wifi-page .icon-btn { padding: 4px; min-width: 28px; min-height: 28px; border-radius: 8px; background-image: none;\n              border: none; box-shadow: none; background-color: transparent; }\n.wifi-page .icon-btn:hover { background-color: alpha(currentColor, 0.08); }\n.wifi-page .icon-btn:active { background-color: alpha(currentColor, 0.14); }\n"

V = {"window": 0, "matrix": [], "info": None, "act": None, "loading": 0}

function nmcli():
    return env.get("LUXOS_NMCLI", "nmcli")
end

function has_camera():
    mode = env.get("LUXOS_CAMERA_TEST", "").strip().lower()
    if mode != "" and mode != "none":
        return True
    end
    dir = env.get("LUXOS_VIDEO_DEV_DIR", "")
    if dir == "":
        dir = "/dev"
    end
    for name in glib.list_dir(dir):
        if name.startswith("video"):
            return True
        end
    end
    return False
end

function label(text, css, chars):
    l = gtk.label_new(text)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_justify(l, gtk.JUSTIFY_CENTER)
    if chars > 0:
        call gtk.label_set_max_width_chars(l, chars)
    end
    call gtk.widget_add_class(l, css)
    return l
end

function icon_button(icon, tip, handler):
    b = gtk.button_new_empty()
    call gtk.widget_set_tooltip(b, tip)
    call gtk.container_add(b, gtk.image_new_from_icon_name(icon, gtk.ICON_MENU))
    call gtk.widget_add_class(b, "icon-btn")
    call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
    call gtk.connect_data(b, "clicked", 0, handler, 0)
    return b
end

function build_page(root):
    # Kopirovat a Obnovit (drive v horni liste okna) nad QR kodem vpravo
    tools = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_set_halign(tools, gtk.ALIGN_END)
    V["copy_btn"] = icon_button("edit-copy-symbolic", i18n.T("Copy QR code image"), on_copy)
    # jen s QR kodem; show_all okna by tlacitko ukazal i ve stavech bez kodu
    call gtk.widget_show_all(V["copy_btn"])
    call gtk.widget_hide(V["copy_btn"])
    call gtk.widget_set_no_show_all(V["copy_btn"], True)
    call gtk.box_pack_start(tools, V["copy_btn"], False, False, 0)
    call gtk.box_pack_start(tools, icon_button("view-refresh-symbolic", i18n.T("Refresh"), on_refresh), False, False, 0)
    call gtk.box_pack_start(root, tools, False, False, 0)
    V["stack"] = gtk.stack_new(True)
    call gtk.box_pack_start(root, V["stack"], False, False, 0)

    # QR kod site
    page = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_valign(page, gtk.ALIGN_CENTER)
    card = gtk.event_box_new()
    call gtk.widget_set_halign(card, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(card, "qr-card")
    V["area"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(V["area"], 260, 260)
    call gtk.connect_data(V["area"], "draw", 1, draw_qr, 0)
    call gtk.container_add(card, V["area"])
    call gtk.box_pack_start(page, card, False, False, 0)
    V["ssid"] = label("", "ssid", 0)
    call gtk.widget_set_name(V["ssid"], "ssid")
    call gtk.label_set_selectable(V["ssid"], True)
    call gtk.box_pack_start(page, V["ssid"], False, False, 6)
    V["hint"] = label(i18n.T("Scan the code with a phone camera to join this network."), "dim", 40)
    call gtk.widget_set_name(V["hint"], "hint")
    call gtk.box_pack_start(page, V["hint"], False, False, 0)
    V["pw_box"] = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_halign(V["pw_box"], gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(V["pw_box"], 0, 0, 6, 0)
    call gtk.box_pack_start(V["pw_box"], gtk.label_new(i18n.T("Password:")), False, False, 0)
    entry = gtk.entry_new()
    V["pw_entry"] = entry
    call gtk.editable_set_editable(entry, False)
    call gtk.entry_set_visibility(entry, False)
    call gtk.entry_set_width_chars(entry, 18)
    call gtk.widget_set_can_focus(entry, False)
    call set_password_icon(False)
    call gtk.connect_data(entry, "icon-press", 2, on_icon_press, 0)
    call gtk.box_pack_start(V["pw_box"], entry, False, False, 0)
    call gtk.box_pack_start(page, V["pw_box"], False, False, 0)
    call gtk.stack_add_named(V["stack"], page, "qr")

    # Stavova stranka (neni Wi-Fi, chybi heslo, podnikova sit, chyba)
    state = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_valign(state, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(state, 0, 0, 24, 24)
    V["state_icon"] = gtk.image_new()
    call gtk.image_set_pixel_size(V["state_icon"], 64)
    call gtk.widget_add_class(V["state_icon"], "dim")
    V["state_title"] = label("", "state-title", 0)
    call gtk.widget_set_name(V["state_title"], "state-title")
    V["state_hint"] = label("", "dim", 44)
    call gtk.widget_set_name(V["state_hint"], "state-hint")
    V["spinner"] = gtk.spinner_new()
    call gtk.widget_set_size_request(V["spinner"], 32, 32)
    call gtk.widget_set_no_show_all(V["spinner"], True)
    V["unlock_btn"] = gtk.button_new(i18n.T("Show Password…"))
    call gtk.widget_set_halign(V["unlock_btn"], gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(V["unlock_btn"], 0, 0, 6, 0)
    call gtk.widget_add_class(V["unlock_btn"], "suggested-action")
    call gtk.widget_set_no_show_all(V["unlock_btn"], True)
    call gtk.connect_data(V["unlock_btn"], "clicked", 0, on_unlock, 0)
    for key in ["state_icon", "spinner", "state_title", "state_hint", "unlock_btn"]:
        call gtk.box_pack_start(state, V[key], False, False, 0)
    end
    call gtk.stack_add_named(V["stack"], state, "state")
    # Gtk.Stack prepne jen na viditelnou stranku (i pred show_all okna)
    call gtk.widget_show_all(page)
    call gtk.widget_show_all(state)

    scan = gtk.button_new(i18n.T("Join a Network with a QR Code…"))
    call gtk.widget_set_halign(scan, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(scan, 0, 0, 18, 0)
    call gtk.widget_add_class(scan, "pill")
    call gtk.widget_set_tooltip(scan, i18n.T("Scan a Wi-Fi QR code with the camera and connect"))
    call gtk.connect_data(scan, "clicked", 0, on_scan, 0)
    call gtk.widget_set_no_show_all(scan, True)
    call gtk.widget_set_visible(scan, has_camera() and qr.available())
    call gtk.box_pack_start(root, scan, False, False, 0)
end

# ---- stav ------------------------------------------------------------------------------------------------------

function show_state(icon, title, hint, unlock, busy):
    call gtk.image_set_from_icon_name(V["state_icon"], icon, gtk.ICON_DIALOG)
    call gtk.widget_set_visible(V["state_icon"], not busy)
    call gtk.widget_set_visible(V["spinner"], busy)
    call gtk.spinner_set(V["spinner"], busy)
    call gtk.label_set_text(V["state_title"], title)
    call gtk.label_set_text(V["state_hint"], hint)
    call gtk.widget_set_visible(V["state_hint"], hint != "")
    call gtk.widget_set_visible(V["unlock_btn"], unlock)
    call gtk.widget_hide(V["copy_btn"])
    call gtk.stack_set_visible_child_name(V["stack"], "state")
end

# nmcli bez prekladu (hodnoty se ctou jako text); chyby (stderr) k vystupu, at je stranka muze ukazat
function run_nmcli(args, root, handler, data):
    argv = ["sh", "-c", "LC_ALL=C exec \"$@\" 2>&1", "nmcli"]
    if root:
        argv.append(env.get("LUXOS_PKEXEC", "pkexec"))
    end
    argv.append(nmcli())
    call glib.spawn_capture(argv + args, handler, data)
end

# Nacteni site: aktivni Wi-Fi, pak jeji udaje s heslem (root = pres pkexec)
function load(root):
    call show_state("network-wireless-symbolic", i18n.T("Reading the network settings…"), "", False, True)
    V["loading"] += 1
    call run_nmcli(["-t", "-f", "TYPE,UUID,DEVICE,NAME", "connection", "show", "--active"], False, on_active, [V["loading"], root])
end

function on_active(job, output, status):
    if job[0] != V["loading"]:
        return 0
    end
    act = None
    if status == 0:
        act = qr.active_wifi(output)
    end
    V["act"] = act
    if act == None:
        call loaded(job, None, "")
        return 0
    end
    call wifi_details(act["uuid"], True, job[1], on_details, job)
    return 0
end

function wifi_details(uuid, secrets, root, handler, job):
    args = ["--escape", "no", "-t", "-f", ",".join(qr.FIELDS), "connection", "show", "uuid", uuid]
    if secrets:
        args = ["--show-secrets"] + args
    end
    call run_nmcli(args, root, handler, job)
end

function on_details(job, output, status):
    if job[0] != V["loading"]:
        return 0
    end
    if status != 0:
        # stav procesu z waitpid: kod konce v horni polovine (pkexec: 126 zruseno, 127 neovereno)
        code = status >> 8
        if job[1] and (code == 126 or code == 127):
            call loaded(job, None, "cancelled")
        elif output.strip() != "":
            call loaded(job, None, output.strip())
        else:
            call loaded(job, None, "nmcli failed")
        end
        return 0
    end
    call loaded(job, qr.details(qr.parse_connection(output)), "")
    return 0
end

# Udaje bez hesla po zrusenem pkexec (jako drive, nez se uzivatel zeptal)
function on_plain_details(job, output, status):
    if job[0] != V["loading"]:
        return 0
    end
    if status != 0:
        call loaded([job[0], False], None, output.strip() if output.strip() != "" else "nmcli failed")
    else:
        call loaded([job[0], False], qr.details(qr.parse_connection(output)), "")
    end
    return 0
end

function loaded(job, info, error):
    act = V["act"]
    if not qr.available():
        call show_state("dialog-warning-symbolic", i18n.T("QR codes are not available"), i18n.T("The zxing-cpp library is missing. Install it with: lux install zxing-cpp"), False, False)
        return 0
    end
    if act == None:
        call show_state("network-wireless-offline-symbolic", i18n.T("Not connected to Wi-Fi"), i18n.T("Connect to a Wi-Fi network to share it with a QR code."), False, False)
        return 0
    end
    if error == "cancelled":
        error = ""
        info = None
        if V["info"] != None and V["info"]["uuid"] == act["uuid"]:
            info = V["info"]
        else:
            call wifi_details(act["uuid"], False, False, on_plain_details, job)
            return 0
        end
    end
    if error != "" or info == None:
        call show_state("dialog-warning-symbolic", i18n.T("The network settings could not be read"), error, False, False)
        return 0
    end
    info["uuid"] = act["uuid"]
    V["info"] = info
    name = info["ssid"]
    if name == "":
        name = act["name"]
    end
    if info["security"] == "":
        call show_state("network-wireless-encrypted-symbolic", name, i18n.T("This network uses a company or school login (802.1X). It cannot be shared with a QR code."), False, False)
        return 0
    end
    if info["need_auth"]:
        call show_state("changes-prevent-symbolic", name, i18n.T("The Wi-Fi password is stored for the whole computer. To show it in the QR code, confirm with the administrator password."), True, False)
        return 0
    end
    result = qr.encode(qr.wifi_payload(info["ssid"], info["password"], info["security"], info["hidden"]))
    if result[1] != "":
        call show_state("dialog-warning-symbolic", i18n.T("The QR code could not be created"), result[1], False, False)
        return 0
    end
    V["matrix"] = result[0]
    call gtk.label_set_text(V["ssid"], name)
    call gtk.entry_set_text(V["pw_entry"], info["password"])
    call gtk.widget_set_visible(V["pw_box"], info["password"] != "")
    if info["password"] != "":
        call gtk.label_set_text(V["hint"], i18n.T("Scan the code with a phone camera to join this network."))
    else:
        call gtk.label_set_text(V["hint"], i18n.T("Open network – no password needed."))
    end
    call gtk.widget_show(V["copy_btn"])
    call gtk.widget_queue_draw(V["area"])
    call gtk.stack_set_visible_child_name(V["stack"], "qr")
end

# ---- akce --------------------------------------------------------------------------------------------------------

function set_password_icon(shown):
    entry = V["pw_entry"]
    # GTK_ENTRY_ICON_SECONDARY
    call gtk.entry_set_icon_from_icon_name(entry, 1, "view-conceal-symbolic" if shown else "view-reveal-symbolic")
    call gtk.entry_set_icon_tooltip(entry, 1, i18n.T("Hide password") if shown else i18n.T("Show password"))
end

function on_icon_press(unused, position, event, entry):
    shown = not gtk.entry_get_visibility(entry)
    call gtk.entry_set_visibility(entry, shown)
    call set_password_icon(shown)
    return 0
end

function on_refresh(unused, b):
    call load(False)
    return 0
end

function on_unlock(unused, b):
    call load(True)
    return 0
end

# Skenovani dela Kamera ve vlastnim okne (stejna pipeline GStreamer, vyber kamery, chybove stavy)
function on_scan(unused, b):
    call glib.spawn_quiet(["luxos-camera", "--scan-wifi"])
    return 0
end

function render(cr, size):
    matrix = V["matrix"]
    n = len(matrix) + 2 * QUIET
    mod = Float(size) / n
    call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
    call cairo.rectangle(cr, 0.0, 0.0, Float(size), Float(size))
    call cairo.fill(cr)
    call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
    for y in range(len(matrix)):
        row = matrix[y]
        for x in range(len(row)):
            if row[x] == 1:
                call cairo.rectangle(cr, (x + QUIET) * mod, (y + QUIET) * mod, mod + 0.02, mod + 0.02)
            end
        end
    end
    call cairo.fill(cr)
end

function draw_qr(unused, cr, widget):
    if len(V["matrix"]) == 0:
        return False
    end
    w = gtk.widget_get_allocated_width(widget)
    h = gtk.widget_get_allocated_height(widget)
    n = len(V["matrix"]) + 2 * QUIET
    # cele pixely na modul = ostre hrany
    size = (min(w, h) // n) * n
    if size == 0:
        size = min(w, h)
    end
    call cairo.translate(cr, Float((w - size) // 2), Float((h - size) // 2))
    call render(cr, size)
    return False
end

function on_copy(unused, b):
    if len(V["matrix"]) == 0:
        return 0
    end
    size = (len(V["matrix"]) + 2 * QUIET) * 10
    # CAIRO_FORMAT_RGB24
    surface = cairo.image_surface_create(1, size, size)
    cr = cairo.create(surface)
    call render(cr, size)
    call cairo.destroy(cr)
    pix = gtk.surface_to_pixbuf(surface, size, size)
    call cairo.surface_destroy(surface)
    # GDK_SELECTION_CLIPBOARD
    call gtk.selection_set_image(69, pix)
    call gtk.object_unref(pix)
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1, prikazy, ktere okno Nastaveni nezna) -----------------------------------------

function test(command, rest):
    if command == "page-state":
        print "page-state " + json.encode({"page": gtk.stack_get_visible_child_name(V["stack"]),
            "password_shown": gtk.entry_get_visibility(V["pw_entry"]), "modules": len(V["matrix"]),
            "clipboard": gtk.selection_owned(69)})
    elif command == "reload":
        call load(False)
    elif command == "toggle":
        call on_icon_press(0, 1, 0, V["pw_entry"])
    else:
        return False
    end
    return True
end

# ---- stranka -------------------------------------------------------------------------------------------------------

function cli(args):
    if not ("--scan" in args):
        return None
    end
    call sys.exec(["luxos-camera", "--scan-wifi"])
    call eprint("luxos-wifi-qr: luxos-camera: " + String(sys.errno()))
    return 1
end

function build(host):
    V["window"] = host["window"]
    call gtk.css_load(CSS)
    page = ui.page_box()
    call gtk.widget_add_class(page, "wifi-page")
    call build_page(page)
    return page
end

# Pri kazdem zobrazeni nacte sit znovu (mezitim se mohla zmenit)
function show(host):
    call load(False)
    return 0
end

# Odpovedi nmcli, ktere dojdou po odchodu ze stranky, se zahodi
function leave(host):
    V["loading"] += 1
    return 0
end
