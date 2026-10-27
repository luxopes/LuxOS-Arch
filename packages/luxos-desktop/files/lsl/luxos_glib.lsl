# lsl: internal-abi
# lsl: link libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - doplnky k modulu glib LSL 0.10.6 (cil linux-x86_64-gnu) pro luxos-hub: jen to, co standardni
# knihovna nema. Programy nacitaji `load luxos_glib, glib as glib`; az tyto funkce budou v glib, modul zmizi.
#
# Zpetna volani s vazanou hodnotou (LSL nema uzavery): obsluha dostane `data` jako prvni argument.
#   connect_data(obj, signal, nargs, f, data)   f(data, argumenty signalu..., obj); vraci id zaznamu
#   timeout_add_data(ms, f, data), timeout_add_seconds_data(s, f, data), idle_add_data(f, data)
#       f(data) se opakuje, dokud vraci True; zaznam obsluhy se po skonceni uvolni
#   spawn_watched_data(argv, f, data)           po skonceni f(data, pid, status)
#   spawn_capture(argv, f, data)                po skonceni f(data, stdout_text, status); stderr zahozen
#   spawn_stream(argv, f, data)                 f(data, kus_vystupu) prubezne, po konci f(data, "")
#   release(id)                                 uvolni zaznam obsluhy (po zniceni widgetu)
#   spawn(argv), spawn_quiet(argv)              jako glib.spawn/spawn_quiet, ale v nove relaci (setsid, jako
#                                               subprocess.Popen(start_new_session=True))
# Cas pres libc (glib ma jen format_unix/local_date): localtime(t), gmtime(t), mktime(...), timegm(...),
#   set_tz(name)/unset_tz() pro TZID kalendare, now().
# Soubory: stat(path) -> [velikost, mtime_ns], rename, unlink, mkdir_p, is_dir, realpath, readlink,
#   write_atomic(path, text), read_text(path) ("" pri chybe), list_dir(path) ([] kdyz neni), close_fd(fd).
# GObject: object_ref_sink(obj) - vlastni reference na widget, ktery se odebira z kontejneru a pouziva znovu.
#
# Pozor (LSL 0.10.6, internal-abi): uvnitr modulu je dynamicka hodnota Int 0 nerozlisitelna od None
# (type(), == None); ukazatele se testuji == 0 a cisla se neporovnavaji s None.
load glib

live = {}            # id -> zaznam obsluhy (drzi ho GC, dokud zije zdroj/signal)
next_id = 1

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function data(bytes):
    unsafe:
        return __lsl_qbe_load64(__lsl_address(bytes) + 24)
    end
end

# Zaznam obsluhy s vazanou hodnotou drzi tento modul (glib.handlers by rostl bez konce); [adresa, id]
function track(handler, count, bound):
    global next_id
    address = glib.record_bound(handler, count, bound)
    record = glib.handlers.pop()
    id = next_id
    next_id += 1
    live[id] = record
    return [address, id]
end

function release(id):
    if id in live:
        call live.pop(id)
    end
    return 0
end

# ---- zdroje hlavni smycky ----------------------------------------------------------------------------

# state = [handler, data, id]
function source_trampoline(state):
    handler = state[0]
    result = handler(state[1])
    if result == True or (result != False and result != None and result != 0):
        return True
    end
    call release(state[2])
    return False
end

function add_source(kind, interval, handler, bound):
    state = [handler, bound, 0]
    tracked = track(source_trampoline, 0, state)
    state[2] = tracked[1]
    unsafe:
        record = tracked[0]
        if kind == 1:
            return __lsl_qbe_call5(__lsl_symbol("g_timeout_add_full"), 0, ptr(interval), glib.callback_first(), ptr(record), 0)
        elif kind == 2:
            return __lsl_qbe_call5(__lsl_symbol("g_timeout_add_seconds_full"), 0, ptr(interval), glib.callback_first(), ptr(record), 0)
        end
        return __lsl_qbe_call4(__lsl_symbol("g_idle_add_full"), 0, glib.callback_first(), ptr(record), 0)
    end
end

function timeout_add_data(ms, handler, bound):
    return add_source(1, ms, handler, bound)
