# LuxOS firewall - upozorneni v luxos-hub (jako v macOS): "<Aplikace> chce prijimat spojeni ze site".
# Root (luxos-firewall-watch.service) zapisuje do /run/luxos-firewall/requests.json zahozena spojeni na porty,
# kde posloucha mistni program. Hub kazdy port oznami jednou za relaci (jen zadosti z posledni hodiny):
#   Povolit           pkexec luxos-firewall allow PORT/PROTO --from lan --app NAZEV (polkit: spravce v aktivni
#                     relaci bez hesla, jen mistni sit - 50-luxos-firewall.rules)
#   Nechat blokovane  port do ~/.config/luxos/firewall-ignored (uz se neozve)
#   klik / Nastaveni  okno Nastaveni > Firewall (luxos-firewall-settings)
# Spojeni z Tailscale: misto Povolit tlacitko do Nastaveni (zarizeni Tailscale jako mistni sit).
#   call firewall.subscribe(session_bus)
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_text as text

CLI = "/usr/bin/luxos-firewall"
SETTINGS = "luxos-firewall-settings"
RUN_DIR = "/run/luxos-firewall"
# Starsi zadosti (napr. sken site pred prihlasenim) se neoznamuji
MAX_AGE = 3600
# Upozorneni zmizi po 30 s (sken portu nezaplni obrazovku); pozdeji jde povolit v Nastaveni > Firewall
NOTIFY_MS = 30000

state = {"bus": 0, "ids": {}, "notified": {}, "timer": 0}

function log(message):
    return eprint("luxos-hub: firewall: " + message)
end

function run_dir():
    value = env.get("LUXOS_FIREWALL_RUN_DIR", "")
    if value == None or value == "":
        return RUN_DIR
    end
    return value
end

function available():
    return exists(CLI) or env.get("LUXOS_FIREWALL_RUN_DIR", "") != ""
end

function ignored_path():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos/firewall-ignored"
end

function ignored():
    out = {}
    content = ""
    safe:
        content = readfile(ignored_path())
    end
    if content == None:
        return out
    end
    for line in content.split("\n"):
        key = line.strip()
        if key != "":
            out[key] = True
        end
    end
    return out
end

# Oznamene porty i pres restart hubu (po aktualizaci): $XDG_RUNTIME_DIR, smaze se odhlasenim
function notified_path():
    base = env.get("XDG_RUNTIME_DIR", "")
    if base == None or base == "":
        base = "/tmp"
    end
    return base + "/luxos-firewall-notified"
end

function load_notified():
    content = ""
    safe:
        content = readfile(notified_path())
    end
    if content == None:
        return 0
    end
    for line in content.split("\n"):
        if line.strip() != "":
            state["notified"][line.strip()] = True
        end
    end
    return 0
end

# Uz povolene porty a stav Tailscale z /etc/luxos/firewall.json (cteni pro vsechny)
function config():
    data = None
    safe:
        data = json.decode(readfile(env.get("LUXOS_FIREWALL_CONFIG", "/etc/luxos/firewall.json")))
    end
    out = {"allowed": {}, "tailscale": False}
    if type(data) != "Dictionary":
        return out
    end
    out["tailscale"] = data.get("trust_tailscale") == True
    allow = data.get("allow", [])
    if type(allow) == "List":
        for item in allow:
            if type(item) == "Dictionary":
                out["allowed"][String(item.get("port", "")) + "/" + String(item.get("proto", ""))] = True
            end
        end
    end
    return out
end

