# LuxOS - klavesove zkratky na X11: cteni a zapis zkratek Xfce v xfconf (kanal xfce4-keyboard-shortcuts),
# drive files/python/luxos_shortcuts.py. Pouziva okno Klavesove zkratky (luxos-keyboard-settings --shortcuts).
#
# Zkratky jsou v xfconf jako vlastnost "zkratka -> prikaz":
#   /commands/custom/<Super>e = thunar             (spousti xfsettingsd)
#   /xfwm4/custom/<Super>q    = close_window_key   (akce spravce oken xfwm4)
# Vychozi hodnoty jsou v systemovem souboru kanalu (XDG_CONFIG_DIRS, u LuxOS /etc/xdg/luxos). Reset vlastnosti
# (xfconf-query -r) vrati systemovou hodnotu, systemovou zkratku proto nelze smazat - vypina se prazdnym
# prikazem (knihovna zkratek Xfce prazdne prikazy preskakuje).
#
# Nazvy vlastnich zkratek (xfconf zna jen prikaz) jsou v ~/.config/luxos/shortcuts.json.
# LUXOS_XFCONF_QUERY prepise prikaz xfconf-query (testy s falesnym prikazem), LUXOS_SHORTCUTS_DEFAULTS soubor
# s vychozimi zkratkami a LUXOS_XKB_CONF nastaveni klavesnice X. Samotna klavesa Super otevira Launchpad
# (luxos-menubar), dokud neexistuje priznak ~/.config/luxos/super-launchpad-off.
#
# Akce = {"id", "section", "label", "kind" ("cmd"/"wm"), "values" (prvni se zapisuje, ostatni jsou aliasy),
# "custom"}. Model (new_model) drzi aktualni hodnoty z xfconf, vychozi z XML a nazvy vlastnich zkratek.
load env, json, process
load luxos_glib, glib as glib
load luxos_glib as lglib
load luxos_text as text
load luxos_xfconf as xfconf
load luxos_i18n as i18n

CHANNEL = "xfce4-keyboard-shortcuts"
KINDS = ["cmd", "wm"]
BASES = {"cmd": "/commands/custom", "wm": "/xfwm4/custom"}
CHANNEL_FILE = "/xfce4/xfconf/xfce-perchannel-xml/" + CHANNEL + ".xml"
# Poradi modifikatoru v ulozenem nazvu (jako gtk_accelerator_name) a v zobrazeni (styl LuxOS)
MOD_ORDER = ["ctrl", "shift", "alt", "super"]
MOD_NAMES = {"ctrl": "<Primary>", "shift": "<Shift>", "alt": "<Alt>", "super": "<Super>"}
MOD_DISPLAY = [["ctrl", "Ctrl"], ["super", "Super"], ["alt", "Alt"], ["shift", "Shift"]]
MOD_ALIASES = {"primary": "ctrl", "control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl", "shift": "shift", "shft": "shift",
               "alt": "alt", "mod1": "alt", "super": "super", "mod4": "super", "meta": "meta", "hyper": "hyper",
               "release": "release"}
# Modifikatory, ktere LuxOS v nazvu nepouziva (Meta/Hyper) - zkratky s nimi se zobrazi, ale needituji
EXTRA_MODS = [["release", "<Release>"], ["meta", "<Meta>"], ["hyper", "<Hyper>"]]
KEY_DISPLAY = {
    "space": "Space", "Escape": "Esc", "Return": "Return", "KP_Enter": "Enter", "Tab": "Tab",
    "BackSpace": "Backspace", "Delete": "Delete", "Insert": "Insert", "Home": "Home", "End": "End",
    "Page_Up": "Page Up", "Page_Down": "Page Down", "Prior": "Page Up", "Next": "Page Down",
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→", "Print": "Print Screen", "Pause": "Pause",
    "Scroll_Lock": "Scroll Lock", "Menu": "Menu", "comma": ",", "period": ".", "slash": "/",
    "backslash": "\\", "semicolon": ";", "apostrophe": "'", "grave": "`", "minus": "-", "equal": "=",
    "plus": "+", "bracketleft": "[", "bracketright": "]", "less": "<", "greater": ">",
    "XF86PowerOff": "Power", "XF86Calculator": "Calculator", "XF86Display": "Display",
    "XF86LaunchA": "Launch A", "XF86LaunchB": "Launch B", "XF86AudioMute": "Mute",
    "XF86AudioRaiseVolume": "Volume Up", "XF86AudioLowerVolume": "Volume Down",
    "XF86MonBrightnessUp": "Brightness Up", "XF86MonBrightnessDown": "Brightness Down",
    "XF86WWW": "Web", "XF86HomePage": "Home Page", "XF86Mail": "Mail", "XF86Explorer": "Explorer"}
