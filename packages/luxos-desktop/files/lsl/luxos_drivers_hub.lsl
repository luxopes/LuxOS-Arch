# LuxOS Ovladace - kontrola po prihlaseni (bezi uvnitr luxos-hub); prepis luxos_drivers_session.py.
# Nejvys jednou za start pocitace (boot_id) chvili po prihlaseni spusti `luxos-hwdetect --json` (bash, jen sysfs,
# ~0,1 s) a porovna doporucene baliky s databazi nainstalovanych (/var/lib/lux/local, jako luxos_drivers.py
# aplikace Ovladace). Kdyz nejaky ovladac chybi, ukaze upozorneni, ktere otevre aplikaci Ovladace;
# "Neupozornovat" si zapamatuje chybejici baliky (znovu se ozve jen pri jinem hardwaru). V live systemu mlci.
#   drivers.available()                 je luxos-hwdetect (balik luxos-drivers)
#   call drivers.subscribe(session_bus)
# LUXOS_HWDETECT a LUXOS_DRIVERS_ROOT (koren pro /var/lib/lux, /run/archiso, boot_id) jen pro testy.
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_text as text

APP = "luxos-drivers"
HWDETECT = "/usr/bin/luxos-hwdetect"
AVAILABLE = "available"
# Baliky, ktere doporuceny balik plne nahrazuji (luxos_drivers.py EQUIVALENT)
EQUIVALENT = {"nvidia-open-dkms": ["nvidia-open", "nvidia-open-lts", "nvidia-580xx-dkms"],
              "nvidia-utils": ["nvidia-580xx-utils"], "lib32-nvidia-utils": ["lib32-nvidia-580xx-utils"],
              "broadcom-wl-dkms": ["broadcom-wl"]}

state = {"bus": 0, "ids": {}, "key": ""}

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function setting(name, default):
    value = env.get(name, "")
    if value == None or value == "":
        return default
    end
    return value
end

function root_path(path):
    return setting("LUXOS_DRIVERS_ROOT", "") + path
end

function hwdetect():
    return setting("LUXOS_HWDETECT", HWDETECT)
end

function available():
    return exists(hwdetect())
end

function cache_dir():
    return setting("XDG_CACHE_HOME", glib.home_dir() + "/.cache") + "/luxos"
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

# Jednou za start pocitace; mimo live system
function should_check(boot):
    if glib.is_dir(root_path("/run/archiso")):
        return False
    end
    return boot == "" or glib.read_text(cache_dir() + "/drivers-checked").strip() != boot
end

function check():
    boot = glib.read_text(root_path("/proc/sys/kernel/random/boot_id")).strip()
    if not should_check(boot):
        return False
    end
    if glib.spawn_capture([hwdetect(), "--json"], on_detected, boot) == 0:
        call log("luxos-hwdetect could not be started")
    end
    return False
end

# Jmena nainstalovanych baliku z databaze (adresare jmeno-verze-vydani)
function installed_packages():
    db = root_path("/var/lib/lux/local")
    if not glib.is_dir(db):
        db = root_path("/var/lib/pacman/local")
    end
    names = {}
    for entry in glib.list_dir(db):
        name = text.rpartition(text.rpartition(entry, "-")[0], "-")[0]
        if name != "":
            names[name] = True
        end
    end
    return names
end

function is_installed(pkg, installed):
    if pkg in installed:
        return True
    end
    for other in EQUIVALENT.get(pkg, []):
        if other in installed:
            return True
        end
    end
    return False
end

function packages_of(item):
    pkgs = item.get("packages")
    if type(pkgs) != "List":
        return []
    end
    return pkgs
end

# [{"device", "status", "missing"}] jako luxos_drivers.evaluate (restart/installed/working tu nejsou potreba)
function evaluate(devices, installed):
    out = []
    for dev in devices:
        if type(dev) != "Dictionary":
            continue
        end
        target = dev
        alternatives = dev.get("alternatives")
        if type(alternatives) == "List":
            for alt in alternatives:
                pk = packages_of(alt)
                if len(pk) > 0 and pk[0] in installed:
                    target = alt
                    break
                end
            end
        end
        missing = [p for p in packages_of(target) if not is_installed(p, installed)]
        status = "ok"
        if len(missing) > 0:
            status = AVAILABLE
        end
        out.append({"device": dev, "status": status, "missing": missing})
    end
    return out
end

# Chybejici baliky serazene, oddelene mezerou (porovnani s tim, co uzivatel uz odmitl)
function notify_key(states):
    seen = {}
    for st in states:
        if st["status"] == AVAILABLE:
            for p in st["missing"]:
                seen[p] = True
            end
        end
    end
    return " ".join(sorted(seen.keys()))
end

function should_notify(states, ignored):
    refused = ignored.split(" ")
    for p in notify_key(states).split(" "):
        if p != "" and p not in refused:
            return True
        end
    end
    return False
end

function on_detected(boot, output, status):
    if status != 0:
        call log("detect: luxos-hwdetect exited with " + String(status // 256))
        return 0
    end
    data = None
    safe:
        data = json.decode(output)
    end
    if type(data) != "Dictionary" or type(data.get("devices")) != "List":
        call log("detect: luxos-hwdetect: unexpected output")
        return 0
    end
    call glib.mkdir_p(cache_dir())
    if not glib.write_atomic(cache_dir() + "/drivers-checked", boot + "\n"):
        call log("state: cannot write " + cache_dir() + "/drivers-checked")
    end
    states = evaluate(data["devices"], installed_packages())
    ignored = glib.read_text(config_dir() + "/drivers-ignored").strip()
    if not should_notify(states, ignored):
        return 0
    end
    names = []
    for st in states:
        title = st["device"].get("title", "")
        if st["status"] == AVAILABLE and type(title) == "String" and title != "":
            title = i18n.T(title)
            if title not in names:
                names.append(title)
            end
        end
    end
    state["key"] = notify_key(states)
    body = i18n.T("Open Drivers to install them with one click.")
    if len(names) > 0:
        shown = []
        for n in names:
            if len(shown) < 3:
                shown.append(n)
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
