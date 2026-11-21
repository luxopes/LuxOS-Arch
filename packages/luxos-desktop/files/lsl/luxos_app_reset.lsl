# LuxOS - vychozi nastaveni aplikaci: seznam aplikaci s nastavenim v domovske slozce a jejich "reset"
# presunem do zalohy (nikdy se nic nemaze). Drive files/python/luxos_app_reset.py, stejne slozky i zalohy.
#
# Kde aplikace maji nastaveni a data:
#   ~/.config/<jmeno>, ~/.local/share/<jmeno>, ~/.cache/<jmeno>   (XDG, vetsina aplikaci)
#   ~/.var/app/<id>                                             (Flatpak: vse v jedne slozce)
#   ~/.mozilla, ~/.thunderbird                                   (par znamych starsich slozek)
#
# Reset presune vsechny slozky aplikace do ~/.local/share/luxos/app-settings-backups/
# <RRRR-MM-DD_HH-MM-SS>-<jmeno>/ (config/, data/, cache/, home/, flatpak/ + manifest.json). Aplikace pak
# startuje jako po instalaci; zaloha jde vratit (restore) nebo smazat rucne. Nektere slozky se nenabizi
# nikdy (hesla v klicence, ucet LuxAI, kos, pisma, instalace Flatpak, plocha Xfce a LuxOS, ...).
#   scan(s_velikosti) -> [{key, name, icon, known, paths: [[druh, cesta]], label, size}]
#   find(apps, dotaz), is_running(app, programy), running_programs()
#   reset(app) -> cesta zalohy (chyba: vyjimka, nic nezustane napul), list_backups(), restore(slozka)
# LUXOS_DESKTOP_DIRS (slozky oddelene ':') nahradi systemove slozky .desktop (testy).
load env, json
load luxos_glib, glib as glib
load luxos_sys as sys
load luxos_i18n as i18n
load luxos_text as text

BACKUP_SUB = "luxos/app-settings-backups"
NAME_FMT = "%Y-%m-%d_%H-%M-%S"
# Slozky, ktere se nikdy nenabizi (porovnava se normalizovane jmeno, viz norm())
PROTECTED = [
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
    "backups", "mc", "nano", "vim", "nvim"]
HOME_DOTDIRS = [[".mozilla", "firefox"], [".thunderbird", "thunderbird"]]
# Zname aliasy slozek -> klic aplikace (normalizovane)
ALIASES = {"mozilla": "firefox", "code": "visualstudiocode", "codeoss": "visualstudiocode",
    "googlechrome": "googlechrome", "chromium": "chromium", "libreoffice": "libreoffice",
    "vlc": "vlc", "transmission": "transmission", "evince": "evince", "keepassxc": "keepassxc",
    "inkscape": "inkscape", "gimp": "gimp", "obsstudio": "obsstudio", "discord": "discord",
    "spotify": "spotify", "telegramdesktop": "telegramdesktop", "celluloid": "celluloid",
    "mousepad": "mousepad", "ristretto": "ristretto", "xarchiver": "xarchiver"}
DESKTOP_DIRS = ["/usr/share/applications", "/var/lib/flatpak/exports/share/applications"]
S_IFMT = 61440
S_IFDIR = 16384
S_IFLNK = 40960

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

# Jmeno slozky/aplikace pro porovnani: mala pismena, jen pismena a cislice ASCII
function norm(name):
    out = ""
    for ch in name.lower():
        code = ord(ch)
        if (code >= 97 and code <= 122) or (code >= 48 and code <= 57):
            out += ch
        end
    end
    return out
end

function home_dir():
    home = env.get("HOME", "")
    if home == "":
        return glib.home_dir()
    end
    return home
end

function xdg(var, default):
    value = env.get(var, "")
    if value.startswith("/"):
        return value
    end
    return home_dir() + "/" + default
end