MODIFIER_PREFIXES = ["Shift", "Control", "Alt", "Super", "Meta", "Hyper", "ISO_Group", "Caps", "Num_Lock", "Mode_switch"]
SECTIONS = [["windows", "Windows"], ["apps", "Apps & System"], ["screenshots", "Screenshots"],
            ["custom", "Custom Shortcuts"], ["other", "Other Xfce Shortcuts"]]
XKB_TOGGLES = {
    "alt_shift_toggle": "Alt + Shift", "ctrl_shift_toggle": "Ctrl + Shift", "alt_space_toggle": "Alt + Space",
    "win_space_toggle": "Super + Space", "ctrl_alt_toggle": "Ctrl + Alt", "caps_toggle": "Caps Lock",
    "shift_caps_toggle": "Shift + Caps Lock", "alt_caps_toggle": "Alt + Caps Lock",
    "lwin_toggle": "Left Super", "rwin_toggle": "Right Super", "menu_toggle": "Menu",
    "shifts_toggle": "Left Shift + Right Shift", "alt_altgr_toggle": "Alt + AltGr"}
GROUP_APPS_PROP = "/general/cycle_group_apps"
LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
WORD = LOWER + UPPER + DIGITS + "_"

function is_letter(c):
    return c.lower() != c.upper()
end

# ---- nazvy zkratek -------------------------------------------------------------------------------------

# "<Super><Shift>4" -> [["super", "shift"], "4"]; neplatny nazev -> None
function parse_accel(value):
    if type(value) != "String" or value == "":
        return None
    end
    mods = []
    rest = value.strip()
    while rest.startswith("<"):
        stop = rest.find(">")
        if stop < 0:
            return None
        end
        name = rest[1:stop].strip().lower()
        if not (name in MOD_ALIASES):
            return None
        end
        if not (MOD_ALIASES[name] in mods):
            mods.append(MOD_ALIASES[name])
        end
        rest = rest[stop + 1:]
    end
    key = rest.strip()
    if key == "" or key.find("<") >= 0 or key.find(">") >= 0 or key.find(" ") >= 0:
        return None
    end
    if len(key) == 1 and is_letter(key):
        key = key.lower()            # GTK uklada pismena male: <Super>e
    end
    return [mods, key]
end

# Kanonicky nazev zkratky ve stylu GTK (modifikatory v pevnem poradi)
function make_accel(mods, key):
    if len(key) == 1 and is_letter(key):
        key = key.lower()
    end
    out = ""
    for m in MOD_ORDER:
        if m in mods:
            out += MOD_NAMES[m]
        end
    end
    for pair in EXTRA_MODS:
        if pair[0] in mods:
            out += pair[1]
        end
    end
    return out + key
end

# Kanonicky tvar pro porovnani: "<Shift><Super>Down" == "<Super><Shift>Down"; neplatny -> ""
function normalize(value):
    p = parse_accel(value)
    if p == None:
        return ""
    end
    return make_accel(p[0], p[1])
end

# XF86AudioPlay -> Audio Play (mezera mezi malym pismenem a velkym pismenem/cislici)
function split_words(name, digits):
    out = ""
    for i in range(len(name)):
        c = name[i]
        if i > 0 and LOWER.find(name[i - 1]) >= 0 and (UPPER.find(c) >= 0 or (digits and DIGITS.find(c) >= 0)):
            out += " "
        end
        out += c
    end
    return out
end

function key_label(key):
    if key in KEY_DISPLAY:
        return KEY_DISPLAY[key]
    end
    if len(key) == 1:
        return key.upper()
    end
    if key.startswith("KP_"):
        return "Num " + key_label(key[3:])
    end
    if key.startswith("XF86"):
        return split_words(key[4:], True)
    end
    return key.replace("_", " ")
end

