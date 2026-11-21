# LuxOS - prihlasovaci obrazovka pro greetd (1.1.0, Wayland): bezi pod `luxwm --greeter` jako jedno okno pres
# celou obrazovku, kresli vse cairem a vypada presne jako X11 luxos-greeter (luxos_lock_draw): v klidu tapeta, hodiny
# a stav, po klavese, kliknuti nebo pohybu mysi vyzva s avatarem a polem pro heslo. Navic rada uzivatelu (vybrany
# uprostred), Jiny uzivatel (domena: volne jmeno), relace jako kulate tlacitko s nazvem pred Uspat / Restartovat /
# Vypnout (klik prepne na dalsi: LuxOS na Waylandu / LuxOS (X11)).
#
# Overeni dela greetd (PAM v greetd, ne tady): zpravy JSON pres GREETD_SOCK (luxos_greetd). Zpravy PAM (otisk prstu,
# zamceny ucet, domena, vyprsele heslo) prichazeji jako auth_message a ukazuji se jako hlaska pod polem.
#
#   luxos-greeter          beh pod greetd (GREETD_SOCK)
# Testy a ladeni: LUXOS_GREETER_TRACE=1 (udalosti na stdout), LUXOS_GREETER_CONF, LUXOS_GREETER_PASSWD,
# LUXOS_GREETER_ICONS, LUXOS_GREETER_STATE_DIR, LUXOS_GREETER_WAYLAND_SESSIONS, LUXOS_GREETER_X_SESSIONS,
# LUXOS_GREETER_SYS (koren /sys), LUXOS_GREETER_DOMAIN_INFO (JSON misto lux-domain), LUXOS_GREETER_POWER=fake
# (tlacitka napajeni bez logind, jen stopa), LUXOS_GREETER_NOW="HH:MM", LUXOS_LOCK_POWER_SUPPLY (baterie), LUXOS_LOCK_NET (sit).
load env, cairo, pango, glib, gio, gtk, json, math
load luxos_glib as lglib
load luxos_gio as lgio
load luxos_gtk as lgtk
load luxos_sys
load luxos_text as text
load luxos_i18n as i18n
load luxos_material as material
load luxos_lock_draw as draw
load luxos_lock_sys as locksys
load luxos_tokens as tokens
load luxos_greetd as greetd
load luxos_greeter_sys as gsys

CONF = "/etc/lightdm/luxos-greeter.conf"
LOGIN1 = "org.freedesktop.login1"
X11_WRAPPER = "/usr/lib/luxos/luxos-x11-session"
FPRINT_SKIP = "/run/luxos-fingerprint/password-only"
DOMAIN_UID_MIN = 100000
# relace X11 navic k LuxOS (X11): Xfce je totez bez nastaveni LuxOS, v nabidce by mylila
HIDDEN_SESSIONS = ["xfce.desktop", "xfce-wayland.desktop", "labwc.desktop"]
MOD_CTRL = 4
MOD_ALT = 8

trace = env.get("LUXOS_GREETER_TRACE", "") == "1"

ui = draw.new_ui("greeter")
# input: znaky v poli (seznam, at jde heslo smazat); visible = pole ukazuje text (jmeno, viditelna vyzva PAM)
state = {"hits": [], "users": [], "sel": 0, "sessions": [], "session": 0, "input": [], "visible": False, "login": "",
         "fd": -1, "inflight": False, "phase": "idle", "pending": None, "auth_error": False, "locked_hint": "",
         "caps_at_submit": False, "fprint": False, "fp_wait": False, "domain": None, "domain_note": "",
         "power": [], "redraw": 0, "frame_timer": 0, "soft_timer": 0, "motion": None,
         "bg_path": "", "layouts": [], "conf": {}, "idle": 0, "last_input": 0, "leaving": False, "notice": "",
         "system": 0, "legacy_gpu": False, "prompt": "",
         "prompted": False, "shown": False, "pending_click": None}


function log(line):
    if trace:
        call luxos_sys.out(line + "\n")
    end
    return 0
end

function getenv_or(name, default):
    value = env.get(name, "")
    if value == "":
        return default
    end
    return value
end

# ---- nastaveni, rozlozeni, stav mezi spustenimi ----

function load_config():
    conf = text.parse_kv(lglib.read_text(getenv_or("LUXOS_GREETER_CONF", CONF)))
    state["conf"] = conf
    ui["font"] = conf.get("font", "Inter").strip()
    fmt = conf.get("clock-format", "").strip()
    if fmt == "":
        fmt = "%-H:%M"
        if i18n.lang() == "en" and conf.get("clock-24h", "").strip() != "true":
            fmt = "%-I:%M"
        end
    end
    state["clock_fmt"] = fmt
    state["idle"] = text.to_int(conf.get("idle-timeout", "30").strip(), 30)
    state["bg_path"] = conf.get("background", "/usr/share/backgrounds/luxos/luxos-light.jpg").strip()
    return 0
end

# Rozlozeni z localed (stejny zdroj jako luxwm): cisla skupin xkb -> nazvy pro cip pod polem
function load_layouts():
    # kompozitor bere rozlozeni z prostredi pred systemovym nastavenim (luxwm system_keymap)
    layout = env.get("XKB_DEFAULT_LAYOUT", "")
    xorg = "/etc/X11/xorg.conf.d/00-keyboard.conf"
    for raw in lglib.read_text(xorg).split("\n"):
        parts = raw.strip().split("\"")
        if layout == "" and len(parts) >= 4 and parts[0].strip() == "Option" and parts[1] == "XkbLayout":
            layout = parts[3]
        end
    end
    if layout == "":
        layout = text.parse_kv(lglib.read_text("/etc/vconsole.conf")).get("XKBLAYOUT", "").strip().strip("\"")
    end
    state["layouts"] = [l.strip() for l in layout.split(",") if l.strip() != ""]
    return 0
