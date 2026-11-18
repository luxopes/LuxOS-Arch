# LuxOS - vyskakovaci okna horni listy: Wi-Fi, Zvuk a Oznameni (misto nabidek Xfce: nm-applet,
# xfce4-pulseaudio-plugin, notification-plugin). Vzhled jako Ovladaci centrum: matne sklo z tapety
# (luxos_glass.panel), dlazdice a posuvniky; zavre se pri ztrate fokusu nebo klavesou Esc.
#
#   Wi-Fi       vypinac, site serazene podle signalu (pripojena s fajfkou, zamek u zabezpecenych);
#               klik na sit: znama nebo otevrena se pripoji hned (nmcli), nova zabezpecena (WPA/WPA3
#               osobni) ukaze pole pro heslo - heslo jde NetworkManageru po D-Bus (AddAndActivateConnection),
#               nikdy v argumentech procesu; podnikova (802.1X) pres pruvodce NetworkManageru.
#   Zvuk        hlasitost a ztlumeni vystupu i vstupu, vyber vystupniho a vstupniho zarizeni (pactl);
#               dokud je okno otevrene, plugin zvuku v liste neukazuje bublinu s hlasitosti (show-notifications)
#   Oznameni    historie z xfce4-notifyd (D-Bus org.xfce.Notifyd.Log: List, Delete, MarkAllRead, Clear);
#               klik na oznameni jako v Androidu: vychozi akce aplikace (cz.luxos.NotificationHistory.Activate
#               z modulu files/src/luxos-notifyd.c - Posta otevre zpravu), jinak otevre aplikaci podle
#               desktop-entry; oznameni pak z historie zmizi,
#               Nerusit (xfconf xfce4-notifyd /do-not-disturb); pri zavreni okna jsou oznameni prectena.
#
#   call popups.start_server(standalone)   prijima prikazy klienta luxos-bar-popup (abstraktni socket)
#   call popups.toggle(druh)                "wifi" | "sound" | "notifications"
#   popups.panel_text("wifi")               vystup pro plugin genmon (ikona Wi-Fi v liste)
#   popups.migrate_panel(config)            starsi profily: jednou ikona Wi-Fi do listy, nm-applet ze systray
# Stav drzi slovnik P (zadne tridy: obsluhy signalu jsou funkce modulu s vazanymi daty).
load env, json, net, process
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys
load luxos_text as text
load luxos_glass as glass

KINDS = ["wifi", "sound", "notifications"]
WIDTH = 330
NM = "org.freedesktop.NetworkManager"

CSS = ("window.bp { background: transparent; }\n"
    + ".bp-box { background-color: @bp_bg; border-radius: 18px; border: 1px solid @bp_border; padding: 12px; color: @bp_fg; }\n"
    # sklo jako widgety na plose (luxos_glass.panel): pod panelem rozostrena tapeta, okraj karty widgetu
    + ".bp-box.lg-panel { background-color: transparent; border-color: rgba(255, 255, 255, 0.38);"
    + " border-top-color: rgba(255, 255, 255, 0.62); border-bottom-color: rgba(255, 255, 255, 0.20); box-shadow: inset 0 1px rgba(255, 255, 255, 0.18); }\n"
    + ".bp-box label { color: @bp_fg; }\n"
    + ".bp-head { font-weight: 700; font-size: 14px; }\n"
    + ".bp-caption { font-weight: 600; font-size: 11px; color: @bp_dim; margin: 6px 4px 0 4px; }\n"
    + ".bp-dim { font-size: 11px; color: @bp_dim; }\n"
    + ".bp-section { background-color: @bp_tile; border-radius: 14px; padding: 6px; }\n"
    + "button.bp-row { border-radius: 10px; padding: 6px 8px; min-height: 22px; background: none; background-image: none; border: none; box-shadow: none; color: @bp_fg; outline: none; }\n"
    + "button.bp-row:hover { background-color: @bp_tile_hover; }\n"
    + "button.bp-row label { font-size: 13px; }\n"
    + "button.bp-row.on label.bp-name { font-weight: 600; }\n"
    + ".bp-bubble { background-color: @bp_bubble; border-radius: 999px; min-width: 26px; min-height: 26px; }\n"
    + "button.bp-row.on .bp-bubble { background-color: #3d7bff; color: white; }\n"
    + "button.bp-icon { border-radius: 999px; min-width: 26px; min-height: 26px; padding: 0; background: none; background-image: none; border: none; box-shadow: none; color: @bp_fg; outline: none; }\n"
    + "button.bp-icon:hover { background-color: @bp_tile_hover; }\n"
    + "button.bp-footer { background: none; background-image: none; border: none; box-shadow: none; color: @bp_fg; padding: 4px 6px; border-radius: 8px; outline: none; }\n"
    + "button.bp-footer label { font-size: 12px; }\n"
    + "button.bp-footer:hover { background-color: @bp_tile; }\n"
    + "button.bp-accent { border-radius: 999px; padding: 3px 14px; border: none; outline: none; background-image: none; background-color: #3d7bff; box-shadow: none; }\n"
    + ".bp-box button.bp-accent label { color: white; font-weight: 600; font-size: 12px; }\n"
    + ".bp-box entry { min-height: 28px; border-radius: 8px; border: none; background-image: none; background-color: @bp_field; box-shadow: inset 0 0 0 1px @bp_border; color: @bp_fg; }\n"
    + ".bp-box switch { border-radius: 999px; border: none; background-image: none; background-color: @bp_bubble; box-shadow: none; min-height: 22px; }\n"
    + ".bp-box switch:checked { background-color: #3d7bff; }\n"
    + ".bp-box switch slider { border-radius: 999px; min-width: 20px; min-height: 20px; margin: 1px; border: none; background-image: none; background-color: white; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25); }\n"
    + ".bp-box scale trough { min-height: 22px; border-radius: 11px; background-color: @bp_trough; border: none; }\n"
    + ".bp-box scale highlight { border-radius: 11px; background-color: @bp_fill; border: none; min-height: 22px; }\n"
    + ".bp-box scale slider { min-width: 22px; min-height: 22px; margin: 0; border-radius: 11px; background-color: white; border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.35); }\n"
    + ".bp-note { background-color: @bp_tile; border-radius: 14px; padding: 4px 6px 4px 4px; }\n"
    + "button.bp-note-open { background: none; background-image: none; border: none; box-shadow: none; outline: none;"
    + " border-radius: 10px; padding: 6px 4px 6px 8px; color: @bp_fg; }\n"
    + "button.bp-note-open:hover { background-color: @bp_tile_hover; }\n"
    + ".bp-note .bp-summary { font-weight: 600; font-size: 12px; }\n"
    + ".bp-note .bp-body { font-size: 12px; color: @bp_dim; }\n"
    + ".bp-unread { background-color: #3d7bff; border-radius: 999px; min-width: 8px; min-height: 8px; }\n"
    + ".bp-error { color: #ff453a; font-size: 11px; }\n"
    + ".bp-box scrolledwindow, .bp-box viewport { background: transparent; border: none; }\n")

