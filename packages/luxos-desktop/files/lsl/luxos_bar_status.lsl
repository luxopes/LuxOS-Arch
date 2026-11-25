# LuxOS - stav systemu pro horni listu na Waylandu (luxos-bar): sit (NetworkManager), baterie (UPower), zvuk
# (pactl subscribe nad PipeWire), rozlozeni klavesnice a probuzeni (logind). Vse z udalosti: signaly D-Bus
# PropertiesChanged a proud `pactl subscribe`, zadne pravidelne dotazovani. Bez sluzby polozka zmizi.
#
#   status.start(f)            f(druh) po kazde zmene: "network", "battery", "sound", "keyboard", "notifications",
#                              "resume" (zvonek: neprectena oznameni v historii luxos-notify, org.xfce.Notifyd.Log)
#   status.state[druh]         {"icon", "tip", ...} pro listu; "" = polozku skryt
#   status.change_volume(d)    hlasitost +-d % (kolecko nad ikonou zvuku)
#   status.change_brightness(d)  jas +-d % (kolecko nad ikonou baterie)
#   status.next_layout(), status.switch_layout(i)   prepnuti rozlozeni klavesnice pres IPC luxwm
#                              (pod luxwm ukazuje aktivni rozlozeni z kompozitoru, jinak prvni z localed)
#   status.summary(druh)       kratky popis stavu (ladeni, testy)
load env
load glib, gio
load luxos_glib as lglib
load luxos_gio, gio as lgio
load luxos_i18n as i18n
load luxos_text as text
load luxos_luxwm as wm

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
UPOWER = "org.freedesktop.UPower"
DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
LOCALE = "org.freedesktop.locale1"
PROPS = "org.freedesktop.DBus.Properties"
# NMState: CONNECTING 40, CONNECTED_SITE 60 (luxos-netcheck); NMConnectivityState: 1 none, 2 portal, 3 limited
NM_CONNECTING = 40
NM_CONNECTED_SITE = 60

state = {
    "network": {"icon": "", "tip": "", "portal": False, "props": {}, "ap": {}, "id": ""},
    "sound": {"icon": "", "tip": "", "volume": -1, "muted": False},
    "battery": {"icon": "", "tip": "", "text": "", "props": {}},
    "keyboard": {"short": "", "tip": "", "layouts": [], "names": [], "current": 0, "caps": False},
    "notifications": {"icon": "notification-symbolic", "unread": False}
}
st = {"changed": None, "system": 0, "session": 0, "ap_path": "", "ap_sub": 0,
      "active_path": "", "active_sub": 0, "active_props": {}, "device_path": "", "device_sub": 0,
      "device_props": {}, "pactl_started": 0,
      "sound_armed": False, "sound_busy": False, "sound_again": False, "wm_keyboard": False}

function emit(kind):
    handler = st["changed"]
    if handler != None:
        call handler(kind)
    end
    return 0
end

function log(message):
    return eprint("luxos-bar: " + message)
end

function runtime_dir():
    value = env.get("XDG_RUNTIME_DIR", "")
    if value == "":
        return "/tmp"
    end
    return value
end

# Sbernice nemusi existovat (testy, zachranny rezim): 0 = bez ni
function bus(kind):
    value = 0
    safe:
        if kind == "system":
            value = gio.system_bus()
        else:
            value = gio.session_bus()
        end
    end
    if value == None:
        return 0
    end
    return value
end

# Vlastnosti objektu: GetAll a pak PropertiesChanged do stejneho slovniku; done(data) po kazde zmene
function watch_props(conn, name, path, interface, target, done, bound):
    sub = lgio.subscribe_data(conn, name, PROPS, "PropertiesChanged", path, interface, lgio.SIGNAL_NONE, on_props_changed,
                              [interface, target, done, bound])
    call lgio.call_async(conn, name, path, PROPS, "GetAll", [interface], "(s)", 5000, on_props_all, [target, done, bound])
    return sub
end

function on_props_all(ctx, values, error):
    if values == None:
        return 0
    end
    for key in values[0].keys():
        ctx[0][key] = values[0][key]
    end
    call ctx[1](ctx[2])
    return 0
