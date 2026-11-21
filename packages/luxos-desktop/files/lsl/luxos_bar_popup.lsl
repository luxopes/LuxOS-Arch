# LuxOS - vyskakovaci okna horni listy na Waylandu: nabidka systemu (logo), Wi-Fi, Zvuk a Oznameni (hodiny otevrou
# Kalendar hubu). Okna
# jsou prevzate z luxos_bar_popups.lsl (vetev gpt-features-1.1.1): nmcli a heslo NetworkManageru pres
# D-Bus, pactl; historie oznameni od luxos-notify (org.xfce.Notifyd.Log, cz.luxos.NotificationHistory: Activate,
# Get/SetDoNotDisturb). Dokud je nektere okno otevrene, luxos-notify neukazuje bubliny (SetPopupsHidden).
#
# Okna jsou plochy layer-shell na vrstve OVERLAY (ne xdg_popup): kotva nahore vlevo pod ikonou, kompozitor je
# umisti pod vyhradnou zonu listy. xdg_popup by kompozitor zavrel s kazdym klikem mimo a drzel by vstup
# (grab) - heslo Wi-Fi a posuvnik hlasitosti by se psaly do okna, ktere kazdy klik zavre; layer surface
# s klavesnici "on demand" dostane klavesy po kliknuti a nic nezavre samo. Okno se vytvori pri prvnim otevreni
# a pri zavreni se jen skryje (dalsi otevreni bez stavby widgetu). Zavira se klavesou Esc, dalsim klikem na
# ikonu v liste, otevrenim jineho okna nebo ztratou fokusu.
#
#   popup.init(tmavy, trace)            trace(text) = ladici vypis listy
#   popup.toggle(druh, monitor, vystup, out_w, out_h, meritko, stred_x, tlacitko, cas_udalosti)
#                                       druh "system" | "wifi" | "sound" | "notifications"; stred_x = stred ikony v liste
#
# Nabidka systemu (logo vlevo) zustava nabidkou systemu, ne aplikaci (aplikace jsou v Launchpadu): vzhled jako nabidka
# Whisker Menu verze 1.1.1 - nahore fotka a jmeno, uprostred O tomto pocitaci, Nastaveni a Launchpad, dole kulata
# tlacitka s popisky Zamknout, Odhlasit, Restartovat a Vypnout.
#   popup.close(druh), popup.close_all(), popup.set_dark(tmavy)
load cairo, json, net
load glib, gtk, gio
load luxos_glib as lglib
load luxos_gio, gio as lgio
load luxos_gtk
load luxos_text as text
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_tokens as tokens
load luxos_avatar as avatar
load luxos_hub_popup as hub_popup

KINDS = ["system", "wifi", "sound", "notifications"]
WIDTH = 320
SYSTEM_WIDTH = 272
# [text, ikona, prikaz]; lista bezi jako uzivatelska sluzba mimo relaci logindu: relaci urcuje XDG_SESSION_ID
# z luxos-wayland-session
SYSTEM_ITEMS = [["About This Computer", "help-about-symbolic", ["luxos-about"]],
    ["Settings", "preferences-system-symbolic", ["luxos-settings"]],
    ["Launchpad", "view-app-grid-symbolic", ["luxos-launchpad"]]]
SYSTEM_POWER = [["Lock Screen", "system-lock-screen-symbolic", ["sh", "-c", "exec loginctl lock-session \"${XDG_SESSION_ID:-auto}\""]],
    ["Sign Out", "system-log-out-symbolic", ["sh", "-c", "exec loginctl terminate-session \"${XDG_SESSION_ID:-auto}\""]],
    ["Restart", "system-reboot-symbolic", ["systemctl", "reboot"]],
    ["Shut Down", "system-shutdown-symbolic", ["systemctl", "poweroff"]]]
SYSTEM_CSS = (".lx-avatar { border-radius: 999px; min-width: 36px; min-height: 36px; font-weight: 800; color: white;"
    + " background-image: linear-gradient(135deg, #3d7bff, #8b4dff); }\n"
    + ".lx-system button.lx-row:focus { background-color: @lx_tile_hover; }\n"
    + "button.lx-power { background: none; background-image: none; border: none; box-shadow: none; outline: none; padding: 2px 0; border-radius: 8px; }\n"
    + "button.lx-power .lx-bubble { min-width: 34px; min-height: 34px; }\n"
    + "button.lx-power:hover .lx-bubble, button.lx-power:focus .lx-bubble { background-color: @lx_tile_hover; }\n"
    + "button.lx-power label { font-size: 11px; color: @lx_fg_secondary; }\n")
GAP = 6
EDGE = 8
NM = "org.freedesktop.NetworkManager"
NOTIFYD = "org.xfce.Notifyd"
LOG_PATH = "/org/xfce/Notifyd"
LOG = "org.xfce.Notifyd.Log"
HISTORY_PATH = "/cz/luxos/NotificationHistory"
HISTORY = "cz.luxos.NotificationHistory"

P = {"wins": {}, "boxes": {}, "dark": False, "trace": None, "open": "", "place": {}, "click": {}, "lost": {}, "w": {},
     "wifi": {"enabled": True, "nets": [], "pending": "", "ask": "", "error": "", "iface": "", "scan": 0, "loaded": False},
     "sound": {"sinks": [], "sources": [], "sink": "", "source": "", "lock": False},
     "notes": {"items": [], "dnd": False, "lock": False}, "session": -1, "face": None, "face_css": 0}

function trace(message):
    if P["trace"] != None:
        call P["trace"](message)
    end
    return 0
end

function log(message):
    return eprint("luxos-bar: " + message)
end

function init(dark, trace_fn):
    P["dark"] = dark
    P["trace"] = trace_fn
    return 0
end

function set_dark(dark):
    P["dark"] = dark
    for kind in P["wins"].keys():
        call gtk.widget_queue_draw(P["wins"][kind])
    end
    return 0
end

function label(value, classes, xalign):
    lab = gtk.label_new(value)
    call gtk.label_set_xalign(lab, xalign)
    for c in classes:
        call gtk.widget_add_class(lab, c)
    end
    return lab
end

