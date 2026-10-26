"""LuxOS - klavesove zkratky: cteni a zapis zkratek Xfce v xfconf (kanal xfce4-keyboard-shortcuts).

Zkratky jsou v xfconf jako vlastnost "zkratka -> prikaz":
  /commands/custom/<Super>e = thunar             (spousti xfsettingsd)
  /xfwm4/custom/<Super>q    = close_window_key   (akce spravce oken xfwm4)
Vychozi hodnoty jsou v systemovem souboru kanalu (XDG_CONFIG_DIRS, u LuxOS /etc/xdg/luxos).
Reset vlastnosti (xfconf-query -r) vrati systemovou hodnotu, systemovou zkratku proto nelze
smazat - vypina se prazdnym prikazem (knihovna zkratek Xfce prazdne prikazy preskakuje).

Nazvy vlastnich zkratek (xfconf zna jen prikaz) jsou v ~/.config/luxos/shortcuts.json.
LUXOS_XFCONF_QUERY prepise prikaz xfconf-query (testy s falesnym prikazem),
LUXOS_SHORTCUTS_DEFAULTS soubor s vychozimi zkratkami a LUXOS_XKB_CONF nastaveni klavesnice X.
Samotna klavesa Super otevira Launchpad (luxos-menubar), dokud neexistuje priznak
~/.config/luxos/super-launchpad-off.
"""
import json
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET

try:
    from luxos_i18n import _
except ImportError:          # pragma: no cover - bez balicku luxos-i18n
    def _(text):
        return text

CHANNEL = "xfce4-keyboard-shortcuts"
BASES = {"cmd": "/commands/custom", "wm": "/xfwm4/custom"}
CHANNEL_FILE = os.path.join("xfce4", "xfconf", "xfce-perchannel-xml", CHANNEL + ".xml")

# Poradi modifikatoru v ulozenem nazvu (jako gtk_accelerator_name) a v zobrazeni (styl LuxOS)
MOD_ORDER = ("ctrl", "shift", "alt", "super")
MOD_NAMES = {"ctrl": "<Primary>", "shift": "<Shift>", "alt": "<Alt>", "super": "<Super>"}
MOD_DISPLAY = (("ctrl", "Ctrl"), ("super", "Super"), ("alt", "Alt"), ("shift", "Shift"))
MOD_ALIASES = {"primary": "ctrl", "control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl", "shift": "shift", "shft": "shift",
               "alt": "alt", "mod1": "alt", "super": "super", "mod4": "super", "meta": "meta", "hyper": "hyper",
               "release": "release"}
# Modifikatory, ktere LuxOS v nazvu nepouziva (Meta/Hyper) - zkratky s nimi se zobrazi, ale needituji
EXTRA_MODS = {"meta": "<Meta>", "hyper": "<Hyper>", "release": "<Release>"}

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
    "XF86WWW": "Web", "XF86HomePage": "Home Page", "XF86Mail": "Mail", "XF86Explorer": "Explorer",
}
# Samotne klavesy bez modifikatoru povolene jako zkratka (pismena by prekazela psani)
SOLO_KEY = re.compile(r"^(F([1-9]|[1-3][0-9])|XF86\w+|Print|Pause|Scroll_Lock|Menu)$")
MODIFIER_KEYS = re.compile(r"^(Shift|Control|Alt|Super|Meta|Hyper|ISO_Level\d|ISO_Group|Caps|Num_Lock|Mode_switch)")


# ---- nazvy zkratek -------------------------------------------------------------------------------
def parse_accel(text):
    """"<Super><Shift>4" -> (frozenset({"super", "shift"}), "4"); neplatny nazev -> None."""
    if not text or not isinstance(text, str):
        return None
    mods = set()
    rest = text.strip()
    while rest.startswith("<"):
        end = rest.find(">")
        if end < 0:
            return None
        name = rest[1:end].strip().lower()
        if name not in MOD_ALIASES:
            return None
        mods.add(MOD_ALIASES[name])
        rest = rest[end + 1:]
    key = rest.strip()
    if not key or "<" in key or ">" in key or " " in key:
        return None
    if len(key) == 1 and key.isalpha():
        key = key.lower()            # GTK uklada pismena male: <Super>e
    return frozenset(mods), key


