# LuxOS - prihlasovaci obrazovka pro greetd (1.1.0, Wayland): bezi pod `luxwm --greeter` jako jedno okno pres
# celou obrazovku, kresli vse cairem ve vzhledu zamku (luxos_lock_draw: rozostrena tapeta, datum a hodiny, avatar,
# matne pole pro heslo, Caps Lock, rozlozeni, baterie). Navic radek uzivatelu, Jiny uzivatel (domena: volne jmeno),
# volba relace (LuxOS na Waylandu / LuxOS (X11)) a tlacitka Uspat / Restartovat / Vypnout.
#
# Overeni dela greetd (PAM v greetd, ne tady): zpravy JSON pres GREETD_SOCK (luxos_greetd). Zpravy PAM (otisk prstu,
# zamceny ucet, domena, vyprsele heslo) prichazeji jako auth_message a ukazuji se jako hlaska pod polem.
#
#   luxos-greeter          beh pod greetd (GREETD_SOCK)
# Testy a ladeni: LUXOS_GREETER_TRACE=1 (udalosti na stdout), LUXOS_GREETER_CONF, LUXOS_GREETER_PASSWD,
# LUXOS_GREETER_ICONS, LUXOS_GREETER_STATE_DIR, LUXOS_GREETER_WAYLAND_SESSIONS, LUXOS_GREETER_X_SESSIONS,
# LUXOS_GREETER_SYS (koren /sys), LUXOS_GREETER_DOMAIN_INFO (JSON misto lux-domain), LUXOS_GREETER_POWER=fake
# (tlacitka napajeni bez logind, jen stopa), LUXOS_GREETER_NOW="HH:MM", LUXOS_LOCK_POWER_SUPPLY (baterie).
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

ui = {"font": "Inter", "clock": "", "date": "", "name": "", "face": None, "length": 0, "placeholder": "",
      "hint": "", "error": False, "caps": False, "caps_text": "", "layout": "", "busy": False, "shake": 0.0,
      "battery": None}
# input: znaky v poli (seznam, at jde heslo smazat); visible = pole ukazuje text (jmeno, viditelna vyzva PAM)
state = {"users": [], "sel": 0, "sessions": [], "session": 0, "input": [], "visible": False, "login": "",
         "fd": -1, "inflight": False, "phase": "idle", "pending": None, "auth_error": False, "locked_hint": "",
         "caps_at_submit": False, "fprint": False, "fp_wait": False, "domain": None, "domain_note": "",
         "power": [], "hits": [], "redraw": 0, "shake_start": 0, "shake_timer": 0, "glass": None, "glass_size": [0, 0],
         "bg_path": "", "layouts": [], "conf": {}, "idle": 0, "last_input": 0, "leaving": False, "notice": "",
         "system": 0, "legacy_gpu": False, "prompt": "",
         "prompted": False}


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
            face = gtk.pixbuf_new_from_file_at_scale(path, 256, 256, True)
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

function update_battery():
    ui["battery"] = None
    if state["conf"].get("show-battery", "true").strip() == "false":
        return 0
    end
    base = getenv_or("LUXOS_LOCK_POWER_SUPPLY", sys_root() + "/class/power_supply")
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
        ui["battery"] = [found[0], found[1] == "Charging" or (found[1] != "Discharging" and mains)]
    end
    return 0
end

function tick():
    call update_clock()
    call update_battery()
    # necinnost: rozepsane heslo a hlasky pryc (heslo nezustane na obrazovce, kdyz uzivatel odejde)
    if state["idle"] > 0 and len(state["input"]) > 0 and glib.monotonic_time() - state["last_input"] > state["idle"] * 1000000:
        call clear_input()
        call set_hint("", False)
    end
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

function glass_for(w, h):
    if state["glass"] == None:
        path = state["bg_path"]
        if not exists(path):
            path = "/usr/share/backgrounds/luxos/luxos-light.jpg"
        end
        state["glass"] = material.glass(path)
    end
    return state["glass"]
end

function hit(x, y, w, h, action):
    state["hits"].append([x, y, w, h, action])
    return 0
end

function small_text(cr, message, size, cx, y, alpha):
    return draw.centered_text(cr, message, draw.font(ui, "Semi-Bold", size), cx, y, alpha, 2.0)
end