# [druh, slozka] mist s nastavenim aplikaci
function roots():
    return [["config", xdg("XDG_CONFIG_HOME", ".config")], ["data", xdg("XDG_DATA_HOME", ".local/share")],
        ["cache", xdg("XDG_CACHE_HOME", ".cache")]]
end

function backup_root():
    return xdg("XDG_DATA_HOME", ".local/share") + "/" + BACKUP_SUB
end

# ---- soubory (lstat: odkazy se nenasleduji) -----------------------------------------------------

# [typ (S_IFDIR, S_IFLNK, ...), velikost, uid] nebo [] kdyz cesta neni
function lstat(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        if __lsl_qbe_call2(__lsl_symbol("lstat"), cstr(path), base) != 0:
            return []
        end
        # struct stat x86_64: st_mode +24, st_uid +28, st_size +48
        return [__lsl_qbe_load32(base + 24) & S_IFMT, __lsl_qbe_load64(base + 48), __lsl_qbe_load32(base + 28)]
    end
end

function is_real_dir(path):
    info = lstat(path)
    return len(info) > 0 and info[0] == S_IFDIR
end

function lexists(path):
    return len(lstat(path)) > 0
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function dirname(path):
    cut = text.rfind(path, "/")
    if cut <= 0:
        return "/"
    end
    return path[:cut]
end

# Cesta bez ".", "..", "//" (os.path.normpath pro absolutni cesty)
function normpath(path):
    parts = []
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        end
        if part == "..":
            if len(parts) > 0:
                call parts.pop()
            end
            continue
        end
        parts.append(part)
    end
    return "/" + "/".join(parts)
end

function realpath(path):
    real = glib.realpath(path)
    if real == "":
        return normpath(path)
    end
    return real
end

function size_of(path):
    info = lstat(path)
    if len(info) == 0:
        return 0
    end
    if info[0] != S_IFDIR:
        return info[1]
    end
    total = 0
    for name in glib.list_dir(path):
        total += size_of(path + "/" + name)
    end
    return total
end

# ---- katalog aplikaci z .desktop ----------------------------------------------------------

function lang_codes():
    lang = env.get("LC_ALL", "")
    if lang == "":
        lang = env.get("LC_MESSAGES", "")
    end
    if lang == "":
        lang = env.get("LANG", "")
    end
    lang = lang.split(".")[0].split("@")[0]
    out = []
    if lang != "" and lang != "C" and lang != "POSIX":
        out.append(lang)
        if lang.find("_") >= 0:
            out.append(lang.split("_")[0])
        end
    end
    return out
end

function read_desktop(path):
    d = {}
    section = ""
    for raw in glib.read_text(path).split("\n"):
        line = raw.strip()
        if line.startswith("["):
            section = line
            continue
        end
        cut = line.find("=")
        if section != "[Desktop Entry]" or cut < 0:
            continue
        end
        key = line[:cut].strip()
        if not (key in d):
            d[key] = line[cut + 1:].strip()
        end
    end
    return d
end

function desktop_dirs():
    data = xdg("XDG_DATA_HOME", ".local/share")
    system = DESKTOP_DIRS
    if env.get("LUXOS_DESKTOP_DIRS", "") != "":
        system = env.get("LUXOS_DESKTOP_DIRS", "").split(":")
    end
    return system + [data + "/applications", data + "/flatpak/exports/share/applications"]
end

# {klic: {name, icon, id}} z .desktop souboru; klice: id, posledni cast reverzniho id, program z Exec,
# StartupWMClass
function desktop_catalog():
    langs = lang_codes()
    cat = {}
    for d in desktop_dirs():
        for f in glib.list_dir(d):
            if not f.endswith(".desktop"):
                continue
            end
            e = read_desktop(d + "/" + f)
            if len(e) == 0 or e.get("Type", "Application") != "Application" or e.get("NoDisplay", "") == "true":
                continue
            end
            name = e.get("Name", "")
            for c in langs:
                if ("Name[" + c + "]") in e:
                    name = e["Name[" + c + "]"]
                    break
                end
            end
            if name == "":
                continue
            end
            ident = f[:len(f) - 8]
            info = {"name": name, "icon": e.get("Icon", ""), "id": ident}
            keys = [ident, ident[text.rfind(ident, ".") + 1:], e.get("StartupWMClass", "")]
            exe = [x for x in e.get("Exec", "").split(" ") if x != ""]
            if len(exe) > 0:
                prog = basename(exe[0])
                if (prog == "flatpak" or prog == "env") and len(exe) > 1:
                    for x in exe[1:]:
                        if not x.startswith("-") and x.find("=") < 0:
                            prog = basename(x)
                            break
                        end
                    end
                end
                keys.append(prog)
            end
            for k in keys:
                n = norm(k)
                if n != "" and not (n in cat):
                    cat[n] = info
                end
            end
        end
    end
    return cat
end

# ---- seznam --------------------------------------------------------------------------------

function new_app(key, label, info):
    if info == None:
        return {"key": key, "name": label, "icon": "", "known": False, "paths": [], "label": label}
    end
    return {"key": key, "name": info["name"], "icon": info["icon"], "known": True, "paths": [], "label": label}
end

function add_path(apps, order, catalog, backups, key, kind, path, label):
    if norm(label) in PROTECTED or key in PROTECTED:
        return 0
    end
    real = realpath(path)
    if real == backups or backups.startswith(real + "/"):
        return 0
    end
    if not (key in apps):
        info = catalog.get(key)
        if info == None:
            info = catalog.get(norm(label))
        end
        apps[key] = new_app(key, label, info)
        order.append(key)
    end
    apps[key]["paths"].append([kind, path])
end

# Aplikace s nastavenim v domovske slozce, zname pred ostatnimi, podle nazvu
function scan(with_size):
    catalog = desktop_catalog()
    apps = {}
    order = []
    backups = realpath(backup_root())
    for root in roots():
        for n in glib.list_dir(root[1]):
            p = root[1] + "/" + n
            if n.startswith(".") or not is_real_dir(p):
                continue
            end
            key = ALIASES.get(norm(n), norm(n))
            if key == "":
                continue
            end
            # cache bez nastaveni neni "aplikace s nastavenim"
            if root[0] == "cache" and not (key in apps):
                continue
            end
            call add_path(apps, order, catalog, backups, key, root[0], p, n)
        end
    end
    home = home_dir()
    for item in HOME_DOTDIRS:
        p = home + "/" + item[0]
        if is_real_dir(p):
            call add_path(apps, order, catalog, backups, item[1], "home", p, item[0][1:])
        end
    end
    flatpaks = home + "/.var/app"
    for ident in glib.list_dir(flatpaks):
        p = flatpaks + "/" + ident
        if glib.is_dir(p):
            key = norm(ident)
            if not (key in apps):
                apps[key] = new_app(key, ident, catalog.get(key))
                order.append(key)
            end
            apps[key]["paths"].append(["flatpak", p])
        end
    end
    keyed = []
    for key in order:
        a = apps[key]
        if len([p for p in a["paths"] if p[0] != "cache"]) == 0:
            continue
        end
        if with_size:
            a["size"] = sum([size_of(p[1]) for p in a["paths"]])
        end
        keyed.append(("0" if a["known"] else "1") + a["name"].lower() + "\t" + key)
    end
    return [apps[k[k.find("\t") + 1:]] for k in sorted(keyed)]
end

# Aplikace podle klice, jmena slozky nebo nazvu (bez ohledu na velikost pismen)
function find(apps, query):
    q = norm(query)
    for a in apps:
        if q == a["key"] or q == norm(a["label"]) or q == norm(a["name"]):
            return a
        end
    end
    return None
end

# ---- bezici aplikace -----------------------------------------------------------------------

# Prvni retezec ze souboru (cmdline: argumenty oddelene nulou)
function first_string(path):
    unsafe:
        fd = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("open"), cstr(path), 0))
        if fd < 0:
            return ""
        end
        buffer = __lsl_byte_zeros(4097)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        call __lsl_qbe_call3(__lsl_symbol("read"), fd, base, 4096)
        call __lsl_qbe_call1(__lsl_symbol("close"), fd)
        return glib.from_c(base)
    end