# "<Super><Shift>4" -> "Super + Shift + 4" (bez symbolu macOS, LuxOS rika Super)
function format_accel(value):
    p = parse_accel(value)
    if p == None:
        if type(value) == "String":
            return value
        end
        return ""
    end
    parts = [pair[1] for pair in MOD_DISPLAY if pair[0] in p[0]]
    for m in ["meta", "hyper"]:
        if m in p[0]:
            parts.append(m.capitalize())
        end
    end
    parts.append(key_label(p[1]))
    return " + ".join(parts)
end

function is_modifier_key(key):
    for prefix in MODIFIER_PREFIXES:
        if key.startswith(prefix):
            return True
        end
    end
    # ISO_Level3_Shift, ISO_Level5_Lock ...
    return key.startswith("ISO_Level") and len(key) > 9 and DIGITS.find(key[9]) >= 0
end

# Samotne klavesy bez modifikatoru povolene jako zkratka (pismena by prekazela psani)
function solo_key(key):
    if key.startswith("F") and len(key) >= 2 and len(key) <= 3 and text.is_digits(key[1:]):
        n = Int(key[1:])
        return key[1] != "0" and n >= 1 and n <= 39
    end
    if key.startswith("XF86") and len(key) > 4 and only_chars(key[4:], WORD):
        return True
    end
    return key in ["Print", "Pause", "Scroll_Lock", "Menu"]
end

function only_chars(value, allowed):
    for c in value:
        if allowed.find(c) < 0:
            return False
        end
    end
    return True
end

# Pouzitelna globalni zkratka: s Ctrl/Alt/Super, nebo samotna funkcni/multimedialni klavesa
function accel_allowed(value):
    p = parse_accel(value)
    if p == None:
        return False
    end
    if is_modifier_key(p[1]):
        return False
    end
    if "ctrl" in p[0] or "alt" in p[0] or "super" in p[0]:
        return True
    end
    return solo_key(p[1])
end

# ---- xfconf ------------------------------------------------------------------------------------------------

function xfconf_cmd():
    value = env.get("LUXOS_XFCONF_QUERY", "")
    if value != "":
        return value
    end
    return "xfconf-query"
end

# xfconf-query pro kanal; [uspech, stdout]
function query(channel, argv):
    program = glib.find_program_in_path(xfconf_cmd())
    if program == "":
        return [False, ""]
    end
    result = None
    safe:
        result = process.capture_result(program, ["-c", channel] + argv)
    end
    if result == None:
        return [False, ""]
    end
    return [result["ok"], result["stdout"]]
end

function xfconf_call(argv):
    return query(CHANNEL, argv)
end

# Vystup "xfconf-query -l -v" -> {"cmd": {zkratka: prikaz}, "wm": {zkratka: akce}}; podvlastnosti
# (.../<Super>e/startup-notify) a "override" se preskoci
function parse_listing(listing):
    out = {"cmd": {}, "wm": {}}
    for raw in listing.split("\n"):
        line = raw.replace("\t", " ")
        if line.strip() == "":
            continue
        end
        line = line.lstrip()
        cut = line.find(" ")
        prop = line
        value = ""
        if cut >= 0:
            prop = line[:cut]
            value = line[cut + 1:].strip()
        end
        for kind in KINDS:
            base = BASES[kind]
            if prop.startswith(base + "/"):
                rest = prop[len(base) + 1:]
                if rest.find("/") < 0 and rest != "override":
                    out[kind][rest] = value
                end
                break
            end
        end
    end
    return out
end

# Aktualni (efektivni) zkratky z xfconf; None, kdyz xfconf neni dostupny
function read_current():
    r = xfconf_call(["-l", "-v"])
    if not r[0]:
        return None
    end
    return parse_listing(r[1])
end

function defaults_path():
    value = env.get("LUXOS_SHORTCUTS_DEFAULTS", "")
    if value != "":
        return value
    end
    # xfconf pouzije prvni nalezeny soubor kanalu (vyssi priorita nahradi cely kanal)
    dirs = env.get("XDG_CONFIG_DIRS", "")
    if dirs == "":
        dirs = "/etc/xdg"
    end
    for d in dirs.split(":"):
        if d != "" and exists(d + CHANNEL_FILE):
            return d + CHANNEL_FILE
        end
    end
    return ""
end

