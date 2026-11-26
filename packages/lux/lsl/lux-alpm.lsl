# LuxOS - lux-alpm: jadro spravce baliku lux v LSL (nahrada /usr/lib/lux/lux_alpm.py a pyalpm).
#
# Stejne rozhrani jako lux_alpm.py (lux, Obchod a Aktualizace ho volaji primo):
#   lux-alpm [-v] [--machine] [--color auto|always|never] [--lang JAZYK] [--datasaver] PRIKAZ ...
# Vsechny prikazy lux_alpm.py: cteni (search, info, list, files, owns, resolve), available, check-updates,
# transakce (install, reinstall, remove, autoremove, upgrade/update, sync), clean a migrate. Vystup je
# stejny jako u Python verze; parity.sh (cteni, 189 pripadu) a txn-test.sh (transakce ve falesnych
# korenech) ho porovnavaji. Rozdil: chyby libalpm nesou skutecny duvod (nesplnene zavislosti, konflikt
# souboru, sit) misto "transaction failed" z pyalpm. Potrebuje lux-engine se zaplatou 0004 (log callback
# v detskem procesu scriptletu). Slouceni konfigurace (*.luxnew) zatim vola Python (lux_configmerge.py
# merge), countme lux-countme (LSL, jinak lux_countme.py); konfiguraci jadra dava `lux-config dump`.
load env
load glib
load luxalpm as alpm
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_glib as lglib
load process
load luxfs as fs
load json

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
lux = {"h": 0, "conf": None, "raised": None, "flow": None, "keyboard": False, "trans": False,
       "in_commit": False, "interrupted": False, "local_siglevel": 0, "transaction": False}

# ---- znaky (retezce LSL nemaji isdigit/isalnum) ----

function is_digits(t):
    if t == "":
        return False
    end
    for ch in t:
        if not (ch in "0123456789"):
            return False
        end
    end
    return True
end

