# LuxOS - neuspavat pri prehravani hudby/videa (i se zavrenym vikem); prepis tridy KeepAwake z luxos-hub.
# Vikem i necinnosti uspava xfce4-power-manager (drzi si inhibitor handle-lid-switch v logind, takze
# inhibitor logind by nepomohl). Behem prehravani proto docasne nastavime jeho akci vika na "vypnout
# obrazovku" (0) a uspani pri necinnosti na "nikdy" (14); puvodni hodnoty jsou v souboru sleep-override
# (obnovi se i po padu, pri dalsim startu). xfce4-power-manager cte nastaveni az v okamziku udalosti.
#   call awake.init(session_bus, system_bus)   po mpris.init
#   call awake.shutdown()                       pri konci hubu
load env
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_mpris as mpris
load luxos_text as text

XFPM = "xfce4-power-manager"
LID_PROPS = ["lid-action-on-battery", "lid-action-on-ac"]
IDLE_PROPS = ["inactivity-on-battery", "inactivity-on-ac"]
SLEEP_ACTIONS = [1, 2, 5]      # uspat, hibernovat, hybridni uspani (0 = vypnout obrazovku)
LID_SCREEN_OFF = 0
IDLE_NEVER = 14

state = {"session": 0, "system": 0, "timer": 0, "engaged": False, "ready": False}

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

# "vlastnost=puvodni hodnota"
function override_path():
    return config_dir() + "/sleep-override"
end

# existuje = volba vypnuta
function while_playing_path():
    return config_dir() + "/sleep-while-playing"
end

# s ticha, nez se nastaveni vrati (mezery mezi skladbami, kratka pauza); LUXOS_PLAYBACK_GRACE pro testy
function grace():
    return text.to_int(env.get("LUXOS_PLAYBACK_GRACE", ""), 30)
end

function read_override():
    values = {}
    for line in glib.read_text(override_path()).split("\n"):
        pair = text.partition(line.strip(), "=")
        if text.is_digits(pair[1]):
            values[pair[0]] = Int(pair[1])
        end
    end
    return values
end

function write_override(values):
    out = ""
    for key in values.keys():
        out = out + key + "=" + String(values[key]) + "\n"
    end
    return glib.write_atomic(override_path(), out)
end

# {vlastnost: hodnota} xfce4-power-manager -> {vlastnost: [puvodni, docasna]} pro dobu prehravani
function plan_override(current):
    plan = {}
    for p in LID_PROPS:
        if current.get(p) in SLEEP_ACTIONS:
            plan[p] = [current[p], LID_SCREEN_OFF]
        end
    end
    for p in IDLE_PROPS:
        v = current.get(p)
        if v != None and v > IDLE_NEVER:
            plan[p] = [v, IDLE_NEVER]
        end
    end
    return plan
end

# Co vratit: jen vlastnosti, ktere mezitim nikdo nezmenil (jinak plati novejsi volba uzivatele)
function plan_restore(saved, current):
    out = {}
    for p in saved.keys():
        temp = IDLE_NEVER
        if p in LID_PROPS:
            temp = LID_SCREEN_OFF
        end
        now = current.get(p)
        if now == None or now == temp:
            out[p] = saved[p]
        end
    end
    return out
end

# Akce po skonceni prehravani se zavrenym vikem: "Suspend", "Hibernate" nebo None
function lid_sleep_action(saved, on_battery, lid_closed, external):
    if not lid_closed or external:
        return None
    end
    key = "lid-action-on-ac"
    if on_battery:
        key = "lid-action-on-battery"
    end
    a = saved.get(key)
    if a == 1 or a == 5:
        return "Suspend"
    end
    if a == 2:
        return "Hibernate"
    end
    return None
end

# Pripojeny jiny nez vestaveny displej (s nim xfce4-power-manager vikem neuspava)
function external_monitor():
    base = env.get("LUXOS_DRM_DIR", "")
    if base == None or base == "":
        base = "/sys/class/drm"
    end
    for name in glib.list_dir(base):
        if name.find("-") < 0 or name.find("-eDP") >= 0 or name.find("-LVDS") >= 0 or name.find("-DSI") >= 0:
            continue
        end
        if glib.read_text(base + "/" + name + "/status").strip() == "connected":
            return True
        end
    end
    return False
end

# ---- xfconf a UPower ------------------------------------------------------------------------------