end

function state_dir():
    return getenv_or("LUXOS_GREETER_STATE_DIR", "/var/lib/luxos-greeter")
end

function load_saved():
    return text.parse_kv(lglib.read_text(state_dir() + "/state"))
end

function save_state(extra):
    saved = load_saved()
    saved["last-user"] = current_name()
    if current_name() != "":
        saved["session." + current_name()] = state["sessions"][state["session"]]["id"]
    end
    saved.update(extra)
    lines = ""
    for key in sorted(saved.keys()):
        if saved[key] != "":
            lines = lines + key + "=" + saved[key] + "\n"
        end
    end
    safe:
        call lglib.write_atomic(state_dir() + "/state", lines)
    end
    return 0
end

# ---- uzivatele ----

function sys_root():
    return getenv_or("LUXOS_GREETER_SYS", "/sys")
end

function login_defs_range():
    low = 1000
    high = 60000
    for raw in lglib.read_text("/etc/login.defs").split("\n"):
        words = raw.strip().split(" ")
        words = [x for x in words if x != ""]
        if len(words) == 2 and words[0] == "UID_MIN" and text.is_digits(words[1]):
            low = Int(words[1])
        elif len(words) == 2 and words[0] == "UID_MAX" and text.is_digits(words[1]):
            high = Int(words[1])
        end
    end
    return [low, high]
end

function icon_for(name):
    path = getenv_or("LUXOS_GREETER_ICONS", "/var/lib/AccountsService/icons") + "/" + name
    if exists(path):
        return path
    end
    return ""
end

function load_face(path):
    face = None
    if path != "" and exists(path):
        safe:
            face = gtk.pixbuf_new_from_file(path)
        end
        if face == 0:
            face = None
        end
    end
    return face
end

# Mistni ucty z passwd (rozsah z login.defs, s prihlasovacim shellem); AccountsService pak doplni domenove
# ucty z cache a obrazky
function load_users():
    users = []
    span = login_defs_range()
    for raw in lglib.read_text(getenv_or("LUXOS_GREETER_PASSWD", "/etc/passwd")).split("\n"):
        f = raw.split(":")
        if len(f) < 7 or not text.is_digits(f[2]) or f[2] == "":
            continue
        end
        uid = Int(f[2])
        shell = f[6].strip()
        if uid < span[0] or uid > span[1] or shell.endswith("nologin") or shell.endswith("/false") or shell == "":
            continue
        end
        real = f[4].split(",")[0].strip()
        if real == "":
            real = f[0]
        end
        icon = icon_for(f[0])
        users.append({"name": f[0], "real": real, "uid": uid, "icon": icon, "face": load_face(icon), "other": False})
    end
    state["users"] = users
    call add_other()
    return 0
end

# Jiny uzivatel: v domene vzdy (domenovy ucet, ktery se tu jeste neprihlasil), jinak jen bez uctu v seznamu
function add_other():
    users = state["users"]
    users = [u for u in users if not u["other"]]
    if len(users) == 0 or state["domain"] != None:
        users.append({"name": "", "real": i18n.T("Other…"), "uid": 0, "icon": "", "face": None, "other": True})
    end
    state["users"] = users
    if state["sel"] >= len(users):
        state["sel"] = 0
    end
    return 0
end

function current():
    return state["users"][state["sel"]]
end

function current_name():
    u = current()
    if u["other"]:
        return state["login"]
    end
    return u["name"]
end

function on_accounts_list(data, reply, error):
    if reply == None or len(reply) == 0:
        return 0
    end
    for path in reply[0]:
        call lgio.call_async(state["system"], "org.freedesktop.Accounts", String(path), "org.freedesktop.DBus.Properties",
                             "GetAll", ["org.freedesktop.Accounts.User"], "(s)", 2000, on_account, 0)
    end
    return 0
end

function on_account(data, reply, error):
    if reply == None or len(reply) == 0:
        return 0
    end
    p = reply[0]
    name = String(p.get("UserName", ""))
    if name == "" or p.get("SystemAccount", False) or p.get("Locked", False):
        return 0
    end
    icon = String(p.get("IconFile", ""))
    for u in state["users"]:
        if u["name"] == name:
            if String(p.get("RealName", "")) != "":
                u["real"] = String(p["RealName"])
            end
            if u["face"] == None and icon != "":
                u["face"] = load_face(icon)
            end
            call refresh_user()
            return 0
        end
    end
    uid = Int(p.get("Uid", 0))
    if uid >= DOMAIN_UID_MIN:
        real = String(p.get("RealName", ""))
        if real == "":
            real = name
        end
        users = [u for u in state["users"] if not u["other"]]
        users.append({"name": name, "real": real, "uid": uid, "icon": icon, "face": load_face(icon), "other": False})
        selected = current()
        state["users"] = users
        call add_other()
        if selected in state["users"]:
            state["sel"] = state["users"].index(selected)
        end
        call refresh_user()
    end
    return 0
end

function refresh_user():
    u = current()
    ui["name"] = u["real"]
    ui["face"] = u["face"]
    ui["initial"] = "+" if u["other"] else ""
    call redraw()
    return 0
end

# ---- relace ----

