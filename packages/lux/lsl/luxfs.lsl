# LuxOS - luxfs: souborove operace libc, ktere lux-alpm potrebuje a moduly luxos_sys/luxos_glib nemaji
# (lstat s vlastnikem, flock, symlink, kopie s casy jako shutil.copy2). Jen x86_64 glibc.
load glib

O_RDONLY = 0
O_WRONLY = 1
O_CREAT = 64
O_TRUNC = 512
O_APPEND = 1024
O_CLOEXEC = 524288
S_IFMT = 61440
S_IFDIR = 16384
S_IFLNK = 40960

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

function u32(value):
    if value < 0:
        return value + 4294967296
    end
    return value
end

# struct stat x86_64: st_mode +24 (u32), st_uid +28 (u32), st_size +48, st_atim +72, st_mtim +88
function stat_fields(base):
    unsafe:
        return {"mode": u32(__lsl_qbe_s32(__lsl_qbe_load32(base + 24))),
                "uid": u32(__lsl_qbe_s32(__lsl_qbe_load32(base + 28))),
                "size": __lsl_qbe_load64(base + 48),
                "atime": [__lsl_qbe_load64(base + 72), __lsl_qbe_load64(base + 80)],
                "mtime": [__lsl_qbe_load64(base + 88), __lsl_qbe_load64(base + 96)]}
    end
end

# lstat: slovnik (mode, uid, size, atime, mtime) nebo None
function lstat(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("lstat"), cstr(path), data(buffer))) != 0:
            return None
        end
        return stat_fields(data(buffer))
    end
end

function stat(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(buffer))) != 0:
            return None
        end
        return stat_fields(data(buffer))
    end
end

function is_dir_mode(st):
    return st != None and st["mode"] & S_IFMT == S_IFDIR
end

function is_link_mode(st):
    return st != None and st["mode"] & S_IFMT == S_IFLNK
end

function is_file(path):
    st = stat(path)
    return st != None and st["mode"] & S_IFMT == 32768
end

# mtime v ns (0 = neexistuje)
function mtime_ns(path):
    st = stat(path)
    if st == None:
        return 0
    end
    return st["mtime"][0] * 1000000000 + st["mtime"][1]
end

# 0 = vytvoreno, jinak errno (17 = EEXIST)
function mkdir(path, mode):
    unsafe:
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(path), ptr(mode))) == 0:
            return 0
        end
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_call0(__lsl_symbol("__errno_location"))))
    end
end

function open(path, flags, mode):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("open"), cstr(path), ptr(flags), ptr(mode)))
    end
end

function close(fd):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("close"), ptr(fd))
    end
    return 0
end

# Vyhradni zamek bez cekani: True = ziskan
function flock_nb(fd):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("flock"), ptr(fd), 6)) == 0
    end
end

function symlink(target, path):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("symlink"), cstr(target), cstr(path))) == 0
    end
end

function unlink(path):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("unlink"), cstr(path))) == 0
    end
end

function geteuid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("geteuid")))
    end
end

function getuid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("getuid")))
    end
end

# monotonicky cas v ms
function monotonic_ms():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_get_monotonic_time")) // 1000
    end
end

function sleep_ms(ms):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_usleep"), ptr(ms * 1000))
    end
    return 0
end

# Kopie obsahu, prav a casu (shutil.copy2); False pri chybe
function copy2(source, target):
    st = stat(source)
    if st == None:
        return False
    end
    src = open(source, O_RDONLY + O_CLOEXEC, 0)
    if src < 0:
        return False
    end
    dst = open(target, O_WRONLY + O_CREAT + O_TRUNC + O_CLOEXEC, 384)
    if dst < 0:
        call close(src)
        return False
    end
    ok = True
    left = st["size"]
    unsafe:
        while left > 0:
            n = __lsl_qbe_call4(__lsl_symbol("sendfile"), ptr(dst), ptr(src), 0, ptr(left))
            if n <= 0:
                ok = False
                break
            end
            left -= n
        end
        if ok:
            call __lsl_qbe_call2(__lsl_symbol("fchmod"), ptr(dst), ptr(st["mode"] & 4095))
            times = __lsl_byte_zeros(32)
            base = data(times)
            call __lsl_qbe_store64(base, ptr(st["atime"][0]))
            call __lsl_qbe_store64(base + 8, ptr(st["atime"][1]))
            call __lsl_qbe_store64(base + 16, ptr(st["mtime"][0]))
            call __lsl_qbe_store64(base + 24, ptr(st["mtime"][1]))
            call __lsl_qbe_call2(__lsl_symbol("futimens"), ptr(dst), base)
        end
    end
    call close(src)
    call close(dst)
    return ok
end

# uname().machine (struct utsname: 6 poli po 65 bajtech, machine je paty)
function machine():
    unsafe:
        buffer = __lsl_byte_zeros(390)
        if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("uname"), data(buffer))) != 0:
            return ""
        end
        return glib.from_c(data(buffer) + 260)
    end
end