DARK = ("@define-color bp_bg rgba(32, 33, 52, 0.86); @define-color bp_border rgba(255, 255, 255, 0.14);\n"
    + "@define-color bp_fg #f4f4fa; @define-color bp_dim rgba(244, 244, 250, 0.6);\n"
    + "@define-color bp_tile rgba(255, 255, 255, 0.08); @define-color bp_tile_hover rgba(255, 255, 255, 0.13);\n"
    + "@define-color bp_bubble rgba(255, 255, 255, 0.14); @define-color bp_trough rgba(255, 255, 255, 0.14);\n"
    + "@define-color bp_fill rgba(255, 255, 255, 0.85); @define-color bp_field rgba(0, 0, 0, 0.24);\n")

LIGHT = ("@define-color bp_bg rgba(246, 247, 252, 0.88); @define-color bp_border rgba(0, 0, 0, 0.10);\n"
    + "@define-color bp_fg #1d1d2b; @define-color bp_dim rgba(29, 29, 43, 0.58);\n"
    + "@define-color bp_tile rgba(0, 0, 0, 0.05); @define-color bp_tile_hover rgba(0, 0, 0, 0.09);\n"
    + "@define-color bp_bubble rgba(0, 0, 0, 0.08); @define-color bp_trough rgba(0, 0, 0, 0.10);\n"
    + "@define-color bp_fill #ffffff; @define-color bp_field rgba(255, 255, 255, 0.55);\n")

P = {"provider": 0, "wins": {}, "boxes": {}, "content": {}, "listening": False, "standalone": False,
     "wifi": {"enabled": True, "nets": [], "pending": "", "ask": "", "error": "", "iface": "", "scan": 0},
     "sound": {"sinks": [], "sources": [], "sink": "", "source": "", "lock": False},
     "notes": {"items": [], "dnd": False, "sub": 0}, "session": 0}

# ---- pomucky --------------------------------------------------------------------------------

function log(message):
    call luxos_sys.eprint("luxos-bar-popup: " + message)
    return 0
end

# Vystup programu synchronne (jen ikona v liste pro genmon - bez hlavni smycky); "" pri chybe
function run_output(argv):
    path = glib.find_program_in_path(argv[0])
    if path == None or path == "":
        return ""
    end
    result = None
    safe:
        result = process.capture_result(path, argv[1:])
    end
    if result == None or not result["ok"]:
        return ""
    end
    return result["stdout"]
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

function icon_button(icon, tooltip, handler, data):
    b = gtk.button_new_from_icon_name(icon, gtk.ICON_MENU)
    call gtk.widget_add_class(b, "bp-icon")
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
    if tooltip != "":
        call gtk.widget_set_tooltip(b, tooltip)
    end
    call gtk.connect_data(b, "clicked", 0, handler, data)
    return b
end

function footer(box, title, command):
    b = gtk.button_new(title)
    call gtk.widget_add_class(b, "bp-footer")
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_set_halign(b, gtk.ALIGN_START)
    call gtk.connect_data(b, "clicked", 0, on_launch, command)
    call gtk.box_pack_start(box, b, False, False, 0)
    return b
end

function on_launch(command, button):
    call glib.spawn_quiet(command)
    call close_all()
    return 0
end

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

function css_text():
    name = gtk.settings_theme_name().lower()
    if name.find("dark") >= 0 or gtk.settings_prefer_dark():
        return DARK + CSS
    end
    return LIGHT + CSS
end

function on_theme_changed(pspec, settings):
    call gtk.css_set(P["provider"], css_text())
    return 0
end

# ---- okna -----------------------------------------------------------------------------------

function window_for(kind):
    win = P["wins"].get(kind, 0)
    if win != 0:
        return win
    end
    if P["provider"] == 0:
        P["provider"] = gtk.css_load(css_text())
        call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme_changed)
    end
    win = gtk.window_new(kind)
    call gtk.widget_add_class(win, "bp")
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_stick(win)
    call gtk.window_set_rgba(win)
    call gtk.window_set_wmclass(win, "luxos-bar-popup", "Luxos-bar-popup")
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "bp-box")
    call gtk.widget_set_size_request(box, WIDTH, -1)
    call gtk.container_add(win, box)
    call glass.panel(win, box, 18)
    call gtk.connect_data(win, "focus-out-event", 1, on_focus_out, kind)
    call gtk.connect_data(win, "key-press-event", 1, on_key, kind)
    call gtk.connect_data(win, "delete-event", 1, on_delete, kind)
    call gtk.connect_data(win, "size-allocate", 1, on_size, kind)
    P["wins"][kind] = win
    P["boxes"][kind] = box
    if kind == "wifi":
        call wifi_build(box)
    elif kind == "sound":
        call sound_build(box)
    else:
        call notes_build(box)
    end
    return win
end

function is_visible(kind):
    win = P["wins"].get(kind, 0)
    return win != 0 and gtk.widget_get_visible(win)
end

function toggle(kind):
    if kind not in KINDS:
        return 1
    end
    if is_visible(kind):
        call close(kind)
        return 0
    end
    call close_all()
    win = window_for(kind)
    if kind == "wifi":
        P["wifi"]["loaded"] = False
        call wifi_refresh(True)
    elif kind == "sound":
        call set_volume_osd(False)
        call sound_refresh()
    else:
        call notes_refresh()
    end
    if "anchor" not in P:
        P["anchor"] = {}
    end
    P["anchor"][kind] = gtk.pointer_position()
    call gtk.widget_show_all(win)
    call place(kind)
    stamp = gtk.get_current_event_time()
    if stamp == 0:
        stamp = gtk.CURRENT_TIME
    end
    call gtk.window_present_with_time(win, stamp)
    call log_test("shown " + kind)
    return 0
end

function close(kind):
    win = P["wins"].get(kind, 0)
    if win == 0 or not gtk.widget_get_visible(win):
        return 0
    end
    call gtk.widget_hide(win)
    if kind == "notifications":
        call notes_mark_all_read()
    end
    if kind == "sound":
        call set_volume_osd(True)
    end
    if kind == "wifi":
        P["wifi"]["ask"] = ""
        P["wifi"]["error"] = ""
    end
    call log_test("hidden " + kind)
    return 0
end

function close_all():
    for kind in KINDS:
        call close(kind)
    end
    return 0
end