function draw_users(cr, w, cy, d, u):
    users = state["users"]
    n = len(users)
    if n < 2:
        return 0
    end
    small = draw.px(u, 64.0, 44)
    step = d * 0.5 + small * 0.5 + draw.px(u, 34.0, 20)
    gap = small + draw.px(u, 56.0, 34)
    cx = Float(w) / 2.0
    name_size = draw.px(u, 13.0, 11)
    for i in range(n):
        if i == state["sel"]:
            continue
        end
        k = i - state["sel"]
        side = 1.0 if k > 0 else -1.0
        x = cx + side * (step + (Float(abs(k)) - 1.0) * gap)
        if x < small or x > Float(w) - small:
            continue
        end
        other = users[i]
        face = {"font": ui["font"], "face": other["face"], "name": other["real"]}
        if other["other"]:
            face["name"] = "+"
        end
        call material.push_group(cr)
        call draw.avatar(cr, x, cy, small, face)
        call small_text(cr, other["real"], name_size, x, cy + small / 2.0 + draw.px(u, 6.0, 4), 1.0)
        call material.pop_group_to_source(cr)
        call cairo.paint_with_alpha(cr, 0.72)
        call hit(x - small / 2.0 - 8.0, cy - small / 2.0 - 8.0, small + 16.0, small + 16.0 + name_size * 1.6, ["user", i])
    end
    return 0
end

function icon_power(cr, cx, cy, s):
    r = s * 0.36
    call cairo.set_line_width(cr, max(1.4, s * 0.085))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy + s * 0.03, r, -cairo.PI / 2.0 + 0.62, -cairo.PI / 2.0 - 0.62 + 2.0 * cairo.PI)
    call cairo.stroke(cr)
    call cairo.move_to(cr, cx, cy - s * 0.45)
    call cairo.line_to(cr, cx, cy - s * 0.05)
    call cairo.stroke(cr)
    return 0
end

function icon_restart(cr, cx, cy, s):
    r = s * 0.36
    call cairo.set_line_width(cr, max(1.4, s * 0.085))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    a0 = -cairo.PI / 2.0 + 0.25
    a1 = -cairo.PI / 2.0 + 2.0 * cairo.PI - 0.75
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, a0, a1)
    call cairo.stroke(cr)
    ex = cx + r * math.cos(a1)
    ey = cy + r * math.sin(a1)
    tx = -math.sin(a1)
    ty = math.cos(a1)
    nx = math.cos(a1)
    ny = math.sin(a1)
    k = s * 0.2
    call cairo.move_to(cr, ex + tx * k * 0.9, ey + ty * k * 0.9)
    call cairo.line_to(cr, ex + nx * k * 0.75 - tx * k * 0.25, ey + ny * k * 0.75 - ty * k * 0.25)
    call cairo.line_to(cr, ex - nx * k * 0.75 - tx * k * 0.25, ey - ny * k * 0.75 - ty * k * 0.25)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    return 0
end

function icon_sleep(cr, cx, cy, s):
    r = s * 0.40
    call cairo.save(cr)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * cairo.PI)
    call cairo.clip(cr)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * cairo.PI)
    call cairo.move_to(cr, cx + r * 0.55 + r * 0.82, cy - r * 0.45)
    call cairo.arc(cr, cx + r * 0.55, cy - r * 0.45, r * 0.82, 0.0, 2.0 * cairo.PI)
    call lgtk.cairo_set_fill_rule(cr, 1)
    call cairo.fill(cr)
    call cairo.restore(cr)
    return 0
end

function icon_session(cr, cx, cy, s):
    q = s * 0.3
    g = s * 0.08
    for dx in [-1.0, 1.0]:
        for dy in [-1.0, 1.0]:
            x = cx + g / 2.0 if dx > 0.0 else cx - g / 2.0 - q
            y = cy + g / 2.0 if dy > 0.0 else cy - g / 2.0 - q
            call material.rounded_path(cr, x, y, q, q, q * 0.25)
            call cairo.fill(cr)
        end
    end
    return 0
end

