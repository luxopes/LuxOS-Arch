# LuxOS - luxwm: spravce oken desktopu na Waylandu (1.1.0, architektura R2). Kompozitor kresli
# libluxcomp v C (packages/luxcomp), tady je jen politika: umisteni noveho okna jako xfwm4 "luxos",
# zamereni klikem, Alt+Tab a Alt+` s koncem pri pusteni modifikatoru, plochy s prejezdem, cela
# obrazovka nad listou, maximalizace do pouzitelne plochy, minimalizace, zahlavi z luxos_tokens
# a klavesove zkratky z luxwm.conf. Popis: packages/luxwm/README.md
#
#   luxwm [-d] [PRIKAZ...]    -d = stopa rozhodnuti na stderr; prikazy se spusti po startu
#   luxwm --greeter PRIKAZ    prihlasovaci obrazovka (greetd): jeden klient pres celou obrazovku, zadne
#                             zkratky, XWayland ani privilegovane protokoly; konci s kodem klienta
#   --hold                    obraz pred startem (splash Plymouthu) zustane, dokud klient nenakresli prvni
#                             snimek (nejdele HOLD_MS); s --greeter pak $XDG_RUNTIME_DIR/luxos-greeter-shown
#   --intro                   prechod po prihlaseni jako v X11 (luxos-session-cover --login): posledni snimek
#                             greeteru s barem prubehu, dokud tapeta, lista a Dock nenakresli prvni snimek, pak se
#                             behem 280 ms rozplyne do plochy
# Signaly: SIGTERM/SIGINT konec, SIGHUP znovu nacte luxwm.conf a vzhled, SIGUSR1 jen vzhled
# (prepnuti svetly/tmavy), SIGUSR2 vypise stav na stderr (testy).
# IPC pro shell (lista, Dock, nastaveni): $XDG_RUNTIME_DIR/luxwm-$WAYLAND_DISPLAY.sock, radkovy JSON,
# popis docs/developers/luxwm-ipc.md. Rozlozeni klavesnice z org.freedesktop.locale1, prepsane
# polozkami xkb_* v luxwm.conf.
load glib, gio, json
load luxos_luxcomp as lc
load luxos_tokens as tokens
load luxos_glib as lglib
load luxos_wm_config as wmconf

CASCADE = 28
PLACE_MARGIN = 8
REACH_X = 100       # tolik px okna zustava vodorovne na monitoru (keep_reachable, presun mysi v jadre)
REACH_TITLE = 30    # u okna s vlastnim zahlavim (CSD) vyska jeho zahlavi
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
greeter = False
hold = False
# hold konci nejpozdeji pred luxos-greetd-splash (10 s): splash nesmi skoncit, dokud ho drzime
HOLD_MS = 8000
# Animace oken z picom.conf LuxOS 1.0.x (ms); vypina je "omezit pohyb" (reduce_motion) a Sporic baterie
ANIM_MS = {lc.ANIM_OPEN: 180, lc.ANIM_CLOSE: 140, lc.ANIM_MINIMIZE: 320, lc.ANIM_RESTORE: 300}
# zaneprazdneny ukazatel po spusteni aplikace nejdele tak dlouho (mutter 15 s; xfwm4 30 s, ale aplikace bez
# xdg-activation na Waylandu spusteni nikdy neohlasi)
LAUNCH_FEEDBACK_MS = 15000
# Prechod po prihlaseni (--intro): posledni snimek greeteru (LOGIN_FRAME) s barem prubehu, plocha se objevi az
# nakreslena. Bez Docku (dock_zone) se po liste ceka nejvys INTRO_DOCK_MS, vzdy konec po INTRO_MAX_MS (relace bez
# shellu). Bez snimku cerna jako v X11 bez snimku od greeteru.
LOGIN_FRAME = "/run/luxos-greeter/login-frame"
LOGIN_FRAME_MAX_AGE = 60
# Predani obrazovky z greeteru do relace bez textove konzole: greeter po prihlaseni prepne na prazdny VT v grafickem
# rezimu (pripravi ho libluxos-greetd-vt.so v greetd), kde zustava jeho posledni snimek, dokud relace neprevezme VT 1
HANDOFF_VT = 12
HANDOFF_MAX_AGE = 20
INTRO_COLOR = 0xFF000000
INTRO_DOCK_MS = 1500
INTRO_SETTLE_MS = 100
INTRO_MAX_MS = 10000
intro = {"on": False, "backgrounds": [], "bar": False, "timer": 0}
session_stopped = {"done": False}
settings = {}
binds = {}           # id zkratky -> akce
outputs = []
ws = []              # id ploch, cur = index zobrazene
spare_ws = []        # plochy odebrane zmenou poctu ploch (apply_workspaces)
cur = 0
mru = []             # okna od naposledy zamereneho
saved = {}           # okno -> [x, y, w, h] pred maximalizaci, pulkou nebo celou obrazovkou
maxed = {}
# okno -> vyska zahlavi pred celou obrazovkou; VIEW_FULLSCREEN a DECO_TOP jadra se zmeni az po
# potvrzeni klientem, politika potrebuje stav hned
full = {}
tiled = {}           # okno -> "left" / "right"
has_xdg_deco = {}    # okna, ktera pouzila xdg-decoration (CSD/SSD si ridi sama)
hidden_desktop = []  # okna schovana "ukazat plochu"
last_title_click = [0, 0]
# Okno s vlastnim zahlavim (GTK headerbar, Firefox): dvojklik na jeho zahlavi klient vyridi sam jako zadost o
# maximalizaci, kompozitor ho nevidi. Poznamenaji se proto stisky v klientske casti: [okno, cas, x, y, dvojklik do
# zahlavi]; zadost o maximalizaci hned po takovem dvojkliku se vyridi podle double_click_action (viz request).
client_press = {"view": 0, "at": 0, "x": 0, "y": 0, "double_at": 0, "double_view": 0}
TITLE_ZONE = 64             # px od horniho okraje okna, kde dvojklik bere jako dvojklik do zahlavi
TITLE_REQUEST_US = 300000   # zadost o maximalizaci do 0,3 s po dvojkliku je z nej

# Alt+Tab: seznam, poloha, puvodni okno, docasne ukazana minimalizovana okna, zkratka Esc
cycle = {"on": False, "list": [], "pos": 0, "from": 0, "shown": [], "cancel": 0}

LOCALE = "org.freedesktop.locale1"
IPC_TOPICS = ["window", "workspace", "keyboard", "modifiers", "output", "theme", "cycle", "media"]
# informace o cizich oknech a jejich ovladani jen pro allowlist (jako wlr-foreign-toplevel)
PRIVILEGED_TOPICS = ["window"]
PRIVILEGED_COMMANDS = ["list_windows", "focus_window", "set_primary", "test_output", "dock_zone"]

deferred = {"on": False, "items": []}
ipc = {}             # klient IPC -> {"privileged": bool, "topics": [...]}
keyboard = {"layouts": [], "locale": {}, "repeat": {}}
look = {"dark": False}
last_window = [-1, "", "", []]
# Dock bez exkluzivni zony (uhyba oknum): nazev vystupu -> [klient IPC, vyska od spodniho okraje].
# Nova okna se umistuji nad nej, jako na X11 s Plankem.
dock_zones = {}
# korenove okno Xwayland aplikace v sandboxu (cela X obrazovka v jednom okne) -> instance sandboxu;
# xroot_pending: velikost a nazev od luxos-sandbox, ktere prisly pred namapovanim okna
xroots = {}
xroot_pending = {}
XWAYLAND_APP_ID = "org.freedesktop.Xwayland"
XROOT_MIN = [320, 200]   # mensi korenove okno Xwayland neumi
# hlavni monitor (Dock, oznameni, okna z odpojenych monitoru) podle nastaveni monitoru; displays_run =
# odlozene spusteni displays_command po pripojeni/odpojeni monitoru
displays = {"primary": "", "timer": 0}

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
            # stejna zkratka zapsana jinym poradim modifikatoru musi uzivatel prepsat
            keys[canonical(name)] = value
        else:
            general[name] = value
        end
    end
    return True
end

function load_config():
    global settings
    general = {"workspaces": "4", "slide_ms": String(tokens.MOTION["workspace"]), "wrap_workspaces": "yes",
               "wrap_windows": "yes", "wrap_resistance": "10",
               "xwayland": "yes", "displays_command": "", "blur": "yes", "vrr": "fullscreen", "tearing": "yes",
               "night_light": "off", "night_light_temperature": "4000", "night_light_from": "21:00", "night_light_to": "07:00"}
    keys = {}
    if greeter:
        # prihlasovaci obrazovka bezi pod uzivatelem greetd: zadna konfigurace, zadne zkratky
        general.update({"workspaces": "1", "slide_ms": "0", "xwayland": "no"})
        settings = general
        settings["keys"] = {}
        return
    end
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
    # prihlasovaci obrazovka privilegovane protokoly nedava; LUXWM_PRIVILEGED nastavuji jen testy (harness)
    if greeter and path == PRIVILEGED:
        return
    end
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

# "<Super><Ctrl>Left" -> "<Primary><Super>Left" (poradi jako gtk_accelerator_name, pismeno male)
function canonical(text):
    parsed = parse_accel(text)
    if len(parsed) != 2:
        return text.strip()
    end
    parts = text.split(">")
    key = parts[len(parts) - 1].strip()
    if len(key) == 1:
        key = key.lower()
    end
    out = ""
    for pair in [[lc.MOD_CTRL, "<Primary>"], [lc.MOD_SHIFT, "<Shift>"], [lc.MOD_ALT, "<Alt>"], [lc.MOD_SUPER, "<Super>"]]:
        if parsed[0] & pair[0]:
            out += pair[1]
        end
    end
    return out + key
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
           "move_window_right_workspace_key", "next_layout_key", "volume_up_key", "volume_down_key",
           "volume_mute_key", "brightness_up_key", "brightness_down_key", "mic_mute_key",
           "media_play_key", "media_next_key", "media_previous_key", "quit"]

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
            if action == "left_workspace_key" or action == "right_workspace_key":
                id = lc.bind_key_repeat(parsed[0], parsed[1])
            else:
                id = lc.bind_key(parsed[0], parsed[1])
            end
        end
        if id == 0:
            call log("bad shortcut " + accel)
            continue
        end
        binds[id] = action
    end
    # Oba Shifty zpracuje primo luxwm. XKB pravidlo se v apply_keyboard vynecha,
    # aby jedno gesto nemohlo prepnout rozlozeni dvakrat.
    if "grp:shifts_toggle" in keyboard_names()[2].split(","):
        for key in ["Shift_L", "Shift_R"]:
            id = lc.bind_key(lc.MOD_SHIFT, key)
            if id != 0:
                binds[id] = "next_layout_key"
            end
        end
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

function with_alpha(c, a):
    return [c[0], c[1], c[2], a]
end

# Zahlavi podle tokens.TITLEBAR (stejne jako zahlavi GTK v luxos-themes). Inkoust (nazev, neaktivni semafor)
# je pro svetle i tmave zahlavi: jadro bere barvu zahlavi z obsahu okna, tmavy terminal ma tmave zahlavi
# i ve svetlem rezimu.
# Velikost tlacitek oken jako na X11 (Nastaveni > Monitory > Tlacitka oken, luxos-appearance wm-buttons):
# WM_BUTTONS v ~/.config/luxos/appearance.conf - standard 1x, large 1,5x, larger 2x; auto = na dotykove
# obrazovce (luxos-touch: touch-state "touchscreen=1") 1,5x, jinak 1x. Meritko vystupu resi jadro samo.
function button_factor():
    choice = "auto"
    safe:
        for raw in readfile(glib.user_config_dir() + "/luxos/appearance.conf").split(chr(10)):
            line = raw.strip()
            if line.startswith("WM_BUTTONS="):
                choice = line[11:].strip().strip("\"'")
            end
        end
    end
    if choice == "larger":
        return 2.0
    elif choice == "large":
        return 1.5
    elif choice == "standard":
        return 1.0
    end
    touch = ""
    safe:
        touch = readfile(glib.user_config_dir() + "/luxos/touch-state")
    end
    if touch.find("touchscreen=1") >= 0:
        return 1.5
    end
    return 1.0