def make_accel(mods, key):
    """Kanonicky nazev zkratky ve stylu GTK (modifikatory v pevnem poradi)."""
    if len(key) == 1 and key.isalpha():
        key = key.lower()
    extra = "".join(EXTRA_MODS[m] for m in ("release", "meta", "hyper") if m in mods)
    return "".join(MOD_NAMES[m] for m in MOD_ORDER if m in mods) + extra + key


def normalize(text):
    """Kanonicky tvar pro porovnani: "<Shift><Super>Down" == "<Super><Shift>Down"."""
    p = parse_accel(text)
    return make_accel(*p) if p else None


def key_label(key):
    if key in KEY_DISPLAY:
        return KEY_DISPLAY[key]
    if len(key) == 1:
        return key.upper()
    if key.startswith("KP_"):
        return "Num " + key_label(key[3:])
    if key.startswith("XF86"):
        # XF86AudioPlay -> Audio Play
        return re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", key[4:])
    return key.replace("_", " ")


def format_accel(text):
    """"<Super><Shift>4" -> "Super + Shift + 4" (bez symbolu macOS, LuxOS rika Super)."""
    p = parse_accel(text)
    if not p:
        return text or ""
    mods, key = p
    parts = [label for m, label in MOD_DISPLAY if m in mods]
    parts += [m.capitalize() for m in ("meta", "hyper") if m in mods]
    parts.append(key_label(key))
    return " + ".join(parts)


def accel_allowed(text):
    """Pouzitelna globalni zkratka: s Ctrl/Alt/Super, nebo samotna funkcni/multimedialni klavesa."""
    p = parse_accel(text)
    if not p:
        return False
    mods, key = p
    if MODIFIER_KEYS.match(key):
        return False
    if mods & {"ctrl", "alt", "super"}:
        return True
    return bool(SOLO_KEY.match(key))


# ---- xfconf -----------------------------------------------------------------------------------------
def xfconf_cmd():
    return os.environ.get("LUXOS_XFCONF_QUERY") or "xfconf-query"


def xfconf(*args):
    """Spusti xfconf-query pro kanal zkratek; vraci (uspech, stdout)."""
    try:
        r = subprocess.run([xfconf_cmd(), "-c", CHANNEL, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return r.returncode == 0, r.stdout


def parse_listing(text):
    """Vystup "xfconf-query -l -v" -> {"cmd": {zkratka: prikaz}, "wm": {zkratka: akce}}.
    Podvlastnosti (…/<Super>e/startup-notify) a "override" se preskoci."""
    out = {"cmd": {}, "wm": {}}
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split(None, 1)
        prop = parts[0]
        value = parts[1].strip() if len(parts) > 1 else ""
        for kind, base in BASES.items():
            if prop.startswith(base + "/"):
                rest = prop[len(base) + 1:]
                if "/" in rest or rest == "override":
                    break
                out[kind][rest] = value
                break
    return out


def read_current():
    """Aktualni (efektivni) zkratky z xfconf; None, kdyz xfconf neni dostupny."""
    ok, text = xfconf("-l", "-v")
    if not ok:
        return None
    return parse_listing(text)


def defaults_path():
    env = os.environ.get("LUXOS_SHORTCUTS_DEFAULTS")
    if env:
        return env
    # xfconf pouzije prvni nalezeny soubor kanalu (vyssi priorita nahradi cely kanal)
    for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":"):
        p = os.path.join(d, CHANNEL_FILE)
        if d and os.path.exists(p):
            return p
    return None


def read_defaults(path=None):
    """Vychozi zkratky ze systemoveho XML kanalu (stejna struktura jako parse_listing)."""
    out = {"cmd": {}, "wm": {}}
    path = path or defaults_path()
    if not path:
        return out
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return out

    def child(node, name):
        for c in node.findall("property"):
            if c.get("name") == name:
                return c
        return None

    for kind, base in BASES.items():
        node = root
        for name in base.strip("/").split("/"):
            node = child(node, name) if node is not None else None
        if node is None:
            continue
        for p in node.findall("property"):
            if p.get("type") == "string" and p.get("name") != "override":
                out[kind][p.get("name")] = p.get("value") or ""
    return out


# ---- nazvy vlastnich zkratek -------------------------------------------------------------------------
def store_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "luxos", "shortcuts.json")