# Vychozi zkratky ze systemoveho XML kanalu (stejna struktura jako parse_listing)
function read_defaults(path):
    out = {"cmd": {}, "wm": {}}
    if path == "":
        path = defaults_path()
    end
    if path == "" or not exists(path):
        return out
    end
    root = xfconf.xml_tree(lglib.read_text(path))
    for kind in KINDS:
        node = root
        for name in BASES[kind][1:].split("/"):
            found = None
            if node != None:
                for c in node["children"]:
                    if found == None and c["name"] == name:
                        found = c
                    end
                end
            end
            node = found
        end
        if node == None:
            continue
        end
        for p in node["children"]:
            if p["type"] == "string" and p["name"] != "override":
                out[kind][p["name"]] = p["value"]
            end
        end
    end
    return out
end

# ---- nazvy vlastnich zkratek ----------------------------------------------------------------------------------

function config_home():
    value = env.get("XDG_CONFIG_HOME", "")
    if value != "":
        return value
    end
    return env.get("HOME", "") + "/.config"
end

function store_path():
    return config_home() + "/luxos/shortcuts.json"
end

# {"<Super>k": {"name": "Moje skripty", "command": "..."}}; poskozeny soubor -> {}
function load_names(path):
    if path == "":
        path = store_path()
    end
    data = None
    safe:
        data = json.decode(lglib.read_text(path))
    end
    if type(data) != "Dictionary":
        return {}
    end
    custom = data.get("custom", None)
    if type(custom) != "Dictionary":
        return {}
    end
    out = {}
    for accel in custom.keys():
        item = custom[accel]
        norm = normalize(accel)
        if norm != "" and type(item) == "Dictionary" and type(item.get("name", None)) == "String" and type(item.get("command", None)) == "String":
            out[norm] = {"name": item["name"], "command": item["command"]}
        end
    end
    return out
end

function save_names(names, path):
    if path == "":
        path = store_path()
    end
    call lglib.mkdir_p(path[:text.rfind(path, "/")])
    keys = sorted(names.keys())
    sorted_names = {}
    for k in keys:
        sorted_names[k] = {"command": names[k]["command"], "name": names[k]["name"]}
    end
    return lglib.write_atomic(path, json.encode({"custom": sorted_names, "version": 1}))
end

# ---- akce ------------------------------------------------------------------------------------------------------

function action(aid, section, label, kind, values, custom):
    return {"id": aid, "section": section, "label": label, "kind": kind, "values": values, "custom": custom}
end

function workspace_label(n):
    return i18n.TF("Go to workspace %d", [n])
end

# Zname akce LuxOS s citelnymi nazvy (prelozene texty z puvodniho prehledu)
function catalog():
    T = i18n.T
    w = "windows"
    a = "apps"
    s = "screenshots"
    return [
        action("close", w, T("Close window"), "wm", ["close_window_key"], False),
        action("hide", w, T("Minimize window"), "wm", ["hide_window_key"], False),
        action("cycle", w, T("Switch windows"), "wm", ["cycle_windows_key"], False),
        action("cycle-reverse", w, T("Switch windows backwards"), "wm", ["cycle_reverse_windows_key"], False),
        action("cycle-app", w, T("Switch windows of the current app"), "wm", ["cycle_app_windows_key"], False),
        action("cycle-app-reverse", w, T("Switch windows of the current app backwards"), "wm", ["cycle_reverse_app_windows_key"], False),
        action("switch-app", w, T("Next window of the same app (without previews)"), "wm", ["switch_window_key"], False),
        action("maximize", w, T("Maximize window"), "wm", ["maximize_window_key"], False),
        action("tile-left", w, T("Tile window left"), "wm", ["tile_left_key"], False),
        action("tile-right", w, T("Tile window right"), "wm", ["tile_right_key"], False),
        action("fullscreen", w, T("Full screen"), "wm", ["fullscreen_key"], False),
        action("desktop", w, T("Show desktop"), "wm", ["show_desktop_key"], False),
        action("ws-left", w, T("Previous workspace"), "wm", ["left_workspace_key"], False),
        action("ws-right", w, T("Next workspace"), "wm", ["right_workspace_key"], False),
        action("ws-1", w, workspace_label(1), "wm", ["workspace_1_key"], False),
        action("ws-2", w, workspace_label(2), "wm", ["workspace_2_key"], False),
        action("search", a, T("Search"), "cmd", ["luxos-search", "luxos-spotlight"], False),
        action("launchpad", a, "Launchpad", "cmd", ["luxos-launchpad"], False),
        action("files", a, T("Files"), "cmd", ["thunar", "exo-open --launch FileManager"], False),
        action("terminal", a, T("Terminal"), "cmd", ["luxos-terminal", "xfce4-terminal", "exo-open --launch TerminalEmulator"], False),
        action("settings", a, T("Settings"), "cmd", ["xfce4-settings-manager"], False),
        action("lock", a, T("Lock screen"), "cmd", ["xflock4"], False),
        action("monitor", a, T("System monitor (force quit)"), "cmd", ["luxos-monitor", "xfce4-taskmanager"], False),
        action("displays", a, T("Displays"), "cmd", ["luxos-displays menu"], False),
        action("calculator", a, T("Calculator"), "cmd", ["luxos-calculator"], False),
        action("emoji", a, T("Emoji & Symbols"), "cmd", ["luxos-emoji"], False),
        action("logout", a, T("Log out or shut down"), "cmd", ["xfce4-session-logout"], False),
        action("shot-screen", s, T("Screenshot"), "cmd", ["luxos-screenshot --screen"], False),
        action("shot-region", s, T("Screenshot of region"), "cmd", ["luxos-screenshot --portion"], False),
        action("shot-tool", s, T("Screenshot tool"), "cmd", ["luxos-screenshot"], False)]
