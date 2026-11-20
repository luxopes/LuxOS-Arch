# LuxOS - luxwm: spravce oken desktopu na Waylandu (1.1.0, architektura R2). Kompozitor kresli
# libluxcomp v C (packages/luxcomp), tady je jen politika: umisteni noveho okna jako xfwm4 "luxos",
# zamereni klikem, Alt+Tab a Alt+` s koncem pri pusteni modifikatoru, plochy s prejezdem, cela
# obrazovka nad listou, maximalizace do pouzitelne plochy, minimalizace, zahlavi z luxos_tokens
# a klavesove zkratky z luxwm.conf. Popis: packages/luxwm/README.md
#
#   luxwm [-d] [PRIKAZ...]    -d = stopa rozhodnuti na stderr; prikazy se spusti po startu
# Signaly: SIGTERM/SIGINT konec, SIGHUP znovu nacte luxwm.conf a vzhled, SIGUSR1 jen vzhled
# (prepnuti svetly/tmavy), SIGUSR2 vypise stav na stderr (testy).
# IPC pro shell (lista, Dock, nastaveni): $XDG_RUNTIME_DIR/luxwm-$WAYLAND_DISPLAY.sock, radkovy JSON,
# popis docs/developers/luxwm-ipc.md. Rozlozeni klavesnice z org.freedesktop.locale1, prepsane
# polozkami xkb_* v luxwm.conf.
load glib, gio, json
load luxos_luxcomp as lc
load luxos_tokens as tokens

CASCADE = 28
DOUBLE_CLICK_US = 400000
SYSTEM_CONFIG = "/usr/share/luxwm/luxwm.conf"
PRIVILEGED = "/usr/share/luxwm/privileged.conf"

# Kdyz chybi konfigurace, aspon zakladni ovladani klavesnici
FALLBACK_KEYS = {
    "<Alt>Tab": "cycle_windows_key",
    "<Alt><Shift>Tab": "cycle_reverse_windows_key",
    "<Alt>grave": "cycle_app_windows_key",
    "<Alt>F4": "close_window_key",
    "<Primary><Super>Left": "left_workspace_key",
    "<Primary><Super>Right": "right_workspace_key",
    "<Primary><Alt>t": "exec luxos-terminal"
}

MODS = {"primary": lc.MOD_CTRL, "control": lc.MOD_CTRL, "ctrl": lc.MOD_CTRL, "shift": lc.MOD_SHIFT,
        "alt": lc.MOD_ALT, "mod1": lc.MOD_ALT, "super": lc.MOD_SUPER, "mod4": lc.MOD_SUPER}

trace = False
settings = {}
binds = {}           # id zkratky -> akce
outputs = []
ws = []              # id ploch, cur = index zobrazene
cur = 0
mru = []             # okna od naposledy zamereneho
saved = {}           # okno -> [x, y, w, h] pred maximalizaci, pulkou nebo celou obrazovkou
maxed = {}
# okno -> vyska zahlavi pred celou obrazovkou; VIEW_FULLSCREEN a DECO_TOP jadra se zmeni az po
# potvrzeni klientem, politika potrebuje stav hned
full = {}
tiled = {}           # okno -> "left" / "right"
hidden_desktop = []  # okna schovana "ukazat plochu"
last_title_click = [0, 0]

# Alt+Tab: seznam, poloha, puvodni okno, docasne ukazana minimalizovana okna, zkratka Esc
cycle = {"on": False, "list": [], "pos": 0, "from": 0, "shown": [], "cancel": 0}

LOCALE = "org.freedesktop.locale1"
IPC_TOPICS = ["window", "workspace", "keyboard", "output", "theme"]
# informace o cizich oknech a jejich ovladani jen pro allowlist (jako wlr-foreign-toplevel)
PRIVILEGED_TOPICS = ["window"]
PRIVILEGED_COMMANDS = ["list_windows", "focus_window"]

ipc = {}             # klient IPC -> {"privileged": bool, "topics": [...]}
keyboard = {"layouts": [], "locale": {}}
look = {"dark": False}
last_window = [-1, "", ""]

function log(text):
    call glib.report("luxwm: " + text + chr(10))
end

function note(text):
    if trace:
        call log(text)
    end
end

function vget(v, prop):
    return lc.view_get(v, prop)
end

# ---- konfigurace -----------------------------------------------------------------------------

# luxwm.conf: "nazev = hodnota", za radkem [keys] zkratky ve tvaru luxos-shortcuts/xfconf
# ("<Primary><Super>Left = left_workspace_key", "<Super>t = exec luxos-terminal"); prazdna
# hodnota zkratku vypne. Uzivatelsky soubor prepisuje systemovy po polozkach.
function read_config(path, general, keys):
    if not exists(path):
        return False
    end
    section = ""
    for raw in readfile(path).split(chr(10)):
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        end
        if line.startswith("["):
            section = line.strip("[]").strip()
            continue
        end
        eq = line.find("=")
        if eq <= 0:
            call log("ignored line in " + path + ": " + line)
            continue
        end
        name = line[:eq].strip()
        value = line[eq + 1:].strip()
        if section == "keys":
            keys[name] = value
        else:
            general[name] = value
        end
    end
    return True
end

function load_config():
    global settings
    general = {"workspaces": "4", "slide_ms": String(tokens.MOTION["workspace"]), "wrap_workspaces": "no",
               "xwayland": "yes"}
    keys = {}
    system = glib.getenv("LUXWM_SYSTEM_CONFIG")
    if system == None or system == "":
        system = SYSTEM_CONFIG
    end
    found = read_config(system, general, keys)
    if read_config(glib.user_config_dir() + "/luxwm/luxwm.conf", general, keys):
        found = True
    end
    if not found or len(keys) == 0:
        call log("no key bindings in " + system + ", using the built-in minimum")
        keys.update(FALLBACK_KEYS)
    end
    settings = general
    settings["keys"] = keys
end

# Programy, ktere smi na privilegovane protokoly (snimky obrazovky, schranka, sprava oken pro
# Dock, virtualni vstup, monitory, zamek): absolutni cesty po radcich. Jen systemovy soubor,
# uzivatelsky by mohl rozsirit cokoli bezici pod uzivatelem.
function load_privileged():
    path = glib.getenv("LUXWM_PRIVILEGED")
    if path == None or path == "":
        path = PRIVILEGED
    end
    call lc.privileged_allow("")
    count = 0
    if exists(path):
        for raw in readfile(path).split(chr(10)):
            line = raw.strip()
            if line == "" or line.startswith("#"):
                continue
            end
            if not line.startswith("/"):
                call log("ignored relative path in " + path + ": " + line)
                continue
            end
            call lc.privileged_allow(line)
            count += 1
        end
    else:
        call log("no " + path + ": privileged protocols disabled")
    end
    call note("privileged programs " + String(count))