end

function on_props_changed(ctx, sender, path, interface, signal, values):
    if len(values) < 2 or values[0] != ctx[0]:
        return 0
    end
    for key in values[1].keys():
        ctx[1][key] = values[1][key]
    end
    if len(values) > 2:
        for key in values[2]:
            call ctx[1].pop(key, None)
        end
    end
    call ctx[2](ctx[3])
    return 0
end

# ---- sit ---------------------------------------------------------------------------------------------

function nm_appeared(unused, name, owner):
    net = state["network"]
    if st.get("nm_sub", 0) == 0:
        st["nm_sub"] = watch_props(st["system"], NM, NM_PATH, NM, net["props"], network_changed, 0)
    else:
        call lgio.call_async(st["system"], NM, NM_PATH, PROPS, "GetAll", [NM], "(s)", 5000, on_props_all, [net["props"], network_changed, 0])
    end
    return 0
end

function nm_vanished(unused, name):
    net = state["network"]
    net["props"] = {}
    if st.get("nm_sub", 0) != 0:
        call gio.unsubscribe(st["system"], st["nm_sub"])
        st["nm_sub"] = 0
    end
    call follow_active("")
    call render_network()
    return 0
end

# Hlavni spojeni se zmenilo: nazev (Id) a u Wi-Fi pristupovy bod (sila signalu chodi jeho signalem)
function network_changed(unused):
    primary = state["network"]["props"].get("PrimaryConnection", "/")
    if primary != st.get("primary", ""):
        st["primary"] = primary
        state["network"]["id"] = ""
        call follow_active(primary)
    end
    call render_network()
    return 0
end

function follow_active(path):
    if path == st["active_path"]:
        return 0
    end
    if st["active_sub"] != 0:
        call gio.unsubscribe(st["system"], st["active_sub"])
        st["active_sub"] = 0
    end
    st["active_path"] = path
    st["active_props"] = {}
    call follow_device("")
    if path != "" and path != "/":
        st["active_sub"] = watch_props(st["system"], NM, path, NM + ".Connection.Active", st["active_props"], on_active_changed, path)
    end
    return 0
end

function on_active_changed(path):
    if path != st["active_path"]:
        return 0
    end
    props = st["active_props"]
    state["network"]["id"] = props.get("Id", "")
    if props.get("Type", "") == "802-11-wireless":
        devices = props.get("Devices", [])
        if len(devices) > 0:
            call follow_device(devices[0])
        else:
            call follow_ap(props.get("SpecificObject", ""))
        end
    else:
        call follow_device("")
    end
    call render_network()
    return 0
end

function follow_device(path):
    if path == st["device_path"]:
        return 0
    end
    if st["device_sub"] != 0:
        call gio.unsubscribe(st["system"], st["device_sub"])
        st["device_sub"] = 0
    end
    st["device_path"] = path
    st["device_props"] = {}
    call follow_ap("")
    if path != "" and path != "/":
        st["device_sub"] = watch_props(st["system"], NM, path, NM + ".Device.Wireless", st["device_props"], on_device_changed, path)
    end
    return 0
end

function on_device_changed(path):
    if path == st["device_path"]:
        call follow_ap(st["device_props"].get("ActiveAccessPoint", ""))
    end
    return 0
end

function follow_ap(path):
    if path == st["ap_path"]:
        return 0
    end
    if st["ap_sub"] != 0:
        call gio.unsubscribe(st["system"], st["ap_sub"])
        st["ap_sub"] = 0
    end
    st["ap_path"] = path
    state["network"]["ap"] = {}
    if path != "" and path != "/":
        st["ap_sub"] = watch_props(st["system"], NM, path, NM + ".AccessPoint", state["network"]["ap"], network_ap_changed, 0)
    end
    return 0
end

function network_ap_changed(unused):
    call render_network()
    return 0
end

function signal_icon(strength):
    if strength > 75:
        return "network-wireless-signal-excellent-symbolic"
    elif strength > 50:
        return "network-wireless-signal-good-symbolic"
    elif strength > 25:
        return "network-wireless-signal-ok-symbolic"
    elif strength > 0:
        return "network-wireless-signal-weak-symbolic"
    end
    return "network-wireless-signal-none-symbolic"