end

# Citelny nazev akce xfwm4 mimo katalog (pro hlasku o kolizi)
function wm_action_label(value):
    for a in catalog():
        if a["kind"] == "wm" and value in a["values"]:
            return a["label"]
        end
    end
    if value.startswith("workspace_") and value.endswith("_key") and text.is_digits(value[10:len(value) - 4]) and len(value) > 14:
        return workspace_label(Int(value[10:len(value) - 4]))
    end
    return value.replace("_key", "").replace("_", " ").capitalize()
end

# ---- argumenty prikazu (jako shlex) ---------------------------------------------------------------------------

# Rozdeleni prikazu jako v shellu; None = neukoncene uvozovky
function shell_split(line):
    out = []
    word = ""
    have = False
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote == "'":
            if c == "'":
                quote = ""
            else:
                word += c
            end
        elif quote == "\"":
            if c == "\"":
                quote = ""
            elif c == "\\" and i + 1 < len(line) and "\\\"$`\n".find(line[i + 1]) >= 0:
                i += 1
                word += line[i]
            else:
                word += c
            end
        elif c == "'" or c == "\"":
            quote = c
            have = True
        elif c == "\\":
            if i + 1 >= len(line):
                return None
            end
            i += 1
            word += line[i]
            have = True
        elif c == " " or c == "\t" or c == "\n":
            if have or word != "":
                out.append(word)
            end
            word = ""
            have = False
        else:
            word += c
        end
        i += 1
    end
    if quote != "":
        return None
    end
    if have or word != "":
        out.append(word)
    end
    return out
end

function plain_split(line):
    return [w for w in line.replace("\t", " ").replace("\n", " ").split(" ") if w != ""]
end

function shell_quote(arg):
    if arg == "":
        return "''"
    end
    if only_chars(arg, WORD + "@%+=:,./-"):
        return arg
    end
    return "'" + arg.replace("'", "'\"'\"'") + "'"
end

function basename(path):
    cut = text.rfind(path, "/")
    if cut < 0:
        return path
    end
    return path[cut + 1:]
end

# Kratky nazev prikazu pro seznam: "exo-open --launch WebBrowser" -> "Web Browser",
# "/usr/bin/xfce4-appfinder --collapsed" -> "xfce4-appfinder"
function short_label(command):
    argv = shell_split(command)
    if argv == None:
        argv = plain_split(command)
    end
    if len(argv) == 0:
        return command
    end
    head = argv[:len(argv) - 1]
    if basename(argv[0]) == "exo-open" and "--launch" in head:
        return split_words(argv[head.index("--launch") + 1], False)
    end
    return basename(argv[0])
end

function is_field_code(arg):
    return len(arg) == 2 and arg[0] == "%" and "fFuUdDnNickvm".find(arg[1]) >= 0
end

# Exec z .desktop bez %f/%U/... (pro spusteni zkratkou bez souboru)
function strip_field_codes(exec_line):
    argv = shell_split(exec_line)
    if argv == None:
        argv = plain_split(exec_line)
    end
    out = []
    for a in argv:
        if is_field_code(a):
            continue
        end
        clean = ""
        i = 0
        while i < len(a):
            if a[i] == "%" and i + 1 < len(a) and is_field_code(a[i:i + 2]):
                i += 2
                continue
            end
            clean += a[i]
            i += 1
        end
        clean = clean.replace("%%", "%")
        if clean != "":
            out.append(clean)
        end
    end
    return " ".join([shell_quote(a) for a in out])
