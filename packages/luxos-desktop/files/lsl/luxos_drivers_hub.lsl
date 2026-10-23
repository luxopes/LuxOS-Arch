# LuxOS Ovladace - kontrola po prihlaseni (bezi uvnitr luxos-hub); prepis luxos_drivers_session.py.
# Nejvys jednou za start pocitace chvili po prihlaseni spusti pomocny program v Pythonu
# `luxos_drivers_session.py check` (luxos-hwdetect --json + databaze baliku, ~0,1 s), ktery vypise JSON
# {"notify": bool, "names": [...], "key": "..."}. Kdyz nejaky ovladac chybi, ukaze upozorneni, ktere otevre
# aplikaci Ovladace; "Neupozornovat" si zapamatuje chybejici baliky (znovu se ozve jen pri jinem hardwaru).
#   call drivers.subscribe(session_bus)
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_text as text

APP = "luxos-drivers"
HELPER = "/usr/lib/luxos/python/luxos_drivers_session.py"

state = {"bus": 0, "ids": {}, "key": ""}

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function helper_path():
    value = env.get("LUXOS_DRIVERS_HELPER", "")
    if value == None or value == "":
        return HELPER
    end
    return value
end

function log(message):
    return eprint("luxos-hub: drivers: " + message)
end

function subscribe(session):
    state["bus"] = session
    if session != 0:
        call gio.subscribe_values(session, "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_action)
    end
    # s po prihlaseni (start relace ma prednost)
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_DRIVERS_DELAY", ""), 45), check)
    return 0
end

function check():
    if glib.spawn_capture(["python3", "-I", helper_path(), "check"], on_checked, 0) == 0:
        call log("helper " + helper_path() + " could not be started")
    end
    return False
end

function on_checked(unused, output, status):
    if status != 0:
        call log("detect: helper exited with " + String(status // 256))
        return 0
    end
    result = {}
    try:
        result = json.decode(output.strip())
    else:
        result = {}
    end
    if type(result) != "Dictionary" or result.get("notify") != True:
        return 0
    end
    names = result.get("names", [])
    if type(names) != "List":
        names = []
    end
    state["key"] = String(result.get("key", ""))
    body = i18n.T("Open Drivers to install them with one click.")
    if len(names) > 0:
        shown = []
        for n in names:
            if len(shown) < 3:
                shown.append(String(n))
            end
        end
        body = text.join(shown, ", ") + "\n" + body
    end
    actions = ["default", i18n.T("Show drivers"), "open", i18n.T("Show drivers"), "ignore", i18n.T("Don't remind me")]
    call gio.call_async(state["bus"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        ["LuxOS", 0, "luxos-drivers", i18n.T("Additional drivers are available"), body, actions, {"desktop-entry": ["s", APP]}, -1],
                        "(susssasa{sv}i)", 5000, on_notified, 0)
    return 0
end

function on_notified(unused, values, error):
    if values == None:
        call log("notify: " + error)
        return 0
    end
    state["ids"][values[0]] = True
    return 0
end

function on_action(sender, path, interface, signal, values):
    nid = values[0]
    action = values[1]
    if nid not in state["ids"]:
        return 0
    end
    call state["ids"].pop(nid, None)
    if action == "open" or action == "default":
        if glib.spawn([APP]) == 0:
            call log(APP + " could not be started")
        end
    elif action == "ignore":
        call glib.mkdir_p(config_dir())
        call glib.write_atomic(config_dir() + "/drivers-ignored", state["key"] + "\n")
    end
    return 0
end