function is_alnum(t):
    if t == "":
        return False
    end
    for ch in t:
        if not (ch in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            return False
        end
    end
    return True
end

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
    call clear_line()
    if err and not ui["machine"]:
        call sys.eprint(text)
    else:
        call sys.out(text + chr(10))
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
        call sys.out("@@" + " ".join([String(p) for p in parts]) + chr(10))
    end
    return 0
end

function compat(text):
    if ui["machine"]:
        call sys.out(text + chr(10))
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
        tool = "/usr/lib/lux/alpm/bin/lux-engine-conf"
        r = process_capture([tool if exists(tool) else "lux-engine-conf", "--config", path])
    else:
        r = process_capture([LUX_CONFIG, "dump"])
    end
    if r[0] != 0:
        Error(LuxConfigError: "lux-engine-conf: " + r[2].strip())
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
    local_sig = parse_siglevel(conf_list(conf, "LocalFileSigLevel"), base)
    call alpm.set_local_file_siglevel(h, local_sig)
    call alpm.set_remote_file_siglevel(h, parse_siglevel(conf_list(conf, "RemoteFileSigLevel"), base))
    lux["local_siglevel"] = local_sig
    for v in conf_list(conf, "NoUpgrade"):
        call alpm.add_noupgrade(h, v)
    end
    for v in conf_list(conf, "NoExtract"):
        call alpm.add_noextract(h, v)
    end
    # hooky z /usr/share/libalpm/hooks pridava libalpm sam; HookDir (/etc/lux/hooks) jen pro transakce
    if lux["transaction"]:
        for d in conf_list(conf, "HookDir"):
            call alpm.add_hookdir(h, d)
        end
    end
    if "CheckSpace" in conf["options"]:
        call alpm.set_checkspace(h, 1)
    end
    if "UseSyslog" in conf["options"]:
        call alpm.set_usesyslog(h, 1)
    end
    if "DisableDownloadTimeout" in conf["options"]:
        call alpm.set_disable_dl_timeout(h, 1)
    end
    pd = conf_get(conf, "ParallelDownloads", "")
    if pd != "" and is_digits(pd):
        call alpm.set_parallel_downloads(h, Int(pd))
    end
    # pacman 7: stahovani pod neprivilegovanym uzivatelem (DownloadUser)
    du = conf_get(conf, "DownloadUser", "")
    if du != "" and not ("DisableSandbox" in conf["options"]):
        call alpm.set_sandboxuser(h, du)
    end
    if conf_get(conf, "XferCommand", "") != "":
        Error(LuxConfigError: "XferCommand is not supported")
    end
    call alpm.set_logcb(h, on_log_all)
    call alpm.set_callbacks(h, on_dl, on_progress, on_event, on_question)
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
        if alpm.pkg_reason(p) == alpm.REASON_DEPEND and len(alpm.pkg_requiredby(p)) == 0 and len(alpm.pkg_optionalfor(p)) == 0:
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
    call cb_reset("refresh")
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

# ---- vyjimky (LuxError z hloubky volani a rizeni opakovani transakce) ----

# Vyvola LuxError: zapise ho do lux["raised"], Error() probubla do main (nebo do transaction)
function raise_lux(err):
    lux["raised"] = err
    Error(LuxRaised: err["message"])
end

# Rizeni toku transakce (_Retry, _RetryCorrupt, _Reprovide, _NeedSysupgrade v lux_alpm.py)
function raise_flow(flow):
    lux["flow"] = flow
    Error(LuxFlow: flow["kind"])
end

# Ctrl+C mimo instalaci (KeyboardInterrupt)
function raise_keyboard():
    lux["keyboard"] = True
    Error(LuxKeyboard: "cancelled")
end

# Zachycena chyba je jedna z nasich (ne chyba programu)?
function pending_raise():
    return lux.get("raised", None) != None or lux.get("flow", None) != None or lux.get("keyboard", False)
end

# ---- texty ----

function n_packages(n):
    if n == 1:
        return _("1 package")
    end
    lg = lang()
    few = False
    if lg in ["cs", "sk"]:
        few = n >= 2 and n <= 4
    elif lg in ["pl", "uk"]:
        few = n % 10 >= 2 and n % 10 <= 4 and not (n % 100 >= 12 and n % 100 <= 14)
    end
    if few:
        s = _("%d packages|few")
        if s != "%d packages|few":
            return s.replace("%d", String(n))
        end
    end
    return _("%d packages").replace("%d", String(n))
end

function fmt_delta(n):
    return ("+" if n >= 0 else "-") + fmt_size(n)
end

# sekundy z milisekund: pod minutu "3.2 s" (desetinna carka podle jazyka), jinak "2 min 5 s"
function fmt_duration_ms(ms):
    if ms < 60000:
        return decimal(one_decimal(Float(ms) / 1000.0) + " s")
    end
    total = (ms + 500) // 1000
    return String(total // 60) + " min " + String(total % 60) + " s"
end

function plan_question(action, n, download, delta):
    parts = []
    if download != 0:
        parts.append(i18n.TF("%s download", [fmt_size(download)]))
    end
    if delta != 0 or action != "remove":
        parts.append(i18n.TF("%s disk", [fmt_delta(delta)]))
    end
    what = n_packages(n) + ((" (" + ", ".join(parts) + ")") if len(parts) > 0 else "")
    verbs = {"install": "Install %s?", "upgrade": "Upgrade %s?", "reinstall": "Reinstall %s?",
             "remove": "Remove %s?", "download": "Download %s?"}
    return i18n.TF(verbs[action], [what])
end

function summary_line(action, explicit, ndeps, ms):
    verbs = {"install": "Installed %s", "upgrade": "Upgraded %s", "reinstall": "Reinstalled %s",
             "remove": "Removed %s", "download": "Downloaded %s"}
    if len(explicit) > 0 and len(explicit) <= 3:
        what = ", ".join([(e[0] + " " + e[1]).strip() for e in explicit])
    else:
        what = n_packages(len(explicit) + (0 if len(explicit) > 0 else ndeps))
        if len(explicit) == 0:
            ndeps = 0
        end
    end
    s = i18n.TF(verbs[action], [what])
    if ndeps > 0:
        s = s + " (" + _("+%d deps").replace("%d", String(ndeps)) + ")"
    end
    return s + " " + i18n.TF("in %s", [fmt_duration_ms(ms)])
end

# delka bez barev ANSI
function visible_len(s):
    n = 0
    i = 0
    esc = False
    for ch in s:
        if esc:
            if ch == "m":
                esc = False
            end
        elif ch == chr(27):
            esc = True
        else:
            n += 1
        end
    end
    return n
end

ERROR_KINDS = [["unable to lock database", "locked"], ["could not lock database", "locked"],
               ["insufficient privileges", "permission"], ["not enough free disk space", "disk"],
               ["no space left on device", "disk"], ["conflicting files", "conflict"],
               ["exists in filesystem", "conflict"], ["conflicting dependencies", "pkgconflict"],
               ["are in conflict", "pkgconflict"], ["could not satisfy dependencies", "deps"],
               ["unable to satisfy dependency", "deps"], ["invalid or corrupted package (checksum)", "corrupt"],
               ["signature", "keyring"], ["unknown trust", "keyring"], ["required key missing", "keyring"],
               ["invalid or corrupted database (pgp", "keyring"], ["failed retrieving file", "network"],
               ["failed to retrieve some files", "network"], ["failed to synchronize", "network"],
               ["download library error", "network"], ["could not resolve host", "network"],
               ["no servers configured", "network"], ["target not found", "notfound"],
               ["could not find or read package", "notfound"]]

function classify(text):
    low = text.lower()
    for e in ERROR_KINDS:
        if e[0] in low:
            return e[1]
        end
    end
    return "unknown"
end

# 404 u souboru baliku (ne databaze): mistni seznam baliku je zastaraly
function stale_download(text):
    for line in text.split(chr(10)):
        if "404" in line and ".pkg.tar" in line:
            return True
        end
    end
    return False
end

function plain_message(kind, detail=""):
    if kind == "locked":
        if detail != "":
            return i18n.TF("Another update is still running (%s). Try again when it finishes.", [detail])
        end
        return _("The package database is locked: another package manager is running, or a previous one crashed. If nothing else is running: lux fix")
    elif kind == "refresh":
        if detail != "":
            return i18n.TF("The package lists could not be refreshed: %s", [detail])
        end
        return _("The package lists could not be refreshed.")
    elif kind == "permission":
        return _("This needs administrator rights.")
    elif kind == "disk":
        return _("Not enough free disk space. Free some space (lux clean) and try again.")
    elif kind == "conflict":
        return _("Some files of the new packages already exist on the system (file conflict).")
    elif kind == "pkgconflict":
        return _("The selected packages conflict with installed packages.")
    elif kind == "deps":
        if detail != "":
            return i18n.TF("Dependencies can not be satisfied: %s", [detail])
        end
        return _("Dependencies can not be satisfied.")
    elif kind == "corrupt":
        return _("A downloaded package is damaged. Try again; if it repeats, run: lux clean")
    elif kind == "keyring":
        return _("A package signature could not be verified. Repair the signing keys with: lux fix")
    elif kind == "network":
        return _("Some packages could not be downloaded. Check your internet connection and try again.")
    elif kind == "outdated":
        return _("The package lists are out of date: the server no longer has this version. Update the system first (lux update), then try again.")
    elif kind == "notfound":
        if detail != "":
            return i18n.TF("Package '%s' not found. Try: lux search %s", [detail, detail])
        end
        return _("Package not found.")
    elif kind == "config":
        return _("The package manager configuration has an error. Check it with: lux config check")
    elif kind == "dbinvalid":
        return _("The package lists are damaged or do not match their signatures. Refresh them first (lux update), then try again.")
    end
    return _("The package operation failed.")
end

# ---- prubeh: jedna radka na fazi (UI.phase v lux_alpm.py) ----

LABELS = {"refresh": "Refreshing", "download": "Downloading", "verify": "Verifying", "install": "Installing",
          "remove": "Removing", "hooks": "Finishing", "prepare": "Preparing"}
uiph = {"ph": None, "last": 0}

function raw_out(text):
    call sys.out(text)
    return 0
end

function clear_line():
    if ui["tty"] and uiph["ph"] != None:
        call raw_out(chr(13) + chr(27) + "[2K")
    end
    return 0
end

function label_width():
    w = 0
    for k in LABELS:
        n = len(_(LABELS[k]))
        if n > w:
            w = n
        end
    end
    return w
end

function term_columns():
    n = fs.term_cols(1)
    if n <= 0:
        cols = env.get("COLUMNS", "")
        if cols != "" and is_digits(cols):
            return Int(cols)
        end
        return 80
    end
    return n
end

function pad3(n):
    s = String(n)
    while len(s) < 3:
        s = " " + s
    end
    return s
end

function render(ph, icon):
    label = _(LABELS.get(ph["name"], ph["name"]))
    while len(label) < label_width():
        label = label + " "
    end
    pct = Int(ph["frac"] * 100.0)
    if not ui["tty"]:
        return (icon + " " + label + "  " + pad3(pct) + "%  " + ph["detail"]).rstrip()
    end
    cols = term_columns()
    barw = 20 if cols >= 70 else 10
    full = Int(ph["frac"] * Float(barw) + 0.5)
    bar = accent("█" * full) + dim("░" * (barw - full))
    head = icon + " " + bold(label) + " " + bar + " " + pad3(pct) + "%  "
    room = cols - visible_len(head) - 1
    detail = ph["detail"]
    if len(detail) > room:
        detail = (detail[0:max(0, room - 1)] + "…") if room > 1 else ""
    end
    return head + dim(detail)
end

function draw(force=False):
    ph = uiph["ph"]
    if ph == None:
        return 0
    end
    now = fs.monotonic_ms()
    if ui["machine"]:
        if force or now - uiph["last"] >= 500:
            uiph["last"] = now
            call emit(["PROGRESS", ph["name"], Int(ph["frac"] * 100.0), ph["detail"]])
        end
        return 0
    end
    if not ui["tty"]:
        return 0
    end
    if not force and now - uiph["last"] < 80:
        return 0
    end
    uiph["last"] = now
    icon = accent("↓" if ph["name"] in ["download", "refresh"] else "•")
    call raw_out(chr(13) + chr(27) + "[2K" + render(ph, icon))
    return 0
end

function phase(name, detail=""):
    if uiph["ph"] != None and uiph["ph"]["name"] == name:
        return 0
    end
    call phase_done()
    uiph["ph"] = {"name": name, "frac": 0.0, "detail": detail}
    call emit(["PHASE", name])
    call draw(True)
    return 0
end

function progress(frac, detail=None):
    ph = uiph["ph"]
    if ph == None:
        return 0
    end
    base = ph["frac"] if ph["name"] != "download" else 0.0
    ph["frac"] = max(base, min(1.0, frac))
    if detail != None:
        ph["detail"] = detail
    end
    call draw()
    return 0
end

function phase_done(ok=True, detail=None):
    ph = uiph["ph"]
    if ph == None:
        return 0
    end
    if detail != None:
        ph["detail"] = detail
    end
    if ok:
        ph["frac"] = 1.0
    end
    uiph["ph"] = None
    if ui["machine"]:
        call emit(["PROGRESS", ph["name"], Int(ph["frac"] * 100.0), ph["detail"]])
        return 0
    end
    icon = green("✓") if ok else red("✗")
    line = render(ph, icon)
    if ui["tty"]:
        call raw_out(chr(13) + chr(27) + "[2K" + line + chr(10))
    else:
        call raw_out(line + chr(10))
    end
    return 0
end

function ok_line(text):
    if not ui["machine"]:
        call write(green("✓") + " " + text)
    end
    return 0
end

function say(text):
    if not ui["machine"]:
        call write(accent("✦") + " " + text)
    end
    return 0
end

function note(text):
    if not ui["machine"]:
        call write(dim(text))
    end
    return 0
end

function warn(text):
    if ui["machine"]:
        call write("warning: " + text)
    else:
        call write(yellow("!") + " " + text, True)
    end
    return 0
end

# ---- signaly: Ctrl+C behem instalace dokonci rozdelany balik ----

sig = {"cancel": False, "pumped": 0}

function on_signal():
    if lux.get("in_commit", False):
        if not lux.get("interrupted", False):
            lux["interrupted"] = True
            call alpm.trans_interrupt(lux["h"])
            if not ui["machine"]:
                call write(yellow("! ") + _("Stopping after the current package…"), True)
            end
        end
    else:
        sig["cancel"] = True
    end
    return True
end

function install_signals():
    for s in [2, 15, 1]:
        call glib.unix_signal_add_full(0, s, on_signal)
    end
    return 0
end

# Doruci cekajici signaly (nejvys 10x za sekundu); mimo instalaci Ctrl+C = Zruseno
function pump_signals(force=False):
    now = fs.monotonic_ms()
    if force or now - sig["pumped"] >= 100:
        sig["pumped"] = now
        call glib.pump()
    end
    return 0
end

function check_cancel():
    call pump_signals(True)
    if sig["cancel"]:
        call raise_keyboard()
    end
    return 0
end

# ---- otazky ----

function read_answer():
    chars = []
    while True:
        call check_cancel()
        if not fs.poll_readable(0, 200):
            continue
        end
        b = fs.read_byte(0)
        if b < 0:
            if len(chars) == 0:
                return None
            end
            break
        end
        if b == 10:
            break
        end
        if b < 128:
            chars.append(chr(b))
        end
    end
    return "".join(chars)
end

function ask(question, default=True):
    if ui["yes"]:
        return True
    end
    if ui["machine"] or not isatty(0):
        call raise_lux(LuxError("confirm", _("Confirmation is needed: run the command in a terminal or add -y.")))
    end
    hint = "[Y/n]" if default else "[y/N]"
    call clear_line()
    call raw_out(bold(question) + " " + hint + " ")
    a = read_answer()
    if a == None:
        return False
    end
    a = a.strip().lower()
    if a == "":
        return default
    end
    return a[0] in ["y", "a"]
end

# ---- callbacky libalpm (Callbacks v lux_alpm.py) ----

cb = {}

function cb_reset(mode="", dl_total=0, ops=None, sizes=None):
    cb["mode"] = mode
    cb["dl_total"] = dl_total
    cb["sizes"] = sizes if sizes != None else {}
    cb["files"] = {}
    cb["file_totals"] = {}
    cb["ops"] = ops if ops != None else {}
    cb["current"] = None
    cb["dl_start"] = fs.monotonic_ms()
    cb["log_errors"] = []
    cb["log_warnings"] = []
    cb["scriptlet"] = []
    cb["pacnew"] = 0
    cb["hosts"] = []
    cb["corrupted"] = []
    cb["hook_when"] = None
    cb["hook_pos"] = 0
    cb["hook_total"] = 0
    cb["hook_label"] = ""
    return 0
end

function sum_values(d):
    total = 0
    for k in d:
        total += d[k]
    end
    return total
end

function file_progress(fname, got, total):
    if cb["mode"] == "refresh":
        return 0
    end
    if total > 0:
        cb["file_totals"][fname] = total
    end
    cb["files"][fname] = max(0, got)
    if uiph["ph"] == None or uiph["ph"]["name"] != "download":
        call phase("download")
    end
    total_all = max(cb["dl_total"], sum_values(cb["file_totals"]))
    if total_all <= 0:
        total_all = 1
    end
    got_all = sum_values(cb["files"])
    elapsed = max(500, fs.monotonic_ms() - cb["dl_start"])
    speed = got_all * 1000 // elapsed
    call progress(Float(got_all) / Float(total_all), fmt_size(got_all) + " / " + fmt_size(total_all) + " · " + fmt_size(speed) + "/s")
    return 0
end

function file_done(fname):
    if cb["mode"] != "refresh" and not fname.endswith(".sig"):
        call compat(fname + " downloading...")
    end
    return 0
end

function on_dl(fname, ev, a, b):
    call pump_signals()
    # prubeh jen u souboru balicku ze seznamu (velikost z databaze), ne u podpisu .sig (jako lux_alpm.py)
    total = cb["sizes"].get(fname, 0)
    if ev == 1:
        if total > 0:
            call file_progress(fname, min(a, total), total)
        end
    elif ev == 2:
        cb["files"][fname] = 0
    elif ev == 3:
        if b == 0 and total > 0:
            call file_progress(fname, total, total)
        end
        if b >= 0:
            call file_done(fname)
        end
    end
    return 0
end

# progress: 0-4 operace s balikem, 5+ kontroly (konflikty, misto, integrita, nacitani, klice)
function on_progress(kind, target, percent, n, i):
    call pump_signals()
    if kind >= 5 or target == "":
        # kontroly pred stahovanim se neukazuji
        if cb["dl_total"] > 0 and len(cb["files"]) == 0:
            return 0
        end
        if uiph["ph"] == None or uiph["ph"]["name"] != "verify":
            call phase("verify")
        end
        call progress((Float(max(i, 1) - 1) + Float(percent) / 100.0) / Float(max(n, 1)))
        return 0
    end
    op = cb["ops"].get(target, "installing")
    name = "install"
    if op == "removing":
        name = "remove"
        for k in cb["ops"]:
            if cb["ops"][k] != "removing":
                name = "install"
            end
        end
    end
    if uiph["ph"] == None or uiph["ph"]["name"] != name:
        call phase(name)
    end
    if target != cb["current"]:
        cb["current"] = target
        call compat(op + " " + target + "...")
    end
    call progress((Float(max(i, 1) - 1) + Float(percent) / 100.0) / Float(max(n, 1)),
                  String(max(i, 1)) + "/" + String(n) + " " + target)
    return 0
end

# popis hooku bez koncovych tecek
function hook_label(text):
    t = text.strip()
    while t.endswith(".") or t.endswith("…"):
        t = t[0:len(t) - 1]
    end
    return t.strip()
end

function hook_start(when):
    ph = "prepare" if when == "pre" else "hooks"
    if uiph["ph"] == None or uiph["ph"]["name"] != ph:
        call phase(ph)
        call compat(":: Running pre-transaction hooks..." if when == "pre" else ":: Running post-transaction hooks...")
    end
    cb["hook_when"] = when
    cb["hook_pos"] = 0
    cb["hook_total"] = 0
    cb["hook_label"] = ""
    return 0
end

function hook_draw(frac):
    label = cb["hook_label"]
    total = max(cb["hook_total"], cb["hook_pos"], 1)
    call progress(frac, String(cb["hook_pos"]) + "/" + String(total) + ((" · " + label) if label != "" else ""))
    return 0
end

# libalpm posila u kazdeho hooku jeho popis, poradi a pocet (pyalpm ne - proto drive odhad HookPlan)
function on_event(ev, text, pos, total):
    call pump_signals()
    if ev == 34:
        call hook_start("pre" if cb["mode"] == "commit" and cb["current"] == None else "post")
    elif ev == 36:
        if cb["hook_when"] == None:
            call hook_start("pre" if cb["mode"] == "commit" and cb["current"] == None else "post")
        end
        cb["hook_pos"] = pos
        cb["hook_total"] = total
        cb["hook_label"] = hook_label(text)
        call hook_draw(Float(pos - 1) / Float(max(total, 1)))
    elif ev == 37:
        if cb["hook_when"] != None:
            cb["hook_pos"] = pos
            cb["hook_total"] = total
            call hook_draw(Float(pos) / Float(max(total, 1)))
        end
    elif ev == 35:
        if cb["hook_when"] != None and cb["hook_pos"] > 0 and uiph["ph"] != None and uiph["ph"]["name"] in ["hooks", "prepare"]:
            call progress(1.0, String(cb["hook_pos"]) + "/" + String(cb["hook_pos"]))
        end
        cb["hook_when"] = None
    elif ev == 17 and text.strip() != "":
        line = text.rstrip()
        cb["scriptlet"].append(line)
        if ui["verbose"] and not ui["machine"]:
            call write(dim("  " + line))
        end
        call compat(line)
    elif ev == 32:
        cb["pacnew"] = cb["pacnew"] + 1
    end
    return 0
end

Q_INSTALL_IGNOREPKG = 1
Q_REPLACE_PKG = 2
Q_CONFLICT_PKG = 4
Q_CORRUPTED_PKG = 8
Q_REMOVE_PKGS = 16
Q_SELECT_PROVIDER = 32
Q_IMPORT_KEY = 64

function on_question(q, text):
    if q == Q_CORRUPTED_PKG:
        # poskozeny soubor v mezipameti se vzdy smaze a stahne znovu (viz _transaction)
        if ".pkg.tar" in text and not (text in cb["corrupted"]):
            cb["corrupted"].append(text)
        end
        return 1
    end
    if q == Q_SELECT_PROVIDER:
        return 0
    end
    defaults = {Q_INSTALL_IGNOREPKG: True, Q_REPLACE_PKG: True, Q_CONFLICT_PKG: False, Q_REMOVE_PKGS: False,
                Q_IMPORT_KEY: True}
    default = defaults.get(q, False)
    if ui["yes"] or ui["machine"] or not isatty(0):
        return 1 if default else 0
    end
    prompts = {Q_REPLACE_PKG: "Replace a package with its successor?", Q_CONFLICT_PKG: "Remove a conflicting package?",
               Q_IMPORT_KEY: "Import the missing signing key?", Q_INSTALL_IGNOREPKG: "Install a package from IgnorePkg anyway?"}
    p = prompts.get(q, None)
    if p == None:
        return 1 if default else 0
    end
    answer = default
    safe:
        answer = ask(_(p) + ((" (" + text + ")") if text != "" else ""), default)
    end
    lux["raised"] = None
    lux["keyboard"] = False
    return 1 if answer else 0
end

function on_log_all(level, message):
    msg = message.rstrip()
    if msg != "" and level == LOG_ERROR and cb.get("log_errors", None) != None:
        cb["log_errors"].append(msg)
    elif msg != "" and level == LOG_WARNING and cb.get("log_warnings", None) != None:
        cb["log_warnings"].append(msg)
        if ".luxnew" in msg or ".pacnew" in msg:
            cb["pacnew"] = cb["pacnew"] + 1
        end
    end
    return on_alpm_log(level, message)
end

# ---- zamek databaze a jine spravce baliku ----

PKG_MANAGERS = ["lux-engine", "lux-engine-key", "pacman", "makepkg", "pacstrap", "yay", "paru", "pamac",
                "pamac-daemon", "packagekitd"]
PKG_SCRIPTS = {"lux_alpm.py": "lux", "lux-alpm": "lux", "luxos-care": "LuxOS Care", "luxos_care.py": "LuxOS Care",
               "luxos-update": "LuxOS Care", "luxos-store-helper": "LuxOS Store"}
LOCK_WAIT_MS = 300000

function read_small(path):
    t = ""
    safe:
        t = lglib.read_text(path)
    end
    return t if t != None else ""
end

function base_name(path):
    i = last_slash(path)
    return path[i + 1:] if i >= 0 else path
end

# PID tohoto procesu a vsech predku (lux, sudo, Obchod nejsou "jiny spravce baliku")
function ancestors():
    out = []
    pid = fs.getpid()
    while pid > 1 and not (pid in out):
        out.append(pid)
        st = read_small("/proc/" + String(pid) + "/stat")
        i = len(st) - 1
        while i >= 0 and st[i] != ")":
            i -= 1
        end
        if i < 0:
            break
        end
        parts = st[i + 1:].split(" ")
        fields = [p for p in parts if p != ""]
        if len(fields) < 2 or not is_digits(fields[1]):
            break
        end
        pid = Int(fields[1])
    end
    return out
end

function proc_uid(pid):
    for line in read_small("/proc/" + String(pid) + "/status").split(chr(10)):
        if line.startswith("Uid:"):
            f = [p for p in line[4:].replace(chr(9), " ").split(" ") if p != ""]
            if len(f) >= 2 and is_digits(f[1]):
                return Int(f[1])
            end
        end
    end
    return None
end

function running_package_managers():
    mine = ancestors()
    names = []
    for d in sys.list_dir("/proc"):
        if not is_digits(d):
            continue
        end
        pid = Int(d)
        if pid in mine:
            continue
        end
        comm = read_small("/proc/" + d + "/comm").strip()
        if comm == "":
            continue
        end
        if comm in PKG_MANAGERS:
            if not (comm in names):
                names.append(comm)
            end
            continue
        end
        argv = fs.read_nul_list("/proc/" + d + "/cmdline", 4096)
        for a in argv[0:3]:
            label = PKG_SCRIPTS.get(base_name(a), None)
            if label != None:
                uid = proc_uid(pid)
                if uid != None and uid != 0:
                    break
                end
                if not (label in names):
                    names.append(label)
                end
                break
            end
        end
    end
    return sorted(names)
end

function lock_path():
    dbpath = conf_get(lux["conf"], "DBPath", DEFAULT_DBPATH)
    if not dbpath.endswith("/"):
        dbpath = dbpath + "/"
    end
    return dbpath + "db.lck"
end

function wait_for_lock():
    lock = lock_path()
    deadline = fs.monotonic_ms() + LOCK_WAIT_MS
    waiting = False
    while sys.lexists(lock):
        procs = running_package_managers()
        if len(procs) == 0:
            if not fs.unlink(lock) and sys.lexists(lock):
                call raise_lux(LuxError("locked", plain_message("locked"), 1, [lock + ": " + String(sys.errno())]))
            end
            call note(_("Removed a stale database lock left by an interrupted update."))
            return 0
        end
        if fs.monotonic_ms() > deadline:
            call raise_lux(LuxError("locked", plain_message("locked", ", ".join(procs)), 1, [lock]))
        end
        if not waiting:
            waiting = True
            call emit(["WAIT", ",".join(procs)])
            call say(i18n.TF("Waiting for another update to finish (%s)…", [", ".join(procs)]))
        end
        call check_cancel()
        call fs.sleep_ms(1000)
    end
    return 0
end

function retry_notice(attempt, attempts):
    call emit(["RETRY", attempt])
    if not ui["machine"]:
        call write(yellow("↻ ") + i18n.TF("Download failed, trying again (%s/3)…", [String(attempt)]))
    end
    delay = env.get("LUX_RETRY_DELAY", "2")
    call fs.sleep_ms(Int(Float(delay) * 1000.0))
    return 0
end

function need_root():
    if fs.geteuid() != 0 and env.get("LUX_ALLOW_NONROOT", "") == "":
        call raise_lux(LuxError("permission", _("This needs administrator rights.")))
    end
    return 0
end

# ---- anonymni pocitani instalaci (lux_countme.py; jednou tydne, rozhoduje skript sam) ----

function countme_start():
    if fs.geteuid() != 0 or env.get("LUX_NO_COUNTME", "") != "" or lux.get("injected", False):
        return 0
    end
    found = False
    for r in lux["conf"]["repos"]:
        for s in r.get("Server", []):
            if s.startswith("https://luxos.lux-ai.cz/repo/") or s.startswith("https://luxos.lux-ai.cz/staging/"):
                found = True
            end
        end
    end
    # LSL verze (lux-countme) vedle teto, jinak Python; rozhodnuti "jednou tydne" dela sam skript
    tool = "/usr/lib/lux/lux-countme"
    if not fs.access_x(tool):
        tool = "/usr/lib/lux/lux_countme.py"
    end
    if found and fs.access_x(tool):
        safe:
            call lglib.spawn_quiet([tool, "send"])
        end
    end
    return 0
end

# ---- obnova databazi (lux sync, --refresh) ----

function refresh(force=False, attempts=3):
    call need_root()
    call wait_for_lock()
    dbs = syncdbs("Sync")
    names = ", ".join([alpm.db_name(d) for d in dbs])
    refetch = []
    attempt = 1
    while attempt <= attempts:
        call cb_reset("refresh")
        call phase("refresh", names)
        failed = []
        i = 0
        for db in dbs:
            call progress(Float(i) / Float(max(1, len(dbs))), alpm.db_name(db))
            i += 1
            if alpm.db_update(lux["h"], db, force or alpm.db_name(db) in refetch) != 0:
                failed.append([alpm.db_name(db), alpm.strerror(alpm.errno(lux["h"]))])
            end
            call check_cancel()
        end
        if len(failed) == 0:
            call phase_done(True, names)
            call countme_start()
            return 0
        end
        text = chr(10).join([f[0] + ": " + f[1] for f in failed]) + chr(10) + chr(10).join(cb["log_errors"])
        kind = classify(text)
        if kind == "unknown":
            kind = "locked" if sys.lexists(lock_path()) else "refresh"
        end
        call phase_done(False)
        for f in failed:
            call compat("error: failed to update " + f[0] + " (" + f[1] + ")")
        end
        call compat("error: failed to synchronize all databases")
        if kind == "keyring" and len(refetch) == 0 and attempt < attempts:
            refetch = [f[0] for f in failed]
        elif not (kind in ["network", "refresh"]) or attempt == attempts:
            detail = ""
            if kind == "refresh":
                detail = cb["log_errors"][0] if len(cb["log_errors"]) > 0 else failed[0][1]
            end
            call raise_lux(LuxError(kind, plain_message(kind, detail), 1,
                               [f[0] + ": " + f[1] for f in failed] + cb["log_errors"]))
        end
        call retry_notice(attempt + 1, attempts)
        attempt += 1
    end
    return 0
end

# ---- soubory balicku ----

function load_file(path):
    r = alpm.pkg_load(lux["h"], path, lux["local_siglevel"])
    if r[0] != 0:
        msg = alpm.strerror(alpm.errno(lux["h"]))
        kind = classify(msg)
        if kind in ["unknown", "notfound"]:
            call raise_lux(LuxError("notfound" if kind == "unknown" else kind, i18n.TF("Cannot read package file %s", [path]), 1, ["error: " + msg]))
        end
        call raise_lux(LuxError(kind, plain_message(kind, path), 1, ["error: " + msg]))
    end
    return r[1]
end

function abspath(path):
    if path.startswith("/"):
        return normpath(path)
    end
    return normpath(sys.cwd() + "/" + path)
end

# ---- graficke ovladace jako zavislosti ----

GPU_FALLBACK = {"vulkan-driver": ["vulkan-swrast"], "lib32-vulkan-driver": ["lib32-vulkan-swrast"],
                "opengl-driver": ["mesa"], "lib32-opengl-driver": ["lib32-mesa"],
                "opencl-driver": ["opencl-mesa"], "lib32-opencl-driver": ["lib32-opencl-mesa"]}

# ^(lib32-)?(opencl-)?nvidia(-\d+xx)?(-utils|-dkms|-open.*)?$
function gpu_vendor_pkg(name):
    n = name
    if n.startswith("lib32-"):
        n = n[6:]
    end
    if n.startswith("opencl-"):
        n = n[7:]
    end
    if not n.startswith("nvidia"):
        return False
    end
    n = n[6:]
    if n.startswith("-"):
        j = 1
        while j < len(n) and is_digits(n[j]):
            j += 1
        end
        if j > 1 and n[j:j + 2] == "xx":
            n = n[j + 2:]
        end
    end
    return n == "" or n == "-utils" or n == "-dkms" or n.startswith("-open")
end

function dep_name(dep):
    for ch in ["<", ">", "="]:
        i = dep.find(ch)
        if i >= 0:
            dep = dep[0:i]
        end
    end
    return dep
end

function hw_packages():
    r = process_capture(["luxos-hwdetect", "--packages"])
    if r[0] != 0:
        return []
    end
    return [p for p in r[1].replace(chr(10), " ").split(" ") if p != ""]
end

function better_gpu_providers(add, to_add):
    asked = [alpm.pkg_name(p) for p in add]
    local = localdb()
    pulled = [p for p in to_add if gpu_vendor_pkg(alpm.pkg_name(p)) and not (alpm.pkg_name(p) in asked)
              and alpm.db_get_pkg(local, alpm.pkg_name(p)) == 0]
    if len(pulled) == 0:
        return []
    end
    hw = hw_packages()
    for p in pulled:
        if alpm.pkg_name(p) in hw:
            return []
        end
    end
    dbs = syncdbs("Install")
    planned = [alpm.pkg_name(p) for p in to_add]
    prefer = hw + ["lib32-" + n for n in hw if not n.startswith("lib32-")]
    extra = []
    for p in pulled:
        for prov in alpm.pkg_provides(p):
            virt = dep_name(prov)
            if not virt.endswith("-driver"):
                continue
            end
            for name in prefer + GPU_FALLBACK.get(virt, []):
                if name in planned:
                    continue
                end
                cand = 0
                for db in dbs:
                    if cand == 0:
                        cand = alpm.db_get_pkg(db, name)
                    end
                end
                if cand == 0:
                    continue
                end
                fits = name == virt
                for x in alpm.pkg_provides(cand):
                    if dep_name(x) == virt:
                        fits = True
                    end
                end
                if fits:
                    extra.append(cand)
                    planned.append(name)
                    break
                end
            end
        end
    end
    return extra
end

# ---- castecna aktualizace ----

function partial_upgrade_risk(to_add):
    local = localdb()
    dbs = syncdbs("Upgrade")
    ignored = conf_list(lux["conf"], "IgnorePkg")
    igroups = conf_list(lux["conf"], "IgnoreGroup")
    adding = [alpm.pkg_name(p) for p in to_add]
    outdated = {}
    for p in alpm.db_pkgcache(local):
        name = alpm.pkg_name(p)
        if name in adding or name in ignored:
            continue
        end
        skip = False
        for g in alpm.pkg_groups(p):
            if g in igroups:
                skip = True
            end
        end
        if skip:
            continue
        end
        if alpm.sync_new_version(p, dbs) != 0:
            outdated[name] = p
        end
    end
    if len(outdated) == 0:
        return []
    end
    risky = []
    old_pkgs = [outdated[k] for k in outdated]
    for p in to_add:
        for d in alpm.pkg_depends(p):
            if alpm.find_satisfier_pkgs(to_add, d) != 0:
                continue
            end
            s = alpm.find_satisfier_pkgs(alpm.db_pkgcache(local), d)
            if s != 0 and alpm.pkg_name(s) in outdated and not (alpm.pkg_name(s) in risky):
                risky.append(alpm.pkg_name(s))
            end
        end
        old = alpm.db_get_pkg(local, alpm.pkg_name(p))
        if old != 0 and alpm.vercmp(alpm.pkg_version(old), alpm.pkg_version(p)) != 0:
            for q in old_pkgs:
                for d in alpm.pkg_depends(q):
                    if alpm.find_satisfier_pkgs([p], d) != 0 and not (alpm.pkg_name(q) in risky):
                        risky.append(alpm.pkg_name(q))
                    end
                end
            end
        end
    end
    return sorted(risky)
end

function confirm_sysupgrade(names):
    shown = ", ".join(names[0:5]) + (", …" if len(names) > 5 else "")
    why = i18n.TF("The system is older than the downloaded package lists (%s). Installing without updating the rest of the system could leave programs that do not start.", [shown])
    refuse = LuxError("outdated", why + " " + _("Update the whole system first (lux update), then try again."), 1,
                      ["partial upgrade: outdated " + n for n in names])
    if ui["machine"] or (not ui["yes"] and not isatty(0)):
        call raise_lux(refuse)
    end
    call warn(why)
    if not ask(_("Update the whole system together with it?")):
        call raise_lux(refuse)
    end
    return 0
end

# ---- plan a souhrn ----

function make_plan(to_add, to_remove):
    local = localdb()
    ops = {}
    order = []
    download = 0
    delta = 0
    sizes = {}
    for p in to_add:
        name = alpm.pkg_name(p)
        old = alpm.db_get_pkg(local, name)
        size = alpm.pkg_download_size(p)
        download += size
        fname = alpm.pkg_filename(p)
        if fname != "" and size > 0:
            sizes[fname] = size
        end
        delta += alpm.pkg_isize(p)
        if not (name in ops):
            order.append(name)
        end
        if old == 0:
            ops[name] = "installing"
        else:
            delta -= alpm.pkg_isize(old)
            c = alpm.vercmp(alpm.pkg_version(p), alpm.pkg_version(old))
            ops[name] = "upgrading" if c > 0 else ("downgrading" if c < 0 else "reinstalling")
        end
    end
    add_names = [alpm.pkg_name(p) for p in to_add]
    for p in to_remove:
        name = alpm.pkg_name(p)
        if not (name in add_names):
            if not (name in ops):
                order.append(name)
            end
            ops[name] = "removing"
        end
        delta -= alpm.pkg_isize(p)
    end
    return {"ops": ops, "download": download, "delta": delta, "count": len(ops), "sizes": sizes}
end

function short_list(names):
    width = max(40, term_columns() - 4)
    out = []
    used = 0
    i = 0
    for n in names:
        if used + len(n) + 2 > width * 2:
            return "  " + ", ".join(out) + ", " + _("+%d more").replace("%d", String(len(names) - i))
        end
        out.append(n)
        used += len(n) + 2
        i += 1
    end
    return "  " + ", ".join(out)
end

function show_plan(action, plan, to_add, to_remove):
    call emit(["PLAN", action, plan["count"], plan["download"], plan["delta"]])
    pool = to_add if len(to_add) > 0 else to_remove
    call compat("Packages (" + String(len(pool)) + ") " + " ".join([alpm.pkg_name(p) + "-" + alpm.pkg_version(p) for p in pool]))
    if ui["machine"]:
        return 0
    end
    add_names = [alpm.pkg_name(p) for p in to_add]
    removed = [p for p in to_remove if not (alpm.pkg_name(p) in add_names)]
    if ui["verbose"]:
        for p in to_add:
            old = alpm.db_get_pkg(localdb(), alpm.pkg_name(p))
            ver = (alpm.pkg_version(old) + " → " + alpm.pkg_version(p)) if old != 0 else alpm.pkg_version(p)
            db = alpm.pkg_db(p)
            dbname = alpm.db_name(db) if db != 0 else ""
            call write("  " + alpm.pkg_name(p) + " " + dim(ver) + " " + dim(dbname) + "  " + dim(fmt_size(alpm.pkg_download_size(p))))
        end
        for p in removed:
            call write("  " + red("-") + " " + alpm.pkg_name(p) + " " + dim(alpm.pkg_version(p)))
        end
    elif action in ["upgrade", "remove", "download"] or (len(removed) > 0 and action != "remove"):
        names = [alpm.pkg_name(p) for p in to_add] if action in ["upgrade", "download"] else []
        names = names + [alpm.pkg_name(p) for p in removed]
        call write(dim(short_list(names)))
    end
    if len(removed) > 0 and action != "remove":
        call warn(i18n.TF("Also removes: %s", [", ".join([alpm.pkg_name(p) for p in removed])]))
    end
    if ui.get("datasaver", False) and plan["download"] > 0:
        call note(i18n.TF("Data Saver is on - this downloads %s.", [fmt_size(plan["download"])]))
    end
    return 0
end

function check_holdpkg(to_remove):
    held = []
    for v in conf_list(lux["conf"], "HoldPkg"):
        for w in v.split(" "):
            if w != "":
                held.append(w)
            end
        end
    end
    hit = [alpm.pkg_name(p) for p in to_remove if alpm.pkg_name(p) in held]
    if len(hit) > 0:
        call warn(i18n.TF("These packages are essential for the system: %s", [", ".join(hit)]))
        ok = False
        if not ui["yes"] and not ui["machine"] and isatty(0):
            ok = ask(_("Remove them anyway?"), False)
        end
        if not ok:
            call raise_lux(LuxError("cancelled", _("Cancelled")))
        end
    end
    return 0
end

# ---- nove verze konfigurace (*.luxnew): lux_configmerge.py (hooky 90-lux-config-merge-*) ----

CONFIGMERGE = "/usr/lib/lux/lux_configmerge.py"
cfg = {"results": [], "shown": [], "result_path": ""}

function configs_enabled():
    return fs.access_x(CONFIGMERGE) and not lux.get("injected", False)
end

# Pred transakci: hook po transakci vysledky nevypise (lux je vypise v souhrnu), jen je zapise
function config_pre():
    if not configs_enabled():
        return 0
    end
    cfg["result_path"] = "/var/lib/lux/pristine/.result-" + String(fs.getpid()) + ".json"
    call sys.setenv("LUX_CONFIG_MERGE_QUIET", "1")
    call sys.setenv("LUX_CONFIG_MERGE_RESULT", cfg["result_path"])
    return 0
end

# Po transakci (a v lux update): slouceni cekajicich *.luxnew; vysledky hooku i tohoto slouceni
function config_post(seen):
    if not configs_enabled():
        return []
    end
    path = cfg["result_path"]
    if path == "":
        path = "/var/lib/lux/pristine/.result-" + String(fs.getpid()) + ".json"
        call sys.setenv("LUX_CONFIG_MERGE_RESULT", path)
    end
    call sys.setenv("LUX_CONFIG_MERGE_QUIET", "1")
    root = conf_get(lux["conf"], "RootDir", "/")
    dbpath = conf_get(lux["conf"], "DBPath", DEFAULT_DBPATH)
    argv = [CONFIGMERGE, "merge", "--root", root, "--dbpath", dbpath]
    for c in conf_list(lux["conf"], "CacheDir"):
        argv = argv + ["--cachedir", c]
    end
    r = process_capture(argv)
    if r[0] != 0:
        call compat("warning: config merge failed (" + r[2].strip() + ")")
    end
    results = []
    full = root.rstrip("/") + path
    text = ""
    safe:
        text = lglib.read_text(full)
    end
    call fs.unlink(full)
    call unsetenv("LUX_CONFIG_MERGE_RESULT")
    call unsetenv("LUX_CONFIG_MERGE_QUIET")
    cfg["result_path"] = ""
    if text != None and text.strip() != "":
        safe:
            data = json.decode(text)
            if type(data) == "List":
                results = [x for x in data if type(x) == "Dictionary" and not (x.get("path", "") in seen)]
            end
        end
    end
    return results
end

function show_config_results(results):
    for r in results:
        call emit(["CONFIG", r.get("status", ""), r.get("path", "")])
    end
    if ui["machine"]:
        return 0
    end
    for r in results:
        if r.get("status", "") == "merged":
            call ok_line(i18n.TF("Updated %s; your settings were kept", [r["path"]]))
        else:
            call warn(i18n.TF("The new version of %s could not be combined with your changes automatically.", [r["path"]]))
            call note("  " + i18n.TF("Your current file stays in use and the system works normally. To review it: sudo lux config-diff %s", [r["path"]]))
        end
    end
    return 0
end

function summary(action, plan, to_add, to_remove, explicit, ms, flags):
    pool = to_add if action != "remove" else to_remove
    exp = []
    ndeps = 0
    if action == "upgrade":
        ndeps = plan["count"]
    else:
        for p in pool:
            if alpm.pkg_name(p) in explicit:
                exp.append([alpm.pkg_name(p), alpm.pkg_version(p)])
            else:
                ndeps += 1
            end
        end
    end
    if flags & alpm.FLAG_DOWNLOADONLY != 0:
        action = "download"
    end
    call ok_line(summary_line(action, exp, ndeps, ms))
    call emit(["SUMMARY", action, plan["count"], plan["download"], plan["delta"], one_decimal(Float(ms) / 1000.0)])
    if configs_enabled() and flags & alpm.FLAG_DOWNLOADONLY == 0:
        call show_config_results(cfg["results"])
        for r in cfg["results"]:
            cfg["shown"].append(r.get("path", ""))
        end
    elif cb["pacnew"] > 0:
        call warn(i18n.TF("New config files to review: %d (run: lux configs)", [String(cb["pacnew"])]).replace("%d", String(cb["pacnew"])))
    end
    if len(cb["scriptlet"]) > 0 and not ui["verbose"] and not ui["machine"]:
        for line in cb["scriptlet"][0:5]:
            call note("  " + line.strip())
        end
        if len(cb["scriptlet"]) > 5:
            call note("  " + _("+%d more").replace("%d", String(len(cb["scriptlet"]) - 5)) + " (--verbose)")
        end
    end
    return 0
end

# ---- ochrana systemu (luxos_protect.writable z LuxOS Care): /usr zapisovatelny jen po dobu commitu ----

PROTECT_LOCK = "/run/luxos-protect/lock"
protect = {"fd": -1}

# LUXOS_CARE_ROOT: testovaci koren LuxOS Care (jako luxos_care.P)
function care_path(path):
    return env.get("LUXOS_CARE_ROOT", "").rstrip("/") + path
end

function usr_mount_state():
    found = None
    for line in read_small(care_path("/proc/self/mountinfo")).split(chr(10)):
        parts = line.split(" ")
        if len(parts) < 7 or parts[4] != "/usr":
            continue
        end
        found = "ro" if "ro" in parts[5].split(",") else "rw"
    end
    return found if found != None else "off"
end

function in_chroot():
    a = fs.stat("/")
    b = fs.stat("/proc/1/root/.")
    if a == None or b == None:
        return False
    end
    return a["dev"] != b["dev"] or a["ino"] != b["ino"]
end

function protect_enabled():
    for line in read_small(care_path("/etc/luxos/care.conf")).split(chr(10)):
        t = line.strip()
        if t.startswith("PROTECT="):
            return t[8:].strip().lower() in ["yes", "1", "true", "on"]
        end
    end
    return False
end

function remount_usr(readonly):
    opt = "remount,bind," + ("ro" if readonly else "rw")
    tries = 5 if readonly else 1
    i = 0
    while i < tries:
        r = process_capture(["mount", "-o", opt, "/usr"])
        if r[0] == 0:
            return True
        end
        if not readonly or not ("busy" in (r[1] + r[2]).lower()):
            return False
        end
        call fs.sleep_ms(400 * (i + 1))
        i += 1
    end
    return False
end

function protect_unlock(flags):
    if flags & alpm.FLAG_DOWNLOADONLY != 0 or (fs.geteuid() != 0 and env.get("LUXOS_CARE_ROOT", "") == "") or usr_mount_state() == "off" or in_chroot():
        return 0
    end
    call sys.mkdir_p("/run/luxos-protect")
    fd = fs.open(PROTECT_LOCK, 2 + fs.O_CREAT + fs.O_CLOEXEC, 384)
    if fd < 0:
        call raise_lux(LuxError("protected", _("Protected system files could not be opened for the update."), 1, [PROTECT_LOCK]))
    end
    protect["fd"] = fd
    call fs.flock_sh(fd)
    if usr_mount_state() == "ro" and not remount_usr(False):
        call fs.close(fd)
        protect["fd"] = -1
        call raise_lux(LuxError("protected", _("Protected system files could not be opened for the update."), 1, ["unlock_failed"]))
    end
    return 0
end

function protect_relock():
    fd = protect["fd"]
    if fd < 0:
        return 0
    end
    protect["fd"] = -1
    if protect_enabled() and usr_mount_state() == "rw" and fs.flock_nb(fd):
        call remount_usr(True)
    end
    call fs.close(fd)
    return 0
end

# ---- transakce ----

function transaction(action, add, remove, sysupgrade, flags, explicit, attempts=3):
    call need_root()
    confirmed = False
    add = [x for x in add]
    check_gpu = True
    attempt = 1
    corrupt_retried = []
    while True:
        lux["flow"] = None
        result = 0
        try:
            result = transaction_once(action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu)
        else:
            flow = lux.get("flow", None)
            if flow == None:
                Error(LuxRaised: String(last_error()))
            end
            lux["flow"] = None
            kind = flow["kind"]
            if kind == "corrupt":
                confirmed = True
                names = [n for n in (flow["names"] if len(flow["names"]) > 0 else corrupt_retried) if n != "?"]
                if len(corrupt_retried) > 0:
                    if len(names) > 0:
                        msg = i18n.TF("The package %s was damaged again after a new download. The server may be updating it - try again later.", [", ".join(names)])
                    else:
                        msg = _("A downloaded package was damaged again after a new download. The server may be updating it - try again later.")
                    end
                    call raise_lux(LuxError("corrupt", msg, 1, flow["error"]["details"]))
                end
                corrupt_retried = names if len(names) > 0 else ["?"]
                call emit(["RETRY", "corrupt"])
                if not ui["machine"]:
                    if len(names) > 0:
                        call write(yellow("↻ ") + i18n.TF("Downloaded package %s was damaged, downloading it again…", [", ".join(names)]))
                    else:
                        call write(yellow("↻ ") + _("A downloaded package was damaged, downloading it again…"))
                    end
                end
            elif kind == "reprovide":
                check_gpu = False
                add = add + flow["extra"]
            elif kind == "sysupgrade":
                call confirm_sysupgrade(flow["names"])
                sysupgrade = True
            elif kind == "retry":
                confirmed = True
                if attempt == attempts:
                    call raise_lux(flow["error"])
                end
                attempt += 1
                call retry_notice(attempt, attempts)
            end
            continue
        end
        return result
    end
    return 0
end

function package_from_file(path):
    base = base_name(path)
    if base.endswith(".sig"):
        base = base[0:len(base) - 4]
    end
    i = base.find(".pkg.tar")
    if i >= 0:
        base = base[0:i]
    end
    parts = base.split("-")
    if len(parts) >= 4:
        return "-".join(parts[0:len(parts) - 3])
    end
    return base
end

function trans_error_details(h, data):
    code = alpm.errno(h)
    return [alpm.strerror(code), code, alpm.describe_data(code, data)]
end

function transaction_once(action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu):
    h = lux["h"]
    call cb_reset()
    call wait_for_lock()
    if alpm.trans_init(h, flags) != 0:
        msg = alpm.strerror(alpm.errno(h))
        call compat("error: failed to init transaction (" + msg + ")")
        kind = classify(msg)
        call raise_lux(LuxError(kind, plain_message(kind), 1, [msg]))
    end
    lux["trans"] = True
    result = 0
    try:
        result = transaction_body(h, action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu)
    else:
        lux["trans"] = False
        lux["in_commit"] = False
        call alpm.trans_release(h)
        Error(LuxRaised: String(last_error()))
    end
    lux["trans"] = False
    lux["in_commit"] = False
    call alpm.trans_release(h)
    return result
end

function transaction_body(h, action, add, remove, sysupgrade, flags, explicit, confirmed, check_gpu):
    # cile pred sysupgrade jako pacman -Syu balik
    failed_add = ""
    for p in add:
        if alpm.add_pkg(h, p) != 0 and alpm.errno(h) != 25:
            failed_add = alpm.strerror(alpm.errno(h))
        end
    end
    if sysupgrade:
        call alpm.sync_sysupgrade(h, False)
    end
    for p in remove:
        if alpm.remove_pkg(h, p) != 0 and alpm.errno(h) != 25:
            failed_add = alpm.strerror(alpm.errno(h))
        end
    end
    prep = [0, 0]
    if failed_add == "":
        prep = alpm.trans_prepare(h)
    end
    if failed_add != "" or prep[0] != 0:
        e = trans_error_details(h, prep[1])
        msg = failed_add if failed_add != "" else e[0]
        det = e[2]
        call compat("error: failed to prepare transaction (" + msg + ")")
        for d in det:
            call compat(":: " + d)
        end
        kind = classify(msg + chr(10) + chr(10).join(det))
        if kind == "unknown" and "target" in msg:
            kind = "notfound"
        end
        if kind == "unknown" and e[1] in [alpm.ERR_DB_INVALID, alpm.ERR_DB_INVALID_SIG]:
            kind = "dbinvalid"
        end
        detail = ", ".join(det[0:5]) if kind == "deps" else ""
        call raise_lux(LuxError(kind, plain_message(kind, detail), 1, [msg] + det + cb["log_errors"]))
    end
    to_add = alpm.trans_add(h)
    to_remove = alpm.trans_remove(h)
    if len(to_add) == 0 and len(to_remove) == 0:
        return 0
    end
    if check_gpu:
        extra = better_gpu_providers(add, to_add)
        if len(extra) > 0:
            call raise_flow({"kind": "reprovide", "extra": extra})
        end
    end
    if action == "install" and not sysupgrade and not confirmed:
        risky = partial_upgrade_risk(to_add)
        if len(risky) > 0:
            call raise_flow({"kind": "sysupgrade", "names": risky})
        end
    end
    plan = make_plan(to_add, to_remove)
    if not confirmed:
        call show_plan(action, plan, to_add, to_remove)
        if action == "remove":
            call check_holdpkg(to_remove)
        end
        if not ask(plan_question(action, plan["count"], plan["download"], plan["delta"])):
            call raise_lux(LuxError("cancelled", _("Cancelled")))
        end
    end
    call cb_reset("commit", plan["download"], plan["ops"], plan["sizes"])
    start = fs.monotonic_ms()
    files = flags & alpm.FLAG_DOWNLOADONLY == 0
    if files:
        call config_pre()
    end
    call protect_unlock(flags)
    lux["in_commit"] = True
    # callbacky v detskem procesu (scriptlety, hooky) odpoji libalpm sam: lux-engine zaplata 0004
    res = alpm.trans_commit(h)
    lux["in_commit"] = False
    call protect_relock()
    call pump_signals(True)
    if res[0] != 0:
        e = trans_error_details(h, res[1])
        if files:
            cfg["results"] = config_post([])
        end
        msg = e[0]
        det = e[2]
        call phase_done(False)
        call compat("error: failed to commit transaction (" + msg + ")")
        for d in det:
            call compat(d)
        end
        text = chr(10).join([msg] + det + cb["log_errors"])
        kind = classify(text)
        if lux.get("interrupted", False):
            call raise_lux(LuxError("interrupted", _("Cancelled"), 130, [msg] + det))
        end
        if kind == "network" and stale_download(text):
            kind = "outdated"
        end
        err = LuxError(kind, plain_message(kind), 1, [msg] + det + cb["log_errors"])
        # sit: nic se jeste neinstalovalo (stahuje se pred instalaci) -> zopakovat
        if kind == "network" and cb["current"] == None:
            call raise_flow({"kind": "retry", "error": err})
        end
        # poskozeny balik z mezipameti (kontrolni soucet i podpis, ktery poskozeni rozbije - libalpm se
        # zepta CORRUPTED_PKG): smazat a stahnout znovu
        if (kind == "corrupt" or len(cb["corrupted"]) > 0) and cb["current"] == None:
            names = []
            for f in cb["corrupted"]:
                call fs.unlink(f)
                n = package_from_file(f)
                if not (n in names):
                    names.append(n)
                end
            end
            call raise_flow({"kind": "corrupt", "error": err, "names": sorted(names)})
        end
        call raise_lux(err)
    end
    if lux.get("interrupted", False):
        if files:
            cfg["results"] = config_post([])
        end
        call phase_done(False)
        call raise_lux(LuxError("interrupted", _("Cancelled"), 130, [_("Stopped part-way: only some packages were installed. Finish with: lux update")]))
    end
    call phase_done(True)
    if files:
        cfg["results"] = config_post([])
    end
    call summary(action, plan, to_add, to_remove, explicit, fs.monotonic_ms() - start, flags)
    return plan["count"]
end

# ---- prikazy, ktere meni system ----

KEYRINGS = ["archlinux-keyring", "luxos-keyring"]

function cmd_sync(args):
    call refresh(args["force"])
    return 0
end

# -> [balicky, nazvy cilu, nenalezene, preskocene]
function resolve_targets(targets, needed):
    pkgs = []
    names = []
    missing = []
    skipped = []
    local = localdb()
    for t in targets:
        found = []
        if is_pkgfile(t) and is_file(t):
            found = [load_file(abspath(t))]
        elif "://" in t:
            call raise_lux(LuxError("usage", i18n.TF("Installing from a URL is not supported, download the file first: %s", [t])))
        else:
            found = find_sync(t)
        end
        if len(found) == 0:
            missing.append(t)
            continue
        end
        for p in found:
            old = alpm.db_get_pkg(local, alpm.pkg_name(p))
            if needed and old != 0 and alpm.vercmp(alpm.pkg_version(old), alpm.pkg_version(p)) == 0:
                skipped.append(alpm.pkg_name(p))
                continue
            end
            pkgs.append(p)
            names.append(alpm.pkg_name(p))
        end
    end
    return [pkgs, names, missing, skipped]
end

function cmd_install(args):
    if args["refresh"]:
        call refresh()
    end
    r = resolve_targets(args["targets"], args["needed"])
    if len(r[2]) > 0:
        call compat("error: target not found: " + " ".join(r[2]))
        return LuxError("notfound", plain_message("notfound", r[2][0]), 1, ["target not found: " + m for m in r[2]])
    end
    if len(r[3]) > 0:
        call compat(" ".join(["warning: " + n + " is up to date -- skipping" for n in r[3]]))
        call ok_line(i18n.TF("Already installed: %s", [", ".join(r[3])]))
    end
    if len(r[0]) == 0:
        return 0
    end
    flags = 0
    if args["needed"]:
        flags += alpm.FLAG_NEEDED
    end
    if args["asdeps"]:
        flags += alpm.FLAG_ALLDEPS
    end
    if args["download_only"]:
        flags += alpm.FLAG_DOWNLOADONLY
    end
    call transaction("install", r[0], [], False, flags, r[1])
    return 0
end

function cached_file(name, version):
    dirs = conf_list(lux["conf"], "CacheDir")
    if len(dirs) == 0:
        dirs = [DEFAULT_CACHEDIR]
    end
    prefix = name + "-" + version + "-"
    for d in dirs:
        if not d.endswith("/"):
            d = d + "/"
        end
        for f in sorted(sys.list_dir(d)):
            if f.startswith(prefix) and (f.endswith(".pkg.tar.zst") or f.endswith(".pkg.tar.xz")):
                arch = f[len(prefix):]
                arch = arch[0:arch.find(".pkg.tar")]
                if arch != "" and not ("-" in arch):
                    return d + f
                end
            end
        end
    end
    return None
end

function cmd_reinstall(args):
    local = localdb()
    pkgs = []
    names = []
    for t in args["targets"]:
        if is_pkgfile(t) and is_file(t):
            p = load_file(abspath(t))
            pkgs.append(p)
            names.append(alpm.pkg_name(p))
            continue
        end
        old = alpm.db_get_pkg(local, t)
        if old == 0:
            return LuxError("notinstalled", i18n.TF("Package '%s' is not installed", [t]))
        end
        found = [p for p in find_sync(t) if alpm.pkg_name(p) == t and alpm.vercmp(alpm.pkg_version(p), alpm.pkg_version(old)) == 0]
        if len(found) == 0:
            cached = cached_file(t, alpm.pkg_version(old))
            if cached == None:
                return LuxError("notfound", i18n.TF("%s %s is not in the repositories or the package cache", [t, alpm.pkg_version(old)]))
            end
            found = [load_file(cached)]
        end
        pkgs = pkgs + found
        names.append(t)
    end
    call transaction("reinstall", pkgs, [], False, 0, names)
    return 0
end

function cmd_remove(args):
    local = localdb()
    pkgs = []
    names = []
    missing = []
    for t in args["targets"]:
        p = alpm.db_get_pkg(local, t)
        if p == 0:
            members = alpm.db_group_pkgs(local, t)
            if len(members) > 0:
                pkgs = pkgs + members
                names = names + [alpm.pkg_name(m) for m in members]
                continue
            end
            missing.append(t)
            continue
        end
        pkgs.append(p)
        names.append(t)
    end
    if len(missing) > 0:
        call compat("error: target not found: " + " ".join(missing))
        return LuxError("notinstalled", i18n.TF("Package '%s' is not installed", [missing[0]]))
    end
    # bez --nosave zustanou zmenene konfiguracni soubory jako *.luxsave (jako pacman -Rs)
    flags = alpm.FLAG_RECURSE
    if args["nosave"]:
        flags += alpm.FLAG_NOSAVE
    end
    if args["cascade"]:
        flags += alpm.FLAG_CASCADE
    end
    call transaction("remove", [], pkgs, False, flags, names)
    return 0
end

function cmd_autoremove(args):
    pkgs = orphans()
    if len(pkgs) == 0:
        call ok_line(_("No unneeded packages"))
        return 0
    end
    call transaction("remove", [], pkgs, False, alpm.FLAG_RECURSE + alpm.FLAG_NOSAVE, [alpm.pkg_name(p) for p in pkgs])
    return 0
end

function newer_keyrings():
    local = localdb()
    out = []
    for k in KEYRINGS:
        old = alpm.db_get_pkg(local, k)
        if old == 0:
            continue
        end
        new = alpm.sync_new_version(old, syncdbs("Upgrade"))
        if new != 0:
            out.append(new)
        end
    end
    return out
end

function cmd_upgrade(args):
    if args["refresh"]:
        call refresh()
    end
    flags = alpm.FLAG_DOWNLOADONLY if args["download_only"] else 0
    action = "download" if args["download_only"] else "upgrade"
    if args["keyring_first"] and not args["download_only"]:
        keys = newer_keyrings()
        if len(keys) > 0:
            # bez otazky (pacman -S --needed --noconfirm archlinux-keyring); otazka je az na system
            call say(_("Updating signing keys"))
            saved = ui["yes"]
            ui["yes"] = True
            try:
                call transaction("upgrade", keys, [], False, alpm.FLAG_NEEDED, [alpm.pkg_name(k) for k in keys])
            else:
                ui["yes"] = saved
                Error(LuxRaised: String(last_error()))
            end
            ui["yes"] = saved
        end
    end
    n = transaction(action, [], [], True, flags, [])
    if n == 0:
        call compat(" there is nothing to do")
        call ok_line(_("System packages are up to date"))
    end
    if not args["download_only"]:
        call show_config_results(config_post(cfg["shown"]))
    end
    return 0
end

# ---- mezipamet balicku ----

# nazev-verze-rel-arch.pkg.tar[.ext] -> [nazev, verze-rel, arch] nebo None
function parse_pkg_file(fname):
    i = fname.find(".pkg.tar")
    if i < 0:
        return None
    end
    rest = fname[i + 8:]
    if rest != "" and not (rest.startswith(".") and not ("." in rest[1:]) and is_alnum(rest[1:])):
        return None
    end
    parts = fname[0:i].split("-")
    if len(parts) < 4:
        return None
    end
    n = len(parts)
    return ["-".join(parts[0:n - 3]), parts[n - 3] + "-" + parts[n - 2], parts[n - 1]]
end

function cache_plan(files, installed, keep, keep_uninstalled):
    groups = {}
    order = []
    for f in files:
        m = parse_pkg_file(base_name(f))
        if m == None:
            continue
        end
        key = m[0] + " " + m[2]
        if not (key in groups):
            groups[key] = []
            order.append(key)
        end
        groups[key].append([m[1], f, m[0]])
    end
    out = []
    for key in order:
        items = groups[key]
        # razeni od nejnovejsi verze (vercmp), vlozenim
        sorted_items = []
        for it in items:
            j = 0
            while j < len(sorted_items) and alpm.vercmp(sorted_items[j][0], it[0]) >= 0:
                j += 1
            end
            sorted_items.insert(j, it)
        end
        n = keep if items[0][2] in installed else keep_uninstalled
        for it in sorted_items[n:]:
            out.append(it[1])
        end
    end
    return sorted(out)
end

function human_size(n):
    v = Float(n)
    for unit in ["B", "kB", "MB", "GB"]:
        if (v < 1024.0 and v > -1024.0) or unit == "GB":
            if unit == "B":
                return String(Int(v + 0.5)) + " " + unit
            end
            return decimal(one_decimal(v) + " " + unit)
        end
        v = v / 1024.0
    end
    return String(n)
end

function cmd_clean(args):
    call need_root()
    call wait_for_lock()
    lock = lock_path()
    if not fs.create_excl(lock, 384):
        return LuxError("locked", plain_message("locked"), 1, [lock])
    end
    result = 0
    try:
        result = clean_cache(args)
    else:
        call fs.unlink(lock)
        Error(LuxRaised: String(last_error()))
    end
    call fs.unlink(lock)
    return result
end

function clean_cache(args):
    dirs = conf_list(lux["conf"], "CacheDir")
    if len(dirs) == 0:
        dirs = [DEFAULT_CACHEDIR]
    end
    files = []
    for d in dirs:
        if not d.endswith("/"):
            d = d + "/"
        end
        for f in sys.list_dir(d):
            if parse_pkg_file(f) != None:
                files.append(d + f)
            end
        end
    end
    installed = {}
    for p in alpm.db_pkgcache(localdb()):
        installed[alpm.pkg_name(p)] = True
    end
    remove = cache_plan(files, installed, args["keep"], args["keep_uninstalled"])
    freed = 0
    for f in remove:
        for path in [f, f + ".sig"]:
            size = fs.file_size(path)
            if size >= 0 and fs.unlink(path):
                freed += size
            end
        end
    end
    call emit(["SUMMARY", "clean", len(remove), 0, -freed, 0])
    if len(remove) > 0:
        call ok_line(i18n.TF("Removed %d old package files from the cache (%s freed)", [String(len(remove)), human_size(freed)]).replace("%d", String(len(remove))))
    else:
        call ok_line(_("The package cache is already clean"))
    end
    return 0
end

# ---- prechod z pacmanu (LuxOS do 0.9.5) a klice live ISO ----

MIGRATE = "/usr/share/libalpm/scripts/lux-engine-migrate"

function migration_pending():
    for p in ["/var/lib/pacman", "/etc/pacman.conf", "/etc/pacman.conf.pacsave", "/etc/pacman.conf.luxsave",
              "/var/log/pacman.log"]:
        if sys.lexists(p):
            return True
        end
    end
    return is_link("/usr/lib/lux/alpm/bin/pacman") or is_link("/var/cache/pacman/pkg")
end

function maybe_migrate(now=False, force=False):
    migrate = env.get("LUX_MIGRATE", MIGRATE)
    if fs.geteuid() != 0 or not fs.access_x(migrate) or not (force or migration_pending()):
        return 0
    end
    if len(running_package_managers()) > 0:
        return 0
    end
    locked = False
    if lglib.is_dir("/var/lib/pacman") and not is_link("/var/lib/pacman"):
        if sys.lexists("/var/lib/pacman/db.lck") or sys.lexists(DEFAULT_DBPATH + "db.lck"):
            return 0
        end
        if not fs.create_excl("/var/lib/pacman/db.lck", 420):
            return 0
        end
        locked = True
    end
    argv = [migrate, "auto"] + (["--now"] if now else []) + ["--ignore-pid", String(fs.getpid())]
    r = process_capture(argv)
    for line in r[2].split(chr(10)):
        if line != "":
            call note(line)
        end
    end
    if locked:
        if not fs.unlink(DEFAULT_DBPATH + "db.lck"):
            call fs.unlink("/var/lib/pacman/db.lck")
        end
    end
    return r[0]
end

function wait_live_keyring():
    if not lglib.is_dir("/run/archiso") or fs.geteuid() != 0:
        return 0
    end
    unit = "lux-keyring-init.service"
    if process_capture(["systemctl", "is-active", "--quiet", unit])[0] == 0:
        return 0
    end
    if process_capture(["systemctl", "cat", unit])[0] != 0:
        return 0
    end
    call note(_("Preparing the package signing keys…"))
    call process_capture(["systemctl", "start", unit])
    return 0
end

function cmd_migrate(args):
    call need_root()
    rc = maybe_migrate(args["now"], True)
    if rc == 0:
        call ok_line(_("The package manager uses /etc/lux and /var/lib/lux"))
    end
    return rc
end

# ---- prikazova radka ----

COMMANDS = ["available", "sync", "install", "reinstall", "remove", "autoremove", "upgrade", "update", "search",
            "info", "list", "files", "owns", "resolve", "check-updates", "clean", "migrate"]
ROOT_CMDS = ["sync", "install", "reinstall", "remove", "autoremove", "upgrade", "update", "clean"]
LIST_MODES = ["installed", "explicit", "foreign", "orphans", "sync", "upgradable"]
# prepinace prikazu: nazev -> klic v args (bez hodnoty)
SWITCHES = {"sync": {"--force": "force"},
            "install": {"--needed": "needed", "--asdeps": "asdeps", "--refresh": "refresh", "--download-only": "download_only"},
            "remove": {"--cascade": "cascade", "--nosave": "nosave"},
            "upgrade": {"--refresh": "refresh", "--download-only": "download_only", "--keyring-first": "keyring_first"},
            "update": {"--refresh": "refresh", "--download-only": "download_only", "--keyring-first": "keyring_first"},
            "search": {"--installed": "installed"}, "info": {"--sync": "sync"}, "migrate": {"--now": "now"}}
# prepinace s hodnotou
VALUED = {"check-updates": {"--db": "db"}, "clean": {"--keep": "keep", "--keep-uninstalled": "keep_uninstalled"}}
INT_VALUES = ["keep", "keep_uninstalled"]

function usage_error(message):
    call sys.eprint("usage: lux-alpm [-y] [-v] [--machine] [--color {auto,always,never}] [--lang LANG] [--datasaver] COMMAND ...")
    call sys.eprint("lux-alpm: error: " + message)
    return 2
end

# argv -> [globalni, argumenty prikazu] nebo [None, chyba]
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
        elif a == "-y" or a == "--yes" or a == "--noconfirm":
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
            "verbose": opts["verbose"], "force": False, "needed": False, "asdeps": False, "refresh": cmd == "update",
            "download_only": False, "keyring_first": cmd == "update", "cascade": False, "nosave": False,
            "now": False, "keep": 2, "keep_uninstalled": 0}
    switches = SWITCHES.get(cmd, {})
    valued = VALUED.get(cmd, {})
    pos = []
    j = 0
    while j < len(rest):
        a = rest[j]
        j += 1
        if a in switches:
            args[switches[a]] = True
        elif cmd == "list" and a.startswith("--") and a[2:] in LIST_MODES:
            if args["mode"] != None and args["mode"] != a[2:]:
                return [None, "argument --" + a[2:] + ": not allowed with argument --" + args["mode"]]
            end
            args["mode"] = a[2:]
        elif a in valued or ("=" in a and a[0:a.find("=")] in valued):
            key = a
            value = None
            if "=" in a:
                key = a[0:a.find("=")]
                value = a[a.find("=") + 1:]
            elif j < len(rest):
                value = rest[j]
                j += 1
            else:
                return [None, "argument " + a + ": expected one argument"]
            end
            name = valued[key]
            if name in INT_VALUES:
                if not is_digits(value):
                    return [None, "argument " + key + ": invalid int value: '" + value + "'"]
                end
                value = Int(value)
            end
            args[name] = value
        elif a == "--":
            pos = pos + rest[j:]
            break
        elif a.startswith("-") and a != "-":
            return [None, "unrecognized arguments: " + a]
        else:
            pos.append(a)
        end
    end
    if args["mode"] == None:
        args["mode"] = "installed"
    end
    if cmd in ["search"]:
        if len(pos) == 0:
            return [None, "the following arguments are required: terms"]
        end
        args["terms"] = pos
    elif cmd in ["info", "files"]:
        if len(pos) != 1:
            return [None, "the following arguments are required: package" if len(pos) == 0 else "unrecognized arguments: " + " ".join(pos[1:])]
        end
        args["package"] = pos[0]
    elif cmd == "list":
        if len(pos) > 1:
            return [None, "unrecognized arguments: " + " ".join(pos[1:])]
        end
        if len(pos) == 1:
            args["pattern"] = pos[0]
        end
    elif cmd == "owns":
        if len(pos) == 0:
            return [None, "the following arguments are required: paths"]
        end
        args["paths"] = pos
    elif cmd in ["install", "reinstall", "remove", "resolve"]:
        if len(pos) == 0:
            return [None, "the following arguments are required: targets"]
        end
        args["targets"] = pos
    elif len(pos) > 0:
        return [None, "unrecognized arguments: " + " ".join(pos)]
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
    elif cmd == "sync":
        return cmd_sync(args)
    elif cmd == "install":
        return cmd_install(args)
    elif cmd == "reinstall":
        return cmd_reinstall(args)
    elif cmd == "remove":
        return cmd_remove(args)
    elif cmd == "autoremove":
        return cmd_autoremove(args)
    elif cmd == "upgrade" or cmd == "update":
        return cmd_upgrade(args)
    elif cmd == "clean":
        return cmd_clean(args)
    elif cmd == "migrate":
        return cmd_migrate(args)
    end
    return cmd_resolve(args)
end

function show_error(err, opts):
    call emit(["ERROR", err["kind"], err["message"]])
    call fail(err["message"])
    details = err.get("details", [])
    if len(details) > 0 and (opts["verbose"] or ui["machine"]):
        for d in details:
            call write(("" if ui["machine"] else "  ") + String(d), True)
        end
    elif len(details) > 0 and not (err["kind"] in ["cancelled", "notfound", "confirm"]):
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
            call note("  " + _("More details: run the command again with --verbose"))
        end
    end
    return 0
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
    # nastroje jadra (lux-engine) v PATH pro hooky a scriptlety
    path = env.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/bin")
    parts = [p for p in path.split(":") if p != "" and p != "/usr/lib/lux/alpm/bin"]
    call sys.setenv("PATH", ":".join(["/usr/lib/lux/alpm/bin"] + parts))
    ui["machine"] = opts["machine"]
    ui["verbose"] = opts["verbose"]
    ui["yes"] = opts["yes"]
    ui["datasaver"] = opts["datasaver"]
    ui["tty"] = (not opts["machine"]) and isatty(1)
    if opts["color"] == "always":
        ui["color"] = True
    elif opts["color"] == "never" or opts["machine"]:
        ui["color"] = False
    else:
        ui["color"] = ui["tty"] and env.get("NO_COLOR", "") == ""
    end
    call cb_reset()
    call install_signals()
    lux["transaction"] = args["cmd"] in ROOT_CMDS
    if args["cmd"] in ROOT_CMDS:
        call maybe_migrate()
        call wait_live_keyring()
    end
    rc = 0
    try:
        call h()
        result = dispatch(args)
        if type(result) == "Dictionary" and result.get("lux_error", False):
            rc = result["rc"]
            call phase_done(False)
            call show_error(result, opts)
        else:
            rc = result
        end
    else:
        if lux["raised"] != None:
            err = lux["raised"]
            rc = err["rc"]
            call phase_done(False)
            call show_error(err, opts)
        elif lux["keyboard"]:
            call phase_done(False)
            call fail(_("Cancelled"))
            rc = 130
        else:
            e = String(last_error())
            rc = EXIT_UNAVAILABLE
            call phase_done(False)
            if args["cmd"] == "available" or opts["verbose"]:
                call sys.eprint("lux: " + e)
            end
            call emit(["UNAVAILABLE", e])
        end
    end
    if check_lock["fd"] >= 0:
        call fs.close(check_lock["fd"])
    end
    call emit(["DONE", rc])
    return rc
end

call exit(main())
