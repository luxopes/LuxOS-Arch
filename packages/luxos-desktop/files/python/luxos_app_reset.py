"""LuxOS - vychozi nastaveni aplikaci: seznam aplikaci s nastavenim v domovske slozce a jejich
"reset" presunem do zalohy (nikdy se nic nemaze).

Kde aplikace maji nastaveni a data:
  ~/.config/<jmeno>, ~/.local/share/<jmeno>, ~/.cache/<jmeno>   (XDG, vetsina aplikaci)
  ~/.var/app/<id>                                             (Flatpak: vse v jedne slozce)
  ~/.mozilla, ~/.thunderbird                                   (par znamych starsich slozek)

Reset presune vsechny slozky aplikace do ~/.local/share/luxos/app-settings-backups/
<RRRR-MM-DD_HH-MM-SS>-<jmeno>/ (config/, data/, cache/, home/, flatpak/ + manifest.json).
Aplikace pak startuje jako po instalaci; zaloha jde vratit (restore) nebo smazat rucne.

Nektere slozky se nenabizi nikdy (hesla v klicence, ucet LuxAI, kos, pisma, instalace Flatpak,
plocha Xfce a LuxOS, ...) - jejich "reset" by zpusobil vic skody nez uzitku.
"""
import datetime
import json
import os
import re
import shutil

BACKUP_SUB = "luxos/app-settings-backups"
NAME_FMT = "%Y-%m-%d_%H-%M-%S"
# Slozky, ktere se nikdy nenabizi (porovnava se normalizovane jmeno, viz norm())
PROTECTED = {
    # hesla, klice, ucty
    "keyrings", "gnupg", "pki", "luxai", "luxosaccount", "gnomekeyring", "ssh",
    # soubory uzivatele a systemove veci relace
    "trash", "recentlyusedxbel", "userdirsdirs", "userdirslocale", "mimeappslist", "autostart",
    "applications", "fonts", "icons", "themes", "sounds", "flatpak", "systemd", "pulse", "pipewire",
    "wireplumber", "dconf", "ibus", "fontconfig", "menus", "desktopdirectories", "environmentd",
    "gvfsmetadata", "tracker3", "xorg", "nautilus",
    # plocha (Xfce + LuxOS) - nastavuje se v Nastaveni, reset by rozbil listu a dock
    "xfce4", "xfconf", "xfce4session", "xfwm4", "thunar", "plank", "luxos", "lightdm", "gtk20", "gtk30",
    "gtk40", "kdeglobals", "qt5ct", "qt6ct", "rofi", "starship", "lsh", "blesh", "lux", "luxossandbox",
    # zalohy samotne a nastroje bez "aplikace"
    "backups", "mc", "nano", "vim", "nvim",
}
HOME_DOTDIRS = {".mozilla": "firefox", ".thunderbird": "thunderbird"}
# Zname aliasy slozek -> klic aplikace (normalizovane)
ALIASES = {"mozilla": "firefox", "code": "visualstudiocode", "codeoss": "visualstudiocode",
           "googlechrome": "googlechrome", "chromium": "chromium", "libreoffice": "libreoffice",
           "vlc": "vlc", "transmission": "transmission", "evince": "evince", "keepassxc": "keepassxc",
           "inkscape": "inkscape", "gimp": "gimp", "obsstudio": "obsstudio", "discord": "discord",
           "spotify": "spotify", "telegramdesktop": "telegramdesktop", "celluloid": "celluloid",
           "mousepad": "mousepad", "ristretto": "ristretto", "xarchiver": "xarchiver"}
DESKTOP_DIRS = ["/usr/share/applications", "/var/lib/flatpak/exports/share/applications"]