end

# Zahlavi s tlacitky zvetsenymi o factor: tlacitka, rozestup a odsazeni rostou, vyska zahlavi jen tolik,
# aby kolem tlacitka zustal stejny okraj
function titlebar_metrics(t, factor):
    m = {}
    for k in ["height", "height_compact", "light", "pitch", "inset", "inset_compact"]:
        m[k] = t[k]
    end
    if factor <= 1.0:
        return m
    end
    light = Int(Float(t["light"]) * factor + 0.5)
    grow = light - t["light"]
    m["light"] = light
    m["pitch"] = Int(Float(t["pitch"]) * factor + 0.5)
    m["inset"] = t["inset"] + grow
    m["inset_compact"] = t["inset_compact"] + grow
    m["height"] = t["height"] + grow
    m["height_compact"] = t["height_compact"] + grow
    return m
end

function apply_theme(dark):
    look["dark"] = dark
    t = titlebar_metrics(tokens.TITLEBAR, button_factor())
    for k in tokens.TITLEBAR:
        if not (k in t):
            t[k] = tokens.TITLEBAR[k]
        end
    end
    window = tokens.color("window", dark)
    call lc.theme_set(lc.THEME_TITLE_HEIGHT, t["height"])
    call lc.theme_set(lc.THEME_TITLE_HEIGHT_COMPACT, t["height_compact"])
    call lc.theme_set(lc.THEME_CORNER_RADIUS, tokens.RADIUS["m"])
    call lc.theme_set(lc.THEME_BUTTON_SIZE, t["light"])
    call lc.theme_set(lc.THEME_BUTTON_SPACING, t["pitch"] - t["light"])
    call lc.theme_set(lc.THEME_BUTTON_INSET, t["inset"])
    call lc.theme_set(lc.THEME_BUTTON_INSET_COMPACT, t["inset_compact"])
    call lc.theme_set(lc.THEME_BG_ACTIVE, argb(window))
    call lc.theme_set(lc.THEME_BG_INACTIVE, argb(window))
    call lc.theme_set(lc.THEME_BG_LIGHT, argb(tokens.color("window", False)))
    call lc.theme_set(lc.THEME_BG_DARK, argb(tokens.color("window", True)))
    for mode in [False, True]:
        fg = tokens.color("fg", mode)
        ink = [255, 255, 255] if mode else [0, 0, 0]
        props = [lc.THEME_TEXT_ACTIVE, lc.THEME_TEXT_INACTIVE, lc.THEME_BUTTON_INACTIVE, lc.THEME_BUTTON_RING]
        if mode:
            props = [lc.THEME_DARK_TEXT_ACTIVE, lc.THEME_DARK_TEXT_INACTIVE, lc.THEME_DARK_BUTTON_INACTIVE,
                     lc.THEME_DARK_BUTTON_RING]
        end
        call lc.theme_set(props[0], argb(with_alpha(fg, 1.0)))
        call lc.theme_set(props[1], argb(with_alpha(fg, t["inactive_title_alpha"])))
        call lc.theme_set(props[2], argb(with_alpha(ink, t["light_inactive_alpha"])))
        call lc.theme_set(props[3], argb(with_alpha(ink, t["light_ring_alpha"])))
    end
    call lc.theme_set(lc.THEME_CLOSE, argb(tokens.COLORS["light_close"]))
    call lc.theme_set(lc.THEME_MINIMIZE, argb(tokens.COLORS["light_min"]))
    call lc.theme_set(lc.THEME_MAXIMIZE, argb(tokens.COLORS["light_max"]))
    # zahlavi splyva s obsahem okna, bez cary pod nim
    call lc.theme_set(lc.THEME_SEPARATOR, 0)
    call lc.theme_set(lc.THEME_GLYPH, argb(tokens.COLORS["light_glyph"]))
    call lc.theme_set(lc.THEME_ACCENT, argb(tokens.COLORS["accent"]))
    call lc.theme_set(lc.THEME_BORDER, argb(t["border_dark"] if dark else t["border_light"]))
    shadow = tokens.WINDOW_SHADOW
    call lc.theme_set(lc.THEME_SHADOW_ACTIVE, argb([0, 0, 0, shadow["active_alpha"]]))
    call lc.theme_set(lc.THEME_SHADOW_INACTIVE, argb([0, 0, 0, shadow["inactive_alpha"]]))
    call lc.theme_set(lc.THEME_SHADOW_ACTIVE_SIZE, shadow["active_size"])
    call lc.theme_set(lc.THEME_SHADOW_INACTIVE_SIZE, shadow["inactive_size"])
    call lc.theme_set(lc.THEME_SHADOW_ACTIVE_OFFSET, shadow["active_y"])
    call lc.theme_set(lc.THEME_SHADOW_INACTIVE_OFFSET, shadow["inactive_y"])
    call lc.theme_set_font(tokens.FONT["family"] + " Semi-Bold " + String(t["title_px"]) + "px")
    call apply_material(dark)
    # pod tapetou (vrstva background) stejna nahradni barva jako u skla bez tapety
    fb = tokens.GLASS["fallback"]
    bg = [Int(fb[0] * 255.0), Int(fb[1] * 255.0), Int(fb[2] * 255.0), 1.0]
    if greeter:
        # prihlasovaci obrazovka prebira obraz od splashe (Plymouth, luxos.script bg_r/g/b): do prvniho snimku
        # greeteru stejne temer cerne pozadi jako splash, ne svetla plocha
        bg = [1, 2, 7, 1.0]
    end
    call lc.set_background(argb(bg))
    call note("theme " + ("dark" if dark else "light"))
    call broadcast("theme", theme_event())
end

# Material ploch shellu v kompozitoru (luxcomp_material_set): nahradni nepruhledna barva = tonovani,
# stin podle vysky; dim pod Launchpadem. blur = no v luxwm.conf nechava jen nepruhlednou barvu.
function apply_material(dark):
    for surface in tokens.SURFACE.keys():
        m = tokens.material(surface, dark, True)
        e = tokens.elevation(surface, dark)
        fallback = [m[0], m[1], m[2], 1.0]
        if surface == "dim":
            d = tokens.DIM["fallback"]
            fallback = [d[0], d[1], d[2], 1.0]
        end
        call lc.material_set(surface, tokens.radius_of(surface), argb(fallback), argb([0, 0, 0, e[2]]), e[0], e[1])
    end
    # Material pro cele okno s hranou widgetu. Stin kresli dekorace okna.
    tint = tokens.material("popup", dark, True)
    call lc.material_set("widget", tokens.WIDGET_RADIUS, argb([tint[0], tint[1], tint[2], 1.0]), 0, 0, 0)
    call lc.blur_set(tokens.BLUR["radius"], Int(tokens.BLUR["saturation"] * 100.0 + 0.5), 1 if settings.get("blur", "yes") != "no" else 0)
    return 0
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
    # Volbu obou Shiftu obsluhuji vazby vyse; ostatni XKB volby zustavaji aktivni.
    xkb_options = ",".join([item for item in names[2].split(",") if item != "grp:shifts_toggle" and item != ""])
    call lc.set_keymap(names[0], names[1], xkb_options)
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
    call bind_keys()
    for client in ipc.keys():
        if ipc[client].get("suspend", False):
            for id in binds.keys():
                call lc.unbind_key(id)
            end
            binds.clear()
            break
        end
    end
end

# Opakovani drzene klavesy (Nastaveni > Klavesnice): znaky za sekundu (0 = vypnuto) a prodleva v ms,
# vychozi jako libluxcomp
function apply_repeat():
    rate = 25
    delay = 600
    if settings.get("repeat_rate", "") != "":
        rate = setting_int("repeat_rate", 0, 100)
    end
    if settings.get("repeat_delay", "") != "":
        delay = setting_int("repeat_delay", 100, 3000)
    end
    call lc.set_repeat(rate, delay)
    keyboard["repeat"] = {"rate": rate, "delay": delay}
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

# Kurzor jako v GTK na X11 (gtk-3.0/settings.ini z luxos-desktop: WhiteSur-cursors 24, uzivatel
# prepise v ~/.config); XCURSOR_THEME a XCURSOR_SIZE prostredi relace maji prednost
session_cursor = [glib.getenv("XCURSOR_THEME"), glib.getenv("XCURSOR_SIZE")]

function apply_cursor():
    found = {"gtk-cursor-theme-name": "", "gtk-cursor-theme-size": "24"}
    for path in ["/etc/xdg/gtk-3.0/settings.ini", "/etc/xdg/luxos/gtk-3.0/settings.ini",
                 glib.user_config_dir() + "/gtk-3.0/settings.ini"]:
        text = ""
        safe:
            text = readfile(path)
        end
        for raw in text.split(chr(10)):
            eq = raw.find("=")
            if eq > 0 and raw[:eq].strip() in found:
                found[raw[:eq].strip()] = raw[eq + 1:].strip()
            end
        end
    end
    theme = found["gtk-cursor-theme-name"]
    size_text = found["gtk-cursor-theme-size"]
    if session_cursor[0] != None and session_cursor[0] != "":
        theme = session_cursor[0]
    end
    if session_cursor[1] != None and session_cursor[1] != "":
        size_text = session_cursor[1]
    end
    size = 24
    try:
        size = max(8, min(256, Int(size_text)))
    else:
        call log("bad cursor size " + size_text)
    end
    call lc.set_cursor(theme, size)
    call note("cursor " + theme + " " + String(size))
end

# Mys a touchpad (Nastaveni > Mys a touchpad): polozky mouse_* a touchpad_* v luxwm.conf. Chybejici nebo
# prazdna polozka = vychozi hodnota zarizeni z libinput, i kdyz predtim byla nastavena (reload).
INPUT_KINDS = {"mouse": lc.INPUT_MOUSE, "touchpad": lc.INPUT_TOUCHPAD}
INPUT_OPTIONS = {"speed": lc.INPUT_SPEED, "accel": lc.INPUT_ACCEL_PROFILE, "natural_scroll": lc.INPUT_NATURAL_SCROLL,
                 "left_handed": lc.INPUT_LEFT_HANDED, "middle_emulation": lc.INPUT_MIDDLE_EMULATION, "tap": lc.INPUT_TAP,
                 "tap_drag": lc.INPUT_TAP_DRAG, "disable_while_typing": lc.INPUT_DISABLE_WHILE_TYPING,
                 "click_method": lc.INPUT_CLICK_METHOD, "scroll_method": lc.INPUT_SCROLL_METHOD}
# nazvy hodnot v poradi cisel jadra
INPUT_NAMES = {"accel": ["adaptive", "flat"], "click_method": ["none", "areas", "clickfinger"],
               "scroll_method": ["none", "two_finger", "edge", "button"]}
input_config = {}

# Text z luxwm.conf -> cislo pro jadro, None = vychozi hodnota zarizeni
function input_value(option, text):
    if text == "":
        return None
    end
    if option == "speed":
        value = None
        safe:
            value = max(-100, min(100, Int(text)))
        end
        return value
    end
    if option in INPUT_NAMES:
        if text in INPUT_NAMES[option]:
            return INPUT_NAMES[option].index(text)
        end
        return None
    end
    if text in ["yes", "true", "on", "1"]:
        return 1
    end
    if text in ["no", "false", "off", "0"]:
        return 0
    end
    return None
end

# Cislo jadra -> hodnota v IPC: rychlost cislem, metoda nazvem, ostatni bool
function input_json(option, value):
    if option == "speed":
        return value
    end
    if option in INPUT_NAMES:
        names = INPUT_NAMES[option]
        return names[value] if value >= 0 and value < len(names) else String(value)
    end
    return value == 1
end