function round_button(cr, w, h, cx, cy, d, gl, kind, label, u):
    call cairo.save(cr)
    call material.push_group(cr)
    if gl != None:
        call material.paint(cr, cx - d / 2.0, cy - d / 2.0, d, d, d / 2.0, cx - d / 2.0, cy - d / 2.0, 0, gl, material.map_for(gl, w, h))
    end
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, d / 2.0, 0.0, 2.0 * cairo.PI)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.16)
    call cairo.fill(cr)
    call material.pop_group_to_source(cr)
    call cairo.paint(cr)
    call cairo.restore(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    if kind == "poweroff":
        call icon_power(cr, cx, cy, d * 0.46)
    elif kind == "reboot":
        call icon_restart(cr, cx, cy, d * 0.46)
    elif kind == "suspend":
        call icon_sleep(cr, cx, cy, d * 0.46)
    else:
        call icon_session(cr, cx, cy, d * 0.46)
    end
    size = small_text(cr, label, draw.px(u, 13.0, 11), cx, cy + d / 2.0 + draw.px(u, 5.0, 3), 0.92)
    call hit(cx - max(d, Float(size[0])) / 2.0, cy - d / 2.0, max(d, Float(size[0])), d + Float(size[1]) + 6.0, [kind, 0])
    return 0
end

POWER_LABELS = {"suspend": "Sleep", "reboot": "Restart", "poweroff": "Shut Down"}

function draw_buttons(cr, w, h, gl, u):
    d = draw.px(u, 44.0, 34)
    cy = Float(h) - draw.px(u, 42.0, 26) - draw.px(u, 20.0, 14) - d / 2.0
    space = draw.px(u, 40.0, 26) + d
    kinds = [k for k in ["suspend", "reboot", "poweroff"] if k in state["power"]]
    x = Float(w) / 2.0 - Float(len(kinds) - 1) * space / 2.0
    for k in kinds:
        call round_button(cr, w, h, x, cy, d, gl, k, i18n.T(POWER_LABELS[k]), u)
        x = x + space
    end
    # volba relace vlevo dole (jen kdyz je z ceho vybirat)
    if len(state["sessions"]) > 1:
        call round_button(cr, w, h, draw.px(u, 42.0, 26) + d, cy, d, gl, "session",
                          state["sessions"][state["session"]]["name"], u)
    end
    return 0
end

function frame(cr, w, h):
    state["hits"] = []
    u = draw.unit(h)
    gl = glass_for(w, h)
    call draw.background(cr, w, h, gl)
    if state["leaving"]:
        # posledni snimek pred startem relace: jen tapeta, prechod bez formulare a hodin
        return 0
    end
    call draw.clock(cr, w, h, ui, u)
    call draw.status(cr, w, ui, u)
    r = draw.field(cr, w, h, ui, gl, u)
    call hit(r[0], r[1], r[2], r[3], ["field", 0])
    fy = r[1]
    gap = draw.px(u, 14.0, 9)
    name_size = draw.px(u, 17.0, 13)
    name_y = fy - gap - name_size * 1.3
    d = draw.px(u, 104.0, 64)
    cy = name_y - draw.px(u, 8.0, 5) - d / 2.0
    call draw.avatar(cr, Float(w) / 2.0, cy, d, {"font": ui["font"], "face": ui["face"],
                                                 "name": "+" if current()["other"] else ui["name"]})
    call draw.centered_text(cr, ui["name"], draw.font(ui, "Semi-Bold", name_size), Float(w) / 2.0, name_y, 1.0, 3.0 * u)
    call draw_users(cr, w, cy, d, u)
    hint_y = fy + r[3] + gap
    call draw.hint(cr, w, hint_y, ui, u)
    row_y = hint_y + draw.px(u, 22.0, 16) + gap
    call draw.keyboard_row(cr, w, row_y, ui, u)
    line = domain_line()
    if line == "":
        line = state["notice"]
    end
    if line != "":
        call small_text(cr, line, draw.px(u, 13.0, 10), Float(w) / 2.0, row_y + draw.px(u, 24.0, 18) + gap, 0.85)
    end
    call draw_buttons(cr, w, h, gl, u)
    return 0
end

function on_draw(cr, widget):
    w = gtk.widget_get_allocated_width(widget)
    h = gtk.widget_get_allocated_height(widget)
    call frame(cr, w, h)
    return False
end

# ---- pole a hlasky ----

function sync_field():
    ui["length"] = len(state["input"])
    if state["visible"] and len(state["input"]) > 0:
        # viditelny text (jmeno): kresli se jako popisek pole
        ui["placeholder"] = "".join(state["input"])
        ui["length"] = 0
    else:
        ui["placeholder"] = state["prompt"]
    end
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

function next_session():
    if len(state["sessions"]) > 1:
        state["session"] = (state["session"] + 1) % len(state["sessions"])
        state["notice"] = ""
        call log("session " + state["sessions"][state["session"]]["id"])
        call redraw()
    end
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

function update_layout(group):
    name = ""
    if len(state["layouts"]) > 1 and group < len(state["layouts"]):
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
    state["last_input"] = glib.monotonic_time()
    name = gtk.event_key_name(event)
    mods = gtk.event_key_state(event)
    call update_layout(gsys.key_group(event))
    call glib.timeout_add(30, update_caps)
    if state["leaving"]:
        return True
    end
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

function on_press(event, widget):
    state["last_input"] = glib.monotonic_time()
    x = gtk.event_x(event)
    y = gtk.event_y(event)
    for h in state["hits"]:
        if x >= h[0] and x < h[0] + h[2] and y >= h[1] and y < h[1] + h[3]:
            action = h[4]
            call log("click " + action[0])
            if action[0] == "user":
                call select_user(action[1])
            elif action[0] == "session":
                call next_session()
            elif action[0] == "field":
                # sipka v poli = odeslat
                if x > h[0] + h[2] - h[3]:
                    call submit()
                end
            else:
                call power(action[0])
            end
            return True
        end
    end
    return True
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
call update_battery()
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
call gtk.widget_add_events(window, gtk.BUTTON_PRESS_MASK + gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
call gtk.connect(window, "draw", on_draw)
call gtk.connect(window, "key-press-event", on_key)
call gtk.connect(window, "key-release-event", on_key_release)
call gtk.connect(window, "button-press-event", on_press)
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
