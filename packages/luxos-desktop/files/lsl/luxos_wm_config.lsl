# LuxOS - nastaveni luxwm pro shell na Waylandu: cteni a uprava ~/.config/luxwm/luxwm.conf (rozlozeni
# klavesnice, zkratky) a jednorazovy prevod zkratek Xfce (xfconf xfce4-keyboard-shortcuts) do nej.
# Format souboru: packages/luxwm/README.md; system /usr/share/luxwm/luxwm.conf (LUXWM_SYSTEM_CONFIG).
#
#   parse(text) -> {"general": {..}, "keys": {zkratka: hodnota}}      zkratky v kanonickem tvaru
#   system_conf(), user_conf()                                         nactene soubory (chybejici = prazdne)
#   save(general, keys)          zmeny do uzivatelskeho souboru po polozkach; hodnota None polozku smaze
#                                (vrati systemovou), ostatni radky a komentare zustanou
#   normalize(zkratka)           "<Super><Primary>Left" -> "<Primary><Super>Left" ("" = spatny zapis)
#   import_xfce()                zkratky uzivatele z Xfce -> luxwm.conf, jen jednou; vraci pocet
#   xfce_overrides(user_xml, default_xml, system_keys) -> {zkratka: hodnota luxwm}, [preskocene prikazy]
load env, glib
load luxos_glib as lglib

MOD_ORDER = ["primary", "shift", "alt", "super"]
MOD_NAMES = {"primary": "<Primary>", "shift": "<Shift>", "alt": "<Alt>", "super": "<Super>"}
MOD_ALIASES = {"primary": "primary", "control": "primary", "ctrl": "primary", "shift": "shift", "alt": "alt",
               "mod1": "alt", "super": "super", "mod4": "super"}
XFCE_FILE = "/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
XFCE_DEFAULTS = "/etc/xdg/luxos" + XFCE_FILE
# Prikazy Xfce a jejich nahrada na Waylandu
COMMANDS = {"xflock4": "loginctl lock-session", "xfce4-settings-manager": "luxos-settings",
            "luxos-spotlight": "luxos-search", "xfce4-taskmanager": "luxos-monitor",
            "exo-open --launch TerminalEmulator": "luxos-terminal", "exo-open --launch FileManager": "thunar"}
# Bez Xfce/X11 nefunguji a nahradu zatim nemaji
X11_ONLY = ["xfce4-session-logout", "luxos-displays menu", "xfce4-display-settings", "xfce4-popup-whiskermenu",
            "xfce4-appfinder", "xfce4-appfinder --collapsed", "xkill", "xfce4-screenshooter"]

function config_home():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == "":
        base = env.get("HOME", "") + "/.config"
    end
    return base
end

function user_path():
    return config_home() + "/luxwm/luxwm.conf"
end

function system_path():
    path = env.get("LUXWM_SYSTEM_CONFIG", "")
    if path == "":
        path = "/usr/share/luxwm/luxwm.conf"
    end
    return path
end

function normalize(accel):
    mods = []
    rest = accel.strip()
    while rest.startswith("<"):
        stop = rest.find(">")
        if stop < 0:
            return ""
        end
        name = rest[1:stop].strip().lower()
        if not (name in MOD_ALIASES):
            return ""
        end
        mods.append(MOD_ALIASES[name])
        rest = rest[stop + 1:]
    end
    key = rest.strip()
    if key == "" or key.find("<") >= 0 or key.find(">") >= 0 or key.find(" ") >= 0:
        return ""
    end
    if len(key) == 1:
        key = key.lower()
    end
    out = ""
    for m in MOD_ORDER:
        if m in mods:
            out += MOD_NAMES[m]
        end
    end
    return out + key
end

function parse(text):
    general = {}
    keys = {}
    section = ""
    for raw in text.split("\n"):
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
            continue
        end
        name = line[:eq].strip()
        value = line[eq + 1:].strip()
        if section == "keys":
            norm = normalize(name)
            if norm != "":
                keys[norm] = value
            end
        elif section == "":
            general[name] = value
        end
    end
    return {"general": general, "keys": keys}
