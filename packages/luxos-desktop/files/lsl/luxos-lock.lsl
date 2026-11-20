# LuxOS - zamek obrazovky na Waylandu (1.1.0): ext-session-lock-v1, jedna zamykaci plocha na monitor (i pripojeny
# za zamceni), kresba cairem (luxos_lock_draw). Nahrazuje xfce4-screensaver s luxos-lock-ui.c.
#
#   luxos-lock            zamknout hned; konci po odemceni (kod 0)
#   luxos-lock --notify   navic radek "ready" na stdout, az je zamceno a kazdy monitor ma nakreslenou plochu
#                         (luxos-lock-session ceka na nej pred uspanim)
# Kody: 0 odemceno, 1 chyba (kompozitor skoncil), 2 kompozitor zamek neumi, 3 zamek odmitnut (uz zamceno).
#
# Bezpecnost: PAM bezi v oddelenem programu luxos-auth (jeden proces na pokus), heslo nikdy neni v LSL: znaky drzi
# libluxos-wl v zamcenem bufferu a posle je primo do roury pomocnika (wl.lock_secret_write). Kdyz zamek spadne,
# kompozitor obrazovku dal zakryva (ext-session-lock) a luxos-lock-session spusti novy zamek. Odemyka jen
# uspesne overeni nebo signal Unlock od logind (loginctl unlock-session, vyzaduje opravneni).
# Otisk prstu bezi soubezne s heslem (sluzba luxos-lock-fingerprint, je-li pam_fprintd); neuspesny otisk
# se do pam_faillock nepocita.
#
# Testy: LUXOS_LOCK_AUTH (jiny luxos-auth, napr. s napodobenym PAM), LUXOS_LOCK_FPRINT_MODULE (misto
# /usr/lib/security/pam_fprintd.so), LUXOS_LOCK_POWER_SUPPLY (misto /sys/class/power_supply),
# LUXOS_LOCK_NOW="HH:MM" (pevne hodiny), LUXOS_LOCK_DEMO_NAME (jmeno na snimcich), LUXOS_LOCK_TRACE=1 (udalosti na stdout).
load env, cairo, glib, gio, gtk, math
load luxos_glib as lglib
load luxos_gio as lgio
load luxos_sys
load luxos_text as text
load luxos_i18n as i18n
load luxos_wl as wl
load luxos_material as material
load luxos_lock_draw as draw
load luxos_lock_sys as sys

AUTH = "/usr/lib/luxos/luxos-auth"
FPRINT_MODULE = "/usr/lib/security/pam_fprintd.so"
GREETER_CONF = "/etc/lightdm/luxos-greeter.conf"
KEY_RETURN = 65293
KEY_KP_ENTER = 65421
KEY_ESCAPE = 65307
LOGIN1 = "org.freedesktop.login1"

notify = arg_count() > 1 and arg(1) == "--notify"
trace = env.get("LUXOS_LOCK_TRACE", "") == "1"

# surfaces: id plochy -> [vystup, sirka, vyska, nakresleno]
state = {"locked": False, "ready": False, "surfaces": {}, "redraw": 0, "shake_start": 0, "shake_timer": 0,
         "auth": [], "auth_error": False, "locked_hint": "", "caps_at_submit": False, "fp": [], "fp_seen": False,
         "fp_off": False, "fp_ended": 0, "system": 0, "session": "", "glasses": {}}
ui = {"font": "Inter", "clock": "", "date": "", "name": "", "face": None, "length": 0, "placeholder": "",
      "hint": "", "error": False, "caps": False, "caps_text": "", "layout": "", "busy": False, "shake": 0.0,
      "battery": None}


function log(line):
    if trace:
        print line
    end
    return 0
end

function quit(code):
    call wl.lock_secret_clear()
    call wl.disconnect()
    call exit(code)
end

# ---- nastaveni a uzivatel ----

