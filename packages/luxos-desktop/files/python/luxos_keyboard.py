"""LuxOS - rozlozeni klavesnice pro cely system (vsechny uzivatele a prihlasovaci obrazovku).

Systemove nastaveni je v /etc/X11/xorg.conf.d/00-keyboard.conf ve formatu, ktery pise
systemd-localed (localectl set-x11-keymap). Z nej si rozlozeni bere X server (relace,
prihlasovaci obrazovka luxos-greeter) a localed z nej odvodi i konzoli (/etc/vconsole.conf).
Uzivatelske Xfce se ridi systemem, dokud ma kanal keyboard-layout /Default/XkbDisable = true.

Pouziva aplikace Klavesnice (luxos-keyboard); instalator zapisuje stejny format v setup-chroot.sh.
LUXOS_KEYBOARD_CONF a LUXOS_XKB_RULES prepisou cesty (testy).
"""
import os
import re

CONF = os.environ.get("LUXOS_KEYBOARD_CONF", "/etc/X11/xorg.conf.d/00-keyboard.conf")
VCONSOLE = os.environ.get("LUXOS_VCONSOLE_CONF", "/etc/vconsole.conf")
RULES = os.environ.get("LUXOS_XKB_RULES", "/usr/share/X11/xkb/rules/evdev.lst")
MAX_LAYOUTS = 4   # XKB umi nejvyse 4 skupiny
DEFAULT_SWITCH = "grp:alt_shift_toggle"
# Prepinani rozlozeni (XkbOptions grp:...); Super+Mezernik je Hledani, Alt+Mezernik nabidka okna
SWITCH_OPTIONS = [
    ("grp:alt_shift_toggle", "Alt + Shift"),
    ("grp:ctrl_shift_toggle", "Ctrl + Shift"),
    ("grp:shifts_toggle", "Both Shift keys"),
    ("grp:caps_toggle", "Caps Lock"),
    ("grp:menu_toggle", "Menu key"),
    ("", "Only by clicking the flag in the menu bar"),
]
# Bezna rozlozeni nahore seznamu (stejne nazvy jako v instalatoru, maji preklad)
COMMON = [
    ("English (US)", "us", ""), ("Czech", "cz", ""), ("Czech (QWERTY)", "cz", "qwerty"), ("Slovak", "sk", ""),
    ("Slovak (QWERTY)", "sk", "qwerty"), ("German", "de", ""), ("English (UK)", "gb", ""), ("French", "fr", ""),
    ("Spanish", "es", ""), ("Italian", "it", ""), ("Polish", "pl", ""), ("Hungarian", "hu", ""),
    ("Ukrainian", "ua", ""), ("Portuguese", "pt", ""), ("Portuguese (Brazil)", "br", ""), ("Swedish", "se", ""),
]
LAYOUT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
VARIANT_RE = re.compile(r"^[A-Za-z0-9_-]{0,48}$")
OPTION_RE = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$")


class KeyboardError(ValueError):
    pass


# ---- cteni a zapis ------------------------------------------------------------------------
def parse_conf(text):
    """Obsah 00-keyboard.conf -> {"layouts": [(rozlozeni, varianta)], "model": str, "options": [str]}."""
    vals = {}
    for line in text.splitlines():
        m = re.match(r'\s*Option\s+"([^"]+)"\s+"([^"]*)"', line)
        if m:
            vals[m.group(1)] = m.group(2)
    return from_strings(vals.get("XkbLayout", ""), vals.get("XkbVariant", ""),
                        vals.get("XkbOptions", ""), vals.get("XkbModel", ""))


def parse_vconsole(text):
    """XKB* z /etc/vconsole.conf (systemd >= 255 je uklada i tam)."""
    vals = {}
    for line in text.splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.startswith("XKB"):
            vals[k] = v.strip().strip('"')
    return from_strings(vals.get("XKBLAYOUT", ""), vals.get("XKBVARIANT", ""),
                        vals.get("XKBOPTIONS", ""), vals.get("XKBMODEL", ""))


def from_strings(layout, variant="", options="", model=""):
    lays = [s.strip() for s in layout.split(",")]
    vars_ = [s.strip() for s in variant.split(",")]
    layouts = [(lays[i], vars_[i] if i < len(vars_) else "") for i in range(len(lays)) if lays[i]]
    return {"layouts": layouts, "model": model.strip(),
            "options": [o.strip() for o in options.split(",") if o.strip()]}


def read_system(conf=None, vconsole=None):
    """Aktualni systemove nastaveni; bez souboru US bez prepinani."""
    for path, parse in ((conf or CONF, parse_conf), (vconsole or VCONSOLE, parse_vconsole)):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = parse(f.read())
        except OSError:
            continue
        if cfg["layouts"]:
            return cfg
    return {"layouts": [("us", "")], "model": "", "options": []}