end

# Jmena bezicich programu uzivatele (comm a jmeno z cmdline), normalizovana
function running_programs():
    out = []
    uid = sys.getuid()
    for pid in glib.list_dir("/proc"):
        if not text.is_digits(pid):
            continue
        end
        info = lstat("/proc/" + pid)
        if len(info) == 0 or info[2] != uid:
            continue
        end
        for name in [first_string("/proc/" + pid + "/comm").strip(), basename(first_string("/proc/" + pid + "/cmdline"))]:
            n = norm(name)
            if n != "" and not (n in out):
                out.append(n)
            end
        end
    end
    return out
end

function is_running(app, programs):
    keys = [app["key"], norm(app["label"])]
    if app["key"] == "firefox":
        keys.append("firefoxbin")
    end
    for k in keys:
        if k in programs:
            return True
        end
    end
    return False
end

# ---- reset a obnova ------------------------------------------------------------------------

# Presun slozky; na jiny souborovy system (napr. ~/.cache v tmpfs) pres mv. Chyba = vyjimka.
function move(source, target):
    call glib.mkdir_p(dirname(target))
    if glib.rename(source, target):
        return 0
    end
    if glib.spawn_sync_quiet(["mv", "--", source, target]) != 0:
        Error(OSError: "cannot move " + source + " to " + target)
    end