function load_config():
    conf = text.parse_kv(lglib.read_text(GREETER_CONF))
    ui["font"] = conf.get("font", "Inter").strip()
    fmt = conf.get("clock-format", "").strip()
    if fmt == "":
        fmt = "%-H:%M"
        if i18n.lang() == "en" and conf.get("clock-24h", "").strip() != "true":
            fmt = "%-I:%M"
        end
    end
    state["clock_fmt"] = fmt
    if conf.get("show-battery", "true").strip() == "false":
        state["no_battery"] = True
    end
    return 0
end

function load_user():
    name = env.get("LUXOS_LOCK_DEMO_NAME", "")
    if name == "":
        name = sys.real_name()
    end
    if name == "" or name == "Unknown":
        name = sys.user_name()
    end
    ui["name"] = name
    paths = [glib.home_dir() + "/.face"]
    if state["system"] != 0:
        call lgio.call_async(state["system"], "org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                             "org.freedesktop.Accounts", "FindUserByName", [sys.user_name()], "(s)", 2000, on_account, 0)
    end
    call load_face(paths[0])
    return 0
end

function load_face(path):
    if path != "" and exists(path):
        face = gtk.pixbuf_new_from_file_at_scale(path, 256, 256, True)
        if face != 0:
            ui["face"] = face
            call redraw()
        end
    end
    return 0
end

function on_account(data, reply, error):
    if reply != None and len(reply) > 0:
        call lgio.call_async(state["system"], "org.freedesktop.Accounts", reply[0], "org.freedesktop.DBus.Properties",
                             "Get", ["org.freedesktop.Accounts.User", "IconFile"], "(ss)", 2000, on_icon, 0)
    end
    return 0
end

function on_icon(data, reply, error):
    if reply != None and len(reply) > 0 and ui["face"] == None:
        call load_face(String(reply[0]))
    end
    return 0
end

# ---- hodiny a baterie ----

function update_clock():
    fixed = env.get("LUXOS_LOCK_NOW", "")
    if fixed != "":
        ui["clock"] = fixed
    else:
        ui["clock"] = luxos_sys.strftime_local(state["clock_fmt"])
    end
    ui["date"] = i18n.format_tm(lglib.localtime(lglib.now()), "long")
    return 0
end

function power_dir():
    path = env.get("LUXOS_LOCK_POWER_SUPPLY", "")
    if path == "":
        return "/sys/class/power_supply"
    end
    return path
end

# Prvni baterie zarizeni (ne mys ani klavesnice: scope Device); blesk i kdyz nabijecka drzi plnou baterii
function update_battery():
    ui["battery"] = None
    if state.get("no_battery", False):
        return 0
    end
    base = power_dir()
    mains = False
    found = None
    for name in lglib.list_dir(base):
        dir = base + "/" + name
        kind = lglib.read_text(dir + "/type").strip()
        if (kind == "Mains" or kind == "USB") and lglib.read_text(dir + "/online").strip() == "1":
            mains = True
        end
        cap = lglib.read_text(dir + "/capacity").strip()
        if found == None and kind == "Battery" and lglib.read_text(dir + "/scope").strip() != "Device" and text.is_digits(cap) and cap != "":
            found = [min(100, Int(cap)), lglib.read_text(dir + "/status").strip()]
        end
    end
    if found != None:
        charging = found[1] == "Charging" or (found[1] != "Discharging" and mains)
        ui["battery"] = [found[0], charging]
    end
    return 0
end

function minute_tick():
    call update_clock()
    call update_battery()
    call redraw()
    call glib.timeout_add((60 - lglib.localtime(lglib.now())[5]) * 1000 + 50, minute_tick)
    return False
end

# ---- kresleni ----

function glass_for(output):
    name = wl.output_name(output)
    if name in state["glasses"]:
        return state["glasses"][name]
    end
    gl = material.glass(material.wallpaper_path(name))
    call log("wallpaper " + name + " " + material.wallpaper_path(name) + " " + String(gl != None))
    state["glasses"][name] = gl
    return gl
end

function redraw():
    if state["redraw"] == 0:
        state["redraw"] = glib.idle_add(draw_all)
    end
    return 0
end

function draw_all():
    state["redraw"] = 0
    again = False
    for id in state["surfaces"]:
        s = state["surfaces"][id]
        if s[1] <= 0:
            continue
        end
        image = wl.surface_begin(id)
        if image == 0:
            # oba bufery u kompozitoru: zkusit za snimek
            again = True
            continue
        end
        cr = cairo.create(image)
        scale = wl.surface_scale(id)
        if scale != 1.0:
            call cairo.scale(cr, scale, scale)
        end
        call draw.frame(cr, s[1], s[2], ui, glass_for(s[0]))
        call cairo.destroy(cr)
        call wl.surface_commit(id, image)
        s[3] = True
    end
    if again:
        call glib.timeout_add(16, redraw_later)
    end
    call check_ready()
    return False
end

function redraw_later():
    call redraw()
    return False
end

function check_ready():
    if state["ready"] or not state["locked"] or len(state["surfaces"]) == 0:
        return 0
    end
    for id in state["surfaces"]:
        if not state["surfaces"][id][3]:
            return 0
        end
    end
    call wl.roundtrip()
    state["ready"] = True
    if notify:
        call luxos_sys.out("ready\n")
    else:
        call log("ready")
    end
    return 0
end

# ---- hlasky a zatreseni ----

function set_hint(message, error):
    ui["hint"] = message
    ui["error"] = error
    call redraw()
    return 0
end

function shake_step():
    p = Float(glib.monotonic_time() - state["shake_start"]) / 480000.0
    if p >= 1.0:
        ui["shake"] = 0.0
        state["shake_timer"] = 0
        call redraw()
        return False
    end
    ui["shake"] = Float(Int(math.sin(p * cairo.PI * 8.0) * (1.0 - p) * 16.0 + 0.5))
    call redraw()
    return True
end

function shake():
    state["shake_start"] = glib.monotonic_time()
    if state["shake_timer"] == 0:
        state["shake_timer"] = glib.timeout_add(16, shake_step)
    end
    call log("shake")
    return 0
end

# pam_faillock: ucet docasne zamceny -> minuty (0 = nevime), jinak -1 (jako account_locked v luxos-lock-ui.c)
function account_locked(message):
    t = message.lower()
    for key in ["account is locked", "is locked due to", "left to unlock", "zamčen", "uzamčen", "zablokov", "do odemčení"]:
        if t.find(key) >= 0:
            words = t.replace("(", " ").split(" ")
            for i in range(len(words) - 1):
                if text.is_digits(words[i]) and words[i] != "" and words[i + 1].startswith("minut"):
                    return Int(words[i])
                end
            end
            return 0
        end
    end
    return -1
end

# ---- overeni ----

function auth_env():
    out = ["PATH=/usr/bin:/bin"]
    for name in ["LANG", "LC_ALL", "LC_MESSAGES", "HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR", "DBUS_SYSTEM_BUS_ADDRESS"]:
        value = env.get(name, "")
        if value != "":
            out.append(name + "=" + value)
        end
    end
    return out
end

function auth_program():
    path = env.get("LUXOS_LOCK_AUTH", "")
    if path == "":
        return AUTH
    end
    return path
end

function submit():
    if len(state["auth"]) > 0 or wl.lock_secret_length() == 0:
        return 0
    end
    child = sys.spawn_lines([auth_program(), "password"], auth_env(), on_auth_line, "password")
    if len(child) == 0:
        call wl.lock_secret_clear()
        call set_hint(i18n.T("Incorrect password. Try again."), True)
        return 0
    end
    # heslo jde do roury hned (pomocnik si ho precte az na vyzvu PAM); co se pise dal, je novy pokus
    call wl.lock_secret_write(child[1])
    call lglib.close_fd(child[1])
    state["auth"] = child
    # PAM bez odpovedi (sitove overeni bez site): po minute pokus vzdat
    call lglib.timeout_add_data(60000, auth_timeout, child[0])
    state["auth_error"] = False
    state["locked_hint"] = ""
    state["caps_at_submit"] = ui["caps"]
    ui["busy"] = True
    ui["length"] = 0
    call set_hint("", False)
    call log("auth start")
    return 0
end

function auth_timeout(pid):
    if len(state["auth"]) > 0 and state["auth"][0] == pid:
        call luxos_sys.kill(pid, 9)
    end
    return False
end

function auth_failed():
    if state["locked_hint"] != "":
        call set_hint(state["locked_hint"], True)
    elif not state["auth_error"]:
        if state["caps_at_submit"]:
            call set_hint(i18n.T("Incorrect password – Caps Lock is on"), True)
        else:
            call set_hint(i18n.T("Incorrect password. Try again."), True)
        end
    end
    call shake()
    return 0
end

function pam_message(kind, message, fingerprint):
    mins = account_locked(message)
    if mins >= 0:
        if mins > 0:
            state["locked_hint"] = i18n.TF("Too many failed attempts. The account is locked for %d min, then try again.", [mins])
        else:
            state["locked_hint"] = i18n.T("Too many failed attempts. Wait a moment, then try again.")
        end
        call set_hint(state["locked_hint"], True)
        return 0
    end
    if fingerprint:
        if kind == "info":
            state["fp_seen"] = True
            if not ui["error"]:
                call set_hint(i18n.T("Touch the fingerprint sensor or enter your password"), False)
            end
        else:
            call set_hint(i18n.T("Fingerprint not recognized. Try again or enter your password."), True)
            call shake()
        end
        return 0
    end
    if message != "":
        state["auth_error"] = kind == "error"
        call set_hint(message, kind == "error")
    end
    return 0
end

function on_auth_line(kind, line, status):
    fingerprint = kind == "fingerprint"
    call log(kind + ": " + line.split(" ")[0])
    if line == "":
        # pomocnik skoncil (i bez radku result, napr. pad): pokus neprosel
        if fingerprint:
            state["fp"] = []
            state["fp_ended"] = glib.monotonic_time()
            if not state["fp_seen"]:
                state["fp_off"] = True
            end
        elif len(state["auth"]) > 0:
            state["auth"] = []
            ui["busy"] = False
            call auth_failed()
        end
        return 0
    end
    word = text.partition(line, " ")
    if word[0] == "result":
        if word[1].startswith("ok"):
            return unlock()
        end
        if not fingerprint:
            state["auth"] = []
            ui["busy"] = False
            call auth_failed()
            # po spatnem hesle otisk znovu (mohl mezitim vyprset)
            call fingerprint_start()
        end
        return 0
    end
    if word[0] == "info" or word[0] == "error":
        call pam_message(word[0], word[1], fingerprint)
    end
    return 0
end

function fingerprint_start():
    module = env.get("LUXOS_LOCK_FPRINT_MODULE", "")
    if module == "":
        module = FPRINT_MODULE
    end
    if state["fp_off"] or len(state["fp"]) > 0 or not exists(module):
        return 0
    end
    # po skonceni (vyprseni, max-tries) az za 2 s, at ctecku netrapime smyckou
    if state["fp_ended"] != 0 and glib.monotonic_time() - state["fp_ended"] < 2000000:
        return 0
    end
    child = sys.spawn_lines([auth_program(), "fingerprint"], auth_env(), on_auth_line, "fingerprint")
    if len(child) > 0:
        call lglib.close_fd(child[1])
        state["fp"] = child
        call log("fingerprint start")
    end
    return 0
end

function unlock():
    call log("unlock")
    for child in [state["auth"], state["fp"]]:
        if len(child) > 0:
            call luxos_sys.kill(child[0], 15)
        end
    end
    call wl.unlock()
    call set_locked_hint(False)
    call quit(0)
    return 0
end

# ---- logind: LockedHint a Unlock (loginctl unlock-session) ----

function set_locked_hint(on):
    if state["system"] != 0 and state["session"] != "":
        call lgio.call_async(state["system"], LOGIN1, state["session"], "org.freedesktop.login1.Session", "SetLockedHint",
                             [on], "(b)", 2000, ignore_reply, 0)
    end
    return 0
end

function ignore_reply(data, reply, error):
    return 0
end

function on_session(data, reply, error):
    if reply == None or len(reply) == 0:
        return 0
    end
    state["session"] = String(reply[0])
    # odesilatele hlida sbernice: signal muze poslat jen vlastnik jmena org.freedesktop.login1
    call gio.subscribe_values(state["system"], LOGIN1, "org.freedesktop.login1.Session", "Unlock", state["session"], on_unlock_signal)
    if state["locked"]:
        call set_locked_hint(True)
    end
    return 0
end

function on_unlock_signal(sender, path, interface, signal, values):
    call log("logind unlock")
    return unlock()
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
    # spousti ho uzivatelska sluzba mimo relaci: "auto" = graficka relace uzivatele (jako luxos-lock-session)
    id = env.get("XDG_SESSION_ID", "")
    if id == "":
        id = "auto"
    end
    call lgio.call_async(state["system"], LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSession",
                         [id], "(s)", 2000, on_session, 0)
    return 0
end

# ---- udalosti Waylandu ----

function add_surface(output):
    id = wl.lock_surface(output)
    if id > 0:
        state["surfaces"][id] = [output, 0, 0, False]
    end
    return 0
end

function keyboard_changed(caps, group):
    ui["caps"] = caps != 0
    ui["layout"] = ""
    # rozlozeni jen pri vic nez jednom (jinak neni co splest)
    if wl.lock_layout_count() > 1:
        ui["layout"] = wl.lock_layout_code(group)
    end
    call log("keyboard caps=" + String(ui["caps"]) + " layout=" + ui["layout"])
    call redraw()
    return 0
end

function key(sym, length):
    call log("key " + String(sym) + " " + String(length))
    ui["length"] = length
    if sym == KEY_RETURN or sym == KEY_KP_ENTER:
        call submit()
    elif ui["error"] and length > 0:
        call set_hint("", False)
    end
    call fingerprint_start()
    call redraw()
    return 0
end

function event(kind, handle, a, b):
    if kind == wl.SURFACE_CONFIGURE:
        if handle in state["surfaces"]:
            s = state["surfaces"][handle]
            s[1] = a
            s[2] = b
            call log("configure " + String(a) + "x" + String(b))
            if wl.surface_scale(handle) != 1.0:
                call log("scale " + String(wl.surface_scale(handle)))
            end
            call draw_all()
        end
    elif kind == wl.KEY:
        call key(a, b)
    elif kind == wl.KEYBOARD:
        call keyboard_changed(a, b)
    elif kind == wl.LOCKED:
        state["locked"] = True
        call log("locked")
        call set_locked_hint(True)
        call fingerprint_start()
        call check_ready()
    elif kind == wl.LOCK_FINISHED:
        # pred "locked" = kompozitor zamek odmitl (jiny zamek uz bezi)
        if not state["locked"]:
            call log("denied")
            call quit(3)
        end
        call quit(1)
    elif kind == wl.OUTPUT_NEW:
        call add_surface(handle)
    elif kind == wl.OUTPUT_REMOVED:
        for id in List(state["surfaces"].keys()):
            if state["surfaces"][id][0] == handle:
                call state["surfaces"].pop(id)
            end
        end
    elif kind == wl.DISCONNECTED:
        call quit(1)
    end
    return 0
end

function main():
    call load_config()
    ui["placeholder"] = i18n.T("Enter Password")
    ui["caps_text"] = i18n.T("Caps Lock is on")
    call update_clock()
    call update_battery()
    call wl.on_event(event)
    if not wl.connect(""):
        call luxos_sys.eprint("luxos-lock: no Wayland compositor")
        call exit(1)
    end
    if wl.has("ext_session_lock_manager_v1") == 0:
        call luxos_sys.eprint("luxos-lock: compositor has no ext-session-lock-v1")
        call quit(2)
    end
    # az po pripojeni: nedumpovatelny proces nema citelne /proc/PID/exe a kompozitor by zamku nedal
    # privilegovany ext-session-lock (allowlist podle programu); heslo se zatim nezadavalo
    call sys.protect()
    call wl.lock_secret(True)
    if not wl.lock():
        call quit(3)
    end
    for output in wl.outputs():
        call add_surface(output)
    end
    call logind_start()
    call load_user()
    call glib.timeout_add((60 - lglib.localtime(lglib.now())[5]) * 1000 + 50, minute_tick)
    call glib.main()
    return 0
end

call main()