# Pod listou, vodorovne pod ukazatelem mysi (ikona v liste), cele na monitoru. Misto se urci jen pri
# otevreni okna; pri zmene velikosti (jina ikona, delsi seznam) zustane okno u stejne ikony - mys je
# v te chvili uvnitr okna a okno by jinak "skocilo" pod ni.
function place(kind):
    win = P["wins"][kind]
    pointer = P.get("anchor", {}).get(kind)
    if pointer == None:
        pointer = gtk.pointer_position()
    end
    geo = gtk.monitor_at_point_workarea(pointer[0], pointer[1])
    size = gtk.window_get_size(win)
    x = pointer[0] - size[0] // 2
    x = max(geo[0] + 8, min(x, geo[0] + geo[2] - size[0] - 8))
    y = geo[1] + 6
    call gtk.window_move(win, x, y)
    return 0
end

function on_size(kind, allocation, window):
    if gtk.widget_get_visible(window):
        call place(kind)
    end
    return 0
end

function on_focus_out(kind, event, window):
    # testy pod Xvfb bez spravce oken: okno by se po zobrazeni hned zavrelo
    if env.get("LUXOS_HUB_NO_AUTOHIDE", "") == "1":
        return False
    end
    call glib.timeout_add_data(120, close_if_unfocused, kind)
    return False
end

function close_if_unfocused(kind):
    win = P["wins"].get(kind, 0)
    if win == 0:
        return False
    end
    active = gtk.screen_active_window()
    own = gtk.widget_get_window(win)
    if not gtk.window_is_active(win) or (active != 0 and active != own):
        call close(kind)
    end
    if active != 0:
        call glib.object_unref(active)
    end
    return False
end

function on_key(kind, event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        call close(kind)
        return True
    end
    return False
end

function on_delete(kind, event, window):
    call close(kind)
    return True
end

function log_test(message):
    path = env.get("LUXOS_BAR_POPUP_TEST_LOG", "")
    if path != None and path != "":
        safe:
            call writefile(path, glib.read_text(path) + message + "\n")
        end
    end
    return 0
end

# Testy: s LUXOS_BAR_POPUP_TEST_LOG zapise okno polohy ovladacich prvku ("pos jmeno x y" - stred
# na obrazovce), aby test mohl klikat bez odhadovani souradnic. Bez promenne nic.
function test_mark(name, widget):
    if env.get("LUXOS_BAR_POPUP_TEST_LOG", "") != "":
        if "test" not in P:
            P["test"] = {}
        end
        P["test"][name] = widget
    end
    return 0
end

function test_dump(kind):
    if env.get("LUXOS_BAR_POPUP_TEST_LOG", "") == "" or not is_visible(kind):
        return False
    end
    win = P["wins"][kind]
    pos = gtk.window_get_position(win)
    lines = ""
    for name in P.get("test", {}).keys():
        w = P["test"][name]
        safe:
            if gtk.widget_get_toplevel(w) == win and gtk.widget_is_visible(w):
                a = gtk.widget_get_allocation(w)
                # stred widgetu v souradnicich okna (i uvnitr posuvne oblasti)
                c = gtk.widget_translate_coordinates(w, win, a[2] // 2, a[3] // 2)
                if len(c) == 2:
                    lines = lines + "pos " + name + " " + String(pos[0] + c[0]) + " " + String(pos[1] + c[1]) + "\n"
                end
            end
        end
    end
    call log_test(lines + "rendered " + kind)
    return False
end

# Pred kazdym vykreslenim seznamu: stare radky zanikaji, odkazy na ne pryc
function test_reset():
    P["test"] = {}
    return 0
end

function header(box, title, switch_handler):
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(row, label(title, ["bp-head"], 0.0), True, True, 4)
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

# ---- Wi-Fi ----------------------------------------------------------------------------------

function wifi_build(box):
    W = P["content"]
    W["wifi_switch"] = header(box, i18n.T("Wi-Fi"), on_wifi_switch)
    W["wifi_caption"] = label(i18n.T("Networks"), ["bp-caption"], 0.0)
    call gtk.box_pack_start(box, W["wifi_caption"], False, False, 0)
    W["wifi_list"] = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_add_class(W["wifi_list"], "bp-section")
    call gtk.box_pack_start(box, W["wifi_list"], False, False, 0)
    # sit s prihlasovaci strankou: prihlaseni (luxos-network-login, jako upozorneni z luxos-hub)
    W["wifi_portal"] = gtk.button_new(i18n.T("Sign in to the network"))
    call gtk.widget_add_class(W["wifi_portal"], "bp-accent")
    call gtk.widget_set_can_focus(W["wifi_portal"], False)
    call gtk.widget_set_halign(W["wifi_portal"], gtk.ALIGN_START)
    call gtk.widget_set_no_show_all(W["wifi_portal"], True)
    call gtk.connect_data(W["wifi_portal"], "clicked", 0, on_launch, ["luxos-network-login"])
    call gtk.box_pack_start(box, W["wifi_portal"], False, False, 0)
    foot = gtk.box_new(gtk.HORIZONTAL, 0)
    call footer(foot, i18n.T("Network Settings…"), ["nm-connection-editor"])
    # vpravo dole: znovu vyhledat site
    W["wifi_rescan"] = icon_button("view-refresh-symbolic", i18n.T("Refresh"), on_wifi_rescan, 0)
    call gtk.box_pack_end(foot, W["wifi_rescan"], False, False, 0)
    call gtk.box_pack_start(box, foot, False, False, 0)
    return 0
end

function on_wifi_rescan(unused, button):
    call gtk.widget_set_sensitive(button, False)
    P["wifi"]["scan"] = glib.now()
    call glib.spawn_watched_data(["nmcli", "device", "wifi", "rescan"], on_wifi_rescanned, 0)
    return 0
end

# Seznam hned z mezipameti NetworkManageru (--rescan no: jinak nmcli pri starsim seznamu potichu
# hleda znovu a okno by sekundy ukazovalo prazdny seznam); nove hledani bezi zvlast a seznam pak obnovi
function wifi_refresh(scan):
    call glib.spawn_capture(["nmcli", "-t", "-f", "WIFI", "general"], on_wifi_radio, 0)
    call glib.spawn_capture(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], on_wifi_iface, 0)
    call glib.spawn_capture(["nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_wifi_connectivity, 0)
    call glib.spawn_capture(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], on_wifi_list, 0)
    if scan and glib.now() - P["wifi"]["scan"] > 10:
        P["wifi"]["scan"] = glib.now()
        call glib.spawn_watched_data(["nmcli", "device", "wifi", "rescan"], on_wifi_rescanned, 0)
    end
    return 0
end

function on_wifi_rescanned(bound, pid, status):
    rescan = P["content"].get("wifi_rescan", 0)
    if rescan != 0:
        call gtk.widget_set_sensitive(rescan, True)
    end
    if is_visible("wifi"):
        call glib.spawn_capture(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], on_wifi_list, 0)
    end
    return 0
end

# Pripojeno, ale za prihlasovaci strankou (hotel, vlak): v okne tlacitko Prihlaseni do site
function on_wifi_connectivity(unused, output, status):
    P["wifi"]["portal"] = output.strip() == "portal"
    call wifi_render()
    return 0
end

function on_wifi_radio(unused, output, status):
    P["wifi"]["enabled"] = output.strip() == "enabled"
    sw = P["content"].get("wifi_switch", 0)
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
    W = P["content"]
    box = W.get("wifi_list", 0)
    if box == 0:
        return 0
    end
    call test_reset()
    call test_mark("wifi-switch", W["wifi_switch"])
    call test_mark("wifi-rescan", W["wifi_rescan"])
    call test_mark("wifi-portal", W["wifi_portal"])
    call clear(box)
    call gtk.widget_set_visible(W["wifi_caption"], P["wifi"]["enabled"])
    if not P["wifi"]["enabled"]:
        call gtk.box_pack_start(box, label(i18n.T("Wi-Fi is off"), ["bp-dim"], 0.0), False, False, 6)
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
        call gtk.widget_add_class(b, "bp-row")
        call gtk.widget_set_can_focus(b, False)
        if net["active"]:
            call gtk.widget_add_class(b, "on")
        end
        row = gtk.box_new(gtk.HORIZONTAL, 10)
        bubble = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(bubble, "bp-bubble")
        img = gtk.image_new_from_icon_name(signal_icon(net["signal"]), gtk.ICON_MENU)
        call gtk.widget_set_hexpand(img, True)
        call gtk.box_pack_start(bubble, img, True, True, 0)
        # hexpand obrazku by se preneslo na bublinu a ta by se roztahla s nazvem site
        call gtk.widget_set_hexpand(bubble, False)
        call gtk.box_pack_start(row, bubble, False, False, 0)
        name = label(net["ssid"], ["bp-name"], 0.0)
        call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
        call gtk.label_set_max_width_chars(name, 24)
        call gtk.box_pack_start(row, name, True, True, 0)
        if net["ssid"] == P["wifi"]["pending"]:
            call gtk.box_pack_end(row, label(i18n.T("Connecting…"), ["bp-dim"], 1.0), False, False, 0)
        elif net["active"]:
            call gtk.box_pack_end(row, gtk.image_new_from_icon_name("object-select-symbolic", gtk.ICON_MENU), False, False, 0)
        elif net["secure"]:
            call gtk.box_pack_end(row, gtk.image_new_from_icon_name("changes-prevent-symbolic", gtk.ICON_MENU), False, False, 0)
        end
        call gtk.widget_set_halign(row, gtk.ALIGN_FILL)
        call gtk.widget_set_hexpand(row, True)
        call gtk.container_add(b, row)
        call gtk.connect_data(b, "clicked", 0, on_wifi_row, net)
        call test_mark("wifi:" + net["ssid"], b)
        call gtk.box_pack_start(box, b, False, False, 0)
        if P["wifi"]["ask"] == net["ssid"]:
            call gtk.box_pack_start(box, wifi_password_row(net), False, False, 0)
        end
    end
    if count == 0:
        empty = i18n.T("No networks found")
        if not P["wifi"].get("loaded", False) or P["wifi"]["scan"] > glib.now() - 10:
            empty = i18n.T("Searching…")
        end
        call gtk.box_pack_start(box, label(empty, ["bp-dim"], 0.0), False, False, 6)
    end
    portal = W.get("wifi_portal", 0)
    if portal != 0:
        call gtk.widget_set_visible(portal, P["wifi"].get("portal", False))
    end
    call gtk.widget_show_all(box)
    if W.get("wifi_entry", 0) != 0 and P["wifi"]["ask"] != "":
        call gtk.widget_grab_focus(W["wifi_entry"])
    end
    call test_marks_static("wifi")
    return 0
end

function wifi_password_row(net):
    W = P["content"]
    col = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_set_margins(col, 8, 8, 2, 6)
    entry = gtk.entry_new()
    call gtk.entry_set_visibility(entry, False)
    call gtk.entry_set_placeholder_text(entry, i18n.T("Password"))
    call gtk.entry_set_icon_from_icon_name(entry, gtk.ENTRY_ICON_SECONDARY, "view-reveal-symbolic")
    call gtk.connect_data(entry, "icon-press", 2, on_reveal, {"shown": False})
    call gtk.connect_data(entry, "activate", 0, on_wifi_join, net)
    call test_mark("wifi-entry", entry)
    W["wifi_entry"] = entry
    call gtk.box_pack_start(col, entry, False, False, 0)
    if P["wifi"]["error"] != "":
        call gtk.box_pack_start(col, label(P["wifi"]["error"], ["bp-error"], 0.0), False, False, 0)
    end
    buttons = gtk.box_new(gtk.HORIZONTAL, 6)
    join = gtk.button_new(i18n.T("Join"))
    call gtk.widget_add_class(join, "bp-accent")
    call gtk.widget_set_can_focus(join, False)
    call gtk.connect_data(join, "clicked", 0, on_wifi_join, net)
    call test_mark("wifi-join", join)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.widget_add_class(cancel, "bp-footer")
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
    call glib.spawn_watched_data(["nmcli", "radio", "wifi", value], on_wifi_changed, 0)
    return False
end

function on_wifi_changed(bound, pid, status):
    call refresh_panel_wifi()
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
        call glib.spawn_capture(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], on_known_profiles, net)
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
    call glib.spawn_capture(["nmcli", "--wait", "30", "device", "wifi", "connect", net["ssid"]], on_wifi_connected, net)
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
    call refresh_panel_wifi()
    call wifi_refresh(False)
    return 0
