# LuxOS - lux-alpm: jadro spravce baliku lux v LSL (nahrada /usr/lib/lux/lux_alpm.py a pyalpm).
#
# Stejne rozhrani jako lux_alpm.py (lux, Obchod a Aktualizace ho volaji primo):
#   lux-alpm [-v] [--machine] [--color auto|always|never] [--lang JAZYK] [--datasaver] PRIKAZ ...
# Hotovo: prikazy jen pro cteni (search, info, list, files, owns, resolve), available a check-updates
# (obnova databazi do docasne kopie jako checkupdates). Vystup je znak po znaku stejny jako u Python
# verze; parity.sh ho porovnava na zivem systemu. Transakce (install/remove/upgrade, sync, clean) chybi.
# Konfiguraci jadra zatim bere z `lux-config dump` (syntaxe pacman.conf); lux_config.py prijde na radu
# v dalsi fazi.
load env
load glib
load luxalpm as alpm
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_glib as lglib
load process
load luxfs as fs

EXIT_UNAVAILABLE = 3
DEFAULT_DBPATH = "/var/lib/lux/"
DEFAULT_CACHEDIR = "/var/cache/lux/pkg/"
LUX_CONFIG = "/usr/lib/lux/lux-config"
ENGINE_DEFAULTS = [["RootDir", "/"], ["DBPath", DEFAULT_DBPATH], ["CacheDir", DEFAULT_CACHEDIR],
                   ["HookDir", "/etc/lux/hooks/"], ["GPGDir", "/etc/lux/keyring/"], ["LogFile", "/var/log/lux.log"]]
PKG_SUFFIXES = [".pkg.tar", ".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar.bz2", ".pkg.tar.lz4",
                ".pkg.tar.lzo", ".pkg.tar.lrz", ".pkg.tar.Z"]

DETAIL_LINES = 6
ui = {"machine": False, "tty": False, "color": False, "verbose": False}
lux = {"h": 0, "conf": None}

# ---- chyby ----

function LuxError(kind, message, rc=1, details=None):
    return {"lux_error": True, "kind": kind, "message": message, "rc": rc, "details": details if details != None else []}
end

function _(text):
    return i18n.T(text)
end

# ---- vystup (UI z lux_alpm.py) ----

function c(code, text):
    if ui["color"]:
        return chr(27) + "[" + code + "m" + text + chr(27) + "[0m"
    end
    return text
end

function bold(t):
    return c("1", t)
end

function dim(t):
    return c("2", t)
end

function accent(t):
    return c("38;2;167;123;255", t)
end

function green(t):
    return c("32", t)
end

function yellow(t):
    return c("33", t)
end

function red(t):
    return c("31", t)
end

function write(text, err=False):
    if err and not ui["machine"]:
        call sys.eprint(text)
    else:
        print text
    end
    return 0
end

function fail(text):
    if not ui["machine"]:
        call write(red("✗") + " " + text, True)
    end
    return 0
end

function emit(parts):
    if ui["machine"]:
        print "@@" + " ".join([String(p) for p in parts])
    end
    return 0
end

function compat(text):
    if ui["machine"]:
        print text
    end
    return 0
end

function isatty(fd):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("isatty"), sys.ptr(fd))) == 1
    end
end

# ---- formatovani ----

function lang():
    return i18n.lang()
end

function decimal(text):
    if lang() in ["en", "C", "POSIX"]:
        return text
    end
    return text.replace(".", ",")
end

# Jedno desetinne misto jako Pythonove f"{v:.1f}" (zaokrouhleni pulky nahoru staci: velikosti nejsou na hrane)
function one_decimal(v):
    tenths = Int(v * 10.0 + 0.5)
    return String(tenths // 10) + "." + String(tenths % 10)
end

function fmt_size(n):
    n = abs(Int(n))
    for unit in [["GB", 1000000000.0], ["MB", 1000000.0], ["kB", 1000.0]]:
        if Float(n) >= unit[1]:
            v = Float(n) / unit[1]
            s = one_decimal(v) if v < 100.0 else String(Int(v + 0.5))
            if s.endswith(".0"):
                s = s[0:len(s) - 2]
            end
            return decimal(s) + " " + unit[0]
        end
    end
    return String(n) + " B"
end

function strftime(format, timestamp):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("setlocale"), 6, sys.cstr(""))
        t = __lsl_byte_zeros(8)
        call __lsl_qbe_store64(sys.data(t), sys.ptr(timestamp))
        tm = __lsl_byte_zeros(64)
        call __lsl_qbe_call2(__lsl_symbol("localtime_r"), sys.data(t), sys.data(tm))
        out = __lsl_byte_zeros(256)
        n = __lsl_qbe_call4(__lsl_symbol("strftime"), sys.data(out), 256, sys.cstr(format), sys.data(tm))
        return __lsl_text_from_bytes(out, 0, n)
    end
end

function fmt_list(values):
    if len(values) == 0:
        return "-"
    end
    return "  ".join(values)
end

function repo_badge(repo):
    if repo == "luxos-apps":
        return accent("✦ LuxOS")
    end
    if repo.startswith("luxos"):
        return accent("✦ " + repo)
    end
    return dim(repo)
end

# ---- konfigurace jadra (EngineConf) ----