def validate(layouts, options=()):
    """Kontrola pred zapisem (hodnoty jdou do prikazove radky a konfigurace X)."""
    if not layouts:
        raise KeyboardError("at least one layout is needed")
    if len(layouts) > MAX_LAYOUTS:
        raise KeyboardError(f"at most {MAX_LAYOUTS} layouts are possible")
    if len(set(layouts)) != len(layouts):
        raise KeyboardError("duplicate layout")
    for lay, var in layouts:
        if not LAYOUT_RE.match(lay) or not VARIANT_RE.match(var):
            raise KeyboardError(f"invalid layout {lay!r} {var!r}")
    for o in options:
        if not OPTION_RE.match(o):
            raise KeyboardError(f"invalid option {o!r}")


def xkb_strings(layouts):
    """[(cz, qwerty), (us, "")] -> ("cz,us", "qwerty,")."""
    return ",".join(lay for lay, _v in layouts), ",".join(var for _l, var in layouts)


def switch_of(options):
    """Prepinani rozlozeni z XkbOptions (prvni grp:...), "" = zadne."""
    return next((o for o in options if o.startswith("grp:")), "")


def with_switch(options, switch):
    """XkbOptions s jinym prepinanim; ostatni volby (compose, ctrl...) zustanou."""
    rest = [o for o in options if not o.startswith("grp:")]
    return ([switch] if switch else []) + rest


def conf_text(layouts, options=(), model=""):
    """00-keyboard.conf stejne jako ho pise systemd-localed."""
    validate(layouts, options)
    lay, var = xkb_strings(layouts)
    lines = ["# Written by systemd-localed(8), read by systemd-localed and Xorg. It's",
             '# probably wise not to edit this file manually. Use localectl(1) to',
             "# update this file.",
             'Section "InputClass"',
             '        Identifier "system-keyboard"',
             '        MatchIsKeyboard "on"',
             f'        Option "XkbLayout" "{lay}"']
    if model:
        lines.append(f'        Option "XkbModel" "{model}"')
    if any(var.split(",")):
        lines.append(f'        Option "XkbVariant" "{var}"')
    if options:
        lines.append(f'        Option "XkbOptions" "{",".join(options)}"')
    lines.append("EndSection")
    return "\n".join(lines) + "\n"


def localectl_cmd(layouts, options=(), model=""):
    """Systemovy zapis pres systemd-localed (opravneni overi polkit, konzoli odvodi localed)."""
    validate(layouts, options)
    lay, var = xkb_strings(layouts)
    return ["localectl", "set-x11-keymap", lay, model, var, ",".join(options)]


def setxkbmap_cmd(layouts, options=()):
    """Okamzite pouziti v bezici relaci ("-option ''" nejdriv smaze stare volby)."""
    validate(layouts, options)
    lay, var = xkb_strings(layouts)
    cmd = ["setxkbmap", "-layout", lay, "-variant", var, "-option", ""]
    if options:
        cmd += ["-option", ",".join(options)]
    return cmd


# ---- katalog rozlozeni --------------------------------------------------------------------
def load_catalog(path=None):
    """[((rozlozeni, varianta), popis)] z evdev.lst: bezna nahore, ostatni podle abecedy."""
    common = [((lay, var), name) for name, lay, var in COMMON]
    seen = {k for k, _d in common}
    rest, section = [], None
    try:
        with open(path or RULES, encoding="utf-8") as f:
            for line in f:
                if line.startswith("!"):
                    section = line[1:].strip()
                    continue
                m = re.match(r"\s+(\S+)\s+(.*)", line)
                if not m:
                    continue
                if section == "layout":
                    key, desc = (m.group(1), ""), m.group(2).strip()
                elif section == "variant" and ":" in m.group(2):
                    lay, desc = m.group(2).split(":", 1)
                    key, desc = (lay.strip(), m.group(1)), desc.strip()
                else:
                    continue
                if key not in seen:
                    seen.add(key)
                    rest.append((key, desc))
    except OSError:
        pass
    rest.sort(key=lambda it: it[1].lower())
    return common + rest


def describe(key, catalog=None, tr=lambda s: s):
    """Citelny nazev rozlozeni (bezna maji preklad)."""
    for name, lay, var in COMMON:
        if (lay, var) == tuple(key):
            return tr(name)
    for k, desc in catalog or ():
        if k == tuple(key):
            return desc
    lay, var = key
    return f"{lay} ({var})" if var else lay


def short(key):
    """Kratky stitek jako vlajka v horni liste: CZ, CZ qwerty."""
    lay, var = key
    return lay.upper() + (f" {var}" if var else "")