end

function mkdir_private(path):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(path), 448) == 0
    end
end

# Zapis s fsync: bez manifestu by zaloha nebyla v seznamu k obnoveni (plny disk)
function write_synced(path, content):
    ok = False
    unsafe:
        # O_WRONLY | O_CREAT | O_TRUNC
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("open"), cstr(path), 1 | 64 | 512, 384))
        if fd >= 0:
            size = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(content))
            written = __lsl_qbe_call3(__lsl_symbol("write"), fd, cstr(content), size)
            synced = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("fsync"), fd))
            closed = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("close"), fd))
            ok = written == size and synced == 0 and closed == 0
        end
    end
    if not ok:
        Error(OSError: "cannot write " + path)
    end
end

# Presune slozky aplikace do nove zalohy -> cesta k zaloze
function reset(app):
    stamp = sys.strftime_local(NAME_FMT)
    base = backup_root()
    call glib.mkdir_p(dirname(base))
    call mkdir_private(base)
    name = stamp + "-" + app["key"]
    dest = base + "/" + name
    n = 1
    while lexists(dest):
        n += 1
        dest = base + "/" + name + "-" + String(n)
    end
    if not mkdir_private(dest):
        Error(OSError: "cannot create " + dest)
    end
    manifest = {"app": app["name"], "key": app["key"], "time": stamp, "items": []}
    moved = []
    failed = ""
    try:
        for i in range(len(app["paths"])):
            kind = app["paths"][i][0]
            path = app["paths"][i][1]
            if not lexists(path):
                continue
            end
            rel = kind + "/" + basename(path)
            if lexists(dest + "/" + rel):
                rel = kind + "/" + String(i) + "-" + basename(path)
            end
            call move(path, dest + "/" + rel)
            moved.append([path, dest + "/" + rel])
            manifest["items"].append({"kind": kind, "path": path, "backup": rel})
        end
        call write_synced(dest + "/manifest.json.tmp", json.encode(manifest))
        if not glib.rename(dest + "/manifest.json.tmp", dest + "/manifest.json"):
            Error(OSError: "cannot write " + dest + "/manifest.json")
        end
    else:
        failed = reason(last_error())
    end
    if failed != "":
        # nic napul: vratit, co uz se presunulo; zaloha zmizi jen kdyz je zase prazdna
        for i in range(len(moved)):
            item = moved[len(moved) - 1 - i]
            try:
                call move(item[1], item[0])
            else:
                call eprint("luxos-app-reset: " + String(last_error()))
            end
        end
        call glib.unlink(dest + "/manifest.json.tmp")
        call remove_empty(dest)
        Error(OSError: failed)
    end
    return dest