# Text v syntaxi pacman.conf -> {"options": {klic: [hodnoty]}, "repos": [{"name", klic: [hodnoty]}]}
function parse_engine_conf(text):
    options = {}
    repos = []
    cur = options
    for raw in text.split(chr(10)):
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        end
        if line.startswith("[") and line.endswith("]"):
            name = line[1:len(line) - 1].strip()
            if name == "options":
                cur = options
            else:
                cur = {"name": name}
                repos.append(cur)
            end
            continue
        end
        eq = line.find("=")
        key = line
        value = None
        if eq >= 0:
            key = line[0:eq].strip()
            value = line[eq + 1:].strip()
        end
        if not (key in cur):
            cur[key] = []
        end
        if value != None:
            cur[key].append(value)
        end
    end
    for d in ENGINE_DEFAULTS:
        if not (d[0] in options):
            options[d[0]] = [d[1]]
        end
    end
    return {"options": options, "repos": repos}
end

function conf_get(conf, key, default_value):
    values = conf["options"].get(key, [])
    if len(values) == 0:
        return default_value
    end
    return values[len(values) - 1]
end

# Opakovatelna volba, hodnoty oddelene mezerami (HoldPkg = lux-engine glibc)
function conf_list(conf, key):
    out = []
    for v in conf["options"].get(key, []):
        for w in v.split(" "):
            if w != "":
                out.append(w)
            end
        end
    end
    return out
end

function load_engine_conf():
    path = env.get("LUX_ENGINE_CONF", "")
    if path != "":
        r = process_capture(["lux-engine-conf", "--config", path])
    else:
        r = process_capture([LUX_CONFIG, "dump"])
    end
    if r[0] != 0:
        Error(LuxConfigError: r[2].strip())
    end
    return parse_engine_conf(r[1])
end

# [rc, stdout, stderr]
function process_capture(argv):
    res = None
    try:
        res = process.capture_result(argv[0], argv[1:])
    else:
        return [127, "", String(last_error())]
    end
    return [res["status"], res["stdout"], res["stderr"]]
end

function unsetenv(name):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("unsetenv"), sys.cstr(name)) == 0
    end
end

function is_link(path):
    return lglib.readlink(path) != ""
end

function is_file(path):
    return exists(path) and not lglib.is_dir(path)
end

# Usage repozitare (Sync/Search/Install/Upgrade/All) -> seznam
function usage_mask(tokens):
    words = []
    for t in tokens:
        for w in t.split(" "):
            if w != "":
                words.append(w)
            end
        end
    end
    if len(words) == 0 or "All" in words:
        return ["Sync", "Search", "Install", "Upgrade"]
    end
    return words
end

SIG_BITS = {"P": alpm.SIG_PACKAGE, "PO": alpm.SIG_PACKAGE_OPTIONAL, "PM": alpm.SIG_PACKAGE_MARGINAL_OK,
            "PU": alpm.SIG_PACKAGE_UNKNOWN_OK, "D": alpm.SIG_DATABASE, "DO": alpm.SIG_DATABASE_OPTIONAL,
            "DM": alpm.SIG_DATABASE_MARGINAL_OK, "DU": alpm.SIG_DATABASE_UNKNOWN_OK}

function bit_set(level, bit):
    if level & bit == 0:
        return level + bit
    end
    return level
end

function bit_clear(level, bit):
    if level & bit != 0:
        return level - bit
    end
    return level
end

# SigLevel jako pacman (conf.c process_siglevel); base = globalni SigLevel
function parse_siglevel(tokens, base):
    level = base
    if level == None:
        level = SIG_BITS["P"] + SIG_BITS["PO"] + SIG_BITS["D"] + SIG_BITS["DO"]
    end
    for tok in tokens:
        for word in tok.split(" "):
            if word == "":
                continue
            end
            parts = ["P", "D"]
            if word.startswith("Package"):
                parts = ["P"]
                word = word[7:]
            elif word.startswith("Database"):
                parts = ["D"]
                word = word[8:]
            end
            for pre in parts:
                if word == "Never":
                    level = bit_clear(level, SIG_BITS[pre])
                elif word == "Optional":
                    level = bit_set(bit_set(level, SIG_BITS[pre]), SIG_BITS[pre + "O"])
                elif word == "Required":
                    level = bit_clear(bit_set(level, SIG_BITS[pre]), SIG_BITS[pre + "O"])
                elif word == "TrustedOnly":
                    level = bit_clear(bit_clear(level, SIG_BITS[pre + "M"]), SIG_BITS[pre + "U"])
                elif word == "TrustAll":
                    level = bit_set(bit_set(level, SIG_BITS[pre + "M"]), SIG_BITS[pre + "U"])
                else:
                    Error(LuxConfigError: "invalid SigLevel value: " + word)
                end
            end
        end
    end
    return level
end

function machine_arch():
    return fs.machine()
end