function clear(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
    return 0
end

function icon_button(icon, tooltip, handler, bound):
    b = gtk.button_new_from_icon_name(icon, luxos_gtk.ICON_MENU)
    call gtk.widget_add_class(b, "lx-icon")
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
    if tooltip != "":
        call gtk.widget_set_tooltip(b, tooltip)
    end
    call lglib.connect_data(b, "clicked", 0, handler, bound)
    return b
end

function footer(box, title, command):
    b = gtk.button_new(title)
    call gtk.widget_add_class(b, "lx-row")
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_set_halign(b, gtk.ALIGN_START)
    call lglib.connect_data(b, "clicked", 0, on_launch, command)
    call gtk.box_pack_start(box, b, False, False, 0)
    return b
end

function on_launch(command, button):
    call glib.spawn_quiet(command)
    call close_all()
    return 0
end

function header(box, title, switch_handler):
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(row, label(title, ["lx-head"], 0.0), True, True, 4)
    sw = 0
    if switch_handler != None:
        sw = gtk.switch_new()
        call gtk.widget_set_can_focus(sw, False)
        call gtk.widget_set_valign(sw, gtk.ALIGN_CENTER)
        call gtk.connect(sw, "state-set", switch_handler)
        call gtk.box_pack_end(row, sw, False, False, 0)
    end
    call gtk.box_pack_start(box, row, False, False, 0)
    return sw
end

# ---- okna -----------------------------------------------------------------------------------------

function window_for(kind):
    win = P["wins"].get(kind, 0)
    if win != 0:
        return win
    end
    win = gtk.window_new("luxos-bar-" + kind)
    call layer.init_for_window(win)
    call layer.set_namespace(win, tokens.namespace("luxos-bar-popup", "popup"))
    call layer.set_layer(win, layer.LAYER_OVERLAY)
    call layer.set_anchors(win, [layer.EDGE_TOP, layer.EDGE_LEFT])
    call layer.set_margin(win, layer.EDGE_TOP, GAP)
    call layer.set_keyboard_mode(win, layer.KEYBOARD_ON_DEMAND)
    call luxos_gtk.window_set_rgba(win)
    call gtk.widget_add_class(win, "lx")
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "lx-popup")
    call gtk.widget_add_class(box, "lx-glass")
    call gtk.widget_set_size_request(box, width_of(kind), -1)
    call gtk.container_add(win, box)
    call lglib.connect_data(win, "draw", 1, on_draw, kind)
    call lglib.connect_data(win, "key-press-event", 1, on_key, kind)
    call lglib.connect_data(win, "focus-in-event", 1, on_focus_in, kind)
    call lglib.connect_data(win, "focus-out-event", 1, on_focus_out, kind)
    call lglib.connect_data(win, "realize", 0, on_realize, kind)
    P["wins"][kind] = win
    P["boxes"][kind] = box
    if kind == "system":
        call system_build(box)
    elif kind == "wifi":
        call wifi_build(box)
    elif kind == "sound":
        call sound_build(box)
    else:
        call notes_build(box)
    end
    return win
end

function width_of(kind):
    if kind == "system":
        return SYSTEM_WIDTH
    end
    return WIDTH
end

function is_visible(kind):
    win = P["wins"].get(kind, 0)
    return win != 0 and gtk.widget_get_visible(win)
end

# Prvni snimek po otevreni (po commitu plochy: GDK commituje v after-paint pred nasi obsluhou)
function on_realize(kind, widget):
    unsafe:
        clock = __lsl_qbe_call1(__lsl_symbol("gdk_window_get_frame_clock"), __lsl_unbox_int(gtk.widget_get_window(widget)))
    end
    call lglib.connect_data(clock, "after-paint", 0, on_after_paint, kind)
    return 0
end

function on_after_paint(kind, clock):
    click = P["click"].get(kind)
    if click == None:
        return 0
    end
    call P["click"].pop(kind)
    now = glib.monotonic_time() // 1000
    # cas udalosti od kompozitoru je CLOCK_MONOTONIC v ms (wlroots); jiny zdroj = jen od zpracovani v liste
    since_event = -1
    if click[0] > 0 and now - click[0] >= 0 and now - click[0] < 60000:
        since_event = now - click[0]
    end
    call trace("popup " + kind + " shown event_ms=" + String(since_event) + " handler_ms=" + String(now - click[1]))
    return 0
end

