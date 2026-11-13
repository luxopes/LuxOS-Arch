# lsl: internal-abi
# lsl: link libglib-2.0.so.0
# Lux Guard - tenke vazby na libc (cil linux-x86_64-gnu) pro luxos-guard-agent: socket UNIX podle cesty,
# cteni celych radku (MSG_PEEK, zadny rozdeleny znak UTF-8), spousteni pomocnika (posix_spawn s jednou
# promennou prostredi navic), sber skoncenych procesu, razitko souboru, SHA-256 zacatku souboru (GLib).
#
# Pravidla uvnitr modulu (viz lsl man gtk): argumenty jsou zabalene, pred predanim do C je rozbali ptr();
# text z C se kopiruje pres __lsl_text_from_bytes; ByteArray drzi pamet po dobu volani C.

EAGAIN = 11
EINTR = 4

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

function getuid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("getuid")))
    end
end

function getppid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("getppid")))
    end
end

function errno():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_call0(__lsl_symbol("__errno_location"))))
    end
end

# Milisekundy CLOCK_MONOTONIC (1)
function monotonic_ms():
    unsafe:
        ts = __lsl_byte_zeros(16)
        call __lsl_qbe_call2(__lsl_symbol("clock_gettime"), 1, data(ts))
        return __lsl_qbe_load64(data(ts)) * 1000 + __lsl_qbe_load64(data(ts) + 8) // 1000000
    end
end

# Spojeni se socketem UNIX podle cesty (AF_UNIX 1, SOCK_STREAM | SOCK_CLOEXEC); popisovac nebo -1
function unix_connect(path):
    unsafe:
        length = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(path))
        if length == 0 or length > 107:
            return -1
        end
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("socket"), 1, 524289, 0))
        if fd < 0:
            return -1
        end
        address = __lsl_byte_zeros(112)
        base = data(address)
        call __lsl_qbe_store32(base, 1)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + 2, cstr(path), length)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("connect"), fd, base, 2 + length + 1)) != 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            return -1
        end
        return fd
    end
end

function close(fd):
    unsafe:
        if ptr(fd) >= 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), ptr(fd))
        end
        return 0
    end
end

# Posle cely text (MSG_NOSIGNAL: bez SIGPIPE); False kdyz protistrana odesla
function send_text(fd, message):
    unsafe:
        total = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(message))
        sent = 0
        tries = 0
        while sent < total:
            n = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("send"), ptr(fd), cstr(message) + sent, total - sent, 16384))
            if n < 0:
                code = errno()
                tries += 1
                if (code == EINTR or code == EAGAIN) and tries < 200:
                    call __lsl_qbe_call3(__lsl_symbol("poll"), 0, 0, 5)
                    continue
                end
                return False
            end
            sent += n
        end
        return True
    end
end

# Cele radky ze socketu: [stav, text]. Stav 1 = text s jednim nebo vice radky (vcetne posledniho "\n"),
# 2 = zatim jen cast radku (nic se neprecetlo), 0 = konec spojeni, -1 = zatim nic / chyba.
# Prilis dlouhy radek (bez "\n" v 64 KiB) se zahodi az do dalsiho "\n" (stav 3).
function read_lines(fd):
    unsafe:
        size = 65536
        buffer = __lsl_byte_zeros(size)
        # MSG_PEEK 2 | MSG_DONTWAIT 64
        n = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("recv"), ptr(fd), data(buffer), size, 66))
        if n == 0:
            return [0, ""]
        end
        if n < 0:
            return [-1, ""]
        end
        last = __lsl_qbe_call3(__lsl_symbol("memrchr"), data(buffer), 10, n)
        if last == 0:
            if n == size:
                call __lsl_qbe_call4(__lsl_symbol("recv"), ptr(fd), data(buffer), size, 64)
                return [3, ""]
            end
            return [2, ""]
        end
        take = last - data(buffer) + 1
        got = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("recv"), ptr(fd), data(buffer), take, 64))
        if got <= 0:
            return [-1, ""]
        end
        return [1, __lsl_text_from_bytes(buffer, 0, got)]
    end
end

# Ceka na data nejvys ms milisekund; fd < 0 = jen spanek. True kdyz jde cist (nebo spojeni skoncilo)
function wait_readable(fd, ms):
    unsafe:
        if ptr(fd) < 0:
            call __lsl_qbe_call3(__lsl_symbol("poll"), 0, 0, ptr(ms))
            return False
        end
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_store32(data(cell), ptr(fd))
        # struct pollfd {int fd; short events; short revents}; POLLIN 1
        call __lsl_qbe_store32(data(cell) + 4, 1)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("poll"), data(cell), 1, ptr(ms)))
        return n > 0
    end
end