end

# ---- model ---------------------------------------------------------------------------------------------------

function new_model(defaults, names_path):
    if defaults == None:
        defaults = read_defaults("")
    end
    m = {"defaults": defaults, "names_path": names_path}
    call reload(m)
    return m
end

function copy_kinds(src):
    out = {}
    for kind in KINDS:
        out[kind] = src[kind].copy()
    end
    return out
end

function reload(m):
    cur = read_current()
    m["available"] = cur != None
    m["current"] = cur if cur != None else copy_kinds(m["defaults"])
    m["names"] = load_names(m["names_path"])
    m["catalog"] = catalog()
    # norm -> [nazev vlastnosti, hodnota]; jen zapnute (neprazdne) zkratky
    active = {"cmd": {}, "wm": {}}
    raw = {"cmd": {}, "wm": {}}
    default_norm = {"cmd": {}, "wm": {}}
    for kind in KINDS:
        for src in [m["defaults"][kind], m["current"][kind]]:
            for name in src.keys():
                norm = normalize(name)
                if norm != "" and not (norm in raw[kind]):
                    raw[kind][norm] = name
                end
            end
        end
        cur_kind = m["current"][kind]
        for name in cur_kind.keys():
            norm = normalize(name)
            if norm != "" and cur_kind[name] != "":
                active[kind][norm] = [name, cur_kind[name]]
            end
        end
        defs = m["defaults"][kind]
        for name in defs.keys():
            norm = normalize(name)
            if norm != "":
                default_norm[kind][norm] = defs[name]
            end
        end
    end
    m["active"] = active
    m["raw"] = raw
    m["default_norm"] = default_norm
    return m
end

# Zkratka patri pojmenovane vlastni polozce (ne radku katalogu se stejnym prikazem)
function is_named(m, kind, norm):
    item = m["names"].get(norm, None)
    return kind == "cmd" and item != None and norm in m["active"]["cmd"] and m["active"]["cmd"][norm][1] == item["command"]
end

function default_accels(m, act):
    defs = m["default_norm"][act["kind"]]
    return [n for n in defs.keys() if defs[n] in act["values"]]
end

# Zkratky akce v poradi: zkratky zvolene uzivatelem, pak vychozi (poradi z XML)
function accels_for(m, act):
    active = m["active"][act["kind"]]
    found = [n for n in active.keys() if active[n][1] in act["values"] and (act["custom"] or not is_named(m, act["kind"], n))]
    order = default_accels(m, act)
    out = sorted([n for n in found if not (n in order)])
    for n in order:
        if n in found:
            out.append(n)
        end
    end
    return out
end

function is_default(m, act):
    if act["custom"]:
        return True
    end
    return sorted(accels_for(m, act)) == sorted(default_accels(m, act))
end

function known_values(m, kind):
    out = []
    for a in m["catalog"]:
        if a["kind"] == kind:
            out = out + a["values"]
        end
    end
    return out
end

# Vlastni zkratky: pojmenovane v shortcuts.json, nebo prikazy mimo katalog a mimo vychozi
function custom_actions(m):
    known = known_values(m, "cmd")
    active = m["active"]["cmd"]
    out = []
    for norm in sorted(active.keys()):
        value = active[norm][1]
        item = m["names"].get(norm, None)
        label = ""
        if item != None and item["command"] == value:
            label = item["name"]
        elif value in known or m["default_norm"]["cmd"].get(norm, None) == value:
            continue
        else:
            label = value.strip()
        end
        out.append(action("custom:" + norm, "custom", label, "cmd", [value], True))
    end
    return out
end

# Vychozi prikazy Xfce mimo katalog LuxOS (lze je zmenit, vypnout i obnovit)
function other_actions(m):
    known = known_values(m, "cmd")
    seen = []
    defs = m["default_norm"]["cmd"]
    for norm in defs.keys():
        value = defs[norm]
        if value != "" and not (value in known) and not (value in seen):
            seen.append(value)
        end
    end
    return [action("other:" + v, "other", short_label(v), "cmd", [v], False) for v in seen]
