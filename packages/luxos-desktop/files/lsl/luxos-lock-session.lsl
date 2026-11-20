# LuxOS - kdy zamknout obrazovku v relaci na Waylandu (sluzba uzivatele luxos-lock.service). Sam nic nekresli:
# zamek luxos-lock spousti az pri zamceni, v klidu tak drzi jen spojeni s kompozitorem a sbernici.
#
#   necinnost   ext-idle-notify-v1 (s ohledem na inhibitory, pri filmu se nezamyka); cas jako xfce4-screensaver
#               v nastaveni LuxOS (luxos-lock-settings): /saver/idle-activation/delay + /lock/saver-activation/delay
#               v minutach, jen kdyz jsou zapnute (zmena souboru plati hned)
#   logind      signal Lock relace (loginctl lock-session, polozka Zamknout v liste) a PrepareForSleep: pred uspanim
#               drzi zpozdovaci inhibitor, dokud zamek nehlasi "ready" (nakreslene plochy) - obrazovka po probuzeni
#               nikdy neukaze plochu; /lock/sleep-activation false = pred uspanim nezamykat
#   pad zamku   kompozitor obrazovku dal zakryva; spusti se novy zamek, ktery zamek prevezme
#
# Testy: LUXOS_LOCK_PROGRAM (jiny luxos-lock a jeho argumenty oddelene mezerou), LUXOS_LOCK_IDLE_MS (pevna
# necinnost v ms), LUXOS_LOCK_TRACE=1 (udalosti na stdout).
load env, glib, gio
load luxos_glib as lglib
load luxos_gio as lgio
load luxos_sys
load luxos_text as text
load luxos_wl as wl
load luxos_lock_sys as sys

LOCKER = "/usr/bin/luxos-lock"
LOGIN1 = "org.freedesktop.login1"
CHANNEL = "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml"
SLEEP_WAIT_MS = 4000

trace = env.get("LUXOS_LOCK_TRACE", "") == "1"
state = {"locker": 0, "ready": False, "watch": 0, "idle_ms": 0, "system": 0, "session": "", "inhibitor": -1,
         "sleeping": False, "sleep_lock": True, "crashes": [], "monitor": 0}


function log(line):
    if trace:
        call luxos_sys.out(line + "\n")
    end
    return 0
end

# ---- nastaveni (xfconf xfce4-screensaver bez xfconfd: na Waylandu nemusi bezet) ----

function channel_path():
    return glib.user_config_dir() + "/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml"
end

function attr(line, name):
    cut = line.find(name + "=\"")
    if cut < 0:
        return ""
    end
    rest = line[cut + len(name) + 2:]
    return rest[0:rest.find("\"")]
end

# Vlastnosti kanalu jako {"/saver/idle-activation/delay": "10", ...}; vnorene <property> skladaji cestu
function read_channel(path, into):
    stack = []
    for raw in text.lines(lglib.read_text(path)):
        line = raw.strip()
        if line.startswith("<property "):
            name = attr(line, "name")
            if line.endswith("/>"):
                into[text.join(stack + [name], "/")] = attr(line, "value")
            else:
                stack.append(name)
            end
        elif line.startswith("</property>") and len(stack) > 0:
            call stack.pop()
        end
    end
    return into
end

function settings():
    conf = read_channel(CHANNEL, {})
    call read_channel(channel_path(), conf)
    out = {}
    for key in conf:
        out["/" + key] = conf[key]
    end
    return out
end

function minutes(value, default):
    if value == "" or not text.is_digits(value):
        return default
    end
    return Int(value)
end

function apply_settings():
    conf = settings()
    state["sleep_lock"] = conf.get("/lock/sleep-activation", "true") != "false"
    ms = 0
    fixed = env.get("LUXOS_LOCK_IDLE_MS", "")
    if fixed != "":
        ms = Int(fixed)
    elif conf.get("/saver/idle-activation/enabled", "true") != "false" and conf.get("/lock/enabled", "true") != "false" and conf.get("/lock/saver-activation/enabled", "true") != "false":
        ms = (minutes(conf.get("/saver/idle-activation/delay", ""), 10) + minutes(conf.get("/lock/saver-activation/delay", ""), 0)) * 60000
    end
    if ms == state["idle_ms"] and state["watch"] != 0:
        return 0
    end
    if state["watch"] != 0:
        call wl.idle_release(state["watch"])
        state["watch"] = 0
    end
    state["idle_ms"] = ms
    if ms > 0:
        state["watch"] = wl.idle_watch_inhibited(ms)
    end
    call log("idle " + String(ms))
    return 0
end

function on_channel_changed(path, event, other):
    call apply_settings()
    return 0
end

# ---- zamek ----

function locker_argv():
    custom = env.get("LUXOS_LOCK_PROGRAM", "")
    if custom == "":
        return [LOCKER, "--notify"]
    end
    return custom.split(" ") + ["--notify"]
end