# Handle libalpm nastaveny jako jadro (build_handle v lux_alpm.py); jen to, co potrebuji cteci prikazy
function build_handle(conf):
    root = conf_get(conf, "RootDir", "/")
    dbpath = conf_get(conf, "DBPath", DEFAULT_DBPATH)
    h = alpm.initialize(root, dbpath)
    if h == 0:
        Error(LuxConfigError: alpm.last_error(0))
    end
    archs = []
    for a in conf_list(conf, "Architecture"):
        archs.append(machine_arch() if a == "auto" else a)
    end
    if len(archs) == 0:
        archs = [machine_arch()]
    end
    for a in archs:
        call alpm.add_architecture(h, a)
    end
    for dir in conf_list(conf, "CacheDir"):
        call alpm.add_cachedir(h, dir)
    end
    for p in conf_list(conf, "IgnorePkg"):
        call alpm.add_ignorepkg(h, p)
    end
    for g in conf_list(conf, "IgnoreGroup"):
        call alpm.add_ignoregroup(h, g)
    end
    # bez GPGDir libalpm neovezi podpis databaze a podepsane repozitare (luxos) zustanou prazdne
    call alpm.set_gpgdir(h, conf_get(conf, "GPGDir", "/etc/lux/keyring/"))
    call alpm.set_logfile(h, conf_get(conf, "LogFile", "/var/log/lux.log"))
    base = parse_siglevel(conf_list(conf, "SigLevel"), None)
    call alpm.set_default_siglevel(h, base)
    for repo in conf["repos"]:
        db = alpm.register_syncdb(h, repo["name"], parse_siglevel(repo.get("SigLevel", []), base))
        for server in repo.get("Server", []):
            call alpm.db_add_server(db, server.replace("$repo", repo["name"]).replace("$arch", archs[0]))
        end
        repo["_usage"] = usage_mask(repo.get("Usage", []))
    end
    return h
end

function h():
    if lux["h"] == 0:
        lux["conf"] = load_engine_conf()
        lux["h"] = build_handle(lux["conf"])
    end
    return lux["h"]
end

function localdb():
    return alpm.localdb(h())
end

function syncdbs(usage=None):
    dbs = alpm.syncdbs(h())
    if usage == None:
        return dbs
    end
    allowed = []
    for r in lux["conf"]["repos"]:
        if usage in r.get("_usage", ["Sync", "Search", "Install", "Upgrade"]):
            allowed.append(r["name"])
        end
    end
    return [d for d in dbs if alpm.db_name(d) in allowed]
end

# Balicky pro cil: nazev, repo/nazev, skupina nebo provides (poradi repozitaru jako pacman)
function find_sync(target, usage="Install"):
    dbs = syncdbs(usage)
    slash = target.find("/")
    if slash > 0:
        repo = target[0:slash]
        name = target[slash + 1:]
        for db in dbs:
            if alpm.db_name(db) == repo:
                p = alpm.db_get_pkg(db, name)
                return [p] if p != 0 else []
            end
        end
        return []
    end
    for db in dbs:
        p = alpm.db_get_pkg(db, target)
        if p != 0:
            return [p]
        end
    end
    plain = True
    for ch in ["<", ">", "="]:
        if ch in target:
            plain = False
        end
    end
    if plain:
        for db in dbs:
            grp = alpm.db_group_pkgs(db, target)
            if len(grp) > 0:
                return grp
            end
        end
    end
    for db in dbs:
        p = alpm.find_satisfier(h(), [db], target)
        if p != 0:
            return [p]
        end
    end
    return []
end

# ---- vzory vyhledavani (lux_community.py: is_pattern, search_pattern, pattern_literal) ----

function is_pattern(term):
    if term == "":
        return False
    end
    if term[0] == "^" or term[len(term) - 1] == "$":
        return True
    end
    for ch in ["*", "?", "%"]:
        if ch in term:
            return True
        end
    end
    return False
end

# Glob s * a ? nad celym textem (bez ohledu na velikost pismen); backtracking pres posledni *
function glob_match(pattern, text):
    p = 0
    t = 0
    star = -1
    mark = 0
    while t < len(text):
        if p < len(pattern) and (pattern[p] == "?" or pattern[p] == text[t]):
            p += 1
            t += 1
        elif p < len(pattern) and pattern[p] == "*":
            star = p
            mark = t
            p += 1
        elif star >= 0:
            p = star + 1
            mark += 1
            t = mark
        else:
            return False
        end
    end
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    end
    return p == len(pattern)
end

# Odpovida nazev vzoru? (search_pattern(term).search(name))
function pattern_match(term, name):
    t = term.replace("%", "*").lower()
    n = name.lower()
    start = t.startswith("^")
    if start:
        t = t[1:]
    end
    stop = t.endswith("$")
    if stop:
        t = t[0:len(t) - 1]
    end
    if "*" in t or "?" in t:
        return glob_match(t, n)
    end
    if start and stop:
        return n == t
    elif start:
        return n.startswith(t)
    elif stop:
        return n.endswith(t)
    end
    return t in n
end

function pattern_literal(term):
    t = term.replace("%", "*")
    if t.startswith("^"):
        t = t[1:]
    end
    if t.endswith("$"):
        t = t[0:len(t) - 1]
    end
    best = ""
    cur = ""
    for ch in t:
        if ch == "*" or ch == "?":
            if len(cur) > len(best):
                best = cur
            end
            cur = ""
        else:
            cur = cur + ch
        end
    end
    if len(cur) > len(best):
        best = cur
    end
    return best
end

