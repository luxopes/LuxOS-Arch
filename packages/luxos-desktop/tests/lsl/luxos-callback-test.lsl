# Zivotni cyklus zaznamu zpetnych volani (LSL 0.11.2: standardni glib/gtk predava callback_destroy sam).
# Pro kazdy druh zdroje a spojeni 1000x "skoncil" (obsluha vrati False, objekt zanikl) a 1000x "odebran"
# (source_remove, signal_handler_disconnect). Kazdy zaznam se musi uvolnit prave jednou: po kazdem druhu
# je pocet zivych zaznamu zpet na vychozi hodnote, kazda obsluha bezi presne tolikrat, kolikrat ma (cizi
# nebo uvolneny zaznam by zavolal jinou obsluhu nebo spadl), gc() mezi koly uvolneny zaznam opravdu smaze.
# Vypise "NAZEV volani rozdil" pro kazdy druh, nakonec "done".
load luxos_glib
load glib
load gtk

N = 1000
hits = {}

function hit(name):
    hits[name] = hits.get(name, 0) + 1
    return 0
end

function alive():
    return glib.record_count() + len(luxos_glib.live)
end

function check(name, before):
    call gc()
    print name, hits.get(name, 0), alive() - before
    return 0
end

function pump_until(name, count):
    guard = 0
    while hits.get(name, 0) < count and guard < 200000:
        call glib.pump()
        guard += 1
    end
    return 0
end

function never():
    return True
end

function never_data(unused):
    return True
end

function never_fd(fd, condition):
    return True
end

# ---- standardni glib -------------------------------------------------------------------------------------

function on_timeout():
    call hit("glib.timeout_add")
    return False
end

function on_timeout_full():
    call hit("glib.timeout_add_full")
    return False
end

function on_idle():
    call hit("glib.idle_add")
    return False
end

function on_gtk_timeout():
    call hit("gtk.timeout_add")
    return False
end

function on_gtk_idle():
    call hit("gtk.idle_add")
    return False
end

function on_fd(fd, condition):
    call hit("glib.fd_add")
    return False
end

function on_usr1():
    call hit("glib.unix_signal_add")
    return False
end

function on_usr1_full():
    call hit("glib.unix_signal_add_full")
    return False
end

function on_usr1_data():
    call hit("luxos_glib.unix_signal_add")
    return False
end

function on_child(pid, status):
    call hit("glib.spawn_watched")
    return 0
end

function on_cancel(obj):
    call hit("glib.signal_connect")
    return 0
end

function on_gtk_cancel(obj):
    call hit("gtk.connect")
    return 0
end

# ---- luxos_glib s vazanou hodnotou -----------------------------------------------------------------------

function on_data(name):
    call hit(name)
    return False
end

function on_cancel_data(name, obj):
    call hit(name)
    return 0
end

function on_fd_data(name, fd, condition):
    call hit(name)
    return False
end

function on_child_data(name, pid, status):
    call hit(name)
    return 0
end

function on_capture(name, text, status):
    if text == "ok" + chr(10) and status == 0:
        call hit(name)
    end
    return 0
end

# ---- pomocne -----------------------------------------------------------------------------------------------

function pipe_fds():
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_call1(__lsl_symbol("pipe"), luxos_glib.data(cell))
        return [__lsl_qbe_s32(__lsl_qbe_load32(luxos_glib.data(cell))), __lsl_qbe_s32(__lsl_qbe_load32(luxos_glib.data(cell) + 4))]
    end
end

function raise_usr1():
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("kill"), __lsl_qbe_call0(__lsl_symbol("getpid")), 10)
    end
    return 0
end

function cancellable():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_cancellable_new"))
    end
end

function cancel_and_free(c):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_cancellable_cancel"), luxos_glib.ptr(c))
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), luxos_glib.ptr(c))
    end
    return 0
end

function remove_all(ids):
    for id in ids:
        call glib.source_remove(id)
    end
    return 0
end

# Prvni volani zalozi trampoliny a hlavni smycku, do vychoziho stavu se nepocita
call glib.idle_add(on_idle)
call pump_until("glib.idle_add", 1)
hits["glib.idle_add"] = 0
call gc()
before = alive()
print "start", before

# zdroje: skoncene (False) a odebrane
ids = []
for i in range(N):
    call glib.timeout_add(0, on_timeout)
    ids.append(glib.timeout_add(60000, never))
end
call remove_all(ids)
call pump_until("glib.timeout_add", N)
call check("glib.timeout_add", before)

ids = []
for i in range(N):
    call glib.timeout_add_full(glib.PRIORITY_DEFAULT, 0, on_timeout_full)
    ids.append(glib.timeout_add_full(glib.PRIORITY_DEFAULT, 60000, never))
    ids.append(glib.timeout_add_seconds(600, never))
    ids.append(glib.timeout_add_seconds_full(glib.PRIORITY_DEFAULT, 600, never))
end
call remove_all(ids)
call pump_until("glib.timeout_add_full", N)
call check("glib.timeout_add_full", before)

ids = []
for i in range(N):
    call glib.idle_add(on_idle)
    ids.append(glib.idle_add(never))
end
call remove_all(ids)
call pump_until("glib.idle_add", N)
call check("glib.idle_add", before)

ids = []
for i in range(N):
    call gtk.timeout_add(0, on_gtk_timeout)
    call gtk.idle_add(on_gtk_idle)
    ids.append(gtk.timeout_add(60000, never))
    ids.append(gtk.idle_add(never))
end
call remove_all(ids)
call pump_until("gtk.timeout_add", N)
call pump_until("gtk.idle_add", N)
call check("gtk.timeout_add", before)
call check("gtk.idle_add", before)