function lock_now(why):
    if state["locker"] != 0:
        return 0
    end
    child = sys.spawn_lines(locker_argv(), [], on_locker, 0)
    if len(child) == 0:
        call luxos_sys.eprint("luxos-lock-session: cannot start luxos-lock")
        call release_inhibitor()
        return 0
    end
    call lglib.close_fd(child[1])
    state["locker"] = child[0]
    state["ready"] = False
    call log("lock " + why)
    return 0
end

function on_locker(data, line, status):
    if line == "ready":
        state["ready"] = True
        call log("locker ready")
        # zamceno a nakresleno: uspani muze pokracovat
        call release_inhibitor()
        return 0
    end
    if line != "":
        return 0
    end
    state["locker"] = 0
    code = (status >> 8) & 255
    signal = status & 127
    call log("locker exit " + String(code) + " signal " + String(signal))
    if signal == 0 and (code == 0 or code == 2 or code == 3):
        # odemceno, zamek neumi kompozitor, nebo uz zamyka nekdo jiny
        call release_inhibitor()
        return 0
    end
    # pad: obrazovka zustava zakryta, novy zamek ji prevezme (pri smycce padu pomaleji)
    now = glib.monotonic_time()
    recent = []
    for t in state["crashes"]:
        if now - t < 10000000:
            recent.append(t)
        end
    end
    recent.append(now)
    state["crashes"] = recent
    delay = 0
    if len(recent) > 3:
        delay = 2000
    end
    call glib.timeout_add(delay, relock)
    return 0
end

function relock():
    call lock_now("restart")
    return False
end

# ---- logind ----

function take_inhibitor():
    if state["system"] == 0 or state["inhibitor"] >= 0 or not state["sleep_lock"]:
        return 0
    end
    state["inhibitor"] = lgio.inhibit_fd(state["system"], "sleep", "LuxOS", "Lock the screen before suspend", "delay")
    call log("inhibitor " + String(state["inhibitor"] >= 0))
    return 0
end

function release_inhibitor():
    if state["inhibitor"] >= 0 and state["sleeping"]:
        call lglib.close_fd(state["inhibitor"])
        state["inhibitor"] = -1
        call log("inhibitor released")
    end
    return 0
end

function sleep_timeout():
    # zamek se nenakreslil vcas: uspani nebrzdit dal (logind by po InhibitDelayMaxSec stejne pokracoval)
    call release_inhibitor()
    return False
end

function on_sleep(sender, path, interface, signal, values):
    if len(values) == 0:
        return 0
    end
    if values[0] == True:
        state["sleeping"] = True
        call log("prepare sleep")
        if not state["sleep_lock"]:
            return 0
        end
        if state["locker"] != 0 and state["ready"]:
            call release_inhibitor()
        else:
            call lock_now("sleep")
            call glib.timeout_add(SLEEP_WAIT_MS, sleep_timeout)
        end
    else:
        state["sleeping"] = False
        call log("resume")
        call take_inhibitor()
    end
    return 0
end

function on_lock_signal(sender, path, interface, signal, values):
    return lock_now("logind")
end

function on_session(data, reply, error):
    if reply == None or len(reply) == 0:
        call log("no session " + String(error))
        return 0
    end
    state["session"] = String(reply[0])
    call gio.subscribe_values(state["system"], LOGIN1, "org.freedesktop.login1.Session", "Lock", state["session"], on_lock_signal)
    call log("session " + state["session"])
    return 0
end

function system_bus():
    bus = 0
    safe:
        bus = gio.system_bus()
    end
    if bus == None:
        return 0
    end
    return bus
end

function logind_start():
    state["system"] = system_bus()
    if state["system"] == 0:
        return 0
    end
    call gio.subscribe_values(state["system"], LOGIN1, "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", on_sleep)
    id = env.get("XDG_SESSION_ID", "")
    if id != "":
        call lgio.call_async(state["system"], LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSession",
                             [id], "(s)", 5000, on_session, 0)
    else:
        call lgio.call_async(state["system"], LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                             "GetSessionByPID", [glib.getpid()], "(u)", 5000, on_session, 0)
    end
    call take_inhibitor()
    return 0
end

# ---- Wayland ----

function event(kind, handle, a, b):
    if kind == wl.IDLE and handle == state["watch"]:
        call lock_now("idle")
    elif kind == wl.DISCONNECTED:
        call exit(1)
    end
    return 0
end

function main():
    call wl.on_event(event)
    if not wl.connect(""):
        call luxos_sys.eprint("luxos-lock-session: no Wayland compositor")
        call exit(2)
    end
    if wl.has("ext_session_lock_manager_v1") == 0:
        call luxos_sys.eprint("luxos-lock-session: compositor has no ext-session-lock-v1")
        call exit(2)
    end
    call apply_settings()
    call lglib.mkdir_p(glib.user_config_dir() + "/xfce4/xfconf/xfce-perchannel-xml")
    safe:
        state["monitor"] = gio.file_monitor(channel_path(), on_channel_changed)
    end
    call logind_start()
    call log("started")
    call glib.main()
    return 0
end

call main()
