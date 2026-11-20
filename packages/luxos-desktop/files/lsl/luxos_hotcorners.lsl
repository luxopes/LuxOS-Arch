# LuxOS - horke rohy (v hubu): najeti ukazatelem do rohu obrazovky spusti akci, jako v macOS.
#   ~/.config/luxos/hotcorners: radky "tl=launchpad", "tr=none", "bl=none", "br=desktop" (Nastaveni > Plocha a Dock)
#   akce: none, launchpad, desktop (ukazat plochu / vratit okna), control-center, lock (zamknout),
#         screensaver (spustit sporic obrazovky)
#   Vychozi: levy horni Launchpad, pravy dolni Ukazat plochu. Ukazatel musi v rohu zustat asi 0,3 s (cestou
#   k logu LuxOS v levem hornim rohu se Launchpad nespusti) a znovu se roh spusti az po odjeti z rohu.
#   Rohy cele obrazovky X (pri vice monitorech vnejsi rohy). Na tabletu bez klavesnice (luxos-touch:
#   touchscreen=1 keyboard=0) vypnute - klepnuti do rohu by je spoustelo.
#   Testy: LUXOS_HOTCORNERS_LOG=soubor (akce se jen zapisou), LUXOS_HOTCORNERS_DWELL (tiky po 100 ms).
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk

DEFAULTS = {"tl": "launchpad", "tr": "none", "bl": "none", "br": "desktop"}
ACTIONS = ["none", "launchpad", "desktop", "control-center", "lock", "screensaver"]
TICK_MS = 100
RELOAD_TICKS = 20          # nastaveni znovu nacist kazde 2 s (zmena v Nastaveni plati hned)
LEAVE_PX = 24              # roh se znovu "nabije" az po odjeti dal nez 24 px

# dwell: pocet tiku (po 100 ms), po ktere musi ukazatel v rohu zustat (vychozi 3 = asi 0,25-0,3 s)
state = {"conf": {}, "ticks": 0, "corner": "", "in_corner": 0, "armed": True, "on_cc": None, "dwell": 3,
         "disabled": False}

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

# "tl=launchpad" -> slovnik; neznamy roh nebo akce se ignoruje, chybejici roh = vychozi
function parse_conf(text):
    conf = {}
    for k in ["tl", "tr", "bl", "br"]:
        conf[k] = DEFAULTS[k]
    end
    for line in text.split("\n"):
        line = line.strip()
        if line == "" or line.startswith("#") or line.find("=") < 0:
            continue
        end
        key = line[:line.find("=")].strip()
        value = line[line.find("=") + 1:].strip()
        if key in DEFAULTS and value in ACTIONS:
            conf[key] = value
        end
    end
    return conf
end

function reload():
    state["conf"] = parse_conf(glib.read_text(config_dir() + "/hotcorners"))
    # tablet bez fyzicke klavesnice: klepnuti do rohu nema nic spoustet
    touch = glib.read_text(config_dir() + "/touch-state")
    state["disabled"] = touch.find("touchscreen=1") >= 0 and touch.find("keyboard=0") >= 0
    return 0
end

# roh, ve kterem je bod (x, y) obrazovky w x h, nebo ""
function corner_at(x, y, w, h):
    if x <= 0 and y <= 0:
        return "tl"
    end
    if x >= w - 1 and y <= 0:
        return "tr"
    end
    if x <= 0 and y >= h - 1:
        return "bl"
    end
    if x >= w - 1 and y >= h - 1:
        return "br"
    end
    return ""
end

function near_corner(x, y, w, h):
    return (x < LEAVE_PX or x > w - 1 - LEAVE_PX) and (y < LEAVE_PX or y > h - 1 - LEAVE_PX)
end

function run_action(action):
    log_file = env.get("LUXOS_HOTCORNERS_LOG", "")
    if log_file != None and log_file != "":
        # testy: vsechny akce do souboru (prepis celeho obsahu: dosavadni + nova)
        call glib.write_atomic(log_file, glib.read_text(log_file) + action + "\n")
        return 0
    end
    if action == "launchpad":
        call glib.spawn_quiet(["luxos-launchpad"])
    elif action == "desktop":
        call glib.spawn_quiet(["sh", "-c", "if wmctrl -m 2>/dev/null | grep -qi 'showing the desktop: on'; then wmctrl -k off; else wmctrl -k on; fi"])
    elif action == "control-center":
        callback = state["on_cc"]
        if callback != None:
            call callback()
        end
    elif action == "lock":
        call glib.spawn_quiet(["xflock4"])
    elif action == "screensaver":
        call glib.spawn_quiet(["xfce4-screensaver-command", "--activate"])
    end
    return 0
end

function tick():
    state["ticks"] += 1
    if state["ticks"] % RELOAD_TICKS == 1:
        call reload()
    end
    if state["disabled"]:
        return True
    end
    p = gtk.pointer_position()
    size = gtk.root_size()
    c = corner_at(p[0], p[1], size[0], size[1])
    if c == "":
        if not near_corner(p[0], p[1], size[0], size[1]):
            state["armed"] = True
        end
        state["corner"] = ""
        return True
    end
    action = state["conf"].get(c, "none")
    if action == "none" or not state["armed"]:
        return True
    end
    if state["corner"] != c:
        state["corner"] = c
        state["in_corner"] = 0
        return True
    end
    state["in_corner"] += 1
    if state["in_corner"] >= state["dwell"]:
        state["armed"] = False
        call run_action(action)
    end
    return True
end

# on_cc: funkce bez argumentu, ktera otevre/zavre Ovladaci centrum (bezi ve stejnem procesu)
function start(on_cc):
    state["on_cc"] = on_cc
    dwell = env.get("LUXOS_HOTCORNERS_DWELL", "")       # testy: pocet tiku
    if dwell != None and dwell != "":
        state["dwell"] = Int(dwell)
    end
    call reload()
    call glib.timeout_add(TICK_MS, tick)
    return 0
end
