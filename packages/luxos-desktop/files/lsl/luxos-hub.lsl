# LuxOS - jeden lehky proces relace misto nekolika samostatnych procesu na pozadi (prepis luxos-hub,
# luxos-control-center a luxos-calendar z Pythonu do LSL; jeden program, tri jmena).
#
# Drzi v pameti skryte okno Ovladaciho centra a Kalendare, aby se po kliknuti v liste ukazaly okamzite,
# a k tomu hlida udalosti, ktere driv obstaravaly samostatne smycky:
#   SIGUSR1           prepne Ovladaci centrum (luxos-cc-toggle)
#   SIGUSR2           prepne Kalendar (luxos-calendar-toggle)
#   Trezor            zamkne pri zamceni obrazovky a pred uspanim (luxos-safe lock --force)
#   Sporic dat        nove pripojena sit se hned oznaci jako merena
#   Pamet             upozorneni, kdyz pojistka earlyoom ukonci program (nedostatek pameti)
#   Fork bomba        upozorneni, kdyz pojistka luxos-forkguard zastavi program s tisici procesy
#   Internet          "!" v liste a upozorneni, kdyz je sit bez internetu (luxos-netcheck); sit
#                     s portalem (hotel, letiste): okno pro prihlaseni (luxos-network-login)
#   Bluetooth         agent pro parovani z telefonu a sluchatek (misto blueman-applet)
#   Zvuk              nove pripojeny monitor (HDMI/DisplayPort), USB a Bluetooth -> vychozi vystup,
#                     po odpojeni zpet (luxos_audio_hub + luxos_audio_switch.py)
#   Svetly/tmavy      automaticky rezim podle vychodu a zapadu slunce
#   Prehravani        pri hrajici hudbe/videu neuspava (ani zavreny vik), viz luxos_awake
#   Ovladace          jednou za start upozorneni na chybejici ovladace (luxos-drivers)
#   Firewall          program, ktery chce prijimat spojeni ze site a firewall ho zablokoval: Povolit /
#                     Nechat blokovane (luxos_firewall_hub + luxos-firewall-watch.service)
#   Zmena casu        vecer pred prechodem na letni/zimni cas a rano po nem (luxos_timechange)
#   Tapeta            tapeta plochy i na prihlasovaci obrazovce (luxos-appearance greeter-sync)
#   Grafika           rezim Vykon: hry a narocne aplikace na samostatne grafice (luxos_gpu_hub + luxos-gpu)
#   Snimek obrazovky  lista a okna luxos-screenshot (luxos_shot) pripravena predem; klient luxos-screenshot
#                     preda prepinace pres abstraktni socket UNIX, lista je videt hned po zkratce
#   Emoji a symboly   okno vyberu emoji (luxos_emoji) s nactenymi daty pripravene predem; klient luxos-emoji
#                     (Super+., Ctrl+Super+Mezernik) preda pozadavek stejne jako snimek obrazovky
#
# Stejny program bezi i jako `luxos-control-center [--panel|--background]` a `luxos-calendar [--background]`
# (podle nazvu, pod kterym byl spusten): bezici instance (hub nebo samostatna) jen dostane signal.
# Vsechno je rizene udalostmi (D-Bus, signaly); casovace jsou jen kontrola automatickeho vzhledu jednou
# za 5 minut a zmeny casu dvakrat denne, bez spousteni dalsich procesu.
load env, fd
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys
load luxos_text as text
load luxos_mpris as mpris
load luxos_cc as cc
load luxos_cal as cal
load luxos_sun as sun
load luxos_awake as awake
load luxos_bt_agent as agent
load luxos_care_hub as care
load luxos_drivers_hub as drivers
load luxos_firewall_hub as firewall
load luxos_safe_hub as safe
load luxos_timechange as timechange
load luxos_shot as shot
load luxos_emoji as emoji
load luxos_audio_hub as audio
load luxos_gpu_hub as gpu

SIGINT = 2
SIGUSR1 = 10
SIGUSR2 = 12
SIGTERM = 15
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
# Kontrola portalu (luxos-portal-check) hned a po techto sekundach, dokud je pripojeni omezene;
# konci prvnim nalezenym portalem nebo internetem
PORTAL_PROBE_DELAYS = [3, 6, 10, 15, 25, 40, 60, 90, 120]
PORTAL_PROBES = 10
# Pripominka prihlaseni (upozorneni), kdyz je sit porad za portalem a okno je zavrene: po 5 min,
# pak vzdy dvojnasobek (nejvys 1 h) - zadna smycka oken ani upozorneni
PORTAL_REMIND = 300
PORTAL_REMIND_MAX = 3600
# Stav portalu pro luxos-netcheck, Ovladaci centrum a luxos-network-login ($XDG_RUNTIME_DIR):
# soubor existuje, dokud je sit za portalem; obsah "URL IP" z luxos-portal-check nebo prazdny
PORTAL_STATE = "luxos-portal"