function desktop_entry(path):
    entry = {}
    section = ""
    for raw in lglib.read_text(path).split("\n"):
        line = raw.strip()
        if line.startswith("["):
            section = line
        elif section == "[Desktop Entry]" and line.find("=") > 0:
            key = text.partition(line, "=")
            entry[key[0].strip()] = key[1].strip()
        end
    end
    return entry
end

function load_sessions():
    sessions = []
    seen = []
    dirs = [[getenv_or("LUXOS_GREETER_WAYLAND_SESSIONS", "/usr/share/wayland-sessions"), "wayland"],
            [getenv_or("LUXOS_GREETER_X_SESSIONS", "/usr/share/xsessions"), "x11"]]
    for pair in dirs:
        for file in luxos_sys.list_dir(pair[0]):
            if not file.endswith(".desktop") or file in HIDDEN_SESSIONS:
                continue
            end
            e = desktop_entry(pair[0] + "/" + file)
            if e.get("Exec", "") == "" or e.get("Hidden", "") == "true" or e.get("NoDisplay", "") == "true":
                continue
            end
            try_exec = e.get("TryExec", "")
            if try_exec != "" and glib.find_program_in_path(try_exec) == "":
                continue
            end
            id = pair[1] + ":" + file
            if id in seen:
                continue
            end
            seen.append(id)
            name = e.get("Name", file)
            desktops = e.get("DesktopNames", "").replace(";", ":").strip(":")
            sessions.append({"id": id, "name": name, "type": pair[1], "exec": e["Exec"],
                             "desktop": file[:len(file) - 8], "desktops": desktops})
        end
    end
    state["sessions"] = sessions
    return 0
end

# NVIDIA 470 a starsi (bez GBM) nebo NVIDIA bez modeset: Wayland nepobezi, vychozi je X11
function legacy_gpu():
    root = sys_root()
    version = lglib.read_text(root + "/module/nvidia/version").strip()
    if version == "":
        return False
    end
    major = text.to_int(text.partition(version, ".")[0], 0)
    if major > 0 and major < 495:
        return True
    end
    return lglib.read_text(root + "/module/nvidia_drm/parameters/modeset").strip() != "Y"
end

function session_index(id):
    for i in range(len(state["sessions"])):
        if state["sessions"][i]["id"] == id:
            return i
        end
    end
    return -1
end

function first_of_type(kind):
    for i in range(len(state["sessions"])):
        if state["sessions"][i]["type"] == kind:
            return i
        end
    end
    return -1
end

# Relace pro vybraneho uzivatele: posledni jeho, jinak LuxOS na Waylandu (na starem NVIDIA X11)
function pick_session():
    if len(state["sessions"]) == 0:
        return 0
    end
    saved = load_saved()
    choice = session_index(saved.get("session." + current_name(), ""))
    preferred = "x11" if state["legacy_gpu"] else "wayland"
    if choice < 0 or (state["legacy_gpu"] and state["sessions"][choice]["type"] == "wayland"):
        choice = session_index(preferred + ":luxos.desktop")
    end
    if choice < 0:
        choice = max(0, first_of_type(preferred))
    end
    state["session"] = choice
    return 0
end

function session_command(s):
    words = [w for w in s["exec"].split(" ") if w != "" and not w.startswith("%")]
    if s["type"] == "x11":
        return [X11_WRAPPER] + words
    end
    return words
end

function session_env(s):
    out = ["XDG_SESSION_TYPE=" + s["type"], "XDG_SESSION_DESKTOP=" + s["desktop"]]
    if s["desktops"] != "":
        out.append("XDG_CURRENT_DESKTOP=" + s["desktops"])
    end
    return out
end

# ---- domena (luxos-domain) ----

function on_domain_status(data, output, status):
    info = None
    safe:
        info = json.decode(output)
    end
    if type(info) != "Dictionary" or not info.get("joined", True) or String(info.get("domain", "")) == "":
        return 0
    end
    if String(info.get("short", "")) == "":
        info["short"] = String(info["domain"]).split(".")[0].upper()
    end
    if String(info.get("example", "")) == "":
        info["example"] = "jan@" + String(info["domain"]).lower()
    end
    state["domain"] = info
    call log("domain " + String(info["domain"]) + " online=" + String(info.get("online", None)))
    call add_other()
    call redraw()
    return 0
end

function load_domain():
    path = env.get("LUXOS_GREETER_DOMAIN_INFO", "")
    if path != "":
        call on_domain_status(0, lglib.read_text(path), 0)
        return 0
    end
    cli = "/usr/bin/lux-domain"
    if exists(cli):
        call lglib.spawn_capture([cli, "status", "--json"], on_domain_status, 0)
    end
    return 0
end

function domain_user():
    u = current()
    return state["domain"] != None and (u["other"] or u["uid"] >= DOMAIN_UID_MIN)
end

function name_placeholder():
    if state["domain"] != None:
        ex = String(state["domain"]["example"])
        return i18n.TF("Name (%s or %s)", [text.partition(ex, "@")[0], ex])
    end
    return i18n.T("Username")
end

function domain_line():
    if not domain_user():
        return ""
    end
    if state["domain_note"] != "":
        return state["domain_note"]
    end
    d = state["domain"]
    if d.get("online", None) == False:
        line = i18n.T("Offline – you will sign in with your saved password")
        left = d.get("offline_left_days", None)
        if type(left) == "Int" and left >= 0:
            line = line + " " + i18n.TF("(%d more days)", [left])
        end
        return line
    end
    return i18n.TF("Sign in to domain %s", [String(d["short"])])
end

