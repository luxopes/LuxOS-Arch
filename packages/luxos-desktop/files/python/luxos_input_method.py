"""LuxOS - psani s diakritikou jinych jazyku pres metodu zadavani (fcitx5), zatim vietnamstina.

Vietnamstina se pise na bezne klavesnici (Telex: "tieesng vieejt" -> "tiếng việt", nebo VNI cislicemi),
tedy ne dalsim rozlozenim XKB, ale metodou zadavani: fcitx5 s modulem Bamboo (fcitx5-bamboo).
fcitx5 je soucasti LuxOS, ale bezi jen u uzivatele, ktery ho zapnul:

- volba uzivatele je v ~/.config/luxos/input-method (IM=vi nebo IM=none, VI_STYLE=Telex|VNI|VIQR);
- bez volby se zapne sam u jazyka vi_* (LANG) a nechava se byt u uzivatele, ktery si fcitx5
  nastavil sam (~/.config/fcitx5/profile existuje);
- spousti ho /etc/xdg/luxos/autostart/org.fcitx.Fcitx5.desktop (prekryva soubor z balicku fcitx5)
  pres "luxos-input-method autostart"; promenne GTK_IM_MODULE a spol. nastavi pri prihlaseni
  /etc/X11/xinit/xinitrc.d/55-luxos-input-method.sh se stejnym pravidlem, za behu (zapnuti
  v aplikaci Rozlozeni klavesnice) XSETTINGS Gtk/IMModule pro nove spustene aplikace GTK.

Prepinani anglictina/vietnamstina: Ctrl+Mezernik (Super+Mezernik je Hledani) nebo ikona v horni liste.
fcitx5 nemeni rozlozeni XKB (to dal ridi Rozlozeni klavesnice a vlajka v liste).

LUXOS_IM_FCITX5 a LUXOS_IM_XFCONF prepisou prikazy (testy); domov z HOME/XDG_CONFIG_HOME.
"""
import configparser
import io
import os
import shutil
import subprocess
import time

STYLES = ("Telex", "VNI", "VIQR")          # nabizene zpusoby psani (Bamboo umi i dalsi, ty se zachovaji)
DEFAULT_STYLE = "Telex"
LANGS = {"vi": {"name": "Vietnamese", "engine": "bamboo", "addon": "/usr/share/fcitx5/inputmethod/bamboo.conf"}}
TRIGGER = "Control+space"
# doplnky fcitx5 s vlastnimi zkratkami, ktere by bezne aplikace prekvapily (Ctrl+; schranka, Super+` fraze)
DISABLED_ADDONS = ("clipboard", "quickphrase")


def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def choice_path():
    return os.path.join(config_home(), "luxos", "input-method")


def fcitx_dir():
    return os.path.join(config_home(), "fcitx5")


def fcitx5_bin():
    exe = os.environ.get("LUXOS_IM_FCITX5") or shutil.which("fcitx5") or ""
    return exe if exe and os.access(exe, os.X_OK) else ""


def available(lang="vi"):
    """Je nainstalovany fcitx5 i modul jazyka?"""
    addon_root = os.environ.get("LUXOS_IM_ADDONS")
    addon = LANGS[lang]["addon"]
    if addon_root:
        addon = os.path.join(addon_root, os.path.basename(addon))
    return bool(fcitx5_bin()) and os.path.exists(addon)


# ---- volba uzivatele ---------------------------------------------------------------------
class ConfigError(ValueError):
    """Stavajici soubor fcitx5 nejde precist - LuxOS ho neprepise."""


