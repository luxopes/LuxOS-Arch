# lsl: internal-abi
# lsl: link libglib-2.0.so.0
# Posta LuxOS - nizkourovnove operace nad ByteArray, ktere LSL 0.10.8 nema (nebo jsou pomale):
#   find(b, jehla, od)            memmem; jehla je ByteArray nebo String (ASCII)
#   find_byte(b, bajt, od, do)    memchr
#   sub(b, od, do)                kopie useku (memcpy, rychlejsi nez b[od:do])
#   concat(a, b), join(list)      spojeni ByteArray
#   convert(b, od, do, charset)   prevod znakove sady do UTF-8 pres GLib (iconv); False pri chybe
#   res_query(jmeno, typ)         odpoved DNS (libc res_query) jako ByteArray; prazdny pri chybe
#   recv(fd, max)                 cteni z neblokujiciho popisovace: ByteArray (prazdny = konec), False = zatim nic
#   send(fd, data)                zapis vseho (MSG_NOSIGNAL); False pri chybe
# Pozor: v internal-abi modulu nevracet None (volajici dostane surovou 0) - chyba = False / "".

function data(bytes):
    unsafe:
        return __lsl_qbe_load64(__lsl_address(bytes) + 24)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function needle_ptr(needle):
    unsafe:
        if type(needle) == "String":
            return __lsl_address(needle) + 16
        end
        return __lsl_qbe_load64(__lsl_address(needle) + 24)
    end
end

function needle_len(needle):
    unsafe:
        if type(needle) == "String":
            return __lsl_text_byte_length(needle)
        end
        return len(needle)
    end
end

# Pozice prvniho vyskytu jehly od `start`, -1 kdyz neni
function find(hay, needle, start0):
    unsafe:
        start = __lsl_unbox_int(start0)
        n = needle_len(needle)
        h = len(hay)
        if start < 0:
            start = 0
        end
        if n == 0 or start + n > h:
            return -1
        end
        base = __lsl_qbe_load64(__lsl_address(hay) + 24)
        p = __lsl_qbe_call4(__lsl_symbol("memmem"), base + start, h - start, needle_ptr(needle), n)
        if p == 0:
            return -1
        end
        return p - base
    end
end

# Pozice bajtu v useku [start, stop), -1 kdyz neni
function find_byte(hay, value0, start0, stop0):
    unsafe:
        value = __lsl_unbox_int(value0)
        start = __lsl_unbox_int(start0)
        stop = __lsl_unbox_int(stop0)
        if stop > len(hay):
            stop = len(hay)
        end
        if start < 0:
            start = 0
        end
        if start >= stop:
            return -1
        end
        base = __lsl_qbe_load64(__lsl_address(hay) + 24)
        p = __lsl_qbe_call3(__lsl_symbol("memchr"), base + start, value, stop - start)
        if p == 0:
            return -1
        end
        return p - base
    end
end

function sub(bytes, start0, stop0):
    unsafe:
        start = __lsl_unbox_int(start0)
        stop = __lsl_unbox_int(stop0)
        if stop > len(bytes):
            stop = len(bytes)
        end
        if start < 0:
            start = 0
        end
        if stop <= start:
            return __lsl_byte_zeros(0)
        end
        out = __lsl_byte_zeros(stop - start)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), __lsl_qbe_load64(__lsl_address(out) + 24), __lsl_qbe_load64(__lsl_address(bytes) + 24) + start, stop - start)
        return out
    end
end

function concat(a, b):
    unsafe:
        na = len(a)
        nb = len(b)
        out = __lsl_byte_zeros(na + nb)
        base = __lsl_qbe_load64(__lsl_address(out) + 24)
        if na > 0:
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), base, __lsl_qbe_load64(__lsl_address(a) + 24), na)
        end
        if nb > 0:
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + na, __lsl_qbe_load64(__lsl_address(b) + 24), nb)
        end
        return out
    end
end