# Zprava PAM/SSSD -> druh (jako domain_message v luxos-greeter v Pythonu)
function domain_message(message):
    t = message.lower()
    if t.find("cached credentials") >= 0 or (t.find("offline") >= 0 and t.find("password") >= 0 and t.find("change") < 0):
        return "offline"
    end
    for key in ["password expired", "password has expired", "required to change your password", "change your password now"]:
        if t.find(key) >= 0:
            return "expired"
        end
    end
    if t.find("lock") >= 0 and t.find("domain") >= 0:
        return "domain-locked"
    end
    for key in ["account expired", "account has expired", "account is disabled", "account disabled"]:
        if t.find(key) >= 0:
            return "disabled"
        end
    end
    return ""
end

# pam_faillock: ucet docasne zamceny -> minuty (0 = nevime), jinak -1 (jako v luxos-lock)
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

# ---- otisk prstu: pam_fprintd ve sluzbe greetd (luxos-fingerprint-pam) ----

function fprint_enabled():
    if env.get("LUXOS_GREETER_FPRINT", "") != "":
        return env.get("LUXOS_GREETER_FPRINT", "") == "1"
    end
    return lglib.read_text("/etc/pam.d/greetd").find("pam_fprintd") >= 0 and exists("/usr/lib/security/pam_fprintd.so")
end

function fprint_skip(name):
    if state["fprint"]:
        safe:
            call writefile(FPRINT_SKIP, name + ("\n" if name != "" else ""))
        end
    end
    return 0
end

# ---- hodiny a baterie ----

function update_clock():
    fixed = env.get("LUXOS_GREETER_NOW", "")
    if fixed != "":
        ui["clock"] = fixed
    else:
        ui["clock"] = luxos_sys.strftime_local(state["clock_fmt"])
    end
    ui["date"] = i18n.format_tm(lglib.localtime(lglib.now()), "long")
    return 0
end

function update_status():
    ui["battery"] = None
    if state["conf"].get("show-battery", "true").strip() != "false":
        ui["battery"] = locksys.battery(getenv_or("LUXOS_LOCK_POWER_SUPPLY", sys_root() + "/class/power_supply"))
    end
    ui["net"] = locksys.network(getenv_or("LUXOS_LOCK_NET", sys_root() + "/class/net"), "/proc/net/wireless")
    return 0
end

function tick():
    call update_clock()
    call update_status()
    # necinnost: rozepsane heslo a hlasky pryc (heslo nezustane na obrazovce, kdyz uzivatel odejde)
    if state["idle"] > 0 and len(state["input"]) > 0 and glib.monotonic_time() - state["last_input"] > state["idle"] * 1000000:
        call clear_input()
        call set_hint("", False)
    end
    call idle_check()
    call redraw()
    call glib.timeout_add((60 - lglib.localtime(lglib.now())[5]) * 1000 + 50, tick)
    return False
end

# ---- kresleni ----

function redraw():
    if state["redraw"] == 0 and window != 0:
        state["redraw"] = glib.idle_add(queue)
    end
    return 0
end

function queue():
    state["redraw"] = 0
    call gtk.widget_queue_draw(window)
    return False
end

function next_frame():
    state["frame_timer"] = 0
    call gtk.widget_queue_draw(window)
    return False
end

function wallpaper():
    path = state["bg_path"]
    if not exists(path):
        path = "/usr/share/backgrounds/luxos/luxos-light.jpg"
    end
    return path
end

function scale_factor():
    f = 1
    safe:
        f = gtk.monitor_scale_factor(0)
    end
    return max(1, f)
end

# Rozmazana tapeta az po prvnim snimku (start nesmi cekat), pred prvni vyzvou nejpozdeji
function prepare_soft():
    state["soft_timer"] = 0
    if window != 0:
        ms = draw.backdrop_soft(draw.backdrop(wallpaper(), gtk.widget_get_allocated_width(window),
                                              gtk.widget_get_allocated_height(window), Float(scale_factor())))
        if ms > 0:
            call log("blur " + String(ms) + " ms")
        end
    end
    return False
end

function sync_ui():
    ui["users"] = state["users"]
    ui["sel"] = state["sel"]
    ui["sessions"] = [x["name"] for x in state["sessions"]]
    ui["session_sel"] = state["session"]
    ui["power"] = [[k, i18n.T(POWER_LABELS[k])] for k in ["suspend", "reboot", "poweroff"] if k in state["power"]]
    line = domain_line()
    if line == "":
        line = state["notice"]
    end
    ui["notice"] = line
    ui["leaving"] = state["leaving"]
    if state["leaving"]:
        # posledni snimek pred startem relace: ostra tapeta bez formulare a hodin (relace zacina tapetou)
        ui["reveal"] = 0.0
        ui["rev_from"] = 0.0
        ui["rev_to"] = 0.0
    end
    return 0
end

POWER_LABELS = {"suspend": "Sleep", "reboot": "Restart", "poweroff": "Shut Down"}

function on_draw(cr, widget):
    w = gtk.widget_get_allocated_width(widget)
    h = gtk.widget_get_allocated_height(widget)
    scale = Float(scale_factor())
    call sync_ui()
    again = draw.step(ui)
    ui["scale"] = scale
    bd = draw.backdrop(wallpaper(), w, h, scale)
    call draw.frame(cr, w, h, ui, bd)
    if trace and ui["hits"] != state["hits"]:
        for h in ui["hits"]:
            call log("hit " + h[4][0] + String(h[4][1]) + " " + String(h[0]) + " " + String(h[1]) + " " + String(h[2]) + " " + String(h[3]))
        end
    end
    state["hits"] = ui["hits"]
    if bd["blur"] == None and state["soft_timer"] == 0:
        state["soft_timer"] = glib.timeout_add(30, prepare_soft)
    end
    if state["frame_timer"] == 0:
        if again:
            state["frame_timer"] = glib.timeout_add(tokens.MOTION["frame"], next_frame)
        elif ui["wake"] > 0:
            state["frame_timer"] = glib.timeout_add(ui["wake"], next_frame)
        end
    end
    if state["pending_click"] != None and len(ui["hits"]) > 0:
        call glib.idle_add(pending_click)
    end
    if not state["shown"]:
        state["shown"] = True
        call glib.timeout_add(100, mark_shown)
    end
    return False