end

function setting_int(name, low, high):
    value = 0
    try:
        value = Int(settings[name])
    else:
        call log("bad " + name + " = " + String(settings.get(name, "")))
        value = low
    end
    return max(low, min(high, value))
end

# "<Primary><Super>Left" -> [mods, klavesa]; [] kdyz je zapis spatne
function parse_accel(text):
    mods = 0
    rest = text.strip()
    while rest.startswith("<"):
        end_pos = rest.find(">")
        if end_pos < 0:
            return []
        end
        name = rest[1:end_pos].strip().lower()
        if not (name in MODS):
            return []
        end
        mods = mods | MODS[name]
        rest = rest[end_pos + 1:]
    end
    key = rest.strip()
    if key == "":
        return []
    end
    # klavesa pod Esc v kazdem rozlozeni (v ceskem ";"), jako luxos patch xfwm4
    if key == "grave":
        key = "code:49"
    end
    return [mods, key]
end

ACTIONS = ["close_window_key", "hide_window_key", "cycle_windows_key", "cycle_reverse_windows_key",
           "cycle_app_windows_key", "cycle_reverse_app_windows_key", "switch_window_key", "fullscreen_key",
           "maximize_window_key", "tile_left_key", "tile_right_key", "show_desktop_key",
           "left_workspace_key", "right_workspace_key", "move_window_left_workspace_key",
           "move_window_right_workspace_key", "quit"]

function known_action(action):
    if action.startswith("exec ") or action in ACTIONS:
        return True
    end
    return action.startswith("workspace_") or action.startswith("move_window_workspace_")
end

function bind_keys():
    for id in binds.keys():
        call lc.unbind_key(id)
    end
    binds.clear()
    keys = settings["keys"]
    for accel in sorted(keys.keys()):
        action = keys[accel]
        if action == "":
            continue
        end
        # sipky, Esc a Enter ovladaly prepinac oken xfwm4; globalne by je aplikace nedostaly
        if not known_action(action):
            call note("skip " + accel + " = " + action)
            continue
        end
        parsed = parse_accel(accel)
        id = 0
        if len(parsed) == 2:
            id = lc.bind_key(parsed[0], parsed[1])
        end
        if id == 0:
            call log("bad shortcut " + accel)
            continue
        end
        binds[id] = action
    end
end

# ---- vzhled ----------------------------------------------------------------------------------

function argb(c):
    return (Int(c[3] * 255.0 + 0.5) << 24) | (c[0] << 16) | (c[1] << 8) | c[2]
end

function dark_mode():
    path = glib.user_config_dir() + "/luxos/appearance"
    text = ""
    safe:
        text = readfile(path).strip()
    end
    return text == "dark"
end