def read_choice():
    """{"IM": "vi"|"none"|"user", "VI_STYLE": ..., "PREV": "user"|""} nebo {} (uzivatel jeste nevolil).
    PREV=user: vietnamstina pridana k vlastnimu nastaveni fcitx5 uzivatele (vypnutim se vrati)."""
    vals = {}
    try:
        with open(choice_path(), encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep and k and not k.startswith("#"):
                    vals[k.strip()] = v.strip()
    except (OSError, ValueError):
        return {}
    return vals


def write_choice(vals):
    path = choice_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# LuxOS: input method (luxos-input-method, Keyboard Layouts)\n")
        for k in ("IM", "VI_STYLE", "PREV"):
            if vals.get(k):
                f.write(f"{k}={vals[k]}\n")
    os.replace(tmp, path)


def lang_default():
    """Jazyk relace, pro ktery se metoda zapne sama (zatim jen vietnamstina)."""
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        v = os.environ.get(var, "")
        # C/POSIX preskocit: Python (PEP 538) sam nastavi LC_CTYPE=C.UTF-8, kdyz locale jazyka neni
        # vygenerovane (napr. vi_VN na zivem ISO) - jazyk uzivatele je pak dal v LANG
        if v and v.split(".")[0] not in ("C", "POSIX"):
            return "vi" if v.startswith("vi_") or v == "vi" else ""
    return ""


def has_profile():
    return os.path.exists(os.path.join(fcitx_dir(), "profile"))


def active():
    """Ktera metoda ma v teto relaci bezet: "vi", "user" (vlastni fcitx5 uzivatele) nebo "".
    Poradi (stejne jako 55-luxos-input-method.sh): volba IM=, vlastni profil fcitx5 (i u vietnamskeho
    jazyka - nastaveni uzivatele s Unikey apod. se neprepisuje), nakonec jazyk vi_*."""
    im = read_choice().get("IM", "")
    if im:
        return im if im in LANGS or im == "user" else ""
    if has_profile():
        return "user"
    return lang_default()


def style():
    return read_choice().get("VI_STYLE") or read_fcitx_style() or DEFAULT_STYLE


# ---- konfigurace fcitx5 -------------------------------------------------------------------
def _ini():
    p = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    p.optionxform = str   # fcitx5 rozlisuje velikost pismen
    return p


def _read_ini(path):
    """Parser se souborem; chybejici soubor = prazdny. Soubor, ktery nejde precist, se neprepisuje."""
    p = _ini()
    try:
        with open(path, encoding="utf-8") as f:
            p.read_file(f)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, configparser.Error) as e:   # UnicodeDecodeError je ValueError
        raise ConfigError(f"{path}: {e}") from e
    return p


def _write_ini(p, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    p.write(buf, space_around_delimiters=False)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    os.replace(tmp, path)


def read_fcitx_style():
    return _top_value(os.path.join(fcitx_dir(), "conf", "bamboo.conf"), "InputMethod")


def _top_value(path, key):
    """Hodnota pred prvni sekci (fcitx5 tak uklada konfiguraci doplnku)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    break
                k, sep, v = line.partition("=")
                if sep and k.strip() == key:
                    return v.strip()
    except (OSError, ValueError):
        pass
    return ""


def _set_top_values(path, values):
    """Nastavi klice pred prvni sekci, zbytek souboru (i sekce) zachova."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from e
    first = next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))
    head, tail = lines[:first], lines[first:]
    seen = set()
    for i, line in enumerate(head):
        k, sep, _v = line.partition("=")
        if sep and k.strip() in values:
            head[i] = f"{k.strip()}={values[k.strip()]}"
            seen.add(k.strip())
    head += [f"{k}={v}" for k, v in values.items() if k not in seen]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(head + tail) + "\n")
    os.replace(tmp, path)


def keyboard_item(layouts):
    """Polozka klavesnice fcitx5 podle prvniho systemoveho rozlozeni: keyboard-us, keyboard-cz-qwerty."""
    layout, variant = (layouts[0] if layouts else ("us", ""))
    return f"keyboard-{layout}-{variant}" if variant else f"keyboard-{layout}"


def _items(p, g):
    """Sekce polozek skupiny serazene podle cisla (cisla nemusi jit po sobe)."""
    def num(sec):
        n = sec.rsplit("/", 1)[1]
        return int(n) if n.isdigit() else -1
    return sorted((sec for sec in p.sections() if sec.startswith(g + "/Items/") and sec.count("/") == 3), key=num)


def _first_group(p):
    groups = [sec for sec in p.sections() if sec.startswith("Groups/") and sec.count("/") == 1]
    return groups[0] if groups else None


def write_profile(lang, layouts):
    """Skupina: klavesnice (vypnuto) + metoda jazyka. Jiny profil uzivatele se jen doplni o metodu."""
    path = os.path.join(fcitx_dir(), "profile")
    engine = LANGS[lang]["engine"]
    p = _read_ini(path)
    g = _first_group(p)
    if g:
        items = _items(p, g)
        if any(p.get(sec, "Name", fallback="") == engine for sec in items):
            return
        nums = [int(sec.rsplit("/", 1)[1]) for sec in items if sec.rsplit("/", 1)[1].isdigit()]
        p[f"{g}/Items/{max(nums, default=-1) + 1}"] = {"Name": engine, "Layout": ""}
        if not p.get(g, "DefaultIM", fallback=""):
            p[g]["DefaultIM"] = engine
        _write_ini(p, path)
        return
    layout, variant = (layouts[0] if layouts else ("us", ""))
    p = _ini()
    p["Groups/0"] = {"Name": "Default", "Default Layout": f"{layout}-{variant}" if variant else layout,
                     "DefaultIM": engine}
    p["Groups/0/Items/0"] = {"Name": keyboard_item(layouts), "Layout": ""}
    p["Groups/0/Items/1"] = {"Name": engine, "Layout": ""}
    p["GroupOrder"] = {"0": "Default"}
    _write_ini(p, path)