def load_names(path=None):
    """{"<Super>k": {"name": "Moje skripty", "command": "..."}}; poskozeny soubor -> {}."""
    try:
        with open(path or store_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    custom = data.get("custom") if isinstance(data, dict) else None
    if not isinstance(custom, dict):
        return {}
    out = {}
    for accel, item in custom.items():
        norm = normalize(accel)
        if norm and isinstance(item, dict) and isinstance(item.get("name"), str) \
                and isinstance(item.get("command"), str):
            out[norm] = {"name": item["name"], "command": item["command"]}
    return out


def save_names(names, path=None):
    path = path or store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "custom": names}, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# ---- akce -------------------------------------------------------------------------------------------
class Action:
    """Polozka seznamu: jedna akce (prikaz nebo akce xfwm4) a vsechny jeji zkratky."""

    def __init__(self, aid, section, label, kind, values, custom=False):
        self.id = aid
        self.section = section
        self.label = label
        self.kind = kind
        self.values = list(values)      # prvni hodnota se zapisuje, ostatni jsou aliasy
        self.custom = custom

    @property
    def value(self):
        return self.values[0]

    def __repr__(self):
        return f"Action({self.id!r})"


SECTIONS = (("windows", "Windows"), ("apps", "Apps & System"), ("screenshots", "Screenshots"),
            ("custom", "Custom Shortcuts"), ("other", "Other Xfce Shortcuts"))


def catalog():
    """Zname akce LuxOS s citelnymi nazvy (prelozene texty z puvodniho prehledu)."""
    W, A, S = "windows", "apps", "screenshots"
    return [
        Action("close", W, _("Close window"), "wm", ["close_window_key"]),
        Action("hide", W, _("Minimize window"), "wm", ["hide_window_key"]),
        Action("cycle", W, _("Switch windows"), "wm", ["cycle_windows_key"]),
        Action("cycle-reverse", W, _("Switch windows backwards"), "wm", ["cycle_reverse_windows_key"]),
        Action("switch-app", W, _("Switch windows of the same app"), "wm", ["switch_window_key"]),
        Action("maximize", W, _("Maximize window"), "wm", ["maximize_window_key"]),
        Action("tile-left", W, _("Tile window left"), "wm", ["tile_left_key"]),
        Action("tile-right", W, _("Tile window right"), "wm", ["tile_right_key"]),
        Action("fullscreen", W, _("Full screen"), "wm", ["fullscreen_key"]),
        Action("desktop", W, _("Show desktop"), "wm", ["show_desktop_key"]),
        Action("ws-left", W, _("Previous workspace"), "wm", ["left_workspace_key"]),
        Action("ws-right", W, _("Next workspace"), "wm", ["right_workspace_key"]),
        Action("ws-1", W, _("Go to workspace %d") % 1, "wm", ["workspace_1_key"]),
        Action("ws-2", W, _("Go to workspace %d") % 2, "wm", ["workspace_2_key"]),
        Action("search", A, _("Search"), "cmd", ["luxos-search", "luxos-spotlight"]),
        Action("launchpad", A, "Launchpad", "cmd", ["luxos-launchpad"]),
        Action("files", A, _("Files"), "cmd", ["thunar", "exo-open --launch FileManager"]),
        Action("terminal", A, _("Terminal"), "cmd", ["luxos-terminal", "xfce4-terminal",
                                                    "exo-open --launch TerminalEmulator"]),
        Action("settings", A, _("Settings"), "cmd", ["xfce4-settings-manager"]),
        Action("lock", A, _("Lock screen"), "cmd", ["xflock4"]),
        Action("monitor", A, _("System monitor (force quit)"), "cmd", ["luxos-monitor", "xfce4-taskmanager"]),
        Action("displays", A, _("Displays"), "cmd", ["luxos-displays menu"]),
        Action("calculator", A, _("Calculator"), "cmd", ["luxos-calculator"]),
        Action("logout", A, _("Log out or shut down"), "cmd", ["xfce4-session-logout"]),
        Action("shot-screen", S, _("Screenshot"), "cmd", ["luxos-screenshot --screen"]),
        Action("shot-region", S, _("Screenshot of region"), "cmd", ["luxos-screenshot --portion"]),
        Action("shot-tool", S, _("Screenshot tool"), "cmd", ["luxos-screenshot"]),
    ]