function search_literal(terms):
    best = ""
    for t in terms:
        if is_pattern(t):
            lit = pattern_literal(t)
            if len(lit) > len(best):
                best = lit
            end
        end
    end
    return best
end

# ---- prikazy ----

function cmd_search(args):
    installed_only = args["installed"]
    terms = args["terms"]
    local = localdb()
    plain = [t for t in terms if not is_pattern(t)]
    patterns = [t for t in terms if is_pattern(t)]
    sdbs = syncdbs("Search")
    seen = {}
    rows = []
    for db in ([local] if installed_only else sdbs):
        res = alpm.db_search(db, plain) if len(plain) > 0 else alpm.db_pkgcache(db)
        dbname = alpm.db_name(db)
        for p in res:
            name = alpm.pkg_name(p)
            key = dbname + "/" + name
            if key in seen:
                continue
            end
            ok = True
            for pat in patterns:
                if not pattern_match(pat, name):
                    ok = False
                end
            end
            if not ok:
                continue
            end
            seen[key] = True
            rows.append([dbname, p, name])
        end
    end
    q = (" ".join(plain) if len(plain) > 0 else search_literal(terms)).lower()
    # stabilni razeni jako Python sort(key=(nazev != q, not nazev.startswith(q))): presna shoda, pak zacatek
    ordered = []
    for rank in [0, 1, 2]:
        for r in rows:
            n = r[2].lower()
            rr = 0 if n == q else (1 if n.startswith(q) else 2)
            if rr == rank:
                ordered.append(r)
            end
        end
    end
    if len(ordered) == 0:
        return 1
    end
    for r in ordered:
        repo = r[0]
        p = r[1]
        if installed_only:
            repo = "local"
            for d in sdbs:
                if alpm.db_get_pkg(d, r[2]) != 0:
                    repo = alpm.db_name(d)
                    break
                end
            end
            inst = p
        else:
            inst = alpm.db_get_pkg(local, r[2])
        end
        version = alpm.pkg_version(p)
        mark = ""
        if inst != 0:
            if alpm.pkg_version(inst) == version:
                mark = " " + green("● " + _("installed"))
            else:
                mark = " " + yellow("● " + _("installed") + " " + alpm.pkg_version(inst))
            end
        end
        if ui["tty"] or ui["color"]:
            call write(bold(r[2]) + " " + green(version) + " " + repo_badge(repo) + mark)
        else:
            call write(repo + "/" + r[2] + " " + version + (" [installed]" if inst != 0 else ""))
        end
        call write("    " + alpm.pkg_desc(p))
    end
    return 0
end

function cmd_info(args):
    local = alpm.db_get_pkg(localdb(), args["package"])
    pkg = local
    if pkg == 0 or args["sync"]:
        found = find_sync(args["package"], "Search")
        if len(found) > 0:
            pkg = found[0]
        end
    end
    if pkg == 0:
        return 1
    end
    is_local = pkg == local
    repo = "-"
    db = alpm.pkg_db(pkg)
    if db != 0:
        repo = alpm.db_name(db)
    end
    if is_local:
        repo = _("not in repositories (AUR or local)")
        for d in syncdbs():
            if alpm.db_get_pkg(d, alpm.pkg_name(pkg)) != 0:
                repo = alpm.db_name(d)
                break
            end
        end
    end
    rows = [[_("Name"), bold(alpm.pkg_name(pkg))], [_("Version"), green(alpm.pkg_version(pkg))],
            [_("Description"), alpm.pkg_desc(pkg)], [_("Repository"), repo], [_("URL"), alpm.pkg_url(pkg)],
            [_("License"), fmt_list(alpm.pkg_licenses(pkg))], [_("Groups"), fmt_list(alpm.pkg_groups(pkg))],
            [_("Provides"), fmt_list(alpm.pkg_provides(pkg))], [_("Depends on"), fmt_list(alpm.pkg_depends(pkg))],
            [_("Optional deps"), fmt_list(alpm.pkg_optdepends(pkg))],
            [_("Conflicts with"), fmt_list(alpm.pkg_conflicts(pkg))], [_("Replaces"), fmt_list(alpm.pkg_replaces(pkg))]]
    if is_local:
        rows.append([_("Required by"), fmt_list(alpm.pkg_requiredby(pkg))])
        rows.append([_("Installed size"), fmt_size(alpm.pkg_isize(pkg))])
        when = alpm.pkg_installdate(pkg)
        rows.append([_("Installed"), strftime("%Y-%m-%d %H:%M", when) if when != 0 else "-"])
        rows.append([_("Install reason"), _("explicitly installed") if alpm.pkg_reason(pkg) == 0 else _("as a dependency")])
        newer = alpm.sync_new_version(pkg, syncdbs())
        if newer != 0:
            rows.append([_("Update"), yellow(alpm.pkg_version(newer))])
        end
    else:
        dl = alpm.pkg_download_size(pkg)
        rows.append([_("Download size"), fmt_size(dl if dl != 0 else alpm.pkg_size(pkg))])
        rows.append([_("Installed size"), fmt_size(alpm.pkg_isize(pkg))])
        rows.append([_("Installed"), _("no")])
    end
    packager = alpm.pkg_packager(pkg)
    rows.append([_("Packager"), packager if packager != "" else "-"])
    built = alpm.pkg_builddate(pkg)
    rows.append([_("Build date"), strftime("%Y-%m-%d", built) if built != 0 else "-"])
    w = 0
    for r in rows:
        w = max(w, len(r[0]))
    end
    for r in rows:
        call write(dim(r[0] + " " * (w - len(r[0]))) + "  " + r[1])
    end
    return 0