def remove_from_profile(lang):
    """Vypnuti u vlastniho nastaveni uzivatele: odebrat jen pridanou metodu, zbytek profilu zustane."""
    path = os.path.join(fcitx_dir(), "profile")
    if not os.path.exists(path):
        return
    engine = LANGS[lang]["engine"]
    p = _read_ini(path)
    g = _first_group(p)
    if not g:
        return
    items = _items(p, g)
    keep = [dict(p[sec]) for sec in items if p.get(sec, "Name", fallback="") != engine]
    if len(keep) == len(items):
        return
    for sec in items:
        p.remove_section(sec)
    for i, vals in enumerate(keep):
        p[f"{g}/Items/{i}"] = vals
    if p.get(g, "DefaultIM", fallback="") == engine:
        others = [v.get("Name", "") for v in keep if not v.get("Name", "").startswith("keyboard-")]
        p[g]["DefaultIM"] = others[-1] if others else (keep[0].get("Name", "") if keep else "")
    _write_ini(p, path)


def write_config():
    """Nastaveni LuxOS (jen kdyz fcitx5 nastavuje LuxOS): Ctrl+Mezernik zapina a vypina (zkratky, ktere
    uz v konfiguraci jsou, zustanou), stav spolecny pro vsechna okna (jako Unikey ve Windows), zapnuto
    hned, samotny levy Shift neprepina, fcitx5 nemeni rozlozeni XKB, bez doplnku s neocekavanymi zkratkami
    (k uz vypnutym doplnkum se pridaji)."""
    path = os.path.join(fcitx_dir(), "config")
    p = _read_ini(path)
    xcb = os.path.join(fcitx_dir(), "conf", "xcb.conf")
    if not p.has_section("Hotkey"):
        p.add_section("Hotkey")
    p["Hotkey"]["EnumerateWithTriggerKeys"] = "True"
    if not (p.has_section("Hotkey/TriggerKeys") and any(v for v in p["Hotkey/TriggerKeys"].values())):
        p["Hotkey/TriggerKeys"] = {"0": TRIGGER}
    if p.has_section("Hotkey/AltTriggerKeys"):
        p.remove_section("Hotkey/AltTriggerKeys")
    p["Hotkey/AltTriggerKeys"] = {}
    if not p.has_section("Behavior"):
        p.add_section("Behavior")
    p["Behavior"]["ShareInputState"] = "All"
    # po prihlaseni a po zapnuti rovnou vietnamsky (kdo metodu zapnul, chce psat vietnamsky; Ctrl+Mezernik
    # prepne na anglictinu) - jinak po kazdem prihlaseni nejdriv Ctrl+Mezernik
    p["Behavior"]["ActiveByDefault"] = "True"
    p["Behavior"]["ShowInputMethodInformation"] = "True"
    old = [v for v in (p["Behavior/DisabledAddons"].values() if p.has_section("Behavior/DisabledAddons") else []) if v]
    disabled = old + [a for a in DISABLED_ADDONS if a not in old]
    if p.has_section("Behavior/DisabledAddons"):
        p.remove_section("Behavior/DisabledAddons")
    p["Behavior/DisabledAddons"] = {str(i): a for i, a in enumerate(disabled)}
    _write_ini(p, path)
    _set_top_values(xcb, {"Allow Overriding System XKB Settings": "False"})


def write_style(s):
    _set_top_values(os.path.join(fcitx_dir(), "conf", "bamboo.conf"), {"InputMethod": s, "OutputCharset": "Unicode"})


# ---- bezici relace -----------------------------------------------------------------------
def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def xsettings(on):
    """Gtk/IMModule pro aplikace GTK spustene od ted (promenne prostredi plati az od dalsiho prihlaseni)."""
    xfconf = os.environ.get("LUXOS_IM_XFCONF") or shutil.which("xfconf-query")
    if not xfconf:
        return
    if on:
        _run([xfconf, "-c", "xsettings", "-p", "/Gtk/IMModule", "-n", "-t", "string", "-s", "fcitx"])
    else:
        _run([xfconf, "-c", "xsettings", "-p", "/Gtk/IMModule", "-r"])