end

function timeout_add_seconds_data(seconds, handler, bound):
    return add_source(2, seconds, handler, bound)
end

function idle_add_data(handler, bound):
    return add_source(3, 0, handler, bound)
end

# ---- signaly GObject s vazanou hodnotou ---------------------------------------------------------------

function connect_data(instance, signal, nargs, handler, bound):
    tracked = track(handler, nargs + 1, bound)
    unsafe:
        call __lsl_qbe_call6(__lsl_symbol("g_signal_connect_data"), ptr(instance), cstr(signal), glib.callback_first(), ptr(tracked[0]), 0, 2)
    end
    return tracked[1]
end

# ---- procesy ---------------------------------------------------------------------------------------------

# G_SPAWN_SEARCH_PATH 4, STDOUT_TO_DEV_NULL 8, STDERR_TO_DEV_NULL 16, DO_NOT_REAP_CHILD 2; child_setup = setsid
function spawn_flags(argv, flags):
    unsafe:
        array = glib.cstr_array(argv)
        cell = __lsl_byte_zeros(16)
        ok = __lsl_qbe_call8(__lsl_symbol("g_spawn_async"), 0, glib.array_data(array), 0, ptr(flags), __lsl_symbol("setsid"), 0, data(cell), data(cell) + 8)
        if ok == 0:
            error = __lsl_qbe_load64(data(cell) + 8)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return 0
        end
        return __lsl_qbe_s32(__lsl_qbe_load32(data(cell)))
    end
end

function spawn(argv):
    return spawn_flags(argv, 4)
end

function spawn_quiet(argv):
    return spawn_flags(argv, 4 + 8 + 16)
end

# state = [handler, data, id]
function child_trampoline(state, pid, status):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(pid))
    end
    handler = state[0]
    call handler(state[1], pid, status)
    call release(state[2])
    return False
end

function spawn_watched_data(argv, handler, bound):
    pid = spawn_flags(argv, 4 + 2 + 8 + 16)
    if pid == 0:
        return 0
    end
    state = [handler, bound, 0]
    tracked = track(child_trampoline, 2, state)
    state[2] = tracked[1]
    unsafe:
        call __lsl_qbe_call5(__lsl_symbol("g_child_watch_add_full"), 0, ptr(pid), __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]), 0)
    end
    return pid
end

# state = [handler, data, fd, text, running, status, id_read, id_child]
function spawn_capture(argv, handler, bound):
    unsafe:
        array = glib.cstr_array(argv)
        cells = __lsl_byte_zeros(24)
        base = data(cells)
        # bez child_setup (setsid): GLib pouzije posix_spawn misto fork() (rychlejsi u velkeho procesu GTK)
        ok = __lsl_qbe_call11(__lsl_symbol("g_spawn_async_with_pipes"), 0, glib.array_data(array), 0, 4 + 2 + 16, 0, 0, base, 0, base + 8, 0, base + 16)
        if ok == 0:
            error = __lsl_qbe_load64(base + 16)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return 0
        end
        pid = __lsl_qbe_s32(__lsl_qbe_load32(base))
        out = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        state = [handler, bound, out, "", True, 0, 0, 0]
        read_rec = track(capture_read, 2, state)
        child_rec = track(capture_exit, 2, state)
        state[6] = read_rec[1]
        state[7] = child_rec[1]
        # G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16
        call __lsl_qbe_call4(__lsl_symbol("g_unix_fd_add"), out, 25, __lsl_symbol("lsl_arch_callback_u3"), ptr(read_rec[0]))
        call __lsl_qbe_call5(__lsl_symbol("g_child_watch_add_full"), 0, pid, __lsl_symbol("lsl_arch_callback_u3"), ptr(child_rec[0]), 0)
        return pid
    end
end

function capture_read(state, handle, condition):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        n = __lsl_qbe_call3(__lsl_symbol("read"), ptr(handle), data(buffer), 4096)
        if n > 0:
            state[3] = state[3] + __lsl_text_from_bytes(buffer, 0, n)
            return True
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    end
    state[2] = -1
    call release(state[6])
    if not state[4]:
        call capture_finish(state)
    end
    return False
