# lsl: link libalpm.so.16
# LuxOS - vazby na libalpm (jadro spravce baliku, lux-engine) pro lux v LSL; nahrada pyalpm.
#
# Ukazatele z C jsou cela cisla (handle, databaze, balicek, alpm_list_t). Retezce a seznamy se ctou hned
# do hodnot LSL; seznamy vracene libalpm, ktere vlastni volajici (compute_requiredby, search, group pkgs),
# se po precteni uvolni. Balicky v databazich patri libalpm a plati do release(handle).
#
#   h = luxalpm.initialize(root, dbpath)      0 = chyba (luxalpm.last_error())
#   luxalpm.release(h), add_architecture(h, arch), add_cachedir(h, dir) ...
#   localdb(h), register_syncdb(h, name, siglevel), syncdbs(h) -> [db]
#   db_name(db), db_pkgcache(db) -> [pkg], db_get_pkg(db, name), db_search(db, [slova]) -> [pkg]
#   pkg_*(pkg): name, version, desc, url, builddate, installdate, packager, size, isize, reason, db,
#               licenses, groups (retezce), depends, optdepends, conflicts, provides, replaces (retezce
#               jako "glibc>=2.40", u optdepends "nazev: popis"), files -> [cesta], requiredby
#   sync_new_version(pkg, [db]) -> pkg nebo 0, find_satisfier(h, [db], "zavislost") -> pkg nebo 0
#   find_group_pkgs([db], skupina) -> [pkg], vercmp(a, b)
load glib

SIG_PACKAGE = 1
SIG_PACKAGE_OPTIONAL = 2
SIG_PACKAGE_MARGINAL_OK = 4
SIG_PACKAGE_UNKNOWN_OK = 8
SIG_DATABASE = 1024
SIG_DATABASE_OPTIONAL = 2048
SIG_DATABASE_MARGINAL_OK = 4096
SIG_DATABASE_UNKNOWN_OK = 8192
SIG_USE_DEFAULT = 1073741824

USAGE_SYNC = 1
USAGE_SEARCH = 2
USAGE_INSTALL = 4
USAGE_UPGRADE = 8
USAGE_ALL = 15

REASON_EXPLICIT = 0
REASON_DEPEND = 1

state = {"errno": 0}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function text(address):
    return glib.from_c(address)
end

# ---- alpm_list_t: { void *data; prev; next } ----

function list_items(list):
    out = []
    unsafe:
        node = ptr(list)
        while node != 0:
            out.append(__lsl_qbe_load64(node))
            node = __lsl_qbe_load64(node + 16)
        end
    end
    return out
end

function list_texts(list):
    return [text(p) for p in list_items(list)]
end

function list_free(list):
    unsafe:
        if ptr(list) != 0:
            call __lsl_qbe_call1(__lsl_symbol("alpm_list_free"), ptr(list))
        end
    end
    return 0
end

# Seznam LSL ukazatelu -> novy alpm_list_t (uvolnit list_free; data patri volajicimu)
function list_new(items):
    out = 0
    unsafe:
        for item in items:
            out = __lsl_qbe_call2(__lsl_symbol("alpm_list_add"), out, ptr(item))
        end
    end
    return out
end

# Seznam retezcu -> alpm_list_t s kopiemi (strdup); uvolnit list_free_texts
function list_new_texts(items):
    out = 0
    unsafe:
        for item in items:
            out = __lsl_qbe_call2(__lsl_symbol("alpm_list_add"), out,
                                  __lsl_qbe_call1(__lsl_symbol("strdup"), cstr(item)))
        end
    end
    return out
end

function list_free_texts(list):
    unsafe:
        if ptr(list) != 0:
            call __lsl_qbe_call2(__lsl_symbol("alpm_list_free_inner"), ptr(list), __lsl_symbol("free"))
            call __lsl_qbe_call1(__lsl_symbol("alpm_list_free"), ptr(list))
        end
    end
    return 0
end