end

# Sirotci: zavislosti, ktere uz nic nepotrebuje (orphans v lux_alpm.py: i opakovane, dokud nejake pribyvaji)
function orphans():
    local = localdb()
    out = []
    for p in alpm.db_pkgcache(local):
        if alpm.pkg_reason(p) == alpm.REASON_DEPEND and len(alpm.pkg_requiredby(p)) == 0:
            out.append(p)
        end
    end
    return out
end

function sort_by_name(pkgs):
    keyed = {}
    names = []
    for p in pkgs:
        n = alpm.pkg_name(p)
        keyed[n] = p
        names.append(n)
    end
    return [keyed[n] for n in sorted(names)]
end

function cmd_list(args):
    local = localdb()
    plain = not (ui["tty"] or ui["color"])
    pattern = args["pattern"]
    mode = args["mode"]
    if mode == "sync":
        for db in syncdbs("Search"):
            dbname = alpm.db_name(db)
            for p in alpm.db_pkgcache(db):
                name = alpm.pkg_name(p)
                if pattern != None and not (pattern.lower() in name.lower()):
                    continue
                end
                desc = alpm.pkg_desc(p).replace(chr(9), " ").replace(chr(10), " ")
                call write(dbname + chr(9) + name + chr(9) + alpm.pkg_version(p) + chr(9) + String(alpm.pkg_isize(p)) + chr(9) + desc)
            end
        end
        return 0
    end
    if mode == "upgradable":
        dbs = syncdbs("Upgrade")
        for p in sort_by_name(alpm.db_pkgcache(local)):
            name = alpm.pkg_name(p)
            new = alpm.sync_new_version(p, dbs)
            if new == 0 or (pattern != None and not (pattern.lower() in name.lower())):
                continue
            end
            if plain:
                call write(name + " " + alpm.pkg_version(p) + " -> " + alpm.pkg_version(new))
            else:
                call write(bold(name) + " " + dim(alpm.pkg_version(p)) + " → " + green(alpm.pkg_version(new)) + " " + repo_badge(alpm.db_name(alpm.pkg_db(new))))
            end
        end
        return 0
    end
    pkgs = sort_by_name(alpm.db_pkgcache(local))
    if mode == "explicit":
        pkgs = [p for p in pkgs if alpm.pkg_reason(p) == 0]
    elif mode == "foreign":
        sync_names = {}
        for db in syncdbs():
            for x in alpm.db_pkgcache(db):
                sync_names[alpm.pkg_name(x)] = True
            end
        end
        pkgs = [p for p in pkgs if not (alpm.pkg_name(p) in sync_names)]
    elif mode == "orphans":
        pkgs = sort_by_name(orphans())
    end
    for p in pkgs:
        name = alpm.pkg_name(p)
        if pattern != None and not (pattern.lower() in name.lower()):
            continue
        end
        call write((name + " " + alpm.pkg_version(p)) if plain else (name + " " + green(alpm.pkg_version(p))))
    end
    return 0
end

function join_root(root, path):
    if root.endswith("/"):
        return root + path
    end
    return root + "/" + path
end

function cmd_files(args):
    p = alpm.db_get_pkg(localdb(), args["package"])
    if p == 0:
        return LuxError("notinstalled", i18n.TF("Package '%s' is not installed", [args["package"]]))
    end
    root = conf_get(lux["conf"], "RootDir", "/")
    for f in alpm.pkg_files(p):
        call write(join_root(root, f))
    end
    return 0
end

# Pozice posledniho "/" (-1 = zadne); retezce v LSL nemaji rfind
function last_slash(path):
    i = len(path) - 1
    while i >= 0:
        if path[i] == "/":
            return i
        end
        i -= 1
    end
    return -1
end

# Absolutni cesta jako u pacman -Qo: adresar se vyhodnoti (symlinky), posledni cast ne; holy nazev prikazu
# se hleda v PATH
function owner_path(path, root):
    if not ("/" in path) and not sys.lexists(path):
        found = glib.find_program_in_path(path)
        if found != "":
            path = found
        end
    end
    if not path.startswith("/"):
        path = sys.cwd() + "/" + path
    end
    path = normpath(path)
    slash = last_slash(path)
    d = path[0:slash] if slash > 0 else "/"
    base = path[slash + 1:]
    rd = lglib.realpath(d)
    if rd == "":
        rd = d
    end
    full = (rd if rd.endswith("/") else rd + "/") + base if base != "" else rd
    rel = full[len(root):] if full.startswith(root) else full
    if rel.startswith("/"):
        rel = rel[1:]
    end
    if base != "" and lglib.is_dir(full) and not is_link(full):
        return rel + "/"
    end
    return rel
end

# os.path.normpath pro absolutni cestu: . a .. a zdvojena lomitka
function normpath(path):
    parts = []
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        elif part == "..":
            if len(parts) > 0:
                parts.pop()
            end
        else:
            parts.append(part)
        end
    end
    return "/" + "/".join(parts)