def wm_action_label(value):
    """Citelny nazev akce xfwm4 mimo katalog (pro hlasku o kolizi)."""
    for a in catalog():
        if a.kind == "wm" and value in a.values:
            return a.label
    m = re.match(r"^workspace_(\d+)_key$", value)
    if m:
        return _("Go to workspace %d") % int(m.group(1))
    return value.replace("_key", "").replace("_", " ").capitalize()


def command_label(command):
    """Cely prikaz (popis vlastni zkratky bez nazvu)."""
    return command.strip()


def short_label(command):
    """Kratky nazev prikazu pro seznam: "exo-open --launch WebBrowser" -> "Web Browser",
    "/usr/bin/xfce4-appfinder --collapsed" -> "xfce4-appfinder"."""
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    if not args:
        return command
    if os.path.basename(args[0]) == "exo-open" and "--launch" in args[:-1]:
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", args[args.index("--launch") + 1])
    return os.path.basename(args[0])


def strip_field_codes(exec_line):
    """Exec z .desktop bez %f/%U/... (pro spusteni zkratkou bez souboru)."""
    try:
        args = shlex.split(exec_line)
    except ValueError:
        args = exec_line.split()
    out = []
    for a in args:
        if re.fullmatch(r"%[fFuUdDnNickvm]", a):
            continue
        a = re.sub(r"%[fFuUdDnNickvm]", "", a).replace("%%", "%")
        if a:
            out.append(a)
    return shlex.join(out)