end

# Text chyby bez typu ("OSError: cannot move ..." -> "cannot move ...")
function reason(error):
    message = String(error)
    for prefix in ["OSError: ", "ValueError: ", "FileError: ", "JSONError: "]:
        if message.startswith(prefix):
            return message[len(prefix):]
        end
    end
    return message
end

# Zalohy od nejnovejsi -> [{dir, app, key, time, items}]
function list_backups():
    base = backup_root()
    out = []
    names = glib.list_dir(base)
    for i in range(len(names)):
        d = base + "/" + names[len(names) - 1 - i]
        m = None
        try:
            m = json.decode(readfile(d + "/manifest.json"))
        else:
            m = None
        end
        if type(m) == "Dictionary":
            m["dir"] = d
            out.append(m)
        end
    end
    return out
end

# Polozka manifestu ukazuje jen tam, kam ji reset mohl vzit: primo do slozky s nastavenim (config, data,
# cache, ~/.var/app, domovska slozka) a zaloha je uvnitr slozky zalohy
function item_ok(it):
    if type(it) != "Dictionary" or type(it.get("path")) != "String" or type(it.get("backup")) != "String" or type(it.get("kind")) != "String":
        return False
    end
    path = it["path"]
    rel = it["backup"]
    if not path.startswith("/") or normpath(path) != path or basename(path) == "":
        return False
    end
    home = normpath(home_dir())
    parents = [home, home + "/.var/app"] + [normpath(r[1]) for r in roots()]
    if not (dirname(path) in parents):
        return False
    end
    backups = normpath(backup_root())
    if path == backups or backups.startswith(path + "/"):
        return False
    end
    if rel.startswith("/") or rel.startswith("..") or rel == "":
        return False
    end
    return normpath("/" + rel) == "/" + rel
end

# Vrati zalohu na puvodni misto. Soucasne nastaveni (pokud mezitim vzniklo) se nejdriv presune do nove
# zalohy - opet se nic nemaze. -> cesta k zaloze soucasneho stavu nebo ""
function restore(backup_dir):
    m = json.decode(readfile(backup_dir + "/manifest.json"))
    base = realpath(backup_root())
    if not realpath(backup_dir).startswith(base + "/"):
        Error(ValueError: "not a LuxOS app settings backup")
    end
    # upraveny nebo poskozeny manifest: nic nepresouvat
    if type(m) != "Dictionary" or type(m.get("items")) != "List" or len([it for it in m["items"] if not item_ok(it)]) > 0:
        Error(ValueError: "invalid LuxOS app settings backup")
    end
    current = [[it["kind"], it["path"]] for it in m["items"] if lexists(it["path"])]
    saved = ""
    if len(current) > 0:
        saved = reset({"key": String(m.get("key", "")), "name": String(m.get("app", "")), "paths": current})
    end
    for it in m["items"]:
        source = backup_dir + "/" + it["backup"]
        if lexists(source):
            call move(source, it["path"])
        end
    end
    call glib.unlink(backup_dir + "/manifest.json")
    call remove_empty(backup_dir)
    return saved
end

# Smaze jen prazdne slozky (soubory nikdy)
function remove_empty(top):
    if not is_real_dir(top):
        return 0
    end
    for name in glib.list_dir(top):
        call remove_empty(top + "/" + name)
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("rmdir"), cstr(top))
    end
end

function one_decimal(value):
    tenths = Int(value * 10 + 0.5)
    return i18n.decimal(String(tenths // 10) + "." + String(tenths % 10))
end

function human_size(n):
    value = Float(n)
    for unit in ["B", "kB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            if unit == "B":
                return String(Int(value)) + " B"
            end
            return one_decimal(value) + " " + unit
        end
        value = value / 1024.0
    end
end
