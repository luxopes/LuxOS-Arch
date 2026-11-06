# lsl: internal-abi
# LuxOS firewall - tenke vazby na libc (cil linux-x86_64-gnu): uid, prava souboru, prejmenovani,
# cteni /dev/kmsg (zaznamy jadra se zahozenymi spojenimi) s cekanim poll().
#
# Pravidla uvnitr modulu (viz lsl man gtk): argumenty jsou zabalene, pred predanim do C je rozbali ptr();
# text z C se kopiruje pres __lsl_text_from_bytes; ByteArray drzi pamet po dobu volani C.

EAGAIN = 11
EINTR = 4
EPIPE = 32

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

function errno():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_call0(__lsl_symbol("__errno_location"))))
    end
end

function chmod(path, mode):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("chmod"), cstr(path), ptr(mode))) == 0
    end
end

function rename(source, target):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("rename"), cstr(source), cstr(target))) == 0
    end
end

function unlink(path):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("unlink"), cstr(path))) == 0
    end
end

# Adresar s pravy mode (rodic musi existovat); True kdyz na konci existuje
function mkdir(path, mode):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(path), ptr(mode))
        buffer = __lsl_byte_zeros(256)
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(buffer))) == 0
    end
end

# /dev/kmsg bez blokovani, pozice na konci (stare zaznamy se nectou); -1 pri chybe
function open_kmsg(path):
    unsafe:
        # O_RDONLY | O_NONBLOCK | O_CLOEXEC = 0 | 2048 | 524288
        fd = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("open"), cstr(path), 526336))
        if fd < 0:
            return -1
        end
        # SEEK_END = 2
        call __lsl_qbe_call3(__lsl_symbol("lseek"), fd, 0, 2)
        return fd
    end
end

# Jeden zaznam: text, "" (zaznamy prepsane - pokracovat), None (zatim nic dalsiho)
function read_record(fd):
    unsafe:
        buffer = __lsl_byte_zeros(8192)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("read"), ptr(fd), data(buffer), 8192))
        if n < 0:
            code = errno()
            if code == EPIPE or code == EINTR:
                return ""
            end
            return None
        end
        if n == 0:
            return None
        end
        return __lsl_text_from_bytes(buffer, 0, n)
    end
end

# Ceka na data nejvys ms milisekund; True kdyz jde cist
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

# Spanek bez procesoru (kdyz /dev/kmsg nejde otevrit)
function sleep_ms(ms):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("poll"), 0, 0, ptr(ms))
        return 0
    end
end

# Nahradi proces programem (execv s celou cestou); vraci jen pri chybe
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
        call __lsl_qbe_call2(__lsl_symbol("execv"), __lsl_qbe_load64(base), base)
        return 127
    end
end

function isatty(fd):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("isatty"), ptr(fd))) == 1
    end
end