# Hry: VRR a tearing po vystupech (luxwm.conf vrr, tearing)
VRR_MODES = {"no": lc.VRR_OFF, "fullscreen": lc.VRR_FULLSCREEN, "always": lc.VRR_ALWAYS}

function apply_gaming(out):
    vrr = settings.get("vrr", "fullscreen")
    if vrr not in VRR_MODES:
        call log("bad vrr = " + String(vrr))
        vrr = "fullscreen"
    end
    call lc.output_set(out, lc.OUT_VRR, VRR_MODES[vrr])
    call lc.output_set(out, lc.OUT_TEARING, 0 if settings.get("tearing", "yes") == "no" else 1)
end

# ---- nocni svetlo a softwarovy jas ----------------------------------------------------------------
# luxwm.conf: night_light = off | on | schedule (od night_light_from do night_light_to, i pres pulnoc),
# night_light_temperature v kelvinech. Rychle prepnuti (Ovladaci centrum) v rezimu schedule plati do pristi
# hranice rozvrhu, v rezimech on/off se ulozi. Jas monitoru bez podsviceni: ~/.config/luxos/brightness
# (uklada Ovladaci centrum, za behu IPC set_brightness). Vystup kresli libluxcomp (gamma tabulka nebo zavoj).
NIGHT_MODES = ["off", "on", "schedule"]
# override = [chteny stav, stav rozvrhu pri prepnuti]: plati, dokud se stav rozvrhu nezmeni
night = {"override": None, "timer": 0, "brightness": 100, "on": False}

function clock_minutes(text, fallback):
    parts = String(text).strip().split(":")
    value = -1
    if len(parts) == 2 and len(parts[1]) == 2:
        safe:
            value = Int(parts[0]) * 60 + Int(parts[1])
        end
    end
    if value < 0 or value >= 1440:
        return fallback
    end
    return value
end