# Seznam alpm_depend_t -> retezce (alpm_dep_compute_string, kopie se uvolni)
function list_deps(list):
    out = []
    unsafe:
        for dep in list_items(list):
            s = __lsl_qbe_call1(__lsl_symbol("alpm_dep_compute_string"), ptr(dep))
            out.append(text(s))
            call __lsl_qbe_call1(__lsl_symbol("free"), s)
        end
    end
    return out
end

# ---- handle ----

function initialize(root, dbpath):
    unsafe:
        err = __lsl_byte_zeros(8)
        h = __lsl_qbe_call3(__lsl_symbol("alpm_initialize"), cstr(root), cstr(dbpath),
                            __lsl_qbe_load64(__lsl_address(err) + 24))
        if h == 0:
            state["errno"] = __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_load64(__lsl_address(err) + 24)))
        end
        return h
    end
end

function release(h):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_release"), ptr(h))
    end
end

# Text posledni chyby (handle nebo initialize)
function last_error(h):
    unsafe:
        code = state["errno"]
        if ptr(h) != 0:
            code = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("alpm_errno"), ptr(h)))
        end
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_strerror"), ptr(code)))
    end
end

function add_architecture(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_architecture"), ptr(h), cstr(value)))
    end
end

function add_cachedir(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_cachedir"), ptr(h), cstr(value)))
    end
end

function add_hookdir(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_hookdir"), ptr(h), cstr(value)))
    end
end

function add_noupgrade(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_noupgrade"), ptr(h), cstr(value)))
    end
end

function add_noextract(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_noextract"), ptr(h), cstr(value)))
    end
end

function add_ignorepkg(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_ignorepkg"), ptr(h), cstr(value)))
    end
end

function add_ignoregroup(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_add_ignoregroup"), ptr(h), cstr(value)))
    end
end

function set_gpgdir(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_gpgdir"), ptr(h), cstr(value)))
    end
end

function set_logfile(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_logfile"), ptr(h), cstr(value)))
    end
end

function set_default_siglevel(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_default_siglevel"), ptr(h), ptr(value)))
    end
end

function set_local_file_siglevel(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_local_file_siglevel"), ptr(h), ptr(value)))
    end
end

function set_remote_file_siglevel(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_remote_file_siglevel"), ptr(h), ptr(value)))
    end
end

function set_checkspace(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_checkspace"), ptr(h), ptr(value)))
    end
end

function set_parallel_downloads(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_parallel_downloads"), ptr(h), ptr(value)))
    end
end

# ---- databaze ----

function localdb(h):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_get_localdb"), ptr(h))
    end
end

function register_syncdb(h, name, siglevel):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("alpm_register_syncdb"), ptr(h), cstr(name), ptr(siglevel))
    end
end

function syncdbs(h):
    unsafe:
        return list_items(__lsl_qbe_call1(__lsl_symbol("alpm_get_syncdbs"), ptr(h)))
    end
end

function db_name(db):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_db_get_name"), ptr(db)))
    end
end

function db_add_server(db, url):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_db_add_server"), ptr(db), cstr(url)))
    end
end

function db_set_usage(db, usage):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_db_set_usage"), ptr(db), ptr(usage)))
    end
end

# ---- zpravy libalpm ----

log_state = {"handler": None, "record": 0}

# alpm_cb_log(ctx, level, fmt, va_list): text slozi vsnprintf, handler(level, text)
function log_trampoline(level, fmt, args):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        call __lsl_qbe_call4(__lsl_symbol("vsnprintf"), base, 4095, ptr(fmt), ptr(args))
        message = text(base)
    end
    handler = log_state["handler"]
    call handler(s32(level), message)
    return 0
end

function set_logcb(h, handler):
    log_state["handler"] = handler
    if log_state["record"] == 0:
        log_state["record"] = glib.record_new(log_trampoline, 3)
    end
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("alpm_option_set_logcb"), ptr(h), glib.callback_first(), ptr(log_state["record"]))
    end
    return 0
end

# Obnovi jednu databazi ze serveru (alpm_db_update se seznamem o jedne polozce); 0 = ok (i "aktualni"),
# -1 = chyba (last_error)
function db_update(h, db, force):
    dbs = list_new([db])
    flag = 1 if force else 0
    unsafe:
        rc = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("alpm_db_update"), ptr(h), ptr(dbs), ptr(flag)))
    end
    call list_free(dbs)
    # 1 = databaze uz aktualni (_alpm_download), chyba je jen zaporna hodnota
    return -1 if rc < 0 else 0
end

function db_pkgcache(db):
    unsafe:
        return list_items(__lsl_qbe_call1(__lsl_symbol("alpm_db_get_pkgcache"), ptr(db)))
    end
end

function db_get_pkg(db, name):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("alpm_db_get_pkg"), ptr(db), cstr(name))
    end
end

# Hledani libalpm (nazev i popis, regularni vyrazy jako pacman -Ss); [] i pri chybe
function db_search(db, words):
    out = []
    unsafe:
        needles = list_new_texts(words)
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        rc = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("alpm_db_search"), ptr(db), ptr(needles), base))
        found = __lsl_qbe_load64(base)
        if rc == 0:
            out = list_items(found)
        end
        call list_free(found)
        call list_free_texts(needles)
    end
    return out
end

# ---- balicky ----

function pkg_name(pkg):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_name"), ptr(pkg)))
    end
end

function pkg_version(pkg):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_version"), ptr(pkg)))
    end
end

function pkg_desc(pkg):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_desc"), ptr(pkg)))
    end
end

function pkg_url(pkg):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_url"), ptr(pkg)))
    end
end

function pkg_packager(pkg):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_packager"), ptr(pkg)))
    end
end

function pkg_builddate(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_builddate"), ptr(pkg))
    end
end

function pkg_installdate(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_installdate"), ptr(pkg))
    end
end

function pkg_size(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_size"), ptr(pkg))
    end
end

function pkg_isize(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_isize"), ptr(pkg))
    end
end

function pkg_download_size(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_download_size"), ptr(pkg))
    end
end

function pkg_reason(pkg):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_reason"), ptr(pkg)))
    end
end

function pkg_db(pkg):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_db"), ptr(pkg))
    end
end

function pkg_licenses(pkg):
    unsafe:
        return list_texts(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_licenses"), ptr(pkg)))
    end
end

function pkg_groups(pkg):
    unsafe:
        return list_texts(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_groups"), ptr(pkg)))
    end
end

function pkg_depends(pkg):
    unsafe:
        return list_deps(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_depends"), ptr(pkg)))
    end
end

function pkg_optdepends(pkg):
    unsafe:
        return list_deps(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_optdepends"), ptr(pkg)))
    end
end

function pkg_conflicts(pkg):
    unsafe:
        return list_deps(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_conflicts"), ptr(pkg)))
    end
end

function pkg_provides(pkg):
    unsafe:
        return list_deps(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_provides"), ptr(pkg)))
    end
end

function pkg_replaces(pkg):
    unsafe:
        return list_deps(__lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_replaces"), ptr(pkg)))
    end
end

# alpm_filelist_t { size_t count; alpm_file_t *files } a alpm_file_t { char *name; off_t size; mode_t mode } (24 B)
function pkg_files(pkg):
    out = []
    unsafe:
        fl = __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_files"), ptr(pkg))
        if fl == 0:
            return out
        end
        count = __lsl_qbe_load64(fl)
        files = __lsl_qbe_load64(fl + 8)
        i = 0
        while i < count:
            out.append(text(__lsl_qbe_load64(files + i * 24)))
            i += 1
        end
    end
    return out
end

function pkg_requiredby(pkg):
    unsafe:
        l = __lsl_qbe_call1(__lsl_symbol("alpm_pkg_compute_requiredby"), ptr(pkg))
        out = list_texts(l)
        call list_free_texts(l)
        return out
    end
end

# ---- vyhledani ----

function sync_new_version(pkg, dbs):
    unsafe:
        l = list_new(dbs)
        p = __lsl_qbe_call2(__lsl_symbol("alpm_sync_get_new_version"), ptr(pkg), ptr(l))
        call list_free(l)
        return p
    end
end

function find_satisfier(h, dbs, dep):
    unsafe:
        l = list_new(dbs)
        p = __lsl_qbe_call3(__lsl_symbol("alpm_find_dbs_satisfier"), ptr(h), ptr(l), cstr(dep))
        call list_free(l)
        return p
    end
end

# Balicky skupiny v jedne databazi (alpm_group_t { char *name; alpm_list_t *packages }); [] kdyz tam neni
function db_group_pkgs(db, group):
    unsafe:
        g = __lsl_qbe_call2(__lsl_symbol("alpm_db_get_group"), ptr(db), cstr(group))
        if g == 0:
            return []
        end
        return list_items(__lsl_qbe_load64(g + 8))
    end
end

# Balicky skupiny ve vsech databazich (jako pacman -S skupina)
function find_group_pkgs(dbs, group):
    unsafe:
        l = list_new(dbs)
        found = __lsl_qbe_call2(__lsl_symbol("alpm_find_group_pkgs"), ptr(l), cstr(group))
        out = list_items(found)
        call list_free(found)
        call list_free(l)
        return out
    end
end

function vercmp(a, b):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_pkg_vercmp"), cstr(a), cstr(b)))
    end
end

# ---- dalsi volby handle (transakce) ----

function set_usesyslog(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_usesyslog"), ptr(h), ptr(value)))
    end
end

function set_disable_dl_timeout(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_disable_dl_timeout"), ptr(h), ptr(value)))
    end
end

function set_sandboxuser(h, value):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_option_set_sandboxuser"), ptr(h), cstr(value)))
    end
end

function option_dbpath(h):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_option_get_dbpath"), ptr(h)))
    end
end

function option_cachedirs(h):
    unsafe:
        return list_texts(__lsl_qbe_call1(__lsl_symbol("alpm_option_get_cachedirs"), ptr(h)))
    end
end

# ---- transakce ----

FLAG_NOSAVE = 4
FLAG_CASCADE = 16
FLAG_RECURSE = 32
FLAG_ALLDEPS = 256
FLAG_DOWNLOADONLY = 512
FLAG_NEEDED = 8192

ERR_DB_INVALID = 16
ERR_DB_INVALID_SIG = 17
ERR_PKG_INVALID = 35
ERR_PKG_INVALID_CHECKSUM = 36
ERR_PKG_INVALID_SIG = 37
ERR_UNSATISFIED_DEPS = 45
ERR_CONFLICTING_DEPS = 46
ERR_FILE_CONFLICTS = 47

function errno(h):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("alpm_errno"), ptr(h)))
    end
end

function strerror(code):
    unsafe:
        return text(__lsl_qbe_call1(__lsl_symbol("alpm_strerror"), ptr(code)))
    end
end

function trans_init(h, flags):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_trans_init"), ptr(h), ptr(flags)))
    end
end

function trans_release(h):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("alpm_trans_release"), ptr(h)))
    end
end

function trans_interrupt(h):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("alpm_trans_interrupt"), ptr(h)))
    end
end

function add_pkg(h, pkg):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_add_pkg"), ptr(h), ptr(pkg)))
    end
end

function remove_pkg(h, pkg):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_remove_pkg"), ptr(h), ptr(pkg)))
    end
end

function sync_sysupgrade(h, downgrade):
    flag = 1 if downgrade else 0
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_sync_sysupgrade"), ptr(h), ptr(flag)))
    end
end

# [rc, data (alpm_list_t* podle errno, viz describe_data)]
function trans_prepare(h):
    unsafe:
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        rc = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_trans_prepare"), ptr(h), base))
        return [rc, __lsl_qbe_load64(base)]
    end
end

function trans_commit(h):
    unsafe:
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        rc = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("alpm_trans_commit"), ptr(h), base))
        return [rc, __lsl_qbe_load64(base)]
    end
end

function trans_add(h):
    unsafe:
        return list_items(__lsl_qbe_call1(__lsl_symbol("alpm_trans_get_add"), ptr(h)))
    end
end

function trans_remove(h):
    unsafe:
        return list_items(__lsl_qbe_call1(__lsl_symbol("alpm_trans_get_remove"), ptr(h)))
    end
end

# Soubor balicku -> [rc, pkg]
function pkg_load(h, path, level):
    unsafe:
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        rc = __lsl_qbe_s32(__lsl_qbe_call5(__lsl_symbol("alpm_pkg_load"), ptr(h), cstr(path), 1, ptr(level), base))
        return [rc, __lsl_qbe_load64(base)]
    end
end

function pkg_filename(pkg):
    unsafe:
        p = __lsl_qbe_call1(__lsl_symbol("alpm_pkg_get_filename"), ptr(pkg))
        if p == 0:
            return ""
        end
        return text(p)
    end
end

function pkg_optionalfor(pkg):
    unsafe:
        l = __lsl_qbe_call1(__lsl_symbol("alpm_pkg_compute_optionalfor"), ptr(pkg))
        out = list_texts(l)
        call list_free_texts(l)
        return out
    end
end

function pkg_name_version(pkg):
    return pkg_name(pkg) + "-" + pkg_version(pkg)
end

function dep_string(dep):
    unsafe:
        s = __lsl_qbe_call1(__lsl_symbol("alpm_dep_compute_string"), ptr(dep))
        out = text(s)
        call __lsl_qbe_call1(__lsl_symbol("free"), s)
        return out
    end
end

function cstr_or(p, fallback):
    if p == 0:
        return fallback
    end
    return text(p)
end

# Data k chybe prepare/commit jako radky ve stylu pacmanu
function describe_data(code, data):
    out = []
    unsafe:
        for item in list_items(data):
            it = ptr(item)
            if code == ERR_UNSATISFIED_DEPS:
                # alpm_depmissing_t {target, depend, causingpkg}
                out.append("unable to satisfy dependency '" + dep_string(__lsl_qbe_load64(it + 8)) + "' required by "
                           + cstr_or(__lsl_qbe_load64(it), "?"))
            elif code == ERR_CONFLICTING_DEPS:
                # alpm_conflict_t {package1, package2, reason}
                out.append(pkg_name_version(__lsl_qbe_load64(it)) + " and " + pkg_name_version(__lsl_qbe_load64(it + 8))
                           + " are in conflict")
            elif code == ERR_FILE_CONFLICTS:
                # alpm_fileconflict_t {target, type, file, ctarget}
                owner = cstr_or(__lsl_qbe_load64(it + 24), "")
                line = cstr_or(__lsl_qbe_load64(it), "?") + ": " + cstr_or(__lsl_qbe_load64(it + 16), "?") + " exists in filesystem"
                if owner != "":
                    line = line + " (owned by " + owner + ")"
                end
                out.append(line)
            else:
                out.append(cstr_or(it, ""))
            end
        end
    end
    return [d for d in out if d != ""]
end

# ---- callbacky (dlcb, progresscb, eventcb, questioncb); handler dostane uz rozlozena data ----

cb_state = {"dl": None, "progress": None, "event": None, "question": None, "records": {}}

function s32(value):
    unsafe:
        return __lsl_qbe_s32(ptr(value))
    end
end

# alpm_cb_download(ctx, filename, event, data): handler(soubor, udalost, a, b)
#   INIT 0, PROGRESS 1 (stazeno, celkem), RETRY 2, COMPLETED 3 (celkem, vysledek)
function dl_trampoline(filename, event, data):
    ev = s32(event)
    a = 0
    b = 0
    unsafe:
        d = ptr(data)
        if d != 0 and ev == 1:
            a = __lsl_qbe_load64(d)
            b = __lsl_qbe_load64(d + 8)
        elif d != 0 and ev == 3:
            a = __lsl_qbe_load64(d)
            b = __lsl_qbe_s32(__lsl_qbe_load32(d + 8))
        end
    end
    handler = cb_state["dl"]
    call handler(cstr_or(ptr(filename), ""), ev, a, b)
    return 0
end

# alpm_cb_progress(ctx, progress, pkg, percent, howmany, current)
function progress_trampoline(progress, pkg, percent, howmany, current):
    handler = cb_state["progress"]
    call handler(s32(progress), cstr_or(ptr(pkg), ""), s32(percent), ptr(howmany), ptr(current))
    return 0
end

# alpm_cb_event(ctx, event): handler(typ, text, pozice, celkem)
#   SCRIPTLET_INFO 17 {line}; HOOK_RUN_START/DONE 36/37 {name, desc, position, total}
function event_trampoline(event):
    t = ""
    pos = 0
    total = 0
    unsafe:
        e = ptr(event)
        ev = __lsl_qbe_s32(__lsl_qbe_load32(e))
        if ev == 17:
            t = cstr_or(__lsl_qbe_load64(e + 8), "")
        elif ev == 36 or ev == 37:
            t = cstr_or(__lsl_qbe_load64(e + 16), "")
            if t == "":
                t = cstr_or(__lsl_qbe_load64(e + 8), "")
            end
            pos = __lsl_qbe_load64(e + 24)
            total = __lsl_qbe_load64(e + 32)
        end
    end
    handler = cb_state["event"]
    call handler(ev, t, pos, total)
    return 0
end

# alpm_cb_question(ctx, question): handler(typ, text) -> odpoved (int na offsetu 4)
#   CORRUPTED_PKG 8: text = cesta souboru; IMPORT_KEY 64: text = uid; REPLACE_PKG 2: "stary -> novy"
function question_trampoline(question):
    unsafe:
        q = ptr(question)
        qt = __lsl_qbe_s32(__lsl_qbe_load32(q))
        t = ""
        if qt == 8 or qt == 64:
            t = cstr_or(__lsl_qbe_load64(q + 8), "")
        elif qt == 2:
            t = pkg_name(__lsl_qbe_load64(q + 8)) + " -> " + pkg_name(__lsl_qbe_load64(q + 16))
        end
        handler = cb_state["question"]
        answer = handler(qt, t)
        call __lsl_qbe_store32(q + 4, ptr(answer))
    end
    return 0
end

function set_callbacks(h, dl, progress, event, question):
    cb_state["dl"] = dl
    cb_state["progress"] = progress
    cb_state["event"] = event
    cb_state["question"] = question
    recs = cb_state["records"]
    if len(recs) == 0:
        recs["dl"] = glib.record_new(dl_trampoline, 3)
        recs["progress"] = glib.record_new(progress_trampoline, 5)
        recs["event"] = glib.record_new(event_trampoline, 1)
        recs["question"] = glib.record_new(question_trampoline, 1)
    end
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("alpm_option_set_dlcb"), ptr(h), glib.callback_first(), ptr(recs["dl"]))
        call __lsl_qbe_call3(__lsl_symbol("alpm_option_set_progresscb"), ptr(h), glib.callback_first(), ptr(recs["progress"]))
        call __lsl_qbe_call3(__lsl_symbol("alpm_option_set_eventcb"), ptr(h), glib.callback_first(), ptr(recs["event"]))
        call __lsl_qbe_call3(__lsl_symbol("alpm_option_set_questioncb"), ptr(h), glib.callback_first(), ptr(recs["question"]))
    end
    return 0
end

# Balicek ze seznamu, ktery splnuje zavislost (alpm_find_satisfier); 0 = zadny
function find_satisfier_pkgs(pkgs, dep):
    unsafe:
        l = list_new(pkgs)
        p = __lsl_qbe_call2(__lsl_symbol("alpm_find_satisfier"), ptr(l), cstr(dep))
        call list_free(l)
        return p
    end
end