function apply_theme(dark):
    look["dark"] = dark
    window = tokens.color("window", dark)
    call lc.theme_set(lc.THEME_TITLE_HEIGHT, tokens.LIGHT_SIZE + 2 * tokens.SPACE["s"])
    call lc.theme_set(lc.THEME_CORNER_RADIUS, tokens.RADIUS["window"])
    call lc.theme_set(lc.THEME_BUTTON_SIZE, 12)
    call lc.theme_set(lc.THEME_BUTTON_SPACING, tokens.SPACE["m"])
    call lc.theme_set(lc.THEME_BG_ACTIVE, argb(window))
    call lc.theme_set(lc.THEME_BG_INACTIVE, argb(window))
    call lc.theme_set(lc.THEME_TEXT_ACTIVE, argb(tokens.color("fg", dark)))
    call lc.theme_set(lc.THEME_TEXT_INACTIVE, argb(tokens.color("dim", dark)))
    call lc.theme_set(lc.THEME_CLOSE, argb(tokens.COLORS["light_close"]))
    call lc.theme_set(lc.THEME_MINIMIZE, argb(tokens.COLORS["light_min"]))
    call lc.theme_set(lc.THEME_MAXIMIZE, argb(tokens.COLORS["light_max"]))
    call lc.theme_set(lc.THEME_BUTTON_INACTIVE, argb(tokens.color("light_inactive", dark)))
    call lc.theme_set(lc.THEME_SEPARATOR, argb(tokens.color("border", dark)))
    # titulek jako v xfwm4 (Inter Semi-Bold 10): velikost tela v px na body
    call lc.theme_set_font(tokens.FONT["family"] + " Semi-Bold " + String(tokens.FONT["body"] * 3 // 4 + 1))
    # pod tapetou (vrstva background) stejna nahradni barva jako u skla bez tapety
    fb = tokens.GLASS["fallback"]
    call lc.set_background(argb([Int(fb[0] * 255.0), Int(fb[1] * 255.0), Int(fb[2] * 255.0), 1.0]))
    call note("theme " + ("dark" if dark else "light"))
    call broadcast("theme", theme_event())
end

# ---- rozlozeni klavesnice --------------------------------------------------------------------
# Zdroj pravdy je localed (stejne rozlozeni jako X11 relace, prihlaseni a konzole); uzivatel si ho
# muze prepsat v luxwm.conf (xkb_layout s xkb_variant spolu, xkb_options a xkb_model zvlast).

function read_locale():
    props = {}
    try:
        bus = gio.system_bus()
        values = gio.call_values(bus, LOCALE, "/org/freedesktop/locale1", "org.freedesktop.DBus.Properties", "GetAll",
                                 [LOCALE], "(s)", 1500)[0]
        for name in ["X11Layout", "X11Variant", "X11Options", "X11Model"]:
            props[name] = String(values.get(name, ""))
        end
        if len(keyboard["locale"]) == 0:
            call gio.subscribe_values(bus, LOCALE, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                      "/org/freedesktop/locale1", on_locale_changed)
        end
    else:
        call note("locale1 not available: " + String(last_error()))
    end
    keyboard["locale"] = props
end

function keyboard_names():
    loc = keyboard["locale"]
    layout = loc.get("X11Layout", "")
    variant = loc.get("X11Variant", "")
    options = loc.get("X11Options", "")
    if settings.get("xkb_layout", "") != "":
        layout = settings["xkb_layout"]
        variant = settings.get("xkb_variant", "")
    end
    if "xkb_options" in settings:
        options = settings["xkb_options"]
    end
    if layout.strip() == "":
        layout = "us"
        variant = ""
    end
    return [layout.replace(" ", ""), variant.replace(" ", ""), options.replace(" ", "")]
end

function apply_keyboard():
    names = keyboard_names()
    call lc.set_keymap(names[0], names[1], names[2])
    codes = names[0].split(",")
    variants = names[1].split(",")
    layouts = []
    for i in range(lc.layout_count()):
        code = codes[i] if i < len(codes) else ""
        layouts.append({"code": code, "variant": variants[i] if i < len(variants) else "", "name": lc.layout_name(i)})
    end
    keyboard["layouts"] = layouts
    call note("keyboard " + names[0] + " variant " + names[1] + " options " + names[2] + " layouts " + String(len(layouts)))
    call broadcast("keyboard", keyboard_event())
end

function on_locale_changed(sender, path, interface, signal, values):
    call read_locale()
    call apply_keyboard()
    return 0
end

function switch_layout(index):
    if index < 0 or index >= lc.layout_count():
        return False
    end
    call lc.set_layout(index)
    call broadcast("keyboard", keyboard_event())
    return True
end

# ---- geometrie -------------------------------------------------------------------------------

function usable(out):
    return [lc.output_get(out, lc.OUT_USABLE_X), lc.output_get(out, lc.OUT_USABLE_Y),
            lc.output_get(out, lc.OUT_USABLE_W), lc.output_get(out, lc.OUT_USABLE_H)]
end

# Ram okna (obsah + zahlavi kompozitoru): [x, y, w, h]
function frame(v):
    top = vget(v, lc.VIEW_DECO_TOP)
    return [vget(v, lc.VIEW_X), vget(v, lc.VIEW_Y) - top, vget(v, lc.VIEW_W), vget(v, lc.VIEW_H) + top]
end

function intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
end

function inside(f, u):
    cx = f[0] + f[2] // 2
    cy = f[1] + f[3] // 2
    return cx >= u[0] and cx < u[0] + u[2] and cy >= u[1] and cy < u[1] + u[3]
end

function geometry(v):
    return [vget(v, lc.VIEW_X), vget(v, lc.VIEW_Y), vget(v, lc.VIEW_W), vget(v, lc.VIEW_H)]
end

function output_of(v):
    out = vget(v, lc.VIEW_OUTPUT)
    if out == 0 and len(outputs) > 0:
        out = outputs[0]
    end
    return out
end

function current_ws():
    return ws[cur]
end

# ---- umisteni (xfwm4 luxos-windows.patch, placement_mode "luxos") -------------------------------
# 1. stred, kdyz tam nic neni; 2. volne misto bez prekryti; 3. kaskada 28 px od nejvyssiho okna
# stejne aplikace, na okraji pouzitelne plochy znovu nahore/vlevo. Nikdy presne na jine okno.

# Okna, se kterymi se pocita: viditelna na stejne plose a monitoru
function others(v, u):
    out = []
    space = vget(v, lc.VIEW_WORKSPACE)
    o = lc.view_next(0)
    while o != 0:
        if o != v and vget(o, lc.VIEW_VISIBLE) == 1 and vget(o, lc.VIEW_WORKSPACE) == space:
            f = frame(o)
            if inside(f, u):
                out.append([o, f])
            end
        end
        o = lc.view_next(o)
    end
    return out
end

function free_at(rect, frames):
    for item in frames:
        if intersects(rect, item[1]):
            return False
        end
    end
    return True
end

function taken(fx, fy, frames):
    for item in frames:
        f = item[1]
        if abs(f[0] - fx) < CASCADE // 2 and abs(f[1] - fy) < CASCADE // 2:
            return True
        end
    end
    return False
end

function place(v):
    out = lc.output_at(lc.cursor_x(), lc.cursor_y())
    if out == 0:
        out = output_of(v)
    end
    u = usable(out)
    top = vget(v, lc.VIEW_DECO_TOP)
    w = vget(v, lc.VIEW_W)
    h = vget(v, lc.VIEW_H) + top
    x = u[0] + (u[2] - w) // 2
    y = max(u[1], u[1] + (u[3] - h) // 2)
    parent = vget(v, lc.VIEW_PARENT)
    if parent != 0:
        # dialog nad stred rodice, cely v pouzitelne plose
        p = frame(parent)
        x = max(u[0], min(p[0] + (p[2] - w) // 2, u[0] + u[2] - w))
        y = max(u[1], min(p[1] + (p[3] - h) // 3, u[1] + u[3] - h))
        call lc.view_move(v, x, y + top)
        return [x, y]
    end
    frames = others(v, u)
    spot = [x, y]
    if not (w >= u[2] and h >= u[3]) and not free_at([x, y, w, h], frames):
        spot = free_spot(w, h, u, frames)
        if len(spot) == 0:
            spot = cascade(v, [x, y], w, h, u, frames)
        end
    end
    call lc.view_move(v, spot[0], spot[1] + top)
    return spot
end

# Nejlevejsi (pak nejvyssi) misto bez prekryti jako hledani "smart" v xfwm4; staci zkouset hrany
# ostatnich oken, protoze takove misto vzdy lezi na okraji plochy nebo tesne vedle jineho okna
function free_spot(w, h, u, frames):
    xs = [u[0]]
    ys = [u[1]]
    for item in frames:
        f = item[1]
        xs.append(f[0] + f[2])
        ys.append(f[1] + f[3])
    end
    for cx in sorted(dedup(xs)):
        if cx + w > u[0] + u[2]:
            continue
        end
        for cy in sorted(dedup(ys)):
            if cy + h <= u[1] + u[3] and free_at([cx, cy, w, h], frames):
                return [cx, cy]
            end
        end
    end
    return []
end

function cascade(v, start, w, h, u, frames):
    app = lc.view_app_id(v)
    fx = start[0]
    fy = start[1]
    if app != "":
        o = lc.view_next(0)
        while o != 0:
            if o != v and lc.view_app_id(o) == app and o not in maxed and o not in tiled and o not in full:
                for item in frames:
                    if item[0] == o:
                        fx = item[1][0] + CASCADE
                        fy = item[1][1] + CASCADE
                        o = 0
                        break
                    end
                end
            end
            if o != 0:
                o = lc.view_next(o)
            end
        end
    end
    tries = 0
    while tries < 64:
        if fy + h > u[1] + u[3]:
            fy = u[1]
        end
        if fx + w > u[0] + u[2]:
            fx = u[0]
        end
        if not taken(fx, fy, frames):
            break
        end
        fx += CASCADE
        fy += CASCADE
        tries += 1
    end
    return [max(fx, u[0]), max(fy, u[1])]
end

# ---- zamereni --------------------------------------------------------------------------------

function on_current(v):
    return vget(v, lc.VIEW_MAPPED) == 1 and vget(v, lc.VIEW_WORKSPACE) == current_ws()
end

function focused():
    o = lc.view_next(0)
    while o != 0:
        if vget(o, lc.VIEW_FOCUSED) == 1:
            return o
        end
        o = lc.view_next(o)
    end
    return 0
end

function to_front(v):
    if v in mru:
        call mru.remove(v)
    end
    call mru.insert(0, v)
end

# Celoobrazovkove okno je nad listou jen zamerene (xfwm4 luxos-fullscreen-layer.patch); jinak
# zustava ve stromu sve plochy, aby s ni odjelo a nezakryvalo jine plochy
function update_layers(active):
    o = lc.view_next(0)
    while o != 0:
        if o in full:
            call lc.view_set_layer(o, lc.LAYER_FULLSCREEN if o == active else lc.LAYER_NORMAL)
        end
        o = lc.view_next(o)
    end
end

# Otevreny dialog okna (modalni chovani: zamereni jde na nej)
function child_of(v):
    o = lc.view_next(0)
    while o != 0:
        if vget(o, lc.VIEW_PARENT) == v and vget(o, lc.VIEW_VISIBLE) == 1:
            return o
        end
        o = lc.view_next(o)
    end
    return 0
end

function show(v, remember):
    if vget(v, lc.VIEW_VISIBLE) == 0:
        call lc.view_set_visible(v, 1)
    end
    call lc.view_raise(v)
    child = child_of(v)
    target = v
    if child != 0:
        call lc.view_raise(child)
        target = child
    end
    call lc.view_focus(target)
    if remember:
        call to_front(v)
        if target != v:
            call to_front(target)
        end
    end
    call update_layers(target)
    return target
end

function focus(v):
    if v == 0:
        call lc.view_focus(0)
        call update_layers(0)
        call note("focus 0")
        return
    end
    target = show(v, True)
    call note("focus " + String(target))
end

# Nejnovejsi okno na zobrazene plose (bez minimalizovanych)
function top_on_current(skip):
    for v in mru:
        if v != skip and on_current(v) and vget(v, lc.VIEW_VISIBLE) == 1:
            return v
        end
    end
    return 0
end

function focus_next(skip, parent):
    if parent != 0 and parent != skip and on_current(parent) and vget(parent, lc.VIEW_VISIBLE) == 1:
        call focus(parent)
    else:
        call focus(top_on_current(skip))
    end
end

# ---- stavy okna ------------------------------------------------------------------------------

function remember_geometry(v):
    if not (v in saved):
        saved[v] = geometry(v)
    end
end

function restore_geometry(v):
    if v in saved:
        g = saved.pop(v)
        call lc.view_resize(v, g[2], g[3])
        call lc.view_move(v, g[0], g[1])
    end
end

function fit_maximized(v):
    call fit_maximized_top(v, vget(v, lc.VIEW_DECO_TOP))
end

function fit_maximized_top(v, top):
    u = usable(output_of(v))
    call lc.view_move(v, u[0], u[1] + top)
    call lc.view_resize(v, u[2], u[3] - top)
end

function fit_tiled(v):
    call fit_tiled_top(v, vget(v, lc.VIEW_DECO_TOP))
end

function fit_tiled_top(v, top):
    u = usable(output_of(v))
    half = u[2] // 2
    x = u[0]
    if tiled[v] == "right":
        x = u[0] + half
    end
    call lc.view_move(v, x, u[1] + top)
    call lc.view_resize(v, half, u[3] - top)
end

function fit_fullscreen(v):
    out = output_of(v)
    call lc.view_move(v, lc.output_get(out, lc.OUT_X), lc.output_get(out, lc.OUT_Y))
    call lc.view_resize(v, lc.output_get(out, lc.OUT_W), lc.output_get(out, lc.OUT_H))
end

function set_maximized(v, on):
    if on and not (v in maxed):
        call remember_geometry(v)
        if v in tiled:
            call tiled.pop(v)
            call lc.view_set_state(v, lc.STATE_TILED, 0)
        end
        maxed[v] = True
        call lc.view_set_state(v, lc.STATE_MAXIMIZED, 1)
        if v not in full:
            call fit_maximized(v)
        end
    elif not on and v in maxed:
        call maxed.pop(v)
        call lc.view_set_state(v, lc.STATE_MAXIMIZED, 0)
        if v not in full:
            call restore_geometry(v)
        end
    else:
        # klient musi dostat odpoved i na pozadavek beze zmeny
        call lc.view_set_state(v, lc.STATE_MAXIMIZED, 1 if on else 0)
    end
    call note("maximize " + String(v) + " " + String(on))
end

function set_tiled(v, side):
    if v in maxed or v in full:
        return
    end
    if tiled.get(v, "") == side:
        call tiled.pop(v)
        call lc.view_set_state(v, lc.STATE_TILED, 0)
        call restore_geometry(v)
        return
    end
    call remember_geometry(v)
    tiled[v] = side
    call lc.view_set_state(v, lc.STATE_TILED, 1)
    call fit_tiled(v)
end

function set_fullscreen(v, on):
    if on == (v in full):
        call lc.view_set_state(v, lc.STATE_FULLSCREEN, 1 if on else 0)
        return
    end
    if on:
        call remember_geometry(v)
        full[v] = vget(v, lc.VIEW_DECO_TOP)
        call lc.view_set_state(v, lc.STATE_FULLSCREEN, 1)
        call fit_fullscreen(v)
        call focus(v)
    else:
        top = full.pop(v)
        call lc.view_set_state(v, lc.STATE_FULLSCREEN, 0)
        call lc.view_set_layer(v, lc.LAYER_NORMAL)
        if v in maxed:
            call fit_maximized_top(v, top)
        elif v in tiled:
            call fit_tiled_top(v, top)
        else:
            call restore_geometry(v)
        end
    end
    call note("fullscreen " + String(v) + " " + String(on))
end

function minimize(v):
    was = vget(v, lc.VIEW_FOCUSED) == 1
    call lc.view_set_visible(v, 0)
    if was:
        call focus_next(v, 0)
    end
    call note("minimize " + String(v))
end

function show_desktop():
    global hidden_desktop
    if len(hidden_desktop) > 0:
        for v in hidden_desktop:
            if vget(v, lc.VIEW_MAPPED) == 1:
                call lc.view_set_visible(v, 1)
            end
        end
        hidden_desktop = []
        call focus(top_on_current(0))
        return
    end
    for v in mru:
        if on_current(v) and vget(v, lc.VIEW_VISIBLE) == 1:
            hidden_desktop.append(v)
            call lc.view_set_visible(v, 0)
        end
    end
    call focus(0)
end

# ---- plochy ----------------------------------------------------------------------------------

function switch_to(index):
    global cur
    if index < 0 or index >= len(ws) or index == cur:
        return
    end
    old = cur
    cur = index
    # zamereni hned (klavesnice patri nove plose uz behem prejezdu); celoobrazovkove okno stare
    # plochy se tim vrati do jejiho stromu a odjede s ni
    call focus(top_on_current(0))
    call lc.workspace_slide(ws[old], ws[index], 1 if index > old else -1, setting_int("slide_ms", 0, 2000))
    call note("workspace " + String(index + 1))
    call broadcast("workspace", workspace_event())
end

function step_index(delta):
    index = cur + delta
    if settings["wrap_workspaces"] == "yes":
        index = (index + len(ws)) % len(ws)
    end
    return index
end

# Presun okna na jinou plochu (jako xfwm4 move_window_*: okno odejde, uzivatel zustava)
function send_to(v, index):
    if v == 0 or index < 0 or index >= len(ws) or index == cur:
        return
    end
    call lc.view_set_layer(v, lc.LAYER_NORMAL)
    call lc.view_set_workspace(v, ws[index])
    call focus_next(v, 0)
    call note("send " + String(v) + " workspace " + String(index + 1))
end

# ---- Alt+Tab ---------------------------------------------------------------------------------

function cycle_start(app_only):
    current = focused()
    app = lc.view_app_id(current) if current != 0 else ""
    items = []
    for v in mru:
        if on_current(v) and (not app_only or (app != "" and lc.view_app_id(v) == app)):
            items.append(v)
        end
    end
    if len(items) == 0:
        return False
    end
    cycle["on"] = True
    cycle["list"] = items
    cycle["pos"] = 0
    cycle["from"] = current
    cycle["shown"] = []
    # Esc se drzenym Alt zrusi vyber; mimo prepinani ho dostava aplikace
    cycle["cancel"] = lc.bind_key(lc.MOD_ALT, "Escape")
    return True
end

function cycle_step(delta, app_only):
    if not cycle["on"] and not cycle_start(app_only):
        return
    end
    items = cycle["list"]
    cycle["pos"] = (cycle["pos"] + delta + len(items)) % len(items)
    v = items[cycle["pos"]]
    # vybrane okno hned dopredu (cycle_raise); minimalizovane jen docasne, dokud je vybrane
    for s in cycle["shown"]:
        if s != v and vget(s, lc.VIEW_MAPPED) == 1:
            call lc.view_set_visible(s, 0)
        end
    end
    cycle["shown"] = []
    if vget(v, lc.VIEW_VISIBLE) == 0:
        cycle["shown"] = [v]
    end
    call show(v, False)
    call note("cycle " + String(v))
end

function cycle_end(cancel):
    if not cycle["on"]:
        return
    end
    cycle["on"] = False
    call lc.unbind_key(cycle["cancel"])
    items = cycle["list"]
    v = items[cycle["pos"]] if len(items) > 0 else 0
    if cancel:
        for s in cycle["shown"]:
            call lc.view_set_visible(s, 0)
        end
        v = cycle["from"]
    end
    cycle["shown"] = []
    if v != 0 and vget(v, lc.VIEW_MAPPED) == 1:
        call focus(v)
    end
end

# ---- akce zkratek ----------------------------------------------------------------------------

function run_action(action):
    v = focused()
    if action.startswith("exec "):
        call lc.spawn(action[5:])
    elif action == "cycle_windows_key":
        call cycle_step(1, False)
    elif action == "cycle_reverse_windows_key":
        call cycle_step(-1, False)
    elif action == "cycle_app_windows_key" or action == "switch_window_key":
        call cycle_step(1, True)
    elif action == "cycle_reverse_app_windows_key":
        call cycle_step(-1, True)
    elif action == "left_workspace_key":
        call switch_to(step_index(-1))
    elif action == "right_workspace_key":
        call switch_to(step_index(1))
    elif action.startswith("workspace_"):
        call switch_to(Int(action.split("_")[1]) - 1)
    elif action == "move_window_left_workspace_key":
        call send_to(v, step_index(-1))
    elif action == "move_window_right_workspace_key":
        call send_to(v, step_index(1))
    elif action.startswith("move_window_workspace_"):
        call send_to(v, Int(action.split("_")[3]) - 1)
    elif action == "show_desktop_key":
        call show_desktop()
    elif action == "quit":
        call stop()
    elif v == 0:
        return
    elif action == "close_window_key":
        call lc.view_close(v)
    elif action == "hide_window_key":
        call minimize(v)
    elif action == "fullscreen_key":
        call set_fullscreen(v, v not in full)
    elif action == "maximize_window_key":
        call set_maximized(v, not (v in maxed))
    elif action == "tile_left_key":
        call set_tiled(v, "left")
    elif action == "tile_right_key":
        call set_tiled(v, "right")
    end
end

# ---- udalosti jadra ----------------------------------------------------------------------------

function view_mapped(v):
    parent = vget(v, lc.VIEW_PARENT)
    space = current_ws()
    if parent != 0:
        space = vget(parent, lc.VIEW_WORKSPACE)
    end
    call lc.view_set_workspace(v, space)
    spot = place(v)
    call note("place " + String(v) + " " + lc.view_app_id(v) + " " + String(spot[0]) + "," + String(spot[1])
        + " " + String(vget(v, lc.VIEW_W)) + "x" + String(vget(v, lc.VIEW_H)))
    # Okno na jine plose (dialog schovane aplikace) nebo nove okno pod zamerenou celou obrazovkou
    # zamereni nekrade: jen se zaradi pod aktualni okno
    current = focused()
    background = space != current_ws() or (current != 0 and current in full and parent != current)
    if background or cycle["on"]:
        mru.insert(1 if len(mru) > 0 else 0, v)
        if current != 0:
            call lc.view_raise(current)
        end
        call note("background " + String(v))
    else:
        call focus(v)
    end
end

function view_gone(v):
    was = v == focused() or focused() == 0
    parent = vget(v, lc.VIEW_PARENT)
    if v in mru:
        call mru.remove(v)
    end
    if cycle["on"] and v in cycle["list"]:
        call cycle_end(True)
    end
    if was:
        call focus_next(v, parent)
    end
end

function forget(v):
    for table in [saved, maxed, tiled, full]:
        if v in table:
            call table.pop(v)
        end
    end
    if v in mru:
        call mru.remove(v)
    end
    if v in hidden_desktop:
        call hidden_desktop.remove(v)
    end
end

# Lista nebo Dock zmenily pouzitelnou plochu (exkluzivni zony): prizpusobit okna na monitoru
function usable_changed(out):
    u = usable(out)
    o = lc.view_next(0)
    while o != 0:
        if output_of(o) == out:
            if o in full:
                call fit_fullscreen(o)
            elif o in maxed:
                call fit_maximized(o)
            elif o in tiled:
                call fit_tiled(o)
            else:
                top = vget(o, lc.VIEW_DECO_TOP)
                if vget(o, lc.VIEW_Y) - top < u[1]:
                    call lc.view_move(o, vget(o, lc.VIEW_X), u[1] + top)
                end
            end
        end
        o = lc.view_next(o)
    end
    call note("usable " + String(out) + " " + String(u[0]) + "," + String(u[1]) + " " + String(u[2]) + "x" + String(u[3]))
end

function button(v, pressed, part):
    if not pressed or v == 0 or part == lc.PART_LAYER:
        return
    end
    if cycle["on"]:
        call cycle_end(False)
    end
    # semafor neaktivniho okna funguje bez jeho zamereni (jako v macOS)
    if part == lc.PART_CLOSE:
        call lc.view_close(v)
        return
    elif part == lc.PART_MINIMIZE:
        call minimize(v)
        return
    end
    if vget(v, lc.VIEW_FOCUSED) == 0:
        call focus(v)
    else:
        call lc.view_raise(v)
    end
    if part == lc.PART_TITLE:
        now = glib.monotonic_time()
        if last_title_click[0] == v and now - last_title_click[1] < DOUBLE_CLICK_US:
            last_title_click[0] = 0
            call set_maximized(v, not (v in maxed))
            return
        end
        last_title_click[0] = v
        last_title_click[1] = now
        if not (v in maxed) and v not in full:
            call lc.view_begin_move(v)
        end
    elif part == lc.PART_MAXIMIZE:
        call set_maximized(v, not (v in maxed))
    end
end

# xdg-activation a Dock: okno jine aplikace se zameri jen s tokenem od zamerene aplikace nebo
# od shellu (Dock, spoustec, luxwm), pak i s prepnutim plochy (xfwm4 activate_action=switch)
function activate(v, origin, source):
    current = focused()
    allowed = origin == lc.ORIGIN_SHELL or origin == lc.ORIGIN_TASKBAR
    if origin == lc.ORIGIN_VIEW and current != 0 and source != 0:
        app = lc.view_app_id(current)
        allowed = source == current or (app != "" and lc.view_app_id(source) == app)
    elif origin == lc.ORIGIN_CLIENT:
        # bez tokenu jen okna aplikace, ktera ma zamereni (zadne kradeze)
        allowed = current != 0 and lc.view_app_id(current) == lc.view_app_id(v) and on_current(v)
    end
    if not allowed:
        call note("activate refused " + String(v) + " origin " + String(origin))
        return
    end
    if cycle["on"]:
        call cycle_end(True)
    end
    space = vget(v, lc.VIEW_WORKSPACE)
    if space in ws and ws.index(space) != cur:
        call switch_to(ws.index(space))
    end
    if v in hidden_desktop:
        call hidden_desktop.remove(v)
    end
    call focus(v)
    call note("activate " + String(v) + " origin " + String(origin))
end

function request(v, what, arg, origin):
    if what == lc.REQ_MOVE:
        if not (v in maxed) and v not in full:
            call lc.view_begin_move(v)
        end
    elif what == lc.REQ_RESIZE:
        if not (v in maxed) and v not in full:
            call lc.view_begin_resize(v, arg)
        end
    elif what == lc.REQ_MAXIMIZE:
        call set_maximized(v, arg == 1)
    elif what == lc.REQ_FULLSCREEN:
        call set_fullscreen(v, arg == 1)
    elif what == lc.REQ_MINIMIZE:
        if arg == 0:
            # obnoveni z Docku (nebo X11 klient sam sebe)
            call activate(v, origin, 0)
        else:
            call minimize(v)
        end
    elif what == lc.REQ_ACTIVATE:
        call activate(v, arg, origin)
    elif what == lc.REQ_DECORATION:
        call lc.view_set_decorated(v, arg)
    elif what == lc.REQ_CLOSE:
        call lc.view_close(v)
    end
end

function handle(event, id, a, b, c):
    if event == lc.EV_VIEW_MAP:
        call view_mapped(id)
    elif event == lc.EV_VIEW_UNMAP:
        call view_gone(id)
    elif event == lc.EV_VIEW_DESTROY:
        call forget(id)
    elif event == lc.EV_BUTTON:
        call button(id, b == 1, c)
    elif event == lc.EV_KEYBIND:
        action = binds.get(id, "")
        if cycle["on"] and id == cycle["cancel"]:
            call cycle_end(True)
        elif action != "":
            t0 = glib.monotonic_time()
            call run_action(action)
            call note("key " + action + " t=" + String(t0) + " took_us=" + String(glib.monotonic_time() - t0))
        end
    elif event == lc.EV_MODS_RELEASED:
        call cycle_end(False)
    elif event == lc.EV_VIEW_REQUEST:
        call request(id, a, b, c)
    elif event == lc.EV_LOCK:
        # pod zamkem jadro zkratky neposila; rozdelany Alt+Tab zrusit
        if a == 1:
            call cycle_end(True)
        end
        call note("lock " + String(a) + (" (locker gone)" if b == 1 else ""))
    elif event == lc.EV_OUTPUT_USABLE:
        call usable_changed(id)
        call broadcast("output", output_event())
    elif event == lc.EV_OUTPUT_ADD:
        outputs.append(id)
        call broadcast("output", output_event())
    elif event == lc.EV_OUTPUT_REMOVE:
        if id in outputs:
            call outputs.remove(id)
        end
        call broadcast("output", output_event())
    elif event == lc.EV_LAYOUT:
        call note("layout " + String(a))
        call broadcast("keyboard", keyboard_event())
    elif event == lc.EV_IPC_CONNECT:
        ipc[id] = {"privileged": b == 1, "topics": []}
        call note("ipc connect " + String(id) + " pid " + String(a) + (" privileged" if b == 1 else ""))
        return
    elif event == lc.EV_IPC_LINE:
        call ipc_line(id)
    elif event == lc.EV_IPC_CLOSE:
        if id in ipc:
            call ipc.pop(id)
        end
        return
    elif event == lc.EV_SLIDE_DONE:
        if focused() == 0:
            call focus(top_on_current(0))
        end
    end
    call window_changed()
end

EVENT_NAMES = ["", "output-add", "output-remove", "output-usable", "view-new", "view-map", "view-unmap",
               "view-destroy", "view-title", "view-app-id", "view-request", "button", "keybind",
               "slide-done", "mods-released", "lock", "layout", "ipc-connect", "ipc-line", "ipc-close"]

# Chyba politiky nesmi shodit kompozitor: zapsat a pokracovat. Nove okno se aspon zameri,
# aby nezustalo neovladatelne.
function on_event(event, id, a, b, c):
    try:
        call handle(event, id, a, b, c)
    else:
        call log("error in " + EVENT_NAMES[event] + " " + String(id) + ": " + String(last_error()))
        if event == lc.EV_VIEW_MAP:
            safe:
                call lc.view_focus(id)
            end
        end
    end
end

# ---- IPC pro shell (docs/developers/luxwm-ipc.md) ----------------------------------------------

function workspace_event():
    return {"event": "workspace", "current": cur + 1, "count": len(ws)}
end

function keyboard_event():
    return {"event": "keyboard", "current": lc.layout(), "layouts": keyboard["layouts"]}
end

function output_event():
    items = []
    for out in outputs:
        items.append({"name": lc.output_name(out), "x": lc.output_get(out, lc.OUT_X), "y": lc.output_get(out, lc.OUT_Y),
                      "width": lc.output_get(out, lc.OUT_W), "height": lc.output_get(out, lc.OUT_H),
                      "scale": lc.output_get(out, lc.OUT_SCALE_PCT), "refresh_mhz": lc.output_get(out, lc.OUT_REFRESH_MHZ),
                      "usable": usable(out)})
    end
    return {"event": "output", "outputs": items}
end

function theme_event():
    return {"event": "theme", "theme": "dark" if look["dark"] else "light"}
end

function window_event():
    v = focused()
    if v == 0:
        return {"event": "window", "id": 0, "app_id": "", "title": ""}
    end
    return {"event": "window", "id": v, "app_id": lc.view_app_id(v), "title": lc.view_title(v)}
end

function topic_event(topic):
    if topic == "window":
        return window_event()
    elif topic == "workspace":
        return workspace_event()
    elif topic == "keyboard":
        return keyboard_event()
    elif topic == "output":
        return output_event()
    end
    return theme_event()
end

function send(client, message):
    if lc.ipc_send(client, json.encode(message)) == 0 and client in ipc:
        call ipc.pop(client)
    end
end

function broadcast(topic, message):
    line = ""
    for client in [k for k in ipc.keys()]:
        if topic in ipc[client]["topics"]:
            if line == "":
                line = json.encode(message)
            end
            if lc.ipc_send(client, line) == 0:
                call ipc.pop(client)
            end
        end
    end
end

# Zamerene okno, jeho nazev nebo app_id se zmenily: jedna udalost, i kdyz k tomu vedlo vic udalosti jadra
function window_changed():
    global last_window
    if len(ipc) == 0:
        return
    end
    v = focused()
    now = [v, lc.view_app_id(v) if v != 0 else "", lc.view_title(v) if v != 0 else ""]
    if now != last_window:
        last_window = now
        call broadcast("window", window_event())
    end
end

function window_info(v):
    space = vget(v, lc.VIEW_WORKSPACE)
    return {"id": v, "app_id": lc.view_app_id(v), "title": lc.view_title(v),
            "workspace": ws.index(space) + 1 if space in ws else 0, "focused": vget(v, lc.VIEW_FOCUSED) == 1,
            "minimized": vget(v, lc.VIEW_VISIBLE) == 0, "fullscreen": v in full, "maximized": v in maxed}
end

function list_windows():
    items = []
    seen = []
    for v in mru:
        if vget(v, lc.VIEW_MAPPED) == 1:
            items.append(window_info(v))
            seen.append(v)
        end
    end
    o = lc.view_next(0)
    while o != 0:
        if o not in seen and vget(o, lc.VIEW_MAPPED) == 1:
            items.append(window_info(o))
        end
        o = lc.view_next(o)
    end
    return items
end

function ipc_command(client, request):
    privileged = ipc[client]["privileged"]
    cmd = request.get("cmd", "")
    if type(cmd) != "String":
        return {"ok": False, "error": "bad request"}
    end
    if cmd in PRIVILEGED_COMMANDS and not privileged:
        return {"ok": False, "error": "permission denied"}
    end
    if cmd == "subscribe":
        topics = request.get("events", [])
        if type(topics) != "List":
            return {"ok": False, "error": "bad request"}
        end
        for topic in topics:
            if topic not in IPC_TOPICS:
                return {"ok": False, "error": "unknown event " + String(topic)}
            end
            if topic in PRIVILEGED_TOPICS and not privileged:
                return {"ok": False, "error": "permission denied"}
            end
        end
        for topic in topics:
            if topic not in ipc[client]["topics"]:
                ipc[client]["topics"].append(topic)
            end
        end
        return {"ok": True}
    elif cmd == "get_state":
        state = {}
        for topic in IPC_TOPICS:
            if privileged or topic not in PRIVILEGED_TOPICS:
                state[topic] = topic_event(topic)
            end
        end
        return {"ok": True, "state": state}
    elif cmd == "next_layout":
        count = lc.layout_count()
        if count > 1:
            call switch_layout((lc.layout() + 1) % count)
        end
        return {"ok": True}
    elif cmd == "switch_layout":
        index = request.get("index", None)
        code = request.get("layout", None)
        if code != None:
            index = None
            for i in range(len(keyboard["layouts"])):
                item = keyboard["layouts"][i]
                if item["code"] == code or item["code"] + "(" + item["variant"] + ")" == code:
                    index = i
                    break
                end
            end
        end
        if type(index) != "Int" or not switch_layout(index):
            return {"ok": False, "error": "unknown layout"}
        end
        return {"ok": True}
    elif cmd == "switch_workspace":
        number = request.get("number", None)
        delta = request.get("delta", None)
        if type(number) == "Int" and number >= 1 and number <= len(ws):
            call switch_to(number - 1)
        elif type(delta) == "Int":
            call switch_to(step_index(delta))
        else:
            return {"ok": False, "error": "bad workspace"}
        end
        return {"ok": True}
    elif cmd == "reload":
        call on_reload()
        return {"ok": True}
    elif cmd == "set_theme":
        theme = request.get("theme", "")
        if theme != "light" and theme != "dark":
            return {"ok": False, "error": "bad theme"}
        end
        call apply_theme(theme == "dark")
        return {"ok": True}
    elif cmd == "list_windows":
        return {"ok": True, "windows": list_windows()}
    elif cmd == "focus_window":
        v = request.get("id", 0)
        if type(v) != "Int" or v <= 0 or vget(v, lc.VIEW_MAPPED) != 1:
            return {"ok": False, "error": "no such window"}
        end
        call activate(v, lc.ORIGIN_TASKBAR, 0)
        return {"ok": True}
    end
    return {"ok": False, "error": "unknown command"}
end

function ipc_line(client):
    if client not in ipc:
        return
    end
    request = None
    try:
        request = json.decode(lc.ipc_line(client))
    else:
        request = None
    end
    if type(request) != "Dictionary":
        call send(client, {"ok": False, "error": "bad request"})
        return
    end
    reply = ipc_command(client, request)
    if "id" in request:
        reply["id"] = request["id"]
    end
    call send(client, reply)
    # po potvrzeni odberu hned aktualni stav, at klient nemusi zvlast cist get_state
    if reply["ok"] and request.get("cmd", "") == "subscribe" and client in ipc:
        for topic in request["events"]:
            call send(client, topic_event(topic))
            if client not in ipc:
                return
            end
        end
    end
end

# ---- stav pro testy (SIGUSR2) ------------------------------------------------------------------

function dump():
    call log("workspace " + String(cur + 1) + "/" + String(len(ws)) + " locked=" + String(lc.locked())
        + " xwayland=" + String(lc.xwayland_running()) + " layout=" + String(lc.layout()) + "/" + String(lc.layout_count())
        + " ipc=" + String(len(ipc)) + " theme=" + ("dark" if look["dark"] else "light"))
    for out in outputs:
        u = usable(out)
        call log("output " + String(out) + " " + lc.output_name(out) + " " + String(lc.output_get(out, lc.OUT_W)) + "x"
            + String(lc.output_get(out, lc.OUT_H)) + " usable=" + String(u[0]) + "," + String(u[1]) + "," + String(u[2]) + "x" + String(u[3]))
    end
    o = lc.view_next(0)
    while o != 0:
        call log("view " + String(o) + " app=" + lc.view_app_id(o) + " title=" + lc.view_title(o).replace(" ", "_")
            + " ws=" + String(ws.index(vget(o, lc.VIEW_WORKSPACE)) + 1 if vget(o, lc.VIEW_WORKSPACE) in ws else 0)
            + " x=" + String(vget(o, lc.VIEW_X)) + " y=" + String(vget(o, lc.VIEW_Y)) + " w=" + String(vget(o, lc.VIEW_W))
            + " h=" + String(vget(o, lc.VIEW_H)) + " top=" + String(vget(o, lc.VIEW_DECO_TOP))
            + " focused=" + String(vget(o, lc.VIEW_FOCUSED)) + " visible=" + String(vget(o, lc.VIEW_VISIBLE))
            + " fullscreen=" + String(vget(o, lc.VIEW_FULLSCREEN)) + " maximized=" + String(1 if o in maxed else 0)
            + " layer=" + String(vget(o, lc.VIEW_LAYER)) + " x11=" + String(vget(o, lc.VIEW_X11)))
        o = lc.view_next(o)
    end
    call log("mru " + " ".join([String(v) for v in mru]))
    call log("end")
end

# ---- beh ---------------------------------------------------------------------------------------

function stop():
    call lc.quit()
    call glib.main_quit()
end

function on_luxcomp(fd, condition):
    if lc.dispatch(0) < 0:
        call glib.main_quit()
        return False
    end
    return True
end

function on_term():
    call log("stopping")
    call stop()
    return True
end

function on_reload():
    call load_config()
    call load_privileged()
    call bind_keys()
    call read_locale()
    call apply_keyboard()
    call apply_theme(dark_mode())
    call log("configuration reloaded")
    return True
end

function on_theme():
    call apply_theme(dark_mode())
    return True
end

function ipc_path():
    runtime = glib.getenv("XDG_RUNTIME_DIR")
    if runtime == None or runtime == "":
        return ""
    end
    return runtime + "/luxwm-" + lc.socket() + ".sock"
end

function on_dump():
    call dump()
    return True
end

commands = []
for i in range(1, len(args)):
    if args[i] == "-d":
        trace = True
    else:
        commands.append(args[i])
    end
end
if glib.getenv("LUXWM_TRACE") == "1":
    trace = True
end

call load_config()
if lc.init(on_event) != 0:
    call log("cannot initialise the compositor core")
    exit(1)
end
call load_privileged()
xdisplay = ""
if settings["xwayland"] == "yes" and lc.xwayland_start() == 0:
    xdisplay = lc.xwayland_display()
end
ws_count = setting_int("workspaces", 1, 16)
for i in range(ws_count):
    ws.append(lc.workspace_new())
end
call lc.workspace_show(ws[0], 1)
call bind_keys()
call read_locale()
call apply_keyboard()
call apply_theme(dark_mode())
sock = ipc_path()
if sock != "" and lc.ipc_listen(sock) == 0:
    call lc.setenv("LUXWM_SOCK", sock)
else:
    call log("no IPC socket" + (" at " + sock if sock != "" else " (no XDG_RUNTIME_DIR)"))
    sock = ""
end
if lc.start() != 0:
    call log("cannot start the backend")
    call lc.destroy()
    exit(1)
end
call log("running on " + lc.socket() + (" (software rendering)" if lc.software_rendering() == 1 else "")
    + ", " + String(ws_count) + " workspaces, " + String(len(binds)) + " shortcuts"
    + (", ipc " + sock if sock != "" else "")
    + (", xwayland " + xdisplay if xdisplay != "" else ""))
call glib.fd_add(lc.fd(), glib.IO_IN, on_luxcomp)
call glib.unix_signal_add(15, on_term)
call glib.unix_signal_add(2, on_term)
call glib.unix_signal_add(1, on_reload)
call glib.unix_signal_add(10, on_theme)
call glib.unix_signal_add(12, on_dump)
for startup in commands:
    call lc.spawn(startup)
end
# prvni pruchod: klienti cekajici na socket a nastartovany backend
call lc.dispatch(0)
call glib.main()
call lc.destroy()
call log("stopped")
