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
    call handler(ptr(level), message)
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
    return rc
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
