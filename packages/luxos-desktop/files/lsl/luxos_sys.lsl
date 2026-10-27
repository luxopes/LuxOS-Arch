# lsl: internal-abi
# LuxOS - tenke vazby na libc pro programy v LSL (cil linux-x86_64-gnu; libc.so.6 je vzdy linkovana).
# Modul gtk/glib LSL 0.10.4 tyto funkce nema; az je bude mit standardni knihovna, tento modul zmizi.
#
#   strftime_local(format)   mistni cas ve formatu strftime, nazvy dnu/mesicu podle LANG (jako bash printf %()T)
#   tsv_lookup(text, key)    hodnota radku "key<TAB>hodnota" v textu (memmem, ~10 us na 160 kB), "" kdyz chybi
#   kill(pid, signal)        signal procesu; 0 = odeslano, -1 = chyba (proces nebezi)
#   exec(argv)               nahradi proces programem (execvp, hledani v PATH); vraci jen pri chybe
#   list_dir(path)           serazena jmena polozek adresare ([] kdyz adresar neni)
#   eprint(text)             radek na stderr
#
# Pravidla uvnitr modulu (viz lsl man gtk): argumenty jsou zabalene, pred predanim do C je rozbali ptr();
# text z C se kopiruje pres bytes(); ByteArray drzi pamet po dobu volani C.

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

# Adresa dat ByteArray
function data(bytes):
    unsafe:
        return __lsl_qbe_load64(__lsl_address(bytes) + 24)
    end
end

# String z `length` bajtu na adrese (kopie)
function text_at(address, length):
    unsafe:
        bytes = __lsl_byte_zeros(length)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), data(bytes), ptr(address), ptr(length))
        return __lsl_text_from_bytes(bytes, 0, length)
    end
end

function strftime_local(format):
    unsafe:
        # LC_ALL = 6: jazyk z prostredi (LANG/LC_TIME), jen jednou za proces
        call __lsl_qbe_call2(__lsl_symbol("setlocale"), 6, cstr(""))
        now = __lsl_byte_zeros(8)
        call __lsl_qbe_call1(__lsl_symbol("time"), data(now))
        tm = __lsl_byte_zeros(64)
        call __lsl_qbe_call2(__lsl_symbol("localtime_r"), data(now), data(tm))
        out = __lsl_byte_zeros(256)
        n = __lsl_qbe_call4(__lsl_symbol("strftime"), data(out), 256, cstr(format), data(tm))
        return __lsl_text_from_bytes(out, 0, n)
    end
end

function tsv_lookup(text, key):
    unsafe:
        needle = "\n" + key + "\t"
        hay = cstr(text)
        hay_len = __lsl_qbe_call1(__lsl_symbol("strlen"), hay)
        nd = cstr(needle)
        nd_len = __lsl_qbe_call1(__lsl_symbol("strlen"), nd)
        hit = __lsl_qbe_call4(__lsl_symbol("memmem"), hay, hay_len, nd, nd_len)
        if hit == 0:
            return ""
        end
        start = hit + nd_len
        stop = __lsl_qbe_call2(__lsl_symbol("strchr"), start, 10)
        if stop == 0:
            stop = hay + hay_len
        end
        return text_at(start, stop - start)
    end
end

function kill(pid, signal):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("kill"), ptr(pid), ptr(signal)))
    end
end

function exec(argv):
    unsafe:
        count = len(argv)
        bytes = __lsl_byte_zeros((count + 1) * 8)
        base = data(bytes)
        index = 0
        while index < count:
            call __lsl_qbe_store64(base + index * 8, cstr(argv[index]))
            index += 1
        end
        call __lsl_qbe_call2(__lsl_symbol("execvp"), __lsl_qbe_load64(base), base)
        return 127
    end
end

function list_dir(path):
    unsafe:
        names = []
        safe:
            names = __lsl_list_directory(path)
        end
        return sorted(names)
    end
end

function eprint(text):
    unsafe:
        line = text + "\n"
        call __lsl_qbe_call3(__lsl_symbol("write"), 2, cstr(line), __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(line)))
        return None
    end
end

# Text na stdout hned (bez vyrovnavaci pameti)
function out(text):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("write"), 1, cstr(text), __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(text)))
        return None
    end
end

# ---- soubory (libc; pro maly klient bez GLib) --------------------------------------------------------------