end

function actions(m):
    return m["catalog"] + custom_actions(m) + other_actions(m)
end

function find_action(m, aid):
    for a in actions(m):
        if a["id"] == aid:
            return a
        end
    end
    return None
end

# Kdo pouziva zkratku: [druh, hodnota] nebo None
function owner(m, norm):
    for kind in KINDS:
        if norm in m["active"][kind]:
            return [kind, m["active"][kind][norm][1]]
        end
    end
    return None
end

function owner_label(m, norm):
    own = owner(m, norm)
    if own == None:
        return None
    end
    if own[0] == "wm":
        return wm_action_label(own[1])
    end
    item = m["names"].get(norm, None)
    if item != None and item["command"] == own[1]:
        return item["name"]
    end
    for a in m["catalog"]:
        if a["kind"] == "cmd" and own[1] in a["values"]:
            return a["label"]
        end
    end
    return own[1].strip()
end

# Nazev akce, ktera uz zkratku pouziva (jina nez tato akce), jinak None
function conflict(m, act, norm):
    own = owner(m, norm)
    if own == None:
        return None
    end
    if act != None and own[0] == act["kind"] and own[1] in act["values"]:
        return None
    end
    return owner_label(m, norm)
end

# ---- zapis --------------------------------------------------------------------------------------------------------

function prop(m, kind, norm):
    return BASES[kind] + "/" + m["raw"][kind].get(norm, norm)
end

function set_value(m, kind, norm, value):
    return xfconf_call(["-p", prop(m, kind, norm), "-n", "-t", "string", "-s", value])[0]
end

function reset(m, kind, norm):
    p = prop(m, kind, norm)
    if p == BASES[kind] or p == BASES[kind] + "/":
        return False
    end
    return xfconf_call(["-p", p, "-r", "-R"])[0]
end

# Vypnout zkratku: systemovou prazdnym prikazem, uzivatelskou smazanim
function disable_accel(m, kind, norm):
    if m["default_norm"][kind].get(norm, "") != "":
        return set_value(m, kind, norm, "")
    end
    return reset(m, kind, norm)
end

# Uvolni zkratku ve vsech sekcich (krome keep = [druh, hodnota])
function free(m, norm, keep):
    ok = True
    for kind in KINDS:
        if norm in m["active"][kind]:
            if keep != None and keep[0] == kind and m["active"][kind][norm][1] == keep[1]:
                continue
            end
            ok = disable_accel(m, kind, norm) and ok
        end
    end
    return ok
end

# Nastavi akci zkratku; replace = puvodni zkratka akce, ktera se uvolni. Kolidujici zkratka jine akce se
# uvolni (okno se predtim zepta).
function assign(m, act, accel, replace):
    norm = normalize(accel)
    if norm == "":
        return False
    end
    kind = act["kind"]
    ok = free(m, norm, [kind, act["values"][0]])
    active = m["active"][kind]
    if replace != "" and replace != norm and replace in active and active[replace][1] in act["values"]:
        ok = disable_accel(m, kind, replace) and ok
    end
    current = active.get(norm, None)
    if current == None or not (current[1] in act["values"]):
        ok = set_value(m, kind, norm, act["values"][0]) and ok
    end
    call reload(m)
    return ok
end

function disable(m, act):
    ok = True
    for norm in accels_for(m, act):
        ok = disable_accel(m, act["kind"], norm) and ok
    end
    call reload(m)
    return ok
end

# Vychozi zkratky akce: pridane uvolnit, vychozi vratit (reset na systemovou hodnotu)
function restore(m, act):
    defaults = default_accels(m, act)
    ok = True
    for norm in accels_for(m, act):
        if not (norm in defaults):
            ok = disable_accel(m, act["kind"], norm) and ok
        end
    end
    for norm in defaults:
        ok = reset(m, act["kind"], norm) and ok
    end
    call reload(m)
    return ok
end

# Vsechny zkratky na vychozi; vlastni zkratky zustanou, pokud nekoliduji s vychozimi
function restore_all(m):
    customs = [[normalize(a["id"][7:]), a["values"][0]] for a in custom_actions(m)]
    ok = True
    for kind in KINDS:
        ok = xfconf_call(["-p", BASES[kind], "-r", "-R"])[0] and ok
    end
    call reload(m)
    kept = {}
    for item in customs:
        if owner(m, item[0]) != None:
            continue
        end
        ok = set_value(m, "cmd", item[0], item[1]) and ok
        if item[0] in m["names"]:
            kept[item[0]] = m["names"][item[0]]
        end
    end
    call save_names(kept, m["names_path"])
    call reload(m)
    return ok