# Pole char* zakoncene NULL; polozky (String) musi zit po dobu volani
function cstr_array(items):
    unsafe:
        count = len(items)
        bytes = __lsl_byte_zeros((count + 1) * 8)
        base = data(bytes)
        index = 0
        while index < count:
            call __lsl_qbe_store64(base + index * 8, cstr(items[index]))
            index += 1
        end
        return bytes
    end
end

# Spusti program (cela cesta v argv[0]) s promennou prostredi name=value navic; pid nebo -1
function spawn(argv, name, value):
    unsafe:
        array = cstr_array(argv)
        if name != "":
            call __lsl_qbe_call3(__lsl_symbol("setenv"), cstr(name), cstr(value), 1)
        end
        cell = __lsl_byte_zeros(8)
        # kopie prostredi vcetne promenne vyse (GLib; adresa promenne environ z LSL neni dostupna)
        environ = __lsl_qbe_call0(__lsl_symbol("g_get_environ"))
        rc = __lsl_qbe_s32(__lsl_qbe_call6(__lsl_symbol("posix_spawn"), data(cell), cstr(argv[0]), 0, 0, data(array), environ))
        call __lsl_qbe_call1(__lsl_symbol("g_strfreev"), environ)
        if name != "":
            call __lsl_qbe_call1(__lsl_symbol("unsetenv"), cstr(name))
        end
        if rc != 0:
            return -1
        end
        return __lsl_qbe_s32(__lsl_qbe_load32(data(cell)))
    end
end

# Jeden skonceny potomek bez cekani: [pid, kod] (kod: navratovy kod, -1 = ukoncen signalem), [0, 0] = zadny
function reap():
    unsafe:
        cell = __lsl_byte_zeros(8)
        # WNOHANG 1
        pid = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("waitpid"), -1, data(cell), 1))
        if pid <= 0:
            return [0, 0]
        end
        status = __lsl_qbe_s32(__lsl_qbe_load32(data(cell)))
        if (status & 127) != 0:
            return [pid, -1]
        end
        return [pid, (status >> 8) & 255]
    end
end

function kill(pid, signal):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("kill"), ptr(pid), ptr(signal)))
    end
end

# Cil symbolickeho odkazu ("" pri chybe)
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

# Razitko souboru "inode:mtime_ns" ("" kdyz soubor neni): nahrazeni balikem (novy inode) i prepsani
function stamp(path):
    unsafe:
        st = __lsl_byte_zeros(256)
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(st))) != 0:
            return ""
        end
        # struct stat (x86_64): st_ino 8, st_mtim 88 (tv_sec) + 96 (tv_nsec)
        ino = __lsl_qbe_load64(data(st) + 8)
        mtime = __lsl_qbe_load64(data(st) + 88) * 1000000000 + __lsl_qbe_load64(data(st) + 96)
        return String(ino) + ":" + String(mtime)
    end
end

# SHA-256 (hex) prvnich limit bajtu souboru; "" kdyz soubor nejde cist
function sha256_head(path, limit):
    unsafe:
        # O_RDONLY | O_CLOEXEC
        fd = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("open"), cstr(path), 524288))
        if fd < 0:
            return ""
        end
        # G_CHECKSUM_SHA256 = 2
        sum = __lsl_qbe_call1(__lsl_symbol("g_checksum_new"), 2)
        chunk = 65536
        buffer = __lsl_byte_zeros(chunk)
        left = ptr(limit)
        ok = True
        while left > 0:
            want = chunk
            if left < want:
                want = left
            end
            n = __lsl_qbe_call3(__lsl_symbol("read"), fd, data(buffer), want)
            if n < 0:
                if errno() == EINTR:
                    continue
                end
                ok = False
                break
            end
            if n == 0:
                break
            end
            call __lsl_qbe_call3(__lsl_symbol("g_checksum_update"), sum, data(buffer), n)
            left -= n
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), fd)
        result = ""
        if ok:
            hex = __lsl_qbe_call1(__lsl_symbol("g_checksum_get_string"), sum)
            length = __lsl_qbe_call1(__lsl_symbol("strlen"), hex)
            out = __lsl_byte_zeros(length)
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), data(out), hex, length)
            result = __lsl_text_from_bytes(out, 0, length)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_checksum_free"), sum)
        return result
    end
end

# Nahradi proces programem (execv s celou cestou); vraci jen pri chybe
function exec(argv):
    unsafe:
        array = cstr_array(argv)
        call __lsl_qbe_call2(__lsl_symbol("execv"), cstr(argv[0]), data(array))
        return 127
    end
end

# Radek na stderr
function eprint(text):
    unsafe:
        line = text + "\n"
        call __lsl_qbe_call3(__lsl_symbol("write"), 2, cstr(line), __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(line)))
        return 0
    end
end