end

# Prvni snimek je na obrazovce: greetd (luxos-greetd-splash) az ted ukonci splash Plymouthu, do te doby
# zustava videt jeho posledni obraz (bez cerne mezery a textove konzole mezi splashem a prihlasenim)
function mark_shown():
    dir = env.get("XDG_RUNTIME_DIR", "")
    if dir != "":
        safe:
            call lglib.write_atomic(dir + "/luxos-greeter-shown", "")
        end
    end
    call log("shown")
    return False
end

# Vyzva k heslu (prechod z klidu)
function show_prompt():
    state["last_input"] = glib.monotonic_time()
    if draw.prompt(ui, True):
        call prepare_soft()
        call log("prompt")
    end
    call redraw()
    return 0
end

function idle_check():
    quiet = (glib.monotonic_time() - state["last_input"]) / 1000 >= tokens.LOCK["idle_after"]
    if quiet and len(state["input"]) == 0 and not ui["busy"] and not state["leaving"] and ui["rev_to"] > 0.0:
        call draw.prompt(ui, False)
        call log("idle")
        call redraw()
    end
    return 0
end

# ---- pole a hlasky ----

function sync_field():
    ui["length"] = len(state["input"])
    # viditelny text (jmeno Jineho uzivatele) jako text pole, heslo tecky
    ui["visible_text"] = state["visible"]
    ui["text"] = "".join(state["input"]) if state["visible"] else ""
    ui["placeholder"] = state["prompt"]
    call draw.typed(ui)
    call redraw()
    return 0
end

function clear_input():
    for i in range(len(state["input"])):
        state["input"][i] = ""
    end
    state["input"] = []
    call sync_field()
    return 0
end

function set_prompt(prompt, visible):
    state["prompt"] = prompt
    state["visible"] = visible
    call sync_field()
    return 0
end

function set_hint(message, error):
    if message != ui["hint"]:
        call log("hint " + ("error " if error else "") + message)
    end
    ui["hint"] = message
    ui["error"] = error
    ui["lockout"] = False
    call redraw()
    return 0
end

function shake():
    call show_prompt()
    call draw.shake(ui)
    call log("shake")
    return 0
end

# Pole podle vybraneho uzivatele: Jiny uzivatel nejdriv jmeno, ostatni rovnou heslo
function reset_field():
    call clear_input()
    state["login"] = ""
    state["domain_note"] = ""
    if current()["other"]:
        call set_prompt(name_placeholder(), True)
    else:
        call set_prompt(i18n.T("Enter Password"), False)
    end
    return 0
end

# ---- greetd ----

function send(message):
    if state["fd"] < 0:
        state["fd"] = greetd.connect(env.get("GREETD_SOCK", ""))
        if state["fd"] < 0:
            call set_hint(i18n.T("Could not start the session."), True)
            call log("no greetd")
            return False
        end
        call greetd.watch(state["fd"], on_reply)
    end
    state["inflight"] = True
    if not greetd.send(state["fd"], message):
        call on_reply(None)
        return False
    end
    call log("send " + message["type"])
    return True
end

function create_session(name):
    state["phase"] = "auth"
    state["auth_error"] = False
    state["locked_hint"] = ""
    state["fp_wait"] = False
    ui["busy"] = True
    call redraw()
    return send({"type": "create_session", "username": name})
end

function respond(answer):
    if answer == None:
        return send({"type": "post_auth_message_response"})
    end
    return send({"type": "post_auth_message_response", "response": answer})
end

function cancel_session():
    state["phase"] = "cancel"
    return send({"type": "cancel_session"})
end

function auth_failed(description):
    if state["locked_hint"] != "":
        call set_hint(state["locked_hint"], True)
        ui["lockout"] = True
    elif state["auth_error"]:
        # hlaska z PAM uz je videt
        call redraw()
    elif domain_user() and state["domain"].get("online", None) == False:
        call set_hint(i18n.T("Incorrect password, or this account has not signed in on this computer yet (the first sign-in needs a connection to the organization network)."), True)
    elif state["caps_at_submit"]:
        call set_hint(i18n.T("Incorrect password – Caps Lock is on"), True)
    else:
        call set_hint(i18n.T("Incorrect password. Try again."), True)
    end
    call shake()
    return 0
end