function toggle(kind, monitor, output, out_w, out_h, scale, center_x, button, event_time):
    if kind not in KINDS:
        return 0
    end
    if is_visible(kind):
        call close(kind)
        return 0
    end
    # klik na ikonu otevreneho okna mu nejdriv vezme fokus (zavre ho): tentyz klik ho nesmi znovu otevrit.
    # Cas udalosti je CLOCK_MONOTONIC v ms jako nase hodiny: fokus se ztratil az po stisku = tentyz klik.
    now = glib.monotonic_time() // 1000
    lost = P["lost"].get(kind, -100000)
    pressed = event_time & 0xffffffff
    if now - lost < 500 and (lost + 2 >= pressed or abs(now - pressed) > 10000):
        return 0
    end
    call close_all()
    P["click"][kind] = [event_time & 0xffffffff, glib.monotonic_time() // 1000]
    win = window_for(kind)
    width = width_of(kind)
    x = max(EDGE, min(center_x - width // 2, out_w - width - EDGE))
    P["place"][kind] = [output, out_w, out_h, scale, x]
    call layer.set_monitor(win, monitor)
    call layer.set_margin(win, layer.EDGE_LEFT, x)
    if kind == "system":
        call face_update()
    elif kind == "wifi":
        P["wifi"]["loaded"] = False
        call wifi_refresh(True)
    elif kind == "sound":
        call sound_refresh()
    else:
        call notes_refresh()
    end
    call hide_bubbles(True)
    P["open"] = kind
    P["focused"] = False
    P["button"] = button
    call luxos_gtk.widget_set_class(button, "open", True)
    call gtk.widget_show_all(win)
    # nabidka systemu: radky jdou projit klavesnici, ale zadny neni vybrany hned po otevreni
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_focus"), __lsl_unbox_int(win), 0)
    end
    return 0
end

function close(kind):
    win = P["wins"].get(kind, 0)
    if win == 0 or not gtk.widget_get_visible(win):
        return 0
    end
    call gtk.widget_hide(win)
    if P.get("button", 0) != 0:
        call luxos_gtk.widget_set_class(P["button"], "open", False)
        P["button"] = 0
    end
    if kind == "wifi":
        P["wifi"]["ask"] = ""
        P["wifi"]["error"] = ""
    end
    if kind == "notifications":
        call notes_mark_all_read()
    end
    call hide_bubbles(False)
    P["open"] = ""
    call trace("popup " + kind + " hidden")
    return 0
end

function close_all():
    for kind in KINDS:
        call close(kind)
    end
    return 0
end

function on_key(kind, event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        call close(kind)
        return True
    end
    return False
end

function on_focus_in(kind, event, window):
    P["focused"] = True
    return False
end

# Klik mimo okno (do aplikace, na plochu) vezme oknu fokus: zavrit, ale jen kdyz ho okno melo
function on_focus_out(kind, event, window):
    if P["focused"] and is_visible(kind):
        P["lost"][kind] = glib.monotonic_time() // 1000
        call close(kind)
    end
    return False
end

# Podklad karty je sklo z tapety jako verze 1.1.1 (hub_popup.paint_glass, kresli ho lista, pruhledne i bez
# rozmazani v kompozitoru); bez tapety material z CSS .lx-popup. Okno samo je pruhledne (rohy).
function on_draw(kind, cr, window):
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.restore(cr)
    place = P["place"].get(kind)
    if place != None:
        call hub_popup.paint_glass(cr, P["boxes"][kind], place[0], place[1], place[2], place[4], tokens.BAR["height"] + GAP)
    end
    return False
end

# ---- nabidka systemu ------------------------------------------------------------------------------

function system_build(box):
    call gtk.widget_add_class(box, "lx-system")
    P["face_css"] = gtk.css_load(SYSTEM_CSS)
    head = gtk.box_new(gtk.HORIZONTAL, 10)
    name = avatar.real_name()
    face = label(avatar.initials(name), ["lx-avatar"], 0.5)
    call gtk.widget_set_valign(face, gtk.ALIGN_CENTER)
    P["w"]["face"] = face
    call gtk.box_pack_start(head, face, False, False, 0)
    who = label(name, ["lx-title"], 0.0)
    call gtk.label_set_ellipsize(who, gtk.ELLIPSIZE_END)
    call gtk.box_pack_start(head, who, True, True, 0)
    call gtk.box_pack_start(box, head, False, False, 2)
    items = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(items, "lx-section")
    for entry in SYSTEM_ITEMS:
        b = gtk.button_new_empty()
        call gtk.widget_add_class(b, "lx-row")
        row = gtk.box_new(gtk.HORIZONTAL, 10)
        image = gtk.image_new_from_icon_name(entry[1], luxos_gtk.ICON_MENU)
        call gtk.box_pack_start(row, image, False, False, 0)
        call gtk.box_pack_start(row, label(i18n.T(entry[0]), [], 0.0), True, True, 0)
        call gtk.container_add(b, row)
        call lglib.connect_data(b, "clicked", 0, on_launch, entry[2])
        call gtk.box_pack_start(items, b, False, False, 0)
    end
    call gtk.box_pack_start(box, items, False, False, 0)
    power = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.box_set_homogeneous(power, True)
    for entry in SYSTEM_POWER:
        b = gtk.button_new_empty()
        call gtk.widget_add_class(b, "lx-power")
        col = gtk.box_new(gtk.VERTICAL, 4)
        bubble = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(bubble, "lx-bubble")
        call gtk.widget_set_halign(bubble, gtk.ALIGN_CENTER)
        image = gtk.image_new_from_icon_name(entry[1], luxos_gtk.ICON_MENU)
        call gtk.widget_set_hexpand(image, True)
        call gtk.box_pack_start(bubble, image, True, True, 0)
        call gtk.box_pack_start(col, bubble, False, False, 0)
        caption = label(i18n.T(entry[0]), [], 0.5)
        call gtk.label_set_justify(caption, gtk.JUSTIFY_CENTER)
        call gtk.label_set_line_wrap(caption, True)
        call gtk.label_set_max_width_chars(caption, 9)
        call gtk.box_pack_start(col, caption, False, False, 0)
        call gtk.container_add(b, col)
        call gtk.widget_set_tooltip(b, i18n.T(entry[0]))
        call lglib.connect_data(b, "clicked", 0, on_launch, entry[2])
        call gtk.box_pack_start(power, b, True, True, 0)
    end
    call gtk.box_pack_start(box, power, False, False, 2)
    return 0
end

# Profilova fotka (~/.face z luxos-profile-picture) misto pismena; styl se meni jen po zmene souboru
function face_update():
    path = avatar.face_path()
    st = lglib.stat(path)
    key = ""
    if len(st) > 0 and st[0] > 0:
        key = path + ":" + String(st[1])
    end
    if key == P["face"]:
        return 0
    end
    P["face"] = key
    css = SYSTEM_CSS
    if key != "":
        uri = "file://" + path.replace("%", "%25").replace(" ", "%20").replace("\"", "%22")
        css = css + ".lx-avatar.photo { background-image: url(\"" + uri + "\"); background-size: cover; background-position: center; color: transparent; }\n"
    end
    call luxos_gtk.css_set(P["face_css"], css)
    call luxos_gtk.widget_set_class(P["w"]["face"], "photo", key != "")
    return 0
end

# ---- Wi-Fi ----------------------------------------------------------------------------------------

# Rozdeli radek "nmcli -t" na pole (dvojtecka oddeluje, "\:" a "\\" jsou znaky v hodnote)
function nm_fields(line):
    out = []
    cur = ""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            cur = cur + line[i + 1]
            i += 2
            continue
        end
        if ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur = cur + ch
        end
        i += 1
    end
    out.append(cur)
    return out
end

function wifi_build(box):
    W = P["w"]
    W["wifi_switch"] = header(box, i18n.T("Wi-Fi"), on_wifi_switch)
    W["wifi_caption"] = label(i18n.T("Networks"), ["lx-caption"], 0.0)
    call gtk.box_pack_start(box, W["wifi_caption"], False, False, 0)
    W["wifi_list"] = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_add_class(W["wifi_list"], "lx-section")
    call gtk.box_pack_start(box, W["wifi_list"], False, False, 0)
    # sit s prihlasovaci strankou: prihlaseni (luxos-network-login, jako upozorneni z luxos-hub)
    W["wifi_portal"] = gtk.button_new(i18n.T("Sign in to the network"))
    call gtk.widget_add_class(W["wifi_portal"], "lx-accent")
    call gtk.widget_set_can_focus(W["wifi_portal"], False)
    call gtk.widget_set_halign(W["wifi_portal"], gtk.ALIGN_START)
    call luxos_gtk.widget_set_no_show_all(W["wifi_portal"], True)
    call lglib.connect_data(W["wifi_portal"], "clicked", 0, on_launch, ["luxos-network-login"])
    call gtk.box_pack_start(box, W["wifi_portal"], False, False, 0)
    foot = gtk.box_new(gtk.HORIZONTAL, 0)
    call footer(foot, i18n.T("Network Settings…"), ["nm-connection-editor"])
    W["wifi_rescan"] = icon_button("view-refresh-symbolic", i18n.T("Refresh"), on_wifi_rescan, 0)
    call gtk.box_pack_end(foot, W["wifi_rescan"], False, False, 0)
    call gtk.box_pack_start(box, foot, False, False, 0)
    return 0
end

# Okno ze skla pri zmene obsahu (seznam siti, oznameni) na novou velikost, i mensi
function fit(kind):
    if is_visible(kind):
        call gtk.window_resize(P["wins"][kind], width_of(kind), 1)
    end
    return 0
end

function on_wifi_rescan(unused, button):
    call gtk.widget_set_sensitive(button, False)
    P["wifi"]["scan"] = lglib.now()
    call lglib.spawn_watched_data(["nmcli", "device", "wifi", "rescan"], on_wifi_rescanned, 0)
    return 0
end

# Seznam hned z mezipameti NetworkManageru (--rescan no), nove hledani bezi zvlast a seznam pak obnovi
function wifi_refresh(scan):
    call lglib.spawn_capture(["nmcli", "-t", "-f", "WIFI", "general"], on_wifi_radio, 0)
    call lglib.spawn_capture(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], on_wifi_iface, 0)
    call lglib.spawn_capture(["nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_wifi_connectivity, 0)
    call lglib.spawn_capture(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], on_wifi_list, 0)
    if scan and lglib.now() - P["wifi"]["scan"] > 10:
        P["wifi"]["scan"] = lglib.now()
        call lglib.spawn_watched_data(["nmcli", "device", "wifi", "rescan"], on_wifi_rescanned, 0)
    end
    call wifi_render()
    return 0
end

function on_wifi_rescanned(bound, pid, status):
    rescan = P["w"].get("wifi_rescan", 0)
    if rescan != 0:
        call gtk.widget_set_sensitive(rescan, True)
    end
    if is_visible("wifi"):
        call lglib.spawn_capture(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], on_wifi_list, 0)
    end
    return 0
end

function on_wifi_connectivity(unused, output, status):
    P["wifi"]["portal"] = output.strip() == "portal"
    call wifi_render()
    return 0
end

function on_wifi_radio(unused, output, status):
    P["wifi"]["enabled"] = output.strip() == "enabled"
    sw = P["w"].get("wifi_switch", 0)
    if sw != 0:
        P["wifi"]["lock"] = True
        call gtk.switch_set_active(sw, P["wifi"]["enabled"])
        P["wifi"]["lock"] = False
    end
    call wifi_render()
    return 0
end

function on_wifi_iface(unused, output, status):
    for line in output.split("\n"):
        f = nm_fields(line)
        if len(f) >= 2 and f[1] == "wifi":
            P["wifi"]["iface"] = f[0]
            return 0
        end
    end
    return 0
end

# Site: jedna polozka na SSID (nejsilnejsi), pripojena nahore, ostatni podle signalu
function on_wifi_list(unused, output, status):
    P["wifi"]["loaded"] = True
    best = {}
    for line in output.split("\n"):
        f = nm_fields(line)
        if len(f) < 4 or f[1] == "":
            continue
        end
        sig = 0
        if text.is_digits(f[2]):
            sig = Int(f[2])
        end
        item = {"ssid": f[1], "signal": sig, "secure": f[3].strip() != "" and f[3].strip() != "--",
                "security": f[3], "active": f[0].strip() == "*"}
        old = best.get(f[1])
        if old == None or item["active"] or (not old["active"] and sig > old["signal"]):
            best[f[1]] = item
        end
    end
    keys = []
    nets = []
    for v in best.values():
        nets.append(v)
    end
    for i in range(len(nets)):
        rank = nets[i]["signal"]
        if nets[i]["active"]:
            rank = 1000
        end
        keys.append((1000 - rank) * 1000 + i)
    end
    ordered = []
    for k in sorted(keys):
        ordered.append(nets[k % 1000])
    end
    P["wifi"]["nets"] = ordered
    call wifi_render()
    return 0
end

function signal_icon(sig):
    if sig >= 75:
        return "network-wireless-signal-excellent-symbolic"
    elif sig >= 50:
        return "network-wireless-signal-good-symbolic"
    elif sig >= 25:
        return "network-wireless-signal-ok-symbolic"
    end
    return "network-wireless-signal-weak-symbolic"
end

function wifi_render():
    W = P["w"]
    box = W.get("wifi_list", 0)
    if box == 0:
        return 0
    end
    call clear(box)
    call gtk.widget_set_visible(W["wifi_caption"], P["wifi"]["enabled"])
    if not P["wifi"]["enabled"]:
        call gtk.box_pack_start(box, label(i18n.T("Wi-Fi is off"), ["lx-dim"], 0.0), False, False, 6)
        call gtk.widget_show_all(box)
        return 0
    end
    count = 0
    for net in P["wifi"]["nets"]:
        if count >= 10:
            break
        end
        count += 1
        b = gtk.button_new_empty()
        call gtk.widget_add_class(b, "lx-row")
        call gtk.widget_set_can_focus(b, False)
        if net["active"]:
            call gtk.widget_add_class(b, "on")
        end
        row = gtk.box_new(gtk.HORIZONTAL, 10)
        bubble = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(bubble, "lx-bubble")
        img = gtk.image_new_from_icon_name(signal_icon(net["signal"]), luxos_gtk.ICON_MENU)
        call gtk.widget_set_hexpand(img, True)
        call gtk.box_pack_start(bubble, img, True, True, 0)
        # hexpand obrazku by se preneslo na bublinu a ta by se roztahla s nazvem site
        call gtk.widget_set_hexpand(bubble, False)
        call gtk.box_pack_start(row, bubble, False, False, 0)
        name = label(net["ssid"], [], 0.0)
        call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
        call gtk.label_set_max_width_chars(name, 24)
        call gtk.box_pack_start(row, name, True, True, 0)
        if net["ssid"] == P["wifi"]["pending"]:
            call gtk.box_pack_end(row, label(i18n.T("Connecting…"), ["lx-dim"], 1.0), False, False, 0)
        elif net["active"]:
            call gtk.box_pack_end(row, gtk.image_new_from_icon_name("object-select-symbolic", luxos_gtk.ICON_MENU), False, False, 0)
        elif net["secure"]:
            call gtk.box_pack_end(row, gtk.image_new_from_icon_name("changes-prevent-symbolic", luxos_gtk.ICON_MENU), False, False, 0)
        end
        call gtk.widget_set_halign(row, gtk.ALIGN_FILL)
        call gtk.widget_set_hexpand(row, True)
        call gtk.container_add(b, row)
        call lglib.connect_data(b, "clicked", 0, on_wifi_row, net)
        call gtk.box_pack_start(box, b, False, False, 0)
        if P["wifi"]["ask"] == net["ssid"]:
            call gtk.box_pack_start(box, wifi_password_row(net), False, False, 0)
        end
    end
    if count == 0:
        empty = i18n.T("No networks found")
        if not P["wifi"]["loaded"] or P["wifi"]["scan"] > lglib.now() - 10:
            empty = i18n.T("Searching…")
        end
        call gtk.box_pack_start(box, label(empty, ["lx-dim"], 0.0), False, False, 6)
    end
    call gtk.widget_set_visible(W["wifi_portal"], P["wifi"].get("portal", False))
    call gtk.widget_show_all(box)
    if W.get("wifi_entry", 0) != 0 and P["wifi"]["ask"] != "":
        call gtk.widget_grab_focus(W["wifi_entry"])
    end
    call fit("wifi")
    return 0
end

function wifi_password_row(net):
    W = P["w"]
    col = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_set_margins(col, 8, 8, 2, 6)
    entry = gtk.entry_new()
    call gtk.entry_set_visibility(entry, False)
    call gtk.entry_set_placeholder_text(entry, i18n.T("Password"))
    call gtk.entry_set_icon_from_icon_name(entry, gtk.ENTRY_ICON_SECONDARY, "view-reveal-symbolic")
    call lglib.connect_data(entry, "icon-press", 2, on_reveal, {"shown": False})
    call lglib.connect_data(entry, "activate", 0, on_wifi_join, net)
    W["wifi_entry"] = entry
    call gtk.box_pack_start(col, entry, False, False, 0)
    if P["wifi"]["error"] != "":
        call gtk.box_pack_start(col, label(P["wifi"]["error"], ["lx-error"], 0.0), False, False, 0)
    end
    buttons = gtk.box_new(gtk.HORIZONTAL, 6)
    join = gtk.button_new(i18n.T("Join"))
    call gtk.widget_add_class(join, "lx-accent")
    call gtk.widget_set_can_focus(join, False)
    call lglib.connect_data(join, "clicked", 0, on_wifi_join, net)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.widget_add_class(cancel, "lx-button")
    call gtk.widget_set_can_focus(cancel, False)
    call gtk.connect(cancel, "clicked", on_wifi_cancel)
    call gtk.box_pack_end(buttons, join, False, False, 0)
    call gtk.box_pack_end(buttons, cancel, False, False, 0)
    call gtk.box_pack_start(col, buttons, False, False, 0)
    return col
end

function on_reveal(state, position, event, entry):
    state["shown"] = not state["shown"]
    call gtk.entry_set_visibility(entry, state["shown"])
    return 0
end

function on_wifi_cancel(button):
    P["wifi"]["ask"] = ""
    P["wifi"]["error"] = ""
    call wifi_render()
    return 0
end

function on_wifi_switch(state, switch):
    if P["wifi"].get("lock", False):
        return False
    end
    value = "off"
    if state != 0:
        value = "on"
    end
    P["wifi"]["enabled"] = state != 0
    call wifi_render()
    call lglib.spawn_watched_data(["nmcli", "radio", "wifi", value], on_wifi_changed, 0)
    return False
end

function on_wifi_changed(bound, pid, status):
    if is_visible("wifi"):
        call wifi_refresh(False)
    end
    return 0
end

# Klik na sit: pripojena nic, znama nebo otevrena hned (NetworkManager pouzije ulozeny profil),
# zabezpecena bez profilu = pole pro heslo
function on_wifi_row(net, button):
    if net["active"] or P["wifi"]["pending"] != "":
        return 0
    end
    P["wifi"]["error"] = ""
    if net["secure"]:
        call lglib.spawn_capture(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], on_known_profiles, net)
        return 0
    end
    call wifi_connect_known(net)
    return 0
end

function on_known_profiles(net, output, status):
    # profil se jmenuje jako sit (vychozi nmcli/nm-applet); ostatni zkusi NetworkManager podle SSID
    for line in output.split("\n"):
        f = nm_fields(line)
        if len(f) >= 2 and f[0] == net["ssid"] and f[1].find("wireless") >= 0:
            call wifi_connect_known(net)
            return 0
        end
    end
    if net["security"].find("802.1X") >= 0:
        # podnikova sit: prihlaseni pres pruvodce NetworkManageru (uzivatel, certifikat)
        call glib.spawn_quiet(["nm-connection-editor", "--create", "--type=802-11-wireless"])
        call close_all()
        return 0
    end
    P["wifi"]["ask"] = net["ssid"]
    call wifi_render()
    return 0
end

function wifi_connect_known(net):
    P["wifi"]["pending"] = net["ssid"]
    call wifi_render()
    call lglib.spawn_capture(["nmcli", "--wait", "30", "device", "wifi", "connect", net["ssid"]], on_wifi_connected, net)
    return 0
end

function on_wifi_connected(net, output, status):
    P["wifi"]["pending"] = ""
    if status != 0:
        if net["secure"] and output.lower().find("secret") >= 0:
            P["wifi"]["ask"] = net["ssid"]
        else:
            P["wifi"]["error"] = i18n.T("Could not connect")
        end
    else:
        P["wifi"]["ask"] = ""
    end
    call wifi_refresh(False)
    return 0
end

# Nova zabezpecena sit: profil s heslem primo NetworkManageru po D-Bus (heslo neni v argumentech procesu)
function on_wifi_join(net, widget):
    entry = P["w"].get("wifi_entry", 0)
    if entry == 0:
        return 0
    end
    password = gtk.entry_get_text(entry)
    if len(password) < 8 and net["security"].find("WEP") < 0:
        P["wifi"]["error"] = i18n.T("Wrong password")
        call wifi_render()
        return 0
    end
    result = wifi_add_and_activate(net, password)
    call gtk.entry_set_text(entry, "")
    if result != "":
        P["wifi"]["error"] = i18n.T("Could not connect")
        call log("wifi: " + result)
        call wifi_render()
        return 0
    end
    P["wifi"]["ask"] = ""
    P["wifi"]["pending"] = net["ssid"]
    call wifi_render()
    # stav pripojeni: znovu nacist po chvili (aktivace bezi v NetworkManageru)
    call lglib.timeout_add_seconds_data(4, wifi_after_join, net)
    return 0
end

function wifi_after_join(net):
    P["wifi"]["pending"] = ""
    if is_visible("wifi"):
        call wifi_refresh(False)
    end
    return False
end

# Nastaveni profilu pro NetworkManager (a{sa{sv}}): SSID v bajtech UTF-8, WPA3 = sae, jinak wpa-psk
function wifi_settings(target, password):
    raw = net.bytes(target["ssid"])
    ssid = []
    for i in range(len(raw)):
        ssid.append(raw[i])
    end
    mgmt = "wpa-psk"
    if target["security"].find("WPA3") >= 0 and target["security"].find("WPA2") < 0:
        mgmt = "sae"
    end
    security = {"key-mgmt": ["s", mgmt], "psk": ["s", password]}
    if target["security"].find("WEP") >= 0:
        security = {"key-mgmt": ["s", "none"], "wep-key0": ["s", password], "wep-key-type": ["u", 1]}
    end
    return {"connection": {"id": ["s", target["ssid"]], "type": ["s", "802-11-wireless"]},
            "802-11-wireless": {"ssid": ["ay", ssid], "mode": ["s", "infrastructure"]},
            "802-11-wireless-security": security}
end

# "" pri uspechu, jinak text chyby
function wifi_add_and_activate(net, password):
    bus = 0
    safe:
        bus = gio.system_bus()
    end
    if bus == 0 or bus == None:
        return "no system bus"
    end
    iface = P["wifi"]["iface"]
    if iface == "":
        return "no wifi device"
    end
    error = ""
    try:
        dev = gio.call_values(bus, NM, "/org/freedesktop/NetworkManager", NM, "GetDeviceByIpIface", [iface], "(s)", 5000)
        call gio.call_values(bus, NM, "/org/freedesktop/NetworkManager", NM, "AddAndActivateConnection",
                             [wifi_settings(net, password), dev[0], "/"], "(a{sa{sv}}oo)", 10000)
    else:
        error = String(last_error())
    end
    return error
end

# ---- Zvuk -------------------------------------------------------------------------------------------

function sound_build(box):
    W = P["w"]
    call header(box, i18n.T("Sound"), None)
    W["out_slider"] = slider(box, i18n.T("Output"), "sink")
    W["out_list"] = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.box_pack_start(box, W["out_list"], False, False, 0)
    W["in_slider"] = slider(box, i18n.T("Input"), "source")
    W["in_list"] = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.box_pack_start(box, W["in_list"], False, False, 0)
    foot = gtk.box_new(gtk.VERTICAL, 0)
    call footer(foot, i18n.T("Sound Settings…"), ["pavucontrol"])
    call gtk.box_pack_start(box, foot, False, False, 0)
    return 0
end

function slider(box, title, what):
    row = {"what": what, "muted": False}
    sec = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_add_class(sec, "lx-section")
    call gtk.box_pack_start(sec, label(title, ["lx-caption"], 0.0), False, False, 0)
    line = gtk.box_new(gtk.HORIZONTAL, 8)
    icon = "audio-volume-high-symbolic"
    if what == "source":
        icon = "audio-input-microphone-symbolic"
    end
    mute = icon_button(icon, "", on_mute_clicked, row)
    scale = gtk.scale_new_with_range(gtk.HORIZONTAL, 0, 100, 1)
    call gtk.scale_set_draw_value(scale, False)
    call gtk.widget_set_hexpand(scale, True)
    call gtk.widget_set_can_focus(scale, False)
    call lglib.connect_data(scale, "value-changed", 0, on_volume_changed, row)
    call gtk.box_pack_start(line, mute, False, False, 0)
    call gtk.box_pack_start(line, scale, True, True, 0)
    call gtk.box_pack_start(sec, line, False, False, 0)
    call gtk.box_pack_start(box, sec, False, False, 0)
    row["scale"] = scale
    row["button"] = mute
    row["section"] = sec
    return row
end

function sound_refresh():
    call lglib.spawn_capture(["pactl", "-f", "json", "list", "sinks"], on_pactl_list, "sinks")
    call lglib.spawn_capture(["pactl", "-f", "json", "list", "sources"], on_pactl_list, "sources")
    call lglib.spawn_capture(["pactl", "get-default-sink"], on_pactl_default, "sink")
    call lglib.spawn_capture(["pactl", "get-default-source"], on_pactl_default, "source")
    call sound_render()
    return 0
end

function on_pactl_default(what, output, status):
    P["sound"][what] = output.strip()
    call sound_render()
    return 0
end

# Prumer kanalu "45%" -> 45
function volume_percent(volume):
    total = 0
    count = 0
    if type(volume) != "Dictionary":
        return 0
    end
    for ch in volume.values():
        v = String(ch.get("value_percent", "0%")).replace("%", "").strip()
        if text.is_digits(v):
            total += Int(v)
            count += 1
        end
    end
    if count == 0:
        return 0
    end
    return (total + count // 2) // count
end

function on_pactl_list(what, output, status):
    items = []
    parsed = None
    safe:
        parsed = json.decode(output)
    end
    if type(parsed) == "List":
        for d in parsed:
            if type(d) != "Dictionary":
                continue
            end
            name = String(d.get("name", ""))
            # monitory vystupu nejsou mikrofony
            if what == "sources" and (name.endswith(".monitor") or d.get("monitor_of_sink") != None):
                continue
            end
            items.append({"name": name, "desc": String(d.get("description", name)), "mute": d.get("mute") == True,
                          "volume": volume_percent(d.get("volume"))})
        end
    end
    P["sound"][what] = items
    call sound_render()
    return 0
end

function current(items, name):
    for it in items:
        if it["name"] == name:
            return it
        end
    end
    if len(items) > 0:
        return items[0]
    end
    return None
end

function sound_render():
    W = P["w"]
    if W.get("out_list", 0) == 0:
        return 0
    end
    S = P["sound"]
    for pair in [["out", "sinks", "sink"], ["in", "sources", "source"]]:
        sl = W[pair[0] + "_slider"]
        cur = current(S[pair[1]], S[pair[2]])
        call gtk.widget_set_visible(sl["section"], cur != None)
        if cur != None:
            S["lock"] = True
            call gtk.range_set_value(sl["scale"], cur["volume"])
            S["lock"] = False
            sl["muted"] = cur["mute"]
            call set_mute_icon(sl)
        end
        box = W[pair[0] + "_list"]
        call clear(box)
        # vyber zarizeni jen pri vice moznostech
        if len(S[pair[1]]) > 1:
            for it in S[pair[1]]:
                b = gtk.button_new_empty()
                call gtk.widget_add_class(b, "lx-row")
                call gtk.widget_set_can_focus(b, False)
                row = gtk.box_new(gtk.HORIZONTAL, 8)
                name = label(it["desc"], [], 0.0)
                call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
                call gtk.label_set_max_width_chars(name, 30)
                call gtk.box_pack_start(row, name, True, True, 0)
                if cur != None and it["name"] == cur["name"]:
                    call gtk.widget_add_class(b, "on")
                    call gtk.box_pack_end(row, gtk.image_new_from_icon_name("object-select-symbolic", luxos_gtk.ICON_MENU), False, False, 0)
                end
                call gtk.widget_set_halign(row, gtk.ALIGN_FILL)
                call gtk.widget_set_hexpand(row, True)
                call gtk.container_add(b, row)
                call lglib.connect_data(b, "clicked", 0, on_device_clicked, [pair[2], it["name"]])
                call gtk.box_pack_start(box, b, False, False, 0)
            end
        end
        call gtk.widget_show_all(box)
    end
    call fit("sound")
    return 0
end

function set_mute_icon(sl):
    icon = "audio-volume-high-symbolic"
    if sl["what"] == "source":
        icon = "audio-input-microphone-symbolic"
        if sl["muted"]:
            icon = "microphone-disabled-symbolic"
        end
    elif sl["muted"]:
        icon = "audio-volume-muted-symbolic"
    elif gtk.range_get_value(sl["scale"]) < 34.0:
        icon = "audio-volume-low-symbolic"
    elif gtk.range_get_value(sl["scale"]) < 67.0:
        icon = "audio-volume-medium-symbolic"
    end
    call gtk.button_set_image(sl["button"], gtk.image_new_from_icon_name(icon, luxos_gtk.ICON_MENU))
    return 0
end

function on_volume_changed(row, scale):
    if P["sound"]["lock"]:
        return 0
    end
    value = Int(gtk.range_get_value(scale) + 0.5)
    target = "@DEFAULT_SINK@"
    command = "set-sink-volume"
    mute = "set-sink-mute"
    if row["what"] == "source":
        target = "@DEFAULT_SOURCE@"
        command = "set-source-volume"
        mute = "set-source-mute"
    end
    call glib.spawn_quiet(["pactl", command, target, String(value) + "%"])
    # posunuti ztlumeneho zvuku ho zapne (jako v macOS)
    if row["muted"]:
        row["muted"] = False
        call glib.spawn_quiet(["pactl", mute, target, "0"])
    end
    call set_mute_icon(row)
    return 0
end

function on_mute_clicked(row, button):
    row["muted"] = not row["muted"]
    flag = "0"
    if row["muted"]:
        flag = "1"
    end
    if row["what"] == "source":
        call glib.spawn_quiet(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", flag])
    else:
        call glib.spawn_quiet(["pactl", "set-sink-mute", "@DEFAULT_SINK@", flag])
    end
    call set_mute_icon(row)
    return 0
end

function on_device_clicked(pair, button):
    command = "set-default-sink"
    if pair[0] == "source":
        command = "set-default-source"
    end
    P["sound"][pair[0]] = pair[1]
    call sound_render()
    call lglib.spawn_watched_data(["pactl", command, pair[1]], on_device_set, 0)
    return 0
end

function on_device_set(bound, pid, status):
    if is_visible("sound"):
        call sound_refresh()
    end
    return 0
end

# ---- Oznameni ---------------------------------------------------------------------------------------

function session():
    if P["session"] == -1:
        P["session"] = 0
        safe:
            bus = gio.session_bus()
            if bus != None:
                P["session"] = bus
            end
        end
    end
    return P["session"]
end

function notify_call(path, interface, method, values, signature, handler, bound):
    if session() == 0:
        return 0
    end
    call lgio.call_async(P["session"], NOTIFYD, path, interface, method, values, signature, 3000, handler, bound)
    return 0
end

function on_ignored(unused, values, error):
    return 0
end

# Bubliny luxos-notify by prekryvaly otevrene okno listy
function hide_bubbles(hidden):
    call notify_call(HISTORY_PATH, HISTORY, "SetPopupsHidden", [hidden], "(b)", on_ignored, 0)
    return 0
end

function notes_build(box):
    W = P["w"]
    call header(box, i18n.T("Notifications"), None)
    dnd = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(dnd, "lx-section")
    call gtk.box_pack_start(dnd, gtk.image_new_from_icon_name("notifications-disabled-symbolic", luxos_gtk.ICON_MENU), False, False, 4)
    call gtk.box_pack_start(dnd, label(i18n.T("Do Not Disturb"), [], 0.0), True, True, 0)
    sw = gtk.switch_new()
    call gtk.widget_set_can_focus(sw, False)
    call gtk.widget_set_valign(sw, gtk.ALIGN_CENTER)
    call gtk.connect(sw, "state-set", on_dnd_switch)
    call gtk.box_pack_end(dnd, sw, False, False, 2)
    W["dnd"] = sw
    call gtk.box_pack_start(box, dnd, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.scrolled_window_set_max_content_height(scroll, 420)
    call luxos_gtk.scrolled_window_set_propagate_natural_height(scroll, True)
    W["notes_list"] = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.container_add(scroll, W["notes_list"])
    W["notes_scroll"] = scroll
    call gtk.box_pack_start(box, scroll, False, False, 0)
    foot = gtk.box_new(gtk.HORIZONTAL, 4)
    W["notes_read"] = gtk.button_new(i18n.T("Mark All as Read"))
    W["notes_clear"] = gtk.button_new(i18n.T("Clear All"))
    for b in [W["notes_read"], W["notes_clear"]]:
        call gtk.widget_add_class(b, "lx-row")
        call gtk.widget_set_can_focus(b, False)
    end
    call gtk.connect(W["notes_read"], "clicked", on_mark_all)
    call gtk.connect(W["notes_clear"], "clicked", on_clear_all)
    call gtk.box_pack_start(foot, W["notes_read"], False, False, 0)
    call gtk.box_pack_end(foot, W["notes_clear"], False, False, 0)
    call gtk.box_pack_start(box, foot, False, False, 0)
    # zmeny historie, kdyz je okno otevrene
    if session() != 0:
        call lgio.subscribe_data(P["session"], NOTIFYD, LOG, "", LOG_PATH, "", lgio.SIGNAL_NONE, on_log_signal, 0)
        call lgio.subscribe_data(P["session"], NOTIFYD, HISTORY, "DoNotDisturbChanged", HISTORY_PATH, "", lgio.SIGNAL_NONE,
                                 on_dnd_signal, 0)
    end
    return 0
end

function on_log_signal(unused, sender, path, interface, signal, values):
    if is_visible("notifications"):
        call notes_refresh()
    end
    return 0
end

function on_dnd_signal(unused, sender, path, interface, signal, values):
    if len(values) > 0:
        call show_dnd(values[0] == True)
    end
    return 0
end

function notes_refresh():
    call notify_call(LOG_PATH, LOG, "List", ["", 50, False], "(sub)", on_notes_list, 0)
    call notify_call(HISTORY_PATH, HISTORY, "GetDoNotDisturb", [], "", on_dnd_state, 0)
    call notes_render()
    return 0
end

# Radek historie (sxssssssa(ss)ib): id, cas v us, ?, app_id, nazev aplikace, ikona, nadpis, text, ..., precteno
function on_notes_list(unused, values, error):
    items = []
    if values != None and len(values) > 0:
        for e in values[0]:
            if len(e) >= 11:
                items.append({"id": e[0], "time": e[1], "app_id": e[3], "app": e[4], "icon": e[5], "summary": e[6],
                              "body": e[7], "read": e[10] == True})
            end
        end
    end
    P["notes"]["items"] = items
    call notes_render()
    return 0
end

function on_dnd_state(unused, values, error):
    if values != None and len(values) > 0:
        call show_dnd(values[0] == True)
    end
    return 0
end

function show_dnd(on):
    P["notes"]["dnd"] = on
    sw = P["w"].get("dnd", 0)
    if sw != 0:
        P["notes"]["lock"] = True
        call gtk.switch_set_active(sw, on)
        P["notes"]["lock"] = False
    end
    return 0
end

function on_dnd_switch(state, switch):
    if not P["notes"]["lock"]:
        call notify_call(HISTORY_PATH, HISTORY, "SetDoNotDisturb", [state != 0], "(b)", on_ignored, 0)
    end
    return False
end

# "Ted", dnes "14:05", jinak "17. 11. 14:05" (podle jazyka)
function note_time(us):
    secs = us // 1000000
    if lglib.now() - secs < 60:
        return i18n.T("Now")
    end
    if glib.format_unix(secs, "%Y-%m-%d") == glib.date_time_format("%Y-%m-%d"):
        return glib.format_unix(secs, "%H:%M")
    end
    return glib.format_unix(secs, "%x %H:%M")
end

function notes_render():
    W = P["w"]
    box = W.get("notes_list", 0)
    if box == 0:
        return 0
    end
    call clear(box)
    items = P["notes"]["items"]
    if len(items) == 0:
        empty = label(i18n.T("No Notifications"), ["lx-dim"], 0.5)
        call gtk.widget_set_margins(empty, 0, 0, 18, 18)
        call gtk.box_pack_start(box, empty, False, False, 0)
    end
    unread = False
    for it in items:
        if not it["read"]:
            unread = True
        end
        # cela plocha oznameni je tlacitko (otevrit), krizek vedle nej
        outer = gtk.box_new(gtk.HORIZONTAL, 2)
        call gtk.widget_add_class(outer, "lx-section")
        open_button = gtk.button_new_empty()
        call gtk.widget_add_class(open_button, "lx-row")
        call gtk.widget_set_can_focus(open_button, False)
        call lglib.connect_data(open_button, "clicked", 0, on_note_open, it)
        card = gtk.box_new(gtk.HORIZONTAL, 10)
        icon = it["icon"]
        img = 0
        if icon.startswith("/") and exists(icon):
            pb = gtk.pixbuf_new_from_file_at_scale(icon, 32, 32, True)
            if pb != 0:
                img = gtk.image_new_from_pixbuf(pb)
                call glib.object_unref(pb)
            end
        end
        if img == 0:
            if icon == "" or icon.startswith("/"):
                icon = "dialog-information"
            end
            img = gtk.image_new_from_icon_name(icon, luxos_gtk.ICON_DIALOG)
            call gtk.image_set_pixel_size(img, 32)
        end
        call gtk.widget_set_valign(img, gtk.ALIGN_START)
        call gtk.box_pack_start(card, img, False, False, 0)
        col = gtk.box_new(gtk.VERTICAL, 2)
        top = gtk.box_new(gtk.HORIZONTAL, 6)
        name = it["app"]
        if name == "":
            name = it["app_id"]
        end
        app = label(name, ["lx-dim"], 0.0)
        call gtk.label_set_ellipsize(app, gtk.ELLIPSIZE_END)
        call gtk.box_pack_start(top, app, True, True, 0)
        call gtk.box_pack_start(top, label(note_time(it["time"]), ["lx-dim"], 1.0), False, False, 0)
        if not it["read"]:
            dot = gtk.box_new(gtk.HORIZONTAL, 0)
            call gtk.widget_add_class(dot, "lx-unread")
            call gtk.widget_set_valign(dot, gtk.ALIGN_CENTER)
            call gtk.box_pack_start(top, dot, False, False, 2)
        end
        call gtk.box_pack_start(col, top, False, False, 0)
        summary = label(it["summary"], ["lx-title"], 0.0)
        call gtk.label_set_line_wrap(summary, True)
        call gtk.label_set_max_width_chars(summary, 30)
        call gtk.box_pack_start(col, summary, False, False, 0)
        if it["body"] != "":
            body = label(it["body"], ["lx-dim"], 0.0)
            call gtk.label_set_line_wrap(body, True)
            call luxos_gtk.label_set_lines(body, 3)
            call gtk.label_set_ellipsize(body, gtk.ELLIPSIZE_END)
            call gtk.label_set_max_width_chars(body, 30)
            call gtk.box_pack_start(col, body, False, False, 0)
        end
        call gtk.box_pack_start(card, col, True, True, 0)
        call gtk.container_add(open_button, card)
        call gtk.box_pack_start(outer, open_button, True, True, 0)
        del_button = icon_button("window-close-symbolic", i18n.T("Delete"), on_note_delete, it["id"])
        call gtk.widget_set_valign(del_button, gtk.ALIGN_START)
        call gtk.box_pack_end(outer, del_button, False, False, 0)
        call gtk.box_pack_start(box, outer, False, False, 0)
    end
    call gtk.widget_set_sensitive(W["notes_read"], unread)
    call gtk.widget_set_sensitive(W["notes_clear"], len(items) > 0)
    call gtk.widget_show_all(box)
    # okno roste jen do minimalni vysky obsahu: seznam ji dostane podle sveho obsahu (nejvys 420 px)
    unsafe:
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        call __lsl_qbe_call4(__lsl_symbol("gtk_widget_get_preferred_height_for_width"), __lsl_unbox_int(box), WIDTH - 2 * 12, base, base + 4)
        natural = __lsl_qbe_s32(__lsl_qbe_load32(base + 4))
    end
    call gtk.scrolled_window_set_min_content_height(W["notes_scroll"], min(natural, 420))
    call fit("notifications")
    return 0
end

# Klik na oznameni (Android): vychozi akce aplikace, kdyz jeste bezi (luxos-notify posle ActionInvoked a z historie
# ho smaze); jinak otevrit aplikaci (desktop-entry) a oznameni smazat. Okno se zavre.
function on_note_open(item, button):
    call notify_call(HISTORY_PATH, HISTORY, "Activate", [item["id"]], "(s)", on_note_activated, item)
    call close_all()
    return 0
end

function on_note_activated(item, values, error):
    if values != None and len(values) > 0 and values[0] == True:
        return 0
    end
    if item["app_id"] != "":
        call glib.spawn_quiet(["gtk-launch", item["app_id"]])
    end
    call notify_call(LOG_PATH, LOG, "Delete", [[item["id"]]], "(as)", on_ignored, 0)
    return 0
end

function on_note_delete(id, button):
    call notify_call(LOG_PATH, LOG, "Delete", [[id]], "(as)", on_ignored, 0)
    return 0
end

function on_mark_all(button):
    call notify_call(LOG_PATH, LOG, "MarkAllRead", [], "", on_ignored, 0)
    return 0
end

function on_clear_all(button):
    call notify_call(LOG_PATH, LOG, "Clear", [], "", on_ignored, 0)
    return 0
end

function notes_mark_all_read():
    for it in P["notes"]["items"]:
        if not it["read"]:
            call notify_call(LOG_PATH, LOG, "MarkAllRead", [], "", on_ignored, 0)
            return 0
        end
    end
    return 0
end