hub = {"session": 0, "system": 0, "plugin": "", "connectivity": None, "awake": False, "pidfiles": [], "windows": False, "portal_pid": 0, "portal_found": False, "portal_url": "", "portal_probes": 0, "portal_note": 0, "portal_gen": 0, "portal_delay": 0, "cover_pid": 0, "start": 0, "noinet_timer": False, "exit": 0, "update_seen": 0, "wm_pid": 0, "wm_seen": 0, "wm_replaced": 0}

function runtime_dir():
    value = env.get("XDG_RUNTIME_DIR", "")
    if value == None or value == "":
        return "/tmp"
    end
    return value
end

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function log(message):
    return eprint("luxos-hub: " + message)
end

# Vystup programu (stripped) nebo None pri chybe/nenulovem kodu (jako run() v Pythonu)
function cmd_output(argv):
    program = glib.find_program_in_path(argv[0])
    if program == "":
        return None
    end
    out = ""
    ok = True
    try:
        out = capture(program, argv[1:])
    else:
        ok = False
    end
    if not ok or capture_status() != 0:
        return None
    end
    return out.strip()
end

# ---- debounce: volani f nejdriv po ms od posledni udalosti (davky signalu -> jedna akce) ------------------

function debounce_new(ms, handler):
    return {"ms": ms, "handler": handler, "id": 0}
end

function debounce_trigger(d):
    if d["id"] != 0:
        call glib.source_remove(d["id"])
    end
    d["id"] = glib.timeout_add_data(d["ms"], debounce_fire, d)
    return 0
end

function debounce_fire(d):
    d["id"] = 0
    handler = d["handler"]
    call handler()
    return False
end

# ---- Internet nedostupny: "!" v liste (luxos-netcheck) a jedno upozorneni ---------------------------------

function panel_xfconf(args):
    argv = ["xfconf-query", "-c", "xfce4-panel"]
    argv.extend(args)
    return cmd_output(argv)
end

# Id pluginu genmon s luxos-netcheck; starsim profilum ho jednou prida vedle ikon (systray)
function netcheck_plugin():
    props = panel_xfconf(["-l", "-p", "/plugins"])
    if props == None:
        props = ""
    end
    for prop in props.split("\n"):
        if prop.endswith("/command"):
            command = panel_xfconf(["-p", prop])
            if command != None and command.startswith("luxos-netcheck"):
                return prop.split("/")[2].split("-")[1]
            end
        end
    end
    mark = config_dir() + "/netcheck-added"
    if exists(mark):
        return ""                      # uzivatel ho z listy odebral
    end
    ids = []
    tray = ""
    for p in props.split("\n"):
        if p.count("/") == 2 and p.startswith("/plugins/plugin-"):
            ids.append(text.to_int(p.split("-")[1], 0))
            if tray == "" and panel_xfconf(["-p", p]) == "systray":
                tray = p.split("-")[1]
            end
        end
    end
    if len(ids) == 0 or tray == "":
        return ""
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
        order = []
        for v in raw.split("\n"):
            for part in v.split(" "):
                if text.is_digits(part):
                    order.append(part)
                end
            end
        end
        if tray not in order:
            continue
        end
        order.insert(order.index(tray) + 1, new)
        base = "/plugins/plugin-" + new
        call panel_xfconf(["-p", base, "-n", "-t", "string", "-s", "genmon"])
        call panel_xfconf(["-p", base + "/command", "-n", "-t", "string", "-s", "luxos-netcheck"])
        call panel_xfconf(["-p", base + "/update-period", "-n", "-t", "int", "-s", "86400000"])
        call panel_xfconf(["-p", base + "/use-label", "-n", "-t", "bool", "-s", "false"])
        call panel_xfconf(["-p", base + "/enable-single-row", "-n", "-t", "bool", "-s", "true"])
        args = ["-p", panel, "--force-array"]
        for v in order:
            args.append("-t")
            args.append("int")
            args.append("-s")
            args.append(v)
        end
        call panel_xfconf(args)
        call glib.mkdir_p(config_dir())
        call writefile(mark, "")
        call glib.spawn(["xfce4-panel", "-r"])
        return new
    end
    return ""
end

function connectivity():
    value = None
    try:
        value = gio.get_property_value(hub["system"], NM, NM_PATH, NM, "Connectivity")
    else:
        value = None
    end
    return value
end

function panel_refresh():
    if hub["plugin"] == "":
        hub["plugin"] = netcheck_plugin()
    end
    if hub["plugin"] != "":
        safe:
            call gio.call_values(hub["session"], "org.xfce.Panel", "/org/xfce/Panel", "org.xfce.Panel", "PluginEvent", ["genmon-" + hub["plugin"], "refresh", ["b", True]], "(ssv)", 2000)
        end
    end
    return 0
end