end

function cmd_owns(args):
    call h()
    root = conf_get(lux["conf"], "RootDir", "/")
    wanted = {}
    order = []
    for a in args["paths"]:
        rel = owner_path(a, root)
        if not (rel in wanted):
            order.append(rel)
        end
        wanted[rel] = a
    end
    found = {}
    for p in alpm.db_pkgcache(localdb()):
        for f in alpm.pkg_files(p):
            if f in wanted:
                if not (f in found):
                    found[f] = []
                end
                found[f].append(p)
            end
        end
    end
    rc = 0
    for rel in order:
        orig = wanted[rel]
        owners = found.get(rel, [])
        if len(owners) == 0:
            call fail(i18n.TF("No package owns %s", [orig]))
            call compat("error: No package owns " + orig)
            rc = 1
            continue
        end
        for p in owners:
            call write("/" + rel + " " + _("is owned by") + " " + bold(alpm.pkg_name(p)) + " " + green(alpm.pkg_version(p)))
        end
    end
    return rc
end

function is_pkgfile(path):
    for s in PKG_SUFFIXES:
        if path.endswith(s):
            return True
        end
    end
    return False
end

function cmd_resolve(args):
    for t in args["targets"]:
        if is_pkgfile(t) and is_file(t):
            call write("file" + chr(9) + t)
        elif len(find_sync(t)) > 0:
            call write("repo" + chr(9) + t)
        else:
            call write("none" + chr(9) + t)
        end
    end
    return 0
end

# ---- zpravy libalpm (Callbacks.log v lux_alpm.py) ----

LOG_ERROR = 1
LOG_WARNING = 2
log_seen = {"hosts": []}

function on_alpm_log(level, message):
    msg = message.rstrip()
    if msg == "":
        return 0
    end
    if level == LOG_ERROR:
        call compat("error: " + msg)
        # "failed retrieving file 'x' from HOST : ..." - jednou na server
        at = msg.find("failed retrieving file '")
        if at >= 0 and not ui["machine"]:
            rest = msg[at + 24:]
            q = rest.find("' from ")
            if q >= 0:
                host = rest[q + 7:]
                colon = host.find(":")
                if colon >= 0:
                    host = host[0:colon]
                end
                host = host.strip()
                if host != "" and not (host in log_seen["hosts"]):
                    log_seen["hosts"].append(host)
                    call write(dim("  ↻ " + i18n.TF("Server %s is not responding, trying another one…", [host])), True)
                end
            end
        end
    elif level == LOG_WARNING:
        call compat("warning: " + msg)
        if ui["verbose"] and not ui["machine"]:
            call write(yellow("! ") + msg, True)
        end
    end
    return 0
end

# ---- kontrola aktualizaci ----

CHECK_UPDATES_WAIT_MS = 300000   # jak dlouho check-updates ceka na jinou probihajici kontrolu
check_lock = {"fd": -1}

function check_updates_db(path):
    if path != None:
        return path
    end
    base = env.get("TMPDIR", "")
    if base == "":
        base = "/tmp"
    end
    return base + "/lux-checkupdates-" + String(fs.getuid())
end

# Kopie konfigurace s jinymi volbami (with_options v lux_config.py)
function conf_with(conf, options, drop):
    opts = {}
    for k in conf["options"]:
        if not (k in drop):
            opts[k] = conf["options"][k]
        end
    end
    for k in options:
        opts[k] = [options[k]]
    end
    return {"options": opts, "repos": conf["repos"]}
end