end

function render_network():
    net = state["network"]
    p = net["props"]
    old = [net["icon"], net["tip"], net["portal"]]
    net["portal"] = False
    if len(p) == 0:
        net["icon"] = ""
        net["tip"] = ""
    else:
        nm_state = p.get("State", 0)
        connectivity = p.get("Connectivity", 0)
        kind = p.get("PrimaryConnectionType", "")
        wifi = kind == "802-11-wireless"
        if nm_state >= NM_CONNECTED_SITE and (connectivity == 1 or connectivity == 2 or connectivity == 3):
            # jako luxos-netcheck: pripojeno, ale internet neni; portal hlasi NetworkManager nebo luxos-hub
            net["portal"] = connectivity == 2 or exists(runtime_dir() + "/luxos-portal")
            net["icon"] = "luxos-network-no-internet-symbolic"
            if net["portal"]:
                net["tip"] = i18n.T("Sign in to the network to use the internet (click to open the sign-in page)")
            else:
                net["tip"] = i18n.T("Connected to the network, but the internet is not available")
            end
        elif nm_state >= NM_CONNECTED_SITE and wifi:
            strength = net["ap"].get("Strength", 0)
            net["icon"] = signal_icon(strength)
            net["tip"] = i18n.T("Wi-Fi") + ": " + net["id"]
            if strength > 0:
                net["tip"] += " (" + String(strength) + "%)"
            end
        elif nm_state >= NM_CONNECTED_SITE:
            net["icon"] = "network-wired-symbolic"
            net["tip"] = net["id"]
            if net["tip"] == "":
                net["tip"] = i18n.T("Wired")
            end
        elif nm_state == NM_CONNECTING:
            net["icon"] = "network-wireless-acquiring-symbolic"
            net["tip"] = i18n.T("Connecting…")
        elif p.get("WirelessEnabled", True):
            net["icon"] = "network-wireless-offline-symbolic"
            net["tip"] = i18n.T("Not connected")
        else:
            net["icon"] = "network-wireless-disabled-symbolic"
            net["tip"] = i18n.T("Wi-Fi is off")
        end
    end
    if old != [net["icon"], net["tip"], net["portal"]]:
        call emit("network")
    end
    return 0
end

function on_portal_file(path, event, other):
    call render_network()
    return 0
end

# ---- baterie -----------------------------------------------------------------------------------------

function upower_appeared(unused, name, owner):
    bat = state["battery"]
    if st.get("upower_sub", 0) == 0:
        st["upower_sub"] = watch_props(st["system"], UPOWER, DISPLAY_DEVICE, UPOWER + ".Device", bat["props"], render_battery, 0)
    else:
        call lgio.call_async(st["system"], UPOWER, DISPLAY_DEVICE, PROPS, "GetAll", [UPOWER + ".Device"], "(s)", 5000,
                             on_props_all, [bat["props"], render_battery, 0])
    end
    return 0
end

function upower_vanished(unused, name):
    state["battery"]["props"] = {}
    call render_battery(0)
    return 0
end