function subscribe(session):
    state["bus"] = session
    if session == 0:
        return 0
    end
    call gio.subscribe_values(session, "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_action)
    call load_notified()
    # adresar vytvori luxos-firewall.service pri startu; sledovat adresar (root zapisuje atomicky prejmenovanim)
    call glib.mkdir_p(run_dir())
    try:
        call gio.file_monitor(run_dir(), on_file)
    else:
        call log("monitor: " + String(last_error()))
    end
    # Po prihlaseni: zadosti z posledni doby (pred prihlasenim)
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_FIREWALL_DELAY", ""), 15), check)
    return 0
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function on_file(path, event, other):
    name = basename(path)
    if event == gio.FILE_RENAMED and other != "":
        name = basename(other)
    end
    if name != "requests.json":
        return 0
    end
    if event != gio.FILE_CHANGES_DONE_HINT and event != gio.FILE_CREATED and event != gio.FILE_MOVED_IN and event != gio.FILE_RENAMED:
        return 0
    end
    if state["timer"] != 0:
        call glib.source_remove(state["timer"])
    end
    state["timer"] = glib.timeout_add(700, check)
    return 0
end

function app_title(app):
    if app == "Podman":
        return i18n.T("A container (Podman)")
    end
    if app == "" or app == "unknown":
        return i18n.T("A program")
    end
    return app
end

function check():
    state["timer"] = 0
    entries = None
    safe:
        entries = json.decode(readfile(run_dir() + "/requests.json"))
    end
    if type(entries) != "List":
        return False
    end
    skip = ignored()
    cfg = config()
    now = glib.now()
    added = ""
    for e in entries:
        if type(e) != "Dictionary":
            continue
        end
        port = e.get("port")
        proto = e.get("proto")
        if type(port) != "Int" or (proto != "tcp" and proto != "udp"):
            continue
        end
        key = String(port) + "/" + proto
        stamp = e.get("time")
        if key in state["notified"] or key in skip or key in cfg["allowed"] or type(stamp) != "Int" or now - stamp > MAX_AGE:
            continue
        end
        if e.get("tailscale") == True and cfg["tailscale"]:
            continue
        end
        state["notified"][key] = True
        added = added + key + "\n"
        call notify(e, key)
    end
    if added != "":
        old = ""
        safe:
            old = readfile(notified_path())
        end
        if old == None:
            old = ""
        end
        call glib.write_atomic(notified_path(), old + added)
    end
    return False
end

function notify(e, key):
    app = String(e.get("app", ""))
    src = String(e.get("src", ""))
    title = i18n.TF("%s wants to accept connections from the network", [app_title(app)])
    actions = ["default", i18n.T("Firewall Settings")]
    if e.get("tailscale") == True:
        body = i18n.TF("The firewall blocked a connection to port %s from a Tailscale device (%s).", [key, src]) + "\n" + i18n.T("To allow your Tailscale devices, turn on \"Treat Tailscale devices as this network\" in Firewall settings.")
        actions.extend(["keep", i18n.T("Keep Blocked")])
    else:
        body = i18n.TF("The firewall blocked a connection to port %s from %s.", [key, src]) + "\n" + i18n.T("Allow will let only devices on this network connect (not the internet).")
        actions.extend(["allow", i18n.T("Allow"), "keep", i18n.T("Keep Blocked")])
    end
    call gio.call_async(state["bus"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        ["LuxOS", 0, "firewall", title, body, actions, {"desktop-entry": ["s", SETTINGS]}, NOTIFY_MS],
                        "(susssasa{sv}i)", 5000, on_notified, {"key": key, "app": app})
    return 0
end

function on_notified(info, values, error):
    if values == None:
        call log("notify: " + error)
        return 0
    end
    state["ids"][values[0]] = info
    return 0
end

function on_action(sender, path, interface, signal, values):
    nid = values[0]
    action = values[1]
    if nid not in state["ids"]:
        return 0
    end
    info = state["ids"].pop(nid, None)
    if action == "allow":
        argv = ["pkexec", CLI, "allow", info["key"], "--from", "lan"]
        if info["app"] != "" and info["app"] != "unknown":
            argv.extend(["--app", info["app"]])
        end
        if glib.spawn_capture(argv, on_allowed, info) == 0:
            call log("pkexec could not be started")
        end
    elif action == "keep":
        call glib.mkdir_p(base_dir(ignored_path()))
        content = ""
        safe:
            content = readfile(ignored_path())
        end
        if content == None:
            content = ""
        end
        call glib.write_atomic(ignored_path(), content + info["key"] + "\n")
    elif action == "settings" or action == "default":
        if glib.spawn([SETTINGS]) == 0:
            call log(SETTINGS + " could not be started")
        end
    end
    return 0
end

function base_dir(path):
    return path[0:text.rfind(path, "/")]
end

function on_allowed(info, output, status):
    if status != 0:
        call log("allow " + info["key"] + ": exit " + String(status // 256))
        # 126 = zruseno v dialogu hesla: bez dalsiho upozorneni
        if status // 256 == 126:
            return 0
        end
        call gio.call_async(state["bus"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                            ["LuxOS", 0, "dialog-error", i18n.T("The firewall exception could not be added"), i18n.T("Open Firewall settings and try it there."), [], {"desktop-entry": ["s", SETTINGS]}, -1],
                            "(susssasa{sv}i)", 5000, on_plain, 0)
        return 0
    end
    call gio.call_async(state["bus"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        ["LuxOS", 0, "firewall", i18n.TF("%s can now accept connections", [app_title(info["app"])]),
                         i18n.TF("Devices on this network can connect to port %s. You can change it in Firewall settings.", [info["key"]]), [], {"desktop-entry": ["s", SETTINGS]}, -1],
                        "(susssasa{sv}i)", 5000, on_plain, 0)
    return 0
end

function on_plain(unused, values, error):
    if values == None:
        call log("notify: " + error)
    end
    return 0
end