end

# Nova zabezpecena sit: profil s heslem primo NetworkManageru po D-Bus (heslo neni v argumentech procesu)
function on_wifi_join(net, widget):
    entry = P["content"].get("wifi_entry", 0)
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
    call glib.timeout_add_seconds_data(4, wifi_after_join, net)
    return 0
end

function wifi_after_join(net):
    P["wifi"]["pending"] = ""
    call refresh_panel_wifi()
    if is_visible("wifi"):
        call wifi_refresh(False)
    end
    return False
end

# Nastaveni profilu pro NetworkManager (a{sa{sv}}): SSID v bajtech UTF-8, WPA3 = sae, jinak wpa-psk
function wifi_settings(net, password):
    raw = net.bytes(net["ssid"])
    ssid = []
    for i in range(len(raw)):
        ssid.append(raw[i])
    end
    mgmt = "wpa-psk"
    if net["security"].find("WPA3") >= 0 and net["security"].find("WPA2") < 0:
        mgmt = "sae"
    end
    security = {"key-mgmt": ["s", mgmt], "psk": ["s", password]}
    if net["security"].find("WEP") >= 0:
        security = {"key-mgmt": ["s", "none"], "wep-key0": ["s", password], "wep-key-type": ["u", 1]}
    end
    return {"connection": {"id": ["s", net["ssid"]], "type": ["s", "802-11-wireless"]},
            "802-11-wireless": {"ssid": ["ay", ssid], "mode": ["s", "infrastructure"]},
            "802-11-wireless-security": security}