function pam_message(kind, message):
    call log("message " + kind)
    found = ""
    if state["domain"] != None:
        found = domain_message(message)
    end
    if found == "offline":
        state["domain_note"] = i18n.T("Signed in offline with your saved password.")
        return 0
    elif found == "expired":
        call set_hint(i18n.T("Your password has expired. Choose a new one."), False)
        return 0
    elif found == "domain-locked" or found == "disabled":
        if found == "domain-locked":
            state["locked_hint"] = i18n.T("The account is locked by the domain administrator. Contact your IT department.")
        else:
            state["locked_hint"] = i18n.T("The account is disabled or expired in the domain. Contact your IT department.")
        end
        call set_hint(state["locked_hint"], True)
        return 0
    end
    mins = account_locked(message)
    if mins >= 0:
        if mins > 0:
            state["locked_hint"] = i18n.TF("Too many failed attempts. The account is locked for %d min, then try again.", [mins])
        else:
            state["locked_hint"] = i18n.T("Too many failed attempts. Wait a moment, then try again.")
        end
        call set_hint(state["locked_hint"], True)
        ui["lockout"] = True
        return 0
    end
    # pam_fprintd mluvi pred vyzvou k heslu (text muze byt v jinem jazyce)
    if state["fprint"] and state["phase"] == "auth" and not state["prompted"]:
        if kind == "info":
            state["fp_wait"] = True
            ui["busy"] = False
            if not ui["error"]:
                call set_hint(i18n.T("Touch the fingerprint sensor or enter your password"), False)
            end
            return 0
        end
        if state["fp_wait"]:
            call set_hint(i18n.T("Fingerprint not recognized. Try again or enter your password."), True)
            call shake()
            return 0
        end
    end
    if message != "":
        if kind == "error":
            state["auth_error"] = True
        end
        call set_hint(message, kind == "error")
    end
    return 0
end

# Vyzvy PAM pri zmene hesla (pam_sss, pam_unix) -> popisek pole
function prompt_label(message, secret):
    t = message.strip().rstrip(":").strip()
    low = t.lower()
    if secret:
        if t == "" or low == "password" or low == "heslo":
            return i18n.T("Enter Password")
        end
        for key in ["current password", "(current)", "old password", "current kerberos password"]:
            if low.find(key) >= 0:
                return i18n.T("Current Password")
            end
        end
        for key in ["retype", "reenter", "re-enter", "repeat", "confirm"]:
            if low.find(key) >= 0:
                return i18n.T("Repeat New Password")
            end
        end
        if low.find("new password") >= 0:
            return i18n.T("New Password")
        end
        return t
    end
    if low == "login" or low == "username" or low == "user name":
        return name_placeholder()
    end
    return t
end

function on_reply(reply):
    state["inflight"] = False
    if reply == None or type(reply) != "Dictionary":
        call log("greetd gone")
        if state["fd"] >= 0:
            call greetd.close(state["fd"])
        end
        state["fd"] = -1
        state["phase"] = "idle"
        ui["busy"] = False
        call set_hint(i18n.T("Could not start the session."), True)
        return 0
    end
    kind = String(reply.get("type", ""))
    call log("reply " + kind + " phase=" + state["phase"])
    if state["phase"] == "cancel":
        state["phase"] = "idle"
        ui["busy"] = False
        call redraw()
        if state["pending"] != None and len(state["pending"]) > 0:
            call start_auth()
        end
        return 0
    end
    if kind == "success":
        if state["phase"] == "start":
            call leave()
        else:
            call start_session()
        end
    elif kind == "error":
        description = String(reply.get("description", ""))
        call log("error " + String(reply.get("error_type", "")) + " " + description)
        failed_start = state["phase"] == "start"
        state["pending"] = None
        call clear_input()
        call cancel_session()
        if failed_start:
            state["leaving"] = False
            call set_hint(i18n.T("Could not start the session."), True)
            call shake()
        elif String(reply.get("error_type", "")) == "auth_error":
            call auth_failed(description)
        else:
            call set_hint(description, True)
            call shake()
        end
        if current()["other"]:
            call reset_field()
        end
    elif kind == "auth_message":
        message = String(reply.get("auth_message", ""))
        style = String(reply.get("auth_message_type", ""))
        if style == "secret" or style == "visible":
            state["prompted"] = True
            state["fp_wait"] = False
            if state["pending"] != None:
                answer = state["pending"]
                state["pending"] = None
                call respond(answer)
            else:
                ui["busy"] = False
                call set_prompt(prompt_label(message, style == "secret"), style == "visible")
            end
        else:
            call pam_message(style, message)
            call respond(None)
        end
    end
    call redraw()
    return 0
end

function start_auth():
    name = current_name()
    if name == "":
        return 0
    end
    state["prompted"] = False
    call fprint_skip("" if state["pending"] == None else name)
    call create_session(name)
    return 0
end

function start_session():
    s = state["sessions"][state["session"]]
    state["phase"] = "start"
    extra = {}
    if s["type"] == "wayland":
        extra["wayland-start"] = String(gsys.epoch())
    end
    call save_state(extra)
    call log("start " + s["id"] + " " + " ".join(session_command(s)))
    call send({"type": "start_session", "cmd": session_command(s), "env": session_env(s)})
    return 0
end

# greetd relaci spusti, az greeter skonci: posledni snimek je tapeta bez formulare (luxwm --greeter pak skonci s nim)
function leave():
    state["leaving"] = True
    call gtk.widget_queue_draw(window)
    call log("leaving")
    call glib.timeout_add(120, quit_now)
    return 0
end

function quit_now():
    call gtk.main_quit()
    return False
end

# Odeslani pole (Enter, sipka): jmeno Jineho uzivatele, nebo heslo / odpoved na vyzvu PAM
function submit():
    if state["leaving"]:
        return 0
    end
    typed = "".join(state["input"])
    if current()["other"] and state["login"] == "":
        if typed.strip() == "":
            return 0
        end
        state["login"] = typed.strip()
        call clear_input()
        call set_prompt(i18n.T("Enter Password"), False)
        call start_auth()
        return 0
    end
    if typed == "" and not state["visible"]:
        return 0
    end
    state["caps_at_submit"] = ui["caps"]
    call clear_input()
    call set_hint("", False)
    ui["busy"] = True
    if state["phase"] == "auth" and not state["inflight"]:
        call respond(typed)
    elif state["phase"] == "idle":
        state["pending"] = typed
        call start_auth()
    else:
        # vyzva jeste neprisla (otisk prstu, PAM premysli): poslat s ni
        state["pending"] = typed
    end
    call redraw()
    return 0