# Cesta existuje (i rozbity symbolicky odkaz, jako os.path.lexists)
function lexists(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        return __lsl_qbe_call2(__lsl_symbol("lstat"), cstr(path), data(buffer)) == 0
    end
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

# Adresar vcetne nadrazenych (mkdir -p, prava 0755); True kdyz na konci existuje
function mkdir_p(path):
    unsafe:
        current = ""
        for part in path.split("/"):
            if part == "":
                if current == "":
                    current = "/"
                end
                continue
            end
            if current == "/" or current == "":
                current = current + part
            else:
                current = current + "/" + part
            end
            call __lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(current), 493)
        end
        buffer = __lsl_byte_zeros(256)
        return __lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(buffer)) == 0
    end
end

function getuid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("getuid")))
    end
end

function errno():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_call0(__lsl_symbol("__errno_location"))))
    end
end

# Pracovni adresar procesu ("/" kdyz nejde zjistit)
function cwd():
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        if __lsl_qbe_call2(__lsl_symbol("getcwd"), data(buffer), 4096) == 0:
            return "/"
        end
        return text_at(data(buffer), __lsl_qbe_call1(__lsl_symbol("strlen"), data(buffer)))
    end
end

function setenv(name, value):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("setenv"), cstr(name), cstr(value), 1) == 0
    end
end

# ---- abstraktni sockety UNIX (klient luxos-screenshot <-> luxos-hub) -----------------------------------------
# Jmeno bez souboru (zadne zbytky po padu, bind je atomicky: obsazene jmeno = EADDRINUSE). Abstraktni
# jmena nemaji prava souboru: server proto overi uzivatele protistrany (peer_uid).

AF_UNIX = 1
SOCK_STREAM = 1
SOCK_CLOEXEC = 524288
SOCK_NONBLOCK = 2048
EADDRINUSE = 98
EAGAIN = 11
EINTR = 4

# [ByteArray sockaddr_un, delka] pro abstraktni jmeno (prvni bajt cesty 0)
function abstract_address(name):
    unsafe:
        length = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(name))
        if length > 100:
            length = 100
        end
        address = __lsl_byte_zeros(112)
        base = data(address)
        call __lsl_qbe_store32(base, 1)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + 3, cstr(name), length)
        return [address, 3 + length]
    end
end

# Spojeni se serverem; popisovac nebo -1 (nikdo neposloucha)
function unix_connect(name):
    unsafe:
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("socket"), 1, 524289, 0))
        if fd < 0:
            return -1
        end
        pair = abstract_address(name)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("connect"), fd, data(pair[0]), ptr(pair[1]))) != 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            return -1
        end
        return fd
    end
end

# Naslouchajici neblokujici socket; popisovac, -EADDRINUSE kdyz uz nekdo posloucha, jinak -1
function unix_listen(name):
    unsafe:
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("socket"), 1, 526337, 0))
        if fd < 0:
            return -1
        end
        pair = abstract_address(name)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("bind"), fd, data(pair[0]), ptr(pair[1]))) != 0:
            code = errno()
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            if code == EADDRINUSE:
                return -EADDRINUSE
            end
            return -1
        end
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("listen"), fd, 16)) != 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            return -1
        end
        return fd
    end
end

# Prijme spojeni (neblokujici popisovac) nebo -1
function unix_accept(fd):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("accept4"), ptr(fd), 0, 0, 526336))
    end
end

# UID procesu na druhe strane spojeni (SO_PEERCRED), -1 pri chybe
function peer_uid(fd):
    unsafe:
        cred = __lsl_byte_zeros(16)
        size = __lsl_byte_zeros(8)
        call __lsl_qbe_store32(data(size), 12)
        # SOL_SOCKET 1, SO_PEERCRED 17; struct ucred {pid, uid, gid}
        if __lsl_qbe_s32(__lsl_qbe_call5(__lsl_symbol("getsockopt"), ptr(fd), 1, 17, data(cred), data(size))) != 0:
            return -1
        end
        return __lsl_qbe_s32(__lsl_qbe_load32(data(cred) + 4))
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

# Precte dostupna data: [pocet bajtu (0 = konec spojeni, < 0 = zatim nic nebo chyba), text]
function recv_text(fd):
    unsafe:
        buffer = __lsl_byte_zeros(65536)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("read"), ptr(fd), data(buffer), 65536))
        if n <= 0:
            if n < 0 and errno() == EINTR:
                return [-1, ""]
            end
            return [n, ""]
        end
        return [n, __lsl_text_from_bytes(buffer, 0, n)]
    end
end

# Ceka na data nejvys ms milisekund (-1 bez limitu); True kdyz jde cist (nebo spojeni skoncilo)
function wait_readable(fd, ms):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_store32(data(cell), ptr(fd))
        # struct pollfd {int fd; short events; short revents}; POLLIN 1
        call __lsl_qbe_store32(data(cell) + 4, 1)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("poll"), data(cell), 1, ptr(ms)))
        return n > 0
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