end

function system_conf():
    return parse(lglib.read_text(system_path()))
end

function user_conf():
    return parse(lglib.read_text(user_path()))
end

function entry(name, value):
    if value == "":
        return name + " ="
    end
    return name + " = " + value
end

# Nahradi, prida nebo smaze polozky jedne sekce ("" = obecna cast pred prvni sekci); zbytek textu zustane.
function set_entries(text, section, updates):
    lines = text.split("\n")
    if len(lines) > 0 and lines[len(lines) - 1] == "":
        call lines.pop()
    end
    left = {}
    for name in updates.keys():
        left[name] = updates[name]
    end
    out = []
    current = ""
    section_end = -1
    seen_section = section == ""
    for raw in lines:
        line = raw.strip()
        if line.startswith("["):
            if current == section and seen_section:
                section_end = len(out)
            end
            current = line.strip("[]").strip()
            if current == section:
                seen_section = True
            end
            out.append(raw)
            continue
        end
        eq = line.find("=")
        if current == section and eq > 0 and not line.startswith("#"):
            name = line[:eq].strip()
            if section == "keys":
                name = normalize(name)
            end
            if name in left:
                value = left.pop(name)
                if value != None:
                    out.append(entry(name, value))
                end
                continue
            end
        end
        out.append(raw)
    end
    if current == section and seen_section:
        section_end = len(out)
    end
    added = []
    for name in sorted(left.keys()):
        if left[name] != None:
            added.append(entry(name, left[name]))
        end
    end
    if len(added) > 0:
        if section_end < 0:
            if section == "":
                section_end = 0
                for i in range(len(out)):
                    if out[i].strip().startswith("["):
                        section_end = i
                        break
                    end
                    section_end = i + 1
                end
            else:
                if len(out) > 0 and out[len(out) - 1].strip() != "":
                    out.append("")
                end
                out.append("[" + section + "]")
                section_end = len(out)
            end
        end
        out = out[:section_end] + added + out[section_end:]
    end
    return "\n".join(out) + "\n"
end

function save(general, keys):
    path = user_path()
    text = lglib.read_text(path)
    if text == "":
        text = "# Vlastni nastaveni luxwm (prepisuje /usr/share/luxwm/luxwm.conf po polozkach)\n"
    end
    if len(general) > 0:
        text = set_entries(text, "", general)
    end
    if len(keys) > 0:
        text = set_entries(text, "keys", keys)
    end
    call lglib.mkdir_p(config_home() + "/luxwm")
    return lglib.write_atomic(path, text)
end

# ---- prevod zkratek Xfce -------------------------------------------------------------------------------

function unescape(text):
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&")
end

function attribute(tag, name):
    key = " " + name + "=\""
    start = tag.find(key)
    if start < 0:
        return None
    end
    start += len(key)
    stop = tag.find("\"", start)
    if stop < 0:
        return None
    end
    return unescape(tag[start:stop])
end

# Kanal xfconf jako XML: vlastnosti commands/custom/* a xfwm4/custom/* -> {"cmd": {..}, "wm": {..}}
function parse_xfce(text):
    out = {"cmd": {}, "wm": {}}
    stack = []
    pos = 0
    while True:
        start = text.find("<", pos)
        if start < 0:
            break
        end
        stop = text.find(">", start)
        if stop < 0:
            break
        end
        tag = text[start:stop + 1]
        pos = stop + 1
        if tag.startswith("</property"):
            if len(stack) > 0:
                call stack.pop()
            end
            continue
        end
        if not tag.startswith("<property"):
            continue
        end
        name = attribute(tag, "name")
        closed = tag.endswith("/>")
        if name == None:
            name = ""
        end
        kind = ""
        if len(stack) == 2 and stack[1] == "custom" and stack[0] == "commands":
            kind = "cmd"
        elif len(stack) == 2 and stack[1] == "custom" and stack[0] == "xfwm4":
            kind = "wm"
        end
        if kind != "" and attribute(tag, "type") == "string" and name != "override":
            norm = normalize(name)
            value = attribute(tag, "value")
            if norm != "" and value != None:
                out[kind][norm] = value.strip()
            end
        end
        if not closed:
            stack.append(name)
        end
    end
    return out