# Jako checkupdates z pacman-contrib: databaze repozitaru se obnovi do docasne kopie (bez zamku a prav
# roota), systemova databaze se nemeni. 0 = jsou aktualizace, 2 = nejsou, 1 = chyba.
function cmd_check_updates(args):
    conf = lux["conf"]
    real = conf_get(conf, "DBPath", DEFAULT_DBPATH)
    if not real.endswith("/"):
        real = real + "/"
    end
    tmp = check_updates_db(args["db"])
    # nejdriv overit slozku (v /tmp ji mohl predem zalozit nekdo jiny, i jako odkaz), az pak do ni zapisovat
    call fs.mkdir(tmp, 448)
    st = fs.lstat(tmp)
    if st == None or st["uid"] != fs.getuid() or not fs.is_dir_mode(st):
        return LuxError("permission", tmp + " does not belong to this user")
    end
    call fs.mkdir(tmp + "/sync", 448)
    # Obchod, Pece a terminal kontroluji do stejne slozky: dalsi beh pocka na prvni. Kdo drzi flock,
    # je jediny uzivatel slozky, takze db.lck je zbytek preruseneho behu.
    fd = fs.open(tmp + "/.check-updates.lock", fs.O_WRONLY + fs.O_CREAT + fs.O_APPEND + fs.O_CLOEXEC, 420)
    check_lock["fd"] = fd
    deadline = fs.monotonic_ms() + CHECK_UPDATES_WAIT_MS
    while not fs.flock_nb(fd):
        if fs.monotonic_ms() > deadline:
            return LuxError("locked", _("Another update check is still running. Try again later."))
        end
        call fs.sleep_ms(500)
    end
    call fs.unlink(tmp + "/db.lck")
    local = tmp + "/local"
    target = real + "local"
    if is_link(local) and lglib.readlink(local) != target:
        call fs.unlink(local)
    end
    if not sys.lexists(local):
        call fs.symlink(target, local)
    end
    # posledni stazene databaze systemu jako zaklad (stahuje se jen to, co se zmenilo); databaze
    # a jeji podpis vzdy spolu, stary podpis k novejsi databazi by neprosel overenim
    for f in sys.list_dir(real + "sync"):
        if not f.endswith(".db"):
            continue
        end
        a = real + "sync/" + f
        b = tmp + "/sync/" + f
        if fs.is_file(a) and (not exists(b) or fs.mtime_ns(a) > fs.mtime_ns(b)):
            call fs.copy2(a, b)
            if fs.is_file(a + ".sig"):
                call fs.copy2(a + ".sig", b + ".sig")
            elif exists(b + ".sig"):
                call fs.unlink(b + ".sig")
            end
        end
    end
    opts = {"DBPath": tmp + "/", "LogFile": "/dev/null"}
    if fs.geteuid() != 0:
        # gpgme potrebuje do slozky klicu zapisovat (zamky, trustdb); /etc/lux/keyring patri rootovi
        gdir = conf_get(conf, "GPGDir", "/etc/lux/keyring/")
        if not gdir.endswith("/"):
            gdir = gdir + "/"
        end
        mine = tmp + "/gnupg"
        call fs.mkdir(mine, 448)
        for f in ["pubring.gpg", "pubring.kbx", "trustdb.gpg", "gpg.conf"]:
            if fs.is_file(gdir + f) and (not exists(mine + "/" + f) or fs.mtime_ns(gdir + f) > fs.mtime_ns(mine + "/" + f)):
                call fs.copy2(gdir + f, mine + "/" + f)
            end
        end
        opts["GPGDir"] = mine + "/"
    end
    tconf = conf_with(conf, opts, ["DownloadUser"])
    th = build_handle(tconf)
    call alpm.set_logcb(th, on_alpm_log)
    failed = []
    for r in tconf["repos"]:
        if not ("Sync" in usage_mask(r.get("Usage", []))):
            continue
        end
        db = 0
        for d in alpm.syncdbs(th):
            if alpm.db_name(d) == r["name"]:
                db = d
            end
        end
        if alpm.db_update(th, db, False) != 0:
            # kopie ze systemu nemusi sedet (databaze a podpis z ruznych chvil): zahodit a stahnout nacisto
            call fs.unlink(tmp + "/sync/" + r["name"] + ".db")
            call fs.unlink(tmp + "/sync/" + r["name"] + ".db.sig")
            if alpm.db_update(th, db, True) != 0:
                failed.append(r["name"] + ": unable to update database")
            end
        end
    end
    if len(failed) > 0:
        return LuxError("refresh", _("The package lists could not be refreshed. Check your internet connection and try again."), 1, failed)
    end
    allowed = [r["name"] for r in tconf["repos"] if "Upgrade" in usage_mask(r.get("Usage", []))]
    dbs = [d for d in alpm.syncdbs(th) if alpm.db_name(d) in allowed]
    n = 0
    for p in sort_by_name(alpm.db_pkgcache(alpm.localdb(th))):
        new = alpm.sync_new_version(p, dbs)
        if new == 0:
            continue
        end
        n += 1
        call write(alpm.pkg_name(p) + " " + alpm.pkg_version(p) + " -> " + alpm.pkg_version(new))
    end
    return 0 if n > 0 else 2
end

function cmd_available(args):
    if args["verbose"]:
        for k in ["RootDir", "DBPath", "GPGDir", "LogFile", "CacheDir", "HookDir", "Architecture", "IgnorePkg"]:
            call write(k + ": " + ", ".join(conf_list(lux["conf"], k)))
        end
        for d in alpm.syncdbs(h()):
            call write("[" + alpm.db_name(d) + "]")
        end
    end
    call write("ok")
    return 0
end

# ---- prikazova radka ----

COMMANDS = ["search", "info", "list", "files", "owns", "resolve", "check-updates", "available"]
LIST_MODES = ["explicit", "foreign", "orphans", "sync", "upgradable"]

function usage_error(message):
    call sys.eprint("usage: lux-alpm [-v] [--machine] [--color {auto,always,never}] [--lang LANG] COMMAND ...")
    call sys.eprint("lux-alpm: error: " + message)
    return 2
end