end

function select_user(index):
    if index < 0 or index >= len(state["users"]) or index == state["sel"]:
        return 0
    end
    state["sel"] = index
    state["pending"] = None
    call refresh_user()
    call pick_session()
    call set_hint("", False)
    call reset_field()
    call log("user " + current()["name"] + " session " + state["sessions"][state["session"]]["id"])
    if state["phase"] != "idle":
        call cancel_session()
    end
    if state["fprint"] and not current()["other"]:
        call start_auth()
    end
    return 0
end

function choose_session(index):
    if index >= 0 and index < len(state["sessions"]) and index != state["session"]:
        state["session"] = index
        state["notice"] = ""
        call log("session " + state["sessions"][state["session"]]["id"])
    end
    call redraw()
    return 0
end

# ---- napajeni (logind) ----

function on_can(kind, reply, error):
    if reply != None and len(reply) > 0 and (String(reply[0]) == "yes" or String(reply[0]) == "challenge"):
        state["power"].append(kind)
        call redraw()
    end
    return 0
end

function load_power():
    if env.get("LUXOS_GREETER_POWER", "") == "fake":
        state["power"] = ["suspend", "reboot", "poweroff"]
        return 0
    end
    if state["system"] == 0:
        return 0
    end
    for pair in [["suspend", "CanSuspend"], ["reboot", "CanReboot"], ["poweroff", "CanPowerOff"]]:
        call lgio.call_async(state["system"], LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                             pair[1], [], "", 3000, on_can, pair[0])
    end
    return 0
end

function on_power_done(kind, reply, error):
    if reply == None:
        call log("power " + kind + " failed: " + error)
        call set_hint(i18n.T("This action is not available right now."), True)
    end
    return 0
end

function power(kind):
    call log("power " + kind)
    if env.get("LUXOS_GREETER_POWER", "") == "fake" or state["system"] == 0:
        return 0
    end
    methods = {"suspend": "Suspend", "reboot": "Reboot", "poweroff": "PowerOff"}
    call lgio.call_async(state["system"], LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                         methods[kind], [False], "(b)", 5000, on_power_done, kind)
    return 0
end

# ---- vstup ----

function update_caps():
    caps = gsys.caps_lock()
    if caps != ui["caps"]:
        ui["caps"] = caps
        call log("caps " + String(caps))
        call redraw()
    end
    return False
end

# Rozlozeni vpravo nahore vzdy, pod polem jen pri vic rozlozenich (jako X11 luxos-greeter)
function update_layout(group):
    ui["layouts"] = len(state["layouts"])
    name = "US"
    if group < len(state["layouts"]) and state["layouts"][group] != "":
        name = state["layouts"][group].upper()
    end
    if name != ui["layout"]:
        ui["layout"] = name
        call log("layout " + name)
        call redraw()
    end
    return 0
end

function on_key(event, widget):
    name = gtk.event_key_name(event)
    mods = gtk.event_key_state(event)
    call update_layout(gsys.key_group(event))
    call glib.timeout_add(30, update_caps)
    if state["leaving"]:
        return True
    end
    if name == "Escape" and len(state["input"]) == 0 and not current()["other"]:
        # Esc s prazdnym polem: zpet do klidu
        state["last_input"] = 0
        call idle_check()
        return True
    end
    call show_prompt()
    if name == "Return" or name == "KP_Enter":
        call submit()
    elif name == "BackSpace":
        if len(state["input"]) > 0:
            state["input"][len(state["input"]) - 1] = ""
            call state["input"].pop()
            call sync_field()
        elif current()["other"] and state["login"] != "" and state["phase"] == "idle":
            call reset_field()
        end
    elif name == "Escape":
        call clear_input()
        call set_hint("", False)
        if current()["other"]:
            if state["phase"] != "idle":
                call cancel_session()
            end
            call reset_field()
        end
    elif (name == "Left" or name == "Right") and len(state["input"]) == 0 and (mods & (MOD_CTRL | MOD_ALT)) == 0:
        call select_user(state["sel"] + (1 if name == "Right" else -1))
    elif (mods & MOD_CTRL) != 0 and name == "u":
        call clear_input()
    elif (mods & (MOD_CTRL | MOD_ALT)) == 0:
        ch = gtk.event_key_text(event)
        if ch != "" and ord(ch) >= 32 and len(state["input"]) < 512:
            state["input"].append(ch)
            if ui["error"]:
                call set_hint("", False)
            end
            call sync_field()
        end
    end
    return True
end

function on_key_release(event, widget):
    call update_layout(gsys.key_group(event))
    call update_caps()
    return False
end

function hit_at(x, y):
    for h in ui["hits"]:
        if x >= h[0] and x < h[0] + h[2] and y >= h[1] and y < h[1] + h[3]:
            return h
        end
    end
    return None
end

function on_press(event, widget):
    x = gtk.event_x(event)
    y = gtk.event_y(event)
    if ui["rev_to"] <= 0.0:
        call show_prompt()
        return True
    end
    state["last_input"] = glib.monotonic_time()
    if len(ui["hits"]) == 0:
        # vyzva se prave objevuje (pohyb mysi) a jeste nebyla nakreslena: klik vyridit po prvnim snimku s ni
        state["pending_click"] = [x, y]
        call redraw()
        return True
    end
    call click_at(x, y)
    return True
end