function connectivity_update():
    c = connectivity()
    start_probe = False
    # 2 = prihlaseni do site (portal), 3 = bez internetu, 4 = internet; jedno upozorneni na kazdou zmenu
    last = hub["connectivity"]
    restored = False
    if last == None and (c == 2 or c == 3):
        restored = portal_restore()
    end
    if restored:
        call log("portal: still signing in (after restart)")
    elif c == 2 and last != 2 and not hub["portal_found"]:
        call portal_detected("")
    elif c == 3 and not (last == 2 or last == 3):
        call noinet_schedule()
        # Portal, ktery NetworkManager neprozna (systemove DNS pres VPN/Tailscale za portalem nefunguje):
        # vlastni kontrola pres DNS a branu site hned a pak opakovane 2 minuty (prihlasovaci brana
        # nekdy nabiha pomalu, napr. Wi-Fi ve vlaku)
        start_probe = True
    end
    if c != 3 and c != 2 and last == 3:
        hub["portal_probes"] = PORTAL_PROBES
    end
    if c == 4 and last != 4:
        # internet: okno portalu uz neni potreba (i rucne otevrene z listy nebo Ovladaciho centra)
        call portal_close_window()
        if last == 2 or hub["portal_found"]:
            call glib.spawn(["notify-send", "-a", "LuxOS", "-e", "-i", "network-wireless-symbolic", i18n.T("Connected to the internet"), i18n.T("You are signed in to the network.")])
        end
    end
    if c != 2 and c != 3:
        if hub["portal_found"] or exists(portal_state_path()):
            call portal_clear()
        end
        hub["portal_found"] = False
        hub["portal_url"] = ""
    end
    hub["connectivity"] = c
    call panel_refresh()
    if start_probe:
        hub["portal_probes"] = 0
        call portal_probe()
        for d in PORTAL_PROBE_DELAYS:
            call glib.timeout_add_seconds(d, portal_probe)
        end
    end
    return False
end

# Sit s portalem: prihlasovaci stranka se otevre sama, jednou za kazde prihlaseni do site
# (cizi sit tak nemuze otevirat okna porad dokola). Zavrenim okna se portal neoznaci jako vyrizeny:
# dokud neni internet, zustava "Prihlasit se" v liste (luxos-netcheck), v Ovladacim centru a v
# upozorneni (pripominka po PORTAL_REMIND s, kdyz je okno zavrene).
function portal_detected(url):
    hub["portal_found"] = True
    hub["portal_url"] = url
    hub["portal_delay"] = 0
    call portal_save()
    call panel_refresh()
    call portal_open()
    call portal_notify()
    return 0
end

function portal_active():
    return hub["portal_found"] or hub["connectivity"] == 2
end

function portal_state_path():
    return runtime_dir() + "/" + PORTAL_STATE
end

function portal_save():
    safe:
        call glib.write_atomic(portal_state_path(), hub["portal_url"] + "\n")
    end
    return 0
end

# luxos-hub spusten znovu (aktualizace, pad) za portalem: stav ze souboru, okno se znovu samo neotevre
function portal_restore():
    path = portal_state_path()
    if not exists(path):
        return False
    end
    hub["portal_found"] = True
    hub["portal_url"] = glib.read_text(path).strip()
    hub["portal_delay"] = 0
    call portal_remind_later()
    return True
end