# argv -> [globalni, prikaz, argumenty prikazu] nebo [None, chyba]
function parse_args(argv):
    opts = {"verbose": False, "machine": False, "color": "auto", "lang": None, "datasaver": False, "yes": False}
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a == "-v" or a == "--verbose":
            opts["verbose"] = True
        elif a == "--machine":
            opts["machine"] = True
        elif a == "--datasaver":
            opts["datasaver"] = True
        elif a == "-y" or a == "--yes":
            opts["yes"] = True
        elif a == "--color" or a == "--lang":
            if i + 1 >= len(argv):
                return [None, "argument " + a + ": expected one argument"]
            end
            opts[a[2:]] = argv[i + 1]
            i += 1
        elif a.startswith("--color="):
            opts["color"] = a[8:]
        elif a.startswith("--lang="):
            opts["lang"] = a[7:]
        else:
            return [None, "unrecognized arguments: " + a]
        end
        i += 1
    end
    if not (opts["color"] in ["auto", "always", "never"]):
        return [None, "argument --color: invalid choice: '" + opts["color"] + "'"]
    end
    if i >= len(argv):
        return [None, "the following arguments are required: cmd"]
    end
    cmd = argv[i]
    rest = argv[i + 1:]
    if not (cmd in COMMANDS):
        return [None, "argument cmd: invalid choice: '" + cmd + "'"]
    end
    args = {"cmd": cmd, "installed": False, "sync": False, "mode": None, "pattern": None, "db": None,
            "verbose": opts["verbose"]}
    pos = []
    j = 0
    while j < len(rest):
        a = rest[j]
        j += 1
        if cmd == "search" and a == "--installed":
            args["installed"] = True
        elif cmd == "info" and a == "--sync":
            args["sync"] = True
        elif cmd == "list" and a.startswith("--") and a[2:] in LIST_MODES:
            args["mode"] = a[2:]
        elif cmd == "check-updates" and a == "--db":
            if j >= len(rest):
                return [None, "argument --db: expected one argument"]
            end
            args["db"] = rest[j]
            j += 1
        elif cmd == "check-updates" and a.startswith("--db="):
            args["db"] = a[5:]
        elif a.startswith("-") and a != "-":
            return [None, "unrecognized arguments: " + a]
        else:
            pos.append(a)
        end
    end
    if cmd == "search":
        if len(pos) == 0:
            return [None, "the following arguments are required: terms"]
        end
        args["terms"] = pos
    elif cmd == "info" or cmd == "files":
        if len(pos) != 1:
            return [None, "the following arguments are required: package"]
        end
        args["package"] = pos[0]
    elif cmd == "list":
        if len(pos) > 1:
            return [None, "unrecognized arguments: " + pos[1]]
        end
        if len(pos) == 1:
            args["pattern"] = pos[0]
        end
    elif cmd == "owns":
        if len(pos) == 0:
            return [None, "the following arguments are required: paths"]
        end
        args["paths"] = pos
    elif (cmd == "check-updates" or cmd == "available") and len(pos) > 0:
        return [None, "unrecognized arguments: " + " ".join(pos)]
    elif cmd == "resolve":
        if len(pos) == 0:
            return [None, "the following arguments are required: targets"]
        end
        args["targets"] = pos
    end
    return [opts, args]
end

function dispatch(args):
    cmd = args["cmd"]
    if cmd == "search":
        return cmd_search(args)
    elif cmd == "info":
        return cmd_info(args)
    elif cmd == "list":
        return cmd_list(args)
    elif cmd == "files":
        return cmd_files(args)
    elif cmd == "owns":
        return cmd_owns(args)
    elif cmd == "check-updates":
        return cmd_check_updates(args)
    elif cmd == "available":
        return cmd_available(args)
    end
    return cmd_resolve(args)
end

function main():
    argv = []
    i = 1
    while i < arg_count():
        argv.append(arg(i))
        i += 1
    end
    parsed = parse_args(argv)
    if parsed[0] == None:
        return usage_error(parsed[1])
    end
    opts = parsed[0]
    args = parsed[1]
    if opts["lang"] != None:
        call sys.setenv("LANG", opts["lang"])
        call unsetenv("LC_ALL")
        call unsetenv("LC_MESSAGES")
    end
    ui["machine"] = opts["machine"]
    ui["verbose"] = opts["verbose"]
    ui["tty"] = (not opts["machine"]) and isatty(1)
    if opts["color"] == "always":
        ui["color"] = True
    elif opts["color"] == "never" or opts["machine"]:
        ui["color"] = False
    else:
        ui["color"] = ui["tty"] and env.get("NO_COLOR", "") == ""
    end
    rc = 0
    try:
        call h()
        result = dispatch(args)
        if type(result) == "Dictionary" and result.get("lux_error", False):
            rc = result["rc"]
            call emit(["ERROR", result["kind"], result["message"]])
            call fail(result["message"])
            details = result.get("details", [])
            if len(details) > 0 and (opts["verbose"] or ui["machine"]):
                for d in details:
                    call write(("" if ui["machine"] else "  ") + String(d), True)
                end
            elif len(details) > 0 and not (result["kind"] in ["cancelled", "notfound", "confirm"]):
                shown = []
                for d in details:
                    t = String(d).strip()
                    if t != "" and not (t in shown):
                        shown.append(t)
                    end
                end
                for d in shown[0:DETAIL_LINES]:
                    call write(dim("  " + d), True)
                end
                if len(shown) > DETAIL_LINES:
                    call write(dim("  " + _("More details: run the command again with --verbose")))
                end
            end
        else:
            rc = result
        end
    else:
        e = String(last_error())
        rc = EXIT_UNAVAILABLE
        if args["cmd"] == "available" or opts["verbose"]:
            call sys.eprint("lux: " + e)
        end
        call emit(["UNAVAILABLE", e])
    end
    call emit(["DONE", rc])
    return rc
end

call exit(main())