# ---- model --------------------------------------------------------------------------------------------
class Shortcuts:
    """Stav zkratek: aktualni hodnoty z xfconf, vychozi z XML a nazvy vlastnich zkratek."""

    def __init__(self, defaults=None, names_path=None):
        self.defaults = defaults if defaults is not None else read_defaults()
        self.names_path = names_path
        self.reload()

    # -- cteni --
    def reload(self):
        cur = read_current()
        self.available = cur is not None
        self.current = cur if cur is not None else {k: dict(v) for k, v in self.defaults.items()}
        self.names = load_names(self.names_path)
        self.catalog = catalog()
        self._index()

    def _index(self):
        # norm -> (raw nazev vlastnosti, hodnota); jen zapnute (neprazdne) zkratky
        self.active = {"cmd": {}, "wm": {}}
        self.raw = {"cmd": {}, "wm": {}}
        for kind in BASES:
            for src in (self.defaults[kind], self.current[kind]):
                for raw in src:
                    norm = normalize(raw)
                    if norm:
                        self.raw[kind].setdefault(norm, raw)
            for raw, value in self.current[kind].items():
                norm = normalize(raw)
                if norm and value:
                    self.active[kind][norm] = (raw, value)
        self.default_norm = {k: {normalize(r): v for r, v in self.defaults[k].items() if normalize(r)}
                             for k in BASES}

    def accels_for(self, action):
        """Zkratky akce v poradi: zkratky zvolene uzivatelem, pak vychozi (poradi z XML)."""
        found = [n for n, (_r, v) in self.active[action.kind].items() if v in action.values
                 and (action.custom or not self.is_named(action.kind, n))]
        order = [n for n, v in self.default_norm[action.kind].items() if v in action.values]
        return sorted(found, key=lambda n: (order.index(n) if n in order else -1, n))

    def is_named(self, kind, norm):
        """Zkratka patri pojmenovane vlastni polozce (ne radku katalogu se stejnym prikazem)."""
        item = self.names.get(norm)
        return kind == "cmd" and bool(item) and norm in self.active["cmd"] \
            and self.active["cmd"][norm][1] == item["command"]

    def default_accels(self, action):
        return [n for n, v in self.default_norm[action.kind].items() if v in action.values]

    def is_default(self, action):
        if action.custom:
            return True
        return sorted(self.accels_for(action)) == sorted(self.default_accels(action))

    def known_values(self, kind):
        return {v for a in self.catalog if a.kind == kind for v in a.values}

    def custom_actions(self):
        """Vlastni zkratky: pojmenovane v shortcuts.json, nebo prikazy mimo katalog a mimo vychozi."""
        known = self.known_values("cmd")
        out = []
        for norm, (_raw, value) in sorted(self.active["cmd"].items(), key=lambda kv: kv[0]):
            item = self.names.get(norm)
            if item and item["command"] == value:
                label = item["name"]
            elif value in known or self.default_norm["cmd"].get(norm) == value:
                continue
            else:
                label = command_label(value)
            out.append(Action("custom:" + norm, "custom", label, "cmd", [value], custom=True))
        return out

    def other_actions(self):
        """Vychozi prikazy Xfce mimo katalog LuxOS (lze je zmenit, vypnout i obnovit)."""
        known = self.known_values("cmd")
        seen = []
        for value in self.default_norm["cmd"].values():
            if value and value not in known and value not in seen:
                seen.append(value)
        return [Action("other:" + v, "other", short_label(v), "cmd", [v]) for v in seen]

    def actions(self):
        return self.catalog + self.custom_actions() + self.other_actions()

    def owner(self, norm):
        """Kdo pouziva zkratku: (druh, hodnota) nebo None."""
        for kind in ("cmd", "wm"):
            if norm in self.active[kind]:
                return kind, self.active[kind][norm][1]
        return None

    def owner_label(self, norm):
        own = self.owner(norm)
        if not own:
            return None
        kind, value = own
        if kind == "wm":
            return wm_action_label(value)
        item = self.names.get(norm)
        if item and item["command"] == value:
            return item["name"]
        for a in self.catalog:
            if a.kind == "cmd" and value in a.values:
                return a.label
        return command_label(value)

    def conflict(self, action, norm):
        """Nazev akce, ktera uz zkratku pouziva (jina nez tato akce), jinak None."""
        own = self.owner(norm)
        if not own:
            return None
        kind, value = own
        if action is not None and kind == action.kind and value in action.values:
            return None
        return self.owner_label(norm)

    # -- zapis --
    def _prop(self, kind, norm):
        return BASES[kind] + "/" + self.raw[kind].get(norm, norm)

    def _set(self, kind, norm, value):
        ok, _out = xfconf("-p", self._prop(kind, norm), "-n", "-t", "string", "-s", value)
        return ok

    def _reset(self, kind, norm):
        prop = self._prop(kind, norm)
        if prop.rstrip("/") == BASES[kind]:
            return False
        ok, _out = xfconf("-p", prop, "-r", "-R")
        return ok

    def _disable(self, kind, norm):
        """Vypnout zkratku: systemovou prazdnym prikazem, uzivatelskou smazanim."""
        if self.default_norm[kind].get(norm):
            return self._set(kind, norm, "")
        return self._reset(kind, norm)

    def free(self, norm, keep=None):
        """Uvolni zkratku ve vsech sekcich (krome keep=(druh, hodnota))."""
        ok = True
        for kind in ("cmd", "wm"):
            if norm in self.active[kind]:
                if keep and keep[0] == kind and self.active[kind][norm][1] == keep[1]:
                    continue
                ok = self._disable(kind, norm) and ok
        return ok

    def assign(self, action, accel, replace=None):
        """Nastavi akci zkratku accel. replace = puvodni zkratka akce, ktera se uvolni.
        Kolidujici zkratka jine akce se uvolni (UI se predtim zepta)."""
        norm = normalize(accel)
        if not norm:
            return False
        ok = self.free(norm, keep=(action.kind, action.value))
        if replace and replace != norm and replace in self.active[action.kind] \
                and self.active[action.kind][replace][1] in action.values:
            ok = self._disable(action.kind, replace) and ok
        current = self.active[action.kind].get(norm)
        if not current or current[1] not in action.values:
            ok = self._set(action.kind, norm, action.value) and ok
        self.reload()
        return ok

    def disable(self, action):
        ok = True
        for norm in self.accels_for(action):
            ok = self._disable(action.kind, norm) and ok
        self.reload()
        return ok

    def restore(self, action):
        """Vychozi zkratky akce: pridane uvolnit, vychozi vratit (reset na systemovou hodnotu)."""
        defaults = self.default_accels(action)
        ok = True
        for norm in self.accels_for(action):
            if norm not in defaults:
                ok = self._disable(action.kind, norm) and ok
        for norm in defaults:
            ok = self._reset(action.kind, norm) and ok
        self.reload()
        return ok

    def restore_all(self):
        """Vsechny zkratky na vychozi; vlastni zkratky zustanou, pokud nekoliduji s vychozimi."""
        customs = [(normalize(a.id.split(":", 1)[1]), a.value, a.label) for a in self.custom_actions()]
        ok = True
        for kind in ("cmd", "wm"):
            ok = xfconf("-p", BASES[kind], "-r", "-R")[0] and ok
        self.reload()
        kept = {}
        for norm, value, label in customs:
            if self.owner(norm):
                continue
            ok = self._set("cmd", norm, value) and ok
            if norm in self.names:
                kept[norm] = self.names[norm]
        save_names(kept, self.names_path)
        self.reload()
        return ok

    def save_custom(self, name, command, accel, old=None):
        """Prida nebo upravi vlastni zkratku (old = puvodni zkratka upravovane polozky)."""
        norm = normalize(accel)
        if not norm or not command.strip() or not name.strip():
            return False
        command = command.strip()
        ok = True
        if old and old != norm and old in self.active["cmd"]:
            ok = self._reset("cmd", old) and ok
        self.reload()
        ok = self.free(norm, keep=("cmd", command)) and ok
        ok = self._set("cmd", norm, command) and ok
        names = load_names(self.names_path)
        if old:
            names.pop(old, None)
        names[norm] = {"name": name.strip(), "command": command}
        save_names(names, self.names_path)
        self.reload()
        return ok

    def delete_custom(self, norm):
        """Smaze vlastni zkratku (prepsana systemova zkratka se tim vrati)."""
        ok = self._reset("cmd", norm) if norm in self.active["cmd"] else True
        names = load_names(self.names_path)
        if names.pop(norm, None) is not None:
            save_names(names, self.names_path)
        self.reload()
        return ok


