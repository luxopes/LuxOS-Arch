# LuxOS Trezor - zamykani pri zamceni obrazovky a pred uspanim (bezi uvnitr luxos-hub); prepis funkce
# subscribe() z luxos-safe. Vlastni zamykani (gocryptfs, otevrene soubory, upozorneni) dela program
# `luxos-safe lock --force` spusteny na pozadi, takze hlavni smycka hubu neceka. Pred uspanim drzi hub
# zpozdovaci inhibitor logind a uvolni ho, az zamykani skonci.
#   call safe.subscribe(session_bus, system_bus)   jen kdyz je luxos-safe nainstalovan
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_text as text

state = {"system": 0, "fd": -1, "locking": False}

function config_path():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos/safe.json"
end

function user_name():
    user = env.get("USER", "")
    if user == None or user == "":
        home = glib.home_dir()
        user = home[text.rfind(home, "/") + 1:]
    end
    return user
end

function mount_point():
    override = env.get("LUXOS_SAFE_MOUNT", "")
    if override != None and override != "":
        return override
    end
    return "/safe/" + user_name()
end

function lock_on_screen_lock():
    raw = glib.read_text(config_path())
    if raw == "":
        return True
    end
    data = {}
    try:
        data = json.decode(raw)
    else:
        data = {}
    end
    if type(data) != "Dictionary":
        return True
    end
    return data.get("lock_on_screen_lock", True) != False
end

# Pripojeni na MOUNT podle /proc/self/mountinfo (posledni je navrchu): [[fstype, zdroj]]
function mounts():
    out = []
    info = env.get("LUXOS_MOUNTINFO", "")
    if info == None or info == "":
        info = "/proc/self/mountinfo"
    end
    target = mount_point()
    for line in glib.read_text(info).split("\n"):
        halves = text.partition(line, " - ")
        fields = halves[0].split(" ")
        rfields = halves[1].split(" ")
        if len(fields) >= 5 and len(rfields) >= 2 and unescape_mount(fields[4]) == target:
            out.append([rfields[0], unescape_mount(rfields[1])])
        end
    end
    return out
end

# \040 apod. v mountinfo
function unescape_mount(value):
    return value.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")
end

# unlocked | locked | none
function status():
    ms = mounts()
    if len(ms) > 0 and ms[len(ms) - 1][0] == "fuse.gocryptfs":
        return "unlocked"
    end
    if exists(mount_point()):
        return "locked"
    end
    return "none"
end

function take_inhibitor():
    if state["system"] == 0:
        return -1
    end
    return gio.inhibit_fd(state["system"], "sleep", i18n.T("Safe"), "Lock the Safe before sleep", "delay")
end

function release():
    if state["fd"] >= 0:
        call glib.close_fd(state["fd"])
    end
    state["fd"] = -1
    return 0
end

function lock(then_release):
    if state["locking"]:
        return 0
    end
    state["locking"] = True
    pid = glib.spawn_watched_data(["luxos-safe", "lock", "--force"], on_locked, then_release)
    if pid == 0:
        state["locking"] = False
        if then_release:
            call release()
        end
    end
    return 0
end

function on_locked(then_release, pid, status_code):
    state["locking"] = False
    if then_release:
        call release()                # uspani pokracuje
    end
    return 0
end

function on_saver(sender, path, interface, signal, values):
    if len(values) > 0 and values[0] == True and lock_on_screen_lock():
        call lock(False)
    end
    return 0
end

function on_sleep(sender, path, interface, signal, values):
    if len(values) > 0 and values[0] == True:
        call lock(True)               # pred uspanim vzdy
    else:
        call release()
        state["fd"] = take_inhibitor()
    end
    return 0
end

function subscribe(session, system):
    state["system"] = system
    if session != 0:
        call gio.subscribe_values(session, "", "org.xfce.ScreenSaver", "ActiveChanged", "", on_saver)
    end
    if system != 0:
        call gio.subscribe_values(system, "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", on_sleep)
        state["fd"] = take_inhibitor()
    end
    if status() == "locked":
        # Spoustec "Odemknout Trezor" v zamcene slozce musi byt pro Thunar duveryhodny
        call glib.spawn_quiet(["luxos-safe", "--trust-launcher"])
    end
    return 0
end