# Internet nebo odpojeno: pryc soubor stavu, upozorneni i cekajici pripominka
function portal_clear():
    hub["portal_gen"] = hub["portal_gen"] + 1
    hub["portal_delay"] = 0
    call glib.unlink(portal_state_path())
    if hub["portal_note"] != 0 and hub["session"] != 0:
        call gio.call_async(hub["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "CloseNotification", [hub["portal_note"]], "(u)", 5000, on_portal_note_closed, 0)
    end
    hub["portal_note"] = 0
    return 0
end

function on_portal_note_closed(unused, values, error):
    return 0
end

# Jedno upozorneni s tlacitkem "Prihlasit se" (nahrazuje predchozi); zustava, dokud ho uzivatel nezavre
function portal_notify():
    if hub["session"] == 0:
        return 0
    end
    # jen "default": xfce4-notifyd ji ukaze jako tlacitko a vyvola ji i klik na upozorneni
    actions = ["default", i18n.T("Sign In")]
    call gio.call_async(hub["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        ["LuxOS", hub["portal_note"], "luxos-network-no-internet-symbolic", i18n.T("Sign in to the network"), i18n.T("This network requires you to sign in before you can use the internet."), actions, {"category": ["s", "network"]}, 0],
                        "(susssasa{sv}i)", 5000, on_portal_notified, 0)
    return 0
end

function on_portal_notified(unused, values, error):
    if values == None:
        call log("portal notify: " + error)
        return 0
    end
    hub["portal_note"] = values[0]
    if not portal_active():
        call portal_clear()            # mezitim prihlaseno
    end
    return 0
end

function on_notification_action(sender, path, interface, signal, values):
    if len(values) < 2 or hub["portal_note"] == 0 or values[0] != hub["portal_note"]:
        return 0
    end
    if (values[1] == "login" or values[1] == "default") and portal_active():
        call portal_open()
    end
    return 0
end

function on_notification_closed(sender, path, interface, signal, values):
    if len(values) < 1 or hub["portal_note"] == 0 or values[0] != hub["portal_note"]:
        return 0
    end
    hub["portal_note"] = 0
    call portal_remind_later()
    return 0
end

# Pripominka za hub["portal_delay"] s; novejsi naplanovani rusi starsi (cislo generace)
function portal_remind_later():
    if not portal_active():
        return 0
    end
    if hub["portal_delay"] == 0:
        hub["portal_delay"] = text.to_int(env.get("LUXOS_HUB_PORTAL_REMIND", ""), PORTAL_REMIND)
    end
    hub["portal_gen"] = hub["portal_gen"] + 1
    call glib.timeout_add_seconds_data(hub["portal_delay"], portal_remind, hub["portal_gen"])
    return 0
end

function portal_remind(gen):
    if gen != hub["portal_gen"] or not portal_active() or hub["portal_note"] != 0 or portal_window_open():
        return False
    end
    delay = hub["portal_delay"] * 2
    if delay > PORTAL_REMIND_MAX:
        delay = PORTAL_REMIND_MAX
    end
    hub["portal_delay"] = delay
    call portal_notify()
    return False
end

# luxos-portal-check: "portal URL IP" / "online" / "none"; jen dokud je pripojeni porad omezene
function portal_probe():
    if hub["portal_probes"] >= PORTAL_PROBES or hub["portal_found"] or hub["connectivity"] != 3:
        return False
    end
    hub["portal_probes"] = hub["portal_probes"] + 1
    call glib.spawn_capture(["luxos-portal-check"], on_portal_probe, 0)
    return False
end

function on_portal_probe(bound, output, status):
    words = output.strip().split(" ")
    if len(words) >= 2 and words[0] == "portal" and hub["connectivity"] == 3 and not hub["portal_found"]:
        url = words[1]
        if len(words) >= 3:
            url = url + " " + words[2]
        end
        call portal_detected(url)
    end
    return 0
end

# "Bez internetu" az kdyz stav trva: po prihlaseni NetworkManager chvili hlasi omezene pripojeni,
# nez Wi-Fi dobehne (falesne upozorneni pri kazdem prihlaseni). Upozorni se jen, kdyz je stav 3
# porad i po LUXOS_HUB_NOINET_DELAY s (60; po probuzeni Wi-Fi dobiha dele) a nejdriv LUXOS_HUB_NOINET_GRACE s (45) po startu.
function noinet_schedule():
    if hub["noinet_timer"]:
        return 0
    end
    delay = text.to_int(env.get("LUXOS_HUB_NOINET_DELAY", ""), 60)
    left = text.to_int(env.get("LUXOS_HUB_NOINET_GRACE", ""), 45) - (glib.now() - hub["start"])
    if left > delay:
        delay = left
    end
    hub["noinet_timer"] = True
    call glib.timeout_add_seconds(delay, noinet_check)
    return 0
end

function noinet_check():
    hub["noinet_timer"] = False
    if hub["connectivity"] == 3 and connectivity() == 3 and not hub["portal_found"]:
        # -e: prechodne (stav je videt na ikone site), do historie oznameni nepatri
        call glib.spawn(["notify-send", "-a", "LuxOS", "-e", "-i", "luxos-network-no-internet-symbolic", i18n.T("No internet connection"), i18n.T("You are connected to the network, but the internet is not available.")])
    end
    return False
end

# ---- konec relace ------------------------------------------------------------------------------------------------
# xfce4-session: 3 = SHUTDOWN (programy se jeste mohou ptat na ulozeni), 4 = SHUTDOWNPHASE2 (konci).
# luxos-session-cover se pripravi hned, zatmi az pri 4 nebo po konci kompozitoru.
function on_session_state(sender, path, interface, signal, values):
    if len(values) < 2:
        return 0
    end
    state = values[1]
    if state == 3 and hub["cover_pid"] == 0:
        hub["cover_pid"] = glib.spawn_watched_data(["luxos-session-cover"], on_cover_closed, 0)
    elif state == 4:
        if hub["cover_pid"] == 0:
            hub["cover_pid"] = glib.spawn_watched_data(["luxos-session-cover"], on_cover_closed, 0)
        end
        if hub["cover_pid"] != 0:
            call glib.kill(hub["cover_pid"], SIGUSR1)
        end
    elif state < 3:
        call on_session_cancelled(sender, path, interface, signal, values)
    end
    return 0
end

function on_session_cancelled(sender, path, interface, signal, values):
    if hub["cover_pid"] != 0:
        call glib.kill(hub["cover_pid"], SIGTERM)
        hub["cover_pid"] = 0
    end
    return 0
end

function on_cover_closed(bound, pid, status):
    if hub["cover_pid"] == pid:
        hub["cover_pid"] = 0
    end
    return 0
end

# Okno pro prihlaseni do site s portalem: jednorazovy profil prohlizece bez dat uzivatele.
# luxos-network-login bezi jen jednou: dalsi spusteni (lista, Ovladaci centrum) jen zvedne okno.
function portal_open():
    if hub["portal_pid"] != 0 or env.get("LUXOS_HUB_NO_PORTAL", "") == "1":
        return 0
    end
    argv = ["luxos-network-login"]
    if hub["portal_url"] != "":
        argv = argv + hub["portal_url"].split(" ")      # adresa a IP portalu z luxos-portal-check
    end
    hub["portal_pid"] = glib.spawn_watched_data(argv, on_portal_closed, 0)
    return 0
end

# Okno zavrene bez prihlaseni: portal trva dal, pripomene se upozornenim
function on_portal_closed(bound, pid, status):
    if hub["portal_pid"] == pid:
        hub["portal_pid"] = 0
        call portal_remind_later()
    end
    return 0
end

# I okno spustene rucne (lista, Ovladaci centrum, prikaz): pid soubor luxos-network-login
function login_window_pid():
    return running_pid("luxos-network-login.pid", ["luxos-network-login"])
end

function portal_window_open():
    return hub["portal_pid"] != 0 or login_window_pid() != 0
end

function portal_close_window():
    if hub["portal_pid"] != 0:
        call glib.kill(hub["portal_pid"], SIGTERM)
        hub["portal_pid"] = 0
    end
    pid = login_window_pid()
    if pid != 0:
        call glib.kill(pid, SIGTERM)
    end
    return 0
end

connectivity_refresh = None

function on_nm_props(sender, path, interface, signal, values):
    if len(values) < 2:
        return 0
    end
    changed = values[1]
    if values[0] == NM and type(changed) == "Dictionary":
        if "Connectivity" in changed or "State" in changed:
            call debounce_trigger(connectivity_refresh)
        end
        if "ActiveConnections" in changed:
            call debounce_trigger(networks_reapply)
        end
    end
    return 0
end

function watch_connectivity():
    global connectivity_refresh, networks_reapply
    connectivity_refresh = debounce_new(1000, connectivity_update)
    networks_reapply = debounce_new(2000, reapply_datasaver)
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_HUB_NETCHECK_DELAY", ""), 8), connectivity_update)   # po prihlaseni (panel uz bezi)
    call gio.subscribe_values(hub["system"], NM, "org.freedesktop.DBus.Properties", "PropertiesChanged", NM_PATH, on_nm_props)
    if hub["session"] != 0:
        call gio.subscribe_values(hub["session"], "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_notification_action)
        call gio.subscribe_values(hub["session"], "org.freedesktop.Notifications", "org.freedesktop.Notifications", "NotificationClosed", "/org/freedesktop/Notifications", on_notification_closed)
    end
    return 0
end

# ---- Sporic dat: merene pripojeni i pro nove pripojene site ---------------------------------------------

networks_reapply = None

function reapply_datasaver():
    if exists(config_dir() + "/datasaver"):
        call glib.spawn(["luxos-datasaver", "reapply"])
    end
    return False
end

# ---- Nedostatek pameti: upozorneni od pojistky earlyoom (luxos-tweaks) --------------------------------------

memory_last = {"name": "", "t": 0}

# "process 1234 firefox." -> "firefox" (regex process (\d+) (.+?)(?:[.,;]|$))
function process_name(message):
    hit = message.find("process ")
    while hit >= 0:
        rest = message[hit + 8:]
        i = 0
        while i < len(rest) and text.is_digit(rest[i]):
            i += 1
        end
        if i > 0 and i < len(rest) and rest[i] == " ":
            name = rest[i + 1:]
            j = 0
            while j < len(name) and name[j] != "." and name[j] != "," and name[j] != ";":
                j += 1
            end
            return name[0:j].strip()
        end
        hit = message.find("process ", hit + 8)
    end
    return ""
end

function on_low_memory(sender, path, interface, signal, values):
    parts = []
    for v in values:
        parts.append(String(v))
    end
    name = process_name(text.join(parts, " "))
    # davka signalu pri jednom zasahu -> jedno upozorneni
    now = glib.monotonic_time()
    if memory_last["name"] == name and now - memory_last["t"] < 10000000:
        return 0
    end
    memory_last["name"] = name
    memory_last["t"] = now
    body = i18n.T("A program used too much memory and was closed so the computer would not freeze.")
    if name != "":
        body = i18n.TF("“%s” used too much memory and was closed so the computer would not freeze.", [name])
    end
    call glib.spawn(["notify-send", "-a", "LuxOS", "-u", "critical", "-i", "dialog-warning", i18n.T("Memory is running low"), body])
    return 0
end

# ---- Fork bomba: upozorneni od pojistky luxos-forkguard (systemova sluzba, luxos-desktop) -------------------
# Signal cz.luxos.ForkGuard.Stopped (jmeno procesu, pocet ukoncenych, UID) - jen pro tohoto uzivatele.

function on_fork_bomb(sender, path, interface, signal, values):
    if len(values) < 3 or values[2] != luxos_sys.getuid():
        return 0
    end
    body = i18n.TF("“%s” started thousands of processes and was stopped so the computer would not freeze.", [String(values[0])])
    call glib.spawn(["notify-send", "-a", "LuxOS", "-u", "critical", "-i", "dialog-warning", i18n.T("Runaway program stopped"), body])
    return 0
end

# ---- Automaticky svetly/tmavy rezim ----------------------------------------------------------------------------

function appearance_check():
    prefs = text.parse_kv(glib.read_text(config_dir() + "/appearance.conf"))
    if prefs.get("APPEARANCE_AUTO") != "1":
        return True
    end
    want = ""
    try:
        want = sun.mode()
    else:
        call log("sun: " + String(last_error()))
        return True
    end
    current = "light"
    if glib.read_text(config_dir() + "/appearance").strip() == "dark":
        current = "dark"
    end
    if want != current:
        call glib.spawn(["luxos-appearance", "auto"])
    end
    return True
end

function appearance_check_once():
    call appearance_check()
    return False
end

function on_sleep(sender, path, interface, signal, values):
    # Po probuzeni (vecer otevreny notebook) hned zkontrolovat vzhled
    if len(values) > 0 and values[0] == False:
        call glib.timeout_add_seconds(3, appearance_check_once)
        call glib.timeout_add_seconds(5, timechange_check_once)
    end
    return 0
end

function timechange_check_once():
    try:
        call timechange.check()
    else:
        call log("time change: " + String(last_error()))
    end
    return False
end

# ---- Tapeta prihlasovaci obrazovky ---------------------------------------------------------------------------
# Zmena tapety plochy (Plocha a Dock, nastaveni plochy Xfce, svetly/tmavy rezim) -> stejna tapeta
# na prihlasovaci obrazovce a pri prepnuti uzivatele (luxos-appearance greeter-sync, AccountsService).
# Jedna davka zmen (vsechny monitory a plochy) = jedno spusteni.

wallsync = {"debounce": 0}

function greeter_sync():
    call glib.spawn_quiet(["luxos-appearance", "greeter-sync"])
    return 0
end

function on_xfconf_changed(sender, path, interface, signal, values):
    if len(values) >= 2 and values[0] == "xfce4-desktop" and String(values[1]).endswith("/last-image"):
        call debounce_trigger(wallsync["debounce"])
    end
    return 0
end

function watch_wallpaper():
    wallsync["debounce"] = debounce_new(text.to_int(env.get("LUXOS_HUB_WALLSYNC_DELAY", ""), 2000), greeter_sync)
    call gio.subscribe_values(hub["session"], "org.xfce.Xfconf", "org.xfce.Xfconf", "PropertyChanged", "/org/xfce/Xfconf", on_xfconf_changed)
    return 0
end

# ---- okna a signaly ----------------------------------------------------------------------------------------------

function prebuild():
    call window_cc()
    call window_cal()
    call window_shot()
    call window_emoji()
    return False
end

# Okno Emoji a symbolu s daty (~2 MB) skryte predem: zkratka ho ukaze hned
function window_emoji():
    try:
        call emoji.prebuild()
    else:
        call log("emoji: " + String(last_error()))
    end
    return 0
end

# Okna Snimku obrazovky (lista, prekryv, nahled) skryta predem: zkratka je ukaze hned
function window_shot():
    try:
        call shot.prebuild()
    else:
        call log("screenshot: " + String(last_error()))
    end
    return 0
end

function window_cc():
    ok = True
    try:
        call cc.create()
    else:
        ok = False
        call log("cc: " + String(last_error()))
    end
    return ok
end

function window_cal():
    ok = True
    try:
        call cal.create(True)
    else:
        ok = False
        call log("cal: " + String(last_error()))
    end
    return ok
end

function on_sigusr1():
    try:
        call cc.toggle()
    else:
        call log("cc: " + String(last_error()))
        call glib.spawn(["luxos-control-center"])
    end
    return True
end

function on_sigusr2():
    try:
        call cal.toggle()
    else:
        call log("cal: " + String(last_error()))
        call glib.spawn(["luxos-calendar"])
    end
    return True
end

# SIGTERM/SIGINT (kill, konec relace): nenulovy kod - smycka v luxos-session hub spusti znovu, dokud
# bezi X (po odhlaseni uz ne); kod 0 by smycku ukoncil a sit, portal ani lista by se nehlidaly
function on_quit():
    if hub["exit"] == 0:
        hub["exit"] = 143
    end
    call gtk.main_quit()
    return False
end

function write_pidfiles(names):
    pid = String(glib.getpid())
    for name in names:
        path = runtime_dir() + "/" + name
        safe:
            call writefile(path, pid)
            hub["pidfiles"].append(path)
        end
    end
    return 0
end

function remove_pidfiles():
    pid = String(glib.getpid())
    for path in hub["pidfiles"]:
        if glib.read_text(path).strip() == pid:
            call glib.unlink(path)
        end
    end
    return 0
end

# PID bezici instance podle pid souboru, jejiz prikazova radka obsahuje nektere ze jmen; 0 kdyz nebezi
function running_pid(pidfile, names):
    raw = glib.read_text(runtime_dir() + "/" + pidfile).strip()
    if not text.is_digits(raw):
        return 0
    end
    cmdline = glib.read_text("/proc/" + raw + "/cmdline")
    for name in names:
        if cmdline.find(name) >= 0:
            return Int(raw)
        end
    end
    return 0
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function has_arg(flag):
    i = 1
    while i < arg_count():
        if arg(i) == flag:
            return True
        end
        i += 1
    end
    return False
end

# ---- hlavni program ------------------------------------------------------------------------------------------------

function main_hub():
    hub["start"] = glib.now()
    call write_pidfiles(["luxos-hub.pid", "luxos-control-center.pid", "luxos-calendar.pid"])
    # signaly hned po zapsani pid souboru (klik v liste behem startu by jinak proces ukoncil)
    call glib.unix_signal_add(SIGUSR1, on_sigusr1)
    call glib.unix_signal_add(SIGUSR2, on_sigusr2)
    call glib.unix_signal_add(SIGTERM, on_quit)
    call glib.unix_signal_add(SIGINT, on_quit)
    call glib.set_prgname("luxos-hub")
    call glib.set_application_name("LuxOS")
    call gtk.init()
    # Snimek obrazovky: pozadavky klienta luxos-screenshot (okna se postavi s ostatnimi, nebo pri prvnim pozadavku)
    try:
        call shot.start_server(False)
    else:
        call log("screenshot: " + String(last_error()))
    end
    # Emoji a symboly: pozadavky klienta luxos-emoji (okno se postavi s ostatnimi, nebo pri prvnim pozadavku)
    try:
        call emoji.start_server(False)
    else:
        call log("emoji: " + String(last_error()))
    end
    safe:
        hub["session"] = gio.session_bus()
    end
    try:
        hub["system"] = gio.system_bus()
    else:
        call log("system bus: " + String(last_error()))
    end

    # Skryta okna Ovladaciho centra a Kalendare: vytvorit az po usazeni relace (nebrzdi prihlaseni),
    # nebo hned pri prvnim kliknuti, prijde-li driv.
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_HUB_PREBUILD_DELAY", ""), 6), prebuild)

    # Trezor (balik luxos-safe): zamceni pri zamceni obrazovky a pred uspanim
    if glib.find_program_in_path("luxos-safe") != "":
        try:
            call safe.subscribe(hub["session"], hub["system"])
        else:
            call log("safe: " + String(last_error()))
        end
    end
    # LuxOS Care (balik luxos-care): upozorneni na aktualizace a opravy, volba opravy pres LuxAI
    if exists(care.helper_path()):
        try:
            call care.subscribe(hub["session"], hub["system"])
        else:
            call log("care: " + String(last_error()))
        end
    end
    # Ovladace (balik luxos-drivers): jednou za start upozorni na chybejici ovladace hardwaru
    if exists(drivers.helper_path()):
        try:
            call drivers.subscribe(hub["session"])
        else:
            call log("drivers: " + String(last_error()))
        end
    end
    # Firewall (balik luxos-firewall): zablokovany program, ktery posloucha -> Povolit / Nechat blokovane
    if firewall.available():
        try:
            call firewall.subscribe(hub["session"])
        else:
            call log("firewall: " + String(last_error()))
        end
    end

    # Zvuk: nove pripojeny monitor (HDMI/DisplayPort), USB a Bluetooth se stane vystupem, po odpojeni zpet
    if glib.find_program_in_path("pactl") != "" and exists(audio.helper_path()):
        try:
            call audio.subscribe()
        else:
            call log("audio: " + String(last_error()))
        end
    end

    # Odhlaseni/vypnuti: cerne zakryti misto oken s cernymi pruhy po konci kompozitoru
    if hub["session"] != 0:
        try:
            call gio.subscribe_values(hub["session"], "org.xfce.SessionManager", "org.xfce.Session.Manager", "StateChanged", "/org/xfce/SessionManager", on_session_state)
            call gio.subscribe_values(hub["session"], "org.xfce.SessionManager", "org.xfce.Session.Manager", "ShutdownCancelled", "/org/xfce/SessionManager", on_session_cancelled)
        else:
            call log("session state: " + String(last_error()))
        end
        # Tapeta plochy i na prihlasovaci obrazovce
        try:
            call watch_wallpaper()
        else:
            call log("wallpaper: " + String(last_error()))
        end
    end

    # Zmena casu (letni/zimni): upozorneni vecer pred ni a rano po ni
    try:
        call timechange.subscribe()
    else:
        call log("time change: " + String(last_error()))
    end

    if hub["system"] != 0:
        try:
            call watch_connectivity()
            call gio.subscribe_values(hub["system"], "", "net.nuetzlich.SystemNotifications", "Notify", "", on_low_memory)
            call gio.subscribe_values(hub["system"], "", "cz.luxos.ForkGuard", "Stopped", "/cz/luxos/ForkGuard", on_fork_bomb)
            call agent.watch(hub["system"])
            if hub["session"] != 0:
                call mpris.init(hub["session"])
                call awake.init(hub["session"], hub["system"])
                hub["awake"] = True
            end
            call gio.subscribe_values(hub["system"], "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", on_sleep)
        else:
            call log("system bus: " + String(last_error()))
        end
    end
    # Grafika podle rezimu napajeni (power-profiles-daemon): po prihlaseni a pri kazde zmene profilu
    try:
        call gpu.subscribe(hub["system"])
    else:
        call log("gpu: " + String(last_error()))
    end
    call glib.timeout_add_seconds(300, appearance_check)
    # Po aktualizaci baliku (lux update) se novy luxos-hub spusti sam: luxos-session ho restartuje
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_HUB_UPDATE_CHECK", ""), 60), update_check)

    call gtk.main()
    if hub["awake"]:
        call awake.shutdown()
    end
    call remove_pidfiles()
    return hub["exit"]
end

# Aktualizace nahradila /usr/bin/luxos-hub (/proc/self/exe ukazuje "(deleted)"): skoncit s kodem 75,
# smycka v luxos-session spusti novou verzi (opravy plati hned, bez odhlaseni). Az pri druhe kontrole
# po sobe, at se nekonci uprostred instalace baliku.
function update_check():
    link = ""
    safe:
        link = glib.readlink("/proc/self/exe")
    end
    if link.endswith(" (deleted)"):
        hub["update_seen"] = hub["update_seen"] + 1
        if hub["update_seen"] >= 2:
            call log("new version installed, restarting")
            hub["exit"] = 75
            call gtk.main_quit()
            return False
        end
    else:
        hub["update_seen"] = 0
    end
    call wm_update_check()
    return True
end

# Spravce oken xfwm4 tohoto uzivatele (cislo procesu; 0 = nebezi). Cizi procesy readlink neprecte.
# LUXOS_HUB_WM_NAME jen pro testy (jiny nazev procesu nez skutecny xfwm4).
function wm_pid():
    comm = env.get("LUXOS_HUB_WM_NAME", "xfwm4") + "\n"
    pid = hub["wm_pid"]
    if pid > 0 and glib.read_text("/proc/" + String(pid) + "/comm") == comm and glib.readlink("/proc/" + String(pid) + "/exe") != "":
        return pid
    end
    hub["wm_pid"] = 0
    for name in glib.list_dir("/proc"):
        if text.is_digits(name) and glib.read_text("/proc/" + name + "/comm") == comm and glib.readlink("/proc/" + name + "/exe") != "":
            hub["wm_pid"] = Int(name)
            return hub["wm_pid"]
        end
    end
    return 0
end

# Aktualizace nahradila /usr/bin/xfwm4 (balik xfwm4 z [luxos]: umisteni oken, Alt+`): bezici spravce
# oken se vymeni za novou verzi (xfwm4 --replace, okna i jejich pozice zustanou, jako luxos-unfreeze),
# az pri druhe kontrole po sobe, at se nemeni uprostred instalace. Opravy plati bez odhlaseni.
function wm_update_check():
    if env.get("LUXOS_HUB_NO_WM_REPLACE", "") != "":
        return False
    end
    pid = wm_pid()
    # stejny proces se nevymenuje dvakrat (kdyby nova verze nenastartovala, stary spravce zustane)
    if pid == 0 or pid == hub["wm_replaced"] or not glib.readlink("/proc/" + String(pid) + "/exe").endswith(" (deleted)"):
        hub["wm_seen"] = 0
        return False
    end
    hub["wm_seen"] = hub["wm_seen"] + 1
    if hub["wm_seen"] < 2 or len(glib.stat("/usr/bin/xfwm4")) == 0:
        return False
    end
    call log("xfwm4: new version installed, replacing the window manager")
    hub["wm_seen"] = 0
    hub["wm_replaced"] = pid
    call glib.spawn_quiet(["setsid", "-f", "xfwm4", "--replace"])
    return True
end

# luxos-control-center [--panel|--background]: klik v liste (bez --background) bezici okno jen prepne
function main_control_center():
    if has_arg("--panel"):
        print cc.panel_text()
        return 0
    end
    pid = running_pid("luxos-control-center.pid", ["luxos-control-center", "luxos-hub"])
    if pid != 0 and pid != glib.getpid():
        call glib.kill(pid, SIGUSR1)
        return 0
    end
    call write_pidfiles(["luxos-control-center.pid"])
    call glib.unix_signal_add(SIGTERM, on_quit)
    call glib.unix_signal_add(SIGINT, on_quit)
    call glib.unix_signal_add(SIGUSR1, on_sigusr1)
    call glib.set_prgname("luxos-control-center")
    call gtk.init()
    call cc.create()
    if not has_arg("--background"):
        call cc.toggle()
    end
    call gtk.main()
    call remove_pidfiles()
    return 0
end

# luxos-calendar [--background]: samostatna instance na pozadi SIGUSR1, luxos-hub SIGUSR2
function main_calendar():
    pid = running_pid("luxos-calendar.pid", ["luxos-hub"])
    signum = SIGUSR2
    if pid == 0:
        pid = running_pid("luxos-calendar.pid", ["luxos-calendar"])
        signum = SIGUSR1
    end
    if pid != 0 and pid != glib.getpid():
        call glib.kill(pid, signum)
        return 0
    end
    call write_pidfiles(["luxos-calendar.pid"])
    call glib.unix_signal_add(SIGTERM, on_quit)
    call glib.unix_signal_add(SIGINT, on_quit)
    call glib.unix_signal_add(SIGUSR1, on_sigusr2)
    call glib.set_prgname("luxos-calendar")
    call glib.set_application_name(i18n.T("Calendar"))
    call gtk.init()
    background = has_arg("--background")
    call cal.create(background)
    if not background:
        call cal.toggle()
    end
    call gtk.main()
    call remove_pidfiles()
    return 0
end

program_name = basename(arg(0))
mode = env.get("LUXOS_HUB_MODE", "")
if mode == None or mode == "":
    mode = program_name
end
if mode == "luxos-control-center":
    call exit(main_control_center())
elif mode == "luxos-calendar":
    call exit(main_calendar())
else:
    call exit(main_hub())
end