end

function capture_exit(state, pid, status):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(pid))
    end
    state[4] = False
    state[5] = status
    call release(state[7])
    if state[2] == -1:
        call capture_finish(state)
    end
    return False
end

function capture_finish(state):
    handler = state[0]
    call handler(state[1], state[3], state[5])
    return 0
end

# Dlouho bezici proces s prubeznym ctenim vystupu (pactl subscribe): f(data, kus_textu) pri kazdem
# precteni, po konci procesu jednou f(data, ""); stderr zahozen; vraci pid nebo 0
# state = [handler, data, fd, running, id_read, id_child]
function spawn_stream(argv, handler, bound):
    unsafe:
        array = glib.cstr_array(argv)
        cells = __lsl_byte_zeros(24)
        base = data(cells)
        ok = __lsl_qbe_call11(__lsl_symbol("g_spawn_async_with_pipes"), 0, glib.array_data(array), 0, 4 + 2 + 16, 0, 0, base, 0, base + 8, 0, base + 16)
        if ok == 0:
            error = __lsl_qbe_load64(base + 16)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return 0
        end
        pid = __lsl_qbe_s32(__lsl_qbe_load32(base))
        out = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        state = [handler, bound, out, True, 0, 0]
        read_rec = track(stream_read, 2, state)
        child_rec = track(stream_exit, 2, state)
        state[4] = read_rec[1]
        state[5] = child_rec[1]
        call __lsl_qbe_call4(__lsl_symbol("g_unix_fd_add"), out, 25, __lsl_symbol("lsl_arch_callback_u3"), ptr(read_rec[0]))
        call __lsl_qbe_call5(__lsl_symbol("g_child_watch_add_full"), 0, pid, __lsl_symbol("lsl_arch_callback_u3"), ptr(child_rec[0]), 0)
        return pid
    end
end

function stream_read(state, handle, condition):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        n = __lsl_qbe_call3(__lsl_symbol("read"), ptr(handle), data(buffer), 4096)
        if n > 0:
            handler = state[0]
            call handler(state[1], __lsl_text_from_bytes(buffer, 0, n))
            return True
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    end
    state[2] = -1
    call release(state[4])
    if not state[3]:
        call stream_finish(state)
    end
    return False
end

function stream_exit(state, pid, status):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(pid))
    end
    state[3] = False
    call release(state[5])
    if state[2] == -1:
        call stream_finish(state)
    end
    return False
end

function stream_finish(state):
    handler = state[0]
    call handler(state[1], "")
    return 0
end

# ---- cas (libc) -----------------------------------------------------------------------------------------

function now():
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("time"), 0)
    end
end

# [rok, mesic, den, hodina, minuta, sekunda, den v tydnu (0 = pondeli), den v roce (1..366), isdst]
function localtime(t):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_store64(data(cell), ptr(t))
        tm = __lsl_byte_zeros(64)
        call __lsl_qbe_call2(__lsl_symbol("localtime_r"), data(cell), data(tm))
        return tm_fields(data(tm))
    end
end

function gmtime(t):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_store64(data(cell), ptr(t))
        tm = __lsl_byte_zeros(64)
        call __lsl_qbe_call2(__lsl_symbol("gmtime_r"), data(cell), data(tm))
        return tm_fields(data(tm))
    end
end

function tm_fields(base):
    unsafe:
        wday = __lsl_qbe_s32(__lsl_qbe_load32(base + 24))
        return [__lsl_qbe_s32(__lsl_qbe_load32(base + 20)) + 1900, __lsl_qbe_s32(__lsl_qbe_load32(base + 16)) + 1,
                __lsl_qbe_s32(__lsl_qbe_load32(base + 12)), __lsl_qbe_s32(__lsl_qbe_load32(base + 8)),
                __lsl_qbe_s32(__lsl_qbe_load32(base + 4)), __lsl_qbe_s32(__lsl_qbe_load32(base)),
                (wday + 6) % 7, __lsl_qbe_s32(__lsl_qbe_load32(base + 28)) + 1, __lsl_qbe_s32(__lsl_qbe_load32(base + 32))]
    end
end