def running():
    return _run(["pgrep", "-u", str(os.getuid()), "-x", "fcitx5"], 5) == 0


def stop():
    """Ukonci fcitx5 (pri ukonceni si ulozi konfiguraci - proto pred zapisem LuxOS nastaveni)."""
    if not running():
        return
    _run(["pkill", "-u", str(os.getuid()), "-x", "fcitx5"], 5)
    for _i in range(30):
        if not running():
            return
        time.sleep(0.1)
    _run(["pkill", "-KILL", "-u", str(os.getuid()), "-x", "fcitx5"], 5)


def start():
    exe = fcitx5_bin()
    if exe:
        # -d: fcitx5 se odpoji a puvodni proces hned skonci - pockat na nej (jinak zustane zombie)
        _run([exe, "-d"], 15)


def system_layouts():
    try:
        import luxos_keyboard as kb
        return kb.read_system()["layouts"]
    except Exception:   # noqa: BLE001 - bez systemoveho nastaveni US
        return [("us", "")]


def setup(lang, s=None):
    """Konfigurace fcitx5 od LuxOS (fcitx5 nesmi bezet). Nejdriv se zkontroluje, ze jdou precist
    vsechny stavajici soubory - jinak se nezapise nic."""
    _read_ini(os.path.join(fcitx_dir(), "config"))
    write_profile(lang, system_layouts())
    write_config()
    if lang == "vi":
        write_style(s or style())


def enable(lang="vi", s=None, live=True):
    if lang not in LANGS:
        raise ValueError(f"unknown input method: {lang}")
    if s is not None and s not in STYLES:
        raise ValueError(f"unknown typing style: {s}")
    s = s or style()
    c = read_choice()
    a = active()
    # k vlastnimu nastaveni fcitx5 uzivatele jen pridat metodu (jeho zkratky a doplnky zustanou)
    prev = "user" if a == "user" else (c.get("PREV", "") if a == lang else "")
    if live:
        stop()
    try:
        if prev == "user":
            write_profile(lang, system_layouts())
            if lang == "vi":
                write_style(s)
        else:
            setup(lang, s)
        write_choice({"IM": lang, "VI_STYLE": s, "PREV": prev})
    finally:
        if live and (prev == "user" or a in LANGS or read_choice().get("IM") == lang):
            start()
    if live:
        xsettings(True)


def disable(live=True):
    c = read_choice()
    if c.get("PREV") == "user":
        # zpet na vlastni nastaveni uzivatele: odebrat jen vietnamstinu, fcitx5 bezi dal
        if live:
            stop()
        try:
            remove_from_profile("vi")
            write_choice({"IM": "user", "VI_STYLE": c.get("VI_STYLE", "")})
        finally:
            if live:
                start()
        return
    write_choice({"IM": "none", "VI_STYLE": c.get("VI_STYLE", "")})
    if live:
        stop()
        xsettings(False)


def set_style(s, live=True):
    if s not in STYLES:
        raise ValueError(f"unknown typing style: {s}")
    if active() != "vi":
        raise ValueError("Vietnamese typing is not turned on")
    c = read_choice()
    if live:
        stop()
    try:
        write_style(s)
        c["IM"] = "vi"
        c["VI_STYLE"] = s
        write_choice(c)
    finally:
        if live:
            start()


def autostart():
    """Pri prihlaseni (xdg autostart): spustit fcitx5, jen kdyz ho uzivatel ma mit.
    Vraci argv pro exec, nebo None."""
    a = active()
    exe = fcitx5_bin()
    if a in LANGS and not available(a):
        xsettings(False)   # modul odinstalovany - aplikace GTK nemaji hledat fcitx5
        return None
    if not a or not exe:
        return None
    if a in LANGS:
        try:
            if not read_choice().get("IM"):
                # prvni prihlaseni s vietnamstinou (bez vlastniho profilu): vychozi nastaveni LuxOS
                setup(a)
                write_choice({"IM": a, "VI_STYLE": style()})
            elif not has_profile():
                setup(a)
        except (OSError, ValueError):
            pass   # konfiguraci nejde zapsat - fcitx5 i tak spustit se stavajici
        xsettings(True)
    return [exe]
