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