end

# Prida nebo upravi vlastni zkratku (old = puvodni zkratka upravovane polozky, "" = nova)
function save_custom(m, name, command, accel, old):
    norm = normalize(accel)
    if norm == "" or command.strip() == "" or name.strip() == "":
        return False
    end
    command = command.strip()
    ok = True
    if old != "" and old != norm and old in m["active"]["cmd"]:
        ok = reset(m, "cmd", old) and ok
    end
    call reload(m)
    ok = free(m, norm, ["cmd", command]) and ok
    ok = set_value(m, "cmd", norm, command) and ok
    names = load_names(m["names_path"])
    if old != "":
        call names.pop(old, None)
    end
    names[norm] = {"name": name.strip(), "command": command}
    call save_names(names, m["names_path"])
    call reload(m)
    return ok
end

# Smaze vlastni zkratku (prepsana systemova zkratka se tim vrati)
function delete_custom(m, norm):
    ok = True
    if norm in m["active"]["cmd"]:
        ok = reset(m, "cmd", norm)
    end
    names = load_names(m["names_path"])
    if norm in names:
        call names.pop(norm)
        call save_names(names, m["names_path"])
    end
    call reload(m)
    return ok
end

# Zapomenout nazev vlastni polozky (po vypnuti jeji zkratky)
function forget_name(m, norm):
    names = load_names(m["names_path"])
    if norm in names:
        call names.pop(norm)
        call save_names(names, m["names_path"])
    end
    call reload(m)
end

# ---- prepinani rozlozeni (XKB, mimo xfconf) ---------------------------------------------------------------------

# Zkratka pro prepnuti rozlozeni z XkbOptions (grp:...) v konfiguraci X; "" = neni
function layout_switch(path):
    if path == "":
        path = env.get("LUXOS_XKB_CONF", "")
    end
    if path == "":
        path = "/etc/X11/xorg.conf.d/00-keyboard.conf"
    end
    content = lglib.read_text(path)
    cut = content.find("\"XkbOptions\"")
    if cut < 0:
        return ""
    end
    start = content.find("\"", cut + 12)
    if start < 0 or content[cut + 12:start].strip() != "":
        return ""
    end
    stop = content.find("\"", start + 1)
    if stop < 0:
        return ""
    end
    for opt in content[start + 1:stop].split(","):
        opt = opt.strip()
        if opt.startswith("grp:"):
            return XKB_TOGGLES.get(opt[4:], opt[4:].replace("_", " "))
        end
    end
    return ""
end

# ---- samotna klavesa Super otevre Launchpad (hlida luxos-menubar) -------------------------------------------

# Priznak vypnuti; luxos-menubar ho kontroluje kazdych 5 s
function super_tap_flag():
    return config_home() + "/luxos/super-launchpad-off"
end

function super_tap_enabled(path):
    if path == "":
        path = super_tap_flag()
    end
    return not exists(path)
end

# Zapne/vypne otevirani Launchpadu samotnou klavesou Super; vraci uspech
function set_super_tap(on, path):
    if path == "":
        path = super_tap_flag()
    end
    if on:
        if exists(path):
            return lglib.unlink(path)
        end
        return True
    end
    call lglib.mkdir_p(path[:text.rfind(path, "/")])
    if exists(path):
        return True
    end
    ok = False
    safe:
        call writefile(path, "")
        ok = True
    end
    return ok
end

# ---- Alt+Tab seskupeny po aplikacich (xfwm4 z [luxos], kanal xfwm4 /general/cycle_group_apps) ------------

# Alt+Tab ukaze kazdou aplikaci jednou (vychozi vypnuto)
function group_apps_enabled():
    r = query("xfwm4", ["-p", GROUP_APPS_PROP])
    return r[0] and r[1].strip().lower() == "true"
end

# Zapne/vypne seskupeni oken po aplikacich v Alt+Tab; xfwm4 ho pouzije hned. Vraci uspech.
function set_group_apps(on):
    return query("xfwm4", ["-p", GROUP_APPS_PROP, "-n", "-t", "bool", "-s", "true" if on else "false"])[0]
end