function fill_tm(base, year, month, day, hour, minute, second):
    unsafe:
        call __lsl_qbe_store32(base, ptr(second))
        call __lsl_qbe_store32(base + 4, ptr(minute))
        call __lsl_qbe_store32(base + 8, ptr(hour))
        call __lsl_qbe_store32(base + 12, ptr(day))
        call __lsl_qbe_store32(base + 16, ptr(month) - 1)
        call __lsl_qbe_store32(base + 20, ptr(year) - 1900)
        call __lsl_qbe_store32(base + 32, -1)
        return 0
    end
end

# Unixovy cas z mistniho data a casu (letni cas urci knihovna)
function mktime(year, month, day, hour, minute, second):
    unsafe:
        tm = __lsl_byte_zeros(64)
        call fill_tm(data(tm), year, month, day, hour, minute, second)
        return __lsl_qbe_call1(__lsl_symbol("mktime"), data(tm))
    end
end

function timegm(year, month, day, hour, minute, second):
    unsafe:
        tm = __lsl_byte_zeros(64)
        call fill_tm(data(tm), year, month, day, hour, minute, second)
        return __lsl_qbe_call1(__lsl_symbol("timegm"), data(tm))
    end
end

# Docasne jine casove pasmo pro mktime/localtime (TZID v kalendari); unset_tz vrati puvodni TZ prostredi
saved_tz = None

function set_tz(name):
    global saved_tz
    unsafe:
        if saved_tz == None:
            previous = __lsl_qbe_call1(__lsl_symbol("getenv"), cstr("TZ"))
            if previous == 0:
                saved_tz = ""
            else:
                saved_tz = ":" + glib.from_c(previous)
            end
        end
        call __lsl_qbe_call3(__lsl_symbol("setenv"), cstr("TZ"), cstr(name), 1)
        call __lsl_qbe_call0(__lsl_symbol("tzset"))
        return 0
    end
end

function unset_tz():
    global saved_tz
    unsafe:
        if saved_tz == None:
            return 0
        end
        if saved_tz == "":
            call __lsl_qbe_call1(__lsl_symbol("unsetenv"), cstr("TZ"))
        else:
            call __lsl_qbe_call3(__lsl_symbol("setenv"), cstr("TZ"), cstr(saved_tz[1:]), 1)
        end
        saved_tz = None
        call __lsl_qbe_call0(__lsl_symbol("tzset"))
        return 0
    end
end

# ---- soubory a adresare -----------------------------------------------------------------------------------

function read_text(path):
    text = ""
    safe:
        text = readfile(path)
    end
    return text
end

# Serazena jmena polozek adresare; [] kdyz adresar neni (listdir vyhazuje FileError)
function list_dir(path):
    names = []
    safe:
        names = listdir(path)
    end
    return sorted(names)
end

function mkdir_p(path):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("g_mkdir_with_parents"), cstr(path), 493) == 0
    end
end

# Atomicky zapis: docasny soubor + prejmenovani
function write_atomic(path, text):
    tmp = path + ".tmp"
    call writefile(tmp, text)
    return rename(tmp, path)
end

function rename(source, target):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("rename"), cstr(source), cstr(target)) == 0
    end
end

function unlink(path):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("unlink"), cstr(path)) == 0
    end
end

function is_dir(path):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("g_file_test"), cstr(path), 4) != 0
    end
end

function realpath(path):
    unsafe:
        # vlastni buffer (PATH_MAX): starsi verze symbolu realpath v glibc s NULL nepracuje
        buffer = __lsl_byte_zeros(4096)
        out = __lsl_qbe_call2(__lsl_symbol("realpath"), cstr(path), data(buffer))
        if out == 0:
            return ""
        end
        return glib.from_c(out)
    end
end

function readlink(path):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        n = __lsl_qbe_call3(__lsl_symbol("readlink"), cstr(path), data(buffer), 4095)
        if n <= 0:
            return ""
        end
        return __lsl_text_from_bytes(buffer, 0, n)
    end
end