end

function luxwm_value(kind, value):
    if value == "":
        return ""
    end
    if kind == "wm":
        return value
    end
    return "exec " + COMMANDS.get(value, value)
end

# Zmeny uzivatele proti vychozim zkratkam Xfce jako polozky luxwm.conf. Shodne s vychozim luxwm se
# nepisou; akce xfwm4 mimo luxwm a prikazy jen pro X11 se preskoci (vraci se pro hlaseni).
function xfce_overrides(user_text, default_text, system_keys):
    user = parse_xfce(user_text)
    defaults = parse_xfce(default_text)
    result = {}
    skipped = []
    for kind in ["cmd", "wm"]:
        for accel in user[kind].keys():
            value = user[kind][accel]
            if defaults[kind].get(accel, None) == value:
                continue
            end
            if kind == "cmd" and value in X11_ONLY:
                skipped.append(accel + " = " + value)
                continue
            end
            if kind == "wm" and value != "" and not known_action(value):
                skipped.append(accel + " = " + value)
                continue
            end
            converted = luxwm_value(kind, value)
            if converted == "" and not (accel in system_keys):
                continue
            end
            if system_keys.get(accel, None) == converted:
                continue
            end
            result[accel] = converted
        end
    end
    return [result, skipped]
end

function known_action(action):
    names = ["close_window_key", "hide_window_key", "cycle_windows_key", "cycle_reverse_windows_key",
             "cycle_app_windows_key", "cycle_reverse_app_windows_key", "switch_window_key", "fullscreen_key",
             "maximize_window_key", "tile_left_key", "tile_right_key", "show_desktop_key", "left_workspace_key",
             "right_workspace_key", "move_window_left_workspace_key", "move_window_right_workspace_key"]
    if action in names:
        return True
    end
    return (action.startswith("workspace_") or action.startswith("move_window_workspace_")) and action.endswith("_key")
end

function defaults_path():
    path = env.get("LUXOS_SHORTCUTS_DEFAULTS", "")
    if path != "":
        return path
    end
    for d in env.get("XDG_CONFIG_DIRS", "/etc/xdg/luxos:/etc/xdg").split(":"):
        if d != "" and len(lglib.stat(d + XFCE_FILE)) > 0:
            return d + XFCE_FILE
        end
    end
    return XFCE_DEFAULTS
end

# Jednou na uzivatele (znacka ~/.config/luxwm/xfce-imported): zkratky z X11 relace do luxwm.conf
function import_xfce():
    marker = config_home() + "/luxwm/xfce-imported"
    if len(lglib.stat(marker)) > 0:
        return 0
    end
    user_text = lglib.read_text(config_home() + XFCE_FILE)
    count = 0
    if user_text != "":
        found = xfce_overrides(user_text, lglib.read_text(defaults_path()), system_conf()["keys"])
        if len(found[0]) > 0:
            current = user_conf()["keys"]
            keys = {}
            # co uz uzivatel nastavil primo pro luxwm, ma prednost
            for accel in found[0].keys():
                if not (accel in current):
                    keys[accel] = found[0][accel]
                end
            end
            if len(keys) > 0 and save({}, keys):
                count = len(keys)
            end
        end
        for item in found[1]:
            call glib.report("luxos-keyboard: shortcut not imported (X11 only): " + item + "\n")
        end
    end
    call lglib.mkdir_p(config_home() + "/luxwm")
    call lglib.write_atomic(marker, String(count) + "\n")
    return count
end