# ---- prepinani rozlozeni (XKB, mimo xfconf) -------------------------------------------------------
XKB_TOGGLES = {
    "alt_shift_toggle": "Alt + Shift", "ctrl_shift_toggle": "Ctrl + Shift", "alt_space_toggle": "Alt + Space",
    "win_space_toggle": "Super + Space", "ctrl_alt_toggle": "Ctrl + Alt", "caps_toggle": "Caps Lock",
    "shift_caps_toggle": "Shift + Caps Lock", "alt_caps_toggle": "Alt + Caps Lock",
    "lwin_toggle": "Left Super", "rwin_toggle": "Right Super", "menu_toggle": "Menu",
    "shifts_toggle": "Left Shift + Right Shift", "alt_altgr_toggle": "Alt + AltGr",
}


def layout_switch(path=None):
    """Zkratka pro prepnuti rozlozeni z XkbOptions (grp:...) v konfiguraci X; None = neni."""
    path = path or os.environ.get("LUXOS_XKB_CONF") or "/etc/X11/xorg.conf.d/00-keyboard.conf"
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r'Option\s+"XkbOptions"\s+"([^"]*)"', text)
    if not m:
        return None
    for opt in m.group(1).split(","):
        opt = opt.strip()
        if opt.startswith("grp:"):
            return XKB_TOGGLES.get(opt[4:], opt[4:].replace("_", " "))
    return None


# ---- samotna klavesa Super otevre Launchpad (hlida luxos-menubar) -------------------------------
def super_tap_flag():
    """Priznak vypnuti; luxos-menubar ho kontroluje kazdych 5 s."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "luxos", "super-launchpad-off")


def super_tap_enabled(path=None):
    return not os.path.exists(path or super_tap_flag())


def set_super_tap(on, path=None):
    """Zapne/vypne otevirani Launchpadu samotnou klavesou Super; vraci uspech."""
    path = path or super_tap_flag()
    try:
        if on:
            if os.path.exists(path):
                os.remove(path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
    except OSError:
        return False
    return True