def norm(name):
    """Jmeno slozky/aplikace pro porovnani: mala pismena, jen pismena a cislice."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def home_dir():
    return os.environ.get("HOME") or os.path.expanduser("~")


def xdg(var, default):
    v = os.environ.get(var)
    return v if v and os.path.isabs(v) else os.path.join(home_dir(), default)


def roots():
    """(druh, slozka) mist s nastavenim aplikaci."""
    return [("config", xdg("XDG_CONFIG_HOME", ".config")), ("data", xdg("XDG_DATA_HOME", ".local/share")),
            ("cache", xdg("XDG_CACHE_HOME", ".cache"))]


def backup_root():
    return os.path.join(xdg("XDG_DATA_HOME", ".local/share"), BACKUP_SUB)


# ---- katalog aplikaci z .desktop ----------------------------------------------------------
def lang_codes():
    lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    lang = lang.split(".")[0].split("@")[0]
    out = []
    if lang and lang not in ("C", "POSIX"):
        out.append(lang)
        if "_" in lang:
            out.append(lang.split("_")[0])
    return out


def read_desktop(path):
    d = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            section = ""
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    section = line
                    continue
                if section != "[Desktop Entry]" or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d.setdefault(k.strip(), v.strip())
    except OSError:
        return None
    return d


def desktop_catalog(dirs=None):
    """{klic: {name, icon, id}} z .desktop souboru; klice: id, posledni cast reverzniho id,
    program z Exec, StartupWMClass."""
    dirs = dirs if dirs is not None else DESKTOP_DIRS + [os.path.join(xdg("XDG_DATA_HOME", ".local/share"), "applications"),
                                                       os.path.join(xdg("XDG_DATA_HOME", ".local/share"),
                                                                    "flatpak/exports/share/applications")]
    langs = lang_codes()
    cat = {}
    for d in dirs:
        try:
            files = sorted(os.listdir(d))
        except OSError:
            continue
        for f in files:
            if not f.endswith(".desktop"):
                continue
            e = read_desktop(os.path.join(d, f))
            if not e or e.get("Type", "Application") != "Application" or e.get("NoDisplay") == "true":
                continue
            name = next((e[f"Name[{c}]"] for c in langs if f"Name[{c}]" in e), e.get("Name", ""))
            if not name:
                continue
            ident = f[:-len(".desktop")]
            info = {"name": name, "icon": e.get("Icon", ""), "id": ident}
            keys = [ident, ident.split(".")[-1] if "." in ident else ident, e.get("StartupWMClass", "")]
            exe = (e.get("Exec") or "").split()
            if exe:
                prog = os.path.basename(exe[0])
                if prog in ("flatpak", "env") and len(exe) > 1:
                    prog = os.path.basename(next((x for x in exe[1:] if not x.startswith("-") and "=" not in x), prog))
                keys.append(prog)
            for k in keys:
                n = norm(k)
                if n and n not in cat:
                    cat[n] = info
    return cat


# ---- seznam --------------------------------------------------------------------------------
def size_of(path):
    total = 0
    if os.path.islink(path) or not os.path.isdir(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    for d, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return total


def scan(catalog=None, with_size=True):
    """Aplikace s nastavenim v domovske slozce -> [dict(key, name, icon, known, paths, size)],
    serazene podle nazvu. paths: [(druh, cesta)]."""
    catalog = desktop_catalog() if catalog is None else catalog
    apps = {}
    backups = os.path.realpath(backup_root())

    def add(key, kind, path, label):
        if norm(label) in PROTECTED or key in PROTECTED:
            return
        if os.path.realpath(path) == backups or backups.startswith(os.path.realpath(path) + os.sep):
            return
        info = catalog.get(key) or catalog.get(norm(label))
        a = apps.setdefault(key, {"key": key, "name": info["name"] if info else label,
                                  "icon": info["icon"] if info else "", "known": bool(info), "paths": [],
                                  "label": label})
        a["paths"].append((kind, path))

    for kind, root in roots():
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            p = os.path.join(root, n)
            if n.startswith(".") or not os.path.isdir(p) or os.path.islink(p):
                continue
            key = ALIASES.get(norm(n), norm(n))
            if not key:
                continue
            # cache bez nastaveni neni "aplikace s nastavenim"
            if kind == "cache" and key not in apps:
                continue
            add(key, kind, p, n)
    home = home_dir()
    for dot, key in HOME_DOTDIRS.items():
        p = os.path.join(home, dot)
        if os.path.isdir(p) and not os.path.islink(p):
            add(key, "home", p, dot[1:])
    fl = os.path.join(home, ".var", "app")
    try:
        ids = sorted(os.listdir(fl))
    except OSError:
        ids = []
    for ident in ids:
        p = os.path.join(fl, ident)
        if os.path.isdir(p):
            key = norm(ident)
            info = catalog.get(key)
            a = apps.setdefault(key, {"key": key, "name": info["name"] if info else ident,
                                      "icon": info["icon"] if info else "", "known": bool(info), "paths": [],
                                      "label": ident})
            a["paths"].append(("flatpak", p))
    out = list(apps.values())
    # cache pridana pred nastavenim (podle poradi slozek) - druha kontrola: jen cache = pryc
    out = [a for a in out if any(k != "cache" for k, _p in a["paths"])]
    if with_size:
        for a in out:
            a["size"] = sum(size_of(p) for _k, p in a["paths"])
    return sorted(out, key=lambda a: (not a["known"], a["name"].lower()))


def find(apps, query):
    """Aplikace podle klice, jmena slozky nebo nazvu (bez ohledu na velikost pismen)."""
    q = norm(query)
    for a in apps:
        if q in (a["key"], norm(a["label"]), norm(a["name"])):
            return a
    return None


# ---- bezici aplikace -----------------------------------------------------------------------
def running_programs(proc="/proc"):
    """Jmena beziciho programu uzivatele (comm a jmeno z cmdline), normalizovana."""
    out = set()
    uid = os.getuid()
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            if os.stat(os.path.join(proc, pid)).st_uid != uid:
                continue
            with open(os.path.join(proc, pid, "comm")) as f:
                out.add(norm(f.read().strip()))
            with open(os.path.join(proc, pid, "cmdline"), "rb") as f:
                arg0 = f.read().split(b"\0")[0].decode(errors="replace")
            if arg0:
                out.add(norm(os.path.basename(arg0)))
        except OSError:
            continue
    out.discard("")
    return out


def is_running(app, programs=None):
    programs = running_programs() if programs is None else programs
    keys = {app["key"], norm(app["label"])}
    if app["key"] == "firefox":
        keys.add("firefoxbin")
    return bool(keys & programs)


# ---- reset a obnova ------------------------------------------------------------------------
def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(src, dst)              # jiny souborovy system (napr. ~/.cache v tmpfs)


def reset(app, now=None):
    """Presune slozky aplikace do nove zalohy -> cesta k zaloze."""
    t = now or datetime.datetime.now()
    base = backup_root()
    os.makedirs(base, mode=0o700, exist_ok=True)
    name = f"{t.strftime(NAME_FMT)}-{app['key']}"
    dest = os.path.join(base, name)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(base, f"{name}-{n}")
    os.makedirs(dest, mode=0o700)
    manifest = {"app": app["name"], "key": app["key"], "time": t.strftime(NAME_FMT), "items": []}
    moved = []
    try:
        for i, (kind, path) in enumerate(app["paths"]):
            if not os.path.lexists(path):
                continue
            rel = f"{kind}/{os.path.basename(path)}"
            if os.path.lexists(os.path.join(dest, rel)):
                rel = f"{kind}/{i}-{os.path.basename(path)}"
            _move(path, os.path.join(dest, rel))
            moved.append((path, os.path.join(dest, rel)))
            manifest["items"].append({"kind": kind, "path": path, "backup": rel})
    except OSError:
        # nic napul: vratit, co uz se presunulo; zaloha zmizi jen kdyz je zase prazdna
        for orig, b in reversed(moved):
            try:
                _move(b, orig)
            except OSError:
                pass
        _remove_empty(dest)
        raise
    with open(os.path.join(dest, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    return dest


def list_backups():
    """Zalohy od nejnovejsi -> [dict(dir, app, key, time, items)]."""
    base = backup_root()
    out = []
    try:
        names = sorted(os.listdir(base), reverse=True)
    except OSError:
        return out
    for n in names:
        d = os.path.join(base, n)
        try:
            with open(os.path.join(d, "manifest.json")) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        m["dir"] = d
        out.append(m)
    return out


def restore(backup_dir, now=None):
    """Vrati zalohu na puvodni misto. Soucasne nastaveni (pokud mezitim vzniklo) se nejdriv
    presune do nove zalohy - opet se nic nemaze. -> cesta k zaloze soucasneho stavu nebo None."""
    with open(os.path.join(backup_dir, "manifest.json")) as f:
        m = json.load(f)
    base = os.path.realpath(backup_root())
    if not os.path.realpath(backup_dir).startswith(base + os.sep):
        raise ValueError("not a LuxOS app settings backup")
    current = [(it["kind"], it["path"]) for it in m["items"] if os.path.lexists(it["path"])]
    saved = None
    if current:
        saved = reset({"key": m["key"], "name": m["app"], "paths": current},
                      now=now or datetime.datetime.now())
    for it in m["items"]:
        src = os.path.join(backup_dir, it["backup"])
        if os.path.lexists(src):
            _move(src, it["path"])
    os.unlink(os.path.join(backup_dir, "manifest.json"))
    _remove_empty(backup_dir)
    return saved


def _remove_empty(top):
    """Smaze jen prazdne slozky (soubory nikdy)."""
    for d, _dirs, _files in os.walk(top, topdown=False):
        try:
            os.rmdir(d)
        except OSError:
            pass


def human_size(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"