function pending_click():
    if state["pending_click"] != None:
        p = state["pending_click"]
        state["pending_click"] = None
        call click_at(p[0], p[1])
    end
    return False
end

function click_at(x, y):
    h = hit_at(x, y)
    if h == None:
        return 0
    end
    action = h[4]
    call log("click " + action[0])
    if action[0] == "user":
        call select_user(action[1])
    elif action[0] == "session":
        # jako X11: relace se prepina kliknutim na dalsi
        if len(state["sessions"]) > 0:
            call choose_session((state["session"] + 1) % len(state["sessions"]))
        end
    elif action[0] == "go":
        call submit()
    elif action[0] == "layout" or action[0] == "chip":
        call log("layout click")
    elif action[0] != "field":
        call power(action[0])
    end
    return 0
end

# Vychozi bod pro "vetsi pohyb" je uz vstup ukazatele do okna (kurzor nad greeterem pri startu)
function on_enter(event, widget):
    if state["motion"] == None:
        state["motion"] = [gtk.event_x(event), gtk.event_y(event)]
    end
    return False
end

# Pohyb mysi: zvyrazneni pod kurzorem; vetsi pohyb v klidu ukaze vyzvu (ne chveni pri startu)
function on_motion(event, widget):
    x = gtk.event_x(event)
    y = gtk.event_y(event)
    if state["motion"] == None:
        state["motion"] = [x, y]
    end
    if ui["rev_to"] <= 0.0:
        if abs(x - state["motion"][0]) + abs(y - state["motion"][1]) > 8.0:
            call show_prompt()
        end
        return False
    end
    state["last_input"] = glib.monotonic_time()
    h = hit_at(x, y)
    key = ""
    if h != None:
        key = h[4][0]
        if key == "user":
            key = key + String(h[4][1])
        end
    end
    if key != ui["hover"]:
        ui["hover"] = key
        call redraw()
    end
    return False
end

# ---- start ----

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

# Posledni relace na Waylandu skoncila hned po startu (kompozitor nenabehl): nabidnout X11
function check_failed_start():
    saved = load_saved()
    started = text.to_int(saved.get("wayland-start", ""), 0)
    if started > 0:
        if gsys.epoch() - started < 10 and first_of_type("x11") >= 0:
            state["session"] = first_of_type("x11")
            state["notice"] = i18n.TF("The desktop could not start. %s is selected.", [state["sessions"][state["session"]]["name"]])
            call log("wayland session failed, x11 selected")
        end
        call save_state({"wayland-start": ""})
    end
    return 0
end

window = 0
# rozepsane heslo: proces nejde cist ani ladit (testy se stopou meri PSS, proto bez ochrany)
if not trace:
    call locksys.protect()
end
call glib.set_prgname("luxos-greeter")
call gtk.init()
call load_config()
call load_layouts()
state["legacy_gpu"] = legacy_gpu()
state["system"] = system_bus()
state["fprint"] = fprint_enabled()
ui["caps_text"] = i18n.T("Caps Lock is on")
ui["lang"] = i18n.lang()
call load_users()
call load_sessions()
last = load_saved()
for i in range(len(state["users"])):
    if state["users"][i]["name"] == last.get("last-user", "") and last.get("last-user", "") != "":
        state["sel"] = i
    end
end
call refresh_user()
call pick_session()
call check_failed_start()
call reset_field()
call update_clock()
call update_status()
call load_domain()
call load_power()
if state["system"] != 0:
    call lgio.call_async(state["system"], "org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                         "org.freedesktop.Accounts", "ListCachedUsers", [], "", 3000, on_accounts_list, 0)
end

settings = gtk.settings_get_default()
call gtk.object_set_string(settings, "gtk-cursor-theme-name", state["conf"].get("cursor-theme", "WhiteSur-cursors").strip())
window = gtk.window_new("LuxOS")
call gtk.window_set_decorated(window, False)
call gtk.widget_set_app_paintable(window, True)
call gtk.widget_add_events(window, gtk.BUTTON_PRESS_MASK + gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK + gtk.POINTER_MOTION_MASK
                          + gtk.ENTER_NOTIFY_MASK)
call gtk.connect(window, "draw", on_draw)
call gtk.connect(window, "key-press-event", on_key)
call gtk.connect(window, "key-release-event", on_key_release)
call gtk.connect(window, "button-press-event", on_press)
call gtk.connect(window, "motion-notify-event", on_motion)
call gtk.connect(window, "enter-notify-event", on_enter)
call gtk.connect(window, "destroy", quit_now)
geometry = []
safe:
    geometry = gtk.monitor_geometry(0)
end
if len(geometry) == 4 and geometry[2] > 0:
    # X11 bez spravce oken (stary NVIDIA): fullscreen nikdo neudela, okno ma velikost monitoru
    call gtk.window_move(window, geometry[0], geometry[1])
    call gtk.window_set_default_size(window, geometry[2], geometry[3])
end
call gtk.window_fullscreen(window)
call gtk.widget_show_all(window)
call update_caps()
if state["fprint"] and not current()["other"]:
    call start_auth()
end
call glib.timeout_add((60 - lglib.localtime(lglib.now())[5]) * 1000 + 50, tick)
call log("ready users=" + String(len(state["users"])) + " sessions=" + String(len(state["sessions"]))
    + " session=" + (state["sessions"][state["session"]]["id"] if len(state["sessions"]) > 0 else "none")
    + " legacy_gpu=" + String(state["legacy_gpu"]))
call gtk.main()
if state["fd"] >= 0:
    call greetd.close(state["fd"])
end
exit(0)