function duration(seconds):
    mins = seconds // 60
    if mins >= 60:
        return String(mins // 60) + " h " + String(mins % 60) + " min"
    end
    return String(mins) + " min"
end

# Ikona, text a popis jako luxos-battery (genmon); UPower State: 1 nabiji, 2 vybiji, 4 nabito, 5 ceka na nabijeni
function render_battery(unused):
    bat = state["battery"]
    p = bat["props"]
    old = [bat["icon"], bat["text"], bat["tip"]]
    if not p.get("IsPresent", False) or p.get("Type", 0) != 2:
        bat["icon"] = ""
        bat["text"] = ""
        bat["tip"] = ""
    else:
        cap = Int(p.get("Percentage", 0.0) + 0.5)
        st_code = p.get("State", 0)
        icon = "battery-level-" + String((cap + 5) // 10 * 10)
        if st_code == 1:
            icon = icon + "-charging"
        end
        if st_code == 4 or (st_code == 5 and cap >= 95):
            icon = "battery-level-100-charged"
        end
        if st_code == 1:
            tip = i18n.T("Charging")
        elif st_code == 2:
            tip = i18n.T("On battery")
        else:
            tip = i18n.T("Fully charged")
        end
        empty = p.get("TimeToEmpty", 0)
        full = p.get("TimeToFull", 0)
        if st_code == 2 and empty > 60 and empty < 360000:
            tip = tip + " · " + i18n.TF("%s remaining", [duration(empty)])
        elif st_code == 1 and full > 60 and full < 360000:
            tip = tip + " · " + i18n.TF("%s until full", [duration(full)])
        end
        if exists(glib.user_config_dir() + "/luxos/powersaver"):
            tip = tip + " · " + i18n.T("Battery Saver")
        end
        bat["icon"] = icon + "-symbolic"
        bat["text"] = String(cap) + " %"
        bat["tip"] = String(cap) + " % · " + tip
    end
    if old != [bat["icon"], bat["text"], bat["tip"]]:
        call emit("battery")
    end
    return 0
end

# ---- zvuk ----------------------------------------------------------------------------------------------

function pactl_watch(unused):
    st["pactl_started"] = glib.monotonic_time()
    if lglib.spawn_stream(["env", "LC_ALL=C", "pactl", "subscribe"], on_pactl_events, 0) == 0:
        call sound_gone()
        return False
    end
    call refresh_sound()
    return False
end

# $XDG_RUNTIME_DIR/pulse/native (pipewire-pulse); adresar pulse nemusi jeste existovat
function wait_for_server():
    if st.get("pulse_monitor", 0) != 0:
        return 0
    end
    path = runtime_dir() + "/pulse"
    if not exists(path):
        path = runtime_dir()
    end
    st["pulse_dir"] = path
    st["pulse_monitor"] = gio.file_monitor(path, on_pulse_dir)
    return 0
end

function on_pulse_dir(path, event, other):
    if st.get("pulse_monitor", 0) == 0:
        return 0
    end
    if exists(runtime_dir() + "/pulse/native"):
        call gio.file_monitor_cancel(st["pulse_monitor"])
        st["pulse_monitor"] = 0
        call pactl_watch(0)
    elif st["pulse_dir"] == runtime_dir() and exists(runtime_dir() + "/pulse"):
        # vznikl adresar pulse: dal sledovat jeho obsah
        call gio.file_monitor_cancel(st["pulse_monitor"])
        st["pulse_monitor"] = 0
        call wait_for_server()
    end
    return 0
end

function sound_gone():
    snd = state["sound"]
    if snd["icon"] != "":
        snd["icon"] = ""
        snd["tip"] = ""
        snd["volume"] = -1
        call emit("sound")
    end
    return 0
end

function on_pactl_events(unused, chunk):
    if chunk == "":
        # zvukovy server skoncil nebo nebezi: znovu az se objevi jeho soket (inotify, zadne opakovani casovacem);
        # rychly konec hned po startu = server se restartuje, pak jednou za 5 s
        call sound_gone()
        if glib.monotonic_time() - st["pactl_started"] > 10000000:
            call lglib.timeout_add_seconds_data(5, pactl_watch, 0)
        else:
            call wait_for_server()
        end
        return 0
    end
    # davka udalosti (posuvnik hlasitosti jich posle desitky) -> jedno precteni
    if (chunk.find(" on sink #") >= 0 or chunk.find(" on server") >= 0) and not st["sound_armed"]:
        st["sound_armed"] = True
        call lglib.timeout_add_data(60, on_sound_settled, 0)
    end
    return 0
end

function on_sound_settled(unused):
    st["sound_armed"] = False
    call refresh_sound()
    return False
end

function refresh_sound():
    if st["sound_busy"]:
        st["sound_again"] = True
        return 0
    end
    st["sound_busy"] = True
    if lglib.spawn_capture(["env", "LC_ALL=C", "pactl", "get-sink-volume", "@DEFAULT_SINK@"], on_volume, 0) == 0:
        st["sound_busy"] = False
    end
    return 0
end

# "Volume: front-left: 26214 /  40% / -23.88 dB, ..." -> 40
function parse_volume(output):
    cut = output.find("%")
    if cut < 0:
        return -1
    end
    start = cut
    while start > 0 and text.is_digit(output[start - 1]):
        start -= 1
    end
    if start == cut:
        return -1
    end
    return Int(output[start:cut])
end

function on_volume(unused, output, status):
    state["sound"]["volume"] = parse_volume(output)
    if lglib.spawn_capture(["env", "LC_ALL=C", "pactl", "get-sink-mute", "@DEFAULT_SINK@"], on_mute, 0) == 0:
        st["sound_busy"] = False
    end
    return 0
end

function on_mute(unused, output, status):
    st["sound_busy"] = False
    snd = state["sound"]
    old = [snd["icon"], snd["tip"]]
    snd["muted"] = output.find("yes") >= 0
    v = snd["volume"]
    if v < 0:
        snd["icon"] = ""
        snd["tip"] = ""
    else:
        if snd["muted"] or v == 0:
            snd["icon"] = "audio-volume-muted-symbolic"
        elif v < 34:
            snd["icon"] = "audio-volume-low-symbolic"
        elif v < 67:
            snd["icon"] = "audio-volume-medium-symbolic"
        else:
            snd["icon"] = "audio-volume-high-symbolic"
        end
        snd["tip"] = i18n.T("Sound") + ": " + String(v) + " %"
        if snd["muted"]:
            snd["tip"] = i18n.T("Sound") + ": " + i18n.T("Muted")
        end
    end
    if old != [snd["icon"], snd["tip"]]:
        call emit("sound")
    end
    if st["sound_again"]:
        st["sound_again"] = False
        call refresh_sound()
    end
    return 0
end

function change_volume(delta):
    v = state["sound"]["volume"]
    if v < 0:
        return 0
    end
    target = max(0, min(100, v + delta))
    call set_volume(target)
    return 0
end

function set_volume(target):
    call glib.spawn_quiet(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
    call glib.spawn_quiet(["pactl", "set-sink-volume", "@DEFAULT_SINK@", String(target) + "%"])
    return 0
end

function change_brightness(delta):
    if delta > 0:
        call glib.spawn_quiet(["brightnessctl", "-q", "set", String(delta) + "%+"])
    else:
        call glib.spawn_quiet(["brightnessctl", "-q", "set", String(-delta) + "%-", "-n", "1"])
    end
    return 0
end

# ---- klavesnice: aktivni rozlozeni z luxwm (IPC), bez luxwm prvni rozlozeni z localed ----------------

function show_keyboard(codes, names, current, caps):
    kb = state["keyboard"]
    kb["layouts"] = codes
    kb["names"] = names
    kb["current"] = current
    kb["caps"] = caps
    kb["short"] = ""
    kb["tip"] = ""
    if current >= 0 and current < len(codes):
        kb["short"] = codes[current].upper()
        kb["tip"] = i18n.T("Keyboard") + ": " + names[current]
    end
    if caps:
        kb["tip"] = kb["tip"] + " – Caps Lock"
    end
    call emit("keyboard")
    return 0
end

function locale_changed(props):
    if st["wm_keyboard"]:
        return 0
    end
    codes = []
    for part in props.get("X11Layout", "").split(","):
        if part.strip() != "":
            codes.append(part.strip())
        end
    end
    call show_keyboard(codes, codes, 0, False)
    return 0
end

function locale_appeared(unused, name, owner):
    if st.get("locale_sub", 0) == 0:
        props = {}
        st["locale_props"] = props
        st["locale_sub"] = watch_props(st["system"], LOCALE, "/org/freedesktop/locale1", LOCALE, props, locale_changed, props)
    end
    return 0
end

function locale_vanished(unused, name):
    return 0
end

function on_wm(event):
    if event["event"] != "keyboard":
        return 0
    end
    codes = []
    names = []
    for item in event["layouts"]:
        codes.append(item["code"])
        names.append(item["name"])
    end
    current = event["current"]
    caps = event.get("caps", False) == True
    kb = state["keyboard"]
    same = st["wm_keyboard"] and kb["current"] == current and kb["caps"] == caps and len(kb["layouts"]) == len(codes)
    if same:
        index = 0
        while index < len(codes):
            if kb["layouts"][index] != codes[index] or kb["names"][index] != names[index]:
                same = False
                break
            end
            index += 1
        end
    end
    st["wm_keyboard"] = True
    if same:
        return 0
    end
    call show_keyboard(codes, names, current, caps)
    return 0
end

# luxwm skoncil: do jeho navratu aspon rozlozeni z localed
function on_wm_state(up):
    if not up and st["wm_keyboard"]:
        st["wm_keyboard"] = False
        call locale_changed(st.get("locale_props", {}))
    end
    return 0
end

function next_layout():
    call wm.request({"cmd": "next_layout"}, None)
    return 0
end

function switch_layout(index):
    call wm.request({"cmd": "switch_layout", "index": index}, None)
    return 0
end

# ---- oznameni a probuzeni ------------------------------------------------------------------------

function notes_appeared(unused, name, owner):
    call refresh_unread()
    return 0
end

function notes_vanished(unused, name):
    call show_unread(False)
    return 0
end

function on_log_changed(unused, sender, path, interface, signal, values):
    call refresh_unread()
    return 0
end

function refresh_unread():
    call lgio.call_async(st["session"], "org.xfce.Notifyd", "/org/xfce/Notifyd", "org.xfce.Notifyd.Log", "HasUnread", [], "",
                         3000, on_unread, 0)
    return 0
end

function on_unread(unused, values, error):
    call show_unread(values != None and len(values) > 0 and values[0] == True)
    return 0
end

function show_unread(unread):
    notes = state["notifications"]
    if unread == notes["unread"]:
        return 0
    end
    notes["unread"] = unread
    notes["icon"] = "notification-symbolic"
    if unread:
        notes["icon"] = "notification-new-symbolic"
    end
    call emit("notifications")
    return 0
end

function on_sleep(sender, path, interface, signal, values):
    if len(values) > 0 and values[0] == False:
        call emit("resume")
    end
    return 0
end

# ---- souhrn -------------------------------------------------------------------------------------------

function summary(kind):
    if kind == "battery":
        return state["battery"]["icon"] + " " + state["battery"]["text"]
    elif kind == "keyboard":
        return state["keyboard"]["short"] + (" caps" if state["keyboard"]["caps"] else "")
    elif kind in state:
        return state[kind]["icon"]
    end
    return ""
end

function start(handler):
    st["changed"] = handler
    st["system"] = bus("system")
    st["session"] = bus("session")
    if st["system"] != 0:
        call lgio.watch_name_data(st["system"], NM, nm_appeared, nm_vanished, 0)
        # UPower a locale1 se spousti az na pozadani (D-Bus aktivace): bez auto-startu by se nikdy neobjevily
        call lgio.watch_name_flags_data(st["system"], UPOWER, lgio.WATCH_AUTO_START, upower_appeared, upower_vanished, 0)
        call lgio.watch_name_flags_data(st["system"], LOCALE, lgio.WATCH_AUTO_START, locale_appeared, locale_vanished, 0)
        call gio.subscribe_values(st["system"], "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                                  "/org/freedesktop/login1", on_sleep)
    end
    if st["session"] != 0:
        call lgio.watch_name_data(st["session"], "org.xfce.Notifyd", notes_appeared, notes_vanished, 0)
        call lgio.subscribe_data(st["session"], "org.xfce.Notifyd", "org.xfce.Notifyd.Log", "", "/org/xfce/Notifyd", "",
                                 lgio.SIGNAL_NONE, on_log_changed, 0)
    end
    call pactl_watch(0)
    # portal nalezeny luxos-hub (NetworkManager pod Tailscale/VPN DNS hlasi jen "omezene"): ikona a klik hned,
    # ne az pri dalsi zmene stavu NetworkManageru
    st["portal_monitor"] = gio.file_monitor(runtime_dir() + "/luxos-portal", on_portal_file)
    call wm.on_state(on_wm_state)
    call wm.subscribe(["keyboard"])
    call wm.connect(on_wm)
    return 0
end