function clock_text(minutes):
    return String(minutes // 60) + ":" + String(minutes % 60 // 10) + String(minutes % 10)
end

function night_mode():
    mode = settings.get("night_light", "off")
    return mode if mode in NIGHT_MODES else "off"
end

function night_kelvin():
    value = 4000
    safe:
        value = Int(settings.get("night_light_temperature", "4000"))
    end
    return max(1000, min(6500, value))
end

function night_window():
    return [clock_minutes(settings.get("night_light_from", ""), 21 * 60), clock_minutes(settings.get("night_light_to", ""), 7 * 60)]
end

function night_scheduled():
    t = lglib.localtime(lglib.now())
    now = t[3] * 60 + t[4]
    w = night_window()
    if w[0] <= w[1]:
        return now >= w[0] and now < w[1]
    end
    return now >= w[0] or now < w[1]
end

function night_active():
    mode = night_mode()
    if mode != "schedule":
        return mode == "on"
    end
    scheduled = night_scheduled()
    if night["override"] != None:
        if night["override"][1] == scheduled:
            return night["override"][0]
        end
        night["override"] = None
    end
    return scheduled
end

function read_brightness():
    value = 100
    safe:
        value = Int(readfile(glib.user_config_dir() + "/luxos/brightness").strip())
    end
    night["brightness"] = max(10, min(100, value))
end

function apply_night():
    on = not greeter and night_active()
    night["on"] = on
    call lc.set_night_light(night_kelvin() if on else 6500, 100 if greeter else night["brightness"])
    # rozvrh: kontrola kazdou minutu (sedi i po zmene casu a probuzeni z uspani)
    schedule = not greeter and night_mode() == "schedule"
    if schedule and night["timer"] == 0:
        night["timer"] = glib.timeout_add_seconds(60, night_tick)
    elif not schedule and night["timer"] != 0:
        call glib.source_remove(night["timer"])
        night["timer"] = 0
    end
end

function night_tick():
    if night_active() != night["on"]:
        call apply_night()
    end
    return True
end

function night_state():
    w = night_window()
    return {"ok": True, "mode": night_mode(), "on": night["on"], "temperature": night_kelvin(),
            "from": clock_text(w[0]), "to": clock_text(w[1]), "brightness": night["brightness"]}
end

# {"on": bool} rychle prepnuti; {"mode", "temperature", "from", "to"} z Nastaveni (ulozi se do luxwm.conf)
function set_night_light(request):
    save = {}
    on = request.get("on", None)
    if on != None:
        if type(on) != "Bool":
            return {"ok": False, "error": "bad request"}
        end
        if night_mode() == "schedule":
            scheduled = night_scheduled()
            night["override"] = None if on == scheduled else [on, scheduled]
        else:
            save["night_light"] = "on" if on else "off"
        end
    end
    mode = request.get("mode", None)
    if mode != None:
        if mode not in NIGHT_MODES:
            return {"ok": False, "error": "bad mode"}
        end
        save["night_light"] = mode
        night["override"] = None
    end
    kelvin = request.get("temperature", None)
    if kelvin != None:
        if type(kelvin) != "Int" or kelvin < 1000 or kelvin > 6500:
            return {"ok": False, "error": "bad temperature"}
        end
        save["night_light_temperature"] = String(kelvin)
    end
    for key in ["from", "to"]:
        value = request.get(key, None)
        if value != None:
            if type(value) != "String" or clock_minutes(value, -1) < 0:
                return {"ok": False, "error": "bad time"}
            end
            save["night_light_" + key] = clock_text(clock_minutes(value, 0))
        end
    end
    if len(save) > 0:
        settings.update(save)
        if not wmconf.save(save, {}):
            call log("cannot save night light to " + wmconf.user_path())
        end
    end
    call apply_night()
    return night_state()
end

# Hra nebo video na cele obrazovce nenecha obrazovku zhasnout ani zamknout; hry pres XWayland a
# Proton idle-inhibit nemaji (XScreenSaverSuspend se do Waylandu nedostane), proto kazde celoobrazovkove X11 okno
idle_held = False

function update_idle_inhibit():
    global idle_held
    v = focused()
    on = v != 0 and v in full and vget(v, lc.VIEW_VISIBLE) == 1
    on = on and (vget(v, lc.VIEW_CONTENT_TYPE) >= lc.CONTENT_VIDEO or vget(v, lc.VIEW_X11) == 1)
    if on != idle_held:
        idle_held = on
        call lc.idle_inhibit(1 if on else 0)
        call note("idle inhibit " + String(on))
    end
end

function apply_input():
    global input_config
    config = {}
    for kind in INPUT_KINDS.keys():
        config[kind] = {}
        for option in INPUT_OPTIONS.keys():
            name = kind + "_" + option
            text = String(settings.get(name, "")).strip()
            value = input_value(option, text)
            if value == None and text != "":
                call log("bad " + name + " = " + text)
            end
            call lc.input_set(INPUT_KINDS[kind], INPUT_OPTIONS[option], value if value != None else lc.INPUT_DEFAULT)
            config[kind][option] = input_json(option, value) if value != None else None
        end
    end
    input_config = config
end

# Co skutecne nastavil libinput, po zarizenich (headless backend zadna nema)
function input_devices():
    out = []
    d = lc.input_next(0)
    while d != 0:
        kind = lc.input_get(d, lc.INPUT_KIND)
        item = {"name": lc.input_name(d), "kind": "touchpad" if kind == lc.INPUT_TOUCHPAD else "mouse"}
        for option in INPUT_OPTIONS.keys():
            value = lc.input_get(d, INPUT_OPTIONS[option])
            if value != lc.INPUT_NONE:
                item[option] = input_json(option, value)
            end
        end
        out.append(item)
        d = lc.input_next(d)
    end
    return out
end

# ---- geometrie -------------------------------------------------------------------------------

function usable(out):
    return [lc.output_get(out, lc.OUT_USABLE_X), lc.output_get(out, lc.OUT_USABLE_Y),
            lc.output_get(out, lc.OUT_USABLE_W), lc.output_get(out, lc.OUT_USABLE_H)]
end

# Kam se umistuji nova okna: pouzitelna plocha bez Docku (exkluzivni zona, nebo dock_zone kdyz jen uhyba)
# a s okrajem PLACE_MARGIN, aby okno nelezelo na liste ani na Docku
function place_area(out):
    u = usable(out)
    zone = dock_zones.get(lc.output_name(out))
    if zone != None:
        bottom = min(u[1] + u[3], lc.output_get(out, lc.OUT_Y) + lc.output_get(out, lc.OUT_H) - zone[1])
        if bottom - u[1] >= u[3] // 2:
            u = [u[0], u[1], u[2], bottom - u[1]]
        end
    end
    m = PLACE_MARGIN
    return [u[0] + m, u[1] + m, u[2] - 2 * m, u[3] - 2 * m]
end

# Ram okna (obsah + zahlavi kompozitoru): [x, y, w, h]
# Okno cele do pouzitelne plochy u: vetsi se zmensi (ne pod minimum), pak se posune dovnitr
function keep_inside(v, u):
    call fit_size(v, vget(v, lc.VIEW_W), vget(v, lc.VIEW_H), u)
    f = frame(v)
    x = max(u[0], min(f[0], u[0] + u[2] - f[2]))
    y = max(u[1], min(f[1], u[1] + u[3] - f[3]))
    if x != f[0] or y != f[1]:
        call lc.view_move(v, x, y + vget(v, lc.VIEW_DECO_TOP))
        call note("inside " + String(v) + " " + String(x) + "," + String(y))
    end
    return 0
end

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
    if out == 0:
        out = primary_output()
    end
    return out
end

# Hlavni monitor: zvoleny v nastaveni monitoru (set_primary), kdyz je zapnuty; jinak zapnuty monitor
# nejvic vlevo nahore. 0 = zadny zapnuty.
function primary_output():
    best = 0
    for out in outputs:
        if lc.output_get(out, lc.OUT_W) <= 0:
            continue
        end
        if lc.output_name(out) == displays["primary"]:
            return out
        end
        x = lc.output_get(out, lc.OUT_X)
        y = lc.output_get(out, lc.OUT_Y)
        if best == 0 or x < lc.output_get(best, lc.OUT_X) or (x == lc.output_get(best, lc.OUT_X) and y < lc.output_get(best, lc.OUT_Y)):
            best = out
        end
    end
    return best
end

# Okna, jejichz stred nelezi na zadnem zapnutem monitoru (odpojeny nebo vypnuty monitor), na hlavni monitor
function rescue_windows():
    target = primary_output()
    if target == 0:
        return
    end
    u = usable(target)
    o = lc.view_next(0)
    while o != 0:
        f = frame(o)
        if lc.output_at(f[0] + f[2] // 2, f[1] + f[3] // 2) == 0:
            w = min(f[2], u[2])
            h = min(f[3], u[3])
            if w != f[2] or h != f[3]:
                call lc.view_resize(o, w, h - vget(o, lc.VIEW_DECO_TOP))
            end
            call lc.view_move(o, u[0] + (u[2] - w) // 2, u[1] + (u[3] - h) // 2 + vget(o, lc.VIEW_DECO_TOP))
            if o in full:
                call fit_fullscreen(o)
            elif o in maxed:
                call fit_maximized(o)
            elif o in tiled:
                call fit_tiled(o)
            end
            call note("rescued " + String(o) + " to " + lc.output_name(target))
        else:
            call keep_reachable(o)
        end
        o = lc.view_next(o)
    end
end

# Po pripojeni/odpojeni monitoru (a pri startu) jednou nastaveni monitoru pro tuto sadu (luxos-displays auto);
# vic udalosti tesne po sobe (start, dokovaci stanice) spusti prikaz jen jednou
function displays_changed():
    if settings["displays_command"] == "":
        return
    end
    if displays["timer"] != 0:
        call glib.source_remove(displays["timer"])
    end
    displays["timer"] = glib.timeout_add(300, run_displays_command)
end

function run_displays_command():
    displays["timer"] = 0
    call note("displays: " + settings["displays_command"])
    call lc.spawn(settings["displays_command"])
    return False
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

# want = [w, h], ktere okno dostane (korenove okno Xwayland sandboxu), nebo [] = jeho velikost
function place(v, want):
    out = lc.output_at(lc.cursor_x(), lc.cursor_y())
    if out == 0:
        out = output_of(v)
    end
    u = place_area(out)
    if len(want) == 0:
        want = [vget(v, lc.VIEW_W), vget(v, lc.VIEW_H)]
    end
    size = fit_size(v, want[0], want[1], u)
    if lc.view_app_id(v) in AT_POINTER:
        return place_at_pointer(v, size[0], size[1], u)
    end
    return place_sized(v, size[0], size[1], u)
end

# Okna otevirana zkratkou nad prave psanym textem (Emoji a symboly, Super+.) jako na X11 u mysi: pod ni,
# kdyz se nevejde, nad ni; cele v pouzitelne plose. Klient na Waylandu svou polohu urcit nemuze.
AT_POINTER = ["luxos-emoji"]

function place_at_pointer(v, w, content_h, u):
    top = vget(v, lc.VIEW_DECO_TOP)
    h = content_h + top
    px = lc.cursor_x()
    py = lc.cursor_y()
    x = px - w // 2
    y = py + 18
    if y + h > u[1] + u[3]:
        y = py - h - 18
    end
    x = max(u[0] + 8, min(x, u[0] + u[2] - w - 8))
    y = max(u[1] + 8, min(y, u[1] + u[3] - h - 8))
    call lc.view_move(v, x, y + top)
    return [x, y]
end

# Okno vetsi nez plocha se zmensi, aby bylo cele videt (i tlacitka dole nad Dockem), jako v X11 relaci;
# ne pod svou minimalni velikost
function fit_size(v, w, h, u):
    top = vget(v, lc.VIEW_DECO_TOP)
    fw = min(w, max(u[2], vget(v, lc.VIEW_MIN_W)))
    fh = min(h, max(u[3] - top, vget(v, lc.VIEW_MIN_H)))
    if fw != vget(v, lc.VIEW_W) or fh != vget(v, lc.VIEW_H):
        call lc.view_resize(v, fw, fh)
        call note("shrink " + String(v) + " " + String(w) + "x" + String(h) + " -> " + String(fw) + "x" + String(fh))
    end
    return [fw, fh]
end

# Nove okno vodorovne uprostred, svisle v horni tretine volneho mista (jako macOS)
function place_sized(v, w, content_h, u):
    top = vget(v, lc.VIEW_DECO_TOP)
    h = content_h + top
    x = u[0] + (u[2] - w) // 2
    y = max(u[1], u[1] + (u[3] - h) // 3)
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

# Aplikace v sandboxu (wp-security-context): identitu dava spoustec (luxos-sandbox), ne aplikace.
# app_id okna si aplikace nastavi sama, proto "stejna aplikace" znamena i stejny sandbox.
function sandbox_id(v):
    if vget(v, lc.VIEW_SANDBOXED) != 1:
        return ""
    end
    return "sandbox:" + lc.view_sandbox_app_id(v) + ":" + lc.view_sandbox_instance(v)
end

function same_app(a, b):
    app = lc.view_app_id(a)
    return app != "" and lc.view_app_id(b) == app and sandbox_id(a) == sandbox_id(b)
end

# Okno ze sandboxu ma vzdy zahlavi kompozitoru se znackou (nejde vypnout ani podvrhnout z aplikace)
function sandbox_window(v):
    if vget(v, lc.VIEW_SANDBOXED) != 1:
        return
    end
    app = lc.view_sandbox_app_id(v)
    call lc.view_set_decorated(v, 1)
    call lc.view_set_badge(v, "Sandbox" + (" · " + app if app != "" else ""))
    call note("sandbox " + String(v) + " " + app)
end

# X11 aplikace v sandboxu bezi ve vlastnim Xwayland s korenovym oknem ("Xwayland on :0"). Lista, Dock
# a zahlavi ukazuji aplikaci ze sandboxu; velikost a nazev hlavniho okna X posila luxos-sandbox.
function adopt_xroot(v):
    if vget(v, lc.VIEW_SANDBOXED) != 1 or lc.view_app_id(v) != XWAYLAND_APP_ID:
        return []
    end
    instance = lc.view_sandbox_instance(v)
    app = lc.view_sandbox_app_id(v)
    xroots[v] = instance
    pending = xroot_pending.pop(instance, None)
    if pending == None:
        call lc.view_set_names(v, app, app)
        return []
    end
    call lc.view_set_names(v, app, pending[2] if pending[2] != "" else app)
    return [max(XROOT_MIN[0], pending[0]), max(XROOT_MIN[1], pending[1])]
end

function size_xroot(v, w, h, title):
    app = lc.view_sandbox_app_id(v)
    call lc.view_set_names(v, app, title if title != "" else app)
    if v in maxed or v in full or v in tiled:
        return
    end
    u = place_area(output_of(v))
    size = fit_size(v, max(XROOT_MIN[0], w), max(XROOT_MIN[1], h), u)
    # stred okna zustava (neskace do rohu), cele okno v plose
    f = frame(v)
    top = vget(v, lc.VIEW_DECO_TOP)
    x = max(u[0], min(f[0] + (f[2] - size[0]) // 2, u[0] + u[2] - size[0]))
    y = max(u[1], min(f[1] + (f[3] - size[1] - top) // 2, u[1] + u[3] - size[1] - top))
    call lc.view_move(v, x, y + top)
    call note("xroot " + String(v) + " " + String(size[0]) + "x" + String(size[1]))
end

# Nazev z X serveru sandboxu: jen tisknutelne znaky, kratky
function clean_title(text):
    out = ""
    for ch in text:
        if ord(ch) >= 32 and ord(ch) != 127:
            out += ch
        end
        if len(out) >= 120:
            break
        end
    end
    return out.strip()
end

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
# zustava ve stromu sve plochy, aby s ni odjelo a nezakryvalo jine plochy. Behem prejezdu ploch zustava
# ve strome plochy i zamerene: jinak by se objevilo hned nad vsim a s plochou neprijelo (EV_SLIDE_DONE
# ho pak zvedne).
sliding = {"on": False}

function update_layers(active):
    demoted = False
    o = lc.view_next(0)
    while o != 0:
        if o in full:
            layer = lc.LAYER_FULLSCREEN if o == active and not sliding["on"] else lc.LAYER_NORMAL
            demoted = demoted or (layer == lc.LAYER_NORMAL and vget(o, lc.VIEW_LAYER) == lc.LAYER_FULLSCREEN)
            call lc.view_set_layer(o, layer)
        end
        o = lc.view_next(o)
    end
    # okno vracene z vrstvy cele obrazovky prijde do stromu plochy navrch: zamerene okno (Alt+Tab z Firefoxu
    # na cele obrazovce na terminal) by zustalo pod nim
    if demoted and active != 0 and not (active in full):
        call lc.view_raise(active)
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

function motion_off():
    return greeter or settings.get("reduce_motion", "no") == "yes" or exists(glib.user_config_dir() + "/luxos/powersaver")
end

function apply_motion():
    for kind in List(ANIM_MS):
        call lc.anim_set(kind, ANIM_MS[kind])
    end
    ms = LAUNCH_FEEDBACK_MS
    safe:
        ms = Int(glib.getenv("LUXWM_LAUNCH_FEEDBACK_MS"))
    end
    call lc.launch_feedback(0 if greeter else ms)
end

# Sporic baterie se muze zapnout kdykoli, proto se kontroluje u kazde animace
function animate(v, kind):
    if not motion_off():
        call lc.view_animate(v, kind)
    end
end

function show(v, remember):
    if vget(v, lc.VIEW_VISIBLE) == 0:
        call lc.view_set_visible(v, 1)
        # Alt+Tab ukazuje minimalizovana okna jen docasne, bez animace
        if not cycle["on"]:
            call animate(v, lc.ANIM_RESTORE)
        end
    end
    call lc.view_raise(v)
    child = child_of(v)
    target = v
    if child != 0:
        call lc.view_raise(child)
        target = child
    end
    if vget(target, lc.VIEW_FOCUSED) == 0:
        focus_change["at"] = glib.monotonic_time()
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
        focus_change["at"] = glib.monotonic_time()
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
        call keep_reachable(v)
    end
end

# Zahlavi okna musi jit chytit (pripominka 28): ram nahore ne pod listou, nahore aspon vyska zahlavi nad spodkem
# pouzitelne plochy, vodorovne aspon REACH_X px na monitoru. Presun mysi hlida jadro (input.c keep_reachable).
function keep_reachable(v):
    if v in maxed or v in tiled or v in full:
        return
    end
    f = frame(v)
    out = lc.output_at(f[0] + f[2] // 2, f[1])
    if out == 0:
        out = output_of(v)
    end
    u = usable(out)
    if u[2] <= 0 or u[3] <= 0:
        return
    end
    top = vget(v, lc.VIEW_DECO_TOP)
    title = top if top > 0 else REACH_TITLE
    y = max(u[1], min(f[1], u[1] + u[3] - title))
    x = max(u[0] + REACH_X - f[2], min(f[0], u[0] + u[2] - REACH_X))
    if x != f[0] or y != f[1]:
        call lc.view_move(v, x, y + top)
        call note("reachable " + String(v) + " " + String(x) + "," + String(y))
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

# Okno pevne velikosti (min = max, dialogy X11): maximalizace ani pulka obrazovky by ho nezvetsily, zbyl by
# jen ram velky jako obrazovka
function fixed_size(v):
    w = vget(v, lc.VIEW_MAX_W)
    h = vget(v, lc.VIEW_MAX_H)
    return w > 0 and h > 0 and vget(v, lc.VIEW_MIN_W) == w and vget(v, lc.VIEW_MIN_H) == h
end

function set_maximized(v, on):
    if on and not (v in maxed) and fixed_size(v):
        call lc.view_set_state(v, lc.STATE_MAXIMIZED, 0)
        call note("maximize " + String(v) + " fixed size")
        return
    end
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
    if v in maxed or v in full or fixed_size(v):
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
    call animate(v, lc.ANIM_MINIMIZE)
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

# ---- horke rohy -------------------------------------------------------------------------------
# Jako na X11 (luxos_hotcorners.lsl v luxos-hubu, ktery na Waylandu polohu ukazatele mimo sva okna nezna):
# ~/.config/luxos/hotcorners radky "tl=launchpad" (Nastaveni > Plocha a Dock), vychozi jen levy horni Launchpad.
# Ukazatel musi v rohu zustat ~0,3 s (3 tiky po 100 ms), roh se znovu nabije az po odjeti dal nez 24 px.
# Rohy cele plochy (pri vice monitorech vnejsi rohy). Ne v prihlasovaci obrazovce, pri zamcene obrazovce,
# nad oknem na celou obrazovku (hry) ani na tabletu bez klavesnice (touch-state touchscreen=1 keyboard=0).
HOT_DEFAULTS = {"tl": "launchpad", "tr": "none", "bl": "none", "br": "none"}
HOT_ACTIONS = ["none", "launchpad", "desktop", "control-center", "lock", "screensaver"]
hot = {"conf": {}, "ticks": 0, "corner": "", "dwell": 0, "armed": True, "disabled": False}

function hot_reload():
    conf = {}
    for k in ["tl", "tr", "bl", "br"]:
        conf[k] = HOT_DEFAULTS[k]
    end
    text = ""
    touch = ""
    safe:
        text = readfile(glib.user_config_dir() + "/luxos/hotcorners")
    end
    safe:
        touch = readfile(glib.user_config_dir() + "/luxos/touch-state")
    end
    for raw in text.split(chr(10)):
        line = raw.strip()
        at = line.find("=")
        if line.startswith("#") or at < 0:
            continue
        end
        key = line[:at].strip()
        value = line[at + 1:].strip()
        if key in conf and value in HOT_ACTIONS:
            conf[key] = value
        end
    end
    hot["conf"] = conf
    hot["disabled"] = touch.find("touchscreen=1") >= 0 and touch.find("keyboard=0") >= 0
end

# [x0, y0, x1, y1] vsech vystupu (prazdne = zadny)
function hot_bounds():
    box = []
    for out in outputs:
        w = lc.output_get(out, lc.OUT_W)
        h = lc.output_get(out, lc.OUT_H)
        if w <= 0 or h <= 0:
            continue
        end
        x = lc.output_get(out, lc.OUT_X)
        y = lc.output_get(out, lc.OUT_Y)
        if len(box) == 0:
            box = [x, y, x + w, y + h]
        else:
            box = [min(box[0], x), min(box[1], y), max(box[2], x + w), max(box[3], y + h)]
        end
    end
    return box
end

function hot_run(action):
    if action == "launchpad":
        call lc.spawn("luxos-launchpad")
    elif action == "desktop":
        call show_desktop()
    elif action == "control-center":
        call lc.spawn("luxos-cc-toggle")
    elif action == "lock" or action == "screensaver":
        call lc.spawn("loginctl lock-session")
    end
end

function hot_tick():
    hot["ticks"] += 1
    if hot["ticks"] % 20 == 1:
        call hot_reload()
    end
    if hot["disabled"] or lc.locked() != 0:
        return True
    end
    box = hot_bounds()
    if len(box) == 0:
        return True
    end
    x = lc.cursor_x()
    y = lc.cursor_y()
    c = ""
    if x <= box[0] and y <= box[1]:
        c = "tl"
    elif x >= box[2] - 1 and y <= box[1]:
        c = "tr"
    elif x <= box[0] and y >= box[3] - 1:
        c = "bl"
    elif x >= box[2] - 1 and y >= box[3] - 1:
        c = "br"
    end
    if c == "":
        near_x = x < box[0] + 24 or x > box[2] - 1 - 24
        near_y = y < box[1] + 24 or y > box[3] - 1 - 24
        if not (near_x and near_y):
            hot["armed"] = True
        end
        hot["corner"] = ""
        return True
    end
    action = hot["conf"].get(c, "none")
    if action == "none" or not hot["armed"]:
        return True
    end
    out = lc.output_at(x, y)
    if out != 0 and lc.output_get(out, lc.OUT_FULLSCREEN) != 0:
        return True
    end
    if hot["corner"] != c:
        hot["corner"] = c
        hot["dwell"] = 0
        return True
    end
    hot["dwell"] += 1
    if hot["dwell"] >= 3:
        hot["armed"] = False
        call hot_run(action)
    end
    return True
end

# ---- plochy ----------------------------------------------------------------------------------

function switch_to(index, hint):
    global cur
    if index < 0 or index >= len(ws) or index == cur:
        return
    end
    old = cur
    cur = index
    ms = setting_int("slide_ms", 0, 2000)
    if settings.get("reduce_motion", "no") == "yes":
        ms = 0
    end
    # zamereni hned (klavesnice patri nove plose uz behem prejezdu); celoobrazovkove okno stare
    # plochy se tim vrati do jejiho stromu a odjede s ni, okno nove plochy s ni prijede
    sliding["on"] = ms > 0
    call focus(top_on_current(0))
    if hint != 0:
        direction = hint
    else:
        direction = 1 if index > old else -1
    end
    call lc.workspace_slide(ws[old], ws[index], direction, ms)
    call note("workspace " + String(index + 1))
    call broadcast("workspace", workspace_event())
end

# Zmena poctu ploch za behu (reload): jadro plochu zrusit neumi, odebrana ceka v spare_ws na dalsi
# pridani; jeji okna prejdou na posledni zbyvajici plochu
function apply_workspaces():
    global cur
    # tazene okno na okraji obrazovky prejde na vedlejsi plochu (xfwm4 wrap_windows, wrap_resistance)
    call lc.set_wrap_resistance(setting_int("wrap_resistance", 1, 100) if settings.get("wrap_windows", "yes") == "yes" else 0)
    count = setting_int("workspaces", 1, 16)
    if count == len(ws):
        return
    end
    while len(ws) < count:
        if len(spare_ws) > 0:
            ws.append(spare_ws.pop())
        else:
            ws.append(lc.workspace_new())
        end
    end
    if len(ws) > count:
        last = ws[count - 1]
        gone = ws[count:]
        o = lc.view_next(0)
        while o != 0:
            if vget(o, lc.VIEW_WORKSPACE) in gone:
                call lc.view_set_workspace(o, last)
            end
            o = lc.view_next(o)
        end
        if cur >= count:
            call lc.workspace_slide(ws[cur], last, -1, 0)
            cur = count - 1
            call focus(top_on_current(0))
        end
        while len(ws) > count:
            spare_ws.append(ws.pop())
        end
    end
    call note("workspaces " + String(count))
    call broadcast("workspace", workspace_event())
end

function step_index(delta):
    index = cur + delta
    if settings["wrap_workspaces"] == "yes":
        index = (index + len(ws)) % len(ws)
    end
    return index
end

# Tazene okno dojelo na levy/pravy okraj obrazovky a tlaci dal (luxcomp EV_MOVE_EDGE): jako xfwm4 wrap_windows
# okno i uzivatel na vedlejsi plochu (s wrap_workspaces dokola), ukazatel na protejsi okraj 10 px od nej,
# tah pokracuje
WRAP_INSET = 10

function move_wrap(v, dir):
    if settings.get("wrap_windows", "yes") != "yes" or len(ws) < 2 or v == 0:
        return
    end
    index = step_index(dir)
    if index < 0 or index >= len(ws) or index == cur:
        return
    end
    left = 0
    right = 0
    first = True
    for out in outputs:
        w = lc.output_get(out, lc.OUT_W)
        if w <= 0:
            continue
        end
        x = lc.output_get(out, lc.OUT_X)
        if first or x < left:
            left = x
        end
        if first or x + w > right:
            right = x + w
        end
        first = False
    end
    if first:
        return
    end
    call lc.view_set_workspace(v, ws[index])
    call switch_to(index, dir)
    x = left + WRAP_INSET if dir > 0 else right - 1 - WRAP_INSET
    call lc.cursor_warp(x, lc.cursor_y())
    call note("wrap " + String(v) + " workspace " + String(index + 1))
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
    call broadcast("cycle", cycle_event("start"))
    return True
end

function cycle_step(delta, app_only):
    if not cycle["on"] and not cycle_start(app_only):
        return
    end
    items = cycle["list"]
    cycle["pos"] = (cycle["pos"] + delta + len(items)) % len(items)
    v = items[cycle["pos"]]
    # jako xfwm4 na X11 (cycle_raise = false): okna se behem vyberu nehybou, vybrane se zameri az po
    # pusteni modifikatoru (cycle_end); vyber ukazuje jen panel luxos-switcher
    call note("cycle " + String(v))
    call broadcast("cycle", cycle_event("step"))
end

# Zavrene okno ze seznamu ven a prepinani pokracuje (jako tabwinRemoveClient v xfwm4); vybrane bylo-li
# zavrene, vybere se nasledujici
function cycle_drop(v):
    items = cycle["list"]
    index = 0
    while index < len(items) and items[index] != v:
        index += 1
    end
    call items.remove(v)
    if v in cycle["shown"]:
        call cycle["shown"].remove(v)
    end
    if cycle["from"] == v:
        cycle["from"] = 0
    end
    if len(items) == 0:
        call cycle_end(True)
        return
    end
    if index < cycle["pos"]:
        cycle["pos"] -= 1
    end
    cycle["pos"] = cycle["pos"] % len(items)
    call cycle_step(0, False)
end

function cycle_end(cancel):
    if not cycle["on"]:
        return
    end
    cycle["on"] = False
    call lc.unbind_key(cycle["cancel"])
    call broadcast("cycle", cycle_event("end"))
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
        call lc.launch_start()
    elif action == "cycle_windows_key":
        call cycle_step(1, False)
    elif action == "cycle_reverse_windows_key":
        call cycle_step(-1, False)
    elif action == "cycle_app_windows_key" or action == "switch_window_key":
        call cycle_step(1, True)
    elif action == "cycle_reverse_app_windows_key":
        call cycle_step(-1, True)
    elif action == "left_workspace_key":
        call switch_to(step_index(-1), -1)
    elif action == "right_workspace_key":
        call switch_to(step_index(1), 1)
    elif action.startswith("workspace_"):
        call switch_to(Int(action.split("_")[1]) - 1, 0)
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
    elif action == "next_layout_key":
        count = lc.layout_count()
        if count > 1:
            call switch_layout((lc.layout() + 1) % count)
        end
    elif action in ["volume_up_key", "volume_down_key", "volume_mute_key", "brightness_up_key",
                   "brightness_down_key", "mic_mute_key", "media_play_key", "media_next_key", "media_previous_key"]:
        call broadcast("media", {"event": "media", "action": action})
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
    if greeter:
        call lc.view_set_workspace(v, current_ws())
        call set_fullscreen(v, True)
        # GTK okno pri fullscreen znovu namapuje: zamereni vzdy, i kdyz uz cela obrazovka je
        call focus(v)
        return
    end
    parent = vget(v, lc.VIEW_PARENT)
    space = current_ws()
    if parent != 0:
        space = vget(parent, lc.VIEW_WORKSPACE)
    end
    call lc.view_set_workspace(v, space)
    if parent == 0 and v not in has_xdg_deco and vget(v, lc.VIEW_X11) == 0:
        call lc.view_set_decorated(v, 1)
    end
    call lc.view_set_compact(v, 1 if compact_window(v) else 0)
    spot = place(v, adopt_xroot(v))
    call note("place " + String(v) + " " + lc.view_app_id(v) + " " + String(spot[0]) + "," + String(spot[1])
        + " " + String(vget(v, lc.VIEW_W)) + "x" + String(vget(v, lc.VIEW_H)))
    # cela obrazovka uz od startu: xdg pozadavek pred prvnim commitem (SDL, mpv --fs) uz je ve full, X11 okno
    # s _NET_WM_STATE_FULLSCREEN pred namapovanim (Wine/Proton) zadny pozadavek neposle
    if v in full:
        # klient mel od zacatku velikost obrazovky: okno po opusteni cele obrazovky na 2/3 plochy
        u = place_area(output_of(v))
        w = u[2] * 2 // 3
        h = u[3] * 2 // 3
        saved[v] = [u[0] + (u[2] - w) // 2, u[1] + (u[3] - h) // 2, w, h]
        call fit_fullscreen(v)
    elif vget(v, lc.VIEW_FULLSCREEN) == 1:
        call set_fullscreen(v, True)
    end
    # Dialog na jine plose zustava na sve plose. Na aktualni plose ma nove okno fokus i nad fullscreenem:
    # caste jsou spusteni Terminalu nebo nove okno prohlizece bez xdg-activation.
    current = focused()
    if space != current_ws() or cycle["on"]:
        mru.insert(1 if len(mru) > 0 else 0, v)
        if current != 0:
            call lc.view_raise(current)
        end
        call note("background " + String(v))
    else:
        call focus(v)
    end
    if v not in full and space == current_ws():
        call animate(v, lc.ANIM_OPEN)
    end
end

# Nizke zahlavi: cizi aplikace a dialogy. Aplikace LuxOS maji bezne zahlavi jako jejich okna s GTK
# headerbarem, aby obe varianty vypadaly stejne.
function compact_window(v):
    app = lc.view_app_id(v)
    if vget(v, lc.VIEW_SANDBOXED) == 1:
        app = lc.view_sandbox_app_id(v)
    end
    return vget(v, lc.VIEW_PARENT) != 0 or not (app.startswith("luxos") or app.startswith("luxai"))
end

# Klient sam zvetsil okno (GTK po namapovani, aplikace podle obsahu): kdyz pretece pres plochu pro okna
# (pod Dock), zmensit a posunout zpet. Okno, ktere uzivatel odsunul mimo plochu, se nechava.
function view_resized(v):
    if v in maxed or v in tiled or v in full or vget(v, lc.VIEW_VISIBLE) != 1:
        return
    end
    u = place_area(output_of(v))
    f = frame(v)
    if not inside(f, u) or (f[0] + f[2] <= u[0] + u[2] and f[1] + f[3] <= u[1] + u[3]):
        return
    end
    top = vget(v, lc.VIEW_DECO_TOP)
    size = fit_size(v, f[2], f[3] - top, u)
    x = max(u[0], min(f[0], u[0] + u[2] - size[0]))
    y = max(u[1], min(f[1], u[1] + u[3] - size[1] - top))
    call lc.view_move(v, x, y + top)
    call note("refit " + String(v) + " " + String(x) + "," + String(y))
end

function view_gone(v):
    call animate(v, lc.ANIM_CLOSE)
    was = v == focused() or focused() == 0
    parent = vget(v, lc.VIEW_PARENT)
    if v in mru:
        call mru.remove(v)
    end
    if was:
        call focus_next(v, parent)
    end
    # az po focus_next: dalsi vybrane okno v Alt+Tab musi zustat vpredu a zamerene
    if cycle["on"] and v in cycle["list"]:
        call cycle_drop(v)
    end
end

function forget(v):
    for table in [saved, maxed, tiled, full, xroots, has_xdg_deco]:
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
# Velikost monitoru pri posledni zmene pouzitelne plochy: zmena rozliseni (okno virtualniho stroje, Nastaveni >
# Monitory) vrati okna cela na obrazovku jako xfwm4; zmena jen pouzitelne plochy (Dock, lista) okna nehybe
output_size = {}

function usable_changed(out):
    u = usable(out)
    size = [lc.output_get(out, lc.OUT_W), lc.output_get(out, lc.OUT_H)]
    resized = out in output_size and output_size[out] != size
    output_size[out] = size
    o = lc.view_next(0)
    while o != 0:
        if output_of(o) == out:
            if o in full:
                call fit_fullscreen(o)
            elif o in maxed:
                call fit_maximized(o)
            elif o in tiled:
                call fit_tiled(o)
            elif resized and vget(o, lc.VIEW_MAPPED) == 1:
                call keep_inside(o, u)
            else:
                call keep_reachable(o)
            end
        end
        o = lc.view_next(o)
    end
    call note("usable " + String(out) + " " + String(u[0]) + "," + String(u[1]) + " " + String(u[2]) + "x" + String(u[3]))
end

# Stisk v klientske casti okna: druhy rychly stisk na stejnem miste v hornim pasu okna = dvojklik do zahlavi
function note_client_press(v):
    now = glib.monotonic_time()
    x = lc.cursor_x()
    y = lc.cursor_y()
    if (client_press["view"] == v and now - client_press["at"] < DOUBLE_CLICK_US
            and abs(x - client_press["x"]) < 8 and abs(y - client_press["y"]) < 8
            and y - vget(v, lc.VIEW_Y) < TITLE_ZONE):
        client_press["double_at"] = now
        client_press["double_view"] = v
        client_press["view"] = 0
        return
    end
    client_press["view"] = v
    client_press["at"] = now
    client_press["x"] = x
    client_press["y"] = y
end

# Zadost o (od)maximalizaci hned po dvojkliku do vlastniho zahlavi klienta: nastaveni Dvojklik na zahlavi
# (Okna a plochy). True = vyrizeno tady
function title_double_click(v):
    if client_press["double_view"] != v or glib.monotonic_time() - client_press["double_at"] > TITLE_REQUEST_US:
        return False
    end
    client_press["double_view"] = 0
    action = settings.get("double_click_action", "maximize")
    if action == "hide":
        call minimize(v)
        return True
    elif action == "none":
        return True
    end
    return False
end

function button(v, pressed, part):
    if not pressed or v == 0 or part == lc.PART_LAYER:
        return
    end
    if cycle["on"]:
        call cycle_end(False)
    end
    if part == lc.PART_CLIENT:
        call note_client_press(v)
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
        # klik do zamereneho okna mu klavesnici potvrdi znovu: kdyby ji mezitim drzelo neco jineho (vrstva,
        # zavrena nabidka), psat by neslo az do Alt+Tab; okno, ktere klavesnici ma, to nezmeni
        call lc.view_focus(v)
    end
    if part == lc.PART_TITLE:
        now = glib.monotonic_time()
        if last_title_click[0] == v and now - last_title_click[1] < DOUBLE_CLICK_US:
            last_title_click[0] = 0
            # double_click_action jako xfwm4 (Nastaveni > Okna a plochy): maximize, hide, none
            action = settings.get("double_click_action", "maximize")
            if action == "hide":
                call minimize(v)
            elif action != "none":
                call set_maximized(v, not (v in maxed))
            end
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
# od shellu (Dock, spoustec, luxwm), pak i s prepnutim plochy (xfwm4 activate_action=switch).
# Okno ze sandboxu tedy aktivuje jen sandbox, ktery prave ma zamereni.
ACTIVATE_AFTER_INPUT_MS = 4000
# cas posledni zmeny zamereni (glib.monotonic_time, us)
focus_change = {"at": 0}

# Posledni stisk klavesy/tlacitka prisel do prave zamereneho okna (kratce, a az po posledni zmene zamereni):
# klik na odkaz v terminalu ano; Alt+Tab nebo klik do jineho okna zamereni meni az po stisku, takze ne
# (jinak by si fokus hned vzalo zpet okno, ktere ho prave ztratilo, napr. Firefox na cele obrazovce)
function input_for_focused():
    idle = lc.input_idle_ms()
    focused_for = (glib.monotonic_time() - focus_change["at"]) // 1000
    return idle < ACTIVATE_AFTER_INPUT_MS and focused_for > idle + 30
end

function activate(v, origin, source):
    current = focused()
    allowed = origin == lc.ORIGIN_SHELL or origin == lc.ORIGIN_TASKBAR
    if origin == lc.ORIGIN_VIEW and current != 0 and source != 0:
        allowed = source == current or same_app(source, current)
    elif origin == lc.ORIGIN_CLIENT:
        # bez tokenu jen okna aplikace, ktera ma zamereni (zadne kradeze)
        allowed = (current != 0 and on_current(v) and sandbox_id(current) == sandbox_id(v)
                   and lc.view_app_id(current) == lc.view_app_id(v))
    end
    # ... nebo kratce po stisku klavesy/tlacitka: terminal a jine programy token spustenemu programu nepredaji, takze
    # bezici prohlizec pozada s tokenem ze sveho okna (nebo bez nej) a odkaz z terminalu by ho jen tise oznacil
    # (X11: xfwm4 podle casu udalosti povoli). Okno ze sandboxu smi jen, kdyz ma zamereni jeho sandbox.
    if (not allowed and (origin == lc.ORIGIN_VIEW or origin == lc.ORIGIN_CLIENT) and current != 0 and v != current
            and input_for_focused()):
        allowed = sandbox_id(v) == "" or (current != 0 and sandbox_id(current) == sandbox_id(v))
    end
    if not allowed:
        # vzdy do luxwm.log: "klik v Docku / odkaz nic neudelal" je jinak bez stopy
        print "luxwm: activate refused " + String(v) + " origin " + String(origin) + " app " + lc.view_app_id(v)
        return
    end
    if cycle["on"]:
        call cycle_end(True)
    end
    space = vget(v, lc.VIEW_WORKSPACE)
    if space in ws and ws.index(space) != cur:
        call switch_to(ws.index(space), 0)
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
        if not title_double_click(v):
            call set_maximized(v, arg == 1)
        end
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
        has_xdg_deco[v] = True
        call lc.view_set_decorated(v, 1 if vget(v, lc.VIEW_SANDBOXED) == 1 else arg)
    elif what == lc.REQ_CLOSE:
        call lc.view_close(v)
    end
end

# Prvni snimek greeteru je na obrazovce: luxos-greetd-splash az ted ukonci Plymouth (plymouth quit
# --retain-splash). Driv by zmizel framebuffer splashe, ktery CRTC jeste zobrazuje (cerna obrazovka).
# ---- prechod po prihlaseni (--intro) -------------------------------------------------------------

# Pred lc.start(): True = snimek greeteru nacten (prvni commit ho uz nese, hold bez cerneho modesetu)
function intro_start():
    intro["on"] = True
    call lc.cover(INTRO_COLOR)
    framed = lc.cover_frame(LOGIN_FRAME, LOGIN_FRAME_MAX_AGE) == 1
    call lc.cover_stage(0)
    intro["timer"] = glib.timeout_add(INTRO_MAX_MS, intro_timeout)
    call log("intro" + (" with the greeter frame" if framed else ""))
    return framed
end

function intro_timeout():
    intro["timer"] = 0
    call intro_end("timeout")
    return False
end

function intro_settled():
    intro["timer"] = 0
    call intro_end("ready")
    return False
end

function intro_end(why):
    if not intro["on"]:
        return
    end
    intro["on"] = False
    if intro["timer"] != 0:
        call glib.source_remove(intro["timer"])
        intro["timer"] = 0
    end
    call lc.cover_fade(0 if motion_off() else tokens.MOTION["login_fade"])
    # volano z casovace glib: naplanovany snimek (idle zdroj smycky wayland) by jinak cekal na dalsi
    # udalost na soketu kompozitoru
    call lc.dispatch(0)
    call log("intro end (" + why + ")")
end

# Plocha je nakreslena, kdyz ma tapetu kazdy monitor a lista (vrstva s exkluzivni zonou) i Dock (dock_zone)
# prvni snimek; Dock nemusi byt (vypnuty), tak se na nej ceka jen chvili
function intro_check():
    if not intro["on"] or not intro["bar"] or len(outputs) == 0:
        return
    end
    for out in outputs:
        if out not in intro["backgrounds"]:
            return
        end
    end
    wait = INTRO_SETTLE_MS if len(dock_zones) > 0 else INTRO_DOCK_MS
    if intro["timer"] != 0:
        call glib.source_remove(intro["timer"])
    end
    intro["timer"] = glib.timeout_add(wait, intro_settled)
end

# Faze baru jako v X11: 1 spravce oken bezi, 2 tapeta, 3 lista, 4 hotovo (rozplynuti)
function intro_stage():
    backgrounds = len(outputs) > 0
    for out in outputs:
        if out not in intro["backgrounds"]:
            backgrounds = False
        end
    end
    call lc.cover_stage(1 + (1 if backgrounds else 0) + (1 if intro["bar"] else 0))
end

function intro_layer(out, layer, exclusive):
    if layer == 0 and out not in intro["backgrounds"]:
        intro["backgrounds"].append(out)
    elif exclusive:
        intro["bar"] = True
    else:
        return
    end
    call intro_stage()
    call intro_check()
end

function hold_end(by_client):
    call log("hold end" + ("" if by_client else " (timeout)"))
    dir = glib.getenv("XDG_RUNTIME_DIR")
    if greeter and dir != None and dir != "":
        safe:
            call writefile(dir + "/luxos-greeter-shown", "")
        end
    end
end

function handle(event, id, a, b, c):
    if event == lc.EV_VIEW_NEW:
        call sandbox_window(id)
    elif event == lc.EV_VIEW_MAP:
        call view_mapped(id)
        call material_mapped(id)
    elif event == lc.EV_VIEW_UNMAP:
        call view_gone(id)
    elif event == lc.EV_VIEW_SIZE:
        call view_resized(id)
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
    elif event == lc.EV_MOVE_EDGE:
        call move_wrap(id, a)
    elif event == lc.EV_SUPER_ALONE:
        call lc.spawn("luxos-launchpad")
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
        call rescue_windows()
        call broadcast("output", output_event())
    elif event == lc.EV_OUTPUT_ADD:
        outputs.append(id)
        call apply_gaming(id)
        call displays_changed()
        call broadcast("output", output_event())
    elif event == lc.EV_OUTPUT_REMOVE:
        if id in outputs:
            call outputs.remove(id)
        end
        call rescue_windows()
        call displays_changed()
        call broadcast("output", output_event())
    elif event == lc.EV_LAYOUT:
        call note("layout " + String(a))
        call broadcast("keyboard", keyboard_event())
    elif event == lc.EV_CAPS_LOCK:
        call broadcast("keyboard", keyboard_event())
    elif event == lc.EV_MODIFIERS:
        call broadcast("modifiers", modifiers_event())
    elif event == lc.EV_IPC_CONNECT:
        ipc[id] = {"privileged": b == 1, "topics": [], "pid": a}
        call note("ipc connect " + String(id) + " pid " + String(a) + (" privileged" if b == 1 else ""))
        return
    elif event == lc.EV_IPC_LINE:
        call ipc_line(id)
    elif event == lc.EV_IPC_CLOSE:
        call drop_client(id)
        return
    elif event == lc.EV_HOLD_END:
        call hold_end(a == 1)
        return
    elif event == lc.EV_LAYER_MAP:
        if intro["on"]:
            call intro_layer(id, a, b == 1)
        end
        return
    elif event == lc.EV_SLIDE_DONE:
        sliding["on"] = False
        if focused() == 0:
            call focus(top_on_current(0))
        else:
            call update_layers(focused())
        end
    end
    call update_idle_inhibit()
    call window_changed()
end

EVENT_NAMES = ["", "output-add", "output-remove", "output-usable", "view-new", "view-map", "view-unmap",
               "view-destroy", "view-title", "view-app-id", "view-request", "button", "keybind",
               "slide-done", "mods-released", "lock", "layout", "ipc-connect", "ipc-line", "ipc-close", "view-size",
               "hold-end", "layer-map", "view-content-type", "caps-lock", "super-alone", "modifiers"]

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
    return {"event": "keyboard", "current": lc.layout(), "layouts": keyboard["layouts"], "repeat": keyboard["repeat"],
            "caps": lc.caps_lock(), "mods": lc.modifiers()}
end

function modifiers_event():
    return {"event": "modifiers", "mods": lc.modifiers()}
end

function output_event():
    items = []
    main = primary_output()
    for out in outputs:
        items.append({"name": lc.output_name(out), "x": lc.output_get(out, lc.OUT_X), "y": lc.output_get(out, lc.OUT_Y),
                      "width": lc.output_get(out, lc.OUT_W), "height": lc.output_get(out, lc.OUT_H),
                      "scale": lc.output_get(out, lc.OUT_SCALE_PCT), "refresh_mhz": lc.output_get(out, lc.OUT_REFRESH_MHZ),
                      "usable": usable(out), "primary": out == main})
    end
    return {"event": "output", "outputs": items, "primary": lc.output_name(main) if main != 0 else ""}
end

function theme_event():
    return {"event": "theme", "theme": "dark" if look["dark"] else "light"}
end

# frame = ram okna se zahlavim v souradnicich rozlozeni (Dock uhyba, kdyz ho okno prekryva)
function window_event():
    v = focused()
    if v == 0:
        return {"event": "window", "id": 0, "app_id": "", "title": "", "frame": []}
    end
    return {"event": "window", "id": v, "app_id": lc.view_app_id(v), "title": lc.view_title(v), "frame": frame(v)}
end

function cycle_event(action):
    items = []
    if cycle["on"]:
        # capture = identifikator pro grim -T (nahled okna); minimalizovana okna nahled nemaji (ani na X11)
        for v in cycle["list"]:
            hidden = v in cycle["shown"] or vget(v, lc.VIEW_VISIBLE) == 0
            items.append({"id": v, "app_id": lc.view_app_id(v), "title": lc.view_title(v),
                          "capture": "" if hidden else lc.view_capture_id(v),
                          "w": vget(v, lc.VIEW_W), "h": vget(v, lc.VIEW_H)})
        end
    end
    return {"event": "cycle", "action": action, "items": items, "pos": cycle["pos"]}
end

function topic_event(topic):
    if topic == "window":
        return window_event()
    elif topic == "workspace":
        return workspace_event()
    elif topic == "keyboard":
        return keyboard_event()
    elif topic == "modifiers":
        return modifiers_event()
    elif topic == "output":
        return output_event()
    elif topic == "cycle":
        return cycle_event("state")
    elif topic == "media":
        return {"event": "media", "action": "state"}
    end
    return theme_event()
end

function send(client, message):
    if lc.ipc_send(client, json.encode(message)) == 0:
        call drop_client(client)
    end
end

function drop_client(client):
    if client in ipc:
        if "material" in ipc[client]:
            call apply_window_material(client, None)
        end
        suspended = ipc.pop(client).get("suspend", False)
        if suspended:
            call update_suspend()
        end
    end
    # Dock skoncil nebo spadl: jeho misto se uz nedrzi
    for name in List(dock_zones):
        if dock_zones[name][0] == client:
            call dock_zones.pop(name)
        end
    end
end

# Nastaveni zkratek chyta klavesy: do konce (nebo odpojeni klienta) zadne globalni zkratky
function update_suspend():
    want = False
    for client in ipc.keys():
        if ipc[client].get("suspend", False):
            want = True
        end
    end
    if want and len(binds) > 0:
        for id in binds.keys():
            call lc.unbind_key(id)
        end
        binds.clear()
        call note("shortcuts suspended")
    elif not want and len(binds) == 0:
        call bind_keys()
        call note("shortcuts resumed")
    end
end

function broadcast(topic, message):
    # udalosti vyvolane prikazem az po jeho odpovedi (klient ceka nejdriv odpoved)
    if deferred["on"]:
        deferred["items"].append([topic, message])
        return
    end
    line = ""
    for client in [k for k in ipc.keys()]:
        if topic in ipc[client]["topics"]:
            if line == "":
                line = json.encode(message)
            end
            if lc.ipc_send(client, line) == 0:
                call drop_client(client)
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
    now = [v, lc.view_app_id(v) if v != 0 else "", lc.view_title(v) if v != 0 else "", frame(v) if v != 0 else []]
    if now != last_window:
        last_window = now
        call broadcast("window", window_event())
    end
end

function window_info(v):
    space = vget(v, lc.VIEW_WORKSPACE)
    return {"id": v, "app_id": lc.view_app_id(v), "title": lc.view_title(v),
            "frame": frame(v) if on_current(v) and vget(v, lc.VIEW_VISIBLE) == 1 else [],
            "workspace": ws.index(space) + 1 if space in ws else 0, "focused": vget(v, lc.VIEW_FOCUSED) == 1,
            "minimized": vget(v, lc.VIEW_VISIBLE) == 0, "fullscreen": v in full, "maximized": v in maxed,
            "sandbox": lc.view_sandbox_app_id(v) if vget(v, lc.VIEW_SANDBOXED) == 1 else ""}
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

# ---- material okna (set_window_material) -------------------------------------------------------
# Sklo pod castmi okna (panel Nastaveni): klient pozada pro sva vlastni okna, jadro kresli rozmazane
# pozadi pod obdelnikem obsahu. Plati jen pro namapovana hlavni okna procesu klienta IPC se shodnym
# app_id, nikdy pro okna ze sandboxu; zije se spojenim (klient bez spojeni kresli panel nepruhledne).

function material_target(client, v):
    m = ipc[client]["material"]
    return (vget(v, lc.VIEW_MAPPED) == 1 and vget(v, lc.VIEW_PARENT) == 0 and vget(v, lc.VIEW_SANDBOXED) != 1
            and vget(v, lc.VIEW_PID) == ipc[client]["pid"] and lc.view_app_id(v) == m["app_id"])
end

# m = None zrusi material oken klienta; vraci pocet oken, kterych se tyka
function apply_window_material(client, m):
    if m != None:
        ipc[client]["material"] = m
    elif "material" not in ipc[client]:
        return 0
    end
    count = 0
    o = lc.view_next(0)
    while o != 0:
        if material_target(client, o):
            if m == None:
                call lc.view_set_material(o, "", 0, 0, 0, 0)
            else:
                call lc.view_set_material(o, m["material"], m["x"], m["y"], m["w"], m["h"])
            end
            count += 1
        end
        o = lc.view_next(o)
    end
    if m == None:
        call ipc[client].pop("material")
    end
    return count
end

# Okno se namapovalo az po pozadavku (klient posila pri kazde zmene velikosti panelu)
function material_mapped(v):
    for client in ipc.keys():
        if "material" in ipc[client] and material_target(client, v):
            m = ipc[client]["material"]
            call lc.view_set_material(v, m["material"], m["x"], m["y"], m["w"], m["h"])
        end
    end
end

function set_window_material(client, request):
    app = request.get("app_id", "")
    name = request.get("material", "")
    box = [request.get(k, 0) for k in ["x", "y", "w", "h"]]
    if type(app) != "String" or app == "" or type(name) != "String" or request.get("radius", 0) != 0:
        return {"ok": False, "error": "bad request"}
    end
    for n in box:
        if type(n) != "Int" or n < -100000 or n > 100000:
            return {"ok": False, "error": "bad request"}
        end
    end
    if name == "" or box[2] <= 0 or box[3] <= 0:
        call apply_window_material(client, None)
        return {"ok": True}
    end
    if (name not in tokens.SURFACE and name != "widget") or name == "dim":
        return {"ok": False, "error": "unknown material"}
    end
    if settings.get("blur", "yes") == "no":
        call apply_window_material(client, None)
        return {"ok": False, "error": "blur off"}
    end
    if "material" in ipc[client] and ipc[client]["material"]["app_id"] != app:
        call apply_window_material(client, None)
    end
    m = {"app_id": app, "material": name, "x": box[0], "y": box[1], "w": box[2], "h": box[3]}
    count = apply_window_material(client, m)
    call note("window material " + app + " " + name + " " + String(box) + " windows " + String(count))
    if count == 0:
        return {"ok": False, "error": "no such window"}
    end
    return {"ok": True}
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
            call switch_to(number - 1, 0)
        elif type(delta) == "Int":
            call switch_to(step_index(delta), delta)
        else:
            return {"ok": False, "error": "bad workspace"}
        end
        return {"ok": True}
    elif cmd == "get_night_light":
        return night_state()
    elif cmd == "set_night_light":
        return set_night_light(request)
    elif cmd == "set_brightness":
        value = request.get("value", None)
        if type(value) != "Int" or value < 10 or value > 100:
            return {"ok": False, "error": "bad brightness"}
        end
        night["brightness"] = value
        call apply_night()
        return {"ok": True}
    elif cmd == "get_input":
        return {"ok": True, "config": input_config, "devices": input_devices()}
    elif cmd == "reload":
        call on_reload()
        call update_suspend()
        return {"ok": True}
    elif cmd == "suspend_shortcuts":
        ipc[client]["suspend"] = request.get("on", False) == True
        call update_suspend()
        return {"ok": True}
    elif cmd == "set_theme":
        theme = request.get("theme", "")
        if theme != "light" and theme != "dark":
            return {"ok": False, "error": "bad theme"}
        end
        call apply_theme(theme == "dark")
        return {"ok": True}
    elif cmd == "set_cursor":
        # Nastaveni > Vzhled: plati do konce relace (i po reload); trvale je v xsettings, odkud ho pri
        # prihlaseni bere prostredi relace (XCURSOR_THEME, luxos-wayland-settings --env)
        theme = request.get("theme", "")
        size = request.get("size", 0)
        if type(theme) != "String" or theme == "" or theme.find("/") >= 0 or type(size) != "Int" or size < 8 or size > 256:
            return {"ok": False, "error": "bad cursor"}
        end
        session_cursor[0] = theme
        session_cursor[1] = String(size)
        call apply_cursor()
        return {"ok": True}
    elif cmd == "list_windows":
        return {"ok": True, "windows": list_windows()}
    elif cmd == "cycle_pick":
        # klik na okno v panelu Alt+Tab (luxos-switcher): vybrat ho a prepinani ukoncit, jako klik v tabwin
        # na X11; jen okno z prave probihajiciho vyberu, takze prikaz nepotrebuje opravneni
        v = request.get("window", 0)
        if not cycle["on"] or not (v in cycle["list"]):
            return {"ok": False, "error": "not cycling"}
        end
        cycle["pos"] = cycle["list"].index(v)
        call cycle_end(False)
        return {"ok": True}
    elif cmd == "focus_window":
        v = request.get("window", 0)
        if type(v) != "Int" or v <= 0 or vget(v, lc.VIEW_MAPPED) != 1:
            return {"ok": False, "error": "no such window"}
        end
        call activate(v, lc.ORIGIN_TASKBAR, 0)
        return {"ok": True}
    elif cmd == "set_primary":
        name = request.get("output", "")
        if type(name) != "String":
            return {"ok": False, "error": "bad request"}
        end
        displays["primary"] = name
        call rescue_windows()
        call broadcast("output", output_event())
        return {"ok": True, "primary": output_event()["primary"]}
    elif cmd == "dock_zone":
        name = request.get("output", "")
        height = request.get("height", 0)
        if type(name) != "String" or type(height) != "Int" or height < 0 or height > 1000:
            return {"ok": False, "error": "bad request"}
        end
        for key in List(dock_zones):
            if dock_zones[key][0] == client:
                call dock_zones.pop(key)
            end
        end
        if height > 0 and name != "":
            dock_zones[name] = [client, height]
        end
        call note("dock zone " + name + " " + String(height))
        call intro_check()
        return {"ok": True}
    elif cmd == "sandbox_window":
        # luxos-sandbox (bezi mimo sandbox, aplikace sama na soket nedosahne): velikost a nazev hlavniho
        # okna X11 aplikace; plati jen pro korenove okno Xwayland teto instance sandboxu
        instance = request.get("instance", "")
        w = request.get("width", 0)
        h = request.get("height", 0)
        title = request.get("title", "")
        if type(instance) != "String" or instance == "" or type(w) != "Int" or type(h) != "Int" or type(title) != "String":
            return {"ok": False, "error": "bad request"}
        end
        title = clean_title(title)
        found = False
        for v in List(xroots):
            if xroots[v] == instance and vget(v, lc.VIEW_MAPPED) == 1:
                call size_xroot(v, w, h, title)
                found = True
            end
        end
        if not found:
            if len(xroot_pending) > 32:
                xroot_pending.clear()
            end
            xroot_pending[instance] = [w, h, title]
        end
        return {"ok": True}
    elif cmd == "set_window_material":
        return set_window_material(client, request)
    elif cmd == "test_output":
        # testy: pripojeni/odpojeni monitoru, funguje jen na headless backendu
        size = request.get("add", "")
        name = request.get("remove", "")
        if type(size) == "String" and size != "":
            parts = size.split("x")
            out = 0
            safe:
                out = lc.test_output_add(Int(parts[0]), Int(parts[1]))
            end
            if out == 0:
                return {"ok": False, "error": "no headless backend"}
            end
            return {"ok": True, "output": lc.output_name(out)}
        end
        for out in outputs:
            if lc.output_name(out) == name:
                call lc.test_output_remove(out)
                return {"ok": True}
            end
        end
        return {"ok": False, "error": "no such output"}
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
    deferred["on"] = True
    reply = {"ok": False, "error": "failed"}
    try:
        reply = ipc_command(client, request)
    else:
        call log("ipc error: " + String(last_error()))
    end
    deferred["on"] = False
    if "id" in request:
        reply["id"] = request["id"]
    end
    call send(client, reply)
    items = deferred["items"]
    deferred["items"] = []
    for item in items:
        call broadcast(item[0], item[1])
    end
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
        + " pointer=" + String(lc.pointer_constraint()) + " idle_inhibit=" + String(1 if idle_held else 0)
        + " xwayland=" + String(lc.xwayland_running()) + " layout=" + String(lc.layout()) + "/" + String(lc.layout_count())
        + " ipc=" + String(len(ipc)) + " theme=" + ("dark" if look["dark"] else "light"))
    for out in outputs:
        u = usable(out)
        call log("output " + String(out) + " " + lc.output_name(out) + " " + String(lc.output_get(out, lc.OUT_W)) + "x"
            + String(lc.output_get(out, lc.OUT_H)) + " usable=" + String(u[0]) + "," + String(u[1]) + "," + String(u[2]) + "x" + String(u[3])
            + " fullscreen=" + String(lc.output_get(out, lc.OUT_FULLSCREEN)) + " scanout=" + String(lc.output_get(out, lc.OUT_SCANOUT))
            + " torn=" + String(lc.output_get(out, lc.OUT_TORN)) + " vrr=" + String(lc.output_get(out, lc.OUT_VRR))
            + " vrr_active=" + String(lc.output_get(out, lc.OUT_VRR_ACTIVE)) + " tearing=" + String(lc.output_get(out, lc.OUT_TEARING)))
    end
    o = lc.view_next(0)
    while o != 0:
        call log("view " + String(o) + " app=" + lc.view_app_id(o) + " title=" + lc.view_title(o).replace(" ", "_")
            + " ws=" + String(ws.index(vget(o, lc.VIEW_WORKSPACE)) + 1 if vget(o, lc.VIEW_WORKSPACE) in ws else 0)
            + " x=" + String(vget(o, lc.VIEW_X)) + " y=" + String(vget(o, lc.VIEW_Y)) + " w=" + String(vget(o, lc.VIEW_W))
            + " h=" + String(vget(o, lc.VIEW_H)) + " top=" + String(vget(o, lc.VIEW_DECO_TOP))
            + " focused=" + String(vget(o, lc.VIEW_FOCUSED)) + " visible=" + String(vget(o, lc.VIEW_VISIBLE))
            + " fullscreen=" + String(vget(o, lc.VIEW_FULLSCREEN)) + " maximized=" + String(1 if o in maxed else 0)
            + " layer=" + String(vget(o, lc.VIEW_LAYER)) + " x11=" + String(vget(o, lc.VIEW_X11))
            + " content=" + String(vget(o, lc.VIEW_CONTENT_TYPE)) + " tearing=" + String(vget(o, lc.VIEW_TEARING))
            + " sandbox=" + (lc.view_sandbox_app_id(o) if vget(o, lc.VIEW_SANDBOXED) == 1 else "-"))
        o = lc.view_next(o)
    end
    call log("mru " + " ".join([String(v) for v in mru]))
    call log("end")
end

# ---- beh ---------------------------------------------------------------------------------------

function stop():
    # V relaci LuxOS nejdriv ukoncit shell (lista, Dock, zamek...) signalem, dokud kompozitor bezi: jinak pri
    # odhlaseni a vypnuti spadnou na ztrate displeje a systemd je hlasi jako selhane
    if glib.getenv("XDG_SESSION_DESKTOP") == "luxos" and not session_stopped["done"]:
        session_stopped["done"] = True
        # Aplikace spustene v relaci (Spoustec, Dock, terminal: jednotky v app.slice bez vazby na relaci) skonci
        # s odhlasenim jako na X11: jinak hraje hudba z Firefoxu dal a pristi spusteni Firefoxu jen posle "otevri
        # okno" jeho kopii bez displeje. 5 s na slusne ukonceni (Firefox ulozi relaci), co zbyde, natvrdo.
        call log("stopping session apps")
        apps = "'app-luxos-*.scope' 'luxos-terminal-tab-*.scope' luxos-terminal2.service"
        call lglib.spawn_sync_quiet(["sh", "-c", "timeout 5 systemctl --user stop " + apps + "; " +
                                     "systemctl --user kill --signal=SIGKILL " + apps + " 2>/dev/null"])
        call log("stopping the session shell")
        call lglib.spawn_sync_quiet(["timeout", "3", "systemctl", "--user", "stop", "luxos-session.target",
                                        "graphical-session.target"])
    end
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
    call apply_workspaces()
    call apply_cursor()
    call apply_input()
    for out in outputs:
        call apply_gaming(out)
    end
    call read_locale()
    call apply_keyboard()
    call apply_repeat()
    call apply_theme(dark_mode())
    call read_brightness()
    call apply_night()
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

# Prihlasovaci obrazovka skoncila (greetd ji ukoncuje po start_session): kompozitor konci s jejim kodem
greeter_status = 0

function on_greeter_exit(pid, status):
    global greeter_status
    greeter_status = status
    call log("greeter exited with status " + String(status))
    if status == 0:
        call handoff()
    end
    call stop()
    return 0
end

# Prihlaseni (greeter ulozil posledni snimek): obraz zustane na obrazovce, dokud ho neprevezme relace. Konec
# luxwm vraci VT do textoveho rezimu (logind) a ten by vynutil textovou konzoli - na jinem nez zobrazenem VT
# se nic nestane. Pri prepnuti na prazdny VT v grafickem rezimu jadro vrati na displej framebuffer konzole a nic
# do nej nekresli; snimek greeteru do nej da greetd (libluxos-greetd-vt.so), jakmile VT prevezme.
function handoff():
    st = lglib.stat(LOGIN_FRAME)
    if len(st) < 2 or lglib.now() - st[1] // 1000000000 > HANDOFF_MAX_AGE:
        return
    end
    if lc.switch_vt(HANDOFF_VT) != 1:
        return
    end
    deadline = glib.monotonic_time() + 1000000
    while lc.session_active() == 1 and glib.monotonic_time() < deadline:
        call lc.dispatch(50)
    end
    call log("handoff to VT " + String(HANDOFF_VT) + ("" if lc.session_active() == 0 else " (still active)"))
end

commands = []
intro_wanted = False
for i in range(1, len(args)):
    if args[i] == "-d":
        trace = True
    elif args[i] == "--greeter":
        greeter = True
    elif args[i] == "--hold":
        hold = True
    elif args[i] == "--intro":
        intro_wanted = True
    else:
        commands.append(args[i])
    end
end
if glib.getenv("LUXWM_TRACE") == "1":
    trace = True
end
if glib.getenv("LUXOS_LOGIN_FRAME") != None and glib.getenv("LUXOS_LOGIN_FRAME") != "":
    LOGIN_FRAME = glib.getenv("LUXOS_LOGIN_FRAME")
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
call apply_cursor()
call apply_input()
call read_locale()
call apply_keyboard()
call apply_repeat()
call apply_theme(dark_mode())
call apply_motion()
call read_brightness()
call apply_night()
sock = ipc_path()
if sock != "" and lc.ipc_listen(sock) == 0:
    call lc.setenv("LUXWM_SOCK", sock)
else:
    call log("no IPC socket" + (" at " + sock if sock != "" else " (no XDG_RUNTIME_DIR)"))
    sock = ""
end
if hold:
    call lc.hold(HOLD_MS)
end
if intro_wanted and not greeter and intro_start():
    call lc.hold(HOLD_MS)
end
if lc.start() != 0:
    call log("cannot start the backend")
    call lc.destroy()
    exit(1)
end
if intro["on"]:
    call lc.cover_stage(1)
end
call log("running on " + lc.socket() + (" (software rendering)" if lc.software_rendering() == 1 else "")
    + ", " + String(ws_count) + " workspaces, " + String(len(binds)) + " shortcuts"
    + (", ipc " + sock if sock != "" else "")
    + (", xwayland " + xdisplay if xdisplay != "" else ""))
call glib.fd_add(lc.fd(), glib.IO_IN, on_luxcomp)
if not greeter:
    call hot_reload()
    call glib.timeout_add(100, hot_tick)
end
call glib.unix_signal_add(15, on_term)
call glib.unix_signal_add(2, on_term)
call glib.unix_signal_add(1, on_reload)
call glib.unix_signal_add(10, on_theme)
call glib.unix_signal_add(12, on_dump)
if greeter:
    if len(commands) != 1 or glib.spawn_watched(["/bin/sh", "-c", commands[0]], on_greeter_exit) <= 0:
        call log("--greeter needs one command that can start")
        call lc.destroy()
        exit(1)
    end
else:
    for startup in commands:
        call lc.spawn(startup)
    end
end
# prvni pruchod: klienti cekajici na socket a nastartovany backend
call lc.dispatch(0)
call glib.main()
call lc.destroy()
call log("stopped")
if greeter and greeter_status != 0:
    exit(1)
end