end

# "" pri uspechu, jinak text chyby
function wifi_add_and_activate(net, password):
    bus = 0
    safe:
        bus = gio.system_bus()
    end
    if bus == 0:
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

# Ikona Wi-Fi v liste (genmon): sila signalu pripojene site, vypnuto, bez site
function panel_text(kind):
    if kind != "wifi":
        return ""
    end
    radio = run_output(["nmcli", "-t", "-f", "WIFI", "general"]).strip()
    state = nm_fields(run_output(["nmcli", "-t", "-f", "STATE,CONNECTIVITY", "general"]).strip())
    icon = "network-wireless-offline-symbolic"
    tip = i18n.T("Wi-Fi is off")
    click = ""
    if radio == "enabled":
        icon = "network-wireless-disconnected-symbolic"
        tip = i18n.T("Wi-Fi")
        out = run_output(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"])
        for line in out.split("\n"):
            f = nm_fields(line)
            if len(f) >= 3 and f[0].strip() == "*":
                sig = 0
                if text.is_digits(f[2]):
                    sig = Int(f[2])
                end
                icon = signal_icon(sig)
                tip = f[1]
                # pripojeno, ale bez internetu: za prihlasovaci strankou klik otevre prihlaseni
                if len(state) >= 2 and state[1] == "portal":
                    icon = "network-wireless-no-route-symbolic"
                    tip = f[1] + " – " + i18n.T("Sign in to the network")
                    click = "luxos-network-login"
                elif len(state) >= 2 and (state[1] == "limited" or state[1] == "none"):
                    icon = "network-wireless-no-route-symbolic"
                end
                break
            end
        end
        if len(state) >= 1 and state[0].startswith("connecting"):
            icon = "network-wireless-acquiring-symbolic"
            tip = i18n.T("Connecting…")
        end
    end
    # klik spusti tentyz program (plna cesta: lista spustena sezenim nemusi mit jeho slozku v PATH)
    program = glib.readlink("/proc/self/exe")
    if program == "" or program.find(" ") >= 0:
        program = "luxos-bar-popup"
    end
    if click == "":
        click = program + " wifi"
    end
    return "<icon>" + icon + "</icon><iconclick>" + click + "</iconclick><tool>" + glib.markup_escape(tip) + "</tool>"
end

# genmon s ikonou Wi-Fi: obnovit hned (jinak az podle periody pluginu). Cislo pluginu se zjisti jednou
# z xfconf po D-Bus (bez spousteni procesu - luxos-hub to vola pri kazde zmene site), pak jen PluginEvent.
function wifi_plugin_id():
    if P.get("wifi_plugin", "") != "":
        return P["wifi_plugin"]
    end
    props = None
    safe:
        props = gio.call_values(P["session"], "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf",
                                "GetAllProperties", ["xfce4-panel", "/plugins"], "(ss)", 2000)
    end
    if props == None or len(props) == 0 or type(props[0]) != "Dictionary":
        return ""
    end
    for key in props[0].keys():
        if key.endswith("/command") and String(props[0][key]).find("luxos-bar-popup --panel wifi") >= 0:
            P["wifi_plugin"] = key.split("/")[2].replace("plugin-", "")
            return P["wifi_plugin"]
        end
    end
    return ""
end

function refresh_panel_wifi():
    if P["session"] == 0:
        safe:
            P["session"] = gio.session_bus()
        end
    end
    if P["session"] == 0:
        return 0
    end
    id = wifi_plugin_id()
    if id == "":
        return 0
    end
    safe:
        call gio.call_values(P["session"], "org.xfce.Panel", "/org/xfce/Panel", "org.xfce.Panel", "PluginEvent",
                             ["genmon-" + id, "refresh", ["b", True]], "(ssv)", 2000)
    end
    return 0
end

# ---- Zvuk -----------------------------------------------------------------------------------

# Bublina s hlasitosti z pluginu zvuku v liste (xfce4-pulseaudio-plugin, volba show-notifications):
# pri otevrenem okne Zvuk vypnuta, pri zavreni vracena. Puvodni hodnota v $XDG_RUNTIME_DIR, aby sla
# vratit i po padu (start_server).
function osd_state_path():
    return runtime_dir() + "/luxos-bar-popup-osd"
end

function xfconf_bus():
    if P["session"] == 0:
        safe:
            P["session"] = gio.session_bus()
        end
    end
    return P["session"]
end

function set_volume_osd(enabled):
    bus = xfconf_bus()
    if bus == 0:
        return 0
    end
    if enabled:
        saved = glib.read_text(osd_state_path())
        for line in saved.split("\n"):
            parts = line.split(" ")
            if len(parts) == 2 and text.is_digits(parts[0]):
                safe:
                    call gio.call_values(bus, "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", "SetProperty",
                                         ["xfce4-panel", "/plugins/plugin-" + parts[0] + "/show-notifications", ["b", parts[1] == "true"]],
                                         "(ssv)", 2000)
                end
            end
        end
        call glib.unlink(osd_state_path())
        return 0
    end
    if exists(osd_state_path()):
        return 0                       # uz vypnuto (a puvodni hodnota ulozena)
    end
    props = None
    safe:
        props = gio.call_values(bus, "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf",
                                "GetAllProperties", ["xfce4-panel", "/plugins"], "(ss)", 2000)
    end
    if props == None or len(props) == 0 or type(props[0]) != "Dictionary":
        return 0
    end
    saved = ""
    for key in props[0].keys():
        if key.count("/") == 2 and String(props[0][key]) == "pulseaudio":
            id = key.split("/")[2].replace("plugin-", "")
            on = props[0].get(key + "/show-notifications", True) != False
            if on:
                saved = saved + id + " true\n"
                safe:
                    call gio.call_values(bus, "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", "SetProperty",
                                         ["xfce4-panel", key + "/show-notifications", ["b", False]], "(ssv)", 2000)
                end
            end
        end
    end
    if saved != "":
        call writefile(osd_state_path(), saved)
    end
    return 0
end

function sound_build(box):
    W = P["content"]
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
    call gtk.widget_add_class(sec, "bp-section")
    call gtk.widget_set_margins(sec, 0, 0, 0, 0)
    call gtk.box_pack_start(sec, label(title, ["bp-caption"], 0.0), False, False, 0)
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
    call gtk.connect_data(scale, "value-changed", 0, on_volume_changed, row)
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
    call glib.spawn_capture(["pactl", "-f", "json", "list", "sinks"], on_pactl_list, "sinks")
    call glib.spawn_capture(["pactl", "-f", "json", "list", "sources"], on_pactl_list, "sources")
    call glib.spawn_capture(["pactl", "get-default-sink"], on_pactl_default, "sink")
    call glib.spawn_capture(["pactl", "get-default-source"], on_pactl_default, "source")
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
    W = P["content"]
    if W.get("out_list", 0) == 0:
        return 0
    end
    S = P["sound"]
    call test_reset()
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
                call gtk.widget_add_class(b, "bp-row")
                call gtk.widget_set_can_focus(b, False)
                row = gtk.box_new(gtk.HORIZONTAL, 8)
                name = label(it["desc"], ["bp-name"], 0.0)
                call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
                call gtk.label_set_max_width_chars(name, 30)
                call gtk.box_pack_start(row, name, True, True, 0)
                if cur != None and it["name"] == cur["name"]:
                    call gtk.widget_add_class(b, "on")
                    call gtk.box_pack_end(row, gtk.image_new_from_icon_name("object-select-symbolic", gtk.ICON_MENU), False, False, 0)
                end
                call gtk.widget_set_halign(row, gtk.ALIGN_FILL)
                call gtk.widget_set_hexpand(row, True)
                call gtk.container_add(b, row)
                call gtk.connect_data(b, "clicked", 0, on_device_clicked, [pair[2], it["name"]])
                call test_mark(pair[2] + ":" + it["name"], b)
                call gtk.box_pack_start(box, b, False, False, 0)
            end
        end
        call gtk.widget_show_all(box)
    end
    call test_mark("mute:sink", W["out_slider"]["button"])
    call test_mark("mute:source", W["in_slider"]["button"])
    call test_marks_static("sound")
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
    call gtk.button_set_image(sl["button"], gtk.image_new_from_icon_name(icon, gtk.ICON_MENU))
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
    call glib.spawn_watched_data(["pactl", command, pair[1]], on_device_set, 0)
    return 0
end

function on_device_set(bound, pid, status):
    if is_visible("sound"):
        call sound_refresh()
    end
    return 0
end

# ---- Oznameni -------------------------------------------------------------------------------

function notes_build(box):
    W = P["content"]
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(row, label(i18n.T("Notifications"), ["bp-head"], 0.0), True, True, 4)
    call gtk.box_pack_start(box, row, False, False, 0)
    dnd = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(dnd, "bp-section")
    call gtk.box_pack_start(dnd, gtk.image_new_from_icon_name("notifications-disabled-symbolic", gtk.ICON_MENU), False, False, 4)
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
    call gtk.scrolled_window_set_propagate_natural_height(scroll, True)
    W["notes_list"] = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.container_add(scroll, W["notes_list"])
    call gtk.box_pack_start(box, scroll, False, False, 0)
    foot = gtk.box_new(gtk.HORIZONTAL, 4)
    W["notes_read"] = gtk.button_new(i18n.T("Mark All as Read"))
    W["notes_clear"] = gtk.button_new(i18n.T("Clear All"))
    for b in [W["notes_read"], W["notes_clear"]]:
        call gtk.widget_add_class(b, "bp-footer")
        call gtk.widget_set_can_focus(b, False)
    end
    call gtk.connect(W["notes_read"], "clicked", on_mark_all)
    call gtk.connect(W["notes_clear"], "clicked", on_clear_all)
    call gtk.box_pack_start(foot, W["notes_read"], False, False, 0)
    call gtk.box_pack_end(foot, W["notes_clear"], False, False, 0)
    call gtk.box_pack_start(box, foot, False, False, 0)
    # zmeny historie, kdyz je okno otevrene
    if P["session"] == 0:
        safe:
            P["session"] = gio.session_bus()
        end
    end
    if P["session"] != 0:
        safe:
            P["notes"]["sub"] = gio.subscribe_values(P["session"], "", "org.xfce.Notifyd.Log", "", "/org/xfce/Notifyd", on_log_signal)
        end
    end
    return 0
end

function on_log_signal(sender, path, interface, signal, values):
    if is_visible("notifications"):
        call notes_refresh()
    end
    return 0
end

function log_call(method, values, signature):
    if P["session"] == 0:
        safe:
            P["session"] = gio.session_bus()
        end
    end
    result = None
    try:
        result = gio.call_values(P["session"], "org.xfce.Notifyd", "/org/xfce/Notifyd", "org.xfce.Notifyd.Log",
                                 method, values, signature, 3000)
    else:
        call log("notifications " + method + ": " + String(last_error()))
    end
    return result
end

function notes_refresh():
    items = []
    reply = log_call("List", ["", 50, False], "(sub)")
    if reply != None and len(reply) > 0 and type(reply[0]) == "List":
        for e in reply[0]:
            if type(e) == "List" and len(e) >= 11:
                name = e[4]
                if name == "":
                    name = app_name(e[3])
                end
                items.append({"id": e[0], "time": e[1], "app_id": e[3], "app": name, "icon": e[5], "summary": e[6],
                              "body": e[7], "read": e[10] == True})
            end
        end
    end
    P["notes"]["items"] = items
    call glib.spawn_capture(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb"], on_dnd_state, 0)
    call notes_render()
    return 0
end

function on_dnd_state(unused, output, status):
    P["notes"]["dnd"] = output.strip() == "true"
    sw = P["content"].get("dnd", 0)
    if sw != 0:
        P["notes"]["lock"] = True
        call gtk.switch_set_active(sw, P["notes"]["dnd"])
        P["notes"]["lock"] = False
    end
    return 0
end

function on_dnd_switch(state, switch):
    if P["notes"].get("lock", False):
        return False
    end
    value = "false"
    if state != 0:
        value = "true"
    end
    call glib.spawn_quiet(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb", "-n", "-t", "bool", "-s", value])
    return False
end

# "Ted", dnes "14:05", jinak "17. 11. 14:05" (podle jazyka)
function note_time(us):
    secs = us // 1000000
    if glib.now() - secs < 60:
        return i18n.T("Now")
    end
    if glib.format_unix(secs, "%Y-%m-%d") == glib.date_time_format("%Y-%m-%d"):
        return glib.format_unix(secs, "%H:%M")
    end
    return glib.format_unix(secs, "%x %H:%M")
end

function notes_render():
    W = P["content"]
    box = W.get("notes_list", 0)
    if box == 0:
        return 0
    end
    call test_reset()
    call clear(box)
    items = P["notes"]["items"]
    if len(items) == 0:
        empty = label(i18n.T("No Notifications"), ["bp-dim"], 0.5)
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
        call gtk.widget_add_class(outer, "bp-note")
        open_button = gtk.button_new_empty()
        call gtk.widget_add_class(open_button, "bp-note-open")
        call gtk.widget_set_can_focus(open_button, False)
        call gtk.widget_set_tooltip(open_button, i18n.T("Open"))
        call gtk.connect_data(open_button, "clicked", 0, on_note_open, it["id"])
        call test_mark("open:" + it["id"], open_button)
        card = gtk.box_new(gtk.HORIZONTAL, 10)
        icon = it["icon"]
        img = 0
        if icon != "" and icon.startswith("/") and exists(icon):
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
            img = gtk.image_new_from_icon_name(icon, gtk.ICON_DIALOG)
            call gtk.image_set_pixel_size(img, 32)
        end
        call gtk.widget_set_valign(img, gtk.ALIGN_START)
        call gtk.box_pack_start(card, img, False, False, 0)
        col = gtk.box_new(gtk.VERTICAL, 2)
        top = gtk.box_new(gtk.HORIZONTAL, 6)
        app = label(it["app"], ["bp-dim"], 0.0)
        call gtk.label_set_ellipsize(app, gtk.ELLIPSIZE_END)
        call gtk.box_pack_start(top, app, True, True, 0)
        call gtk.box_pack_start(top, label(note_time(it["time"]), ["bp-dim"], 1.0), False, False, 0)
        if not it["read"]:
            dot = gtk.box_new(gtk.HORIZONTAL, 0)
            call gtk.widget_add_class(dot, "bp-unread")
            call gtk.widget_set_valign(dot, gtk.ALIGN_CENTER)
            call gtk.box_pack_start(top, dot, False, False, 2)
        end
        call gtk.box_pack_start(col, top, False, False, 0)
        summary = label(it["summary"], ["bp-summary"], 0.0)
        call gtk.label_set_line_wrap(summary, True)
        call gtk.label_set_max_width_chars(summary, 30)
        call gtk.box_pack_start(col, summary, False, False, 0)
        if it["body"] != "":
            body = label(it["body"], ["bp-body"], 0.0)
            call gtk.label_set_line_wrap(body, True)
            call gtk.label_set_lines(body, 3)
            call gtk.label_set_ellipsize(body, gtk.ELLIPSIZE_END)
            call gtk.label_set_max_width_chars(body, 30)
            call gtk.box_pack_start(col, body, False, False, 0)
        end
        call gtk.box_pack_start(card, col, True, True, 0)
        call gtk.container_add(open_button, card)
        call gtk.box_pack_start(outer, open_button, True, True, 0)
        del_button = icon_button("window-close-symbolic", i18n.T("Delete"), on_note_delete, it["id"])
        call gtk.widget_set_valign(del_button, gtk.ALIGN_START)
        call test_mark("delete:" + it["id"], del_button)
        call gtk.box_pack_end(outer, del_button, False, False, 0)
        call gtk.box_pack_start(box, outer, False, False, 0)
    end
    call gtk.widget_set_sensitive(W["notes_read"], unread)
    call gtk.widget_set_sensitive(W["notes_clear"], len(items) > 0)
    call gtk.widget_show_all(box)
    call test_mark("mark-all", W["notes_read"])
    call test_mark("clear-all", W["notes_clear"])
    call test_mark("dnd", W["dnd"])
    call test_marks_static("notifications")
    return 0
end

function test_marks_static(kind):
    if env.get("LUXOS_BAR_POPUP_TEST_LOG", "") != "":
        call glib.timeout_add_data(400, test_dump, kind)
    end
    return 0
end

# Nazev aplikace z jejiho .desktop (Name[jazyk], jinak Name), kdyz ho historie nema (desktop-entry)
function app_name(app_id):
    if app_id == "":
        return ""
    end
    dirs = [env.get("XDG_DATA_HOME", env.get("HOME", "") + "/.local/share")]
    for d in env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        dirs.append(d)
    end
    for d in dirs:
        path = d + "/applications/" + app_id + ".desktop"
        if d != "" and exists(path):
            name = ""
            local = ""
            key = "Name[" + i18n.lang() + "]="
            for line in glib.read_text(path).split("\n"):
                if line.startswith("[") and line != "[Desktop Entry]":
                    break
                end
                if line.startswith("Name=") and name == "":
                    name = line[5:]
                elif line.startswith(key):
                    local = line[len(key):]
                end
            end
            if local != "":
                return local
            end
            if name != "":
                return name
            end
        end
    end
    return app_id
end

# Klik na oznameni (Android): vychozi akce aplikace, kdyz jeste bezi (modul luxos-notifyd posle
# ActionInvoked a oznameni zavre - z historie zmizi samo); jinak otevrit aplikaci (desktop-entry)
# a oznameni z historie smazat. Okno se zavre.
function on_note_open(id, button):
    item = None
    for it in P["notes"]["items"]:
        if it["id"] == id:
            item = it
        end
    end
    handled = False
    reply = None
    safe:
        reply = gio.call_values(P["session"], "org.freedesktop.Notifications", "/cz/luxos/NotificationHistory",
                                "cz.luxos.NotificationHistory", "Activate", [id], "(s)", 2000)
    end
    if reply != None and len(reply) > 0 and reply[0] == True:
        handled = True
    end
    if not handled and item != None and item["app_id"] != "":
        call glib.spawn_quiet(["gtk-launch", item["app_id"]])
        handled = True
    end
    call log_test("open " + id + " " + String(handled))
    if handled:
        call log_call("Delete", [[id]], "(as)")
    end
    call close_all()
    return 0
end

function on_note_delete(id, button):
    call log_call("Delete", [[id]], "(as)")
    call notes_refresh()
    return 0
end

function on_mark_all(button):
    call log_call("MarkAllRead", [], "")
    call notes_refresh()
    return 0
end

function on_clear_all(button):
    call log_call("Clear", [], "")
    call notes_refresh()
    return 0
end

function notes_mark_all_read():
    for it in P["notes"]["items"]:
        if not it["read"]:
            call log_call("MarkAllRead", [], "")
            return 0
        end
    end
    return 0
end

# ---- lista: starsi profily ------------------------------------------------------------------

# xfconf-query nad kanalem xfce4-panel; None pri chybe (vlastnost neexistuje, xfconf nebezi)
function panel_xfconf(args):
    argv = ["xfconf-query", "-c", "xfce4-panel"]
    argv.extend(args)
    path = glib.find_program_in_path("xfconf-query")
    if path == None or path == "":
        return None
    end
    result = None
    safe:
        result = process.capture_result(path, argv[1:])
    end
    if result == None or not result["ok"]:
        return None
    end
    return result["stdout"].strip()
end

# Wi-Fi v liste: starsim profilum jednou prida vlastni ikonu Wi-Fi (luxos-bar-popup) za ikony (systray)
# a skryje v nich ikonu nm-applet (bezi dal kvuli VPN a podnikovym sitim). Kdo ikonu odebere, tomu se nevrati.
function migrate_panel(config):
    mark = config + "/bar-wifi-added"
    if exists(mark):
        return False
    end
    props = panel_xfconf(["-l", "-p", "/plugins"])
    if props == None or props == "":
        return True                    # xfconf jeste nebezi: zkusit pozdeji
    end
    ids = []
    tray = ""
    for p in props.split("\n"):
        if p.endswith("/command"):
            command = panel_xfconf(["-p", p])
            if command != None and command.startswith("luxos-bar-popup --panel wifi"):
                call glib.mkdir_p(config)
                call writefile(mark, "")
                return False
            end
        end
        if p.count("/") == 2 and p.startswith("/plugins/plugin-"):
            ids.append(text.to_int(p.split("-")[1], 0))
            if tray == "" and panel_xfconf(["-p", p]) == "systray":
                tray = p.split("-")[1]
            end
        end
    end
    call glib.mkdir_p(config)
    call writefile(mark, "")
    if len(ids) == 0 or tray == "":
        return False                   # lista bez ikon (vlastni rozlozeni): nemenit
    end
    new = String(max(ids) + 1)
    panels = panel_xfconf(["-l", "-p", "/panels"])
    if panels == None:
        panels = ""
    end
    for panel in panels.split("\n"):
        if not panel.endswith("/plugin-ids"):
            continue
        end
        raw = panel_xfconf(["-p", panel])
        if raw == None:
            raw = ""
        end
        # "Value is an array with N items:", prazdny radek, pak hodnoty (cislo z hlavicky neni id)
        order = []
        for v in raw.split("\n")[2:]:
            if text.is_digits(v.strip()):
                order.append(v.strip())
            end
        end
        if tray not in order:
            continue
        end
        order.insert(order.index(tray) + 1, new)
        base = "/plugins/plugin-" + new
        call panel_xfconf(["-p", base, "-n", "-t", "string", "-s", "genmon"])
        call panel_xfconf(["-p", base + "/command", "-n", "-t", "string", "-s", "luxos-bar-popup --panel wifi"])
        call panel_xfconf(["-p", base + "/update-period", "-n", "-t", "int", "-s", "10000"])
        call panel_xfconf(["-p", base + "/use-label", "-n", "-t", "bool", "-s", "false"])
        call panel_xfconf(["-p", base + "/enable-single-row", "-n", "-t", "bool", "-s", "true"])
        args = ["-p", panel, "--force-array"]
        for v in order:
            args.extend(["-t", "int", "-s", v])
        end
        call panel_xfconf(args)
        # ikona nm-applet v systray skryta; ostatni skryte polozky zustanou
        hidden = []
        cur = panel_xfconf(["-p", "/plugins/plugin-" + tray + "/hidden-items"])
        if cur != None:
            for line in cur.split("\n")[2:]:
                if line.strip() != "" and line.strip() not in hidden:
                    hidden.append(line.strip())
                end
            end
        end
        if "nm-applet" not in hidden:
            hidden.append("nm-applet")
        end
        args = ["-p", "/plugins/plugin-" + tray + "/hidden-items", "-n", "--force-array"]
        for h in hidden:
            args.extend(["-t", "string", "-s", h])
        end
        call panel_xfconf(args)
        call glib.spawn(["xfce4-panel", "-r"])
        return False
    end
    return False
end

# Rozlozeni klavesnice v liste jako text (US, CZ) misto vlajky: plugin xkb z Xfce -> luxos-xkb
# (files/src/luxos-xkb.c) se stejnym mistem v liste. Jednou (znacka bar-xkb-text); xfce4-panel -r
# zmenu typu pluginu neprepise.
function migrate_keyboard(config):
    mark = config + "/bar-xkb-text"
    if exists(mark):
        return False
    end
    props = panel_xfconf(["-l", "-p", "/plugins"])
    if props == None or props == "":
        return True                    # xfconf jeste nebezi: zkusit pozdeji
    end
    changed = False
    for p in props.split("\n"):
        if p.count("/") == 2 and p.startswith("/plugins/plugin-") and panel_xfconf(["-p", p]) == "xkb":
            call panel_xfconf(["-p", p, "-s", "luxos-xkb"])
            changed = True
        end
    end
    call glib.mkdir_p(config)
    call writefile(mark, "")
    if changed:
        call glib.spawn(["xfce4-panel", "-r"])
    end
    return False
end

# ---- prikazy klienta (abstraktni socket) ----------------------------------------------------

function runtime_dir():
    base = env.get("XDG_RUNTIME_DIR", "")
    if base == None or base == "":
        base = "/tmp"
    end
    return base
end

function socket_name():
    display = env.get("DISPLAY", "")
    if display == None:
        display = ""
    end
    return "luxos-bar-popup-" + String(luxos_sys.getuid()) + "-" + display
end

function start_server(standalone):
    P["standalone"] = standalone
    # okno Zvuk spadlo s vypnutou bublinou hlasitosti: vratit
    if exists(osd_state_path()):
        call set_volume_osd(True)
    end
    fd = luxos_sys.unix_listen(socket_name())
    if fd >= 0:
        P["listening"] = True
        call glib.fd_add_data(fd, 1, on_listen, fd)
        return True
    end
    if not standalone:
        # jmeno drzi samostatny proces (hub se restartoval): zkusit pozdeji
        call glib.timeout_add_seconds_data(5, retry_listen, 0)
    end
    return False
end

function retry_listen(bound):
    fd = luxos_sys.unix_listen(socket_name())
    if fd < 0:
        return True
    end
    P["listening"] = True
    call glib.fd_add_data(fd, 1, on_listen, fd)
    return False
end

function on_listen(listen_fd, handle, condition):
    while True:
        conn = luxos_sys.unix_accept(listen_fd)
        if conn < 0:
            break
        end
        if luxos_sys.peer_uid(conn) != luxos_sys.getuid():
            call luxos_sys.close(conn)
            continue
        end
        state = {"fd": conn, "buf": "", "done": False}
        call glib.fd_add_data(conn, 1 + 8 + 16, on_conn_data, state)
    end
    return True
end

function on_conn_data(state, handle, condition):
    if state["done"]:
        return False
    end
    r = luxos_sys.recv_text(state["fd"])
    if r[0] > 0:
        state["buf"] = state["buf"] + r[1]
        if state["buf"].find("\n") < 0 and len(state["buf"]) < 64:
            return True
        end
        state["done"] = True
        kind = state["buf"].split("\n")[0].strip()
        code = 1
        if kind in KINDS:
            code = 0
        end
        call luxos_sys.send_text(state["fd"], String(code) + "\n")
        call luxos_sys.close(state["fd"])
        if code == 0:
            call toggle(kind)
        end
        return False
    end
    state["done"] = True
    call luxos_sys.close(state["fd"])
    return False
end

# Klient: druh posle bezicimu serveru (hub nebo samostatny proces); -1 = nikdo neposloucha
function client_send(kind):
    fd = luxos_sys.unix_connect(socket_name())
    if fd < 0:
        return -1
    end
    if not luxos_sys.send_text(fd, kind + "\n"):
        call luxos_sys.close(fd)
        return -1
    end
    if not luxos_sys.wait_readable(fd, 3000):
        call luxos_sys.close(fd)
        return -1
    end
    r = luxos_sys.recv_text(fd)
    call luxos_sys.close(fd)
    if r[0] > 0 and r[1].strip() == "0":
        return 0
    end
    return 1
end