# [velikost, cas zmeny v ns] nebo [] kdyz soubor neexistuje
function stat(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        if __lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(buffer)) != 0:
            return []
        end
        base = data(buffer)
        # struct stat x86_64: st_size +48, st_mtim +88 (tv_sec, tv_nsec)
        return [__lsl_qbe_load64(base + 48), __lsl_qbe_load64(base + 88) * 1000000000 + __lsl_qbe_load64(base + 96)]
    end
end

# Vlastni reference na objekt GObject (widget prezije odebrani z kontejneru; PyGObject to dela samo)
function object_ref_sink(object):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("g_object_ref_sink"), ptr(object))
    end
end

# Zavre popisovac souboru (inhibitor logind)
function close_fd(handle):
    unsafe:
        if ptr(handle) >= 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
        end
        return 0
    end
end

# ---- Snimek obrazovky ------------------------------------------------------------------------------------------

# Sledovani popisovace v hlavni smycce: f(data, fd, podminka) dokud vraci True; [id zdroje, id zaznamu]
# (podminka G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16)
function fd_add_data(handle, condition, handler, bound):
    state = [handler, bound, 0]
    tracked = track(fd_trampoline, 2, state)
    state[2] = tracked[1]
    unsafe:
        source = __lsl_qbe_call4(__lsl_symbol("g_unix_fd_add"), ptr(handle), ptr(condition), __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]))
        return [source, tracked[1]]
    end
end

function fd_trampoline(state, handle, condition):
    handler = state[0]
    result = handler(state[1], handle, condition)
    if result == True or (result != False and result != None and result != 0):
        return True
    end
    call release(state[2])
    return False
end

# Synchronni spusteni bez vystupu (xclip: hlavni proces skonci hned, kopie ve schrance zustane v nove relaci);
# vraci kod ukonceni nebo -1, kdyz program neni
function spawn_sync_quiet(argv):
    unsafe:
        array = glib.cstr_array(argv)
        cells = __lsl_byte_zeros(16)
        # G_SPAWN_SEARCH_PATH 4 | STDOUT_TO_DEV_NULL 8 | STDERR_TO_DEV_NULL 16; child_setup = setsid
        ok = __lsl_qbe_call10(__lsl_symbol("g_spawn_sync"), 0, glib.array_data(array), 0, 28, __lsl_symbol("setsid"), 0, 0, 0, data(cells), data(cells) + 8)
        if ok == 0:
            error = __lsl_qbe_load64(data(cells) + 8)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return -1
        end
        status = __lsl_qbe_s32(__lsl_qbe_load32(data(cells)))
        if status & 127 != 0:
            return 128 + (status & 127)
        end
        return (status >> 8) & 255
    end
end

# Slozka uzivatele podle xdg-user-dirs (G_USER_DIRECTORY_DESKTOP 0, PICTURES 4, VIDEOS 7); "" kdyz neni
function user_special_dir(kind):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_get_user_special_dir"), ptr(kind)))
    end
end

# Do Kose (g_file_trash): "trash", "unsupported" (slozka Kos nepodporuje), jinak text chyby
function trash_file(path):
    unsafe:
        file = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(path))
        cell = __lsl_byte_zeros(8)
        ok = __lsl_qbe_call3(__lsl_symbol("g_file_trash"), file, 0, data(cell))
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), file)
        if ok != 0:
            return "trash"
        end
        error = __lsl_qbe_load64(data(cell))
        if error == 0:
            return "error"
        end
        # GError {domain, code, message}; G_IO_ERROR_NOT_SUPPORTED = 15
        domain = __lsl_qbe_load32(error)
        code = __lsl_qbe_s32(__lsl_qbe_load32(error + 4))
        message = glib.from_c(__lsl_qbe_load64(error + 8))
        call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        if domain == __lsl_qbe_call0(__lsl_symbol("g_io_error_quark")) and code == 15:
            return "unsupported"
        end
        return message
    end
end

# Otevre adresu ve vychozi aplikaci; False pri chybe
function launch_uri(uri):
    unsafe:
        cell = __lsl_byte_zeros(8)
        ok = __lsl_qbe_call3(__lsl_symbol("g_app_info_launch_default_for_uri"), cstr(uri), 0, data(cell))
        error = __lsl_qbe_load64(data(cell))
        if error != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        end
        return ok != 0
    end
end