# fd: precteny konec roury s bajtem je stale citelny, prazdna roura nikdy
full = pipe_fds()
empty = pipe_fds()
unsafe:
    call __lsl_qbe_call3(__lsl_symbol("write"), luxos_glib.ptr(full[1]), luxos_glib.cstr("x"), 1)
end
ids = []
for i in range(N):
    call glib.fd_add(full[0], 1, on_fd)
    ids.append(glib.fd_add(empty[0], 1, never_fd))
end
call remove_all(ids)
call pump_until("glib.fd_add", N)
call check("glib.fd_add", before)

# signaly UNIXu: kazde kolo jeden signal a jedna obsluha, ktera skonci; k tomu odebrane
ids = []
for i in range(N):
    call glib.unix_signal_add(10, on_usr1)
    call raise_usr1()
    call pump_until("glib.unix_signal_add", i + 1)
    ids.append(glib.unix_signal_add(12, never))
end
call remove_all(ids)
call check("glib.unix_signal_add", before)

ids = []
for i in range(N):
    call glib.unix_signal_add_full(glib.PRIORITY_DEFAULT, 10, on_usr1_full)
    call raise_usr1()
    call pump_until("glib.unix_signal_add_full", i + 1)
    ids.append(glib.unix_signal_add_full(glib.PRIORITY_DEFAULT, 12, never))
end
call remove_all(ids)
call check("glib.unix_signal_add_full", before)

ids = []
for i in range(N):
    call luxos_glib.unix_signal_add(10, on_usr1_data)
    call raise_usr1()
    call pump_until("luxos_glib.unix_signal_add", i + 1)
    ids.append(luxos_glib.unix_signal_add(12, never))
end
call remove_all(ids)
call check("luxos_glib.unix_signal_add", before)

# signaly GObject: objekt zanikne, nebo se spojeni odpoji
for i in range(N):
    c = cancellable()
    call glib.signal_connect(c, "cancelled", on_cancel, 0)
    call cancel_and_free(c)
    c = cancellable()
    id = glib.signal_connect(c, "cancelled", on_cancel, 0)
    call glib.signal_handler_disconnect(c, id)
    call cancel_and_free(c)
end
call check("glib.signal_connect", before)

for i in range(N):
    c = cancellable()
    call gtk.connect(c, "cancelled", on_gtk_cancel)
    call cancel_and_free(c)
    c = cancellable()
    id = gtk.connect(c, "cancelled", on_gtk_cancel)
    call glib.signal_handler_disconnect(c, id)
    call cancel_and_free(c)
end
call check("gtk.connect", before)

name = "luxos_glib.connect_data"
for i in range(N):
    c = cancellable()
    call luxos_glib.connect_data(c, "cancelled", 0, on_cancel_data, name)
    call cancel_and_free(c)
    c = cancellable()
    record = luxos_glib.connect_data(c, "cancelled", 0, on_cancel_data, name)
    unsafe:
        # G_SIGNAL_MATCH_DATA 16: odpojit podle user_data (zaznamu)
        call __lsl_qbe_call7(__lsl_symbol("g_signal_handlers_disconnect_matched"), luxos_glib.ptr(c), 16, 0, 0, 0, 0, luxos_glib.ptr(record))
    end
    call cancel_and_free(c)
end
call check(name, before)

# luxos_glib: zdroje s vazanou hodnotou
for kind in ["luxos_glib.timeout_add_data", "luxos_glib.idle_add_data"]:
    ids = []
    for i in range(N):
        if kind == "luxos_glib.timeout_add_data":
            call luxos_glib.timeout_add_data(0, on_data, kind)
            ids.append(luxos_glib.timeout_add_data(60000, never_data, 0))
            ids.append(luxos_glib.timeout_add_seconds_data(600, never_data, 0))
        else:
            call luxos_glib.idle_add_data(on_data, kind)
            ids.append(luxos_glib.idle_add_data(never_data, 0))
        end
    end
    call remove_all(ids)
    call pump_until(kind, N)
    call check(kind, before)
end

# fd_add_data: skonceny se uvolni sam, odebrany uvolni volajici (release) jako luxos-polkit
name = "luxos_glib.fd_add_data"
for i in range(N):
    call luxos_glib.fd_add_data(full[0], 1, on_fd_data, name)
    watch = luxos_glib.fd_add_data(empty[0], 1, on_fd_data, "never")
    call glib.source_remove(watch[0])
    call luxos_glib.release(watch[1])
end
call pump_until(name, N)
call check(name, before)

# procesy: mene kol (kazde spusti program)
M = 200
for i in range(M):
    call glib.spawn_watched(["true"], on_child)
    call luxos_glib.spawn_watched_data(["true"], on_child_data, "luxos_glib.spawn_watched_data")
    call luxos_glib.spawn_capture(["echo", "ok"], on_capture, "luxos_glib.spawn_capture")
    call pump_until("glib.spawn_watched", i + 1)
    call pump_until("luxos_glib.spawn_watched_data", i + 1)
    call pump_until("luxos_glib.spawn_capture", i + 1)
end
call check("glib.spawn_watched", before)
call check("luxos_glib.spawn_watched_data", before)
call check("luxos_glib.spawn_capture", before)

# po vsem uklidu se obsluhy volaji porad spravne
hits["glib.timeout_add"] = 0
call glib.timeout_add(0, on_timeout)
call pump_until("glib.timeout_add", 1)
call check("glib.timeout_add", before)
print "never", hits.get("never", 0)
print "done"