function xfconf_get(prop):
    value = None
    try:
        reply = gio.call_values(state["session"], "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", "GetProperty", [XFPM, "/" + XFPM + "/" + prop], "(ss)", 3000)
        value = reply[0]
    else:
        value = None
    end
    return value
end

function xfconf_set(prop, value):
    ok = True
    try:
        call gio.call_values(state["session"], "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf", "SetProperty", [XFPM, "/" + XFPM + "/" + prop, ["u", value]], "(ssv)", 3000)
    else:
        ok = False
    end
    return ok
end

function current(props):
    values = {}
    for p in props:
        v = xfconf_get(p)
        if v != None and type(v) == "Int":
            values[p] = v
        end
    end
    return values
end

function upower(prop):
    result = False
    try:
        result = gio.get_property_value(state["system"], "org.freedesktop.UPower", "/org/freedesktop/UPower", "org.freedesktop.UPower", prop) == True
    else:
        result = False
    end
    return result
end

# ---- logika ------------------------------------------------------------------------------------------

function init(session, system):
    state["session"] = session
    state["system"] = system
    state["ready"] = True
    call restore(False)           # zbytek po padu / odhlaseni behem prehravani
    call mpris.connect(changed)
    safe:
        call gio.file_monitor(while_playing_path(), on_option_file)
    end
    call changed()
    return 0
end

function on_option_file(path, event, other):
    call changed()
    return 0
end

function changed():
    want = mpris.playing() and not exists(while_playing_path())
    if want:
        if state["timer"] != 0:
            call glib.source_remove(state["timer"])
            state["timer"] = 0
        end
        # Jednou za prehravani (zmena metadat u dalsi skladby uz xfconf necte)
        if not state["engaged"]:
            state["engaged"] = True
            if not exists(override_path()):
                call engage()
            end
        end
        return 0
    end
    state["engaged"] = False
    if exists(override_path()) and state["timer"] == 0:
        # Volbu uzivatel vypnul -> hned, jinak az po chvili ticha
        delay = grace()
        if exists(while_playing_path()):
            delay = 1
        end
        state["timer"] = glib.timeout_add_seconds(delay, on_quiet)
    end
    return 0
end

function engage():
    props = []
    props.extend(LID_PROPS)
    props.extend(IDLE_PROPS)
    plan = plan_override(current(props))
    if len(plan) == 0:
        return 0
    end
    saved = {}
    for p in plan.keys():
        saved[p] = plan[p][0]
    end
    call glib.mkdir_p(config_dir())
    call write_override(saved)
    for p in plan.keys():
        call xfconf_set(p, plan[p][1])
    end
    return 0
end

function on_quiet():
    state["timer"] = 0
    if not mpris.playing() or exists(while_playing_path()):
        call restore(True)
    end
    return False
end

function restore(sleep):
    saved = read_override()
    if len(saved) == 0:
        if exists(override_path()):
            call glib.unlink(override_path())
        end
        return 0
    end
    keys = []
    for p in saved.keys():
        keys.append(p)
    end
    plan = plan_restore(saved, current(keys))
    for p in plan.keys():
        call xfconf_set(p, plan[p])
    end
    call glib.unlink(override_path())
    if not sleep:
        return 0
    end
    # Vik se zavrel behem prehravani: ted, kdyz hudba skoncila, uspat jako po zavreni vika
    action = lid_sleep_action(saved, upower("OnBattery"), upower("LidIsClosed"), external_monitor())
    if action != None:
        call eprint("luxos-hub: playback stopped with the lid closed: " + action)
        call do_sleep(action)
    end
    return 0
end

function do_sleep(action):
    # Pres xfce4-power-manager (zamkne obrazovku podle nastaveni), jinak primo logind
    ok = True
    try:
        call gio.call_values(state["session"], "org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement", "org.freedesktop.PowerManagement", action, [], "", 5000)
    else:
        ok = False
        call eprint("luxos-hub: power manager " + action + ": " + String(last_error()))
    end
    if ok:
        return 0
    end
    try:
        call gio.call_values(state["system"], "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", action, [False], "(b)", 5000)
    else:
        call eprint("luxos-hub: logind " + action + ": " + String(last_error()))
    end
    return 0
end

function shutdown():
    if state["ready"] and exists(override_path()):
        call restore(False)
    end
    return 0
end