function join(items):
    unsafe:
        total = 0
        for item in items:
            total += len(item)
        end
        out = __lsl_byte_zeros(total)
        base = __lsl_qbe_load64(__lsl_address(out) + 24)
        offset = 0
        for item in items:
            n = len(item)
            if n > 0:
                call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + offset, __lsl_qbe_load64(__lsl_address(item) + 24), n)
            end
            offset += n
        end
        return out
    end
end

# Text v libovolne znakove sade -> String (UTF-8); neprevoditelne znaky "?"; False kdyz sadu iconv nezna
function convert(bytes, start0, stop0, charset):
    unsafe:
        start = __lsl_unbox_int(start0)
        stop = __lsl_unbox_int(stop0)
        if stop > len(bytes):
            stop = len(bytes)
        end
        if stop <= start:
            return ""
        end
        cell = __lsl_byte_zeros(16)
        cbase = __lsl_qbe_load64(__lsl_address(cell) + 24)
        src = __lsl_qbe_load64(__lsl_address(bytes) + 24) + start
        out = __lsl_qbe_call8(__lsl_symbol("g_convert_with_fallback"), src, stop - start, cstr("UTF-8"), cstr(charset), cstr("?"), 0, cbase, cbase + 8)
        if out == 0:
            err = __lsl_qbe_load64(cbase + 8)
            if err != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), err)
            end
            return False
        end
        n = __lsl_qbe_load64(cbase)
        res = __lsl_byte_zeros(n)
        if n > 0:
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), __lsl_qbe_load64(__lsl_address(res) + 24), out, n)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_free"), out)
        return __lsl_text_from_bytes(res, 0, n)
    end
end

# DNS dotaz (trida IN): surova odpoved, prazdny ByteArray pri chybe/neexistujicim jmenu
function res_query(name, kind0):
    unsafe:
        kind = __lsl_unbox_int(kind0)
        buffer = __lsl_byte_zeros(8192)
        n = __lsl_qbe_s32(__lsl_qbe_call5(__lsl_symbol("res_query"), cstr(name), 1, kind, __lsl_qbe_load64(__lsl_address(buffer) + 24), 8192))
        if n <= 0:
            return __lsl_byte_zeros(0)
        end
        if n > 8192:
            n = 8192
        end
        return sub(buffer, 0, n)
    end
end

function errno():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_load32(__lsl_qbe_call0(__lsl_symbol("__errno_location"))))
    end
end

# Cteni z neblokujiciho popisovace (socket UNIX): data, prazdny ByteArray = konec spojeni, False = nic/EAGAIN
function recv(fd0, maximum0):
    unsafe:
        fd = __lsl_unbox_int(fd0)
        maximum = __lsl_unbox_int(maximum0)
        buffer = __lsl_byte_zeros(maximum)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("read"), fd, __lsl_qbe_load64(__lsl_address(buffer) + 24), maximum))
        if n < 0:
            code = errno()
            # EAGAIN 11, EINTR 4: zatim nic; jina chyba = konec spojeni
            if code == 11 or code == 4:
                return False
            end
            return __lsl_byte_zeros(0)
        end
        return sub(buffer, 0, n)
    end
end

# Zapise vsechna data (String nebo ByteArray); kratke cekani pri plnem bufferu; False pri chybe
function send(fd0, payload):
    unsafe:
        fd = __lsl_unbox_int(fd0)
        total = needle_len(payload)
        base = needle_ptr(payload)
        sent = 0
        tries = 0
        while sent < total:
            n = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("send"), fd, base + sent, total - sent, 16384))
            if n < 0:
                code = errno()
                tries += 1
                if (code == 4 or code == 11) and tries < 2000:
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

# Prava souboru (chmod), napr. 0o600 pro mezipamet posty
function chmod(path, mode0):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("chmod"), cstr(path), __lsl_unbox_int(mode0))) == 0
    end
end

function getuid():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("getuid")))
    end
end

# Monotonni cas v ms (mereni spusteni okna)
function monotonic_ms():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_get_monotonic_time")) // 1000
    end
end
